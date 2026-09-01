from __future__ import annotations

import hashlib
import json
import copy
from dataclasses import dataclass, field, replace
from decimal import Decimal
from enum import Enum
from fractions import Fraction
from math import isfinite
from types import MappingProxyType
from typing import Any, Mapping, Optional, Sequence


COMPONENT_ID = "MULTICRITERIA_TOLERANCE_SKILL"
VERSION = "3.0.0"
UNKNOWN = object()


class Decision(str, Enum):
    PASS = "PASS"
    RETRY = "RETRY"
    VETO = "VETO"


TOLERANCE_FAMILIES = (
    "metier",
    "coherence",
    "semantic",
    "factual",
    "numeric",
    "measurement",
    "temporal",
    "source",
    "ambiguity",
    "causal",
    "safety",
    "regulatory",
    "resource",
    "repeatability",
    "integration",
    "intentional",
    "epistemic",
)

# Defaults are conservative recommendations, not universal truths. A domain may override
# them, but disabling fail-closed / non-compensation is forbidden by the meta-contract.
RECOMMENDED_ZERO_TOLERANCE = frozenset(
    {
        "factual",
        "source",
        "causal",
        "safety",
        "regulatory",
        "intentional",
        "epistemic",
    }
)


@dataclass(frozen=True)
class DimensionPolicy:
    local_cap: float
    dimension_budget: float
    weight: float = 1.0
    zero_tolerance: bool = False
    unknown_blocks: bool = True


@dataclass(frozen=True)
class TolerancePolicy:
    dimensions: Mapping[str, DimensionPolicy]
    metier_budgets: Mapping[str, float]
    frame_budgets: Mapping[str, float]
    global_budget: float
    non_compensatory: bool = True
    signed_refunds_allowed: bool = False
    cross_dimension_refunds_allowed: bool = False
    unknown_can_pass: bool = False
    deterministic: bool = True
    exact_boundary_accounting: bool = True

    def validate_meta_contract(self) -> tuple[Decision, tuple[str, ...]]:
        violations: list[str] = []
        if self.non_compensatory is not True:
            violations.append("NON_COMPENSATION_DISABLED")
        if self.signed_refunds_allowed is not False:
            violations.append("SIGNED_REFUNDS_FORBIDDEN")
        if self.cross_dimension_refunds_allowed is not False:
            violations.append("CROSS_DIMENSION_REFUNDS_FORBIDDEN")
        if self.unknown_can_pass is not False:
            violations.append("UNKNOWN_PASS_FORBIDDEN")
        if self.deterministic is not True:
            violations.append("DETERMINISM_REQUIRED")
        if self.exact_boundary_accounting is not True:
            violations.append("EXACT_BOUNDARY_ACCOUNTING_REQUIRED")
        if not _valid_nonnegative(self.global_budget):
            violations.append("INVALID_GLOBAL_BUDGET")

        missing = set(TOLERANCE_FAMILIES) - set(self.dimensions)
        extra = set(self.dimensions) - set(TOLERANCE_FAMILIES)
        if missing:
            violations.append(f"MISSING_DIMENSIONS:{','.join(sorted(missing))}")
        if extra:
            violations.append(f"UNKNOWN_DIMENSIONS:{','.join(sorted(extra))}")

        for name, spec in self.dimensions.items():
            if not isinstance(spec.zero_tolerance,bool):
                violations.append(f"INVALID_ZERO_TOLERANCE_FLAG:{name}")
            if not isinstance(spec.unknown_blocks,bool) or spec.unknown_blocks is not True:
                violations.append(f"UNKNOWN_MUST_BLOCK:{name}")
            if not _valid_nonnegative(spec.local_cap):
                violations.append(f"INVALID_LOCAL_CAP:{name}")
            if not _valid_nonnegative(spec.dimension_budget):
                violations.append(f"INVALID_DIMENSION_BUDGET:{name}")
            if not _valid_positive(spec.weight):
                violations.append(f"INVALID_WEIGHT:{name}")
            if spec.zero_tolerance and (_q(spec.local_cap) != 0 or _q(spec.dimension_budget) != 0):
                violations.append(f"ZERO_TOLERANCE_MUST_HAVE_ZERO_BUDGET:{name}")

        if not self.metier_budgets:
            violations.append("METIER_BUDGET_REQUIRED")
        if not self.frame_budgets:
            violations.append("FRAME_BUDGET_REQUIRED")
        for name, budget in self.metier_budgets.items():
            if not name or not _valid_nonnegative(budget):
                violations.append(f"INVALID_METIER_BUDGET:{name}")
        for name, budget in self.frame_budgets.items():
            if not name or not _valid_nonnegative(budget):
                violations.append(f"INVALID_FRAME_BUDGET:{name}")

        return (Decision.VETO if violations else Decision.PASS, tuple(violations))




