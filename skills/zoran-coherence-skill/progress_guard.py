from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from math import isfinite
from typing import Any, Sequence

from tolerance_skill import Decision

COMPONENT_ID = "MULTICRITERIA_PROGRESS_GUARD"
VERSION = "11.0.0"


@dataclass(frozen=True)
class ProgressPolicy:
    objective_id: str
    direction: str  # maximize | minimize
    target_value: float
    min_absolute_gain: float = 0.0
    min_fraction_of_remaining: float = 0.0
    min_gain_per_cost: float = 0.0
    completion_tolerance: float = 0.0
    max_projected_steps: int | None = None

    def validate(self) -> tuple[Decision, tuple[str, ...]]:
        reasons: list[str] = []
        if not isinstance(self.objective_id, str) or not self.objective_id.strip():
            reasons.append("OBJECTIVE_ID_REQUIRED")
        if self.direction not in {"maximize", "minimize"}:
            reasons.append("INVALID_DIRECTION")
        for name in (
            "target_value",
            "min_absolute_gain",
            "min_fraction_of_remaining",
            "min_gain_per_cost",
            "completion_tolerance",
        ):
            value = getattr(self, name)
            if not _valid_finite(value):
                reasons.append(f"INVALID_{name.upper()}")
        if _valid_finite(self.min_absolute_gain) and self.min_absolute_gain < 0:
            reasons.append("NEGATIVE_MIN_ABSOLUTE_GAIN")
        if _valid_finite(self.min_fraction_of_remaining) and not (0 <= self.min_fraction_of_remaining <= 1):
            reasons.append("INVALID_MIN_FRACTION_OF_REMAINING")
        if _valid_finite(self.min_gain_per_cost) and self.min_gain_per_cost < 0:
            reasons.append("NEGATIVE_MIN_GAIN_PER_COST")
        if _valid_finite(self.completion_tolerance) and self.completion_tolerance < 0:
            reasons.append("NEGATIVE_COMPLETION_TOLERANCE")
        if self.max_projected_steps is not None and (
            not isinstance(self.max_projected_steps, int) or isinstance(self.max_projected_steps, bool) or self.max_projected_steps <= 0
        ):
            reasons.append("INVALID_MAX_PROJECTED_STEPS")
        return (Decision.VETO if reasons else Decision.PASS, tuple(reasons))


