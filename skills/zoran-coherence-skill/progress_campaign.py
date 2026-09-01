from __future__ import annotations

import json
from progress_guard import ProgressAttempt, ProgressGuard, ProgressHistoryEntry, ProgressPolicy
from tolerance_skill import Decision

POLICY = ProgressPolicy(
    objective_id="campaign_goal",
    direction="maximize",
    target_value=100.0,
    min_absolute_gain=1.0,
    min_fraction_of_remaining=0.05,
    min_gain_per_cost=0.1,
    completion_tolerance=0.0,
    max_projected_steps=20,
)
GUARD = ProgressGuard(POLICY)

counts = {"PASS": 0, "VETO": 0, "RETRY": 0}
correct = 0
false_pass = 0
false_block = 0
cases = 0
classes: dict[str, int] = {}


def check(name: str, attempt: ProgressAttempt, expected: Decision, history=()):
    global correct, false_pass, false_block, cases
    result = GUARD.evaluate(attempt, history)
    cases += 1
    classes[name] = classes.get(name, 0) + 1
    counts[result.decision.value] += 1
    ok = result.decision is expected
    correct += int(ok)
    false_pass += int(result.decision is Decision.PASS and expected is not Decision.PASS)
    false_block += int(result.decision is not Decision.PASS and expected is Decision.PASS)
    if not ok:
        raise AssertionError((name, attempt, expected, result.as_dict()))


N = 10_000
for i in range(N):
    before = 10.0 + (i % 8000) / 100.0  # 10..89.99
    cost = 1.0 + (i % 9)
    base = dict(
        attempt_id=f"A{i}",
        state_before_fingerprint=f"S:{before}:{i}",
        action_fingerprint=f"ACT:{i % 97}",
        context_fingerprint=f"CTX:{i % 53}",
        value_before=before,
        cost=cost,
        evidence_measured=True,
    )

    # 1. exact stagnation
    check("stagnation", ProgressAttempt(value_after=before, **base), Decision.VETO)

    # 2. regression
    check("regression", ProgressAttempt(value_after=before - 0.5, **base), Decision.VETO)

    # Required target-aware gain is at least max(1, 5% remaining, 0.1*cost).
    required = max(1.0, (100.0 - before) * 0.05, 0.1 * cost)

    # 3. low gain: strictly positive but below required and not completing target.
    low = required * 0.5
    check("low_gain", ProgressAttempt(value_after=before + low, **base), Decision.VETO)

    # 4. productive gain: enough to pass both significance and projected-steps rule.
    productive = max(required * 2.0, (100.0 - before) / 15.0)
    after = min(100.0, before + productive)
    check("productive", ProgressAttempt(value_after=after, **base), Decision.PASS)

    # 5. loop: same state + same action was already attempted, even with changed context.
    first = ProgressAttempt(value_after=after, **base)
    first_result = GUARD.evaluate(first)
    hist = (GUARD.history_entry(first, first_result, f"AFTER:{i}"),)
    loop = ProgressAttempt(
        attempt_id=f"L{i}",
        state_before_fingerprint=base["state_before_fingerprint"],
        action_fingerprint=base["action_fingerprint"],
        context_fingerprint=f"NEWCTX:{i}",
        value_before=before,
        value_after=after,
        cost=cost,
        evidence_measured=True,
    )
    check("repeated_transition", loop, Decision.VETO, hist)

    # 6. same action on evolved state remains a valid convergent iteration.
    next_before = after
    if next_before >= 100.0:
        # use a different earlier state that remains below target
        next_before = min(95.0, before + required)
    next_required = max(1.0, (100.0 - next_before) * 0.05, 0.1 * cost)
    next_gain = max(next_required * 2.0, (100.0 - next_before) / 15.0)
    next_after = min(100.0, next_before + next_gain)
    evolved = ProgressAttempt(
        attempt_id=f"E{i}",
        state_before_fingerprint=f"EVOLVED:{next_before}:{i}",
        action_fingerprint=base["action_fingerprint"],
        context_fingerprint=base["context_fingerprint"],
        value_before=next_before,
        value_after=next_after,
        cost=cost,
        evidence_measured=True,
    )
    check("productive_iteration", evolved, Decision.PASS, hist)

result = {
    "component": "MULTICRITERIA_PROGRESS_GUARD",
    "version": "2.0.0",
    "cases": cases,
    "correct": correct,
    "false_pass": false_pass,
    "false_block": false_block,
    "accuracy": correct / cases,
    "classes": classes,
    "decision_counts": counts,
}
print(json.dumps(result, indent=2, ensure_ascii=False))
with open("PROGRESS_CAMPAIGN_RESULTS.json", "w", encoding="utf-8") as f:
    json.dump(result, f, indent=2, ensure_ascii=False)
    f.write("\n")
