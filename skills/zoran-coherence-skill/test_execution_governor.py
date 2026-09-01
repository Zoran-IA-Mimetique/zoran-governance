from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from execution_governor import (
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
from frame_search import FrameSearchEngine
from recovery_loop import CycleResult
from terminal_controller import FAIL, PASS as TERMINAL_PASS, RecoveryDirective, TerminalVerdict
from tolerance_skill import Decision
from zoran_runtime import ZoranRuntime


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def request(
    program: str,
    session: str,
    index: int,
    *,
    decision: object = Decision.RETRY,
    phase: str = BUILD,
    material_delta: bool = True,
    tool_calls_delta: int = 1,
    owner: str = "INTERNAL",
    available: bool = True,
    requires_proof: bool = False,
    proof: str | None = None,
) -> ExecutionRequest:
    return ExecutionRequest(
        program_id=program,
        session_id=session,
        phase=phase,
        evaluation_decision=decision,
        state_fingerprint=digest(f"state-{index}"),
        action_fingerprint=digest(f"action-{index}"),
        progress_fingerprint=digest(f"progress-{index}"),
        material_delta=material_delta,
        tool_calls_delta=tool_calls_delta,
        capability_owner=owner,
        capability_available=available,
        requires_external_proof=requires_proof,
        external_proof_sha256=proof,
        checkpoint_sha256=digest(f"checkpoint-{index}"),
    )


class Clock:
    def __init__(self, value: float = 0.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


def test_program_budget_survives_new_governor_and_new_session(tmp_path: Path):
    policy = ExecutionPolicy(max_cycles=2)
    first = ExecutionGovernor(tmp_path, policy=policy, clock=Clock())
    assert first.evaluate(request("P", "chat-1", 1)).execution_state == CONTINUE
    second = ExecutionGovernor(tmp_path, policy=policy, clock=Clock())
    assert second.evaluate(request("P", "chat-2", 2)).execution_state == CONTINUE
    third = ExecutionGovernor(tmp_path, policy=policy, clock=Clock())
    result = third.evaluate(request("P", "chat-3", 3))
    assert result.execution_state == STOP
    assert result.reasons == ("GLOBAL_CYCLE_BUDGET_EXHAUSTED",)
    assert result.cycles_used == 2


def test_session_id_never_names_or_resets_the_journal(tmp_path: Path):
    governor = ExecutionGovernor(tmp_path, clock=Clock())
    governor.evaluate(request("stable-program", "../../chat-a", 1))
    governor.evaluate(request("stable-program", "another-chat", 2))
    journals = tuple(tmp_path.glob("*.jsonl"))
    assert len(journals) == 1
    assert "chat" not in journals[0].name
    assert governor.verify_program_journal("stable-program")[0] == 2


def test_repeated_state_action_stops_before_second_execution(tmp_path: Path):
    governor = ExecutionGovernor(tmp_path, clock=Clock())
    original = request("P", "S1", 1)
    assert governor.evaluate(original).execution_state == CONTINUE
    repeated = ExecutionRequest(**{**original.__dict__, "session_id": "S2"})
    result = governor.evaluate(repeated)
    assert result.execution_state == STOP
    assert result.reasons == ("REPEATED_STATE_ACTION",)


def test_two_consecutive_absent_material_deltas_stop(tmp_path: Path):
    governor = ExecutionGovernor(
        tmp_path,
        policy=ExecutionPolicy(max_no_material_delta=2),
        clock=Clock(),
    )
    first = governor.evaluate(request("P", "S1", 1, material_delta=False))
    second = governor.evaluate(request("P", "S2", 2, material_delta=False))
    assert first.execution_state == CONTINUE
    assert second.execution_state == STOP
    assert second.reasons == ("NO_MATERIAL_DELTA_LIMIT_REACHED",)


def test_material_delta_resets_stagnation_counter(tmp_path: Path):
    governor = ExecutionGovernor(
        tmp_path,
        policy=ExecutionPolicy(max_cycles=4, max_no_material_delta=2),
        clock=Clock(),
    )
    assert governor.evaluate(request("P", "S1", 1, material_delta=False)).no_material_delta_count == 1
    assert governor.evaluate(request("P", "S2", 2, material_delta=True)).no_material_delta_count == 0
    assert governor.evaluate(request("P", "S3", 3, material_delta=False)).execution_state == CONTINUE


def test_missing_external_capability_is_terminal_wait_without_polling(tmp_path: Path):
    governor = ExecutionGovernor(tmp_path, clock=Clock())
    blocked = request(
        "P",
        "S1",
        1,
        phase=PROMOTION,
        owner="CONNECTOR",
        available=False,
        requires_proof=True,
    )
    first = governor.evaluate(blocked)
    replay = ExecutionRequest(**{**blocked.__dict__, "session_id": "S2", "tool_calls_delta": 9})
    second = governor.evaluate(replay)
    assert first.execution_state == WAIT_EXTERNAL
    assert first.terminal and not first.may_auto_retry
    assert first.resume_requires_new_external_evidence
    assert second.receipt_sha256 == first.receipt_sha256
    assert second.journal_head_sha256 == first.journal_head_sha256
    assert governor.verify_program_journal("P")[0] == 1


def test_new_external_proof_can_resume_a_waiting_program_once(tmp_path: Path):
    governor = ExecutionGovernor(tmp_path, clock=Clock())
    blocked = request("P", "S1", 1, phase=PROMOTION, owner="EXTERNAL", available=False, requires_proof=True)
    assert governor.evaluate(blocked).execution_state == WAIT_EXTERNAL
    resumed = request(
        "P",
        "S2",
        1,
        phase=PROMOTION,
        owner="EXTERNAL",
        available=True,
        requires_proof=True,
        proof=digest("signed-proof"),
    )
    assert governor.evaluate(resumed).execution_state == CONTINUE


def test_build_checkpoint_is_not_blocked_by_promotion_signature(tmp_path: Path):
    governor = ExecutionGovernor(tmp_path, clock=Clock())
    result = governor.evaluate(request("P", "S", 1, phase=BUILD, requires_proof=True))
    assert result.execution_state == CONTINUE
    assert result.checkpoint_allowed


def test_promotion_without_required_proof_waits(tmp_path: Path):
    governor = ExecutionGovernor(tmp_path, clock=Clock())
    result = governor.evaluate(request("P", "S", 1, phase=PROMOTION, requires_proof=True))
    assert result.execution_state == WAIT_EXTERNAL
    assert result.reasons == ("PROMOTION_PROOF_REQUIRED",)


def test_pass_is_done_and_veto_is_stop(tmp_path: Path):
    governor = ExecutionGovernor(tmp_path, clock=Clock())
    passed = governor.evaluate(request("pass-program", "S", 1, decision=Decision.PASS))
    vetoed = governor.evaluate(request("veto-program", "S", 1, decision=Decision.VETO))
    assert passed.execution_state == DONE and passed.terminal
    assert vetoed.execution_state == STOP and vetoed.terminal


def test_tool_call_budget_is_persistent_and_non_compensatory(tmp_path: Path):
    governor = ExecutionGovernor(
        tmp_path,
        policy=ExecutionPolicy(max_tool_calls=2),
        clock=Clock(),
    )
    result = governor.evaluate(request("P", "S", 1, tool_calls_delta=3))
    assert result.execution_state == STOP
    assert result.reasons == ("TOOL_CALL_BUDGET_EXHAUSTED",)


def test_wall_clock_budget_survives_session_restart(tmp_path: Path):
    clock = Clock(100.0)
    policy = ExecutionPolicy(max_cycles=4, max_elapsed_seconds=10)
    first = ExecutionGovernor(tmp_path, policy=policy, clock=clock)
    assert first.evaluate(request("P", "S1", 1)).execution_state == CONTINUE
    clock.value = 111.0
    second = ExecutionGovernor(tmp_path, policy=policy, clock=clock)
    result = second.evaluate(request("P", "S2", 2))
    assert result.execution_state == STOP
    assert result.reasons == ("WALL_CLOCK_BUDGET_EXHAUSTED",)


def test_clock_regression_fails_closed(tmp_path: Path):
    clock = Clock(100.0)
    governor = ExecutionGovernor(tmp_path, clock=clock)
    assert governor.evaluate(request("P", "S1", 1)).execution_state == CONTINUE
    clock.value = 99.0
    result = ExecutionGovernor(tmp_path, clock=clock).evaluate(request("P", "S2", 2))
    assert result.execution_state == STOP
    assert result.reasons == ("EXECUTION_CLOCK_REGRESSION",)


def test_journal_is_hash_chained_and_mode_0600(tmp_path: Path):
    governor = ExecutionGovernor(tmp_path, clock=Clock())
    first = governor.evaluate(request("P", "S1", 1))
    second = governor.evaluate(request("P", "S2", 2))
    count, head = governor.verify_program_journal("P")
    assert count == 2 and head == second.journal_head_sha256
    assert first.journal_head_sha256 != second.journal_head_sha256
    assert governor.journal_mode("P") == 0o600


def test_journal_tampering_fails_closed(tmp_path: Path):
    governor = ExecutionGovernor(tmp_path, clock=Clock())
    governor.evaluate(request("P", "S1", 1))
    journal = next(tmp_path.glob("*.jsonl"))
    event = json.loads(journal.read_text(encoding="utf-8"))
    event["cycles_used"] = 0
    journal.write_text(json.dumps(event) + "\n", encoding="utf-8")
    result = ExecutionGovernor(tmp_path, clock=Clock()).evaluate(request("P", "S2", 2))
    assert result.execution_state == STOP
    assert result.reasons == ("EXECUTION_JOURNAL_HASH_INVALID",)


def test_symlink_state_root_is_rejected(tmp_path: Path):
    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)
    with pytest.raises(ValueError):
        ExecutionGovernor(linked)


def test_runtime_recovery_requires_persistent_governor(tmp_path: Path):
    runtime = ZoranRuntime(frame_engine=FrameSearchEngine(()))
    with pytest.raises(RuntimeError):
        runtime.recover_until_terminal(lambda _: None, lambda _directive, _attempt: True)


def test_runtime_recovery_is_authorized_cycle_by_cycle(tmp_path: Path):
    clock = Clock()
    runtime = ZoranRuntime(
        frame_engine=FrameSearchEngine(()),
        execution_state_root=tmp_path,
        execution_clock=clock,
    )
    failed = TerminalVerdict(
        FAIL,
        ("TEST_FAIL",),
        (),
        (RecoveryDirective("LLM", "repair", "TEST_FAIL"),),
        digest("failed-terminal"),
    )
    passed = TerminalVerdict(TERMINAL_PASS, (), (), (), digest("passed-terminal"))

    def cycle(attempt: int) -> CycleResult:
        return CycleResult(failed if attempt == 1 else passed, product="ok" if attempt == 2 else None)

    def execution_request(result: CycleResult, attempt: int) -> ExecutionRequest:
        decision = Decision.PASS if result.terminal.status == TERMINAL_PASS else Decision.RETRY
        return request("runtime-program", "runtime-session", attempt, decision=decision)

    result = runtime.recover_until_terminal(
        cycle,
        lambda _directive, _attempt: True,
        execution_request_factory=execution_request,
    )
    assert result.status == TERMINAL_PASS
    assert result.execution_state == DONE
    assert runtime.execution_governor is not None
    assert runtime.execution_governor.verify_program_journal("runtime-program")[0] == 2
