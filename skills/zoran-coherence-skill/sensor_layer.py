from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from decimal import Decimal
from math import isfinite
from typing import Any, Mapping, Sequence

from tolerance_skill import Observation, EvaluationScope, TOLERANCE_FAMILIES

SENSOR_COMPONENT_ID = "MULTICRITERIA_TOLERANCE_SENSOR_LAYER"
SENSOR_VERSION = "1.0.0"

_MODALITY_RANK = {"unknown": 0, "possible": 1, "probable": 2, "certain": 3}
_INTENT_PATTERNS = {
    "FACT": ("quel état", "quelle valeur", "combien", "what is", "how much"),
    "CAUSE": ("pourquoi", "quelle cause", "what caused", "why"),
    "LIMITATION": ("quelle limite", "quelles limites", "quel risque", "limites", "limitations"),
    "EVIDENCE": ("quelle source", "quelles preuves", "source", "evidence", "proof"),
    "PROCEDURE": ("comment faire", "quelles étapes", "procedure", "how to"),
}

_FACT_RE = re.compile(
    r"^(?:(possible|probable|certain)\s*:\s*)?(not\s+)?([A-Za-zÀ-ÿ0-9_.-]+)\s*=\s*([^\[]+?)\s*(?:\[([A-Za-z0-9_.:-]+)\])?$",
    re.IGNORECASE,
)
_CAUSE_RE = re.compile(r"^cause\(([^-()]+)->([^()]+)\)\s*(?:\[([A-Za-z0-9_.:-]+)\])?$", re.IGNORECASE)
_TIME_RE = re.compile(r"^time\(([^()]+?)\s+(before|after)\s+([^()]+?)\)\s*(?:\[([A-Za-z0-9_.:-]+)\])?$", re.IGNORECASE)
_NUMBER_RE = re.compile(r"^(-?\d+(?:[.,]\d+)?)\s*([A-Za-z%°/_-]+)?$")


@dataclass(frozen=True)
class EvidenceFact:
    key: str
    value: str
    source_id: str
    modality: str = "certain"
    polarity: str = "positive"


@dataclass(frozen=True)
class NumericExpectation:
    key: str
    value: float
    tolerance: float
    source_id: str
    unit: str = ""


@dataclass(frozen=True)
class RelationEvidence:
    left: str
    relation: str  # cause | before | after
    right: str
    source_id: str


@dataclass(frozen=True)
class NumericConstraint:
    name: str
    key: str
    operator: str  # <= | >=
    limit: float


@dataclass(frozen=True)
class SensorBundle:
    request_text: str
    response_text: str
    domain_id: str
    allowed_domains: tuple[str, ...]
    facts: tuple[EvidenceFact, ...] = ()
    numeric_expectations: tuple[NumericExpectation, ...] = ()
    relations: tuple[RelationEvidence, ...] = ()
    required_response_keys: tuple[str, ...] = ()
    measurement_uncertainty: float | None = None
    measurement_uncertainty_cap: float | None = None
    safety_constraints: tuple[NumericConstraint, ...] = ()
    regulatory_constraints: tuple[NumericConstraint, ...] = ()
    resource_used: float | None = None
    resource_budget: float | None = None
    repeat_fingerprints: tuple[str, ...] = ()
    required_output_fields: tuple[str, ...] = ()
    output_fields: Mapping[str, Any] = field(default_factory=dict)
    metier_id: str = "generic"
    frame_id: str = "general"


@dataclass(frozen=True)
class ParsedAssertion:
    kind: str
    key: str | None = None
    value: str | None = None
    source_id: str | None = None
    modality: str = "unknown"
    polarity: str = "positive"
    left: str | None = None
    relation: str | None = None
    right: str | None = None
    numeric_value: float | None = None
    unit: str = ""


@dataclass(frozen=True)
class SensorReceipt:
    observations: tuple[Observation, ...]
    scope: EvaluationScope
    parsed_assertions: tuple[ParsedAssertion, ...]
    intent_matches: tuple[str, ...]
    receipt_sha256: str


def _norm(text: str) -> str:
    return " ".join(text.casefold().replace("’", "'").split())


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(float(value))


def _nonnegative(value: Any) -> bool:
    return _finite(value) and float(value) >= 0


def classify_intents(request_text: str) -> tuple[str, ...]:
    normalized = _norm(request_text)
    found = []
    for intent, patterns in _INTENT_PATTERNS.items():
        if any(pattern in normalized for pattern in patterns):
            found.append(intent)
    return tuple(found)


