from components.semantic_color_patterns_v0.discourse_realizer_v1 import (
    SemanticDiscourse,
    SemanticProposition,
)
from semantic_speech_gate import SemanticSpeechGate
from tolerance_skill import Decision


def _discourse() -> SemanticDiscourse:
    return SemanticDiscourse(
        intent="expliquer",
        propositions=(
            SemanticProposition(
                subject="cadre local",
                relation="préserve",
                object="cadre pair",
                modality="possible",
                condition="preuve présente",
            ),
        ),
        temporal_order=("avant", "après"),
        references=(("il", "cadre local"),),
        units=("seconde",),
    )


def test_exact_speech_is_released_only_after_round_trip():
    result = SemanticSpeechGate().evaluate(_discourse())
    assert result.decision is Decision.PASS
    assert result.status == "SPEECH_READY"
    assert result.speech is not None
    assert result.target_sha256 == result.observed_sha256
    assert result.equivalence_decision == "PASS"
    assert result.promotion == "FORBIDDEN"


def test_receipt_and_speech_are_deterministic():
    gate = SemanticSpeechGate()
    first = gate.evaluate(_discourse())
    second = gate.evaluate(_discourse())
    assert first.speech == second.speech
    assert first.receipt_sha256 == second.receipt_sha256


def test_missing_semantic_object_fails_closed():
    result = SemanticSpeechGate().evaluate(None)
    assert result.decision is Decision.VETO
    assert result.speech is None
    assert result.reasons == ("SEMANTIC_DISCOURSE_REQUIRED",)


def test_switch_scope_requires_real_negation_cue():
    gate = SemanticSpeechGate()
    assert gate.switches("Il ne change pas le cadre.")[0][1] == "NEGATION"
    assert gate.switches("Il avance d'un pas.") == ()


def test_runtime_exposes_the_same_gate():
    from frame_search import FrameDefinition, FrameSearchEngine
    from zoran_runtime import ZoranRuntime

    runtime = ZoranRuntime(
        frame_engine=FrameSearchEngine(
            (FrameDefinition("local", "Cadre local", ("cadre",)),)
        )
    )
    assert runtime.evaluate_semantic_speech(_discourse()).decision is Decision.PASS
