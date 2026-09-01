from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from tolerance_skill import Decision


ENVELOPE_SCHEMA = "zoran.robot-signed-envelope.v1"
SESSION_SCHEMA = "zoran.opaque-session-certificate.v1"
ANCHOR_PATH = Path(__file__).resolve().parent / "references" / "robot-trust-anchors.json"
SHA_RE = re.compile(r"[0-9a-f]{64}")
STAGE_ORDER = (
    "activation", "prompt_security", "pre_chat", "zmos_recall", "retrieval",
    "claim_evidence", "semantic_non_conflation", "frame_search", "proxy", "sources",
    "phenomenal_resources", "phenomenal_coherence", "host_truth", "laws", "action",
    "robot_handoff", "k3_post", "terminal",
)


class SessionCertificateError(ValueError):
    pass


@dataclass(frozen=True)
class HostSessionRequest:
    mission_sha256: str
    prompt_sha256: str
    output_text: str
    certificate: Mapping[str, object] | None
    observed_at: str


@dataclass(frozen=True)
class HostSessionEvaluation:
    decision: Decision
    state: str
    reasons: tuple[str, ...]
    certificate_sha256: str | None
    receipt_sha256: str


def canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise SessionCertificateError("SESSION_CERTIFICATE_NOT_CANONICAL") from exc


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise SessionCertificateError("SESSION_TIMEZONE_REQUIRED")
    return parsed.astimezone(timezone.utc)


def trusted_session_anchor() -> dict[str, str]:
    try:
        anchors = json.loads(ANCHOR_PATH.read_text(encoding="utf-8"))
        anchor = anchors["session"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise SessionCertificateError("SESSION_TRUST_ANCHOR_UNAVAILABLE") from exc
    expected = {"authority_id", "fingerprint_sha256", "public_key_hex"}
    if anchors.get("schema") != "zoran.robot-trust-anchors.v1" or set(anchor) != expected:
        raise SessionCertificateError("SESSION_TRUST_ANCHOR_SCHEMA_INVALID")
    try:
        public = bytes.fromhex(anchor["public_key_hex"])
    except (TypeError, ValueError) as exc:
        raise SessionCertificateError("SESSION_TRUST_PUBLIC_KEY_INVALID") from exc
    if len(public) != 32 or _sha(public) != anchor["fingerprint_sha256"]:
        raise SessionCertificateError("SESSION_TRUST_FINGERPRINT_INVALID")
    return anchor


def verify_session_certificate(envelope: Mapping[str, object], *, mission_sha256: str, prompt_sha256: str, output_sha256: str, observed_at: str) -> tuple[dict, str]:
    value = dict(envelope)
    required = {"schema", "authority_id", "authority_fingerprint", "public_key_hex", "payload", "signature_base64", "envelope_sha256"}
    if set(value) != required or value.get("schema") != ENVELOPE_SCHEMA:
        raise SessionCertificateError("SESSION_CERTIFICATE_ENVELOPE_SCHEMA_INVALID")
    anchor = trusted_session_anchor()
    if value.get("authority_id") != anchor["authority_id"] or value.get("authority_fingerprint") != anchor["fingerprint_sha256"] or value.get("public_key_hex") != anchor["public_key_hex"]:
        raise SessionCertificateError("SESSION_CERTIFICATE_AUTHORITY_UNTRUSTED")
    body = {key: value[key] for key in sorted(required - {"envelope_sha256"})}
    envelope_sha = _sha(canonical_bytes(body))
    if value.get("envelope_sha256") != envelope_sha:
        raise SessionCertificateError("SESSION_CERTIFICATE_ENVELOPE_SHA_INVALID")
    payload = value.get("payload")
    if not isinstance(payload, dict):
        raise SessionCertificateError("SESSION_CERTIFICATE_PAYLOAD_INVALID")
    try:
        signature = base64.b64decode(value["signature_base64"], validate=True)
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(anchor["public_key_hex"])).verify(signature, canonical_bytes(payload))
    except (InvalidSignature, ValueError, TypeError) as exc:
        raise SessionCertificateError("SESSION_CERTIFICATE_SIGNATURE_INVALID") from exc
    payload_keys = {
        "schema", "session_id", "mission_sha256", "prompt_sha256", "output_sha256",
        "issued_at", "expires_at", "stages", "chain_head", "terminal_status", "display_authorized",
    }
    if set(payload) != payload_keys or payload.get("schema") != SESSION_SCHEMA:
        raise SessionCertificateError("SESSION_CERTIFICATE_SCHEMA_INVALID")
    if payload.get("mission_sha256") != mission_sha256 or payload.get("prompt_sha256") != prompt_sha256 or payload.get("output_sha256") != output_sha256:
        raise SessionCertificateError("SESSION_CERTIFICATE_IDENTITY_MISMATCH")
    if payload.get("terminal_status") != "PASS" or payload.get("display_authorized") is not True:
        raise SessionCertificateError("SESSION_DISPLAY_NOT_AUTHORIZED")
    observed = _time(observed_at); issued = _time(payload["issued_at"]); expires = _time(payload["expires_at"])
    if observed < issued or observed > expires or expires <= issued:
        raise SessionCertificateError("SESSION_CERTIFICATE_EXPIRED_OR_NOT_YET_VALID")
    stages = payload.get("stages")
    if not isinstance(stages, list) or tuple(item.get("stage_id") for item in stages if isinstance(item, dict)) != STAGE_ORDER:
        raise SessionCertificateError("SESSION_STAGE_ORDER_INVALID")
    previous = "0" * 64
    for index, item in enumerate(stages):
        expected = {"index", "stage_id", "status", "receipt_sha256", "previous_event_hash", "event_hash"}
        if not isinstance(item, dict) or set(item) != expected or item.get("index") != index or item.get("status") != "PASS" or item.get("previous_event_hash") != previous or not SHA_RE.fullmatch(item.get("receipt_sha256", "")):
            raise SessionCertificateError("SESSION_STAGE_EVENT_INVALID")
        event = {key: item[key] for key in ("index", "stage_id", "status", "receipt_sha256", "previous_event_hash")}
        event_hash = _sha(canonical_bytes(event))
        if item.get("event_hash") != event_hash:
            raise SessionCertificateError("SESSION_STAGE_HASH_INVALID")
        previous = event_hash
    if payload.get("chain_head") != previous:
        raise SessionCertificateError("SESSION_CHAIN_HEAD_INVALID")
    return payload, envelope_sha