def parse_response(response_text: str) -> tuple[ParsedAssertion, ...]:
    out: list[ParsedAssertion] = []
    for raw in [part.strip() for part in response_text.split(";") if part.strip()]:
        match = _CAUSE_RE.match(raw)
        if match:
            out.append(ParsedAssertion(kind="causal", left=_norm(match.group(1)), relation="cause", right=_norm(match.group(2)), source_id=match.group(3)))
            continue
        match = _TIME_RE.match(raw)
        if match:
            out.append(ParsedAssertion(kind="temporal", left=_norm(match.group(1)), relation=match.group(2).lower(), right=_norm(match.group(3)), source_id=match.group(4)))
            continue
        match = _FACT_RE.match(raw)
        if match:
            modality = (match.group(1) or "unknown").lower()
            polarity = "negative" if match.group(2) else "positive"
            key = _norm(match.group(3))
            value = match.group(4).strip()
            nmatch = _NUMBER_RE.match(value)
            numeric_value = None
            unit = ""
            if nmatch:
                try:
                    candidate = float(Decimal(nmatch.group(1).replace(",", ".")))
                    numeric_value = candidate if isfinite(candidate) else None
                except (ArithmeticError, ValueError):
                    numeric_value = None
                unit = (nmatch.group(2) or "").casefold()
            out.append(
                ParsedAssertion(
                    kind="fact",
                    key=key,
                    value=_norm(value),
                    source_id=match.group(5),
                    modality=modality,
                    polarity=polarity,
                    numeric_value=numeric_value,
                    unit=unit,
                )
            )
            continue
        out.append(ParsedAssertion(kind="unsupported", value=raw))
    return tuple(out)


def _obs(bundle: SensorBundle, dimension: str, delta: float, *, measured: bool = True, stage: str | None = None) -> Observation:
    return Observation(
        stage_id=stage or f"sensor:{dimension}",
        dimension=dimension,
        delta=delta,
        amplification=1.0 if measured else None,
        metier_id=bundle.metier_id,
        frame_id=bundle.frame_id,
        evidence_measured=measured,
    )


def _assertions_by_key(parsed: Sequence[ParsedAssertion]) -> dict[str, list[ParsedAssertion]]:
    out: dict[str, list[ParsedAssertion]] = {}
    for item in parsed:
        if item.kind == "fact" and item.key is not None:
            out.setdefault(item.key, []).append(item)
    return out


