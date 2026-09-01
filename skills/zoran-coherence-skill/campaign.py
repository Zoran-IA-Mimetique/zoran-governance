from __future__ import annotations

import itertools
import json
from pathlib import Path

from tolerance_skill import (
    Decision,
    DimensionPolicy,
    MulticriteriaToleranceSkill,
    Observation,
    RECOMMENDED_ZERO_TOLERANCE,
    TOLERANCE_FAMILIES,
    TolerancePolicy,
    conservative_default_policy,
    scope_for,
)

ROOT = Path(__file__).resolve().parent


def o(stage, dimension, delta, amp=1.0, metier="generic", frame="local"):
    return Observation(stage, dimension, delta, amp, metier, frame)



def run(skill, observations):
    dims = tuple(dict.fromkeys(item.dimension for item in observations))
    return skill.evaluate(observations, scope=scope_for(*dims))


def all_soft(local=.2, dim=.3, metier=.5, frame=.5, global_=.5):
    return TolerancePolicy(
        dimensions={name: DimensionPolicy(local, dim, 1.0, False, True) for name in TOLERANCE_FAMILIES},
        metier_budgets={"generic": metier},
        frame_budgets={"local": frame, "general": frame},
        global_budget=global_,
    )


def main():
    total = correct = false_pass = false_block = 0
    classes = {}

    def record(expected_pass: bool, actual: Decision, label: str):
        nonlocal total, correct, false_pass, false_block
        total += 1
        observed_pass = actual is Decision.PASS
        if observed_pass == expected_pass:
            correct += 1
        elif observed_pass:
            false_pass += 1
        else:
            false_block += 1
        classes[label] = classes.get(label, 0) + 1

    # 1) All 17 families: clean + local/zero-tolerance exceed.
    policy = conservative_default_policy(soft_local_cap=.1, soft_dimension_budget=10, metier_budget=100, frame_budget=100, global_budget=100)
    skill = MulticriteriaToleranceSkill(policy)
    for dim in TOLERANCE_FAMILIES:
        clean_delta = 0.0 if dim in RECOMMENDED_ZERO_TOLERANCE else .05
        record(True, run(skill, [o("clean", dim, clean_delta)]).decision, "families_clean")
        bad_delta = .001 if dim in RECOMMENDED_ZERO_TOLERANCE else .1001
        record(False, run(skill, [o("bad", dim, bad_delta)]).decision, "families_exceed")

    # 2) All 2^7 zero-tolerance combinations. Empty set passes, every non-empty set vetoes.
    critical = sorted(RECOMMENDED_ZERO_TOLERANCE)
    for bits in itertools.product((0, 1), repeat=len(critical)):
        observations = [o(f"crit-{i}", dim, .0001 if bit else 0.0) for i, (dim, bit) in enumerate(zip(critical, bits))]
        record(not any(bits), run(skill, observations).decision, "critical_combinations")

    # 3) Signed stacking on each soft dimension: no cancellation.
    soft_dims = [d for d in TOLERANCE_FAMILIES if d not in RECOMMENDED_ZERO_TOLERANCE]
    stack_policy = all_soft(local=.1, dim=.2, metier=100, frame=100, global_=100)
    stack_skill = MulticriteriaToleranceSkill(stack_policy)
    values = (-.1, -.05, 0.0, .05, .1)
    for dim in soft_dims:
        for seq in itertools.product(values, repeat=3):
            expected = sum(abs(x) for x in seq) <= .2 and all(abs(x) <= .1 for x in seq)
            observations = [o(f"{dim}-{i}", dim, x) for i, x in enumerate(seq)]
            record(expected, run(stack_skill, observations).decision, "signed_stacking")

    # 4) Cross-dimension global envelope grid: good dimensions never refund global charge.
    grid_policy = all_soft(local=.1, dim=1, metier=1, frame=1, global_=.25)
    grid_skill = MulticriteriaToleranceSkill(grid_policy)
    chosen = soft_dims[:4]
    for vals in itertools.product((0.0, .05, .1), repeat=4):
        expected = sum(abs(v) for v in vals) <= .25
        observations = [o(f"g{i}", d, v) for i, (d, v) in enumerate(zip(chosen, vals))]
        record(expected, run(grid_skill, observations).decision, "global_grid")

    # 5) Exact decimal boundaries.
    boundary_policy = all_soft(local=1, dim=1, metier=1, frame=1, global_=1)
    boundary_skill = MulticriteriaToleranceSkill(boundary_policy)
    decimal_pairs = [
        (.1, .2, .3), (.2, .4, .6), (.3, .6, .9), (.05, .15, .2), (.125, .375, .5),
        (.01, .09, .1), (.333, .667, 1.0), (.025, .075, .1), (.12, .18, .3), (.7, .3, 1.0),
    ]
    for a, b, budget in decimal_pairs:
        p = all_soft(local=1, dim=budget, metier=budget, frame=budget, global_=budget)
        s = MulticriteriaToleranceSkill(p)
        record(True, run(s, [o("a", "semantic", a), o("b", "semantic", b)]).decision, "decimal_boundary")
        record(False, run(s, [o("a", "semantic", a), o("b", "semantic", b), o("x", "semantic", .000001)]).decision, "decimal_over")

    # 6) Transversal domain scenarios.
    metiers = ("btp", "medical", "finance", "software", "text_ai")
    p = conservative_default_policy(metier_ids=metiers, frame_ids=("local", "system", "global"), metier_budget=10, frame_budget=10, global_budget=10)
    s = MulticriteriaToleranceSkill(p)
    scenarios = [
        ("btp", "safety", 0.001),
        ("medical", "factual", 0.001),
        ("finance", "source", 0.001),
        ("software", "integration", 0.101),
        ("text_ai", "intentional", 0.001),
    ]
    for metier, dim, bad_delta in scenarios:
        record(True, run(s, [o("clean", dim, 0, metier=metier, frame="system")]).decision, "domain_clean")
        record(False, run(s, [o("bad", dim, bad_delta, metier=metier, frame="system")]).decision, "domain_corrupt")

    # 7) Deterministic replay 10,000 exact receipt matches.
    replay_case = [o("r1", "semantic", .02), o("r2", "measurement", -.03, frame="general"), o("r3", "factual", 0)]
    expected_receipt = run(skill, replay_case).as_dict()
    replay_mismatches = 0
    for _ in range(10_000):
        if run(skill, replay_case).as_dict() != expected_receipt:
            replay_mismatches += 1

    # 8) Naive weighted average adversary: 16 perfect scores + one critical failure.
    # Average = 16/17 = 94.1176%, while this skill must VETO.
    naive_average = 16 / 17
    adversary = [o(f"adv-{i}", dim, 0.0) for i, dim in enumerate(TOLERANCE_FAMILIES)]
    # flip a single zero-tolerance factual invariant
    adversary[3] = o("adv-factual", "factual", .0001)
    adversary_decision = run(skill, adversary).decision

    results = {
        "component": "MULTICRITERIA_TOLERANCE_SKILL",
        "version": "2.0.0",
        "cases": total,
        "correct": correct,
        "false_pass": false_pass,
        "false_block": false_block,
        "classification_accuracy": correct / total if total else 0,
        "replay_iterations": 10_000,
        "replay_mismatches": replay_mismatches,
        "classes": classes,
        "zero_tolerance_dimensions": critical,
        "soft_dimensions": soft_dims,
        "naive_average_adversary": {
            "naive_weighted_average": naive_average,
            "critical_failures": 1,
            "skill_decision": adversary_decision.value,
        },
    }
    (ROOT / "CAMPAIGN_RESULTS.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(results, indent=2, ensure_ascii=False))

    assert false_pass == 0
    assert false_block == 0
    assert replay_mismatches == 0
    assert adversary_decision is Decision.VETO


if __name__ == "__main__":
    main()
