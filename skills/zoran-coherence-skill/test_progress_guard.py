from __future__ import annotations

import pytest

from progress_guard import (
    ProgressAttempt,
    ProgressGuard,
    ProgressHistoryEntry,
    ProgressPolicy,
)
from tolerance_skill import Decision


def policy(**overrides):
    base = dict(
        objective_id="reach_100",
        direction="maximize",
        target_value=100.0,
        min_absolute_gain=1.0,
        min_fraction_of_remaining=0.05,
        min_gain_per_cost=0.1,
        completion_tolerance=0.0,
        max_projected_steps=20,
    )
    base.update(overrides)
    return ProgressPolicy(**base)


def attempt(**overrides):
    base = dict(
        attempt_id="A1",
        state_before_fingerprint="S65.79",
        action_fingerprint="ACT_CLOSE_BLOCKERS",
        context_fingerprint="CTX1",
        value_before=65.79,
        value_after=70.0,
        cost=5.0,
        evidence_measured=True,
    )
    base.update(overrides)
    return ProgressAttempt(**base)


def test_significant_progress_passes():
    r = ProgressGuard(policy()).evaluate(attempt())
    assert r.decision is Decision.PASS
    assert r.reasons == ("SIGNIFICANT_PROGRESS",)


def test_exact_stagnation_is_veto():
    r = ProgressGuard(policy()).evaluate(attempt(value_after=65.79))
    assert r.decision is Decision.VETO
    assert "NO_MEASURABLE_PROGRESS" in r.reasons


def test_tiny_gain_relative_to_objective_is_veto():
    r = ProgressGuard(policy()).evaluate(attempt(value_after=65.81))
    assert r.decision is Decision.VETO
    assert "GAIN_BELOW_OBJECTIVE_THRESHOLD" in r.reasons


def test_regression_is_veto():
    r = ProgressGuard(policy()).evaluate(attempt(value_after=64.0))
    assert r.decision is Decision.VETO
    assert "OBJECTIVE_REGRESSION" in r.reasons


def test_same_state_same_action_is_loop_even_if_context_label_changes():
    guard = ProgressGuard(policy())
    first = attempt()
    result = guard.evaluate(first)
    hist = (guard.history_entry(first, result, "S70"),)
    rerun = attempt(attempt_id="A2", context_fingerprint="CTX2", value_after=72.0)
    r = guard.preflight(rerun, hist)
    assert r.decision is Decision.VETO
    assert "REPEATED_STATE_ACTION_LOOP" in r.reasons


def test_same_action_on_new_state_is_allowed_when_productive():
    guard = ProgressGuard(policy())
    first = attempt()
    first_result = guard.evaluate(first)
    hist = (guard.history_entry(first, first_result, "S70"),)
    second = attempt(
        attempt_id="A2",
        state_before_fingerprint="S70",
        value_before=70.0,
        value_after=74.0,
    )
    r = guard.evaluate(second, hist)
    assert r.decision is Decision.PASS


def test_cost_efficiency_can_veto_otherwise_good_gain():
    r = ProgressGuard(policy(min_gain_per_cost=2.0, min_fraction_of_remaining=0.0)).evaluate(
        attempt(value_after=70.0, cost=3.0)
    )
    assert r.decision is Decision.VETO
    assert "GAIN_BELOW_OBJECTIVE_THRESHOLD" in r.reasons


def test_target_completion_overrides_large_step_floor():
    p = policy(min_absolute_gain=10.0, min_fraction_of_remaining=1.0)
    a = attempt(state_before_fingerprint="S99.5", value_before=99.5, value_after=100.0, cost=1.0)
    r = ProgressGuard(p).evaluate(a)
    assert r.decision is Decision.PASS
    assert r.reasons == ("OBJECTIVE_COMPLETED",)


def test_action_after_objective_already_met_is_veto():
    a = attempt(state_before_fingerprint="S100", value_before=100.0, value_after=100.0)
    r = ProgressGuard(policy()).preflight(a)
    assert r.decision is Decision.VETO
    assert "OBJECTIVE_ALREADY_MET" in r.reasons


def test_trace_pending_after_is_retrye():
    a = attempt(value_after=None)
    r = ProgressGuard(policy()).evaluate(a)
    assert r.decision is Decision.RETRY
    assert "VALUE_AFTER_TRACE_PENDING" in r.reasons


def test_trace_pending_evidence_is_retrye():
    r = ProgressGuard(policy()).evaluate(attempt(evidence_measured=False))
    assert r.decision is Decision.RETRY


def test_negative_cost_is_retrye():
    r = ProgressGuard(policy()).evaluate(attempt(cost=-1.0))
    assert r.decision is Decision.RETRY


def test_projected_convergence_too_slow_is_veto():
    # Low absolute/fraction thresholds so velocity rule is the blocker.
    p = policy(min_absolute_gain=0.0, min_fraction_of_remaining=0.0, min_gain_per_cost=0.0, max_projected_steps=5)
    r = ProgressGuard(p).evaluate(attempt(value_after=67.0))
    assert r.decision is Decision.VETO
    assert "PROJECTED_CONVERGENCE_TOO_SLOW" in r.reasons


def test_minimize_direction_pass_and_regression():
    p = ProgressPolicy(
        objective_id="reduce_error",
        direction="minimize",
        target_value=0.0,
        min_absolute_gain=1.0,
        min_fraction_of_remaining=0.05,
        min_gain_per_cost=0.0,
        max_projected_steps=20,
    )
    good = ProgressAttempt("A1", "S20", "FIX", "C", 20.0, 15.0, 1.0)
    bad = ProgressAttempt("A2", "S20b", "BREAK", "C", 20.0, 21.0, 1.0)
    assert ProgressGuard(p).evaluate(good).decision is Decision.PASS
    assert ProgressGuard(p).evaluate(bad).decision is Decision.VETO


@pytest.mark.parametrize(
    "overrides",
    [
        {"objective_id": ""},
        {"direction": "sideways"},
        {"min_absolute_gain": -1.0},
        {"min_fraction_of_remaining": 1.1},
        {"min_gain_per_cost": -1.0},
        {"completion_tolerance": -1.0},
        {"max_projected_steps": 0},
    ],
)
def test_invalid_policy_veto(overrides):
    r = ProgressGuard(policy(**overrides)).evaluate(attempt())
    assert r.decision is Decision.VETO
    assert r.reasons[0] == "PROGRESS_POLICY_INVALID"


def test_replay_10000_identical_receipts():
    g = ProgressGuard(policy())
    a = attempt()
    expected = g.evaluate(a).receipt_sha256
    for _ in range(10_000):
        assert g.evaluate(a).receipt_sha256 == expected
