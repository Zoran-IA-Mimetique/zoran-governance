import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

from robot_handoff_guard import RobotHandoffGuard, RobotHandoffRequest, RobotTrustRegistry
from semantic_non_conflation import evidence_sha256
from tolerance_skill import Decision


MISSION = "a" * 64
CANDIDATE = "b" * 64
FIXTURE = json.loads((Path(__file__).resolve().parent / "audit" / "ROBOT_TEST_CERTIFICATE.json").read_text(encoding="utf-8"))
AUTHORITY_FINGERPRINT = FIXTURE["authority_fingerprint"]
VALIDATION_RECEIPT = FIXTURE["envelope_sha256"]


def _ev(value):
    return value, evidence_sha256(value)


def make_request(*, required=True, discovery=True, channel=True, submission=True, validation_status="PASS", envelope=FIXTURE):
    applicability, applicability_sha = _ev("robot validation applies to promotion" if required else "robot validation does not apply to this non-promotion evaluation")
    discovery_evidence, discovery_sha = _ev("host robot registry discovery completed")
    channel_evidence, channel_sha = _ev("callable robot channel resolved")
    submission_evidence, submission_sha = _ev("artifact submitted to external robot")
    certificate_present = validation_status == "PASS" and envelope is not None
    return RobotHandoffRequest(
        MISSION,
        CANDIDATE,
        CANDIDATE,
        required,
        applicability,
        applicability_sha,
        discovery_completed=discovery,
        discovery_evidence=discovery_evidence if discovery else None,
        discovery_evidence_sha256=discovery_sha if discovery else None,
        channel_id="zoran-host:dual-robot-v1" if channel else None,
        channel_evidence=channel_evidence if channel else None,
        channel_evidence_sha256=channel_sha if channel else None,
        submission_id=f"sha256:{CANDIDATE}" if submission else None,
        submission_evidence=submission_evidence if submission else None,
        submission_evidence_sha256=submission_sha if submission else None,
        validation_status=validation_status,
        validation_receipt_sha256=VALIDATION_RECEIPT if certificate_present else ("d" * 64 if validation_status == "FAIL" else None),
        authority_id=FIXTURE["authority_id"] if validation_status in {"PASS", "FAIL"} else None,
        authority_fingerprint=AUTHORITY_FINGERPRINT if validation_status in {"PASS", "FAIL"} else None,
        certification_envelope=envelope if certificate_present else None,
    )


def registry():
    return None


def test_signed_robot_validation_passes():
    result = RobotHandoffGuard().evaluate(make_request())
    assert result.decision is Decision.PASS
    assert result.state == "VALIDATED"
    assert result.certificate_sha256 == VALIDATION_RECEIPT


def test_explicit_non_applicability_can_pass_without_handoff():
    request = make_request(required=False, discovery=False, channel=False, submission=False, validation_status=None)
    result = RobotHandoffGuard().evaluate(request)
    assert result.decision is Decision.PASS
    assert result.state == "NOT_REQUIRED_PROVEN"


def test_required_handoff_without_discovery_retries():
    result = RobotHandoffGuard().evaluate(make_request(discovery=False, channel=False, submission=False, validation_status=None))
    assert result.decision is Decision.RETRY
    assert result.reasons == ("ROBOT_DISCOVERY_NOT_RUN",)


def test_completed_discovery_without_channel_is_retry():
    result = RobotHandoffGuard().evaluate(make_request(channel=False, submission=False, validation_status=None))
    assert result.decision is Decision.RETRY
    assert result.state == "CHANNEL_UNRESOLVED"


def test_callable_channel_without_submission_retries():
    result = RobotHandoffGuard().evaluate(make_request(submission=False, validation_status=None))
    assert result.decision is Decision.RETRY
    assert result.reasons == ("ROBOT_HANDOFF_NOT_TRIGGERED",)


def test_submission_without_verdict_stays_pending():
    result = RobotHandoffGuard().evaluate(make_request(validation_status="PENDING"))
    assert result.decision is Decision.RETRY
    assert result.state == "VALIDATION_PENDING"


def test_robot_rejection_is_veto():
    result = RobotHandoffGuard().evaluate(make_request(validation_status="FAIL"))
    assert result.decision is Decision.VETO
    assert result.state == "REJECTED"


def test_pass_without_signed_certificate_is_retry():
    result = RobotHandoffGuard().evaluate(make_request(envelope=None))
    assert result.decision is Decision.RETRY
    assert result.state == "VALIDATION_UNPROVEN"


def test_caller_supplied_trust_registry_is_vetoed():
    legacy = RobotTrustRegistry({FIXTURE["authority_id"]: AUTHORITY_FINGERPRINT}, (VALIDATION_RECEIPT,))
    result = RobotHandoffGuard().evaluate(make_request(), trust_registry=legacy)
    assert result.decision is Decision.VETO
    assert result.state == "CALLER_TRUST_FORBIDDEN"


def test_signature_mutation_is_veto():
    mutated = deepcopy(FIXTURE)
    mutated["signature_base64"] = "A" + mutated["signature_base64"][1:]
    result = RobotHandoffGuard().evaluate(make_request(envelope=mutated))
    assert result.decision is Decision.VETO
    assert result.state == "CERTIFICATE_INVALID"


def test_certificate_receipt_substitution_is_veto():
    result = RobotHandoffGuard().evaluate(replace(make_request(), validation_receipt_sha256="d" * 64))
    assert result.decision is Decision.VETO
    assert result.state == "CERTIFICATE_SUBSTITUTED"


def test_candidate_artifact_substitution_is_veto():
    result = RobotHandoffGuard().evaluate(replace(make_request(), artifact_sha256="e" * 64))
    assert result.decision is Decision.VETO
    assert result.state == "IDENTITY_CONFLICT"


def test_handoff_submission_substitution_is_veto():
    result = RobotHandoffGuard().evaluate(replace(make_request(), submission_id="sha256:" + "c" * 64))
    assert result.decision is Decision.VETO
    assert result.state == "HANDOFF_IDENTITY_CONFLICT"


def test_receipt_is_deterministic_and_request_bound():
    engine = RobotHandoffGuard()
    first = engine.evaluate(make_request())
    second = engine.evaluate(make_request())
    changed = engine.evaluate(replace(make_request(), submission_id="sha256:" + "c" * 64))
    assert first.receipt_sha256 == second.receipt_sha256
    assert changed.receipt_sha256 != first.receipt_sha256
