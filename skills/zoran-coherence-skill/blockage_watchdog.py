from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Sequence

PASS = 'PASS'
STUCK = 'STUCK'
RETRY = 'RETRY'
RESTART_MESSAGE = 'Relance-moi, je suis bloqué.'


def _sha(payload: object) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


@dataclass(frozen=True)
class WatchdogPolicy:
    repeated_state_action_limit: int = 2
    repeated_error_limit: int = 3
    no_progress_limit: int = 3
    max_cycles: int = 8

    def __post_init__(self) -> None:
        for name in ('repeated_state_action_limit', 'repeated_error_limit', 'no_progress_limit', 'max_cycles'):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value,bool) or value < 2:
                raise ValueError(f'INVALID_WATCHDOG_POLICY:{name}')


@dataclass(frozen=True)
class LoopSignal:
    cycle: int
    state_fingerprint: str | None = None
    action_fingerprint: str | None = None
    progress_fingerprint: str | None = None
    error_code: str | None = None
    checkpoint: str | None = None
    terminal_receipt_sha256: str | None = None

    @property
    def state_action_key(self) -> str | None:
        if not self.state_fingerprint or not self.action_fingerprint:
            return None
        return _sha({'state': self.state_fingerprint, 'action': self.action_fingerprint})


@dataclass(frozen=True)
class WatchdogVerdict:
    status: str
    reasons: tuple[str, ...]
    restart_message: str | None
    resume_checkpoint: str | None
    receipt_sha256: str


class BlockageWatchdog:
    """Deterministic loop breaker.

    It never guesses from elapsed wall-clock time alone.  A blockage is emitted
    only from measurable repetition/stagnation signals or the hard cycle bound.
    """

    def __init__(self, policy: WatchdogPolicy | None = None) -> None:
        self.policy = policy or WatchdogPolicy()

    def evaluate(self, history: Sequence[LoopSignal], current: LoopSignal) -> WatchdogVerdict:
        signals = tuple(history) + (current,)
        reasons: list[str] = []

        if any(not isinstance(item.cycle,int) or isinstance(item.cycle,bool) or item.cycle<1 for item in signals):
            reasons.append('CYCLE_INVALID')
        cycles=[item.cycle for item in signals if isinstance(item.cycle,int) and not isinstance(item.cycle,bool)]
        if len(cycles)!=len(set(cycles)) or cycles!=sorted(cycles):reasons.append('CYCLE_SEQUENCE_INVALID')
        for item in signals:
            for value in (item.state_fingerprint,item.action_fingerprint,item.progress_fingerprint,item.error_code,item.checkpoint):
                if value is not None and (not isinstance(value,str) or not value.strip()):reasons.append('SIGNAL_FINGERPRINT_INVALID')
            if item.terminal_receipt_sha256 is not None and not (isinstance(item.terminal_receipt_sha256,str) and re.fullmatch(r'[0-9a-f]{64}',item.terminal_receipt_sha256)):
                reasons.append('TERMINAL_RECEIPT_INVALID')
        trace_pending=not any((current.state_fingerprint,current.action_fingerprint,current.progress_fingerprint,current.error_code,current.terminal_receipt_sha256))

        key = current.state_action_key
        if key is not None:
            repeated = sum(1 for item in signals if item.state_action_key == key)
            if repeated >= self.policy.repeated_state_action_limit:
                reasons.append('REPEATED_STATE_ACTION')

        if current.error_code:
            same_error = 0
            for item in reversed(signals):
                if item.error_code == current.error_code:
                    same_error += 1
                else:
                    break
            if same_error >= self.policy.repeated_error_limit:
                reasons.append('REPEATED_ERROR')

        if current.progress_fingerprint:
            same_progress = 0
            for item in reversed(signals):
                if item.progress_fingerprint == current.progress_fingerprint:
                    same_progress += 1
                else:
                    break
            if same_progress >= self.policy.no_progress_limit:
                reasons.append('NO_NEW_PROGRESS')

        if isinstance(current.cycle,int) and not isinstance(current.cycle,bool) and current.cycle >= self.policy.max_cycles:
            reasons.append('MAX_CYCLE_BOUND_REACHED')

        status = STUCK if reasons else (RETRY if trace_pending else PASS)
        if trace_pending and not reasons:reasons.append('WATCHDOG_SIGNAL_TRACE_PENDING')
        checkpoint = next((x.checkpoint for x in reversed(signals) if x.checkpoint), None)
        payload = {
            'component': 'zoran.blockage-watchdog-v1',
            'status': status,
            'reasons': reasons,
            'restart_message': RESTART_MESSAGE if status == STUCK else None,
            'resume_checkpoint': checkpoint,
            'cycle': current.cycle,
            'policy':self.policy.__dict__,
            'signals':[item.__dict__ for item in signals],
        }
        return WatchdogVerdict(
            status=status,
            reasons=tuple(reasons),
            restart_message=RESTART_MESSAGE if status == STUCK else None,
            resume_checkpoint=checkpoint,
            receipt_sha256=_sha(payload),
        )