@dataclass(frozen=True)
class AtomicBundleProof:
    """Proof that a zero/marginal sub-step belongs to a significant atomic plan.

    The bundle, not the sub-step, is the autonomous unit of value. This preserves
    the rule "no autonomous zero-gain work" while allowing an indispensable
    preparatory sub-step inside a preregistered, bounded, causally necessary plan.
    """

    bundle_id: str
    step_id: str
    step_index: int
    step_count: int
    expected_total_gain: float
    min_required_total_gain: float
    expected_total_cost: float
    max_total_cost: float
    evidence_id: str
    preregistered: bool = True
    causal_dependency: bool = True

    def validate(self) -> tuple[str, ...]:
        reasons: list[str] = []
        for name in ("bundle_id", "step_id", "evidence_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                reasons.append(f"BUNDLE_{name.upper()}_REQUIRED")
        if not isinstance(self.step_index, int) or isinstance(self.step_index, bool) or self.step_index < 0:
            reasons.append("BUNDLE_STEP_INDEX_INVALID")
        if not isinstance(self.step_count, int) or isinstance(self.step_count, bool) or self.step_count < 2:
            reasons.append("BUNDLE_STEP_COUNT_INVALID")
        elif isinstance(self.step_index, int) and self.step_index >= self.step_count:
            reasons.append("BUNDLE_STEP_INDEX_OUT_OF_RANGE")
        for name in ("expected_total_gain", "min_required_total_gain", "expected_total_cost", "max_total_cost"):
            if not _valid_finite(getattr(self, name)):
                reasons.append(f"BUNDLE_{name.upper()}_INVALID")
        if _valid_finite(self.min_required_total_gain) and self.min_required_total_gain <= 0:
            reasons.append("BUNDLE_MIN_REQUIRED_GAIN_NOT_POSITIVE")
        if _valid_finite(self.expected_total_gain) and _valid_finite(self.min_required_total_gain) and self.expected_total_gain < self.min_required_total_gain:
            reasons.append("BUNDLE_TOTAL_GAIN_BELOW_THRESHOLD")
        if _valid_finite(self.expected_total_cost) and self.expected_total_cost < 0:
            reasons.append("BUNDLE_EXPECTED_COST_NEGATIVE")
        if _valid_finite(self.max_total_cost) and self.max_total_cost < 0:
            reasons.append("BUNDLE_MAX_COST_NEGATIVE")
        if _valid_finite(self.expected_total_cost) and _valid_finite(self.max_total_cost) and self.expected_total_cost > self.max_total_cost:
            reasons.append("BUNDLE_COST_UNBOUNDED")
        if self.preregistered is not True:
            reasons.append("BUNDLE_NOT_PREREGISTERED")
        if self.causal_dependency is not True:
            reasons.append("BUNDLE_CAUSAL_DEPENDENCY_UNPROVEN")
        if not re.fullmatch(r"[0-9a-f]{64}",self.evidence_id):
            reasons.append("BUNDLE_EVIDENCE_RECEIPT_INVALID")
        return tuple(reasons)


@dataclass(frozen=True)
class ProgressAttempt:
    attempt_id: str
    state_before_fingerprint: str
    action_fingerprint: str
    context_fingerprint: str
    value_before: float
    value_after: float | None
    cost: float | None
    evidence_measured: bool = True
    atomic_bundle: AtomicBundleProof | None = None

    @property
    def loop_key(self) -> str:
        # State fingerprint is required to include all materially relevant context/evidence.
        # Therefore identical state + identical action is a loop, full stop.
        return "|".join((self.state_before_fingerprint, self.action_fingerprint))


@dataclass(frozen=True)
class ProgressHistoryEntry:
    loop_key: str
    state_after_fingerprint: str
    decision: str
    receipt_sha256: str
    bundle_id: str | None = None
    bundle_step_id: str | None = None
    bundle_step_index: int | None = None


@dataclass(frozen=True)
class ProgressEvaluation:
    decision: Decision
    reasons: tuple[str, ...]
    objective_id: str
    directional_gain: str | None
    required_gain: str | None
    remaining_before: str | None
    remaining_after: str | None
    gain_per_cost: str | None
    projected_steps: str | None
    loop_key: str
    receipt_sha256: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "component": COMPONENT_ID,
            "version": VERSION,
            "decision": self.decision.value,
            "reasons": list(self.reasons),
            "objective_id": self.objective_id,
            "directional_gain": self.directional_gain,
            "required_gain": self.required_gain,
            "remaining_before": self.remaining_before,
            "remaining_after": self.remaining_after,
            "gain_per_cost": self.gain_per_cost,
            "projected_steps": self.projected_steps,
            "loop_key": self.loop_key,
            "receipt_sha256": self.receipt_sha256,
        }


