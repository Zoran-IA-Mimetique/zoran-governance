from __future__ import annotations

from exact_math_engine import ExactMathEngine, ExactMathRequest
from structural_reasoning_gate import ProofStatus


def evaluate(context: str, question: str, answer: str):
    return ExactMathEngine().evaluate(ExactMathRequest(context, question, answer))


def test_households_minus_families_is_bound_to_named_operands() -> None:
    proof = evaluate(
        "The city counted 18,878 households and 13,629 families.",
        "How many more households are there than families?",
        "5,249",
    )
    assert proof.status is ProofStatus.PROVED
    assert proof.exact_result == "5249"
    assert proof.inverse_trace == ("13629+5249=18878",)


def test_french_named_difference_is_exact() -> None:
    proof = evaluate(
        "La commune compte 18 878 ménages et 13 629 familles.",
        "Combien y a-t-il de ménages de plus que de familles ?",
        "5 249",
    )
    assert proof.status is ProofStatus.PROVED


def test_wrong_difference_is_disproved() -> None:
    proof = evaluate(
        "The city counted 18,878 households and 13,629 families.",
        "How many more households are there than families?",
        "5,248",
    )
    assert proof.status is ProofStatus.DISPROVED


def test_duplicate_same_scalar_does_not_create_a_second_answer() -> None:
    proof = evaluate(
        "The city counted 18,878 households and 13,629 families.",
        "How many more households are there than families?",
        "5,249. Therefore the difference is 5,249.",
    )
    assert proof.status is ProofStatus.PROVED


def test_fraction_sum_stays_exact() -> None:
    proof = evaluate("Use the values in the question.", "What is 1/3 plus 1/6 in total?", "1/2")
    assert proof.status is ProofStatus.PROVED
    assert proof.exact_result == "0.5"


def test_percentage_is_verified_as_a_ratio() -> None:
    proof = evaluate(
        "Revenue was 100 in 2024 and 125 in 2025.",
        "What was the percentage increase?",
        "25%",
    )
    assert proof.status is ProofStatus.PROVED
    assert proof.exact_result == "0.25"


def test_compatible_units_are_converted_before_addition() -> None:
    proof = evaluate("The first length is 1 m and the second is 50 cm.", "What is the sum in meters?", "1.5 m")
    assert proof.status is ProofStatus.PROVED
    assert proof.unit == "m"


def test_incompatible_units_abstain() -> None:
    proof = evaluate("The inputs are 2 liters and 3 kilograms.", "What is the sum in total?", "5")
    assert proof.status is ProofStatus.UNRESOLVED
    assert proof.reason == "EXACT_MATH_UNIT_DIMENSION_MISMATCH"


def test_ambiguous_operand_set_abstains() -> None:
    proof = evaluate("The page lists 1, 2, 3, 4, 5, 6, 7, 8 and 9.", "What is the difference?", "1")
    assert proof.status is ProofStatus.UNRESOLVED


def test_unknown_question_family_is_not_applicable() -> None:
    proof = evaluate("Maya designed the bridge.", "Who designed it?", "Maya")
    assert proof.status is ProofStatus.NOT_APPLICABLE


def test_receipt_is_deterministic() -> None:
    request = ExactMathRequest("There are 9 cats and 4 dogs.", "How many more cats than dogs?", "5")
    assert ExactMathEngine().evaluate(request).receipt_sha256 == ExactMathEngine().evaluate(request).receipt_sha256


def test_linear_equation_is_solved_and_substituted() -> None:
    proof = evaluate("Use the equation in the question.", "Solve the equation 2x + 3 = 11.", "x = 4")
    assert proof.status is ProofStatus.PROVED
    assert proof.exact_result == "4"
    assert proof.unit == "x"


def test_wrong_linear_solution_is_disproved() -> None:
    proof = evaluate("Use the equation in the question.", "Solve the equation 2x + 3 = 11.", "x = 5")
    assert proof.status is ProofStatus.DISPROVED


def test_nonlinear_equation_abstains() -> None:
    proof = evaluate("Use the equation in the question.", "Solve the equation x*x = 4.", "x = 2")
    assert proof.status is ProofStatus.UNRESOLVED
