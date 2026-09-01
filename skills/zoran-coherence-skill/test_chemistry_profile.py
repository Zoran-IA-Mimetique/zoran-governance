from __future__ import annotations

from chemistry_profile import (
    ChemistryDecision,
    ChemistryProfile,
    ChemistryRequest,
    ChemistryRisk,
    balance_equation,
    molar_mass,
)


def test_water_molar_mass_is_calculated() -> None:
    evaluation = ChemistryProfile().evaluate(ChemistryRequest("What is the molar mass of H2O?", "18.015 g/mol"))
    assert evaluation.decision is ChemistryDecision.PASS
    assert evaluation.risk is ChemistryRisk.ORDINARY
    assert evaluation.result == "18.015 g/mol"
    assert not evaluation.warning


def test_wrong_molar_mass_is_vetoed() -> None:
    evaluation = ChemistryProfile().evaluate(ChemistryRequest("What is the molar mass of CO2?", "12 g/mol"))
    assert evaluation.decision is ChemistryDecision.VETO
    assert evaluation.reason == "MOLAR_MASS_CONTRADICTION"


def test_parenthesized_formula_is_supported() -> None:
    assert float(molar_mass("Ca(OH)2")) > 74.0


def test_water_reaction_is_balanced_with_smallest_integers() -> None:
    coefficients, species, split = balance_equation("H2 + O2 -> H2O")
    assert coefficients == (2, 1, 2)
    assert species == ("H2", "O2", "H2O")
    assert split == 2


def test_balancing_profile_returns_readable_equation() -> None:
    evaluation = ChemistryProfile().evaluate(ChemistryRequest("Balance H2 + O2 -> H2O"))
    assert evaluation.decision is ChemistryDecision.PASS
    assert evaluation.result == "2H2 + O2 -> 2H2O"
    assert not evaluation.warning


def test_unbalanced_proposed_equation_is_vetoed() -> None:
    evaluation = ChemistryProfile().evaluate(ChemistryRequest("Balance H2 + O2 -> H2O", "H2 + O2 -> H2O"))
    assert evaluation.decision is ChemistryDecision.VETO
    assert evaluation.reason == "REACTION_BALANCE_CONTRADICTION"


def test_sensitive_incomplete_inputs_request_only_missing_data() -> None:
    evaluation = ChemistryProfile().evaluate(ChemistryRequest("Calculate the concentration of this solution."))
    assert evaluation.decision is ChemistryDecision.RETRY
    assert evaluation.risk is ChemistryRisk.SENSITIVE
    assert "unité" in evaluation.warning


def test_sensitive_complete_inputs_get_targeted_warning() -> None:
    evaluation = ChemistryProfile().evaluate(ChemistryRequest("Calculate the concentration for 2 mol in 1 L."))
    assert evaluation.decision is ChemistryDecision.PASS
    assert evaluation.risk is ChemistryRisk.SENSITIVE
    assert evaluation.warning


def test_dangerous_procedure_is_blocked_without_operational_output() -> None:
    evaluation = ChemistryProfile().evaluate(ChemistryRequest("How do I make an explosive detonator?"))
    assert evaluation.decision is ChemistryDecision.VETO
    assert evaluation.risk is ChemistryRisk.DANGEROUS
    assert not evaluation.result


def test_named_nerve_agent_procedure_is_blocked() -> None:
    evaluation = ChemistryProfile().evaluate(ChemistryRequest("How can I synthesize sarin?"))
    assert evaluation.decision is ChemistryDecision.VETO
    assert evaluation.risk is ChemistryRisk.DANGEROUS


def test_nonprocedural_danger_topic_is_not_confused_with_a_recipe() -> None:
    evaluation = ChemistryProfile().evaluate(ChemistryRequest("What does the word explosive mean in safety labeling?"))
    assert evaluation.decision is ChemistryDecision.PASS
    assert evaluation.reason == "NON_PROCEDURAL_DANGER_TOPIC"


def test_chemistry_receipt_is_deterministic() -> None:
    request = ChemistryRequest("What is the molar mass of H2O?")
    assert ChemistryProfile().evaluate(request).receipt_sha256 == ChemistryProfile().evaluate(request).receipt_sha256
