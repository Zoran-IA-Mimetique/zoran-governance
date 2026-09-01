from dataclasses import replace

from phenomenal_coherence import (
    CANONICAL_FRAMES,
    SUPERIOR_FRAMES,
    CausalBenefit,
    FrameTransition,
    PhenomenalCoherenceEngine,
    PhenomenalCoherenceRequest,
    PhenomenalSnapshot,
    RegressionException,
    evidence_sha256,
)
from tolerance_skill import Decision


MISSION = "a" * 64
BASELINE = "b" * 64
CANDIDATE = "c" * 64
CONTRACT = "d" * 64


def _transition(frame_id: str, before: float = 10, after: float | None = None) -> FrameTransition:
    if after is None:
        after = 11 if frame_id not in {"lower", "peer"} else 10
    evidence = f"measured transition:{frame_id}:{before}:{after}"
    return FrameTransition(frame_id, before, after, evidence, evidence_sha256(evidence))


def _causal(frame_id: str, observed: float = 11) -> CausalBenefit:
    evidence = f"paired intervention and counterfactual:{frame_id}:{observed}"
    return CausalBenefit(
        frame_id,
        f"intervention:{frame_id}",
        observed,
        observed - 1,
        f"replace intervention and expect no gain:{frame_id}",
        evidence,
        evidence_sha256(evidence),
    )


def make_request(
    *,
    transitions=None,
    causal_benefits=None,
    trajectory=None,
    regression_exceptions=(),
    candidate_sha256=CANDIDATE,
) -> PhenomenalCoherenceRequest:
    transitions = tuple(transitions or (_transition(frame_id) for frame_id in CANONICAL_FRAMES))
    by_frame = {item.frame_id: item for item in transitions}
    if causal_benefits is None:
        causal_benefits = tuple(_causal(frame_id, by_frame[frame_id].after_s) for frame_id in SUPERIOR_FRAMES)
    if trajectory is None and set(by_frame) == set(CANONICAL_FRAMES):
        snapshots = []
        for t in range(3):
            if t == 0:
                scores = {frame_id: by_frame[frame_id].before_s - 1 for frame_id in CANONICAL_FRAMES}
            elif t == 1:
                scores = {frame_id: by_frame[frame_id].before_s for frame_id in CANONICAL_FRAMES}
            else:
                scores = {frame_id: by_frame[frame_id].after_s for frame_id in CANONICAL_FRAMES}
            evidence = f"snapshot:{t}"
            snapshots.append(PhenomenalSnapshot(t, scores, CONTRACT, evidence, evidence_sha256(evidence)))
        trajectory = tuple(snapshots)
    return PhenomenalCoherenceRequest(
        "object",
        MISSION,
        BASELINE,
        candidate_sha256,
        CONTRACT,
        transitions,
        tuple(causal_benefits),
        tuple(trajectory or ()),
        tuple(regression_exceptions),
        "e" * 64,
    )


def _replace_transition(request, frame_id, **changes):
    transitions = tuple(
        replace(item, **changes) if item.frame_id == frame_id else item
        for item in request.transitions
    )
    by_frame = {item.frame_id: item for item in transitions}
    causal = tuple(
        replace(item, observed_after_s=by_frame[item.frame_id].after_s)
        if item.frame_id == frame_id and item.frame_id in SUPERIOR_FRAMES
        else item
        for item in request.causal_benefits
    )
    return make_request(
        transitions=transitions,
        causal_benefits=causal,
        regression_exceptions=request.regression_exceptions,
    )


def _complete_exception(frame_id: str, **changes) -> RegressionException:
    evidence = f"bounded regression exception:{frame_id}"
    item = RegressionException(
        frame_id,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        evidence,
        evidence_sha256(evidence),
    )
    return replace(item, **changes)


def test_complete_phenomenal_trajectory_passes():
    result = PhenomenalCoherenceEngine().evaluate(make_request())
    assert result.decision is Decision.PASS
    assert result.guard_delta_s == "0"
    assert len(result.frame_verdicts) == 6
    assert "PHENOMENAL_COHERENCE_ADMISSIBLE" in result.reasons


def test_logically_identical_input_order_has_identical_receipt():
    request = make_request()
    reordered = replace(
        request,
        transitions=tuple(reversed(request.transitions)),
        causal_benefits=tuple(reversed(request.causal_benefits)),
    )
    engine = PhenomenalCoherenceEngine()
    assert engine.evaluate(request).receipt_sha256 == engine.evaluate(reordered).receipt_sha256


def test_gate_is_mandatory_and_missing_request_is_retry():
    result = PhenomenalCoherenceEngine().evaluate(None)
    assert result.decision is Decision.RETRY
    assert result.reasons[0] == "PHENOMENAL_REQUEST_MISSING"
    assert "OWNER:HOST_RUNTIME" in result.reasons
    assert "NEXT_ACTION:BUILD_REQUEST_FROM_PASSED_RESOURCE_RECEIPT" in result.reasons
    assert "REMAINING_ATTEMPT_BUDGET:1" in result.reasons


def test_self_authored_measurement_without_resource_receipt_is_retry():
    request = replace(make_request(), resource_gate_receipt_sha256="")
    result = PhenomenalCoherenceEngine().evaluate(request)
    assert result.decision is Decision.VETO
    assert "RESOURCE_GATE_RECEIPT_SHA256_INVALID" in result.reasons


def test_missing_frame_is_retry_not_partial_pass():
    request = make_request()
    request = replace(request, transitions=request.transitions[:-1])
    result = PhenomenalCoherenceEngine().evaluate(request)
    assert result.decision is Decision.RETRY
    assert result.reasons == ("FRAME_COVERAGE_INCOMPLETE",)


