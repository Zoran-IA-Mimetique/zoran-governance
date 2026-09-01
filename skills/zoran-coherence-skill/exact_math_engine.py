from __future__ import annotations

"""Closed exact-arithmetic proofs for natural-language questions.

The engine recognises a deliberately small operation vocabulary, binds each
operand to a question term or to an explicit expression, calculates with
``Fraction`` and verifies the result by the inverse operation.  It never uses
``eval`` and never guesses when a binding or a unit is ambiguous.
"""

import hashlib
import ast
import json
import math
import re
import unicodedata
from dataclasses import dataclass
from fractions import Fraction

from structural_reasoning_gate import ProofStatus


COMPONENT_ID = "zoran.exact-math-engine"
VERSION = "22.3.0"


_NUMBER_RE = re.compile(
    r"(?<![A-Za-z0-9])(?P<sign>[-+])?(?P<number>"
    r"\d+/\d+|\d{1,3}(?:[ ,]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)"
    r"(?P<percent>%)?"
)

_STOP = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "between", "by", "calculate",
    "did", "do", "does", "for", "from", "how", "in", "is", "it", "many",
    "much", "of", "on", "or", "than", "that", "the", "there", "to", "total",
    "was", "were", "what", "which", "with", "year",
    "a-t-il", "au", "aux", "avec", "calculer", "combien", "dans", "de", "des",
    "du", "en", "entre", "est", "il", "la", "le", "les", "par", "plus", "que",
    "quel", "quelle", "quels", "quelles", "sur", "un", "une", "y",
})

_CUE_WORDS = frozenset({
    "addition", "average", "combined", "difference", "divide", "divided", "fewer",
    "increase", "less", "mean", "more", "multiply", "multiplied", "percent",
    "percentage", "product", "ratio", "remainder", "sum",
    "augmentation", "difference", "divise", "moyenne", "pourcentage", "produit",
    "reste", "somme", "fois",
})

_UNIT_REGISTRY: dict[str, tuple[str, Fraction, str]] = {
    "mm": ("length", Fraction(1, 1000), "m"),
    "millimeter": ("length", Fraction(1, 1000), "m"),
    "millimetre": ("length", Fraction(1, 1000), "m"),
    "cm": ("length", Fraction(1, 100), "m"),
    "centimeter": ("length", Fraction(1, 100), "m"),
    "centimetre": ("length", Fraction(1, 100), "m"),
    "m": ("length", Fraction(1), "m"),
    "meter": ("length", Fraction(1), "m"),
    "metre": ("length", Fraction(1), "m"),
    "km": ("length", Fraction(1000), "m"),
    "kilometer": ("length", Fraction(1000), "m"),
    "kilometre": ("length", Fraction(1000), "m"),
    "mg": ("mass", Fraction(1, 1000), "g"),
    "milligram": ("mass", Fraction(1, 1000), "g"),
    "g": ("mass", Fraction(1), "g"),
    "gram": ("mass", Fraction(1), "g"),
    "gramme": ("mass", Fraction(1), "g"),
    "kg": ("mass", Fraction(1000), "g"),
    "kilogram": ("mass", Fraction(1000), "g"),
    "kilogramme": ("mass", Fraction(1000), "g"),
    "ml": ("volume", Fraction(1, 1000), "l"),
    "milliliter": ("volume", Fraction(1, 1000), "l"),
    "millilitre": ("volume", Fraction(1, 1000), "l"),
    "l": ("volume", Fraction(1), "l"),
    "liter": ("volume", Fraction(1), "l"),
    "litre": ("volume", Fraction(1), "l"),
    "s": ("time", Fraction(1), "s"),
    "second": ("time", Fraction(1), "s"),
    "min": ("time", Fraction(60), "s"),
    "minute": ("time", Fraction(60), "s"),
    "h": ("time", Fraction(3600), "s"),
    "hour": ("time", Fraction(3600), "s"),
    "heure": ("time", Fraction(3600), "s"),
    "day": ("time", Fraction(86400), "s"),
    "jour": ("time", Fraction(86400), "s"),
}


@dataclass(frozen=True)
class ExactMathRequest:
    context: str
    question: str
    answer: str