@dataclass(frozen=True)
class EvaluationScope:
    """Explicit applicability contract for all 17 tolerance families.

    Every family must be either applicable or explicitly excluded with a non-empty reason.
    This prevents PASS-by-omission.
    """

    applicable_dimensions: tuple[str, ...]
    excluded_dimensions: Mapping[str, str] = field(default_factory=dict)

    def validate(self) -> tuple[Decision, tuple[str, ...]]:
        applicable = tuple(self.applicable_dimensions)
        applicable_set = set(applicable)
        excluded_set = set(self.excluded_dimensions)
        reasons: list[str] = []
        if not applicable:
            reasons.append("NO_APPLICABLE_DIMENSION")
        if len(applicable) != len(applicable_set):
            reasons.append("DUPLICATE_APPLICABLE_DIMENSION")
        unknown = (applicable_set | excluded_set) - set(TOLERANCE_FAMILIES)
        if unknown:
            reasons.append(f"UNKNOWN_SCOPE_DIMENSIONS:{','.join(sorted(unknown))}")
        overlap = applicable_set & excluded_set
        if overlap:
            reasons.append(f"SCOPE_OVERLAP:{','.join(sorted(overlap))}")
        empty_reasons = [name for name, reason in self.excluded_dimensions.items() if not isinstance(reason, str) or not reason.strip()]
        if empty_reasons:
            reasons.append(f"EXCLUSION_REASON_REQUIRED:{','.join(sorted(empty_reasons))}")
        if reasons:
            return Decision.VETO, tuple(reasons)
        missing = set(TOLERANCE_FAMILIES) - applicable_set - excluded_set
        if missing:
            return Decision.RETRY, (f"APPLICABILITY_UNDECLARED:{','.join(sorted(missing))}",)
        return Decision.PASS, ("APPLICABILITY_COMPLETE",)


def scope_for(*applicable: str, exclusion_reason: str = "NOT_APPLICABLE") -> EvaluationScope:
    selected = tuple(dict.fromkeys(applicable))
    excluded = {name: exclusion_reason for name in TOLERANCE_FAMILIES if name not in selected}
    return EvaluationScope(selected, excluded)


@dataclass(frozen=True)
class HardContract:
    invariants: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Observation:
    stage_id: str
    dimension: str
    delta: float
    amplification: Optional[float]
    metier_id: str
    frame_id: str
    evidence_measured: bool = True
    invariant_observed: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LedgerEntry:
    stage_id: str
    dimension: str
    metier_id: str
    frame_id: str
    signed_delta: str
    charged_cost: str
    dimension_cost: str
    dimension_remaining: str
    metier_cost: str
    metier_remaining: str
    frame_cost: str
    frame_remaining: str
    global_cost: str
    global_remaining: str


@dataclass(frozen=True)
class Evaluation:
    decision: Decision
    reasons: tuple[str, ...]
    ledger: tuple[LedgerEntry, ...]
    dimension_costs: Mapping[str, str]
    metier_costs: Mapping[str, str]
    frame_costs: Mapping[str, str]
    global_cost: str
    receipt_sha256: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "component": COMPONENT_ID,
            "version": VERSION,
            "decision": self.decision.value,
            "reasons": list(self.reasons),
            "ledger": [entry.__dict__ for entry in self.ledger],
            "dimension_costs": dict(self.dimension_costs),
            "metier_costs": dict(self.metier_costs),
            "frame_costs": dict(self.frame_costs),
            "global_cost": self.global_cost,
            "receipt_sha256": self.receipt_sha256,
        }


