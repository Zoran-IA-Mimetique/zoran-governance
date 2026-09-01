from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Mapping

from tolerance_skill import Decision


COMPONENT_ID = "zoran.blind-eval-integrity"
VERSION = "16.0.0"
DATASET_SCHEMA = "zoran.blind-public-dataset.v1"
ORACLE_SCHEMA = "zoran.blind-hidden-oracle.v1"
PREDICTION_SCHEMA = "zoran.blind-predictions.v1"
SHA_RE = re.compile(r"[0-9a-f]{64}")
ALLOWED_DECISIONS = frozenset(item.value for item in Decision)


class BlindEvalError(ValueError):
    pass


@dataclass(frozen=True)
class BlindEvalRequest:
    preregistration_sha256: str
    public_dataset: Mapping[str, object]
    dataset_sha256: str
    hidden_oracle: Mapping[str, object]
    oracle_commitment_sha256: str
    predictions: Mapping[str, object]


@dataclass(frozen=True)
class BlindEvalEvaluation:
    decision: Decision
    reasons: tuple[str, ...]
    total: int
    correct: int
    false_pass: int
    false_block: int
    other_mismatch: int
    score_basis_points: int
    dataset_sha256: str | None
    oracle_commitment_sha256: str | None
    predictions_sha256: str | None
    receipt_sha256: str


def canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise BlindEvalError("BLIND_ARTIFACT_NOT_CANONICAL") from exc