@dataclass(frozen=True)
class _Quantity:
    value: Fraction
    raw: str
    start: int
    end: int
    percent: bool
    dimension: str = ""
    factor: Fraction = Fraction(1)
    base_unit: str = ""

    @property
    def base_value(self) -> Fraction:
        return self.value * self.factor


@dataclass(frozen=True)
class ExactMathProof:
    status: ProofStatus
    reason: str
    operation: str
    operands: tuple[str, ...]
    exact_result: str
    unit: str
    evidence_quotes: tuple[str, ...]
    inverse_trace: tuple[str, ...]
    receipt_sha256: str

    @property
    def applicable(self) -> bool:
        return self.status is not ProofStatus.NOT_APPLICABLE


def _norm(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value.casefold())
    folded = "".join(char for char in folded if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)?", folded))


def _stem(token: str) -> str:
    aliases = {
        "families": "family", "familles": "famille", "households": "household",
        "menages": "menage", "people": "person", "persons": "person",
    }
    if token in aliases:
        return aliases[token]
    for suffix in ("ies", "es", "s"):
        if token.endswith(suffix) and len(token) > len(suffix) + 2:
            return token[:-3] + "y" if suffix == "ies" else token[:-len(suffix)]
    return token


def _fraction(raw: str) -> Fraction:
    compact = raw.replace(" ", "")
    if "/" in compact:
        numerator, denominator = compact.split("/", 1)
        if int(denominator) == 0:
            raise ZeroDivisionError
        return Fraction(int(numerator), int(denominator))
    if "," in compact and "." not in compact:
        groups = compact.split(",")
        compact = "".join(groups) if len(groups[-1]) == 3 and len(groups) > 1 else ".".join(groups)
    else:
        compact = compact.replace(",", "")
    return Fraction(compact)


def _quantities(text: str, *, drop_years: bool = False) -> tuple[_Quantity, ...]:
    result: list[_Quantity] = []
    for match in _NUMBER_RE.finditer(text):
        try:
            value = _fraction(match.group("number"))
        except (ValueError, ZeroDivisionError):
            continue
        if match.group("sign") == "-":
            value = -value
        if drop_years and value.denominator == 1 and 1900 <= value <= 2100 and not match.group("percent"):
            continue
        suffix = text[match.end():match.end() + 24]
        unit_match = re.match(r"\s*([A-Za-zÀ-ÿ]+)", suffix)
        unit_token = _stem(_norm(unit_match.group(1))) if unit_match else ""
        dimension, factor, base_unit = _UNIT_REGISTRY.get(unit_token, ("", Fraction(1), ""))
        result.append(_Quantity(
            value / 100 if match.group("percent") else value,
            match.group(0), match.start(), match.end(), bool(match.group("percent")),
            dimension, factor, base_unit,
        ))
    return tuple(result)


def _operation(question: str) -> str:
    q = f" {_norm(question)} "
    if "=" in question and re.search(r"\b[xyz]\b|\d[xyz]\b", question, flags=re.I) and any(cue in q for cue in (" solve ", " resolve ", " resous ", " equation ")):
        return "solve_linear"
    if any(cue in q for cue in (
        " how many more ", " how much more ", " how many fewer ", " how much less ",
        " difference between ", " difference ", " de plus que ", " de moins que ", " difference entre ",
    )):
        return "difference"
    if any(cue in q for cue in (" percentage increase ", " percent increase ", " pourcentage d augmentation ")):
        return "percentage_change"
    if any(cue in q for cue in (" average ", " arithmetic mean ", " moyenne ")):
        return "mean"
    if any(cue in q for cue in (" divided by ", " quotient ", " ratio of ", " divise par ")):
        return "divide"
    if any(cue in q for cue in (" multiplied by ", " product of ", " fois ", " produit de ")):
        return "multiply"
    if any(cue in q for cue in (" in total ", " combined ", " sum of ", " sum ", " au total ", " somme de ")):
        return "sum"
    return ""


def _question_terms(question: str) -> tuple[str, ...]:
    terms: list[str] = []
    for token in _norm(question).split():
        term = _stem(token)
        if term in _STOP or term in _CUE_WORDS or term.isdigit() or len(term) < 2:
            continue
        if term not in terms:
            terms.append(term)
    return tuple(terms)


