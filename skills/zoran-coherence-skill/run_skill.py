from __future__ import annotations

import json
import sys
from pathlib import Path

from tolerance_skill import (
    DimensionPolicy,
    HardContract,
    MulticriteriaToleranceSkill,
    Observation,
    TOLERANCE_FAMILIES,
    TolerancePolicy,
    conservative_default_policy,
    EvaluationScope,
    scope_for,
)


def _load_policy(raw):
    preset = raw.get("preset")
    if preset == "conservative_default":
        return conservative_default_policy(
            metier_ids=tuple(raw.get("metier_ids", ["generic"])),
            frame_ids=tuple(raw.get("frame_ids", ["local", "general"])),
            soft_local_cap=raw.get("soft_local_cap", .1),
            soft_dimension_budget=raw.get("soft_dimension_budget", .25),
            metier_budget=raw.get("metier_budget", 2.0),
            frame_budget=raw.get("frame_budget", 2.0),
            global_budget=raw.get("global_budget", 3.0),
        )
    dims = raw.get("dimensions", {})
    return TolerancePolicy(
        dimensions={
            name: DimensionPolicy(**dims[name]) for name in TOLERANCE_FAMILIES if name in dims
        },
        metier_budgets=raw.get("metier_budgets", {}),
        frame_budgets=raw.get("frame_budgets", {}),
        global_budget=raw.get("global_budget", 0),
        non_compensatory=raw.get("non_compensatory", True),
        signed_refunds_allowed=raw.get("signed_refunds_allowed", False),
        cross_dimension_refunds_allowed=raw.get("cross_dimension_refunds_allowed", False),
        unknown_can_pass=raw.get("unknown_can_pass", False),
        deterministic=raw.get("deterministic", True),
        exact_boundary_accounting=raw.get("exact_boundary_accounting", True),
    )


def main(path):
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    policy = _load_policy(raw["policy"])
    contract = HardContract(raw.get("hard_contract", {}))
    observations = [Observation(**item) for item in raw.get("observations", [])]
    scope_raw = raw.get("scope")
    if isinstance(scope_raw, dict) and "applicable_dimensions" in scope_raw:
        applicable = tuple(scope_raw["applicable_dimensions"])
        if "excluded_dimensions" in scope_raw:
            scope = EvaluationScope(applicable, scope_raw["excluded_dimensions"])
        else:
            scope = scope_for(*applicable, exclusion_reason=scope_raw.get("exclude_remaining_reason", "NOT_APPLICABLE"))
    else:
        scope = None
    result = MulticriteriaToleranceSkill(policy, contract).evaluate(observations, scope=scope)
    print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
    return 0 if result.decision.value == "PASS" else 2


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python run_skill.py INPUT.json", file=sys.stderr)
        raise SystemExit(64)
    raise SystemExit(main(sys.argv[1]))
