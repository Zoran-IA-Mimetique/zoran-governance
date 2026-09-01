from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


CONTINUE = "CONTINUE"
WAIT_EXTERNAL = "WAIT_EXTERNAL"
STOP = "STOP"
DONE = "DONE"

BUILD = "BUILD"
PROMOTION = "PROMOTION"

PASS = "PASS"
RETRY = "RETRY"
VETO = "VETO"

_SHA256 = re.compile(r"[0-9a-f]{64}")
_ZERO_SHA256 = "0" * 64


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _valid_sha(value: object) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _decision_value(value: object) -> str:
    candidate = getattr(value, "value", value)
    if candidate not in {PASS, RETRY, VETO}:
        raise ValueError("INVALID_EVALUATION_DECISION")
    return str(candidate)


@dataclass(frozen=True)
class ExecutionPolicy:
    """One budget for one program, independent of chat or process boundaries."""

    max_cycles: int = 3
    max_no_material_delta: int = 2
    max_elapsed_seconds: int = 1_200
    max_tool_calls: int = 60

    def __post_init__(self) -> None:
        for name in (
            "max_cycles",
            "max_no_material_delta",
            "max_elapsed_seconds",
            "max_tool_calls",
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"INVALID_EXECUTION_POLICY:{name}")


@dataclass(frozen=True)
class ExecutionRequest:
    program_id: str
    session_id: str
    phase: str
    evaluation_decision: object
    state_fingerprint: str
    action_fingerprint: str
    progress_fingerprint: str | None = None
    material_delta: bool = False
    tool_calls_delta: int = 0
    capability_owner: str = "INTERNAL"
    capability_available: bool = True
    requires_external_proof: bool = False
    external_proof_sha256: str | None = None
    checkpoint_sha256: str | None = None


@dataclass(frozen=True)
class ExecutionReceipt:
    evaluation_decision: str
    execution_state: str
    terminal: bool
    reasons: tuple[str, ...]
    phase: str
    cycles_used: int
    cycles_remaining: int
    no_material_delta_count: int
    tool_calls_used: int
    tool_calls_remaining: int
    elapsed_seconds: int
    checkpoint_allowed: bool
    may_auto_retry: bool
    resume_requires_new_external_evidence: bool
    program_id_sha256: str
    session_id_sha256: str
    journal_head_sha256: str
    receipt_sha256: str

    def as_dict(self) -> dict[str, object]:
        return {
            "component": "zoran.execution-governor-v1",
            "version": "1.0.0",
            **self.__dict__,
            "reasons": list(self.reasons),
        }


class JournalIntegrityError(RuntimeError):
    pass