class ProgressGuard:
    """Fail-closed sequence guard for productive iteration.

    It blocks two classes of loops:
      * incoherent repetition: same state + action already attempted;
      * coherent but insufficient progress: measured gain below the preregistered
        target-aware threshold or below the required gain/cost efficiency.

    A repeated action is allowed on a *new state* when it continues a productive
    convergence. The guard therefore forbids repeated transitions, not iteration itself.
    """

    def __init__(self, policy: ProgressPolicy, *, trusted_bundle_receipts: Sequence[str] = ()):
        self.policy = policy
        self.trusted_bundle_receipts = frozenset(trusted_bundle_receipts)
        if any(not re.fullmatch(r"[0-9a-f]{64}",x) for x in self.trusted_bundle_receipts):
            raise ValueError("trusted bundle receipts must be SHA-256")
        self._policy_validation = policy.validate()

    def preflight(self, attempt: ProgressAttempt, history: Sequence[ProgressHistoryEntry] = ()) -> ProgressEvaluation:
        history=tuple(history)
        meta, reasons = self._policy_validation
        if meta is not Decision.PASS:
            return self._finish(Decision.VETO, ("PROGRESS_POLICY_INVALID",) + reasons, attempt, history=history)
        bad_input = self._validate_attempt_base(attempt, require_after=False)
        if bad_input:
            return self._finish(Decision.RETRY, bad_input, attempt, history=history)
        bad_history=self._validate_history(history)
        if bad_history:
            return self._finish(Decision.RETRY,bad_history,attempt,history=history)
        bundle_sequence=self._bundle_sequence_status(attempt.atomic_bundle,history)
        if bundle_sequence is not None:
            decision,reason=bundle_sequence
            return self._finish(decision,(reason,),attempt,history=history)
        if self._objective_met(_q(attempt.value_before)):
            return self._finish(Decision.VETO, ("OBJECTIVE_ALREADY_MET",), attempt, history=history)
        if any(item.loop_key == attempt.loop_key for item in history):
            return self._finish(Decision.VETO, ("REPEATED_STATE_ACTION_LOOP",), attempt, history=history)
        return self._finish(Decision.PASS, ("PREFLIGHT_PROGRESS_ADMISSIBLE",), attempt, history=history)

    def evaluate(self, attempt: ProgressAttempt, history: Sequence[ProgressHistoryEntry] = ()) -> ProgressEvaluation:
        history=tuple(history)
        pre = self.preflight(attempt, history)
        if pre.decision is not Decision.PASS:
            return pre
        bad_input = self._validate_attempt_base(attempt, require_after=True)
        if bad_input:
            return self._finish(Decision.RETRY, bad_input, attempt, history=history)

        before = _q(attempt.value_before)
        after = _q(attempt.value_after)
        cost = _q(attempt.cost)
        target = _q(self.policy.target_value)
        completion_tol = _q(self.policy.completion_tolerance)

        gain = after - before if self.policy.direction == "maximize" else before - after
        remaining_before = max(Fraction(0), target - before) if self.policy.direction == "maximize" else max(Fraction(0), before - target)
        remaining_after = max(Fraction(0), target - after) if self.policy.direction == "maximize" else max(Fraction(0), after - target)

        reached_target = remaining_after <= completion_tol
        bundle_ok = self._bundle_valid(attempt.atomic_bundle)
        if gain < 0:
            return self._finish(
                Decision.VETO,
                ("OBJECTIVE_REGRESSION",),
                attempt,
                history=history,
                gain=gain,
                remaining_before=remaining_before,
                remaining_after=remaining_after,
            )
        if gain == 0 and not reached_target:
            if bundle_ok:
                return self._finish(
                    Decision.PASS,
                    ("ATOMIC_BUNDLE_PREPARATORY_STEP",),
                    attempt,
                    history=history,
                    gain=gain,
                    required=Fraction(0),
                    remaining_before=remaining_before,
                    remaining_after=remaining_after,
                )
            return self._finish(
                Decision.VETO,
                ("NO_MEASURABLE_PROGRESS",),
                attempt,
                history=history,
                gain=gain,
                remaining_before=remaining_before,
                remaining_after=remaining_after,
            )

        required_abs = _q(self.policy.min_absolute_gain)
        required_fraction = remaining_before * _q(self.policy.min_fraction_of_remaining)
        required_cost = cost * _q(self.policy.min_gain_per_cost)
        required = max(required_abs, required_fraction, required_cost)

        gain_per_cost: Fraction | None
        if cost == 0:
            gain_per_cost = None if gain == 0 else Fraction(10**18)
        else:
            gain_per_cost = gain / cost

        if not reached_target and gain < required:
            if bundle_ok:
                return self._finish(
                    Decision.PASS,
                    ("ATOMIC_BUNDLE_MARGINAL_STEP",),
                    attempt,
                    history=history,
                    gain=gain,
                    required=required,
                    remaining_before=remaining_before,
                    remaining_after=remaining_after,
                    gain_per_cost=gain_per_cost,
                )
            return self._finish(
                Decision.VETO,
                ("GAIN_BELOW_OBJECTIVE_THRESHOLD",),
                attempt,
                history=history,
                gain=gain,
                required=required,
                remaining_before=remaining_before,
                remaining_after=remaining_after,
                gain_per_cost=gain_per_cost,
            )

        projected_steps: Fraction | None = None
        if remaining_after > 0 and gain > 0:
            projected_steps = remaining_after / gain
            if self.policy.max_projected_steps is not None and projected_steps > self.policy.max_projected_steps:
                return self._finish(
                    Decision.VETO,
                    ("PROJECTED_CONVERGENCE_TOO_SLOW",),
                    attempt,
                    history=history,
                    gain=gain,
                    required=required,
                    remaining_before=remaining_before,
                    remaining_after=remaining_after,
                    gain_per_cost=gain_per_cost,
                    projected_steps=projected_steps,
                )

        reason = "OBJECTIVE_COMPLETED" if reached_target else "SIGNIFICANT_PROGRESS"
        return self._finish(
            Decision.PASS,
            (reason,),
            attempt,
            history=history,
            gain=gain,
            required=required,
            remaining_before=remaining_before,
            remaining_after=remaining_after,
            gain_per_cost=gain_per_cost,
            projected_steps=projected_steps,
        )

    def history_entry(self, attempt: ProgressAttempt, result: ProgressEvaluation, state_after_fingerprint: str) -> ProgressHistoryEntry:
        bundle=attempt.atomic_bundle
        return ProgressHistoryEntry(
            loop_key=attempt.loop_key,
            state_after_fingerprint=state_after_fingerprint,
            decision=result.decision.value,
            receipt_sha256=result.receipt_sha256,
            bundle_id=None if bundle is None else bundle.bundle_id,
            bundle_step_id=None if bundle is None else bundle.step_id,
            bundle_step_index=None if bundle is None else bundle.step_index,
        )

    def _validate_attempt_base(self, attempt: ProgressAttempt, *, require_after: bool) -> tuple[str, ...]:
        reasons: list[str] = []
        if attempt.evidence_measured is not True:
            reasons.append("PROGRESS_EVIDENCE_TRACE_PENDING")
        for name in ("attempt_id", "state_before_fingerprint", "action_fingerprint", "context_fingerprint"):
            value = getattr(attempt, name)
            if not isinstance(value, str) or not value.strip():
                reasons.append(f"{name.upper()}_REQUIRED")
        if not _valid_finite(attempt.value_before):
            reasons.append("VALUE_BEFORE_TRACE_PENDING")
        if attempt.atomic_bundle is not None:
            bundle_reasons = attempt.atomic_bundle.validate()
            if bundle_reasons:
                reasons.append("ATOMIC_BUNDLE_INVALID")
                reasons.extend(bundle_reasons)
            elif attempt.atomic_bundle.evidence_id not in self.trusted_bundle_receipts:
                reasons.append("ATOMIC_BUNDLE_RECEIPT_UNTRUSTED")
        if require_after:
            if attempt.value_after is None or not _valid_finite(attempt.value_after):
                reasons.append("VALUE_AFTER_TRACE_PENDING")
            if attempt.cost is None or not _valid_finite(attempt.cost) or attempt.cost < 0:
                reasons.append("COST_TRACE_PENDING_OR_INVALID")
        return tuple(reasons)

    def _bundle_valid(self, bundle: AtomicBundleProof | None) -> bool:
        return bundle is not None and not bundle.validate() and bundle.evidence_id in self.trusted_bundle_receipts

    @staticmethod
    def _validate_history(history:Sequence[ProgressHistoryEntry])->tuple[str,...]:
        reasons=[]
        for item in history:
            if not isinstance(item,ProgressHistoryEntry):
                reasons.append('PROGRESS_HISTORY_ENTRY_INVALID'); continue
            if not item.loop_key or not item.state_after_fingerprint or item.decision not in {x.value for x in Decision} or not re.fullmatch(r'[0-9a-f]{64}',item.receipt_sha256):
                reasons.append('PROGRESS_HISTORY_ENTRY_INVALID')
            bundle_values=(item.bundle_id,item.bundle_step_id,item.bundle_step_index)
            if any(value is not None for value in bundle_values) and (not isinstance(item.bundle_id,str) or not item.bundle_id.strip() or not isinstance(item.bundle_step_id,str) or not item.bundle_step_id.strip() or not isinstance(item.bundle_step_index,int) or isinstance(item.bundle_step_index,bool) or item.bundle_step_index<0):
                reasons.append('PROGRESS_HISTORY_BUNDLE_INVALID')
        return tuple(reasons)

    @staticmethod
    def _bundle_sequence_status(bundle:AtomicBundleProof|None,history:Sequence[ProgressHistoryEntry])->tuple[Decision,str]|None:
        if bundle is None:return None
        related=[item for item in history if item.bundle_id==bundle.bundle_id]
        if any(item.bundle_step_id==bundle.step_id or item.bundle_step_index==bundle.step_index for item in related):
            return Decision.VETO,'ATOMIC_BUNDLE_STEP_REPLAY'
        if bundle.step_index==0:
            return None if not related else (Decision.VETO,'ATOMIC_BUNDLE_SEQUENCE_RESTART')
        if not related or max(item.bundle_step_index for item in related)!=bundle.step_index-1:
            return Decision.RETRY,'ATOMIC_BUNDLE_PREVIOUS_STEP_TRACE_PENDING'
        return None

    def _objective_met(self, before: Fraction) -> bool:
        target = _q(self.policy.target_value)
        tol = _q(self.policy.completion_tolerance)
        if self.policy.direction == "maximize":
            return before >= target - tol
        return before <= target + tol

    def _finish(
        self,
        decision: Decision,
        reasons: tuple[str, ...],
        attempt: ProgressAttempt,
        *,
        history: Sequence[ProgressHistoryEntry] = (),
        gain: Fraction | None = None,
        required: Fraction | None = None,
        remaining_before: Fraction | None = None,
        remaining_after: Fraction | None = None,
        gain_per_cost: Fraction | None = None,
        projected_steps: Fraction | None = None,
    ) -> ProgressEvaluation:
        payload = {
            "component": COMPONENT_ID,
            "version": VERSION,
            "decision": decision.value,
            "reasons": list(reasons),
            "objective_id": self.policy.objective_id,
            "direction": self.policy.direction,
            "target_value": str(self.policy.target_value),
            "policy": self.policy.__dict__,
            "attempt": {
                "attempt_id": attempt.attempt_id,
                "state_before_fingerprint": attempt.state_before_fingerprint,
                "action_fingerprint": attempt.action_fingerprint,
                "context_fingerprint": attempt.context_fingerprint,
                "value_before": repr(attempt.value_before),
                "value_after": repr(attempt.value_after),
                "cost": repr(attempt.cost),
                "evidence_measured": attempt.evidence_measured,
            },
            "loop_key": attempt.loop_key,
            "history": [item.__dict__ if isinstance(item,ProgressHistoryEntry) else repr(item) for item in history],
            "directional_gain": _frac(gain),
            "required_gain": _frac(required),
            "remaining_before": _frac(remaining_before),
            "remaining_after": _frac(remaining_after),
            "gain_per_cost": _frac(gain_per_cost),
            "projected_steps": _frac(projected_steps),
            "atomic_bundle": None if attempt.atomic_bundle is None else {
                "bundle_id": attempt.atomic_bundle.bundle_id,
                "step_id": attempt.atomic_bundle.step_id,
                "step_index": attempt.atomic_bundle.step_index,
                "step_count": attempt.atomic_bundle.step_count,
                "expected_total_gain": str(attempt.atomic_bundle.expected_total_gain),
                "min_required_total_gain": str(attempt.atomic_bundle.min_required_total_gain),
                "expected_total_cost": str(attempt.atomic_bundle.expected_total_cost),
                "max_total_cost": str(attempt.atomic_bundle.max_total_cost),
                "evidence_id": attempt.atomic_bundle.evidence_id,
                "preregistered": attempt.atomic_bundle.preregistered,
                "causal_dependency": attempt.atomic_bundle.causal_dependency,
            },
        }
        digest = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return ProgressEvaluation(
            decision=decision,
            reasons=reasons,
            objective_id=self.policy.objective_id,
            directional_gain=payload["directional_gain"],
            required_gain=payload["required_gain"],
            remaining_before=payload["remaining_before"],
            remaining_after=payload["remaining_after"],
            gain_per_cost=payload["gain_per_cost"],
            projected_steps=payload["projected_steps"],
            loop_key=attempt.loop_key,
            receipt_sha256=digest,
        )


def _q(value: float | int | str | Decimal | Fraction) -> Fraction:
    if isinstance(value, Fraction):
        return value
    return Fraction(Decimal(str(value)))


def _frac(value: Fraction | None) -> str | None:
    if value is None:
        return None
    return f"{value.numerator}/{value.denominator}"


def _valid_finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(float(value))
