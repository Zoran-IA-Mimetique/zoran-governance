from __future__ import annotations

from dataclasses import fields

from structural_reasoning_gate import ProofStatus, StructuralProofRequest, StructuralReasoningGate


def evaluate(context: str, question: str, answer: str):
    return StructuralReasoningGate().evaluate(StructuralProofRequest(context, question, answer))


def test_zmos_structural_request_has_no_external_dataset_or_task_channel():
    assert tuple(field.name for field in fields(StructuralProofRequest)) == ("context", "question", "answer")


def test_financial_table_binds_label_year_and_value():
    context = """December 31,
2022
2021
Accounts payable
$
79,600
$
78,664
Total current liabilities
155,393
142,266
"""
    result = evaluate(context, "What were accounts payable at FY2022 in USD millions?", "$79,600")
    assert result.status is ProofStatus.PROVED
    assert result.reason == "TABLE_CELL_BOUND"
    assert "year=2022" in result.calculation_trace


def test_financial_table_rejects_number_from_wrong_row():
    context = """December 31,
2022
2021
Accounts payable
79,600
78,664
Total current liabilities
155,393
142,266
"""
    result = evaluate(context, "What were accounts payable at FY2022 in USD millions?", "$155,393")
    assert result.status is ProofStatus.DISPROVED
    assert result.reason == "TABLE_CELL_CONTRADICTION"


def test_financial_table_rejects_number_from_wrong_year():
    context = """December 31,
2022
2021
Accounts payable
79,600
78,664
"""
    result = evaluate(context, "What were accounts payable at FY2022 in USD millions?", "$78,664")
    assert result.status is ProofStatus.DISPROVED


def test_financial_alias_and_split_date_headers_bind_without_footnote_numbers():
    context = """September 29,
2018
September 30,
2017
Property, plant and equipment, net of allowances of $111 and $87, respectively
41,304
33,783
"""
    result = evaluate(context, "What was net PPNE at FY2018 in USD millions?", "$41304.00")
    assert result.status is ProofStatus.PROVED
    assert "value=41304" in result.calculation_trace


def test_uncommaed_decimal_is_one_number_not_two_partial_numbers():
    context = """December 31, 2016 and 2015
Accounts receivable, net
2,166
2,302
"""
    result = evaluate(context, "What was net AR at FY2016 in USD millions?", "$2166.00")
    assert result.status is ProofStatus.PROVED


def test_operating_margin_average_requires_a_complete_formula_trace():
    context = """Year ended December 31,
2018
2017
2016
Total net revenue
3,298,177
2,214,253
1,708,721
Operating loss
(36,614)
(54,206)
(170,453)
"""
    result = evaluate(context, "What was the three year average operating income margin from FY2016 to FY2018?", "-4.5%")
    assert result.status is ProofStatus.PROVED
    assert result.reason == "FINANCE_FORMULA_PROVED"
    assert result.calculation_trace[-1].startswith("average=")


def test_ebitda_margin_rejects_a_nearby_but_wrong_percentage():
    context = """Year ended May 31,
2016
Total revenues
37,047
Operating income
12,604
Cash flows from operating activities
Depreciation
871
Amortization of intangible assets
1,638
"""
    result = evaluate(context, "What is the FY2016 EBITDA margin using operating income and D&A?", "41.2%")
    assert result.status is ProofStatus.DISPROVED
    assert result.reason == "FINANCE_FORMULA_CONTRADICTION"


def test_percent_complement_is_reconstructed_not_merely_present():
    context = "Residents were 25.4% under 18, 16.4% from 18 to 24, 31.2% from 25 to 44, 16.7% from 45 to 64, and 10.2% at least 65."
    result = evaluate(context, "How many in percent weren't 18 to 24?", "83.6%")
    assert result.status is ProofStatus.PROVED
    assert result.calculation_trace == ("100-16.4=83.6",)


