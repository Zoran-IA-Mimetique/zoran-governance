from __future__ import annotations

from action_gate import MulticriteriaActionGate
from progress_guard import ProgressAttempt, ProgressGuard, ProgressPolicy
from tolerance_skill import (
    Decision,
    MulticriteriaToleranceSkill,
    Observation,
    conservative_default_policy,
    scope_for,
)


def clean_tolerance():
    p = conservative_default_policy(metier_ids=("generic",), frame_ids=("general",), metier_budget=100, frame_budget=100, global_budget=100)
    observations = [
        Observation(f"s:{d}", d, 0.0, 1.0, "generic", "general")
        for d in __import__("tolerance_skill").TOLERANCE_FAMILIES
    ]
    return MulticriteriaToleranceSkill(p), observations, scope_for(*__import__("tolerance_skill").TOLERANCE_FAMILIES)


def pg():
    return ProgressGuard(ProgressPolicy("goal", "maximize", 100.0, min_absolute_gain=1.0, min_fraction_of_remaining=0.05, max_projected_steps=20))


def pa(after=70.0):
    return ProgressAttempt("a1", "s1", "act1", "ctx", 65.79, after, 1.0)


def test_clean_tolerance_plus_productive_progress_passes():
    tol, obs, scope = clean_tolerance()
    r = MulticriteriaActionGate(tol, pg()).evaluate(obs, scope=scope, progress_attempt=pa())
    assert r.decision is Decision.PASS


def test_tolerance_veto_cannot_be_compensated_by_huge_progress():
    tol, obs, scope = clean_tolerance()
    obs = list(obs)
    idx = next(i for i, o in enumerate(obs) if o.dimension == "factual")
    obs[idx] = Observation("bad:factual", "factual", 1.0, 1.0, "generic", "general")
    r = MulticriteriaActionGate(tol, pg()).evaluate(obs, scope=scope, progress_attempt=pa(after=100.0))
    assert r.decision is Decision.VETO
    assert r.reasons[0] == "TOLERANCE_GATE_BLOCK"


def test_perfect_tolerances_cannot_compensate_low_progress():
    tol, obs, scope = clean_tolerance()
    r = MulticriteriaActionGate(tol, pg()).evaluate(obs, scope=scope, progress_attempt=pa(after=65.80))
    assert r.decision is Decision.VETO
    assert r.reasons[0] == "PROGRESS_GATE_BLOCK"


def test_action_gate_receipt_is_deterministic():
    tol, obs, scope = clean_tolerance()
    gate = MulticriteriaActionGate(tol, pg())
    x = gate.evaluate(obs, scope=scope, progress_attempt=pa()).receipt_sha256
    y = gate.evaluate(obs, scope=scope, progress_attempt=pa()).receipt_sha256
    assert x == y
