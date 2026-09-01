from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from math import isfinite
from typing import Mapping, Sequence

from coherence_dynamics import CoherenceDynamics, CoherencePoint
from tolerance_skill import Decision


COMPONENT_ID = "ZORAN_PHENOMENAL_COHERENCE_GATE"
VERSION = "2.0.0"

# ``planetary`` is the terminal global frame.  It is deliberately not named
# merely ``global`` so a system-wide software result cannot be mistaken for a
# demonstrated planetary effect.
CANONICAL_FRAMES = ("local", "lower", "peer", "upper", "temporal", "planetary")
PRESERVATION_FRAMES = ("lower", "peer")
SUPERIOR_FRAMES = ("upper", "temporal", "planetary")
SHA256_LENGTH = 64


def _q(value) -> Fraction | None:
    if isinstance(value, bool):
        return None
    try:
        result = value if isinstance(value, Fraction) else Fraction(Decimal(str(value)))
    except (ValueError, TypeError, ArithmeticError, InvalidOperation, OverflowError):
        return None
    if not isfinite(float(result)):
        return None
    return result


def _fmt(value: Fraction | None) -> str | None:
    if value is None:
        return None
    return str(value.numerator) if value.denominator == 1 else f"{value.numerator}/{value.denominator}"


def _valid_sha(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == SHA256_LENGTH
        and all(character in "0123456789abcdef" for character in value)
    )


def _evidence_valid(evidence: object, evidence_sha256: object) -> bool:
    return (
        isinstance(evidence, str)
        and bool(evidence.strip())
        and _valid_sha(evidence_sha256)
        and hashlib.sha256(evidence.encode("utf-8")).hexdigest() == evidence_sha256
    )


