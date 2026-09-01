from __future__ import annotations

import copy
import itertools
from dataclasses import replace

import pytest

from tolerance_skill import (
    Decision,
    DimensionPolicy,
    HardContract,
    MulticriteriaToleranceSkill,
    Observation,
    RECOMMENDED_ZERO_TOLERANCE,
    TOLERANCE_FAMILIES,
    TolerancePolicy,
    conservative_default_policy,
    scope_for,
    EvaluationScope,
)


def obs(stage, dimension, delta, *, amp=1.0, metier="generic", frame="local", measured=True, invariants=None):
    return Observation(
        stage_id=stage,
        dimension=dimension,
        delta=delta,
        amplification=amp,
        metier_id=metier,
        frame_id=frame,
        evidence_measured=measured,
        invariant_observed=invariants or {},
    )



def run(skill, observations):
    dims = tuple(dict.fromkeys(item.dimension for item in observations))
    return skill.evaluate(observations, scope=scope_for(*dims))


def all_soft_policy(*, local=.2, dim=1.0, metier=100.0, frame=100.0, global_=100.0, metiers=("generic",), frames=("local", "general")):
    return TolerancePolicy(
        dimensions={name: DimensionPolicy(local, dim, 1.0, False, True) for name in TOLERANCE_FAMILIES},
        metier_budgets={m: metier for m in metiers},
        frame_budgets={f: frame for f in frames},
        global_budget=global_,
    )


def test_A_all_17_dimensions_accept_clean_case():
    policy = conservative_default_policy()
    skill = MulticriteriaToleranceSkill(policy)
    observations = []
    for i, name in enumerate(TOLERANCE_FAMILIES):
        delta = 0.0 if name in RECOMMENDED_ZERO_TOLERANCE else 0.01
        observations.append(obs(f"S{i}", name, delta))
    result = run(skill, observations)
    assert result.decision is Decision.PASS
    assert len(result.ledger) == 17


def test_B_all_17_dimensions_block_local_exceed_or_zero_tolerance_violation():
    policy = conservative_default_policy(soft_local_cap=0.1, soft_dimension_budget=10.0, metier_budget=100.0, frame_budget=100.0, global_budget=100.0)
    skill = MulticriteriaToleranceSkill(policy)
    for name in TOLERANCE_FAMILIES:
        result = run(skill, [obs("X", name, 0.11 if name not in RECOMMENDED_ZERO_TOLERANCE else 0.001)])
        assert result.decision in {Decision.RETRY, Decision.VETO}, (name, result.as_dict())


def test_C_all_zero_tolerance_dimensions_veto_any_nonzero_drift():
    policy = conservative_default_policy()
    skill = MulticriteriaToleranceSkill(policy)
    for name in sorted(RECOMMENDED_ZERO_TOLERANCE):
        assert run(skill, [obs("Z", name, 0.000001)]).decision is Decision.VETO
        assert run(skill, [obs("Z", name, -0.000001)]).decision is Decision.VETO


def test_D_opposite_drifts_never_cancel():
    policy = all_soft_policy(local=.1, dim=.15)
    skill = MulticriteriaToleranceSkill(policy)
    result = run(skill, [obs("A", "coherence", +.1), obs("B", "coherence", -.1)])
    assert result.decision is Decision.RETRY
    assert result.reasons[0].startswith("DIMENSION_BUDGET_EXCEEDED")


def test_E_cross_dimension_margin_never_compensates_other_dimension():
    policy = all_soft_policy(local=.2, dim=.15)
    skill = MulticriteriaToleranceSkill(policy)
    result = run(skill, [
        obs("A", "semantic", 0.0),
        obs("B", "coherence", 0.1),
        obs("C", "coherence", 0.1),
    ])
    assert result.decision is Decision.RETRY
    assert "coherence" in result.reasons[0]


def test_F_dimension_budget_independent():
    policy = all_soft_policy(local=.2, dim=.15, metier=10, frame=10, global_=10)
    result = run(MulticriteriaToleranceSkill(policy), [obs("A", "semantic", .1), obs("B", "semantic", .1)])
    assert result.decision is Decision.RETRY
    assert result.reasons[0].startswith("DIMENSION_BUDGET_EXCEEDED")