def artifact_sha256(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _exact_object(value: object, keys: set[str], error: str) -> dict:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise BlindEvalError(error)
    return dict(value)


def _validate_public_dataset(value: object) -> tuple[dict, tuple[str, ...]]:
    artifact = _exact_object(value, {"schema", "cases"}, "PUBLIC_DATASET_SCHEMA_INVALID")
    if artifact["schema"] != DATASET_SCHEMA or not isinstance(artifact["cases"], list) or not artifact["cases"]:
        raise BlindEvalError("PUBLIC_DATASET_SCHEMA_INVALID")
    ids = []
    for case in artifact["cases"]:
        row = _exact_object(case, {"case_id", "input_text"}, "PUBLIC_CASE_SCHEMA_OR_LABEL_LEAKAGE")
        if not isinstance(row["case_id"], str) or not row["case_id"].strip() or not isinstance(row["input_text"], str) or not row["input_text"].strip():
            raise BlindEvalError("PUBLIC_CASE_VALUE_INVALID")
        ids.append(row["case_id"])
    if len(ids) != len(set(ids)):
        raise BlindEvalError("PUBLIC_CASE_ID_DUPLICATE")
    return artifact, tuple(ids)


def _validate_oracle(value: object, case_ids: tuple[str, ...]) -> tuple[dict, dict[str, str]]:
    artifact = _exact_object(value, {"schema", "cases"}, "HIDDEN_ORACLE_SCHEMA_INVALID")
    if artifact["schema"] != ORACLE_SCHEMA or not isinstance(artifact["cases"], list):
        raise BlindEvalError("HIDDEN_ORACLE_SCHEMA_INVALID")
    rows = []
    mapping = {}
    for case in artifact["cases"]:
        row = _exact_object(case, {"case_id", "expected_decision"}, "HIDDEN_ORACLE_CASE_SCHEMA_INVALID")
        if row["expected_decision"] not in ALLOWED_DECISIONS:
            raise BlindEvalError("HIDDEN_ORACLE_DECISION_INVALID")
        rows.append(row["case_id"])
        mapping[row["case_id"]] = row["expected_decision"]
    if tuple(rows) != case_ids or len(mapping) != len(rows):
        raise BlindEvalError("HIDDEN_ORACLE_CASE_SET_MISMATCH")
    return artifact, mapping


def _validate_predictions(value: object, case_ids: tuple[str, ...]) -> tuple[dict, dict[str, str]]:
    artifact = _exact_object(value, {"schema", "cases"}, "PREDICTIONS_SCHEMA_INVALID")
    if artifact["schema"] != PREDICTION_SCHEMA or not isinstance(artifact["cases"], list):
        raise BlindEvalError("PREDICTIONS_SCHEMA_INVALID")
    rows = []
    mapping = {}
    for case in artifact["cases"]:
        row = _exact_object(case, {"case_id", "decision", "output_sha256", "trace_sha256"}, "PREDICTION_CASE_SCHEMA_INVALID")
        if row["decision"] not in ALLOWED_DECISIONS:
            raise BlindEvalError("PREDICTION_DECISION_INVALID")
        if not SHA_RE.fullmatch(row["output_sha256"] if isinstance(row["output_sha256"], str) else "") or not SHA_RE.fullmatch(row["trace_sha256"] if isinstance(row["trace_sha256"], str) else ""):
            raise BlindEvalError("PREDICTION_TRACE_IDENTITY_INVALID")
        rows.append(row["case_id"])
        mapping[row["case_id"]] = row["decision"]
    if tuple(rows) != case_ids or len(mapping) != len(rows):
        raise BlindEvalError("PREDICTION_CASE_SET_MISMATCH")
    return artifact, mapping


class BlindEvalGate:
    def __init__(self, *, preregistration_sha256: str, dataset_sha256: str, oracle_commitment_sha256: str):
        self.preregistration_sha256 = preregistration_sha256
        self.dataset_sha256 = dataset_sha256
        self.oracle_commitment_sha256 = oracle_commitment_sha256

    def evaluate(self, request: BlindEvalRequest | None) -> BlindEvalEvaluation:
        if not isinstance(request, BlindEvalRequest):
            return self._finish(Decision.RETRY, ("BLIND_EVAL_REQUEST_MISSING",), 0, 0, 0, 0, 0, None, None, None)
        pinned = (self.preregistration_sha256, self.dataset_sha256, self.oracle_commitment_sha256)
        supplied = (request.preregistration_sha256, request.dataset_sha256, request.oracle_commitment_sha256)
        if any(not SHA_RE.fullmatch(value if isinstance(value, str) else "") for value in pinned + supplied):
            return self._finish(Decision.RETRY, ("BLIND_EVAL_COMMITMENT_INVALID",), 0, 0, 0, 0, 0, None, None, None)
        if supplied != pinned:
            return self._finish(Decision.VETO, ("BLIND_EVAL_PINNED_COMMITMENT_MISMATCH",), 0, 0, 0, 0, 0, request.dataset_sha256, request.oracle_commitment_sha256, None)
        try:
            dataset, case_ids = _validate_public_dataset(request.public_dataset)
            if artifact_sha256(dataset) != request.dataset_sha256:
                raise BlindEvalError("PUBLIC_DATASET_DIGEST_MISMATCH")
            oracle, expected = _validate_oracle(request.hidden_oracle, case_ids)
            if artifact_sha256(oracle) != request.oracle_commitment_sha256:
                raise BlindEvalError("HIDDEN_ORACLE_COMMITMENT_MISMATCH")
            predictions, observed = _validate_predictions(request.predictions, case_ids)
        except BlindEvalError as exc:
            return self._finish(Decision.VETO, (str(exc),), 0, 0, 0, 0, 0, request.dataset_sha256, request.oracle_commitment_sha256, None)
        false_pass = sum(observed[key] == Decision.PASS.value and expected[key] != Decision.PASS.value for key in case_ids)
        false_block = sum(observed[key] != Decision.PASS.value and expected[key] == Decision.PASS.value for key in case_ids)
        other = sum(observed[key] != expected[key] and observed[key] != Decision.PASS.value and expected[key] != Decision.PASS.value for key in case_ids)
        correct = len(case_ids) - false_pass - false_block - other
        score = correct * 10000 // len(case_ids)
        predictions_sha = artifact_sha256(predictions)
        if false_pass:
            return self._finish(Decision.VETO, ("BLIND_EVAL_FALSE_PASS",), len(case_ids), correct, false_pass, false_block, other, request.dataset_sha256, request.oracle_commitment_sha256, predictions_sha)
        if false_block or other:
            return self._finish(Decision.RETRY, ("BLIND_EVAL_PREDICTION_MISMATCH",), len(case_ids), correct, false_pass, false_block, other, request.dataset_sha256, request.oracle_commitment_sha256, predictions_sha)
        return self._finish(Decision.PASS, ("BLIND_EVAL_INTEGRITY_AND_PREDICTIONS_PASS",), len(case_ids), correct, 0, 0, 0, request.dataset_sha256, request.oracle_commitment_sha256, predictions_sha)

    @staticmethod
    def _finish(decision: Decision, reasons: tuple[str, ...], total: int, correct: int, false_pass: int, false_block: int, other: int, dataset_sha: str | None, oracle_sha: str | None, predictions_sha: str | None) -> BlindEvalEvaluation:
        score = correct * 10000 // total if total else 0
        body = {
            "component": COMPONENT_ID, "version": VERSION, "decision": decision.value,
            "reasons": list(reasons), "total": total, "correct": correct,
            "false_pass": false_pass, "false_block": false_block, "other_mismatch": other,
            "score_basis_points": score, "dataset_sha256": dataset_sha,
            "oracle_commitment_sha256": oracle_sha, "predictions_sha256": predictions_sha,
        }
        receipt = artifact_sha256(body)
        return BlindEvalEvaluation(decision, reasons, total, correct, false_pass, false_block, other, score, dataset_sha, oracle_sha, predictions_sha, receipt)
