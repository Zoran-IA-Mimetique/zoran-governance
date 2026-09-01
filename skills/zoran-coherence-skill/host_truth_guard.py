from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from tolerance_skill import Decision


ENVELOPE_SCHEMA = "zoran.robot-signed-envelope.v1"
TRUTH_SCHEMA = "zoran.truth-attestation.v1"
ANCHOR_PATH = Path(__file__).resolve().parent / "references" / "robot-trust-anchors.json"
AUTHORITY_ID = "zoran-deterministic-evaluator-v1"
SHA_RE = re.compile(r"[0-9a-f]{64}")
CONTROL_IDS = (
    "intrinsic_coherence",
    "wikimedia_first_pass",
    "source_authenticity",
    "citation_entailment",
    "epistemic_status",
    "semantic_clause_coverage",
    "semantic_roundtrip",
    "phenomenal_measurement_authenticity",
    "contradiction_search_scope",
)


class TruthAttestationError(ValueError):
    pass


@dataclass(frozen=True)
class HostTruthRequest:
    mission_sha256: str
    source_text: str
    output_text: str
    claim_receipt_sha256: str
    semantic_receipt_sha256: str
    phenomenal_resource_receipt_sha256: str
    phenomenal_receipt_sha256: str
    source_authority_receipts_sha256: str
    certificate: Mapping[str, object] | None
    observed_at: str


@dataclass(frozen=True)
class HostTruthEvaluation:
    decision: Decision
    state: str
    reasons: tuple[str, ...]
    certificate_sha256: str | None
    receipt_sha256: str


def canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise TruthAttestationError("TRUTH_ATTESTATION_NOT_CANONICAL") from exc


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise TruthAttestationError("TRUTH_TIMEZONE_REQUIRED")
    return parsed.astimezone(timezone.utc)


