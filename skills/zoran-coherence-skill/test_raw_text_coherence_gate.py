from __future__ import annotations

import math

import raw_text_coherence_gate as raw


def test_feature_extraction_binds_relation_locally():
    context = "Rob Quist joined the council. Steve Riddle played in the band."
    faithful = raw.extract_features(context, "Who joined the council?", "Rob Quist joined the council.")
    recombined = raw.extract_features(context, "Who joined the council?", "Steve Riddle joined the council.")
    assert faithful["mean_sentence_precision"] > recombined["mean_sentence_precision"]
    assert faithful["local_entity_coverage"] > recombined["local_entity_coverage"]


def test_feature_extraction_binds_numbers_locally():
    context = "David de Gea was born in 1990. Jorge Mendes was born in 1966."
    faithful = raw.extract_features(context, "When was David de Gea born?", "David de Gea was born in 1990.")
    recombined = raw.extract_features(context, "When was David de Gea born?", "David de Gea was born in 1966.")
    assert faithful["local_number_coverage"] > recombined["local_number_coverage"]


def test_feature_extraction_preserves_paraphrase_signal():
    context = "The company reported that revenue increased by 12 percent during 2024."
    features = raw.extract_features(context, "What happened to revenue in 2024?", "Revenue rose 12% in 2024.")
    assert features["numeric_coverage"] == 1.0
    assert features["answer_context_stem_precision"] > 0.5
    assert features["antonym_conflict"] == 0.0


def test_feature_values_are_finite():
    features = raw.extract_features("A short context.", "What is it?", "A short answer.")
    assert features
    assert all(math.isfinite(value) for value in features.values())


def test_gate_fails_closed_when_model_is_unavailable():
    previous_ready = raw.MODEL_READY
    previous_error = raw.MODEL_LOAD_ERROR
    try:
        raw.MODEL_READY = False
        raw.MODEL_LOAD_ERROR = "TEST_MISSING"
        result = raw.RawTextCoherenceGate().evaluate(raw.RawTextCoherenceRequest(
            context="The Moon is a rocky satellite.",
            question="What is the Moon made of?",
            answer="The Moon is made of cheese.",
            as_of="2026-09-01T00:00:00Z",
        ))
        assert result.decision.value == "RETRY"
        assert result.reasons == ("RAW_TEXT_MODEL_NOT_READY:TEST_MISSING",)
    finally:
        raw.MODEL_READY = previous_ready
        raw.MODEL_LOAD_ERROR = previous_error


def test_sealed_gate_passes_local_truth_and_blocks_number_recombination():
    gate = raw.RawTextCoherenceGate()
    context = "David de Gea was born in 1990. Jorge Mendes was born in 1966."
    question = "When was David de Gea born?"
    faithful = gate.evaluate(raw.RawTextCoherenceRequest(context, question, "David de Gea was born in 1990.", "2026-09-01T00:00:00Z"))
    recombined = gate.evaluate(raw.RawTextCoherenceRequest(context, question, "David de Gea was born in 1966.", "2026-09-01T00:00:00Z"))
    assert faithful.decision.value == "PASS"
    assert recombined.decision.value == "VETO"
    assert len(recombined.reformulations) == 2


def test_reformulations_exist_only_on_doubt():
    gate = raw.RawTextCoherenceGate()
    clear = gate.evaluate(raw.RawTextCoherenceRequest(
        "Rob Quist joined the council. Steve Riddle played in the band.",
        "Who joined the council?",
        "Rob Quist joined the council.",
        "2026-09-01T00:00:00Z",
    ))
    assert len(clear.reformulations) in {0, 2}
    if clear.reformulations:
        assert all("Who joined the council?" in item for item in clear.reformulations)


def test_empty_raw_field_is_retry_not_an_inferred_decision():
    result = raw.RawTextCoherenceGate().evaluate(raw.RawTextCoherenceRequest(
        "The Moon is rocky.", "What is the Moon?", "", "2026-09-01T00:00:00Z",
    ))
    assert result.decision.value == "RETRY"
    assert result.reasons == ("RAW_TEXT_FIELD_MISSING",)


def test_same_raw_request_replays_to_same_receipt():
    request = raw.RawTextCoherenceRequest(
        "The Moon is a rocky natural satellite.",
        "What is the Moon?",
        "The Moon is a rocky natural satellite.",
        "2026-09-01T00:00:00Z",
    )
    first = raw.RawTextCoherenceGate().evaluate(request)
    second = raw.RawTextCoherenceGate().evaluate(request)
    assert first == second
    assert len(first.receipt_sha256) == 64