def test_percent_complement_rejects_invented_result():
    context = "Residents were 25.4% under 18, 16.4% from 18 to 24, 31.2% from 25 to 44, 16.7% from 45 to 64, and 10.2% at least 65."
    result = evaluate(context, "How many in percent weren't 18 to 24?", "84.6%")
    assert result.status is ProofStatus.DISPROVED


def test_percent_complement_requires_a_valid_partition():
    context = "The report mentions 16.4% from 18 to 24 and a separate 75% confidence threshold."
    result = evaluate(context, "How many in percent weren't 18 to 24?", "83.6%")
    assert result.status is ProofStatus.UNRESOLVED
    assert result.reason == "PERCENT_PARTITION_NOT_VALIDATED"


def test_labeled_sum_is_reconstructed_from_two_operands():
    context = "The county census recorded 10,477 households and 7,459 families."
    result = evaluate(context, "How many households and families were recorded in total?", "17,936")
    assert result.status is ProofStatus.PROVED
    assert result.reason == "ARITHMETIC_TRACE_PROVED"


def test_labeled_subtraction_rejects_a_wrong_result():
    context = "The School of Medicine received 1,764 applications and made only 39 offers."
    result = evaluate(context, "How many applicants did not receive an offer?", "1,700")
    assert result.status is ProofStatus.DISPROVED


def test_explicit_word_count_is_bound_to_the_questioned_event():
    context = "Smith caught a 74-yard touchdown pass. Before the first quarter ended, Smith caught three touchdown passes. It was the 12th such game in league history."
    result = evaluate(context, "How many touchdown catches did Smith make in the first quarter?", "3")
    assert result.status is ProofStatus.PROVED
    assert result.calculation_trace == ("explicit_count=3",)


def test_nearby_count_with_wrong_relation_cannot_become_a_proof():
    context = "Crabtree caught his first of three touchdown scores. Oakland ultimately won the game by two points."
    result = evaluate(context, "How many points did Oakland win by?", "3")
    assert result.status is ProofStatus.UNRESOLVED
    assert result.reason == "ARITHMETIC_TRACE_UNRESOLVED"


def test_financial_cell_binding_precedes_generic_how_much_routing():
    context = """December 31,
2020
2019
Total current assets
19,378
17,095
"""
    result = evaluate(context, "How much total current assets were reported at FY2020 in USD millions?", "$19378.00")
    assert result.status is ProofStatus.PROVED
    assert result.family == "numeric_table"


def test_financial_table_converts_millions_to_billions_with_disclosed_scale():
    context = """Consolidated Balance Sheets ($ in millions)
January 30, 2016
January 31, 2015
Totalcurrentassets
9,886
11,472
"""
    result = evaluate(context, "How much total current assets were reported at FY2016? Answer in USD billions.", "$9.90")
    assert result.status is ProofStatus.PROVED
    assert "unit_scale=0.001" in result.calculation_trace


def test_financial_unit_conversion_rejects_a_nearby_thousand_value():
    context = """Consolidated Balance Sheets ($ in millions)
December 31, 2019
Total current assets
20,411
"""
    result = evaluate(context, "What were total current assets at FY2019 in USD thousands?", "$20412000.00")
    assert result.status is ProofStatus.DISPROVED


def test_conditional_repair_steps_are_not_internal_contradictions():
    context = "passage 1: Close the door and try the lock. If it does not lock, tighten the hinges."
    answer = "Close the door and try to lock it. If it does not lock, tighten the hinges."
    result = evaluate(context, "How should the lock be repaired?", answer)
    assert result.status is not ProofStatus.DISPROVED


def test_exact_internal_negation_conflict_is_rejected():
    context = "passage 1: FEHA covers housing discrimination."
    answer = "FEHA covers housing discrimination. FEHA does not cover housing discrimination. A claimant should read the statute."
    result = evaluate(context, "What does FEHA cover?", answer)
    assert result.status is ProofStatus.DISPROVED
    assert result.reason == "ANSWER_INTERNAL_CONTRADICTION"


