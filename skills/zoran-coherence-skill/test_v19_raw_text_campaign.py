from scripts.run_v19_raw_text_campaign import run
from raw_text_coherence_gate import RawTextCoherenceGate, RawTextCoherenceRequest


def test_v19_raw_text_campaign_has_no_false_pass_or_false_block():
    result = run(25)
    assert result["verdict"] == "PASS"
    assert result["total_cases"] == 100
    assert result["false_pass"] == 0
    assert result["false_block"] == 0


def test_birth_date_relation_ignores_year_like_number_in_subject_name():
    gate = RawTextCoherenceGate()
    context = "Alex Mercer 2000 was born in 1900. Jordan Hale 2000 was born in 2000."
    question = "When was Alex Mercer 2000 born?"
    faithful = gate.evaluate(RawTextCoherenceRequest(context, question, "Alex Mercer 2000 was born in 1900.", "2026-09-01T00:00:00Z"))
    faithful_scalar = gate.evaluate(RawTextCoherenceRequest(context, question, "1900", "2026-09-01T00:00:00Z"))
    borrowed = gate.evaluate(RawTextCoherenceRequest(context, question, "Alex Mercer 2000 was born in 2000.", "2026-09-01T00:00:00Z"))
    assert faithful.decision.value == "PASS"
    assert faithful_scalar.decision.value == "PASS"
    assert borrowed.decision.value == "VETO"


def test_ambiguous_birth_date_relation_cannot_be_overridden_by_statistical_score():
    gate = RawTextCoherenceGate()
    context = "Sam Mercer 2028 was born in 1912. Sam Mercer 2028 was born in 2028."
    result = gate.evaluate(RawTextCoherenceRequest(
        context,
        "When was Sam Mercer 2028 born?",
        "Sam Mercer 2028 was born in 1912.",
        "2026-09-01T00:00:00Z",
    ))
    assert result.decision.value == "VETO"
    assert result.structural_status == "UNRESOLVED"
    assert result.structural_family == "factoid_relation"


def test_birth_date_question_without_named_subject_is_blocked():
    result = RawTextCoherenceGate().evaluate(RawTextCoherenceRequest(
        "Jordan Hale was born in 1900.",
        "When was --- born?",
        "1900",
        "2026-09-01T00:00:00Z",
    ))
    assert result.decision.value == "VETO"
    assert result.structural_status == "UNRESOLVED"
    assert result.structural_family == "factoid_relation"


def test_v19_high_index_birth_date_collisions_are_closed():
    result = run(2020)
    assert result["verdict"] == "PASS"
    assert result["false_pass"] == 0
    assert result["false_block"] == 0