class MulticriteriaToleranceSkill:
    """Deterministic, non-compensatory tolerance engine.

    The engine does not invent domain metrics. It consumes measured deviations and a
    pre-registered policy. If a required measurement is missing, it fails closed.

    Decision precedence:
      1. policy self-audit,
      2. hard contract / zero-tolerance veto,
      3. measurement completeness,
      4. local cap,
      5. per-dimension cumulative budget,
      6. métier budget,
      7. frame budget,
      8. global budget.
    """

    def __init__(self, policy: TolerancePolicy, contract: HardContract | None = None):
        # Frozen dataclasses do not freeze nested dicts. Copy and seal every mapping
        # so a caller cannot mutate a policy after its one-time validation.
        self.policy = TolerancePolicy(
            dimensions=MappingProxyType(dict(policy.dimensions)),
            metier_budgets=MappingProxyType(dict(policy.metier_budgets)),
            frame_budgets=MappingProxyType(dict(policy.frame_budgets)),
            global_budget=policy.global_budget,
            non_compensatory=policy.non_compensatory,
            signed_refunds_allowed=policy.signed_refunds_allowed,
            cross_dimension_refunds_allowed=policy.cross_dimension_refunds_allowed,
            unknown_can_pass=policy.unknown_can_pass,
            deterministic=policy.deterministic,
            exact_boundary_accounting=policy.exact_boundary_accounting,
        )
        supplied_contract = contract or HardContract()
        self.contract = HardContract(_deep_freeze(copy.deepcopy(dict(supplied_contract.invariants))))
        self._policy_digest = _stable_sha({
            "dimensions": {k: v.__dict__ for k, v in sorted(self.policy.dimensions.items())},
            "metier_budgets": dict(sorted(self.policy.metier_budgets.items())),
            "frame_budgets": dict(sorted(self.policy.frame_budgets.items())),
            "global_budget": self.policy.global_budget,
            "non_compensatory": self.policy.non_compensatory,
            "signed_refunds_allowed": self.policy.signed_refunds_allowed,
            "cross_dimension_refunds_allowed": self.policy.cross_dimension_refunds_allowed,
            "unknown_can_pass": self.policy.unknown_can_pass,
            "deterministic": self.policy.deterministic,
            "exact_boundary_accounting": self.policy.exact_boundary_accounting,
        })
        self._contract_digest = _stable_sha(dict(self.contract.invariants))
        self._meta_validation = self.policy.validate_meta_contract()

    def admissible_next_delta(
        self,
        *,
        dimension: str,
        metier_id: str,
        frame_id: str,
        amplification: Optional[float],
        dimension_cost: float = 0.0,
        metier_cost: float = 0.0,
        frame_cost: float = 0.0,
        global_cost: float = 0.0,
    ) -> tuple[Decision, Optional[float], tuple[str, ...]]:
        meta, reasons = self._meta_validation
        if meta is not Decision.PASS:
            return Decision.VETO, None, ("META_CONTRACT_VIOLATION",) + reasons
        if dimension not in self.policy.dimensions:
            return Decision.RETRY, None, (f"UNREGISTERED_DIMENSION:{dimension}",)
        if metier_id not in self.policy.metier_budgets:
            return Decision.RETRY, None, (f"UNREGISTERED_METIER:{metier_id}",)
        if frame_id not in self.policy.frame_budgets:
            return Decision.RETRY, None, (f"UNREGISTERED_FRAME:{frame_id}",)
        spec = self.policy.dimensions[dimension]
        if spec.zero_tolerance:
            return Decision.PASS, 0.0, ("ZERO_TOLERANCE",)
        if amplification is None or not _valid_positive(amplification):
            return Decision.RETRY, None, (f"AMPLIFICATION_TRACE_PENDING:{dimension}",)

        costs = [dimension_cost, metier_cost, frame_cost, global_cost]
        if not all(_valid_nonnegative(value) for value in costs):
            return Decision.RETRY, None, ("INVALID_CURRENT_COST",)

        denom = _q(spec.weight) * _q(amplification)
        caps = (
            _q(spec.local_cap),
            (_q(spec.dimension_budget) - _q(dimension_cost)) / denom,
            (_q(self.policy.metier_budgets[metier_id]) - _q(metier_cost)) / denom,
            (_q(self.policy.frame_budgets[frame_id]) - _q(frame_cost)) / denom,
            (_q(self.policy.global_budget) - _q(global_cost)) / denom,
        )
        if any(cap < 0 for cap in caps):
            return Decision.RETRY, 0.0, ("BUDGET_ALREADY_EXHAUSTED",)
        return Decision.PASS, float(min(caps)), ("DYNAMIC_INTERSECTION_CAP",)

    def evaluate(self, observations: Sequence[Observation], *, scope: EvaluationScope | None = None) -> Evaluation:
        items = tuple(observations)
        request_digest = _stable_sha({
            "policy_sha256": self._policy_digest,
            "contract_sha256": self._contract_digest,
            "scope": None if scope is None else {
                "applicable_dimensions": list(scope.applicable_dimensions),
                "excluded_dimensions": dict(scope.excluded_dimensions),
            },
            "observations": [x.__dict__ for x in items],
        })
        result = self._evaluate_unbound(items, scope=scope)
        receipt = _stable_sha({
            "request_sha256": request_digest,
            "evaluation_sha256": result.receipt_sha256,
        })
        return replace(result, receipt_sha256=receipt)

    def _evaluate_unbound(self, observations: Sequence[Observation], *, scope: EvaluationScope | None = None) -> Evaluation:
        meta, meta_reasons = self._meta_validation
        if meta is not Decision.PASS:
            return self._finish(
                Decision.VETO,
                ("META_CONTRACT_VIOLATION",) + meta_reasons,
                [],
                {},
                {},
                {},
                Fraction(0),
            )

        if scope is None:
            return self._finish(
                Decision.RETRY,
                ("APPLICABILITY_SCOPE_REQUIRED",),
                [], {}, {}, {}, Fraction(0),
            )
        scope_decision, scope_reasons = scope.validate()
        if scope_decision is not Decision.PASS:
            return self._finish(
                scope_decision, scope_reasons, [], {}, {}, {}, Fraction(0)
            )
        observed_dimensions = {obs.dimension for obs in observations}
        applicable_set = set(scope.applicable_dimensions)
        missing_observations = applicable_set - observed_dimensions
        if missing_observations:
            return self._finish(
                Decision.RETRY,
                (f"APPLICABLE_DIMENSION_TRACE_PENDING:{','.join(sorted(missing_observations))}",),
                [], {}, {}, {}, Fraction(0),
            )
        excluded_observed = observed_dimensions & set(scope.excluded_dimensions)
        if excluded_observed:
            return self._finish(
                Decision.VETO,
                (f"EXCLUDED_DIMENSION_OBSERVED:{','.join(sorted(excluded_observed))}",),
                [], {}, {}, {}, Fraction(0),
            )

        dim_costs = {name: Fraction(0) for name in self.policy.dimensions}
        metier_costs = {name: Fraction(0) for name in self.policy.metier_budgets}
        frame_costs = {name: Fraction(0) for name in self.policy.frame_budgets}
        global_cost = Fraction(0)
        ledger: list[LedgerEntry] = []

        # Hard invariants are checked at every stage that provides them. If the contract
        # declares an invariant, every stage must expose it: missing = RETRY.
        for obs in observations:
            for key, expected in self.contract.invariants.items():
                if key not in obs.invariant_observed or obs.invariant_observed[key] is UNKNOWN:
                    return self._finish(
                        Decision.RETRY,
                        (f"CRITICAL_TRACE_PENDING:{obs.stage_id}:{key}",),
                        ledger,
                        dim_costs,
                        metier_costs,
                        frame_costs,
                        global_cost,
                    )
                if obs.invariant_observed[key] != expected:
                    return self._finish(
                        Decision.VETO,
                        (f"HARD_INVARIANT_VIOLATION:{obs.stage_id}:{key}",),
                        ledger,
                        dim_costs,
                        metier_costs,
                        frame_costs,
                        global_cost,
                    )

        for obs in observations:
            if obs.dimension not in self.policy.dimensions:
                return self._stop_retry(obs, "UNREGISTERED_DIMENSION", ledger, dim_costs, metier_costs, frame_costs, global_cost)
            if obs.metier_id not in self.policy.metier_budgets:
                return self._stop_retry(obs, "UNREGISTERED_METIER", ledger, dim_costs, metier_costs, frame_costs, global_cost)
            if obs.frame_id not in self.policy.frame_budgets:
                return self._stop_retry(obs, "UNREGISTERED_FRAME", ledger, dim_costs, metier_costs, frame_costs, global_cost)
            if obs.evidence_measured is not True:
                return self._stop_retry(obs, "EVIDENCE_TRACE_PENDING", ledger, dim_costs, metier_costs, frame_costs, global_cost)
            if not _valid_finite(obs.delta):
                return self._stop_retry(obs, "INVALID_DELTA", ledger, dim_costs, metier_costs, frame_costs, global_cost)

            spec = self.policy.dimensions[obs.dimension]
            magnitude = abs(_q(obs.delta))

            if spec.zero_tolerance and magnitude != 0:
                return self._finish(
                    Decision.VETO,
                    (f"ZERO_TOLERANCE_VIOLATION:{obs.stage_id}:{obs.dimension}",),
                    ledger,
                    dim_costs,
                    metier_costs,
                    frame_costs,
                    global_cost,
                )

            if magnitude == 0:
                charge = Fraction(0)
                amplification_q = Fraction(1)
            else:
                if obs.amplification is None or not _valid_positive(obs.amplification):
                    return self._stop_retry(obs, "AMPLIFICATION_TRACE_PENDING", ledger, dim_costs, metier_costs, frame_costs, global_cost)
                amplification_q = _q(obs.amplification)
                if magnitude > _q(spec.local_cap):
                    return self._finish(
                        Decision.RETRY,
                        (f"LOCAL_CAP_EXCEEDED:{obs.stage_id}:{obs.dimension}",),
                        ledger,
                        dim_costs,
                        metier_costs,
                        frame_costs,
                        global_cost,
                    )
                charge = magnitude * _q(spec.weight) * amplification_q

            new_dim = dim_costs[obs.dimension] + charge
            if new_dim > _q(spec.dimension_budget):
                return self._finish(
                    Decision.RETRY,
                    (f"DIMENSION_BUDGET_EXCEEDED:{obs.stage_id}:{obs.dimension}",),
                    ledger,
                    dim_costs,
                    metier_costs,
                    frame_costs,
                    global_cost,
                )

            new_metier = metier_costs[obs.metier_id] + charge
            if new_metier > _q(self.policy.metier_budgets[obs.metier_id]):
                return self._finish(
                    Decision.RETRY,
                    (f"METIER_BUDGET_EXCEEDED:{obs.stage_id}:{obs.metier_id}",),
                    ledger,
                    dim_costs,
                    metier_costs,
                    frame_costs,
                    global_cost,
                )

            new_frame = frame_costs[obs.frame_id] + charge
            if new_frame > _q(self.policy.frame_budgets[obs.frame_id]):
                return self._finish(
                    Decision.RETRY,
                    (f"FRAME_BUDGET_EXCEEDED:{obs.stage_id}:{obs.frame_id}",),
                    ledger,
                    dim_costs,
                    metier_costs,
                    frame_costs,
                    global_cost,
                )

            new_global = global_cost + charge
            if new_global > _q(self.policy.global_budget):
                return self._finish(
                    Decision.RETRY,
                    (f"GLOBAL_BUDGET_EXCEEDED:{obs.stage_id}",),
                    ledger,
                    dim_costs,
                    metier_costs,
                    frame_costs,
                    global_cost,
                )

            dim_costs[obs.dimension] = new_dim
            metier_costs[obs.metier_id] = new_metier
            frame_costs[obs.frame_id] = new_frame
            global_cost = new_global
            ledger.append(
                LedgerEntry(
                    stage_id=obs.stage_id,
                    dimension=obs.dimension,
                    metier_id=obs.metier_id,
                    frame_id=obs.frame_id,
                    signed_delta=_frac(_q(obs.delta)),
                    charged_cost=_frac(charge),
                    dimension_cost=_frac(new_dim),
                    dimension_remaining=_frac(_q(spec.dimension_budget) - new_dim),
                    metier_cost=_frac(new_metier),
                    metier_remaining=_frac(_q(self.policy.metier_budgets[obs.metier_id]) - new_metier),
                    frame_cost=_frac(new_frame),
                    frame_remaining=_frac(_q(self.policy.frame_budgets[obs.frame_id]) - new_frame),
                    global_cost=_frac(new_global),
                    global_remaining=_frac(_q(self.policy.global_budget) - new_global),
                )
            )

        return self._finish(
            Decision.PASS,
            ("ALL_INTERSECTED_TOLERANCES_ADMISSIBLE",),
            ledger,
            dim_costs,
            metier_costs,
            frame_costs,
            global_cost,
        )

    def _stop_retry(self, obs: Observation, code: str, ledger, dim_costs, metier_costs, frame_costs, global_cost):
        return self._finish(
            Decision.RETRY,
            (f"{code}:{obs.stage_id}:{obs.dimension}",),
            ledger,
            dim_costs,
            metier_costs,
            frame_costs,
            global_cost,
        )

    def _finish(self, decision, reasons, ledger, dim_costs, metier_costs, frame_costs, global_cost):
        payload = {
            "component": COMPONENT_ID,
            "version": VERSION,
            "policy_sha256": self._policy_digest,
            "contract_sha256": self._contract_digest,
            "decision": decision.value,
            "reasons": list(reasons),
            "ledger": [entry.__dict__ for entry in ledger],
            "dimension_costs": {k: _frac(v) for k, v in sorted(dim_costs.items())},
            "metier_costs": {k: _frac(v) for k, v in sorted(metier_costs.items())},
            "frame_costs": {k: _frac(v) for k, v in sorted(frame_costs.items())},
            "global_cost": _frac(global_cost),
        }
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return Evaluation(
            decision=decision,
            reasons=tuple(reasons),
            ledger=tuple(ledger),
            dimension_costs=MappingProxyType(payload["dimension_costs"]),
            metier_costs=MappingProxyType(payload["metier_costs"]),
            frame_costs=MappingProxyType(payload["frame_costs"]),
            global_cost=payload["global_cost"],
            receipt_sha256=digest,
        )