def _sentences(text: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in re.split(r"(?<=[.!?])\s+|\s*[;|]\s*", " ".join(text.split())) if part.strip())


def _bound_operands(context: str, question: str, operation: str) -> tuple[tuple[_Quantity, ...], tuple[str, ...]]:
    explicit = _quantities(question, drop_years=operation not in {"divide", "multiply"})
    if len(explicit) >= 2:
        return explicit, (question.strip(),)
    terms = _question_terms(question)
    candidates: list[tuple[int, int, _Quantity, str]] = []
    for sentence in _sentences(context):
        quantities = _quantities(sentence, drop_years=True)
        if not quantities:
            continue
        normalized = _norm(sentence)
        for term_index, term in enumerate(terms):
            for occurrence in re.finditer(rf"\b{re.escape(term)}(?:s|es)?\b", normalized):
                nearest = min(quantities, key=lambda item: min(abs(item.start - occurrence.end()), abs(occurrence.start() - item.end)))
                distance = min(abs(nearest.start - occurrence.end()), abs(occurrence.start() - nearest.end))
                if distance <= 80:
                    candidates.append((term_index, distance, nearest, sentence))
    selected: list[_Quantity] = []
    evidence: list[str] = []
    for term_index in range(len(terms)):
        options = sorted((item for item in candidates if item[0] == term_index), key=lambda item: (item[1], item[2].start))
        for _, _, quantity, sentence in options:
            if all(quantity.base_value != prior.base_value for prior in selected):
                selected.append(quantity)
                evidence.append(sentence)
                break
        if operation in {"difference", "percentage_change", "divide", "multiply"} and len(selected) == 2:
            break
    if len(selected) >= 2:
        return tuple(selected), tuple(dict.fromkeys(evidence))
    global_values = _quantities(context, drop_years=True)
    distinct: list[_Quantity] = []
    seen: set[tuple[Fraction, str]] = set()
    for item in global_values:
        key = item.base_value, item.dimension
        if key not in seen:
            seen.add(key)
            distinct.append(item)
    if 2 <= len(distinct) <= 8:
        return tuple(distinct), _sentences(context)
    return (), ()


def _compatible(operands: tuple[_Quantity, ...], operation: str) -> tuple[bool, tuple[Fraction, ...], str]:
    if operation not in {"difference", "sum", "mean", "percentage_change"}:
        return True, tuple(item.value for item in operands), ""
    dimensions = {item.dimension for item in operands if item.dimension}
    if len(dimensions) > 1:
        return False, (), ""
    if dimensions and any(not item.dimension for item in operands):
        return False, (), ""
    if dimensions:
        base_unit = next(item.base_unit for item in operands if item.dimension)
        return True, tuple(item.base_value for item in operands), base_unit
    return True, tuple(item.value for item in operands), ""


def _calculate(operation: str, operands: tuple[Fraction, ...]) -> tuple[Fraction | None, tuple[str, ...]]:
    if len(operands) < 2:
        return None, ()
    if operation == "difference":
        result = abs(operands[0] - operands[1])
        inverse = (f"{_fmt(min(operands[:2]))}+{_fmt(result)}={_fmt(max(operands[:2]))}",)
    elif operation == "sum":
        result = sum(operands, Fraction(0))
        inverse = (f"{_fmt(result)}-{_fmt(operands[-1])}={_fmt(result-operands[-1])}",)
    elif operation == "mean":
        result = sum(operands, Fraction(0)) / len(operands)
        inverse = (f"{_fmt(result)}*{len(operands)}={_fmt(sum(operands, Fraction(0)))}",)
    elif operation == "multiply":
        result = math.prod(operands)
        inverse = (f"{_fmt(result)}/{_fmt(operands[0])}={_fmt(result/operands[0])}" if operands[0] else "inverse=undefined",)
    elif operation == "divide":
        if operands[1] == 0:
            return None, ("division_by_zero",)
        result = operands[0] / operands[1]
        inverse = (f"{_fmt(result)}*{_fmt(operands[1])}={_fmt(operands[0])}",)
    elif operation == "percentage_change":
        if operands[0] == 0:
            return None, ("zero_baseline",)
        result = (operands[1] - operands[0]) / operands[0]
        inverse = (f"{_fmt(operands[0])}*(1+{_fmt(result)})={_fmt(operands[1])}",)
    else:
        return None, ()
    return result, inverse