def test_yes_no_polarity_accepts_explicit_negative_conclusion():
    context = "The treatment did not significantly increase residual activity. No adverse clinical outcome was observed."
    result = evaluate(context, "Does the treatment adversely affect residual activity and clinical outcomes?", "No. It does not adversely affect either outcome.")
    assert result.status is ProofStatus.PROVED
    assert result.reason == "POLARITY_AND_CLAIMS_ALIGNED"


def test_yes_no_polarity_rejects_opposite_answer():
    context = "The treatment did not significantly increase residual activity."
    result = evaluate(context, "Does the treatment increase residual activity?", "Yes. It increases residual activity.")
    assert result.status is ProofStatus.DISPROVED
    assert result.reason == "POLARITY_CONTRADICTION"


def test_yes_no_polarity_does_not_promote_uncertain_evidence():
    context = "The treatment may possibly affect residual activity, but the result is uncertain."
    result = evaluate(context, "Does the treatment affect residual activity?", "Yes.")
    assert result.status is ProofStatus.UNRESOLVED


def test_comparison_selects_the_larger_bound_value():
    context = "The census counted 55,893 Chinese residents and 5,289 residents from Australia."
    result = evaluate(context, "Were there more residents from China or Australia?", "China")
    assert result.status is ProofStatus.PROVED
    assert result.reason == "COMPARISON_PROVED"


def test_comparison_rejects_the_smaller_option():
    context = "The census counted 55,893 Chinese residents and 5,289 residents from Australia."
    result = evaluate(context, "Were there more residents from China or Australia?", "Australia")
    assert result.status is ProofStatus.DISPROVED


def test_winner_relation_rejects_the_defeated_team():
    context = "The Redskins avenged their loss by defeating the Dallas Cowboys after a final field goal."
    result = evaluate(context, "Which team won the game?", "Cowboys")
    assert result.status is ProofStatus.DISPROVED
    assert result.reason == "WINNER_RELATION_CONTRADICTION"


def test_winner_relation_accepts_the_winner():
    context = "The Redskins avenged their loss by defeating the Dallas Cowboys after a final field goal."
    result = evaluate(context, "Which team won the game?", "Redskins")
    assert result.status is ProofStatus.PROVED


def test_long_answer_requires_local_evidence_for_each_atomic_claim():
    context = "passage 1: Tighten the hinge screws first. Enlarge the strike plate hole if the latch remains misaligned."
    answer = "1. Tighten the hinge screws first. 2. Enlarge the strike plate hole if the latch remains misaligned. 3. Paint the lock blue."
    result = evaluate(context, "How should the latch be repaired?", answer)
    assert result.status is ProofStatus.UNRESOLVED
    assert result.reason == "CLAIM_EVIDENCE_UNRESOLVED"


def test_long_answer_passes_only_when_each_atomic_claim_is_supported():
    context = "passage 1: Tighten the hinge screws first. Enlarge the strike plate hole if the latch remains misaligned. Move the strike plate only after checking alignment."
    answer = "1. Tighten the hinge screws first. 2. Enlarge the strike plate hole if the latch remains misaligned. 3. Move the strike plate only after checking alignment."
    result = evaluate(context, "How should the latch be repaired?", answer)
    assert result.status is ProofStatus.PROVED
    assert result.reason == "ALL_ATOMIC_CLAIMS_PROVED"


def test_plain_non_structural_answer_is_not_forced_into_a_family():
    result = evaluate("The Moon is a rocky satellite.", "What is the Moon?", "A rocky satellite.")
    assert result.status is ProofStatus.NOT_APPLICABLE


def test_structural_receipt_replays_exactly():
    request = StructuralProofRequest(
        "The treatment did not increase risk.",
        "Does the treatment increase risk?",
        "No.",
    )
    gate = StructuralReasoningGate()
    assert gate.evaluate(request) == gate.evaluate(request)
    assert len(gate.evaluate(request).receipt_sha256) == 64
