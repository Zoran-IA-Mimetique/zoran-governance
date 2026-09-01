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
CERTIFICATE_SCHEMA = "zoran.release-certification.v1"
CERTIFICATION_SCOPE = "DETERMINISTIC_SOFTWARE_ARTIFACT"
CANONICAL_FRAMES = frozenset({"local", "lower", "peer", "upper", "temporal", "planetary"})
ANCHOR_PATH = Path(__file__).resolve().parent / "references" / "robot-trust-anchors.json"
SHA256_RE = re.compile(r"[0-9a-f]{64}")
SHA1_RE = re.compile(r"[0-9a-f]{40}")


class RobotCertificateError(ValueError):
    pass


def canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise RobotCertificateError("ROBOT_CERTIFICATE_NOT_CANONICAL") from exc


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def trusted_certifier() -> dict[str, str]:
    try:
        anchors = json.loads(ANCHOR_PATH.read_text(encoding="utf-8"))
        certifier = anchors["certifier"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise RobotCertificateError("ROBOT_TRUST_ANCHOR_UNAVAILABLE") from exc
    expected = {"authority_id", "fingerprint_sha256", "public_key_hex"}
    if anchors.get("schema") != "zoran.robot-trust-anchors.v1" or set(certifier) != expected:
        raise RobotCertificateError("ROBOT_TRUST_ANCHOR_SCHEMA_INVALID")
    try:
        public_raw = bytes.fromhex(certifier["public_key_hex"])
    except (TypeError, ValueError) as exc:
        raise RobotCertificateError("ROBOT_TRUST_PUBLIC_KEY_INVALID") from exc
    if len(public_raw) != 32 or _sha256(public_raw) != certifier["fingerprint_sha256"]:
        raise RobotCertificateError("ROBOT_TRUST_FINGERPRINT_INVALID")
    return certifier


def verify_release_certificate(
    envelope: Mapping[str, object] | None,
    *,
    mission_sha256: str,
    candidate_sha256: str,
) -> tuple[dict, str]:
    if not isinstance(envelope, Mapping):
        raise RobotCertificateError("ROBOT_CERTIFICATE_MISSING")
    value = dict(envelope)
    required = {
        "schema", "authority_id", "authority_fingerprint", "public_key_hex",
        "payload", "signature_base64", "envelope_sha256",
    }
    if set(value) != required or value.get("schema") != ENVELOPE_SCHEMA:
        raise RobotCertificateError("ROBOT_CERTIFICATE_ENVELOPE_SCHEMA_INVALID")
    anchor = trusted_certifier()
    if value.get("authority_id") != anchor["authority_id"]:
        raise RobotCertificateError("ROBOT_CERTIFICATE_AUTHORITY_INVALID")
    if value.get("authority_fingerprint") != anchor["fingerprint_sha256"] or value.get("public_key_hex") != anchor["public_key_hex"]:
        raise RobotCertificateError("ROBOT_CERTIFICATE_AUTHORITY_UNTRUSTED")
    body = {key: value[key] for key in sorted(required - {"envelope_sha256"})}
    envelope_sha = _sha256(canonical_bytes(body))
    if value.get("envelope_sha256") != envelope_sha:
        raise RobotCertificateError("ROBOT_CERTIFICATE_ENVELOPE_SHA_INVALID")
    payload = value.get("payload")
    if not isinstance(payload, dict):
        raise RobotCertificateError("ROBOT_CERTIFICATE_PAYLOAD_INVALID")
    try:
        signature = base64.b64decode(value["signature_base64"], validate=True)
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(anchor["public_key_hex"])).verify(signature, canonical_bytes(payload))
    except (InvalidSignature, ValueError, TypeError) as exc:
        raise RobotCertificateError("ROBOT_CERTIFICATE_SIGNATURE_INVALID") from exc
    if payload.get("schema") != CERTIFICATE_SCHEMA or payload.get("certification_scope") != CERTIFICATION_SCOPE:
        raise RobotCertificateError("ROBOT_CERTIFICATE_SCOPE_INVALID")
    if payload.get("verdict") != "PASS":
        raise RobotCertificateError("ROBOT_CERTIFICATE_NOT_PASS")
    if payload.get("mission_sha256") != mission_sha256 or payload.get("candidate_sha256") != candidate_sha256:
        raise RobotCertificateError("ROBOT_CERTIFICATE_IDENTITY_MISMATCH")
    if payload.get("channel_id") != "zoran-host:dual-robot-v1" or payload.get("submission_id") != f"sha256:{candidate_sha256}":
        raise RobotCertificateError("ROBOT_CERTIFICATE_HANDOFF_IDENTITY_INVALID")
    frames = payload.get("frames")
    if not isinstance(frames, dict) or set(frames) != CANONICAL_FRAMES or any(status != "PASS" for status in frames.values()):
        raise RobotCertificateError("ROBOT_CERTIFICATE_FRAME_COVERAGE_INVALID")
    checks = payload.get("checks")
    if not isinstance(checks, dict):
        raise RobotCertificateError("ROBOT_CERTIFICATE_CHECKS_INVALID")
    critical = {
        "evaluator_signature": "PASS",
        "evaluator_identity_binding": "PASS",
        "double_rebuild_byte_identical": "PASS",
        "candidate_rebuild_exact": "PASS",
        "source_commit_build_exact": "PASS",
        "signed_build_attestation": "PASS",
        "pinned_trust_anchors": "PASS",
        "private_key_absent_from_candidate": "PASS",
    }
    if any(checks.get(key) != expected for key, expected in critical.items()):
        raise RobotCertificateError("ROBOT_CERTIFICATE_CRITICAL_CHECK_INVALID")
    if not isinstance(checks.get("independent_tests_passed"), int) or checks["independent_tests_passed"] <= 0:
        raise RobotCertificateError("ROBOT_CERTIFICATE_TEST_COUNT_INVALID")
    source = payload.get("source")
    if not isinstance(source, dict) or set(source) != {"git_commit_sha1", "git_tree_sha1"} or not SHA1_RE.fullmatch(source.get("git_commit_sha1", "")) or not SHA1_RE.fullmatch(source.get("git_tree_sha1", "")):
        raise RobotCertificateError("ROBOT_CERTIFICATE_SOURCE_IDENTITY_INVALID")
    if not SHA256_RE.fullmatch(payload.get("manifest_sha256", "")) or not SHA256_RE.fullmatch(payload.get("sbom_sha256", "")):
        raise RobotCertificateError("ROBOT_CERTIFICATE_BUILD_MATERIAL_INVALID")
    if payload.get("builder_id") != anchor["authority_id"]:
        raise RobotCertificateError("ROBOT_CERTIFICATE_BUILDER_IDENTITY_INVALID")
    statement = payload.get("slsa_provenance")
    if not isinstance(statement, dict) or statement.get("_type") != "https://in-toto.io/Statement/v1" or statement.get("predicateType") != "https://slsa.dev/provenance/v1":
        raise RobotCertificateError("ROBOT_CERTIFICATE_SLSA_STATEMENT_INVALID")
    subject = statement.get("subject")
    if not isinstance(subject, list) or len(subject) != 1 or not isinstance(subject[0], dict) or set(subject[0]) != {"name", "digest"} or not isinstance(subject[0].get("name"), str) or not subject[0]["name"] or subject[0].get("digest") != {"sha256": candidate_sha256}:
        raise RobotCertificateError("ROBOT_CERTIFICATE_SLSA_SUBJECT_INVALID")
    predicate = statement.get("predicate")
    try:
        definition = predicate["buildDefinition"]
        details = predicate["runDetails"]
        dependencies = definition["resolvedDependencies"]
    except (KeyError, TypeError):
        raise RobotCertificateError("ROBOT_CERTIFICATE_SLSA_PREDICATE_INVALID")
    if definition.get("externalParameters") != {"mission_sha256": mission_sha256} or details.get("builder") != {"id": anchor["authority_id"]}:
        raise RobotCertificateError("ROBOT_CERTIFICATE_SLSA_IDENTITY_INVALID")
    expected_digests = (
        {"sha1": source["git_commit_sha1"], "gitTree": source["git_tree_sha1"]},
        {"sha256": payload["manifest_sha256"]},
        {"sha256": payload["sbom_sha256"]},
    )
    if not isinstance(dependencies, list) or tuple(item.get("digest") for item in dependencies if isinstance(item, dict)) != expected_digests:
        raise RobotCertificateError("ROBOT_CERTIFICATE_SLSA_MATERIALS_INVALID")
    return payload, envelope_sha