def _linear_form(node: ast.AST, variable: str) -> tuple[Fraction, Fraction]:
    """Return coefficient and constant for one affine expression."""
    if isinstance(node, ast.Expression):
        return _linear_form(node.body, variable)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return Fraction(str(node.value)), Fraction(0)
    if isinstance(node, ast.Name) and node.id == variable:
        return Fraction(0), Fraction(1)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        constant, coefficient = _linear_form(node.operand, variable)
        sign = -1 if isinstance(node.op, ast.USub) else 1
        return constant * sign, coefficient * sign
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub)):
        left_constant, left_coefficient = _linear_form(node.left, variable)
        right_constant, right_coefficient = _linear_form(node.right, variable)
        sign = -1 if isinstance(node.op, ast.Sub) else 1
        return left_constant + sign * right_constant, left_coefficient + sign * right_coefficient
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
        left_constant, left_coefficient = _linear_form(node.left, variable)
        right_constant, right_coefficient = _linear_form(node.right, variable)
        if left_coefficient and right_coefficient:
            raise ValueError("NONLINEAR_EQUATION")
        return (
            left_constant * right_constant,
            left_coefficient * right_constant + right_coefficient * left_constant,
        )
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        numerator_constant, numerator_coefficient = _linear_form(node.left, variable)
        denominator_constant, denominator_coefficient = _linear_form(node.right, variable)
        if denominator_coefficient or denominator_constant == 0:
            raise ValueError("NONLINEAR_OR_ZERO_DENOMINATOR")
        return numerator_constant / denominator_constant, numerator_coefficient / denominator_constant
    raise ValueError("EQUATION_SYNTAX_UNSUPPORTED")


def _solve_linear(question: str) -> tuple[Fraction, str, tuple[str, ...]]:
    match = re.search(r"([0-9xyzXYZ+*/().\-\s]+)=([0-9xyzXYZ+*/().\-\s]+)", question)
    if not match:
        raise ValueError("EQUATION_NOT_BOUND")
    raw_left, raw_right = match.group(1).strip(), match.group(2).strip()
    variables = sorted(set(re.findall(r"[xyz]", raw_left + raw_right, flags=re.I)))
    if len(variables) != 1:
        raise ValueError("EQUATION_VARIABLE_AMBIGUOUS")
    variable = variables[0].casefold()

    def prepare(expression: str) -> str:
        expression = expression.casefold().replace("^", "**")
        expression = re.sub(r"(?<=\d)(?=[xyz])", "*", expression)
        expression = re.sub(r"(?<=[xyz])(?=\d)", "*", expression)
        if not re.fullmatch(r"[0-9xyz+*/().\-\s]+", expression):
            raise ValueError("EQUATION_SYNTAX_UNSUPPORTED")
        return expression

    left = prepare(raw_left)
    right = prepare(raw_right)
    left_constant, left_coefficient = _linear_form(ast.parse(left, mode="eval"), variable)
    right_constant, right_coefficient = _linear_form(ast.parse(right, mode="eval"), variable)
    coefficient = left_coefficient - right_coefficient
    if coefficient == 0:
        raise ValueError("EQUATION_NO_UNIQUE_SOLUTION")
    solution = (right_constant - left_constant) / coefficient
    inverse = (f"substitute {variable}={_fmt(solution)} into {raw_left}={raw_right}",)
    return solution, variable, inverse


def _fmt(value: Fraction) -> str:
    if value.denominator == 1:
        return str(value.numerator)
    finite = value.denominator
    while finite % 2 == 0:
        finite //= 2
    while finite % 5 == 0:
        finite //= 5
    if finite == 1:
        return format(float(value), ".15g")
    return f"{value.numerator}/{value.denominator}"


