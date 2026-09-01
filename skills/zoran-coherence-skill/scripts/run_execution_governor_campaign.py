#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from execution_governor import (  # noqa: E402
    BUILD,
    CONTINUE,
    DONE,
    PROMOTION,
    STOP,
    WAIT_EXTERNAL,
    ExecutionGovernor,
    ExecutionPolicy,
    ExecutionRequest,
)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class Clock:
    def __init__(self, value: float = 0.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


def req(
    program: str,
    session: str,
    index: int,
    *,
    decision: str = "RETRY",
    phase: str = BUILD,
    material: bool = True,
    tools: int = 1,
    owner: str = "INTERNAL",
    available: bool = True,
    proof_required: bool = False,
) -> ExecutionRequest:
    return ExecutionRequest(
        program,
        session,
        phase,
        decision,
        digest(f"state:{index}"),
        digest(f"action:{index}"),
        digest(f"progress:{index}"),
        material,
        tools,
        owner,
        available,
        proof_required,
        None,
        digest(f"checkpoint:{index}"),
    )


def observed(category: str, root: Path, suffix: str) -> str:
    program = f"{category}:{suffix}"
    clock = Clock()
    governor = ExecutionGovernor(root, clock=clock)
    if category == "session_budget":
        policy = ExecutionPolicy(max_cycles=1)
        ExecutionGovernor(root, policy=policy, clock=clock).evaluate(req(program, "chat-a", 1))
        return ExecutionGovernor(root, policy=policy, clock=clock).evaluate(req(program, "chat-b", 2)).execution_state
    if category == "repeated_state_action":
        original = req(program, "chat-a", 1)
        governor.evaluate(original)
        replay = ExecutionRequest(**{**original.__dict__, "session_id": "chat-b"})
        return governor.evaluate(replay).execution_state
    if category == "no_material_delta":
        policy = ExecutionPolicy(max_no_material_delta=2)
        governed = ExecutionGovernor(root, policy=policy, clock=clock)
        governed.evaluate(req(program, "chat-a", 1, material=False))
        return governed.evaluate(req(program, "chat-b", 2, material=False)).execution_state
    if category == "external_capability":
        return governor.evaluate(req(program, "chat", 1, phase=PROMOTION, owner="CONNECTOR", available=False)).execution_state
    if category == "wait_no_poll":
        blocked = req(program, "chat-a", 1, phase=PROMOTION, owner="EXTERNAL", available=False)
        first = governor.evaluate(blocked)
        replay = ExecutionRequest(**{**blocked.__dict__, "session_id": "chat-b", "tool_calls_delta": 9})
        second = governor.evaluate(replay)
        count, _ = governor.verify_program_journal(program)
        return WAIT_EXTERNAL if first.receipt_sha256 == second.receipt_sha256 and count == 1 else CONTINUE
    if category == "build_without_promotion_proof":
        return governor.evaluate(req(program, "chat", 1, phase=BUILD, proof_required=True)).execution_state
    if category == "promotion_without_proof":
        return governor.evaluate(req(program, "chat", 1, phase=PROMOTION, proof_required=True)).execution_state
    if category == "wall_clock":
        policy = ExecutionPolicy(max_cycles=4, max_elapsed_seconds=10)
        governed = ExecutionGovernor(root, policy=policy, clock=clock)
        governed.evaluate(req(program, "chat-a", 1))
        clock.value = 11.0
        return ExecutionGovernor(root, policy=policy, clock=clock).evaluate(req(program, "chat-b", 2)).execution_state
    if category == "tool_budget":
        governed = ExecutionGovernor(root, policy=ExecutionPolicy(max_tool_calls=1), clock=clock)
        return governed.evaluate(req(program, "chat", 1, tools=2)).execution_state
    if category == "veto":
        return governor.evaluate(req(program, "chat", 1, decision="VETO")).execution_state
    if category == "pass":
        return governor.evaluate(req(program, "chat", 1, decision="PASS")).execution_state
    if category == "journal_tamper":
        governor.evaluate(req(program, "chat-a", 1))
        journal = next(root.glob("*.jsonl"))
        event = json.loads(journal.read_text(encoding="utf-8"))
        event["cycles_used"] = 0
        journal.write_text(json.dumps(event) + "\n", encoding="utf-8")
        return ExecutionGovernor(root, clock=clock).evaluate(req(program, "chat-b", 2)).execution_state
    raise ValueError(f"UNKNOWN_CATEGORY:{category}")


EXPECTED = {
    "session_budget": STOP,
    "repeated_state_action": STOP,
    "no_material_delta": STOP,
    "external_capability": WAIT_EXTERNAL,
    "wait_no_poll": WAIT_EXTERNAL,
    "build_without_promotion_proof": CONTINUE,
    "promotion_without_proof": WAIT_EXTERNAL,
    "wall_clock": STOP,
    "tool_budget": STOP,
    "veto": STOP,
    "pass": DONE,
    "journal_tamper": STOP,
}


def campaign(cases_per_category: int) -> dict[str, object]:
    if cases_per_category < 1:
        raise ValueError("CASES_PER_CATEGORY_INVALID")
    rows = []
    with tempfile.TemporaryDirectory(prefix="zoran-execution-campaign-") as temporary:
        base = Path(temporary)
        for category, expected in EXPECTED.items():
            for index in range(cases_per_category):
                case_root = base / f"{category}-{index}"
                actual = observed(category, case_root, str(index))
                rows.append((category, index, expected, actual, expected == actual))
    failed = [row for row in rows if not row[-1]]
    payload = {
        "component": "ZORAN_EXECUTION_GOVERNOR_CAMPAIGN",
        "version": "1.0.0",
        "categories": len(EXPECTED),
        "cases_per_category": cases_per_category,
        "total_cases": len(rows),
        "passed": len(rows) - len(failed),
        "failed": len(failed),
        "failures": [list(row[:-1]) for row in failed],
        "case_set_sha256": hashlib.sha256(
            json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
    }
    payload["verdict"] = "PASS" if not failed else "FAIL"
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases-per-category", type=int, default=100)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = campaign(args.cases_per_category)
    raw = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(raw, encoding="utf-8")
    print(raw, end="")
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