def conservative_default_policy(
    *,
    metier_ids: Sequence[str] = ("generic",),
    frame_ids: Sequence[str] = ("local", "general"),
    soft_local_cap: float = 0.1,
    soft_dimension_budget: float = 0.25,
    metier_budget: float = 2.0,
    frame_budget: float = 2.0,
    global_budget: float = 3.0,
) -> TolerancePolicy:
    """Create a complete 17-family policy with conservative zero-tolerance defaults."""
    dimensions = {
        name: DimensionPolicy(
            local_cap=0.0 if name in RECOMMENDED_ZERO_TOLERANCE else soft_local_cap,
            dimension_budget=0.0 if name in RECOMMENDED_ZERO_TOLERANCE else soft_dimension_budget,
            weight=1.0,
            zero_tolerance=name in RECOMMENDED_ZERO_TOLERANCE,
            unknown_blocks=True,
        )
        for name in TOLERANCE_FAMILIES
    }
    return TolerancePolicy(
        dimensions=dimensions,
        metier_budgets={name: metier_budget for name in metier_ids},
        frame_budgets={name: frame_budget for name in frame_ids},
        global_budget=global_budget,
    )


def _q(value: float | int | str | Decimal | Fraction) -> Fraction:
    if isinstance(value, Fraction):
        return value
    return Fraction(Decimal(str(value)))


def _frac(value: Fraction) -> str:
    return f"{value.numerator}/{value.denominator}"


def _valid_finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(float(value))


def _valid_nonnegative(value: Any) -> bool:
    return _valid_finite(value) and float(value) >= 0


def _valid_positive(value: Any) -> bool:
    return _valid_finite(value) and float(value) > 0


def _stable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _stable(v) for k, v in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (tuple, list)):
        return [_stable(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_stable(v) for v in value), key=repr)
    if isinstance(value, float) and not isfinite(value):
        return repr(value)
    if isinstance(value, (Decimal, Fraction)):
        return str(value)
    if value is UNKNOWN:
        return "__UNKNOWN__"
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return repr(value)


def _deep_freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({k: _deep_freeze(v) for k, v in value.items()})
    if isinstance(value, list):
        return tuple(_deep_freeze(v) for v in value)
    if isinstance(value, tuple):
        return tuple(_deep_freeze(v) for v in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_deep_freeze(v) for v in value)
    return value


def _stable_sha(value: Any) -> str:
    raw = json.dumps(_stable(value), sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
