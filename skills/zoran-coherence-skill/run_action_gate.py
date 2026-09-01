from __future__ import annotations

import json
import sys
from pathlib import Path

from action_gate import MulticriteriaActionGate
from progress_guard import ProgressAttempt, ProgressGuard, ProgressHistoryEntry, ProgressPolicy
from run_skill import _load_policy
from tolerance_skill import EvaluationScope, HardContract, MulticriteriaToleranceSkill, Observation, scope_for


def main(path: str) -> int:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    tol_policy = _load_policy(raw["tolerance_policy"])
    contract = HardContract(raw.get("hard_contract", {}))
    observations = [Observation(**item) for item in raw.get("observations", [])]
    scope_raw = raw.get("scope") or {}
    applicable = tuple(scope_raw.get("applicable_dimensions", ()))
    if "excluded_dimensions" in scope_raw:
        scope = EvaluationScope(applicable, scope_raw["excluded_dimensions"])
    else:
        scope = scope_for(*applicable, exclusion_reason=scope_raw.get("exclude_remaining_reason", "NOT_APPLICABLE"))

    progress_policy = ProgressPolicy(**raw["progress_policy"])
    attempt = ProgressAttempt(**raw["progress_attempt"])
    history = tuple(ProgressHistoryEntry(**item) for item in raw.get("progress_history", ()))
    gate = MulticriteriaActionGate(
        MulticriteriaToleranceSkill(tol_policy, contract),
        ProgressGuard(progress_policy),
    )
    result = gate.evaluate(
        observations,
        scope=scope,
        progress_attempt=attempt,
        progress_history=history,
    )
    print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
    return 0 if result.decision.value == "PASS" else 2


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python run_action_gate.py INPUT.json", file=sys.stderr)
        raise SystemExit(64)
    raise SystemExit(main(sys.argv[1]))