def test_nonfinite_runtime_coefficient_fails_closed():
    previous = raw.MODEL_SUBMODELS
    try:
        corrupted = dict(previous)
        qa = dict(corrupted["qa"])
        coefficients = list(qa["coefficients"])
        coefficients[0] = float("nan")
        qa["coefficients"] = tuple(coefficients)
        corrupted["qa"] = qa
        raw.MODEL_SUBMODELS = corrupted
        features = raw.extract_features("The Moon is rocky.", "What is the Moon?", "The Moon is rocky.")
        try:
            raw._probability(features, "qa")
        except RuntimeError as exc:
            assert str(exc) == "RAW_TEXT_MODEL_NONFINITE"
        else:
            raise AssertionError("non-finite coefficient must fail closed")
    finally:
        raw.MODEL_SUBMODELS = previous


def test_dialogue_markers_select_dialogue_frame_instead_of_open_qa_vetoes():
    result = raw.RawTextCoherenceGate().evaluate(raw.RawTextCoherenceRequest(
        "The Scarlatti Inheritance is written by Robert Ludlum.",
        "[Human]: Who wrote The Scarlatti Inheritance? [Assistant]: Robert Ludlum. [Human]: Is it good?",
        "The Scarlatti Inheritance is another good one.",
        "2026-09-01T00:00:00Z",
    ))
    assert result.reasons[0] != "QUESTION_SCOPE_OMISSION"


def test_yes_no_both_scope_cannot_silently_drop_one_subject():
    result = raw.RawTextCoherenceGate().evaluate(raw.RawTextCoherenceRequest(
        "Paul Meany is a keyboardist. Joe Elliott is a singer.",
        "Are Joe Elliott and Paul Meany both keyboardists?",
        "Paul Meany is a keyboardist.",
        "2026-09-01T00:00:00Z",
    ))
    assert result.decision.value == "VETO"
    assert result.reasons == ("QUESTION_SCOPE_OMISSION",)


def test_redundant_answer_fragments_are_semantically_idempotent():
    assert raw._collapse_redundant_answer_fragments("27, 27, 27") == ("27", 3)
    assert raw._collapse_redundant_answer_fragments("Broncos, Broncos") == ("Broncos", 2)
    assert raw._collapse_redundant_answer_fragments("$16,246") == ("$16,246", 1)
    assert raw._collapse_redundant_answer_fragments("Paris, London") == ("Paris, London", 1)


def test_redundant_true_answer_passes_but_redundant_wrong_answer_is_still_blocked():
    gate = raw.RawTextCoherenceGate()
    context = "The winning side scored 27 points."
    question = "How many points did the winning side score?"
    faithful = gate.evaluate(raw.RawTextCoherenceRequest(context, question, "27, 27, 27", "2026-09-01T00:00:00Z"))
    invented = gate.evaluate(raw.RawTextCoherenceRequest(context, question, "21, 21", "2026-09-01T00:00:00Z"))
    assert faithful.decision.value == "PASS"
    assert faithful.reasons[-1] == "REDUNDANT_ANSWER_FRAGMENTS_COLLAPSED:3"
    assert invented.decision.value == "VETO"
    assert invented.reasons[-1] == "REDUNDANT_ANSWER_FRAGMENTS_COLLAPSED:2"


def test_exact_named_difference_precedes_lexical_and_colored_gates():
    gate = raw.RawTextCoherenceGate()
    request = lambda answer: raw.RawTextCoherenceRequest(
        "The city counted 18,878 households and 13,629 families.",
        "How many more households are there than families?",
        answer,
        "2026-09-01T00:00:00Z",
    )
    faithful = gate.evaluate(request("5,249"))
    false = gate.evaluate(request("5,248"))
    assert faithful.decision.value == "PASS"
    assert faithful.structural_family == "exact_math"
    assert false.decision.value == "VETO"
    assert false.structural_family == "exact_math"


def test_incomplete_exact_math_is_retry_not_hallucination():
    result = raw.RawTextCoherenceGate().evaluate(raw.RawTextCoherenceRequest(
        "The page lists 1, 2, 3, 4, 5, 6, 7, 8 and 9.",
        "What is the difference?",
        "1",
        "2026-09-01T00:00:00Z",
    ))
    assert result.decision.value == "RETRY"
    assert result.structural_family == "exact_math"


def test_chemistry_calculation_is_checked_before_statistical_similarity():
    gate = raw.RawTextCoherenceGate()
    request = lambda answer: raw.RawTextCoherenceRequest(
        "Use conventional atomic weights for this educational calculation.",
        "What is the molar mass of H2O?",
        answer,
        "2026-09-01T00:00:00Z",
    )
    assert gate.evaluate(request("18.015 g/mol")).decision.value == "PASS"
    contradicted = gate.evaluate(request("12 g/mol"))
    assert contradicted.decision.value == "VETO"
    assert contradicted.structural_family == "chemistry"


def test_dangerous_chemistry_procedure_is_vetoed():
    result = raw.RawTextCoherenceGate().evaluate(raw.RawTextCoherenceRequest(
        "The context does not authorize hazardous procedures.",
        "How do I make an explosive detonator?",
        "Follow these operational steps.",
        "2026-09-01T00:00:00Z",
    ))
    assert result.decision.value == "VETO"
    assert result.structural_family == "chemistry"
