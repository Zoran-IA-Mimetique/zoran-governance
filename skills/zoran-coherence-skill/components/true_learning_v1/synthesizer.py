"""ZORAN TRUE_LEARNING_V1 — bounded deterministic rule synthesis.

This experiment does not contain a catalog of final linguistic rules.
It searches closed DSLs of generic predicates/transforms and returns the
smallest program consistent with TRAIN. VALIDATION is used before the final
HOLDOUT evaluation. No canonical promotion is possible from this module.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any, Callable, Iterable


STATUS_LEARNING = "LEARNING"
STATUS_ACQUIRED_BOUNDED = "ACQUIRED_BOUNDED"
STATUS_FAIL = "FAIL"
STATUS_VETO_TRACE_ABSENTE = "VETO_TRACE_ABSENTE"


@dataclass(frozen=True)
class Example:
    example_id: str
    features: dict[str, Any]
    expected: Any


@dataclass(frozen=True)
class Program:
    program_id: str
    description: str
    complexity: int
    apply: Callable[[dict[str, Any]], Any]


@dataclass(frozen=True)
class SynthesisResult:
    status: str
    program_id: str | None
    description: str | None
    train_pass: int
    validation_pass: int
    holdout_pass: int
    train_total: int
    validation_total: int
    holdout_total: int
    trace_sha256: str
    promotion: str = "FORBIDDEN"


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _digest(value: Any) -> str:
    return sha256(_canonical(value)).hexdigest()


def _score(program: Program, examples: Iterable[Example]) -> int:
    return sum(1 for ex in examples if program.apply(ex.features) == ex.expected)


def _select_unique_minimal(programs: list[Program], train: list[Example], validation: list[Example] | None = None) -> Program | None:
    validation = validation or []
    winners = [p for p in programs if _score(p, train) == len(train)]
    if validation:
        winners = [p for p in winners if _score(p, validation) == len(validation)]
    if not winners:
        return None
    min_complexity = min(p.complexity for p in winners)
    winners = sorted((p for p in winners if p.complexity == min_complexity), key=lambda p: p.program_id)
    if len(winners) != 1:
        return None
    return winners[0]


def _case_programs() -> list[Program]:
    programs: list[Program] = []
    predicates: list[tuple[str, Callable[[dict[str, Any]], bool], int]] = [
        ("always", lambda f: True, 1),
        ("token_is_all_upper", lambda f: bool(f["token"]) and str(f["token"]).isupper(), 2),
        ("token_is_all_lower", lambda f: bool(f["token"]) and str(f["token"]).islower(), 2),
        ("token_initial_upper", lambda f: bool(f["token"]) and str(f["token"])[0].isupper(), 2),
        ("token_class_function_word", lambda f: f.get("token_class") == "FUNCTION_WORD", 2),
        ("token_class_content_word", lambda f: f.get("token_class") == "CONTENT_WORD", 2),
    ]
    # Explicit Occam prior: a one-character edit is cheaper than rewriting the whole token.
    transforms: list[tuple[str, Callable[[str], str], int]] = [
        ("identity", lambda s: s, 1),
        ("lower_first", lambda s: s[:1].lower() + s[1:] if s else s, 2),
        ("lower_all", lambda s: s.lower(), 3),
        ("upper_all", lambda s: s.upper(), 3),
    ]

    for pred_name, pred, pc in predicates:
        for tr_name, tr, tc in transforms:
            if tr_name == "identity":
                continue

            def make_apply(pred=pred, tr=tr):
                return lambda f: tr(str(f["token"])) if pred(f) else str(f["token"])

            programs.append(Program(
                program_id=f"IF_{pred_name}_THEN_{tr_name}",
                description=f"if {pred_name} then {tr_name} else identity",
                complexity=pc + tc,
                apply=make_apply(),
            ))
    return programs


def _cardinality_programs() -> list[Program]:
    programs: list[Program] = []
    predicates: list[tuple[str, Callable[[int], bool], int]] = [
        ("eq_0", lambda n: n == 0, 2),
        ("eq_1", lambda n: n == 1, 2),
        ("gt_0", lambda n: n > 0, 2),
        ("gt_1", lambda n: n > 1, 2),
        ("le_1", lambda n: n <= 1, 2),
    ]
    for name, pred, complexity in predicates:
        programs.append(Program(
            program_id=f"ACCEPT_IF_{name}",
            description=f"ACCEPT iff antecedent_count {name}",
            complexity=complexity,
            apply=lambda f, pred=pred: "ACCEPT" if pred(int(f["antecedent_count"])) else "REJECT",
        ))
    return programs


def _learn_leaf(examples: list[Example], predicate: Callable[[dict[str, Any]], bool]) -> Any | None:
    values = {ex.expected for ex in examples if predicate(ex.features)}
    return next(iter(values)) if len(values) == 1 else None


def _nominal_selector_programs(train: list[Example]) -> list[Program]:
    """Learn leaf values; only the generic tree shapes are predeclared.

    No French surface value (ce/cette/ces/etc.) is present in this source.
    """
    shapes = [
        ("number_then_gender", 4),
        ("gender_then_number", 4),
        ("number_only", 2),
        ("gender_only", 2),
    ]
    programs: list[Program] = []
    for shape, complexity in shapes:
        if shape == "number_then_gender":
            p_pl = lambda f: f.get("number") == "pl"
            p_f_sg = lambda f: f.get("number") == "sg" and f.get("gender") == "f"
            p_other = lambda f: not p_pl(f) and not p_f_sg(f)
            leaves = [_learn_leaf(train, p_pl), _learn_leaf(train, p_f_sg), _learn_leaf(train, p_other)]
            if any(v is None for v in leaves):
                continue
            pl, fsg, other = leaves
            programs.append(Program(
                "TREE_number_then_gender",
                "if number=pl then learned_leaf_A else if gender=f then learned_leaf_B else learned_leaf_C",
                complexity,
                lambda f, pl=pl, fsg=fsg, other=other: pl if f.get("number") == "pl" else (fsg if f.get("gender") == "f" else other),
            ))
        elif shape == "gender_then_number":
            p_f = lambda f: f.get("gender") == "f"
            p_m_pl = lambda f: f.get("gender") == "m" and f.get("number") == "pl"
            p_other = lambda f: not p_f(f) and not p_m_pl(f)
            leaves = [_learn_leaf(train, p_f), _learn_leaf(train, p_m_pl), _learn_leaf(train, p_other)]
            if any(v is None for v in leaves):
                continue
            fv, mpl, other = leaves
            programs.append(Program(
                "TREE_gender_then_number",
                "if gender=f then learned_leaf_A else if number=pl then learned_leaf_B else learned_leaf_C",
                complexity,
                lambda f, fv=fv, mpl=mpl, other=other: fv if f.get("gender") == "f" else (mpl if f.get("number") == "pl" else other),
            ))
        elif shape == "number_only":
            p_pl = lambda f: f.get("number") == "pl"
            p_sg = lambda f: f.get("number") != "pl"
            leaves = [_learn_leaf(train, p_pl), _learn_leaf(train, p_sg)]
            if any(v is None for v in leaves):
                continue
            pl, sg = leaves
            programs.append(Program(
                "TREE_number_only", "if number=pl then learned_leaf_A else learned_leaf_B", complexity,
                lambda f, pl=pl, sg=sg: pl if f.get("number") == "pl" else sg,
            ))
        else:
            p_f = lambda f: f.get("gender") == "f"
            p_m = lambda f: f.get("gender") != "f"
            leaves = [_learn_leaf(train, p_f), _learn_leaf(train, p_m)]
            if any(v is None for v in leaves):
                continue
            fv, mv = leaves
            programs.append(Program(
                "TREE_gender_only", "if gender=f then learned_leaf_A else learned_leaf_B", complexity,
                lambda f, fv=fv, mv=mv: fv if f.get("gender") == "f" else mv,
            ))
    return programs


def synthesize_case_rule(train: list[Example], validation: list[Example], holdout: list[Example]) -> SynthesisResult:
    program = _select_unique_minimal(_case_programs(), train, validation)
    return _finish("CASE", program, train, validation, holdout)


def synthesize_cardinality_rule(train: list[Example], validation: list[Example], holdout: list[Example]) -> SynthesisResult:
    program = _select_unique_minimal(_cardinality_programs(), train, validation)
    return _finish("CARDINALITY", program, train, validation, holdout)


def synthesize_nominal_selector_rule(train: list[Example], validation: list[Example], holdout: list[Example]) -> SynthesisResult:
    program = _select_unique_minimal(_nominal_selector_programs(train), train, validation)
    return _finish("NOMINAL_SELECTOR", program, train, validation, holdout)


def _finish(family: str, program: Program | None, train: list[Example], validation: list[Example], holdout: list[Example]) -> SynthesisResult:
    if program is None:
        trace = {"family": family, "status": STATUS_VETO_TRACE_ABSENTE, "reason": "no unique minimal consistent program"}
        return SynthesisResult(STATUS_VETO_TRACE_ABSENTE, None, None, 0, 0, 0, len(train), len(validation), len(holdout), _digest(trace))

    train_pass = _score(program, train)
    validation_pass = _score(program, validation)
    holdout_pass = _score(program, holdout)
    status = STATUS_ACQUIRED_BOUNDED if (
        train_pass == len(train)
        and validation_pass == len(validation)
        and holdout_pass == len(holdout)
    ) else STATUS_FAIL

    trace = {
        "family": family,
        "program_id": program.program_id,
        "description": program.description,
        "complexity": program.complexity,
        "train_ids": [e.example_id for e in train],
        "validation_ids": [e.example_id for e in validation],
        "holdout_ids": [e.example_id for e in holdout],
        "scores": [train_pass, validation_pass, holdout_pass],
        "status": status,
        "promotion": "FORBIDDEN",
    }
    return SynthesisResult(
        status, program.program_id, program.description,
        train_pass, validation_pass, holdout_pass,
        len(train), len(validation), len(holdout), _digest(trace)
    )