def sense(bundle: SensorBundle) -> SensorReceipt:
    parsed = parse_response(bundle.response_text)
    by_key = _assertions_by_key(parsed)
    intents = classify_intents(bundle.request_text)
    observations: list[Observation] = []

    # métier
    metier_measured = bool(bundle.domain_id and bundle.allowed_domains)
    metier_delta = 0.0 if metier_measured and bundle.domain_id in bundle.allowed_domains else 1.0
    observations.append(_obs(bundle, "metier", metier_delta, measured=metier_measured))

    # coherence: contradictory values/polarities for same key. An absent
    # response is not evidence of coherence; it is trace_pending.
    coherence_measured = bool(bundle.response_text.strip())
    contradiction = False
    if coherence_measured:
        for items in by_key.values():
            signatures = {(x.value, x.polarity) for x in items}
            if len(signatures) > 1:
                contradiction = True
                break
    observations.append(_obs(bundle, "coherence", 1.0 if contradiction else 0.0, measured=coherence_measured))

    # semantic/factual/epistemic use governed facts. Provenance is checked
    # separately across every governed assertion family (facts, numbers,
    # causal relations, temporal relations).
    if bundle.facts:
        semantic_bad = factual_bad = epistemic_bad = False
        semantic_measured = factual_measured = epistemic_measured = True
        for fact in bundle.facts:
            items = by_key.get(_norm(fact.key), [])
            if not items:
                semantic_measured = factual_measured = source_measured = epistemic_measured = False
                continue
            item = items[0]
            if item.polarity != fact.polarity:
                semantic_bad = True
            if _norm(item.value or "") != _norm(fact.value):
                factual_bad = True
            if item.modality == "unknown":
                epistemic_measured = False
            elif _MODALITY_RANK.get(item.modality, 99) > _MODALITY_RANK.get(fact.modality, -1):
                epistemic_bad = True
        observations.append(_obs(bundle, "semantic", 1.0 if semantic_bad else 0.0, measured=semantic_measured))
        observations.append(_obs(bundle, "factual", 1.0 if factual_bad else 0.0, measured=factual_measured))
        observations.append(_obs(bundle, "epistemic", 1.0 if epistemic_bad else 0.0, measured=epistemic_measured))
    else:
        for dim in ("semantic", "factual", "epistemic"):
            observations.append(_obs(bundle, dim, 0.0, measured=False))

    # provenance across all governed assertion families. A source check is
    # measured only if at least one source-bearing expectation exists and every
    # expected assertion can be located in the bounded response syntax.
    source_expectations = bool(bundle.facts or bundle.numeric_expectations or bundle.relations)
    source_measured = source_expectations
    source_bad = False
    if source_expectations:
        for fact in bundle.facts:
            items = by_key.get(_norm(fact.key), [])
            if not items:
                source_measured = False
                continue
            item = items[0]
            if item.source_id is None or item.source_id != fact.source_id:
                source_bad = True
        for exp in bundle.numeric_expectations:
            items = by_key.get(_norm(exp.key), [])
            item = next((x for x in items if x.numeric_value is not None), None)
            if item is None:
                source_measured = False
                continue
            if item.source_id is None or item.source_id != exp.source_id:
                source_bad = True
        for rel in bundle.relations:
            kind = "causal" if rel.relation == "cause" else "temporal"
            candidates = [x for x in parsed if x.kind == kind]
            matching_shape = [
                x for x in candidates
                if x.left == _norm(rel.left)
                and x.relation == rel.relation
                and x.right == _norm(rel.right)
            ]
            if not matching_shape:
                source_measured = False
                continue
            if not any(x.source_id == rel.source_id for x in matching_shape):
                source_bad = True
    observations.append(_obs(bundle, "source", 1.0 if source_bad else 0.0, measured=source_measured))

    # numeric
    if bundle.numeric_expectations:
        numeric_bad = False
        numeric_measured = True
        for exp in bundle.numeric_expectations:
            if not _finite(exp.value) or not _nonnegative(exp.tolerance):
                numeric_measured = False
                continue
            items = by_key.get(_norm(exp.key), [])
            item = next((x for x in items if x.numeric_value is not None), None)
            if item is None:
                numeric_measured = False
                continue
            if exp.unit and item.unit != exp.unit.casefold():
                numeric_bad = True
            if abs(item.numeric_value - exp.value) > exp.tolerance:
                numeric_bad = True
        observations.append(_obs(bundle, "numeric", 1.0 if numeric_bad else 0.0, measured=numeric_measured))
    else:
        observations.append(_obs(bundle, "numeric", 0.0, measured=False))

    # measurement
    measurement_measured = _nonnegative(bundle.measurement_uncertainty) and _nonnegative(bundle.measurement_uncertainty_cap)
    measurement_bad = measurement_measured and bundle.measurement_uncertainty > bundle.measurement_uncertainty_cap
    observations.append(_obs(bundle, "measurement", 1.0 if measurement_bad else 0.0, measured=measurement_measured))

    # temporal / causal
    if bundle.relations:
        temporal_expected = [r for r in bundle.relations if r.relation in {"before", "after"}]
        causal_expected = [r for r in bundle.relations if r.relation == "cause"]
        temporal_measured = True
        temporal_bad = False
        causal_measured = True
        causal_bad = False
        for rel in temporal_expected:
            found = [x for x in parsed if x.kind == "temporal"]
            if not found:
                temporal_measured = False
            elif not any(x.left == _norm(rel.left) and x.relation == rel.relation and x.right == _norm(rel.right) and x.source_id == rel.source_id for x in found):
                temporal_bad = True
        for rel in causal_expected:
            found = [x for x in parsed if x.kind == "causal"]
            if not found:
                causal_measured = False
            elif not any(x.left == _norm(rel.left) and x.relation == "cause" and x.right == _norm(rel.right) and x.source_id == rel.source_id for x in found):
                causal_bad = True
        observations.append(_obs(bundle, "temporal", 1.0 if temporal_bad else 0.0, measured=temporal_measured if temporal_expected else False))
        observations.append(_obs(bundle, "causal", 1.0 if causal_bad else 0.0, measured=causal_measured if causal_expected else False))
    else:
        observations.append(_obs(bundle, "temporal", 0.0, measured=False))
        observations.append(_obs(bundle, "causal", 0.0, measured=False))

    # ambiguity
    observations.append(_obs(bundle, "ambiguity", 1.0 if len(intents) != 1 else 0.0, measured=bool(bundle.request_text.strip())))

    # safety / regulatory from numeric assertions + hard constraints.
    def constraint_sensor(constraints: Sequence[NumericConstraint], dimension: str) -> Observation:
        if not constraints:
            return _obs(bundle, dimension, 0.0, measured=False)
        bad = False
        measured = True
        for constraint in constraints:
            if not _finite(constraint.limit) or constraint.operator not in {"<=", ">="}:
                measured = False
                continue
            items = by_key.get(_norm(constraint.key), [])
            item = next((x for x in items if x.numeric_value is not None), None)
            if item is None:
                measured = False
                continue
            if constraint.operator == "<=" and item.numeric_value > constraint.limit:
                bad = True
            elif constraint.operator == ">=" and item.numeric_value < constraint.limit:
                bad = True
        return _obs(bundle, dimension, 1.0 if bad else 0.0, measured=measured)

    observations.append(constraint_sensor(bundle.safety_constraints, "safety"))
    observations.append(constraint_sensor(bundle.regulatory_constraints, "regulatory"))

    # resource
    resource_measured = _nonnegative(bundle.resource_used) and _nonnegative(bundle.resource_budget)
    resource_bad = resource_measured and bundle.resource_used > bundle.resource_budget
    observations.append(_obs(bundle, "resource", 1.0 if resource_bad else 0.0, measured=resource_measured))

    # repeatability
    repeat_measured = len(bundle.repeat_fingerprints) >= 2
    repeat_bad = repeat_measured and len(set(bundle.repeat_fingerprints)) != 1
    observations.append(_obs(bundle, "repeatability", 1.0 if repeat_bad else 0.0, measured=repeat_measured))

    # integration
    integration_measured = bool(bundle.required_output_fields)
    integration_bad = integration_measured and any(field not in bundle.output_fields for field in bundle.required_output_fields)
    observations.append(_obs(bundle, "integration", 1.0 if integration_bad else 0.0, measured=integration_measured))

    # intentional: exactly one bounded intent + required response keys present.
    intentional_measured = len(intents) == 1 and bool(bundle.required_response_keys)
    if intentional_measured:
        actual_keys = set(by_key)
        intentional_bad = not set(map(_norm, bundle.required_response_keys)).issubset(actual_keys)
    else:
        intentional_bad = False
    observations.append(_obs(bundle, "intentional", 1.0 if intentional_bad else 0.0, measured=intentional_measured))

    # Unsupported clauses make semantic interpretation incomplete.
    if any(item.kind == "unsupported" for item in parsed):
        observations = [
            Observation(o.stage_id, o.dimension, o.delta, o.amplification, o.metier_id, o.frame_id,
                        False if o.dimension in {"semantic", "factual", "source", "epistemic", "intentional"} else o.evidence_measured,
                        o.invariant_observed)
            for o in observations
        ]

    # Exactly one observation per family, in canonical order.
    by_dim_obs = {o.dimension: o for o in observations}
    ordered = tuple(by_dim_obs[name] for name in TOLERANCE_FAMILIES)
    scope = EvaluationScope(tuple(TOLERANCE_FAMILIES), {})
    payload = {
        "component": SENSOR_COMPONENT_ID,
        "version": SENSOR_VERSION,
        "contract": {
            "request_text": bundle.request_text,
            "response_text_sha256": hashlib.sha256(bundle.response_text.encode()).hexdigest(),
            "domain_id": bundle.domain_id,
            "allowed_domains": list(bundle.allowed_domains),
            "facts": [x.__dict__ for x in bundle.facts],
            "numeric_expectations": [
                {**x.__dict__, "value": repr(x.value), "tolerance": repr(x.tolerance)}
                for x in bundle.numeric_expectations
            ],
            "relations": [x.__dict__ for x in bundle.relations],
            "required_response_keys": list(bundle.required_response_keys),
            "measurement_uncertainty": repr(bundle.measurement_uncertainty),
            "measurement_uncertainty_cap": repr(bundle.measurement_uncertainty_cap),
            "safety_constraints": [{**x.__dict__, "limit": repr(x.limit)} for x in bundle.safety_constraints],
            "regulatory_constraints": [{**x.__dict__, "limit": repr(x.limit)} for x in bundle.regulatory_constraints],
            "resource_used": repr(bundle.resource_used),
            "resource_budget": repr(bundle.resource_budget),
            "repeat_fingerprints": list(bundle.repeat_fingerprints),
            "required_output_fields": list(bundle.required_output_fields),
            "output_field_names": sorted(map(str, bundle.output_fields)),
            "metier_id": bundle.metier_id,
            "frame_id": bundle.frame_id,
        },
        "intents": list(intents),
        "parsed": [item.__dict__ for item in parsed],
        "observations": [
            {
                "stage_id": o.stage_id,
                "dimension": o.dimension,
                "delta": o.delta,
                "amplification": o.amplification,
                "metier_id": o.metier_id,
                "frame_id": o.frame_id,
                "evidence_measured": o.evidence_measured,
            }
            for o in ordered
        ],
    }
    receipt = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return SensorReceipt(ordered, scope, parsed, intents, receipt)
