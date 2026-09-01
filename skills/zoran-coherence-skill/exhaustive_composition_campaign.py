from __future__ import annotations

import json
import multiprocessing as mp
from pathlib import Path

from action_gate import MulticriteriaActionGate
from progress_guard import ProgressAttempt, ProgressGuard, ProgressPolicy
from tolerance_skill import Decision, MulticriteriaToleranceSkill, Observation, RECOMMENDED_ZERO_TOLERANCE, TOLERANCE_FAMILIES, conservative_default_policy, scope_for

ROOT = Path(__file__).resolve().parent
N = len(TOLERANCE_FAMILIES)
TOTAL_MASKS = 1 << N


def _run_chunk(bounds):
    start, end = bounds
    policy = conservative_default_policy(
        soft_local_cap=.1, soft_dimension_budget=100,
        metier_budget=1000, frame_budget=1000, global_budget=1000,
    )
    tol = MulticriteriaToleranceSkill(policy)
    pg = ProgressGuard(ProgressPolicy(
        objective_id="goal", direction="maximize", target_value=100.0,
        min_absolute_gain=1.0, min_fraction_of_remaining=.05,
        min_gain_per_cost=.1, max_projected_steps=20,
    ))
    gate = MulticriteriaActionGate(tol, pg)
    scope = scope_for(*TOLERANCE_FAMILIES)
    clean = [Observation(f"S{i}", dim, 0.0, 1.0, "generic", "local") for i, dim in enumerate(TOLERANCE_FAMILIES)]
    bad = [
        Observation(f"S{i}", dim, .0001 if dim in RECOMMENDED_ZERO_TOLERANCE else .1001, 1.0, "generic", "local")
        for i, dim in enumerate(TOLERANCE_FAMILIES)
    ]
    productive = ProgressAttempt("P", "STATE", "ACT", "CTX", 65.79, 70.0, 1.0)
    low = ProgressAttempt("L", "STATE2", "ACT2", "CTX", 65.79, 65.80, 1.0)
    total = correct = false_pass = false_block = 0
    for mask in range(start, end):
        observations = [bad[i] if mask & (1 << i) else clean[i] for i in range(N)]
        for kind, progress in (("productive", productive), ("low", low)):
            result = gate.evaluate(observations, scope=scope, progress_attempt=progress)
            expected_pass = mask == 0 and kind == "productive"
            observed_pass = result.decision is Decision.PASS
            total += 1
            correct += int(expected_pass == observed_pass)
            false_pass += int(observed_pass and not expected_pass)
            false_block += int((not observed_pass) and expected_pass)
    return total, correct, false_pass, false_block


def main():
    workers = 4
    chunk = (TOTAL_MASKS + workers - 1) // workers
    bounds = [(i, min(i + chunk, TOTAL_MASKS)) for i in range(0, TOTAL_MASKS, chunk)]
    with mp.Pool(processes=workers) as pool:
        parts = pool.map(_run_chunk, bounds)
    total = sum(x[0] for x in parts)
    correct = sum(x[1] for x in parts)
    false_pass = sum(x[2] for x in parts)
    false_block = sum(x[3] for x in parts)
    result = {
        "component": "MULTICRITERIA_ACTION_GATE",
        "version": "2.0.0",
        "tolerance_masks": TOTAL_MASKS,
        "progress_classes": 2,
        "total_combinations": total,
        "correct": correct,
        "false_pass": false_pass,
        "false_block": false_block,
        "accuracy": correct / total,
        "only_pass_condition": "all_17_tolerances_clean AND productive_progress",
        "workers": workers,
    }
    (ROOT / "EXHAUSTIVE_COMPOSITION_RESULTS.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    assert correct == total and false_pass == 0 and false_block == 0


if __name__ == "__main__":
    main()