class ExecutionGovernor:
    """Persistent fail-closed execution scheduler.

    Evaluation keeps the three semantic decisions PASS/RETRY/VETO.  This class
    separately decides whether execution may CONTINUE, must WAIT_EXTERNAL, must
    STOP, or is DONE.  Its append-only hash-chained journal is derived from a
    stable program id, so constructing a new governor in a new session does not
    reset the budget.
    """

    def __init__(
        self,
        state_root: str | Path,
        *,
        policy: ExecutionPolicy | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.state_root = Path(state_root)
        self.policy = policy or ExecutionPolicy()
        self.clock = clock or time.time
        self._ensure_state_root()

    def _ensure_state_root(self) -> None:
        if self.state_root.is_symlink():
            raise ValueError("EXECUTION_STATE_ROOT_SYMLINK_FORBIDDEN")
        self.state_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not self.state_root.is_dir():
            raise ValueError("EXECUTION_STATE_ROOT_NOT_DIRECTORY")
        os.chmod(self.state_root, 0o700)

    def _paths(self, program_id: str) -> tuple[Path, Path]:
        if not isinstance(program_id, str) or not program_id.strip():
            raise ValueError("PROGRAM_ID_REQUIRED")
        stem = hashlib.sha256(program_id.encode("utf-8")).hexdigest()
        return self.state_root / f"{stem}.jsonl", self.state_root / f"{stem}.lock"

    @staticmethod
    def _validate_request(request: ExecutionRequest) -> str:
        if not isinstance(request, ExecutionRequest):
            raise ValueError("EXECUTION_REQUEST_REQUIRED")
        decision = _decision_value(request.evaluation_decision)
        if not isinstance(request.session_id, str) or not request.session_id.strip():
            raise ValueError("SESSION_ID_REQUIRED")
        if request.phase not in {BUILD, PROMOTION}:
            raise ValueError("INVALID_EXECUTION_PHASE")
        if not _valid_sha(request.state_fingerprint):
            raise ValueError("STATE_FINGERPRINT_INVALID")
        if not _valid_sha(request.action_fingerprint):
            raise ValueError("ACTION_FINGERPRINT_INVALID")
        if request.progress_fingerprint is not None and not _valid_sha(request.progress_fingerprint):
            raise ValueError("PROGRESS_FINGERPRINT_INVALID")
        if request.external_proof_sha256 is not None and not _valid_sha(request.external_proof_sha256):
            raise ValueError("EXTERNAL_PROOF_SHA256_INVALID")
        if request.checkpoint_sha256 is not None and not _valid_sha(request.checkpoint_sha256):
            raise ValueError("CHECKPOINT_SHA256_INVALID")
        if not isinstance(request.material_delta, bool):
            raise ValueError("MATERIAL_DELTA_FLAG_INVALID")
        if not isinstance(request.tool_calls_delta, int) or isinstance(request.tool_calls_delta, bool) or request.tool_calls_delta < 0:
            raise ValueError("TOOL_CALLS_DELTA_INVALID")
        if request.capability_owner not in {"INTERNAL", "USER", "CONNECTOR", "EXTERNAL"}:
            raise ValueError("CAPABILITY_OWNER_INVALID")
        if not isinstance(request.capability_available, bool):
            raise ValueError("CAPABILITY_AVAILABLE_FLAG_INVALID")
        if not isinstance(request.requires_external_proof, bool):
            raise ValueError("EXTERNAL_PROOF_REQUIREMENT_FLAG_INVALID")
        return decision

    @staticmethod
    def _load(journal: Path, program_id: str) -> list[dict[str, object]]:
        if not journal.exists():
            return []
        if journal.is_symlink():
            raise JournalIntegrityError("EXECUTION_JOURNAL_SYMLINK_FORBIDDEN")
        if journal.stat().st_size > 4_000_000:
            raise JournalIntegrityError("EXECUTION_JOURNAL_SIZE_LIMIT")
        events: list[dict[str, object]] = []
        prior = _ZERO_SHA256
        with journal.open("r", encoding="utf-8") as handle:
            for expected_sequence, line in enumerate(handle, 1):
                try:
                    event = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise JournalIntegrityError("EXECUTION_JOURNAL_JSON_INVALID") from exc
                if not isinstance(event, dict):
                    raise JournalIntegrityError("EXECUTION_JOURNAL_EVENT_INVALID")
                event_hash = event.get("event_sha256")
                body = {key: value for key, value in event.items() if key != "event_sha256"}
                if event.get("sequence") != expected_sequence:
                    raise JournalIntegrityError("EXECUTION_JOURNAL_SEQUENCE_INVALID")
                if event.get("program_id_sha256") != hashlib.sha256(program_id.encode("utf-8")).hexdigest():
                    raise JournalIntegrityError("EXECUTION_JOURNAL_PROGRAM_MISMATCH")
                if event.get("previous_event_sha256") != prior:
                    raise JournalIntegrityError("EXECUTION_JOURNAL_CHAIN_INVALID")
                if not _valid_sha(event_hash) or event_hash != _sha(body):
                    raise JournalIntegrityError("EXECUTION_JOURNAL_HASH_INVALID")
                prior = str(event_hash)
                events.append(event)
        return events

    @staticmethod
    def _append(journal: Path, event: dict[str, object]) -> dict[str, object]:
        body = dict(event)
        body["event_sha256"] = _sha(body)
        descriptor = os.open(journal, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
            os.write(descriptor, _canonical(body) + b"\n")
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return body

    def _receipt(
        self,
        *,
        request: ExecutionRequest,
        decision: str,
        state: str,
        reasons: tuple[str, ...],
        cycles: int,
        no_delta: int,
        tool_calls: int,
        elapsed: int,
        head: str,
        phase: str | None = None,
        program_id_sha256: str | None = None,
        session_id_sha256: str | None = None,
    ) -> ExecutionReceipt:
        terminal = state in {WAIT_EXTERNAL, STOP, DONE}
        payload = {
            "evaluation_decision": decision,
            "execution_state": state,
            "terminal": terminal,
            "reasons": list(reasons),
            "phase": phase or request.phase,
            "cycles_used": cycles,
            "cycles_remaining": max(0, self.policy.max_cycles - cycles),
            "no_material_delta_count": no_delta,
            "tool_calls_used": tool_calls,
            "tool_calls_remaining": max(0, self.policy.max_tool_calls - tool_calls),
            "elapsed_seconds": elapsed,
            "checkpoint_allowed": (phase or request.phase) == BUILD and state != DONE,
            "may_auto_retry": state == CONTINUE,
            "resume_requires_new_external_evidence": state == WAIT_EXTERNAL,
            "program_id_sha256": program_id_sha256 or hashlib.sha256(request.program_id.encode("utf-8")).hexdigest(),
            "session_id_sha256": session_id_sha256 or hashlib.sha256(request.session_id.encode("utf-8")).hexdigest(),
            "journal_head_sha256": head,
        }
        return ExecutionReceipt(
            evaluation_decision=decision,
            execution_state=state,
            terminal=terminal,
            reasons=tuple(reasons),
            phase=str(payload["phase"]),
            cycles_used=cycles,
            cycles_remaining=int(payload["cycles_remaining"]),
            no_material_delta_count=no_delta,
            tool_calls_used=tool_calls,
            tool_calls_remaining=int(payload["tool_calls_remaining"]),
            elapsed_seconds=elapsed,
            checkpoint_allowed=bool(payload["checkpoint_allowed"]),
            may_auto_retry=bool(payload["may_auto_retry"]),
            resume_requires_new_external_evidence=bool(payload["resume_requires_new_external_evidence"]),
            program_id_sha256=str(payload["program_id_sha256"]),
            session_id_sha256=str(payload["session_id_sha256"]),
            journal_head_sha256=head,
            receipt_sha256=_sha(payload),
        )

    def _from_event(self, request: ExecutionRequest, event: dict[str, object]) -> ExecutionReceipt:
        return self._receipt(
            request=request,
            decision=str(event["evaluation_decision"]),
            state=str(event["execution_state"]),
            reasons=tuple(str(value) for value in event["reasons"]),
            cycles=int(event["cycles_used"]),
            no_delta=int(event["no_material_delta_count"]),
            tool_calls=int(event["tool_calls_used"]),
            elapsed=int(event["elapsed_seconds"]),
            head=str(event["event_sha256"]),
            phase=str(event["phase"]),
            program_id_sha256=str(event["program_id_sha256"]),
            session_id_sha256=str(event["session_id_sha256"]),
        )

    def evaluate(self, request: ExecutionRequest) -> ExecutionReceipt:
        decision = self._validate_request(request)
        journal, lock_path = self._paths(request.program_id)
        lock_descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            os.fchmod(lock_descriptor, 0o600)
            fcntl.flock(lock_descriptor, fcntl.LOCK_EX)
            try:
                events = self._load(journal, request.program_id)
            except JournalIntegrityError as exc:
                return self._receipt(
                    request=request,
                    decision=decision,
                    state=STOP,
                    reasons=(str(exc),),
                    cycles=self.policy.max_cycles,
                    no_delta=self.policy.max_no_material_delta,
                    tool_calls=self.policy.max_tool_calls,
                    elapsed=self.policy.max_elapsed_seconds,
                    head=_ZERO_SHA256,
                )

            last = events[-1] if events else None
            if last and last["execution_state"] in {STOP, DONE}:
                return self._from_event(request, last)

            request_fingerprint = _sha({
                "phase": request.phase,
                "evaluation_decision": decision,
                "state_fingerprint": request.state_fingerprint,
                "action_fingerprint": request.action_fingerprint,
                "progress_fingerprint": request.progress_fingerprint,
                "material_delta": request.material_delta,
                "capability_owner": request.capability_owner,
                "capability_available": request.capability_available,
                "requires_external_proof": request.requires_external_proof,
                "external_proof_sha256": request.external_proof_sha256,
            })
            if last and last["execution_state"] == WAIT_EXTERNAL:
                same_request = request_fingerprint == last["request_fingerprint"]
                prior_proof = last.get("external_proof_sha256")
                new_proof = _valid_sha(request.external_proof_sha256) and request.external_proof_sha256 != prior_proof
                distinct_internal_build = (
                    request.phase == BUILD
                    and request.capability_owner == "INTERNAL"
                    and request.capability_available
                    and not same_request
                )
                if not new_proof and not distinct_internal_build:
                    return self._from_event(request, last)

            cycles = int(last["cycles_used"]) if last else 0
            no_delta = int(last["no_material_delta_count"]) if last else 0
            tool_calls = (int(last["tool_calls_used"]) if last else 0) + request.tool_calls_delta
            started_at = float(events[0]["started_at_epoch"]) if events else float(self.clock())
            now = float(self.clock())
            if now < started_at:
                elapsed = self.policy.max_elapsed_seconds
                clock_reason: tuple[str, ...] = ("EXECUTION_CLOCK_REGRESSION",)
            else:
                elapsed = int(now - started_at)
                clock_reason = ()

            state = CONTINUE
            reasons: tuple[str, ...] = ("MATERIAL_REPAIR_AUTHORIZED",)
            next_cycles = cycles
            next_no_delta = no_delta

            if decision == PASS:
                state, reasons = DONE, ("EVALUATION_PASS",)
            elif decision == VETO:
                state, reasons = STOP, ("EVALUATION_VETO",)
            elif clock_reason:
                state, reasons = STOP, clock_reason
            elif elapsed >= self.policy.max_elapsed_seconds:
                state, reasons = STOP, ("WALL_CLOCK_BUDGET_EXHAUSTED",)
            elif tool_calls > self.policy.max_tool_calls:
                state, reasons = STOP, ("TOOL_CALL_BUDGET_EXHAUSTED",)
            elif request.capability_owner in {"USER", "CONNECTOR", "EXTERNAL"} and not request.capability_available:
                state, reasons = WAIT_EXTERNAL, ("EXTERNAL_CAPABILITY_UNAVAILABLE",)
            elif request.phase == PROMOTION and request.requires_external_proof and not _valid_sha(request.external_proof_sha256):
                state, reasons = WAIT_EXTERNAL, ("PROMOTION_PROOF_REQUIRED",)
            elif cycles >= self.policy.max_cycles:
                state, reasons = STOP, ("GLOBAL_CYCLE_BUDGET_EXHAUSTED",)
            elif any(
                event["execution_state"] == CONTINUE
                and event["state_fingerprint"] == request.state_fingerprint
                and event["action_fingerprint"] == request.action_fingerprint
                for event in events
            ):
                state, reasons = STOP, ("REPEATED_STATE_ACTION",)
            else:
                next_no_delta = 0 if request.material_delta else no_delta + 1
                if next_no_delta >= self.policy.max_no_material_delta:
                    state, reasons = STOP, ("NO_MATERIAL_DELTA_LIMIT_REACHED",)
                else:
                    next_cycles = cycles + 1

            event = {
                "schema": "zoran.execution-journal.v1",
                "sequence": len(events) + 1,
                "previous_event_sha256": str(last["event_sha256"]) if last else _ZERO_SHA256,
                "program_id_sha256": hashlib.sha256(request.program_id.encode("utf-8")).hexdigest(),
                "session_id_sha256": hashlib.sha256(request.session_id.encode("utf-8")).hexdigest(),
                "started_at_epoch": started_at,
                "observed_at_epoch": now,
                "phase": request.phase,
                "evaluation_decision": decision,
                "execution_state": state,
                "reasons": list(reasons),
                "terminal": state in {WAIT_EXTERNAL, STOP, DONE},
                "request_fingerprint": request_fingerprint,
                "state_fingerprint": request.state_fingerprint,
                "action_fingerprint": request.action_fingerprint,
                "progress_fingerprint": request.progress_fingerprint,
                "material_delta": request.material_delta,
                "cycles_used": next_cycles,
                "no_material_delta_count": next_no_delta,
                "tool_calls_used": tool_calls,
                "elapsed_seconds": elapsed,
                "capability_owner": request.capability_owner,
                "capability_available": request.capability_available,
                "requires_external_proof": request.requires_external_proof,
                "external_proof_sha256": request.external_proof_sha256,
                "checkpoint_sha256": request.checkpoint_sha256,
            }
            appended = self._append(journal, event)
            return self._from_event(request, appended)
        finally:
            try:
                fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
            finally:
                os.close(lock_descriptor)

    def verify_program_journal(self, program_id: str) -> tuple[int, str]:
        journal, lock_path = self._paths(program_id)
        lock_descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            os.fchmod(lock_descriptor, 0o600)
            fcntl.flock(lock_descriptor, fcntl.LOCK_EX)
            events = self._load(journal, program_id)
            head = str(events[-1]["event_sha256"]) if events else _ZERO_SHA256
            return len(events), head
        finally:
            try:
                fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
            finally:
                os.close(lock_descriptor)

    def journal_mode(self, program_id: str) -> int | None:
        journal, _ = self._paths(program_id)
        if not journal.exists():
            return None
        return stat.S_IMODE(journal.stat().st_mode)
