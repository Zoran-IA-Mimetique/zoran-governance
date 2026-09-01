from __future__ import annotations

"""Bounded chemistry calculations with targeted, non-procedural safety routing."""

import hashlib
import json
import math
import re
from dataclasses import dataclass
from enum import Enum
from fractions import Fraction


COMPONENT_ID = "zoran.chemistry-profile"
VERSION = "22.3.0"


# Conventional abridged atomic weights.  Values are decimal constants for
# deterministic educational calculations, not metrology certificates.
_ATOMIC_WEIGHTS = {
    "H": Fraction("1.008"), "He": Fraction("4.002602"), "Li": Fraction("6.94"),
    "Be": Fraction("9.0121831"), "B": Fraction("10.81"), "C": Fraction("12.011"),
    "N": Fraction("14.007"), "O": Fraction("15.999"), "F": Fraction("18.998403163"),
    "Ne": Fraction("20.1797"), "Na": Fraction("22.98976928"), "Mg": Fraction("24.305"),
    "Al": Fraction("26.9815385"), "Si": Fraction("28.085"), "P": Fraction("30.973761998"),
    "S": Fraction("32.06"), "Cl": Fraction("35.45"), "Ar": Fraction("39.948"),
    "K": Fraction("39.0983"), "Ca": Fraction("40.078"), "Sc": Fraction("44.955908"),
    "Ti": Fraction("47.867"), "V": Fraction("50.9415"), "Cr": Fraction("51.9961"),
    "Mn": Fraction("54.938044"), "Fe": Fraction("55.845"), "Co": Fraction("58.933194"),
    "Ni": Fraction("58.6934"), "Cu": Fraction("63.546"), "Zn": Fraction("65.38"),
    "Ga": Fraction("69.723"), "Ge": Fraction("72.630"), "As": Fraction("74.921595"),
    "Se": Fraction("78.971"), "Br": Fraction("79.904"), "Kr": Fraction("83.798"),
    "Rb": Fraction("85.4678"), "Sr": Fraction("87.62"), "Ag": Fraction("107.8682"),
    "Cd": Fraction("112.414"), "I": Fraction("126.90447"), "Ba": Fraction("137.327"),
    "Pt": Fraction("195.084"), "Au": Fraction("196.966569"), "Hg": Fraction("200.592"),
    "Pb": Fraction("207.2"), "U": Fraction("238.02891"),
}

_PROCEDURAL_CUES = frozenset({
    "build", "cook", "create", "extract", "fabricate", "make", "manufacture", "prepare",
    "purify", "scale", "synthesise", "synthesize",
    "fabriquer", "faire", "preparer", "produire", "purifier", "synthetiser",
})
_DANGER_CUES = frozenset({
    "agent neurotoxique", "bioweapon", "chemical weapon", "detonator", "explosive",
    "explosif", "nerve agent", "poison", "poison gas", "ricin", "sarin", "toxique",
    "toxic", "toxic gas", "tnt", "vx", "weapon", "arme chimique",
})
_SENSITIVE_CUES = frozenset({
    "concentration", "dose", "dosage", "pressure", "pression", "scale", "temperature",
    "volume", "quantite", "quantity",
})


class ChemistryDecision(str, Enum):
    PASS = "PASS"
    RETRY = "RETRY"
    VETO = "VETO"


class ChemistryRisk(str, Enum):
    ORDINARY = "ORDINARY"
    SENSITIVE = "SENSITIVE"
    DANGEROUS = "DANGEROUS"


@dataclass(frozen=True)
class ChemistryRequest:
    question: str
    answer: str = ""
    context: str = ""


@dataclass(frozen=True)
class ChemistryEvaluation:
    decision: ChemistryDecision
    risk: ChemistryRisk
    reason: str
    result: str
    warning: str
    calculation_trace: tuple[str, ...]
    receipt_sha256: str


def _norm(text: str) -> str:
    import unicodedata
    folded = unicodedata.normalize("NFKD", text.casefold())
    folded = "".join(char for char in folded if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9]+", folded))


def _formula_counts(formula: str) -> dict[str, int]:
    cleaned = re.sub(r"\((?:aq|s|l|g)\)$", "", formula.strip(), flags=re.I)
    if not cleaned or not re.fullmatch(r"[A-Z][A-Za-z0-9()]*", cleaned):
        raise ValueError("FORMULA_SYNTAX_UNSUPPORTED")
    index = 0

    def parse(stop: str = "") -> dict[str, int]:
        nonlocal index
        counts: dict[str, int] = {}
        while index < len(cleaned):
            if stop and cleaned[index] == stop:
                index += 1
                return counts
            if cleaned[index] == "(":
                index += 1
                group = parse(")")
                multiplier = parse_number()
                for element, count in group.items():
                    counts[element] = counts.get(element, 0) + count * multiplier
                continue
            match = re.match(r"[A-Z][a-z]?", cleaned[index:])
            if not match:
                raise ValueError("FORMULA_SYNTAX_UNSUPPORTED")
            element = match.group(0)
            if element not in _ATOMIC_WEIGHTS:
                raise ValueError("ELEMENT_UNSUPPORTED")
            index += len(element)
            counts[element] = counts.get(element, 0) + parse_number()
        if stop:
            raise ValueError("FORMULA_PARENTHESIS_UNCLOSED")
        return counts

    def parse_number() -> int:
        nonlocal index
        match = re.match(r"\d+", cleaned[index:])
        if not match:
            return 1
        index += len(match.group(0))
        value = int(match.group(0))
        if value <= 0:
            raise ValueError("FORMULA_MULTIPLIER_INVALID")
        return value

    result = parse()
    if index != len(cleaned):
        raise ValueError("FORMULA_TRAILING_CONTENT")
    return result