def test_local_frame_must_strictly_improve():
    request = _replace_transition(make_request(), "local", after_s=10)
    result = PhenomenalCoherenceEngine().evaluate(request)
    assert result.decision is Decision.VETO
    assert "LOCAL_FRAME_NOT_IMPROVED" in result.reasons


def test_lower_or_peer_regression_is_non_compensatory_veto():
    request = _replace_transition(make_request(), "peer", after_s=9)
    result = PhenomenalCoherenceEngine().evaluate(request)
    assert result.decision is Decision.VETO
    assert "UNJUSTIFIED_FRAME_REGRESSION:peer" in result.reasons


def test_complete_bounded_regression_exception_is_traceable():
    request = _replace_transition(make_request(), "peer", after_s=9)
    request = replace(request, regression_exceptions=(_complete_exception("peer"),))
    result = PhenomenalCoherenceEngine().evaluate(request)
    assert result.decision is Decision.PASS
    assert result.guard_delta_s == "-1"
    assert "BOUNDED_REGRESSION_EXCEPTION:peer" in result.reasons


def test_incomplete_regression_exception_cannot_pass():
    request = _replace_transition(make_request(), "peer", after_s=9)
    request = replace(request, regression_exceptions=(_complete_exception("peer", minimal=False),))
    assert PhenomenalCoherenceEngine().evaluate(request).decision is Decision.VETO


def test_critical_invariant_loss_always_vetoes():
    request = _replace_transition(make_request(), "peer", critical_invariant_preserved=False)
    result = PhenomenalCoherenceEngine().evaluate(request)
    assert result.decision is Decision.VETO
    assert "CRITICAL_INVARIANT_REGRESSION:peer" in result.reasons


def test_mandatory_local_and_superior_frames_cannot_be_excluded():
    for frame_id in ("local", *SUPERIOR_FRAMES):
        request = _replace_transition(make_request(), frame_id, affected=False, non_affected_proven=True)
        result = PhenomenalCoherenceEngine().evaluate(request)
        assert result.decision is Decision.VETO
        assert f"MANDATORY_PHENOMENAL_FRAME_EXCLUDED:{frame_id}" in result.reasons


def test_trajectory_evidence_digest_must_match_content():
    request = make_request()
    damaged = replace(request.trajectory[0], evidence="tampered")
    result = PhenomenalCoherenceEngine().evaluate(replace(request, trajectory=(damaged,) + request.trajectory[1:]))
    assert result.decision is Decision.RETRY
    assert result.reasons == ("TRAJECTORY_EVIDENCE_INVALID",)


def test_each_superior_frame_requires_causal_evidence():
    request = make_request()
    request = replace(
        request,
        causal_benefits=tuple(item for item in request.causal_benefits if item.frame_id != "planetary"),
    )
    result = PhenomenalCoherenceEngine().evaluate(request)
    assert result.decision is Decision.RETRY
    assert "CAUSAL_BENEFIT_MISSING:planetary" in result.reasons


def test_non_positive_counterfactual_effect_vetoes():
    request = make_request()
    causal = tuple(
        replace(item, counterfactual_s=item.observed_after_s)
        if item.frame_id == "upper"
        else item
        for item in request.causal_benefits
    )
    result = PhenomenalCoherenceEngine().evaluate(replace(request, causal_benefits=causal))
    assert result.decision is Decision.VETO
    assert "CAUSAL_GAIN_NOT_POSITIVE:upper" in result.reasons


def test_causal_observation_must_bind_the_transition():
    request = make_request()
    causal = tuple(
        replace(item, observed_after_s=12)
        if item.frame_id == "upper"
        else item
        for item in request.causal_benefits
    )
    result = PhenomenalCoherenceEngine().evaluate(replace(request, causal_benefits=causal))
    assert result.decision is Decision.VETO
    assert "CAUSAL_OBSERVED_TRANSITION_MISMATCH:upper" in result.reasons


def test_three_state_trajectory_is_required():
    request = make_request()
    result = PhenomenalCoherenceEngine().evaluate(replace(request, trajectory=request.trajectory[-2:]))
    assert result.decision is Decision.RETRY
    assert result.reasons == ("TRAJECTORY_REQUIRES_THREE_VALIDATED_STATES",)


def test_trajectory_must_bind_before_and_after():
    request = make_request()
    last = replace(request.trajectory[-1], frame_scores={**request.trajectory[-1].frame_scores, "local": 12})
    result = PhenomenalCoherenceEngine().evaluate(replace(request, trajectory=request.trajectory[:-1] + (last,)))
    assert result.decision is Decision.VETO
    assert result.reasons == ("TRAJECTORY_TRANSITION_MISMATCH:local",)


def test_non_finite_and_boolean_scores_never_pass():
    for value in (float("nan"), float("inf"), True):
        request = _replace_transition(make_request(), "local", after_s=value)
        assert PhenomenalCoherenceEngine().evaluate(request).decision is Decision.RETRY


def test_receipt_is_deterministic_and_request_bound():
    engine = PhenomenalCoherenceEngine()
    request = make_request()
    first = engine.evaluate(request)
    second = engine.evaluate(request)
    changed = engine.evaluate(replace(request, candidate_sha256="e" * 64))
    assert first.receipt_sha256 == second.receipt_sha256
    assert changed.receipt_sha256 != first.receipt_sha256


def test_same_baseline_and_candidate_identity_is_rejected():
    result = PhenomenalCoherenceEngine().evaluate(make_request(candidate_sha256=BASELINE))
    assert result.decision is Decision.VETO
    assert "BASELINE_CANDIDATE_IDENTITY_DUPLICATE" in result.reasons
