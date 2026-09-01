from copy import deepcopy
import hashlib
import json
from pathlib import Path

from blind_eval import BlindEvalGate, BlindEvalRequest, artifact_sha256
from tolerance_skill import Decision


PREREG = "9" * 64
DATASET = {
    "schema": "zoran.blind-public-dataset.v1",
    "cases": [
        {"case_id": "B-001", "input_text": "benign"},
        {"case_id": "B-002", "input_text": "malicious"},
        {"case_id": "B-003", "input_text": "unknown"},
    ],
}
ORACLE = {
    "schema": "zoran.blind-hidden-oracle.v1",
    "cases": [
        {"case_id": "B-001", "expected_decision": "PASS"},
        {"case_id": "B-002", "expected_decision": "VETO"},
        {"case_id": "B-003", "expected_decision": "RETRY"},
    ],
}


def _digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def predictions(decisions=("PASS", "VETO", "RETRY")):
    return {
        "schema": "zoran.blind-predictions.v1",
        "cases": [
            {"case_id": case["case_id"], "decision": decision, "output_sha256": _digest("output:" + case["case_id"]), "trace_sha256": _digest("trace:" + case["case_id"])}
            for case, decision in zip(DATASET["cases"], decisions)
        ],
    }


def gate():
    return BlindEvalGate(preregistration_sha256=PREREG, dataset_sha256=artifact_sha256(DATASET), oracle_commitment_sha256=artifact_sha256(ORACLE))


def request(*, dataset=DATASET, oracle=ORACLE, predicted=None):
    return BlindEvalRequest(PREREG, dataset, artifact_sha256(DATASET), oracle, artifact_sha256(ORACLE), predicted or predictions())


def test_exact_hidden_oracle_predictions_pass():
    result = gate().evaluate(request())
    assert result.decision is Decision.PASS
    assert result.total == result.correct == 3
    assert result.score_basis_points == 10000
    assert result.false_pass == result.false_block == result.other_mismatch == 0


def test_missing_request_is_retrye():
    assert gate().evaluate(None).decision is Decision.RETRY


def test_label_leakage_in_public_split_is_vetoed():
    leaked = deepcopy(DATASET)
    leaked["cases"][0]["expected_decision"] = "PASS"
    result = gate().evaluate(request(dataset=leaked))
    assert result.decision is Decision.VETO
    assert result.reasons == ("PUBLIC_CASE_SCHEMA_OR_LABEL_LEAKAGE",)


def test_public_dataset_content_change_is_vetoed():
    changed = deepcopy(DATASET)
    changed["cases"][0]["input_text"] = "post-hoc edit"
    result = gate().evaluate(request(dataset=changed))
    assert result.decision is Decision.VETO
    assert result.reasons == ("PUBLIC_DATASET_DIGEST_MISMATCH",)


def test_oracle_change_is_vetoed_by_commitment():
    changed = deepcopy(ORACLE)
    changed["cases"][1]["expected_decision"] = "PASS"
    result = gate().evaluate(request(oracle=changed))
    assert result.decision is Decision.VETO
    assert result.reasons == ("HIDDEN_ORACLE_COMMITMENT_MISMATCH",)


def test_post_hoc_case_deletion_is_vetoed():
    changed = predictions()
    changed["cases"].pop()
    result = gate().evaluate(request(predicted=changed))
    assert result.decision is Decision.VETO
    assert result.reasons == ("PREDICTION_CASE_SET_MISMATCH",)


def test_prediction_reordering_or_duplication_is_vetoed():
    changed = predictions()
    changed["cases"][1] = deepcopy(changed["cases"][0])
    assert gate().evaluate(request(predicted=changed)).decision is Decision.VETO


def test_missing_trace_is_vetoed():
    changed = predictions()
    changed["cases"][0]["trace_sha256"] = ""
    assert gate().evaluate(request(predicted=changed)).decision is Decision.VETO


def test_false_pass_is_vetoed_not_averaged():
    result = gate().evaluate(request(predicted=predictions(("PASS", "PASS", "RETRY"))))
    assert result.decision is Decision.VETO
    assert result.false_pass == 1
    assert result.correct == 2


def test_false_block_requires_retry():
    result = gate().evaluate(request(predicted=predictions(("VETO", "VETO", "RETRY"))))
    assert result.decision is Decision.RETRY
    assert result.false_block == 1


def test_non_pass_classification_mismatch_requires_retry():
    result = gate().evaluate(request(predicted=predictions(("PASS", "RETRY", "RETRY"))))
    assert result.decision is Decision.RETRY
    assert result.other_mismatch == 1


def test_pinned_commitments_cannot_be_replaced_by_caller():
    supplied = BlindEvalRequest("8" * 64, DATASET, artifact_sha256(DATASET), ORACLE, artifact_sha256(ORACLE), predictions())
    result = gate().evaluate(supplied)
    assert result.decision is Decision.VETO
    assert result.reasons == ("BLIND_EVAL_PINNED_COMMITMENT_MISMATCH",)


def test_replay_is_byte_deterministic():
    first = gate().evaluate(request())
    second = gate().evaluate(request())
    assert first == second


def test_frozen_v16_blind_artifacts_replay_to_certificate():
    root = Path(__file__).resolve().parent / "audit"
    public = json.loads((root / "BLIND_EVAL_PUBLIC_V16.json").read_text(encoding="utf-8"))
    oracle = json.loads((root / "BLIND_EVAL_ORACLE_V16.json").read_text(encoding="utf-8"))
    frozen = json.loads((root / "BLIND_EVAL_PREREG_V16.json").read_text(encoding="utf-8"))
    predicted = json.loads((root / "BLIND_EVAL_PREDICTIONS_V16.json").read_text(encoding="utf-8"))
    certificate = json.loads((root / "BLIND_EVAL_CERTIFICATE_V16.json").read_text(encoding="utf-8"))
    evaluator = BlindEvalGate(
        preregistration_sha256=frozen["governing_preregistration_sha256"],
        dataset_sha256=frozen["public_dataset_canonical_sha256"],
        oracle_commitment_sha256=frozen["hidden_oracle_commitment_sha256"],
    )
    result = evaluator.evaluate(BlindEvalRequest(
        frozen["governing_preregistration_sha256"], public,
        frozen["public_dataset_canonical_sha256"], oracle,
        frozen["hidden_oracle_commitment_sha256"], predicted,
    ))
    assert result.decision is Decision.PASS
    assert result.receipt_sha256 == certificate["receipt_sha256"]
    assert result.total == result.correct == certificate["total"]
