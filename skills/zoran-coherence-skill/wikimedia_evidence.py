from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Mapping
from urllib.parse import urlparse

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


ENVELOPE_SCHEMA = "zoran.robot-signed-envelope.v1"
WIKIMEDIA_SCHEMA = "zoran.wikimedia-evidence.v1"
ANCHOR_PATH = Path(__file__).resolve().parent / "references" / "robot-trust-anchors.json"
AUTHORITY_ID = "zoran-deterministic-evaluator-v1"
SHA_RE = re.compile(r"[0-9a-f]{64}")
PROJECT_HOSTS = {
    "wikipedia": "wikipedia.org",
    "wiktionary": "wiktionary.org",
    "wikiquote": "wikiquote.org",
    "wikidata": "wikidata.org",
}


class WikimediaEvidenceError(ValueError):
    pass


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise WikimediaEvidenceError("WIKIMEDIA_EVIDENCE_NOT_CANONICAL") from exc


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha_text(value: str) -> str:
    return _sha_bytes(value.encode("utf-8"))


def _time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise WikimediaEvidenceError("WIKIMEDIA_TIMEZONE_REQUIRED")
    return parsed.astimezone(timezone.utc)


def _anchor() -> dict[str, str]:
    try:
        anchors = json.loads(ANCHOR_PATH.read_text(encoding="utf-8"))
        anchor = anchors["evaluator"]
        public = bytes.fromhex(anchor["public_key_hex"])
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise WikimediaEvidenceError("WIKIMEDIA_TRUST_ANCHOR_UNAVAILABLE") from exc
    if (
        anchors.get("schema") != "zoran.robot-trust-anchors.v1"
        or set(anchor) != {"authority_id", "fingerprint_sha256", "public_key_hex"}
        or anchor.get("authority_id") != AUTHORITY_ID
        or len(public) != 32
        or _sha_bytes(public) != anchor.get("fingerprint_sha256")
    ):
        raise WikimediaEvidenceError("WIKIMEDIA_TRUST_ANCHOR_INVALID")
    return anchor


def verify_wikimedia_certificate(envelope: Mapping[str, object], *, claim_text: str, span: object, as_of: datetime) -> str:
    value = dict(envelope)
    keys = {"schema", "authority_id", "authority_fingerprint", "public_key_hex", "payload", "signature_base64", "envelope_sha256"}
    if set(value) != keys or value.get("schema") != ENVELOPE_SCHEMA:
        raise WikimediaEvidenceError("WIKIMEDIA_ENVELOPE_SCHEMA_INVALID")
    anchor = _anchor()
    if (
        value.get("authority_id") != anchor["authority_id"]
        or value.get("authority_fingerprint") != anchor["fingerprint_sha256"]
        or value.get("public_key_hex") != anchor["public_key_hex"]
    ):
        raise WikimediaEvidenceError("WIKIMEDIA_AUTHORITY_UNTRUSTED")
    body = {key: value[key] for key in sorted(keys - {"envelope_sha256"})}
    envelope_sha = _sha_bytes(_canonical_bytes(body))
    if value.get("envelope_sha256") != envelope_sha:
        raise WikimediaEvidenceError("WIKIMEDIA_ENVELOPE_SHA_INVALID")
    payload = value.get("payload")
    if not isinstance(payload, dict):
        raise WikimediaEvidenceError("WIKIMEDIA_PAYLOAD_INVALID")
    try:
        signature = base64.b64decode(value["signature_base64"], validate=True)
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(anchor["public_key_hex"])).verify(signature, _canonical_bytes(payload))
    except (InvalidSignature, TypeError, ValueError) as exc:
        raise WikimediaEvidenceError("WIKIMEDIA_SIGNATURE_INVALID") from exc
    payload_keys = {
        "schema", "lookup_id", "claim_sha256", "query", "project", "language", "api_endpoint",
        "page_id", "page_title", "revision_id", "retrieved_at", "source_sha256", "quote_sha256",
        "response_sha256", "relation",
    }
    if set(payload) != payload_keys or payload.get("schema") != WIKIMEDIA_SCHEMA:
        raise WikimediaEvidenceError("WIKIMEDIA_PAYLOAD_SCHEMA_INVALID")
    project = payload.get("project")
    language = payload.get("language")
    if project not in PROJECT_HOSTS or not isinstance(language, str) or not re.fullmatch(r"[a-z-]{2,12}", language):
        raise WikimediaEvidenceError("WIKIMEDIA_PROJECT_INVALID")
    endpoint = urlparse(str(payload.get("api_endpoint", "")))
    expected_host = PROJECT_HOSTS[project] if project == "wikidata" else f"{language}.{PROJECT_HOSTS[project]}"
    if endpoint.scheme != "https" or endpoint.hostname != expected_host or endpoint.path != "/w/api.php":
        raise WikimediaEvidenceError("WIKIMEDIA_ENDPOINT_INVALID")
    expected = {
        "claim_sha256": _sha_text(claim_text),
        "source_sha256": getattr(span, "source_sha256", None),
        "quote_sha256": getattr(span, "quote_sha256", None),
        "relation": getattr(getattr(span, "relation", None), "value", None),
        "retrieved_at": getattr(span, "observed_at", None),
    }
    if any(not SHA_RE.fullmatch(str(item)) for item in (payload.get("claim_sha256"), payload.get("source_sha256"), payload.get("quote_sha256"), payload.get("response_sha256"))):
        raise WikimediaEvidenceError("WIKIMEDIA_DIGEST_INVALID")
    if any(payload.get(key) != expected_value for key, expected_value in expected.items()):
        raise WikimediaEvidenceError("WIKIMEDIA_CLAIM_OR_SOURCE_IDENTITY_MISMATCH")
    if not isinstance(payload.get("query"), str) or not payload["query"].strip() or not isinstance(payload.get("page_title"), str) or not payload["page_title"].strip():
        raise WikimediaEvidenceError("WIKIMEDIA_LOOKUP_IDENTITY_MISSING")
    if not isinstance(payload.get("page_id"), int) or payload["page_id"] <= 0 or not isinstance(payload.get("revision_id"), int) or payload["revision_id"] <= 0:
        raise WikimediaEvidenceError("WIKIMEDIA_REVISION_IDENTITY_INVALID")
    if _time(payload["retrieved_at"]) > as_of:
        raise WikimediaEvidenceError("WIKIMEDIA_EVIDENCE_FROM_FUTURE")
    return envelope_sha