def _finish(
    status: ProofStatus, reason: str, operation: str = "", operands: tuple[Fraction, ...] = (),
    result: Fraction | None = None, unit: str = "", evidence: tuple[str, ...] = (), inverse: tuple[str, ...] = (),
) -> ExactMathProof:
    payload = {
        "component": COMPONENT_ID, "version": VERSION, "status": status.value,
        "reason": reason, "operation": operation, "operands": [_fmt(item) for item in operands],
        "result": _fmt(result) if result is not None else "", "unit": unit,
        "evidence_sha256": [hashlib.sha256(item.encode()).hexdigest() for item in evidence],
        "inverse": list(inverse),
    }
    receipt = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return ExactMathProof(status, reason, operation, tuple(_fmt(item) for item in operands), _fmt(result) if result is not None else "", unit, evidence, inverse, receipt)


class ExactMathEngine:
    """Exact closed-world arithmetic with semantic operand and unit binding."""

    def evaluate(self, request: ExactMathRequest | None) -> ExactMathProof:
        if not isinstance(request, ExactMathRequest) or not all(isinstance(item, str) and item.strip() for item in (request.context, request.question, request.answer)):
            return _finish(ProofStatus.UNRESOLVED, "EXACT_MATH_REQUEST_INVALID")
        operation = _operation(request.question)
        if not operation:
            return _finish(ProofStatus.NOT_APPLICABLE, "EXACT_MATH_NOT_APPLICABLE")
        answer_values = _quantities(request.answer)
        if not answer_values:
            return _finish(ProofStatus.UNRESOLVED, "EXACT_MATH_ANSWER_MISSING", operation)
        if operation == "solve_linear":
            try:
                solution, variable, inverse = _solve_linear(request.question)
            except (SyntaxError, ValueError) as exc:
                return _finish(ProofStatus.UNRESOLVED, str(exc), operation)
            observed = {item.value for item in answer_values}
            status = ProofStatus.PROVED if observed == {solution} else ProofStatus.DISPROVED
            reason = "EXACT_LINEAR_SOLUTION_VERIFIED" if status is ProofStatus.PROVED else "EXACT_LINEAR_SOLUTION_CONTRADICTION"
            return _finish(status, reason, operation, (), solution, variable, (request.question.strip(),), inverse)
        operands, evidence = _bound_operands(request.context, request.question, operation)
        minimum, maximum = (2, 2) if operation in {"difference", "percentage_change", "divide", "multiply"} else (2, 8)
        if not minimum <= len(operands) <= maximum:
            return _finish(ProofStatus.UNRESOLVED, "EXACT_MATH_OPERANDS_UNBOUND", operation, evidence=evidence)
        compatible, values, unit = _compatible(operands, operation)
        if not compatible:
            return _finish(ProofStatus.UNRESOLVED, "EXACT_MATH_UNIT_DIMENSION_MISMATCH", operation, evidence=evidence)
        result, inverse = _calculate(operation, values)
        if result is None:
            return _finish(ProofStatus.UNRESOLVED, "EXACT_MATH_OPERATION_UNDEFINED", operation, values, evidence=evidence, inverse=inverse)
        expected_answer = result
        if operation == "percentage_change":
            expected_answer = result
        allowed = {result, *values}
        observed = {item.value for item in answer_values}
        answer_dimensions = {item.dimension for item in answer_values if item.dimension}
        if unit and answer_dimensions and answer_dimensions != {operands[0].dimension}:
            return _finish(ProofStatus.DISPROVED, "EXACT_MATH_ANSWER_UNIT_CONTRADICTION", operation, values, result, unit, evidence, inverse)
        if unit and any(item.dimension for item in answer_values):
            observed = {item.base_value for item in answer_values}
        if operation == "percentage_change" and any(item.percent for item in answer_values):
            observed = {item.value for item in answer_values}
        status = ProofStatus.PROVED if expected_answer in observed and observed <= allowed else ProofStatus.DISPROVED
        reason = "EXACT_MATH_INVERSE_VERIFIED" if status is ProofStatus.PROVED else "EXACT_MATH_RESULT_CONTRADICTION"
        return _finish(status, reason, operation, values, result, unit, evidence, inverse)
