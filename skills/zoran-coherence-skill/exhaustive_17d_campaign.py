from __future__ import annotations

import json
import multiprocessing as mp
from pathlib import Path

from tolerance_skill import Decision, MulticriteriaToleranceSkill, Observation, RECOMMENDED_ZERO_TOLERANCE, TOLERANCE_FAMILIES, conservative_default_policy, scope_for

ROOT = Path(__file__).resolve().parent
N = len(TOLERANCE_FAMILIES)
TOTAL = 1 << N


def _run_chunk(bounds):
    start, end = bounds
    policy = conservative_default_policy(
        soft_local_cap=.1, soft_dimension_budget=100,
        metier_budget=1000, frame_budget=1000, global_budget=1000,
    )
    skill = MulticriteriaToleranceSkill(policy)
    scope = scope_for(*TOLERANCE_FAMILIES)
    correct = false_pass = false_block = 0
    decision_counts = {d.value: 0 for d in Decision}
    clean = [Observation(f"S{i}", dim, 0.0, 1.0, "generic", "local") for i, dim in enumerate(TOLERANCE_FAMILIES)]
    bad = [
        Observation(f"S{i}", dim, .0001 if dim in RECOMMENDED_ZERO_TOLERANCE else .1001, 1.0, "generic", "local")
        for i, dim in enumerate(TOLERANCE_FAMILIES)
    ]
    for mask in range(start, end):
        observations = [bad[i] if mask & (1 << i) else clean[i] for i in range(N)]
        result = skill.evaluate(observations, scope=scope)
        decision_counts[result.decision.value] += 1
        expected_pass = mask == 0
        observed_pass = result.decision is Decision.PASS
        if expected_pass == observed_pass:
            correct += 1
        elif observed_pass:
            false_pass += 1
        else:
            false_block += 1
    return correct, false_pass, false_block, decision_counts


def main():
    workers = 4
    chunk = (TOTAL + workers - 1) // workers
    bounds = [(i, min(i + chunk, TOTAL)) for i in range(0, TOTAL, chunk)]
    with mp.Pool(processes=workers) as pool:
        parts = pool.map(_run_chunk, bounds)
    correct = sum(x[0] for x in parts)
    false_pass = sum(x[1] for x in parts)
    false_block = sum(x[2] for x in parts)
    decision_counts = {d.value: sum(x[3][d.value] for x in parts) for d in Decision}
    results = {
        "dimensions": N,
        "total_combinations": TOTAL,
        "correct": correct,
        "false_pass": false_pass,
        "false_block": false_block,
        "accuracy": correct / TOTAL,
        "decision_counts": decision_counts,
        "workers": workers,
    }
    (ROOT / "EXHAUSTIVE_17D_RESULTS.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))
    assert correct == TOTAL and false_pass == 0 and false_block == 0


if __name__ == "__main__":
    main()
