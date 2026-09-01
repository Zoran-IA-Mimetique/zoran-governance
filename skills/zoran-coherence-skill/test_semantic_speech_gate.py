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


def test_terminal_controller_requires_semantic_speech_receipt():
    from terminal_controller import (
        ControlEvidence,
        PASS,
        REQUIRED_CONTROL_IDS,
        RETRY,
        TerminalController,
    )

    receipt = "a" * 64
    controls = tuple(
        ControlEvidence(control_id, True, True, PASS, receipt, "ok")
        for control_id in REQUIRED_CONTROL_IDS
        if control_id != "semantic_speech_gate"
    )
    trusted = {control.control_id: receipt for control in controls}

    result = TerminalController().evaluate(controls, trusted_receipts=trusted)

    assert result.status == RETRY
    assert "CONTROL_UNDECLARED:semantic_speech_gate" in result.reasons


def test_runtime_final_display_requires_semantic_discourse():
    from frame_search import FrameDefinition, FrameSearchEngine
    from test_host_session_guard import request
    from zoran_runtime import ZoranRuntime

    runtime = ZoranRuntime(
        frame_engine=FrameSearchEngine(
            (FrameDefinition("local", "Cadre local", ("cadre",)),)
        )
    )

    result = runtime.finalize_output(request())

    assert result.decision is Decision.RETRY
    assert result.reasons == ("SEMANTIC_SPEECH_REQUEST_MISSING",)


def test_runtime_final_display_rejects_output_not_generated_by_semantic_gate():
    from frame_search import FrameDefinition, FrameSearchEngine
    from test_host_session_guard import request
    from zoran_runtime import ZoranRuntime

    runtime = ZoranRuntime(
        frame_engine=FrameSearchEngine(
            (FrameDefinition("local", "Cadre local", ("cadre",)),)
        )
    )

    result = runtime.finalize_output(request(), semantic_speech_request=_discourse())

    assert result.decision is Decision.VETO
    assert result.reasons == ("SEMANTIC_SPEECH_OUTPUT_IDENTITY_MISMATCH",)


def test_runtime_keeps_matching_semantic_speech_withheld_without_host_certificate():
    from frame_search import FrameDefinition, FrameSearchEngine
    from host_session_guard import HostSessionRequest
    from zoran_runtime import ZoranRuntime

    speech = SemanticSpeechGate().evaluate(_discourse())
    request = HostSessionRequest(
        "a" * 64,
        "b" * 64,
        speech.speech,
        None,
        "2026-09-01T00:00:00Z",
    )
    runtime = ZoranRuntime(
        frame_engine=FrameSearchEngine(
            (FrameDefinition("local", "Cadre local", ("cadre",)),)
        )
    )

    result = runtime.finalize_output(request, semantic_speech_request=_discourse())

    assert result.decision is Decision.RETRY
    assert result.speech is None
    assert result.semantic_speech_receipt_sha256 == speech.receipt_sha256
    assert result.reasons == ("HOST_SESSION_CERTIFICATE_MISSING",)


def test_full_runtime_requires_semantic_speech_request():
    from test_zoran_runtime_integration_v13_3 import eval_kwargs, runtime

    kwargs = eval_kwargs()
    kwargs["semantic_speech_request"] = None

    result = runtime().evaluate(**kwargs)

    assert result.decision is Decision.RETRY
    assert result.reasons == ("SEMANTIC_SPEECH_REQUEST_MISSING",)


def test_full_runtime_rejects_text_outside_semantic_speech_gate():
    from test_zoran_runtime_integration_v13_3 import eval_kwargs, runtime

    kwargs = eval_kwargs()
    kwargs["semantic_speech_request"] = _discourse()

    result = runtime().evaluate(**kwargs)

    assert result.decision is Decision.VETO
    assert result.reasons == ("SEMANTIC_SPEECH_OUTPUT_IDENTITY_MISMATCH",)