def test_F_metier_budget_independent():
    policy = all_soft_policy(local=.2, dim=10, metier=.15, frame=10, global_=10)
    result = run(MulticriteriaToleranceSkill(policy), [obs("A", "semantic", .1), obs("B", "coherence", .1)])
    assert result.decision is Decision.RETRY
    assert result.reasons[0].startswith("METIER_BUDGET_EXCEEDED")


def test_F_frame_budget_independent():
    policy = all_soft_policy(local=.2, dim=10, metier=10, frame=.15, global_=10)
    result = run(MulticriteriaToleranceSkill(policy), [obs("A", "semantic", .1), obs("B", "coherence", .1)])
    assert result.decision is Decision.RETRY
    assert result.reasons[0].startswith("FRAME_BUDGET_EXCEEDED")


def test_F_global_budget_independent_across_metiers_and_frames():
    policy = all_soft_policy(local=.2, dim=10, metier=10, frame=10, global_=.15, metiers=("a", "b"), frames=("local", "general"))
    result = run(MulticriteriaToleranceSkill(policy), [
        obs("A", "semantic", .1, metier="a", frame="local"),
        obs("B", "coherence", .1, metier="b", frame="general"),
    ])
    assert result.decision is Decision.RETRY
    assert result.reasons[0].startswith("GLOBAL_BUDGET_EXCEEDED")


def test_G_trace_pending_evidence_blocks():
    policy = all_soft_policy()
    result = run(MulticriteriaToleranceSkill(policy), [obs("U", "semantic", .01, measured=False)])
    assert result.decision is Decision.RETRY


def test_G_hard_contract_missing_or_mutated_blocks():
    policy = all_soft_policy()
    skill = MulticriteriaToleranceSkill(policy, HardContract({"identity": "ALPHA", "polarity": "positive"}))
    missing = run(skill, [obs("A", "semantic", 0.0, invariants={"identity": "ALPHA"})])
    mutated = run(skill, [obs("A", "semantic", 0.0, invariants={"identity": "BETA", "polarity": "positive"})])
    clean = run(skill, [obs("A", "semantic", 0.0, invariants={"identity": "ALPHA", "polarity": "positive"})])
    assert missing.decision is Decision.RETRY
    assert mutated.decision is Decision.VETO
    assert clean.decision is Decision.PASS


def test_H_nonzero_drift_without_amplification_blocks_but_zero_drift_is_neutral():
    policy = all_soft_policy()
    skill = MulticriteriaToleranceSkill(policy)
    assert run(skill, [obs("A", "semantic", .01, amp=None)]).decision is Decision.RETRY
    assert run(skill, [obs("B", "semantic", 0.0, amp=None)]).decision is Decision.PASS


def test_I_exact_decimal_boundary_has_no_binary_float_false_block():
    policy = all_soft_policy(local=.2, dim=.3, metier=.3, frame=.3, global_=.3)
    skill = MulticriteriaToleranceSkill(policy)
    exact = run(skill, [obs("A", "semantic", .1), obs("B", "semantic", .2)])
    over = run(skill, [obs("A", "semantic", .1), obs("B", "semantic", .2), obs("C", "semantic", .0001)])
    assert exact.decision is Decision.PASS
    assert over.decision is Decision.RETRY


def test_dynamic_admissible_cap_is_intersection_of_all_remaining_envelopes():
    policy = all_soft_policy(local=.5, dim=.4, metier=.3, frame=.2, global_=.1)
    skill = MulticriteriaToleranceSkill(policy)
    decision, cap, reasons = skill.admissible_next_delta(
        dimension="semantic", metier_id="generic", frame_id="local", amplification=1.0,
        dimension_cost=0.0, metier_cost=0.0, frame_cost=0.0, global_cost=0.0,
    )
    assert decision is Decision.PASS
    assert cap == .1
    assert reasons == ("DYNAMIC_INTERSECTION_CAP",)


def test_J_replay_10000_identical_receipts():
    policy = conservative_default_policy(metier_ids=("generic",), frame_ids=("local", "general"))
    skill = MulticriteriaToleranceSkill(policy)
    corpus = [
        obs("A", "semantic", .02),
        obs("B", "measurement", -.03, frame="general"),
        obs("C", "factual", 0.0),
    ]
    expected = run(skill, corpus).as_dict()
    for _ in range(10_000):
        assert run(skill, corpus).as_dict() == expected