def molar_mass(formula: str) -> Fraction:
    return sum((_ATOMIC_WEIGHTS[element] * count for element, count in _formula_counts(formula).items()), Fraction(0))


def _rref_null_vector(matrix: list[list[Fraction]]) -> tuple[int, ...]:
    if not matrix or not matrix[0]:
        raise ValueError("EMPTY_STOICHIOMETRY")
    rows, cols = len(matrix), len(matrix[0])
    pivot_columns: list[int] = []
    pivot_row = 0
    for column in range(cols):
        row = next((candidate for candidate in range(pivot_row, rows) if matrix[candidate][column]), None)
        if row is None:
            continue
        matrix[pivot_row], matrix[row] = matrix[row], matrix[pivot_row]
        divisor = matrix[pivot_row][column]
        matrix[pivot_row] = [value / divisor for value in matrix[pivot_row]]
        for other in range(rows):
            if other == pivot_row or not matrix[other][column]:
                continue
            factor = matrix[other][column]
            matrix[other] = [left - factor * right for left, right in zip(matrix[other], matrix[pivot_row], strict=True)]
        pivot_columns.append(column)
        pivot_row += 1
        if pivot_row == rows:
            break
    free = [column for column in range(cols) if column not in pivot_columns]
    if len(free) != 1:
        raise ValueError("STOICHIOMETRY_NOT_UNIQUE")
    vector = [Fraction(0) for _ in range(cols)]
    vector[free[0]] = Fraction(1)
    for row, column in reversed(list(enumerate(pivot_columns))):
        vector[column] = -sum(matrix[row][j] * vector[j] for j in range(column + 1, cols))
    denominator_lcm = math.lcm(*(value.denominator for value in vector))
    integers = [int(value * denominator_lcm) for value in vector]
    if all(value <= 0 for value in integers):
        integers = [-value for value in integers]
    if any(value <= 0 for value in integers):
        raise ValueError("STOICHIOMETRY_NONPOSITIVE")
    divisor = math.gcd(*integers)
    return tuple(value // divisor for value in integers)


def balance_equation(equation: str) -> tuple[tuple[int, ...], tuple[str, ...], int]:
    if "->" in equation:
        left, right = equation.split("->", 1)
    elif "=" in equation:
        left, right = equation.split("=", 1)
    else:
        raise ValueError("REACTION_ARROW_MISSING")
    reactants = tuple(part.strip() for part in left.split("+") if part.strip())
    products = tuple(part.strip() for part in right.split("+") if part.strip())
    if not reactants or not products or len(reactants) + len(products) > 12:
        raise ValueError("REACTION_SCOPE_UNSUPPORTED")
    species = reactants + products
    counts = tuple(_formula_counts(re.sub(r"^\d+\s*", "", item)) for item in species)
    elements = sorted({element for item in counts for element in item})
    matrix = [
        [Fraction(item.get(element, 0) * (1 if index < len(reactants) else -1)) for index, item in enumerate(counts)]
        for element in elements
    ]
    coefficients = _rref_null_vector(matrix)
    normalized_species = tuple(re.sub(r"^\d+\s*", "", item) for item in species)
    return coefficients, normalized_species, len(reactants)


def _format_equation(coefficients: tuple[int, ...], species: tuple[str, ...], split: int) -> str:
    def side(start: int, end: int) -> str:
        return " + ".join(("" if coefficients[index] == 1 else str(coefficients[index])) + species[index] for index in range(start, end))
    return f"{side(0, split)} -> {side(split, len(species))}"


def _finish(decision: ChemistryDecision, risk: ChemistryRisk, reason: str, result: str = "", warning: str = "", trace: tuple[str, ...] = ()) -> ChemistryEvaluation:
    payload = {
        "component": COMPONENT_ID, "version": VERSION, "decision": decision.value,
        "risk": risk.value, "reason": reason, "result": result,
        "warning": warning, "trace": list(trace),
    }
    receipt = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return ChemistryEvaluation(decision, risk, reason, result, warning, trace, receipt)


class ChemistryProfile:
    """Route ordinary calculations, incomplete sensitive work and dangerous procedures."""

    def evaluate(self, request: ChemistryRequest | None) -> ChemistryEvaluation:
        if not isinstance(request, ChemistryRequest) or not isinstance(request.question, str) or not request.question.strip():
            return _finish(ChemistryDecision.RETRY, ChemistryRisk.ORDINARY, "CHEMISTRY_REQUEST_INVALID")
        normalized = _norm(request.question)
        procedural = any(re.search(rf"\b{re.escape(cue)}\b", normalized) for cue in _PROCEDURAL_CUES)
        dangerous = any(cue in normalized for cue in _DANGER_CUES)
        if procedural and dangerous:
            return _finish(
                ChemistryDecision.VETO, ChemistryRisk.DANGEROUS, "DANGEROUS_PROCEDURE_BLOCKED", "",
                "Je peux aider à évaluer le risque, sécuriser la situation ou orienter vers un professionnel, mais pas fournir cette procédure.",
            )

        mass_match = re.search(r"(?:molar mass|masse molaire)(?:\s+(?:of|de|du))?\s+([A-Z][A-Za-z0-9()]*)", request.question)
        if mass_match:
            formula = mass_match.group(1)
            try:
                mass = molar_mass(formula)
            except ValueError as exc:
                return _finish(ChemistryDecision.RETRY, ChemistryRisk.ORDINARY, str(exc))
            result = f"{float(mass):.6f}".rstrip("0").rstrip(".") + " g/mol"
            trace = tuple(f"{element}:{count}" for element, count in sorted(_formula_counts(formula).items()))
            if request.answer:
                observed_match = re.search(r"[-+]?\d+(?:[.,]\d+)?", request.answer)
                if not observed_match:
                    return _finish(ChemistryDecision.RETRY, ChemistryRisk.ORDINARY, "MOLAR_MASS_ANSWER_MISSING", result, trace=trace)
                observed = Fraction(observed_match.group(0).replace(",", "."))
                if abs(observed - mass) > Fraction(1, 200):
                    return _finish(ChemistryDecision.VETO, ChemistryRisk.ORDINARY, "MOLAR_MASS_CONTRADICTION", result, trace=trace)
            return _finish(ChemistryDecision.PASS, ChemistryRisk.ORDINARY, "MOLAR_MASS_CALCULATED", result, trace=trace)

        equation_match = re.search(r"([A-Z][A-Za-z0-9()]*\s*(?:\+\s*[A-Z][A-Za-z0-9()]*\s*)+(?:->|=)\s*[A-Z][A-Za-z0-9()]*(?:\s*\+\s*[A-Z][A-Za-z0-9()]*)*)", request.question)
        if equation_match:
            try:
                coefficients, species, split = balance_equation(equation_match.group(1))
            except ValueError as exc:
                return _finish(ChemistryDecision.RETRY, ChemistryRisk.ORDINARY, str(exc))
            result = _format_equation(coefficients, species, split)
            if request.answer:
                normalized_result = re.sub(r"\s+", "", result).replace("=", "->")
                normalized_answer = re.sub(r"\s+", "", request.answer).replace("=", "->")
                if normalized_result not in normalized_answer:
                    return _finish(
                        ChemistryDecision.VETO, ChemistryRisk.ORDINARY,
                        "REACTION_BALANCE_CONTRADICTION", result,
                        trace=("coefficients=" + ",".join(map(str, coefficients)),),
                    )
            return _finish(ChemistryDecision.PASS, ChemistryRisk.ORDINARY, "REACTION_BALANCED", result, trace=("coefficients=" + ",".join(map(str, coefficients)),))

        sensitive = any(re.search(rf"\b{re.escape(cue)}\b", normalized) for cue in _SENSITIVE_CUES)
        if sensitive:
            complete = bool(re.search(r"\d", request.question + " " + request.context)) and bool(re.search(r"\b(?:g|kg|mg|ml|l|mol|molar|c|k|pa|bar|atm)\b", normalized))
            if not complete:
                return _finish(ChemistryDecision.RETRY, ChemistryRisk.SENSITIVE, "SENSITIVE_INPUTS_INCOMPLETE", warning="Il manque une valeur ou une unité nécessaire au calcul.")
            return _finish(ChemistryDecision.PASS, ChemistryRisk.SENSITIVE, "SENSITIVE_INPUTS_PRESENT", warning="Calcul théorique seulement : vérifie les conditions réelles, la compatibilité des produits et les consignes du laboratoire.")

        if dangerous:
            return _finish(ChemistryDecision.PASS, ChemistryRisk.ORDINARY, "NON_PROCEDURAL_DANGER_TOPIC", warning="Sujet dangereux détecté : réponse limitée aux faits généraux et à la prévention.")
        return _finish(ChemistryDecision.RETRY, ChemistryRisk.ORDINARY, "CHEMISTRY_OPERATION_NOT_RECOGNISED")
