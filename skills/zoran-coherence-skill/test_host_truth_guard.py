from dataclasses import replace
import json
from pathlib import Path

from host_truth_guard import HostTruthGuard, HostTruthRequest
from tolerance_skill import Decision


ROOT = Path(__file__).resolve().parent
CERT = json.loads((ROOT / "audit" / "HOST_TRUTH_TEST_CERTIFICATE_V17.json").read_text(encoding="utf-8"))


def request(certificate=CERT):
    payload = CERT["payload"]
    return HostTruthRequest(
        payload["mission_sha256"],
        "candidate cannot certify itself. host must submit candidate.",
        "coherence decision",
        payload["claim_receipt_sha256"],
        payload["semantic_receipt_sha256"],
        payload["phenomenal_resource_receipt_sha256"],
        payload["phenomenal_receipt_sha256"],
        payload["source_authority_receipts_sha256"],
        certificate,
        "2026-09-01T00:05:00Z",
    )


def test_pinned_host_truth_attestation_passes():
    result = HostTruthGuard().evaluate(request())
    assert result.decision is Decision.PASS
    assert result.state == "TRUTH_CONTROLS_AUTHENTICATED"


def test_missing_truth_attestation_is_retry_with_beacon():
    result = HostTruthGuard().evaluate(None)
    assert result.decision is Decision.RETRY
    assert result.state == "GYROPHARE"


def test_caller_truth_registry_is_forbidden():
    assert HostTruthGuard().evaluate(request(), trust_registry={}).decision is Decision.VETO


def test_output_substitution_is_vetoed():
    assert HostTruthGuard().evaluate(replace(request(), output_text="substituted")).decision is Decision.VETO


def test_measurement_receipt_substitution_is_vetoed():
    assert HostTruthGuard().evaluate(replace(request(), phenomenal_receipt_sha256="f" * 64)).decision is Decision.VETO


def test_control_downgrade_breaks_signature():
    damaged = json.loads(json.dumps(CERT))
    damaged["payload"]["controls"]["source_authenticity"] = "FAIL"
    assert HostTruthGuard().evaluate(request(damaged)).decision is Decision.VETO
