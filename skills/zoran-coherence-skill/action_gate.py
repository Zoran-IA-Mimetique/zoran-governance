from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Sequence

from progress_guard import ProgressAttempt, ProgressEvaluation, ProgressGuard, ProgressHistoryEntry
from tolerance_skill import Evaluation, EvaluationScope, MulticriteriaToleranceSkill, Observation, Decision

COMPONENT_ID = "MULTICRITERIA_ACTION_GATE"
VERSION = "11.0.0"


@dataclass(frozen=True)
class ActionGateEvaluation:
    decision: Decision
    reasons: tuple[str, ...]
    tolerance_receipt_sha256: str
    progress_receipt_sha256: str | None
    receipt_sha256: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "component": COMPONENT_ID,
            "version": VERSION,
            "decision": self.decision.value,
            "reasons": list(self.reasons),
            "tolerance_receipt_sha256": self.tolerance_receipt_sha256,
            "progress_receipt_sha256": self.progress_receipt_sha256,
            "receipt_sha256": self.receipt_sha256,
        }


class MulticriteriaActionGate:
    """Composition: 17D tolerance gate THEN target-aware progress guard.

    No progress can compensate a tolerance failure, and perfect tolerance cannot
    authorize a repeated or low-yield action.
    """

    def __init__(self, tolerance_skill: MulticriteriaToleranceSkill, progress_guard: ProgressGuard):
        self.tolerance_skill = tolerance_skill
        self.progress_guard = progress_guard

    def evaluate(
        self,
        observations: Sequence[Observation],
        *,
        scope: EvaluationScope,
        progress_attempt: ProgressAttempt,
        progress_history: Sequence[ProgressHistoryEntry] = (),
    ) -> ActionGateEvaluation:
        tol = self.tolerance_skill.evaluate(observations, scope=scope)
        if tol.decision is not Decision.PASS:
            return self._finish(tol.decision, ("TOLERANCE_GATE_BLOCK",) + tol.reasons, tol, None)

        prog = self.progress_guard.evaluate(progress_attempt, progress_history)
        if prog.decision is not Decision.PASS:
            return self._finish(prog.decision, ("PROGRESS_GATE_BLOCK",) + prog.reasons, tol, prog)
        return self._finish(Decision.PASS, ("ACTION_ADMISSIBLE_AND_PRODUCTIVE",), tol, prog)

    def _finish(self, decision: Decision, reasons: tuple[str, ...], tol: Evaluation, prog: ProgressEvaluation | None) -> ActionGateEvaluation:
        payload = {
            "component": COMPONENT_ID,
            "version": VERSION,
            "decision": decision.value,
            "reasons": list(reasons),
            "tolerance_receipt_sha256": tol.receipt_sha256,
            "progress_receipt_sha256": prog.receipt_sha256 if prog else None,
        }
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
        return ActionGateEvaluation(
            decision=decision,
            reasons=reasons,
            tolerance_receipt_sha256=tol.receipt_sha256,
            progress_receipt_sha256=prog.receipt_sha256 if prog else None,
            receipt_sha256=digest,
        )
