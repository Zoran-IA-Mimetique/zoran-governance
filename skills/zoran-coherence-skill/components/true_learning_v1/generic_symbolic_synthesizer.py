"""Generic bounded symbolic synthesis for previously unseen categorical families.

No family name, French surface token or final rule is embedded in this module.
The DSL is generated from observed categorical feature/value predicates and
conjunctions of at most two predicates. Programs are deterministic decision
lists whose leaf outputs are learned from TRAIN. VALIDATION may disambiguate;
HOLDOUT is evaluated only after the program is frozen.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from itertools import combinations, permutations
import json
from typing import Any

from components.true_learning_v1.synthesizer import (
    Example,
    SynthesisResult,
    STATUS_ACQUIRED_BOUNDED,
    STATUS_FAIL,
    STATUS_VETO_TRACE_ABSENTE,
)


@dataclass(frozen=True)
class Predicate:
    predicate_id: str
    complexity: int
    operator: str
    key: str | None = None
    value: Any = None
    terms: tuple["Predicate", ...] = ()

    def test(self, features: dict[str, Any]) -> bool:
        if self.operator == "EQ":
            return features.get(self.key) == self.value
        if self.operator == "AND" and len(self.terms) == 2:
            return self.terms[0].test(features) and self.terms[1].test(features)
        raise ValueError("unsupported in-memory predicate")

    def to_spec(self) -> dict[str, Any]:
        if self.operator == "EQ":
            return {"operator": "EQ", "key": self.key, "value": self.value}
        if self.operator == "AND" and len(self.terms) == 2:
            return {"operator": "AND", "terms": [item.to_spec() for item in self.terms]}
        raise ValueError("unsupported predicate serialization")


@dataclass(frozen=True)
class SymbolicProgram:
    program_id: str
    description: str
    complexity: int
    rules: tuple[tuple[Predicate, Any], ...]
    default: Any

    def apply(self, features: dict[str, Any]) -> Any:
        for predicate, output in self.rules:
            if predicate.test(features):
                return output
        return self.default


@dataclass(frozen=True)
class GenericSynthesisMetrics:
    observed_predicates: int
    candidate_orders_evaluated: int
    train_consistent_programs: int
    validation_consistent_programs: int
    selected_programs: int


@dataclass(frozen=True)
class GenericSynthesisRun:
    result: SynthesisResult
    program: SymbolicProgram | None
    metrics: GenericSynthesisMetrics


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _digest(value: Any) -> str:
    return sha256(_canonical(value)).hexdigest()


def _observed_predicates(train: list[Example]) -> tuple[Predicate, ...]:
    values: dict[str, set[Any]] = {}
    for ex in train:
        for key, value in ex.features.items():
            if isinstance(value, (str, int, bool)) or value is None:
                values.setdefault(key, set()).add(value)
    singles: list[Predicate] = []
    for key in sorted(values):
        ordered = sorted(values[key], key=lambda x: _canonical(x))
        for value in ordered:
            pid = f"EQ[{key}={json.dumps(value, ensure_ascii=False, sort_keys=True)}]"
            singles.append(Predicate(pid, 1, "EQ", key=key, value=value))
    predicates = list(singles)
    for a, b in combinations(singles, 2):
        if a.key == b.key:
            continue
        left, right = sorted((a, b), key=lambda item: item.predicate_id)
        predicates.append(Predicate(
            f"AND[{left.predicate_id}&{right.predicate_id}]",
            3,
            "AND",
            terms=(left, right),
        ))
    return tuple(sorted(predicates, key=lambda p: (p.complexity, p.predicate_id)))


def _learn_program(order: tuple[Predicate, ...], train: list[Example]) -> SymbolicProgram | None:
    unmatched = list(train)
    rules: list[tuple[Predicate, Any]] = []
    used_any = False
    for predicate in order:
        matched = [ex for ex in unmatched if predicate.test(ex.features)]
        if not matched:
            return None
        outputs = {ex.expected for ex in matched}
        if len(outputs) != 1:
            return None
        output = next(iter(outputs))
        rules.append((predicate, output))
        used_any = True
        unmatched = [ex for ex in unmatched if not predicate.test(ex.features)]
    if not used_any:
        return None
    defaults = {ex.expected for ex in unmatched}
    if len(defaults) != 1:
        return None
    default = next(iter(defaults))
    signature = [(p.predicate_id, out) for p, out in rules]
    program_id = "SYMLIST-" + _digest({"rules": signature, "default": default})[:24]
    description = " ; ".join(f"if {p.predicate_id} => learned_leaf" for p, _ in rules) + " ; else learned_default"
    complexity = sum(p.complexity + 1 for p, _ in rules) + 1
    return SymbolicProgram(program_id, description, complexity, tuple(rules), default)


def _score(program: SymbolicProgram, examples: list[Example]) -> int:
    return sum(1 for ex in examples if program.apply(ex.features) == ex.expected)


def _behavior_signature(program: SymbolicProgram, examples: list[Example]) -> tuple[Any, ...]:
    return tuple(program.apply(ex.features) for ex in examples)


def _candidate_programs(train: list[Example], max_rules: int) -> tuple[tuple[SymbolicProgram, ...], int, int]:
    predicates = _observed_predicates(train)
    programs: dict[str, SymbolicProgram] = {}
    evaluated = 0
    for width in range(1, max_rules + 1):
        for order in permutations(predicates, width):
            evaluated += 1
            candidate = _learn_program(order, train)
            if candidate is None or _score(candidate, train) != len(train):
                continue
            programs[candidate.program_id] = candidate
    return (
        tuple(sorted(programs.values(), key=lambda p: (p.complexity, p.program_id))),
        len(predicates),
        evaluated,
    )


def synthesize_generic_categorical_program(
    train: list[Example],
    validation: list[Example],
    holdout: list[Example],
    *,
    family: str = "UNSEEN_CATEGORICAL_FAMILY",
    max_rules: int = 4,
) -> GenericSynthesisRun:
    if not train or not validation or not holdout:
        raise ValueError("TRAIN, VALIDATION and HOLDOUT must all be non-empty")
    if max_rules < 1 or max_rules > 6:
        raise ValueError("max_rules outside bounded search contract")

    train_candidates, predicate_count, evaluated = _candidate_programs(train, max_rules)
    candidates = [p for p in train_candidates if _score(p, validation) == len(validation)]
    base_metrics = {
        "observed_predicates": predicate_count,
        "candidate_orders_evaluated": evaluated,
        "train_consistent_programs": len(train_candidates),
        "validation_consistent_programs": len(candidates),
    }
    if not candidates:
        trace = {"family": family, "status": STATUS_VETO_TRACE_ABSENTE, "reason": "no consistent bounded symbolic program"}
        result = SynthesisResult(STATUS_VETO_TRACE_ABSENTE, None, None, 0, 0, 0, len(train), len(validation), len(holdout), _digest(trace))
        return GenericSynthesisRun(result, None, GenericSynthesisMetrics(**base_metrics, selected_programs=0))

    min_complexity = min(p.complexity for p in candidates)
    minimal = [p for p in candidates if p.complexity == min_complexity]
    evidence = train + validation
    by_behavior: dict[tuple[Any, ...], list[SymbolicProgram]] = {}
    for program in minimal:
        by_behavior.setdefault(_behavior_signature(program, evidence), []).append(program)
    if len(by_behavior) != 1:
        trace = {"family": family, "status": STATUS_VETO_TRACE_ABSENTE, "reason": "multiple minimal semantic behaviors", "behaviors": len(by_behavior)}
        result = SynthesisResult(STATUS_VETO_TRACE_ABSENTE, None, None, len(train), len(validation), 0, len(train), len(validation), len(holdout), _digest(trace))
        return GenericSynthesisRun(result, None, GenericSynthesisMetrics(**base_metrics, selected_programs=0))

    semantic_class = next(iter(by_behavior.values()))
    program = min(semantic_class, key=lambda p: p.program_id)
    train_pass = _score(program, train)
    validation_pass = _score(program, validation)
    holdout_pass = _score(program, holdout)
    status = STATUS_ACQUIRED_BOUNDED if holdout_pass == len(holdout) else STATUS_FAIL
    trace = {
        "family": family,
        "program_id": program.program_id,
        "description": program.description,
        "complexity": program.complexity,
        "train_ids": [e.example_id for e in train],
        "validation_ids": [e.example_id for e in validation],
        "holdout_ids": [e.example_id for e in holdout],
        "scores": [train_pass, validation_pass, holdout_pass],
        "candidate_count": len(candidates),
        "minimal_semantic_class_size": len(semantic_class),
        "status": status,
        "promotion": "FORBIDDEN",
    }
    result = SynthesisResult(
        status, program.program_id, program.description,
        train_pass, validation_pass, holdout_pass,
        len(train), len(validation), len(holdout), _digest(trace),
    )
    return GenericSynthesisRun(
        result,
        program,
        GenericSynthesisMetrics(**base_metrics, selected_programs=1),
    )


def synthesize_generic_categorical_rule(
    train: list[Example],
    validation: list[Example],
    holdout: list[Example],
    *,
    family: str = "UNSEEN_CATEGORICAL_FAMILY",
    max_rules: int = 4,
) -> SynthesisResult:
    return synthesize_generic_categorical_program(
        train,
        validation,
        holdout,
        family=family,
        max_rules=max_rules,
    ).result
