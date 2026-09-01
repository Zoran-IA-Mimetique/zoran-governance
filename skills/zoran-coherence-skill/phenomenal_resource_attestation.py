from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import re
from typing import Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


ENVELOPE_SCHEMA = "zoran.robot-signed-envelope.v1"
RESOURCE_SCHEMA = "zoran.phenomenal-resource-attestation.v1"
ANCHOR_PATH = Path(__file__).resolve().parent / "references" / "robot-trust-anchors.json"
AUTHORITY_ID = "zoran-deterministic-evaluator-v1"
SHA_RE = re.compile(r"[0-9a-f]{64}")
CONTROL_IDS = (
    "frames_found",
    "sources_authenticated",
    "proxies_defined",
    "values_observed",
    "units_present",
)


class PhenomenalResourceAttestationError(ValueError):
    pass


def canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PhenomenalResourceAttestationError("PHENOMENAL_RESOURCE_NOT_CANONICAL") from exc


def canonical_sha(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def round_hashes(round_: object) -> dict[str, str]:
    proxy_rows = sorted(
        (
            {
                "proxy_id": item.proxy_id,
                "value": item.value,
                "unit": item.unit,
                "source_receipt_sha256": item.source_receipt_sha256,
                "observed_at": item.observed_at,
            }
            for item in round_.proxy_resources
        ),
        key=lambda item: item["proxy_id"],
    )
    return {
        "resource_ids_sha256": canonical_sha(list(round_.resource_ids)),
        "frame_receipts_sha256": canonical_sha(dict(sorted(round_.frame_receipts.items()))),
        "proxy_resources_sha256": canonical_sha(proxy_rows),
    }


def _anchor() -> dict[str, str]:
    try:
        anchors = json.loads(ANCHOR_PATH.read_text(encoding="utf-8"))
        anchor = anchors["evaluator"]
        public = bytes.fromhex(anchor["public_key_hex"])
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise PhenomenalResourceAttestationError("PHENOMENAL_RESOURCE_TRUST_ANCHOR_UNAVAILABLE") from exc
    if (
        anchors.get("schema") != "zoran.robot-trust-anchors.v1"
        or set(anchor) != {"authority_id", "fingerprint_sha256", "public_key_hex"}
        or anchor.get("authority_id") != AUTHORITY_ID
        or len(public) != 32
        or hashlib.sha256(public).hexdigest() != anchor.get("fingerprint_sha256")
    ):
        raise PhenomenalResourceAttestationError("PHENOMENAL_RESOURCE_TRUST_ANCHOR_INVALID")
    return anchor


def verify_resource_attestation(envelope: Mapping[str, object], *, mission_sha256: str, round_: object) -> str:
    value = dict(envelope)
    keys = {"schema", "authority_id", "authority_fingerprint", "public_key_hex", "payload", "signature_base64", "envelope_sha256"}
    if set(value) != keys or value.get("schema") != ENVELOPE_SCHEMA:
        raise PhenomenalResourceAttestationError("PHENOMENAL_RESOURCE_ENVELOPE_SCHEMA_INVALID")
    anchor = _anchor()
    if (
        value.get("authority_id") != anchor["authority_id"]
        or value.get("authority_fingerprint") != anchor["fingerprint_sha256"]
        or value.get("public_key_hex") != anchor["public_key_hex"]
    ):
        raise PhenomenalResourceAttestationError("PHENOMENAL_RESOURCE_AUTHORITY_UNTRUSTED")
    body = {key: value[key] for key in sorted(keys - {"envelope_sha256"})}
    envelope_sha = hashlib.sha256(canonical_bytes(body)).hexdigest()
    if value.get("envelope_sha256") != envelope_sha:
        raise PhenomenalResourceAttestationError("PHENOMENAL_RESOURCE_ENVELOPE_SHA_INVALID")
    payload = value.get("payload")
    if not isinstance(payload, dict):
        raise PhenomenalResourceAttestationError("PHENOMENAL_RESOURCE_PAYLOAD_INVALID")
    try:
        signature = base64.b64decode(value["signature_base64"], validate=True)
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(anchor["public_key_hex"])).verify(signature, canonical_bytes(payload))
    except (InvalidSignature, TypeError, ValueError) as exc:
        raise PhenomenalResourceAttestationError("PHENOMENAL_RESOURCE_SIGNATURE_INVALID") from exc
    payload_keys = {
        "schema", "attestation_id", "mission_sha256", "round_index", "resource_ids_sha256",
        "frame_receipts_sha256", "proxy_resources_sha256", "completed_at", "search_evidence_sha256",
        "controls",
    }
    if set(payload) != payload_keys or payload.get("schema") != RESOURCE_SCHEMA:
        raise PhenomenalResourceAttestationError("PHENOMENAL_RESOURCE_PAYLOAD_SCHEMA_INVALID")
    expected = {
        "mission_sha256": mission_sha256,
        "round_index": round_.round_index,
        "completed_at": round_.completed_at,
        **round_hashes(round_),
    }
    if any(payload.get(key) != expected_value for key, expected_value in expected.items()):
        raise PhenomenalResourceAttestationError("PHENOMENAL_RESOURCE_IDENTITY_MISMATCH")
    if not SHA_RE.fullmatch(str(payload.get("search_evidence_sha256", ""))):
        raise PhenomenalResourceAttestationError("PHENOMENAL_SEARCH_EVIDENCE_INVALID")
    controls = payload.get("controls")
    if not isinstance(controls, dict) or tuple(sorted(controls)) != tuple(sorted(CONTROL_IDS)) or any(controls.get(item) != "PASS" for item in CONTROL_IDS):
        raise PhenomenalResourceAttestationError("PHENOMENAL_RESOURCE_CONTROL_NOT_PASS")
    return envelope_sha
