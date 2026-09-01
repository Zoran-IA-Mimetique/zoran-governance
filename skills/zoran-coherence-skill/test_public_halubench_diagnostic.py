from __future__ import annotations

from dataclasses import fields
from types import SimpleNamespace

from raw_text_coherence_gate import RawTextCoherenceRequest
from scripts.run_public_halubench_diagnostic import evaluate_rows
from tolerance_skill import Decision


class FakeGate:
    def __init__(self, decisions):
        self.decisions = iter(decisions)
        self.requests = []

    def evaluate(self, request):
        self.requests.append(request)
        decision = next(self.decisions)
        return SimpleNamespace(
            decision=decision,
            reasons=("fixture",),
            faithful_probability=0.5,
            threshold=0.5,
            structural_status="NOT_APPLICABLE",
            structural_family="none",
            structural_trace=(),
            receipt_sha256=("a" if decision is Decision.PASS else "b") * 64,
        )


def row(case_id, label, source="public"):
    return {
        "id": case_id,
        "passage": "Context text.",
        "question": "Question?",
        "answer": "Answer.",
        "label": label,
        "source_ds": source,
    }


def test_candidate_request_has_no_dataset_label_or_source_channel():
    gate = FakeGate((Decision.PASS,))
    evaluate_rows((row("1", "PASS"),), gate, as_of="2026-09-01T00:00:00Z", excluded_sources=frozenset())
    assert tuple(field.name for field in fields(RawTextCoherenceRequest)) == ("context", "question", "answer", "as_of")
    assert gate.requests == [RawTextCoherenceRequest("Context text.", "Question?", "Answer.", "2026-09-01T00:00:00Z")]


def test_metrics_distinguish_false_pass_from_false_block_and_exclusions():
    rows = (
        row("1", "PASS"), row("2", "PASS"), row("3", "FAIL"), row("4", "FAIL"),
        row("5", "FAIL", "excluded"),
    )
    gate = FakeGate((Decision.PASS, Decision.VETO, Decision.VETO, Decision.PASS))
    report, failures = evaluate_rows(rows, gate, as_of="2026-09-01T00:00:00Z", excluded_sources=frozenset({"excluded"}))
    assert report["metrics"]["cases"] == 4
    assert report["metrics"]["accuracy"] == 0.5
    assert report["metrics"]["faithful_acceptance"] == 0.5
    assert report["metrics"]["hallucination_block_recall"] == 0.5
    assert report["metrics"]["false_pass"] == 1
    assert report["metrics"]["false_block"] == 1
    assert len(failures) == 2


def test_prediction_receipt_replays_deterministically():
    rows = (row("1", "PASS"), row("2", "FAIL"))
    first, _ = evaluate_rows(rows, FakeGate((Decision.PASS, Decision.VETO)), as_of="2026-09-01T00:00:00Z", excluded_sources=frozenset())
    second, _ = evaluate_rows(rows, FakeGate((Decision.PASS, Decision.VETO)), as_of="2026-09-01T00:00:00Z", excluded_sources=frozenset())
    assert first["prediction_receipts_sha256"] == second["prediction_receipts_sha256"]