def evidence_sha256(evidence: str) -> str:
    """Return the digest expected by every evidence-bearing input object."""
    return hashlib.sha256(evidence.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class FrameTransition:
    frame_id: str
    before_s: float
    after_s: float
    evidence: str
    evidence_sha256: str
    affected: bool = True
    non_affected_proven: bool = False
    critical_invariant_preserved: bool = True


@dataclass(frozen=True)
class CausalBenefit:
    frame_id: str
    intervention_id: str
    observed_after_s: float
    counterfactual_s: float
    falsifier: str
    evidence: str
    evidence_sha256: str
    measured: bool = True


@dataclass(frozen=True)
class PhenomenalSnapshot:
    t: int
    frame_scores: Mapping[str, float]
    measurement_contract_sha256: str
    evidence: str
    evidence_sha256: str
    validated: bool = True


@dataclass(frozen=True)
class RegressionException:
    frame_id: str
    inevitable: bool
    strictly_necessary: bool
    minimal: bool
    measured: bool
    bounded: bool
    traceable: bool
    no_less_harmful_alternative: bool
    no_uncompensable_invariant: bool
    net_coherence_gain_proven: bool
    evidence: str
    evidence_sha256: str

    def complete(self) -> bool:
        flags = (
            self.inevitable,
            self.strictly_necessary,
            self.minimal,
            self.measured,
            self.bounded,
            self.traceable,
            self.no_less_harmful_alternative,
            self.no_uncompensable_invariant,
            self.net_coherence_gain_proven,
        )
        return all(flag is True for flag in flags) and _evidence_valid(self.evidence, self.evidence_sha256)


@dataclass(frozen=True)
class PhenomenalCoherenceRequest:
    object_id: str
    mission_sha256: str
    baseline_sha256: str
    candidate_sha256: str
    measurement_contract_sha256: str
    transitions: Sequence[FrameTransition]
    causal_benefits: Sequence[CausalBenefit]
    trajectory: Sequence[PhenomenalSnapshot]
    regression_exceptions: Sequence[RegressionException] = ()
    resource_gate_receipt_sha256: str = ""


@dataclass(frozen=True)
class FrameVerdict:
    frame_id: str
    decision: Decision
    before_s: str | None
    after_s: str | None
    delta_s: str | None
    causal_gain: str | None
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class PhenomenalCoherenceEvaluation:
    decision: Decision
    frame_verdicts: tuple[FrameVerdict, ...]
    guard_delta_s: str | None
    reasons: tuple[str, ...]
    request_sha256: str
    receipt_sha256: str

    def as_dict(self) -> dict:
        return {
            "component": COMPONENT_ID,
            "version": VERSION,
            "decision": self.decision.value,
            "frame_verdicts": [
                {
                    **item.__dict__,
                    "decision": item.decision.value,
                    "reasons": list(item.reasons),
                }
                for item in self.frame_verdicts
            ],
            "guard_delta_s": self.guard_delta_s,
            "reasons": list(self.reasons),
            "request_sha256": self.request_sha256,
            "receipt_sha256": self.receipt_sha256,
        }


class PhenomenalCoherenceEngine:
    """Non-compensatory admissibility gate over coherence trajectories.

    The engine validates supplied measurements and causal receipts.  It does not
    infer real-world effects, prove the scientific universality of a law, or turn
    a synthetic fixture into evidence about the planet.
    """

    def __init__(self, dynamics: CoherenceDynamics | None = None):
        self.dynamics = dynamics or CoherenceDynamics()

    def evaluate(self, request: PhenomenalCoherenceRequest | None) -> PhenomenalCoherenceEvaluation:
        request_payload = self._request_payload(request)
        request_sha = hashlib.sha256(
            json.dumps(
                request_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=True,
                default=repr,
            ).encode("utf-8")
        ).hexdigest()

        if not isinstance(request, PhenomenalCoherenceRequest):
            return self._finish(Decision.RETRY, (), None, (
                "PHENOMENAL_REQUEST_MISSING",
                "TRACE_MANQUANTE:SIGNED_PHENOMENAL_REQUEST",
                "OWNER:HOST_RUNTIME",
                "NEXT_ACTION:BUILD_REQUEST_FROM_PASSED_RESOURCE_RECEIPT",
                "REMAINING_ATTEMPT_BUDGET:1",
                "EXIT_CONDITION:COMPLETE_REQUEST_OR_VETO",
            ), request_sha)

        identity_reasons = self._validate_identity(request)
        if identity_reasons:
            decision = Decision.VETO if any(
                reason.endswith("_DUPLICATE") or reason == "RESOURCE_GATE_RECEIPT_SHA256_INVALID"
                for reason in identity_reasons
            ) else Decision.RETRY
            return self._finish(decision, (), None, tuple(identity_reasons), request_sha)

        transitions = tuple(request.transitions)
        transition_ids = [item.frame_id for item in transitions if isinstance(item, FrameTransition)]
        if len(transitions) != len(CANONICAL_FRAMES) or set(transition_ids) != set(CANONICAL_FRAMES):
            return self._finish(Decision.RETRY, (), None, ("FRAME_COVERAGE_INCOMPLETE",), request_sha)
        if len(transition_ids) != len(set(transition_ids)):
            return self._finish(Decision.VETO, (), None, ("FRAME_ID_DUPLICATE",), request_sha)

        causal = tuple(request.causal_benefits)
        causal_ids = [item.frame_id for item in causal if isinstance(item, CausalBenefit)]
        if len(causal_ids) != len(set(causal_ids)):
            return self._finish(Decision.VETO, (), None, ("CAUSAL_FRAME_DUPLICATE",), request_sha)
        unknown_causal = set(causal_ids) - set(SUPERIOR_FRAMES)
        if unknown_causal:
            return self._finish(Decision.VETO, (), None, ("CAUSAL_FRAME_INVALID",), request_sha)

        exceptions = tuple(request.regression_exceptions)
        exception_ids = [item.frame_id for item in exceptions if isinstance(item, RegressionException)]
        if len(exception_ids) != len(set(exception_ids)):
            return self._finish(Decision.VETO, (), None, ("REGRESSION_EXCEPTION_DUPLICATE",), request_sha)
        if set(exception_ids) - set(CANONICAL_FRAMES):
            return self._finish(Decision.VETO, (), None, ("REGRESSION_EXCEPTION_FRAME_INVALID",), request_sha)

        trajectory_decision, trajectory_reasons = self._validate_trajectory(request)
        if trajectory_decision is not Decision.PASS:
            return self._finish(trajectory_decision, (), None, trajectory_reasons, request_sha)

        by_transition = {item.frame_id: item for item in transitions}
        by_causal = {item.frame_id: item for item in causal}
        by_exception = {item.frame_id: item for item in exceptions}
        verdicts: list[FrameVerdict] = []
        all_reasons: list[str] = list(trajectory_reasons)
        guard_deltas: list[Fraction] = []
        overall = Decision.PASS

        for frame_id in CANONICAL_FRAMES:
            transition = by_transition[frame_id]
            verdict = self._evaluate_frame(
                transition,
                by_causal.get(frame_id),
                by_exception.get(frame_id),
            )
            verdicts.append(verdict)
            all_reasons.extend(verdict.reasons)
            delta = _q(transition.after_s)
            before = _q(transition.before_s)
            if delta is not None and before is not None:
                guard_deltas.append(delta - before)
            if verdict.decision is Decision.VETO:
                overall = Decision.VETO
            elif verdict.decision is Decision.RETRY and overall is not Decision.VETO:
                overall = Decision.RETRY

        guard_delta = min(guard_deltas) if len(guard_deltas) == len(CANONICAL_FRAMES) else None
        if overall is Decision.PASS:
            all_reasons.append("PHENOMENAL_COHERENCE_ADMISSIBLE")
        return self._finish(overall, tuple(verdicts), guard_delta, tuple(dict.fromkeys(all_reasons)), request_sha)

    def _validate_identity(self, request: PhenomenalCoherenceRequest) -> list[str]:
        reasons: list[str] = []
        if not isinstance(request.object_id, str) or not request.object_id.strip():
            reasons.append("OBJECT_ID_MISSING")
        for name in (
            "mission_sha256",
            "baseline_sha256",
            "candidate_sha256",
            "measurement_contract_sha256",
            "resource_gate_receipt_sha256",
        ):
            if not _valid_sha(getattr(request, name)):
                reasons.append(f"{name.upper()}_INVALID")
        if request.baseline_sha256 == request.candidate_sha256:
            reasons.append("BASELINE_CANDIDATE_IDENTITY_DUPLICATE")
        return reasons

    def _validate_trajectory(self, request: PhenomenalCoherenceRequest) -> tuple[Decision, tuple[str, ...]]:
        snapshots = tuple(request.trajectory)
        if len(snapshots) < 3:
            return Decision.RETRY, ("TRAJECTORY_REQUIRES_THREE_VALIDATED_STATES",)
        if not all(isinstance(item, PhenomenalSnapshot) for item in snapshots):
            return Decision.RETRY, ("TRAJECTORY_SNAPSHOT_INVALID",)
        if any(item.validated is not True for item in snapshots):
            return Decision.RETRY, ("TRAJECTORY_UNVALIDATED_STATE",)
        times = [item.t for item in snapshots]
        if any(not isinstance(value, int) or isinstance(value, bool) for value in times):
            return Decision.RETRY, ("TRAJECTORY_TIME_INVALID",)
        if times != sorted(times) or len(times) != len(set(times)):
            return Decision.VETO, ("TRAJECTORY_TIME_NOT_STRICTLY_MONOTONIC",)
        for item in snapshots:
            if set(item.frame_scores) != set(CANONICAL_FRAMES):
                return Decision.RETRY, ("TRAJECTORY_FRAME_COVERAGE_INCOMPLETE",)
            if item.measurement_contract_sha256 != request.measurement_contract_sha256:
                return Decision.RETRY, ("TRAJECTORY_MEASUREMENT_CONTRACT_DRIFT",)
            if not _evidence_valid(item.evidence, item.evidence_sha256):
                return Decision.RETRY, ("TRAJECTORY_EVIDENCE_INVALID",)
            for score in item.frame_scores.values():
                q = _q(score)
                if q is None or not 0 <= q <= 100:
                    return Decision.RETRY, ("TRAJECTORY_SCORE_INVALID",)

        by_transition = {item.frame_id: item for item in request.transitions if isinstance(item, FrameTransition)}
        if set(by_transition) != set(CANONICAL_FRAMES):
            return Decision.RETRY, ("TRAJECTORY_TRANSITION_BINDING_UNAVAILABLE",)
        penultimate, last = snapshots[-2:]
        for frame_id in CANONICAL_FRAMES:
            before = _q(by_transition[frame_id].before_s)
            after = _q(by_transition[frame_id].after_s)
            if before != _q(penultimate.frame_scores[frame_id]) or after != _q(last.frame_scores[frame_id]):
                return Decision.VETO, (f"TRAJECTORY_TRANSITION_MISMATCH:{frame_id}",)
            history = tuple(
                CoherencePoint(
                    item.t,
                    item.frame_scores[frame_id],
                    item.validated,
                    CANONICAL_FRAMES,
                    ("beta", "dphi", "T", "sigma"),
                )
                for item in snapshots
            )
            dynamics = self.dynamics.evaluate(history)
            if dynamics.decision is not Decision.PASS:
                return dynamics.decision, (f"TRAJECTORY_DYNAMICS_BLOCK:{frame_id}",) + dynamics.reasons
        return Decision.PASS, ("PHENOMENAL_TRAJECTORY_MEASURED",)

    def _evaluate_frame(
        self,
        transition: FrameTransition,
        causal: CausalBenefit | None,
        exception: RegressionException | None,
    ) -> FrameVerdict:
        before = _q(transition.before_s)
        after = _q(transition.after_s)
        if before is None or after is None or not 0 <= before <= 100 or not 0 <= after <= 100:
            return FrameVerdict(transition.frame_id, Decision.RETRY, _fmt(before), _fmt(after), None, None, (f"FRAME_SCORE_INVALID:{transition.frame_id}",))
        delta = after - before
        if not _evidence_valid(transition.evidence, transition.evidence_sha256):
            return FrameVerdict(transition.frame_id, Decision.RETRY, _fmt(before), _fmt(after), _fmt(delta), None, (f"FRAME_EVIDENCE_INVALID:{transition.frame_id}",))
        if not isinstance(transition.affected, bool) or not isinstance(transition.non_affected_proven, bool):
            return FrameVerdict(transition.frame_id, Decision.RETRY, _fmt(before), _fmt(after), _fmt(delta), None, (f"FRAME_APPLICABILITY_INVALID:{transition.frame_id}",))
        if transition.affected is not True:
            if transition.frame_id not in PRESERVATION_FRAMES:
                return FrameVerdict(transition.frame_id, Decision.VETO, _fmt(before), _fmt(after), _fmt(delta), None, (f"MANDATORY_PHENOMENAL_FRAME_EXCLUDED:{transition.frame_id}",))
            if transition.non_affected_proven is True and delta == 0:
                return FrameVerdict(transition.frame_id, Decision.PASS, _fmt(before), _fmt(after), _fmt(delta), None, (f"FRAME_NON_AFFECTED_PROVEN:{transition.frame_id}",))
            return FrameVerdict(transition.frame_id, Decision.RETRY, _fmt(before), _fmt(after), _fmt(delta), None, (f"FRAME_NON_AFFECTED_UNPROVEN:{transition.frame_id}",))
        if not isinstance(transition.critical_invariant_preserved, bool):
            return FrameVerdict(transition.frame_id, Decision.RETRY, _fmt(before), _fmt(after), _fmt(delta), None, (f"CRITICAL_INVARIANT_STATUS_INVALID:{transition.frame_id}",))
        if transition.critical_invariant_preserved is not True:
            return FrameVerdict(transition.frame_id, Decision.VETO, _fmt(before), _fmt(after), _fmt(delta), None, (f"CRITICAL_INVARIANT_REGRESSION:{transition.frame_id}",))

        if delta < 0:
            if exception is None or not exception.complete():
                return FrameVerdict(transition.frame_id, Decision.VETO, _fmt(before), _fmt(after), _fmt(delta), None, (f"UNJUSTIFIED_FRAME_REGRESSION:{transition.frame_id}",))
            return FrameVerdict(transition.frame_id, Decision.PASS, _fmt(before), _fmt(after), _fmt(delta), None, (f"BOUNDED_REGRESSION_EXCEPTION:{transition.frame_id}",))

        if transition.frame_id == "local" and delta <= 0:
            return FrameVerdict(transition.frame_id, Decision.VETO, _fmt(before), _fmt(after), _fmt(delta), None, ("LOCAL_FRAME_NOT_IMPROVED",))
        if transition.frame_id == "local":
            return FrameVerdict(transition.frame_id, Decision.PASS, _fmt(before), _fmt(after), _fmt(delta), None, ("LOCAL_FRAME_IMPROVED",))
        if transition.frame_id in PRESERVATION_FRAMES:
            return FrameVerdict(transition.frame_id, Decision.PASS, _fmt(before), _fmt(after), _fmt(delta), None, (f"FRAME_PRESERVED:{transition.frame_id}",))
        if transition.frame_id in SUPERIOR_FRAMES:
            if delta <= 0:
                return FrameVerdict(transition.frame_id, Decision.VETO, _fmt(before), _fmt(after), _fmt(delta), None, (f"SUPERIOR_FRAME_BENEFIT_ABSENT:{transition.frame_id}",))
            if causal is None:
                return FrameVerdict(transition.frame_id, Decision.RETRY, _fmt(before), _fmt(after), _fmt(delta), None, (f"CAUSAL_BENEFIT_MISSING:{transition.frame_id}",))
            causal_decision, causal_gain, causal_reasons = self._evaluate_causal(transition, causal)
            return FrameVerdict(transition.frame_id, causal_decision, _fmt(before), _fmt(after), _fmt(delta), _fmt(causal_gain), causal_reasons)
        return FrameVerdict(transition.frame_id, Decision.VETO, _fmt(before), _fmt(after), _fmt(delta), None, ("UNKNOWN_FRAME",))

    def _evaluate_causal(
        self,
        transition: FrameTransition,
        causal: CausalBenefit,
    ) -> tuple[Decision, Fraction | None, tuple[str, ...]]:
        if causal.frame_id != transition.frame_id:
            return Decision.VETO, None, (f"CAUSAL_FRAME_MISMATCH:{transition.frame_id}",)
        if causal.measured is not True:
            return Decision.RETRY, None, (f"CAUSAL_BENEFIT_TRACE_ABSENTE:{transition.frame_id}",)
        if not isinstance(causal.intervention_id, str) or not causal.intervention_id.strip():
            return Decision.RETRY, None, (f"CAUSAL_INTERVENTION_MISSING:{transition.frame_id}",)
        if not isinstance(causal.falsifier, str) or not causal.falsifier.strip():
            return Decision.RETRY, None, (f"CAUSAL_FALSIFIER_MISSING:{transition.frame_id}",)
        if not _evidence_valid(causal.evidence, causal.evidence_sha256):
            return Decision.RETRY, None, (f"CAUSAL_EVIDENCE_INVALID:{transition.frame_id}",)
        observed = _q(causal.observed_after_s)
        counterfactual = _q(causal.counterfactual_s)
        transition_after = _q(transition.after_s)
        if observed is None or counterfactual is None or not 0 <= observed <= 100 or not 0 <= counterfactual <= 100:
            return Decision.RETRY, None, (f"CAUSAL_SCORE_INVALID:{transition.frame_id}",)
        if observed != transition_after:
            return Decision.VETO, None, (f"CAUSAL_OBSERVED_TRANSITION_MISMATCH:{transition.frame_id}",)
        gain = observed - counterfactual
        if gain <= 0:
            return Decision.VETO, gain, (f"CAUSAL_GAIN_NOT_POSITIVE:{transition.frame_id}",)
        return Decision.PASS, gain, (f"CAUSAL_BENEFIT_PROVEN:{transition.frame_id}",)

    def _finish(
        self,
        decision: Decision,
        frame_verdicts: tuple[FrameVerdict, ...],
        guard_delta: Fraction | None,
        reasons: tuple[str, ...],
        request_sha: str,
    ) -> PhenomenalCoherenceEvaluation:
        payload = {
            "component": COMPONENT_ID,
            "version": VERSION,
            "decision": decision.value,
            "frame_verdicts": [
                {
                    **item.__dict__,
                    "decision": item.decision.value,
                    "reasons": list(item.reasons),
                }
                for item in frame_verdicts
            ],
            "guard_delta_s": _fmt(guard_delta),
            "reasons": list(reasons),
            "request_sha256": request_sha,
        }
        receipt = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        ).hexdigest()
        return PhenomenalCoherenceEvaluation(
            decision,
            frame_verdicts,
            _fmt(guard_delta),
            reasons,
            request_sha,
            receipt,
        )

    @staticmethod
    def _request_payload(request: PhenomenalCoherenceRequest | None):
        if not isinstance(request, PhenomenalCoherenceRequest):
            return {"request": repr(request)}
        return {
            "object_id": request.object_id,
            "mission_sha256": request.mission_sha256,
            "baseline_sha256": request.baseline_sha256,
            "candidate_sha256": request.candidate_sha256,
            "measurement_contract_sha256": request.measurement_contract_sha256,
            "resource_gate_receipt_sha256": request.resource_gate_receipt_sha256,
            "transitions": [item.__dict__ for item in sorted(request.transitions, key=lambda value: getattr(value, "frame_id", repr(value)))],
            "causal_benefits": [item.__dict__ for item in sorted(request.causal_benefits, key=lambda value: getattr(value, "frame_id", repr(value)))],
            "trajectory": [
                {**item.__dict__, "frame_scores": dict(item.frame_scores)}
                for item in sorted(request.trajectory, key=lambda value: getattr(value, "t", repr(value)))
            ],
            "regression_exceptions": [item.__dict__ for item in sorted(request.regression_exceptions, key=lambda value: getattr(value, "frame_id", repr(value)))],
        }