class HostSessionGuard:
    def evaluate(self, request: HostSessionRequest | None, *, trust_registry: object | None = None) -> HostSessionEvaluation:
        if trust_registry is not None:
            return self._finish(Decision.VETO, "REJECTED", ("CALLER_SESSION_TRUST_REGISTRY_FORBIDDEN",), None)
        if not isinstance(request, HostSessionRequest):
            return self._finish(Decision.RETRY, "CERTIFICATE_REQUIRED", ("HOST_SESSION_CERTIFICATE_MISSING",), None)
        if not SHA_RE.fullmatch(request.mission_sha256) or not SHA_RE.fullmatch(request.prompt_sha256) or not isinstance(request.output_text, str):
            return self._finish(Decision.RETRY, "IDENTITY_TRACE_PENDING", ("HOST_SESSION_IDENTITY_INVALID",), None)
        if not isinstance(request.certificate, Mapping):
            return self._finish(Decision.RETRY, "CERTIFICATE_REQUIRED", ("HOST_SESSION_CERTIFICATE_MISSING",), None)
        try:
            _, certificate_sha = verify_session_certificate(
                request.certificate, mission_sha256=request.mission_sha256,
                prompt_sha256=request.prompt_sha256, output_sha256=_sha(request.output_text.encode("utf-8")),
                observed_at=request.observed_at,
            )
        except SessionCertificateError as exc:
            return self._finish(Decision.VETO, "REJECTED", (str(exc),), None)
        return self._finish(Decision.PASS, "DISPLAY_AUTHORIZED", ("OPAQUE_SESSION_CHAIN_VALIDATED",), certificate_sha)

    @staticmethod
    def _finish(decision: Decision, state: str, reasons: tuple[str, ...], certificate_sha: str | None) -> HostSessionEvaluation:
        body = {"component": "zoran.host-session-guard", "version": "17.0.0", "decision": decision.value, "state": state, "reasons": list(reasons), "certificate_sha256": certificate_sha}
        return HostSessionEvaluation(decision, state, reasons, certificate_sha, _sha(canonical_bytes(body)))