def test_K_transversal_domains_clean_pass_and_critical_corruption_blocks():
    metiers = ("btp", "medical", "finance", "software", "text_ai")
    policy = conservative_default_policy(metier_ids=metiers, frame_ids=("local", "system", "global"), metier_budget=10, frame_budget=10, global_budget=10)
    skill = MulticriteriaToleranceSkill(policy)
    cases = [
        ("btp", "safety"),
        ("medical", "factual"),
        ("finance", "source"),
        ("software", "integration"),
        ("text_ai", "intentional"),
    ]
    for metier, critical_dim in cases:
        clean = run(skill, [obs("clean", critical_dim, 0.0, metier=metier, frame="system")])
        corrupt = run(skill, [obs("bad", critical_dim, 0.001, metier=metier, frame="system")])
        assert clean.decision is Decision.PASS
        # integration is soft by default; force an actual local exceed for that domain.
        if critical_dim == "integration":
            corrupt = run(skill, [obs("bad", critical_dim, 0.2, metier=metier, frame="system")])
        assert corrupt.decision in {Decision.VETO, Decision.RETRY}


def test_L_meta_contract_rejects_compensation_refund_unknown_pass_nondeterminism_or_inexact_boundaries():
    base = all_soft_policy()
    mutations = [
        replace(base, non_compensatory=False),
        replace(base, signed_refunds_allowed=True),
        replace(base, cross_dimension_refunds_allowed=True),
        replace(base, unknown_can_pass=True),
        replace(base, deterministic=False),
        replace(base, exact_boundary_accounting=False),
    ]
    for mutated in mutations:
        assert MulticriteriaToleranceSkill(mutated).evaluate([]).decision is Decision.VETO


def test_L_zero_tolerance_policy_cannot_hide_positive_budget():
    base = conservative_default_policy()
    dims = dict(base.dimensions)
    dims["safety"] = DimensionPolicy(local_cap=.1, dimension_budget=.1, weight=1, zero_tolerance=True)
    mutated = replace(base, dimensions=dims)
    result = MulticriteriaToleranceSkill(mutated).evaluate([])
    assert result.decision is Decision.VETO



def test_applicability_scope_required_and_pass_by_omission_is_blocked():
    skill = MulticriteriaToleranceSkill(all_soft_policy())
    no_scope = skill.evaluate([obs("A", "semantic", 0.0)])
    assert no_scope.decision is Decision.RETRY
    incomplete = EvaluationScope(("semantic",), {})
    assert skill.evaluate([obs("A", "semantic", 0.0)], scope=incomplete).decision is Decision.RETRY
    required_but_missing = scope_for("semantic", "factual")
    assert skill.evaluate([obs("A", "semantic", 0.0)], scope=required_but_missing).decision is Decision.RETRY
    excluded_but_observed = scope_for("semantic")
    result = skill.evaluate([obs("A", "semantic", 0.0), obs("B", "factual", 0.0)], scope=excluded_but_observed)
    assert result.decision is Decision.VETO


def test_receipt_sha_is_stable_and_changes_with_decision_evidence():
    skill = MulticriteriaToleranceSkill(all_soft_policy())
    a = run(skill, [obs("A", "semantic", .01)])
    b = run(skill, [obs("A", "semantic", .01)])
    c = run(skill, [obs("A", "semantic", .02)])
    assert a.receipt_sha256 == b.receipt_sha256
    assert a.receipt_sha256 != c.receipt_sha256


def test_all_nonempty_corruption_combinations_are_noncompensatory():
    # Four representative independent dimensions; every non-empty corruption set must block.
    base = conservative_default_policy(metier_budget=100, frame_budget=100, global_budget=100)
    skill = MulticriteriaToleranceSkill(base)
    dims = ("factual", "source", "intentional", "epistemic")
    for bits in itertools.product((0, 1), repeat=len(dims)):
        observations = [obs(f"{d}-{i}", d, 0.001 if bit else 0.0) for i, (d, bit) in enumerate(zip(dims, bits))]
        result = run(skill, observations)
        assert result.decision is (Decision.PASS if not any(bits) else Decision.VETO)