def trusted_evaluator_anchor() -> dict[str, str]:
    try:
        anchors = json.loads(ANCHOR_PATH.read_text(encoding="utf-8"))
        anchor = anchors["evaluator"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise TruthAttestationError("TRUTH_TRUST_ANCHOR_UNAVAILABLE") from exc
    expected = {"authority_id", "fingerprint_sha256", "public_key_hex"}
    if anchors.get("schema") != "zoran.robot-trust-anchors.v1" or set(anchor) != expected or anchor.get("authority_id") != AUTHORITY_ID:
        raise TruthAttestationError("TRUTH_TRUST_ANCHOR_SCHEMA_INVALID")
    try:
        raw = bytes.fromhex(anchor["public_key_hex"])
    except (TypeError, ValueError) as exc:
        raise TruthAttestationError("TRUTH_TRUST_PUBLIC_KEY_INVALID") from exc
    if len(raw) != 32 or _sha(raw) != anchor["fingerprint_sha256"]:
        raise TruthAttestationError("TRUTH_TRUST_FINGERPRINT_INVALID")
    return anchor


def verify_truth_certificate(envelope: Mapping[str, object], request: HostTruthRequest) -> tuple[dict, str]:
    value = dict(envelope)
    required = {"schema", "authority_id", "authority_fingerprint", "public_key_hex", "payload", "signature_base64", "envelope_sha256"}
    if set(value) != required or value.get("schema") != ENVELOPE_SCHEMA:
        raise TruthAttestationError("TRUTH_ENVELOPE_SCHEMA_INVALID")
    anchor = trusted_evaluator_anchor()
    if value.get("authority_id") != anchor["authority_id"] or value.get("authority_fingerprint") != anchor["fingerprint_sha256"] or value.get("public_key_hex") != anchor["public_key_hex"]:
        raise TruthAttestationError("TRUTH_AUTHORITY_UNTRUSTED")
    body = {key: value[key] for key in sorted(required - {"envelope_sha256"})}
    envelope_sha = _sha(canonical_bytes(body))
    if value.get("envelope_sha256") != envelope_sha:
        raise TruthAttestationError("TRUTH_ENVELOPE_SHA_INVALID")
    payload = value.get("payload")
    if not isinstance(payload, dict):
        raise TruthAttestationError("TRUTH_PAYLOAD_INVALID")
    try:
        signature = base64.b64decode(value["signature_base64"], validate=True)
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(anchor["public_key_hex"])).verify(signature, canonical_bytes(payload))
    except (InvalidSignature, ValueError, TypeError) as exc:
        raise TruthAttestationError("TRUTH_SIGNATURE_INVALID") from exc
    payload_keys = {
        "schema", "attestation_id", "mission_sha256", "source_text_sha256", "output_sha256",
        "claim_receipt_sha256", "semantic_receipt_sha256", "phenomenal_resource_receipt_sha256",
        "phenomenal_receipt_sha256", "source_authority_receipts_sha256", "controls", "scope",
        "issued_at", "expires_at",
    }
    if set(payload) != payload_keys or payload.get("schema") != TRUTH_SCHEMA:
        raise TruthAttestationError("TRUTH_PAYLOAD_SCHEMA_INVALID")
    expected = {
        "mission_sha256": request.mission_sha256,
        "source_text_sha256": _sha(request.source_text.encode("utf-8")),
        "output_sha256": _sha(request.output_text.encode("utf-8")),
        "claim_receipt_sha256": request.claim_receipt_sha256,
        "semantic_receipt_sha256": request.semantic_receipt_sha256,
        "phenomenal_resource_receipt_sha256": request.phenomenal_resource_receipt_sha256,
        "phenomenal_receipt_sha256": request.phenomenal_receipt_sha256,
        "source_authority_receipts_sha256": request.source_authority_receipts_sha256,
    }
    if any(not SHA_RE.fullmatch(value) for value in expected.values()) or any(payload.get(key) != value for key, value in expected.items()):
        raise TruthAttestationError("TRUTH_IDENTITY_MISMATCH")
    controls = payload.get("controls")
    if not isinstance(controls, dict) or tuple(sorted(controls)) != tuple(sorted(CONTROL_IDS)) or any(controls.get(control) != "PASS" for control in CONTROL_IDS):
        raise TruthAttestationError("TRUTH_CONTROL_NOT_PASS")
    scope = payload.get("scope")
    if not isinstance(scope, dict) or set(scope) != {"source_corpus", "measurement_domain", "limitations"} or not isinstance(scope.get("limitations"), list):
        raise TruthAttestationError("TRUTH_SCOPE_INVALID")
    observed = _time(request.observed_at); issued = _time(payload["issued_at"]); expires = _time(payload["expires_at"])
    if expires <= issued or expires - issued > timedelta(minutes=15) or observed < issued or observed > expires:
        raise TruthAttestationError("TRUTH_ATTESTATION_EXPIRED_OR_NOT_YET_VALID")
    return payload, envelope_sha


class HostTruthGuard:
    def evaluate(self, request: HostTruthRequest | None, *, trust_registry: object | None = None) -> HostTruthEvaluation:
        if trust_registry is not None:
            return self._finish(Decision.VETO, "REJECTED", ("CALLER_TRUTH_REGISTRY_FORBIDDEN",), None)
        if not isinstance(request, HostTruthRequest):
            return self._finish(Decision.RETRY, "GYROPHARE", ("HOST_TRUTH_ATTESTATION_MISSING",), None)
        if not isinstance(request.certificate, Mapping):
            return self._finish(Decision.RETRY, "GYROPHARE", ("HOST_TRUTH_ATTESTATION_MISSING",), None)
        try:
            _, certificate_sha = verify_truth_certificate(request.certificate, request)
        except TruthAttestationError as exc:
            return self._finish(Decision.VETO, "REJECTED", (str(exc),), None)
        return self._finish(Decision.PASS, "TRUTH_CONTROLS_AUTHENTICATED", ("PINNED_HOST_TRUTH_ATTESTATION_VALID",), certificate_sha)

    @staticmethod
    def _finish(decision: Decision, state: str, reasons: tuple[str, ...], certificate_sha: str | None) -> HostTruthEvaluation:
        body = {"component": "zoran.host-truth-guard", "version": "17.0.0", "decision": decision.value, "state": state, "reasons": list(reasons), "certificate_sha256": certificate_sha}
        return HostTruthEvaluation(decision, state, reasons, certificate_sha, _sha(canonical_bytes(body)))
