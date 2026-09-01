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
    context = """(In thousands)
Year ended December 31,
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


def test_working_capital_ratio_uses_two_year_bound_rows_not_one_table_cell():
    context = """December 31,
2019
2018
Total current assets
23,485
20,289
Total current liabilities
23,237
19,926
"""
    result = evaluate(context, "What is the FY2019 working capital ratio defined as total current assets divided by total current liabilities?", "1.01")
    assert result.status is ProofStatus.PROVED
    assert result.family == "finance_formula"


def test_net_working_capital_subtracts_bound_current_rows():
    context = """December 31,
2018
2017
Total current assets
7,126
7,744
Total current liabilities
4,454
3,559
"""
    result = evaluate(context, "What is FY2018 net working capital in USD millions?", "$2,672.00")
    assert result.status is ProofStatus.PROVED
    assert result.calculation_trace == ("(7126-4454)*1=2672",)


def test_operating_income_growth_binds_old_and_new_years():
    context = """Years ended
2017
2016
Operating income
61,344
60,024
"""
    result = evaluate(context, "What is the FY2016 to FY2017 operating income growth rate in percent?", "2.2%")
    assert result.status is ProofStatus.PROVED
    assert result.calculation_trace == ("(61344-60024)/abs(60024)*100=2.19912035186",)


def test_direct_financial_amount_rejects_unrequested_same_unit_rounding():
    context = """May 29,
2022
2021
Accounts payable
3,982.3
3,653.5
"""
    result = evaluate(context, "What was FY2022 accounts payable in USD millions?", "$3,982.00")
    assert result.status is ProofStatus.DISPROVED


def test_direct_financial_amount_allows_whole_rounding_after_unit_conversion():
    context = """(In thousands)
Year ended December 31,
2021
2020
Depreciation and amortization
134,757
84,212
"""
    result = evaluate(context, "What was FY2021 depreciation and amortization in USD millions?", "$135.00")
    assert result.status is ProofStatus.PROVED


def test_revenue_growth_binds_revenue_instead_of_operating_income():
    context = """Fiscal Years Ended
2019
2018
Revenue
42,879
42,151
Operating income
1,900
1,843
"""
    result = evaluate(context, "What is the year-over-year change in revenue from FY2018 to FY2019 in percent?", "2.1%")
    assert result.status is ProofStatus.DISPROVED
    assert result.calculation_trace == ("(42879-42151)/abs(42151)*100=1.72712391165",)


def test_ebitda_less_capex_closes_all_three_operands():
    context = """(In millions)
Fiscal Years Ended
2020
2019
Revenue
43,638
42,879
Operating income
2,009
1,900
Depreciation and amortization
812
770
Additions to property and equipment
(743)
(819)
"""
    result = evaluate(context, "What is FY2020 unadjusted EBITDA less capital expenditures in USD billions?", "$2.15")
    assert result.status is ProofStatus.DISPROVED
    assert result.calculation_trace == ("(2009+abs(812)-abs(-743))*0.001=2.078",)


def test_prose_parenthetical_percentages_bind_to_the_following_category():
    context = "The top ancestries were Italian (13.6%), Irish (12.1%), Puerto Rican (10.1%), and German (8.7%)."
    result = evaluate(context, "Were there more people of self-identified German or Irish ancestry?", "German")
    assert result.status is ProofStatus.DISPROVED
    assert result.calculation_trace == ("german=8.7", "irish ancestry=12.1", "selected=irish ancestry")


def test_comparison_answer_cannot_name_both_exclusive_options():
    context = "Tamil language (3.45%) and Marathi language (3.38%) were reported."
    result = evaluate(context, "Which language is spoken more: Tamil or Marathi?", "Marathi, Tamil, Marathi")
    assert result.status is ProofStatus.DISPROVED


def test_event_count_comparison_does_not_borrow_yardage():
    context = (
        "Crabtree scored on a 13-yard pass and again from 23 yards out. "
        "The three-touchdown game marked Crabtree's first. Carr finished with four touchdowns."
    )
    result = evaluate(context, "Who had more touchdowns Crabtree or Carr?", "Crabtree")
    assert result.status is ProofStatus.DISPROVED
    assert result.calculation_trace == ("crabtree=3", "carr=4", "selected=carr")


def test_activation_mechanism_binds_phosphorylation_not_nearby_deactivation():
    context = "Since MAPKs are activated by phosphorylation, dephosphorylation of MAPKs inactivates their activities."
    result = evaluate(context, "How is MAPK activated?", "dephosphorylation")
    assert result.status is ProofStatus.DISPROVED
    assert result.family == "exclusive_relation"


def test_gram_classification_binds_to_the_queried_bacterium():
    context = "LPS is a component of Gram-negative bacteria. Staphylococcus aureus (S. aureus) is a Gram-positive bacterium."
    result = evaluate(context, "What is Staph aureus?", "Gram negative bacteria")
    assert result.status is ProofStatus.DISPROVED
    assert "expected=gram positive" in result.calculation_trace


def test_recommendation_type_does_not_borrow_the_rejected_alternative():
    context = "The WHO recently recommended that countries using whole cell pertussis vaccines continue to do so because acellular vaccines are less effective."
    result = evaluate(context, "What type of pertussis vaccine has been recently recommended by the WHO?", "acellular pertussis vaccines")
    assert result.status is ProofStatus.DISPROVED


def test_regulated_element_is_bound_to_metabolism_relation():
    context = "Hepcidin plays a fundamental role in the regulation of Fe metabolism. Cu was measured separately."
    result = evaluate(context, "What element does hepcidin play a role in regulating during metabolism?", "Cu")
    assert result.status is ProofStatus.DISPROVED
    assert "expected=iron" in result.calculation_trace


def test_second_longest_field_goal_is_ranked_inside_first_half():
    context = (
        "In the first quarter, Tynes made a 42-yard field goal. "
        "In the second quarter, Wilkins made a 41-yard field goal. "
        "In the third quarter, Brown made a 55-yard field goal."
    )
    result = evaluate(context, "How many yards was the second longest field goal of the first half?", "42")
    assert result.status is ProofStatus.DISPROVED
    assert "expected_yards=41" in result.calculation_trace


def test_last_touchdown_uses_narrative_order_not_global_occurrence():
    context = (
        "In the first quarter, Favre completed an 18-yard touchdown pass. "
        "In the fourth quarter, Favre completed the game-winning 15-yard touchdown pass. "
        "With the win, the team improved to 4-4."
    )
    result = evaluate(context, "How long was the last touchdown?", "18-yard")
    assert result.status is ProofStatus.DISPROVED
    assert "expected_yards=15" in result.calculation_trace


def test_ranked_event_accepts_the_bound_entity_window():
    context = "In the first quarter, Brown made a 35-yard field goal. In the second quarter, Tynes made a 42-yard field goal."
    result = evaluate(context, "Who kicked the longest field goal?", "Tynes")
    assert result.status is ProofStatus.PROVED


def test_first_aid_safety_pin_is_not_misrouted_as_a_scoring_event():
    result = evaluate(
        "Safety pins can secure a bandana over a wound.",
        "What are safety pins in a first aid box used for?",
        "They secure a bandana over a wound.",
    )
    assert result.family == "none"


def test_first_half_scope_alone_is_not_an_event_rank():
    result = evaluate(
        "The Steelers scored a touchdown and two field goals in the first half.",
        "How many points did the Steelers get in the first half?",
        "13",
    )
    assert result.family != "ranked_event"


def test_longest_touchdown_pass_excludes_longer_runs():
    context = "Smith caught a 54-yard touchdown pass. Jones then made a 66-yard touchdown run."
    result = evaluate(context, "How many yards was the longest touchdown pass?", "54")
    assert result.status is ProofStatus.PROVED


def test_second_shortest_uses_the_second_ascending_event():
    context = "A made a 27-yard field goal. B made a 28-yard field goal. C made a 40-yard field goal."
    result = evaluate(context, "How many yards was the second shortest field goal?", "28")
    assert result.status is ProofStatus.PROVED


def test_fourth_longest_uses_the_requested_rank():
    context = (
        "A threw a 50-yard touchdown pass. B threw a 40-yard touchdown pass. "
        "C threw a 30-yard touchdown pass. Manning threw a 20-yard touchdown pass."
    )
    result = evaluate(context, "Which player threw the fourth longest TD pass?", "Manning")
    assert result.status is ProofStatus.PROVED


def test_first_touchdown_catcher_binds_receiver_not_later_receiver():
    context = (
        "Garrard got a 10-yard TD pass to WR Mike Sims-Walker. "
        "He later found TE Marcedes Lewis on a 42-yard TD pass."
    )
    result = evaluate(context, "Which player caught the first TD of the game?", "Marcedes Lewis")
    assert result.status is ProofStatus.DISPROVED
    assert result.reason == "RANKED_EVENT_ROLE_CONTRADICTION"


def test_touchdown_scorer_is_not_the_passer():
    context = "Ravens quarterback Joe Flacco completed a 14-yard touchdown pass to wide receiver Anquan Boldin."
    result = evaluate(context, "Which player scored the first touchdown?", "Joe Flacco")
    assert result.status is ProofStatus.DISPROVED
    assert "expected_entity=anquan boldin" in result.calculation_trace


def test_first_team_on_board_uses_scoring_clause_not_previous_opponent_name():
    context = "The Lions hosted the San Francisco 49ers. The Lions struck first when Jason Hanson kicked a 25-yard field goal."
    result = evaluate(context, "Which team got on the board first?", "49ers")
    assert result.status is ProofStatus.DISPROVED
    assert "expected_entity=lions" in result.calculation_trace


def test_question_local_percentage_rejects_a_percentage_borrowed_elsewhere():
    context = "The clinical attack rate was 20% in the 2009 H1N1 pandemic. A separate outbreak affected 25% of patients."
    result = evaluate(context, "What was the clinical attack rate in the 2009 H1N1 pandemic?", "25%")
    assert result.status is ProofStatus.DISPROVED
    assert result.reason == "LOCAL_PERCENT_RELATION_CONTRADICTION"


def test_question_local_percentage_does_not_override_an_exact_value():
    context = "SARS-CoV infected 8,000 people and approximately 10% died."
    result = evaluate(context, "What percentage of people infected with SARS-CoV died?", "10%")
    assert result.family != "local_scalar_relation"


def test_declaration_date_is_bound_to_the_correct_authority():
    context = (
        "On January 30, 2020, the World Health Organization declared COVID a Public Health Emergency of International Concern. "
        "On January 31, 2020, the US Department of Health and Human Services declared a public health emergency."
    )
    result = evaluate(context, "When did the WHO declare COVID to be a Public Health Emergency of International Concern?", "January 31, 2020")
    assert result.status is ProofStatus.DISPROVED
    assert "expected_date=2020-01-30" in result.calculation_trace


def test_missing_thrower_role_cannot_be_filled_by_the_receiver():
    context = "Detroit took the lead with a 36-yard touchdown catch by Calvin Johnson."
    result = evaluate(context, "Who threw the first touchdown pass of the game?", "Calvin Johnson")
    assert result.status is ProofStatus.UNRESOLVED
    assert result.reason == "RANKED_EVENT_ROLE_UNBOUND"


def test_scrambling_player_is_bound_as_touchdown_scorer():
    context = "Hasselbeck scrambled 20 yards to the endzone for a touchdown."
    result = evaluate(context, "Which player scored the last touchdown of the game?", "Hasselbeck")
    assert result.status is ProofStatus.PROVED


def test_getting_field_goal_binds_the_kicker():
    context = "Jaguars kicker Josh Scobee managed to get a 48-yard field goal."
    result = evaluate(context, "Who kicked the longest field goal?", "Josh Scobee")
    assert result.status is ProofStatus.PROVED


def test_touchdown_reception_binds_the_receiver():
    context = "The Colts scored a touchdown on another Austin Collie reception."
    result = evaluate(context, "Which player scored the last touchdown of the game?", "Austin Collie")
    assert result.status is ProofStatus.PROVED


def test_selected_event_role_does_not_leak_from_preceding_field_goal_clause():
    context = "Janikowski made a 49-yard field goal, followed by RB Michael Bush making a 4-yard TD run."
    result = evaluate(context, "Which player scored the last touchdown of the game?", "Michael Bush")
    assert result.status is ProofStatus.PROVED
    assert "expected_entity=rb michael bush" in result.calculation_trace


def test_only_fraction_contradicts_claim_of_frequent_presence():
    context = "SV40 could be confirmed in only 3 of the 30 Swedish malignant mesothelioma samples."
    result = evaluate(context, "Is presence of SV40 frequent in Swedish malignant mesotheliomas?", "Yes. SV40 is frequent.")
    assert result.status is ProofStatus.DISPROVED
    assert result.reason == "DIRECT_RESULT_POLARITY_CONTRADICTION"


def test_strongly_related_result_overrides_negative_answer():
    context = "Smoking was strongly related to fracture risk in women with diabetes."
    result = evaluate(context, "Is smoking a strong risk factor for fractures in women with diabetes?", "No. Smoking is not related.")
    assert result.status is ProofStatus.DISPROVED


def test_respectively_binds_value_to_the_correct_year():
    context = "The company paid $489 million and $466 million in dividends during 2022 and 2021, respectively."
    result = evaluate(context, "Has the company paid dividends in 2022?", "Yes, it paid $466 million in 2022.")
    assert result.status is ProofStatus.DISPROVED
    assert result.reason == "YEAR_VALUE_RELATION_CONTRADICTION"


def test_only_one_non_core_item_is_rejected_against_enumerated_list():
    context = "Non-core items: (1) amortization; (2) bankruptcy costs; (3) wildfire-related costs."
    result = evaluate(context, "Does PG&E report any non-core items?", "Yes, only wildfire-related costs are non-core items.")
    assert result.status is ProofStatus.DISPROVED
    assert result.reason == "EXCLUSIVITY_QUANTIFIER_CONTRADICTION"


def test_combined_da_row_is_not_double_counted_in_ebitda_margin():
    context = """(In millions)
Years ended
2016
2015
Total revenues
116,073
113,666
Operating income
3,672
3,624
Depreciation and amortization
1,255
1,127
"""
    result = evaluate(context, "What is the FY2015 to FY2016 change in unadjusted EBITDA margin?", "0.1%")
    assert result.status is ProofStatus.PROVED
    assert result.calculation_trace[-1].startswith("change=")


def test_change_in_operating_margin_uses_delta_not_terminal_margin():
    context = """Years ended
2021
2020
Total revenues
200
100
Operating income
30
10
"""
    result = evaluate(context, "What is the FY2020 to FY2021 change in operating income margin?", "5.0%")
    assert result.status is ProofStatus.PROVED
    assert result.calculation_trace[-1] == "change=15-10=5"


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


def test_multi_number_answer_is_accepted_only_as_a_closed_operand_result_trace():
    context = "The county census recorded 10,477 households and 7,459 families."
    result = evaluate(
        context,
        "How many households and families were recorded in total?",
        "10,477, 7,459, 17,936",
    )
    assert result.status is ProofStatus.PROVED
    assert result.calculation_trace == ("7459+10477=17936",)


def test_multi_number_trace_with_wrong_result_is_rejected():
    context = "The county census recorded 10,477 households and 7,459 families."
    result = evaluate(
        context,
        "How many households and families were recorded in total?",
        "10,477, 7,459, 17,900",
    )
    assert result.status is ProofStatus.DISPROVED


def test_partial_operand_trace_cannot_hide_a_missing_operand():
    context = "There were 290,000 Indians and 8,000 Indonesians."
    result = evaluate(
        context,
        "How many Indians and Indonesians were there in total?",
        "298,000, 8,000",
    )
    assert result.status is ProofStatus.DISPROVED


def test_enumerated_categories_are_summed_from_locally_bound_values():
    context = (
        "German has 13,444 speakers and Vietnamese is spoken by 11,330 people. "
        "French has 8,258 speakers, Korean 3,948, and Arabic 3,265."
    )
    result = evaluate(
        context,
        "How many people speak either German, Vietnamese, Korean, Arabic, or French?",
        "40,245",
    )
    assert result.status is ProofStatus.PROVED
    assert result.calculation_trace == ("3265+3948+8258+11330+13444=40245",)


def test_labeled_subtraction_rejects_a_wrong_result():
    context = "The School of Medicine received 1,764 applications and made only 39 offers."
    result = evaluate(context, "How many applicants did not receive an offer?", "1,700")
    assert result.status is ProofStatus.DISPROVED


def test_how_many_more_routes_to_arithmetic_not_entity_comparison():
    context = "The earlier census counted 18,878 residents, while the later census counted 13,629 residents."
    result = evaluate(context, "How many more residents were counted earlier than later?", "5,249")
    assert result.status is ProofStatus.PROVED
    assert result.family == "arithmetic"
    assert result.calculation_trace == ("abs(13629-18878)=5249",)


def test_difference_binds_each_queried_category_to_its_nearest_value():
    context = "There were approximately 93,000 Mormons in 253 congregations and 12,000 Muslims in 39 masjids."
    result = evaluate(context, "How many more Mormons than Muslims were there?", "81,000")
    assert result.status is ProofStatus.PROVED
    assert result.calculation_trace == ("abs(12000-93000)=81000",)


def test_difference_uses_question_qualifiers_to_select_repeated_units():
    context = (
        "The population included 5,841 people under age 18, 1,875 people age 18 to 24, "
        "5,025 people age 25 to 44, and 7,414 people age 45 to 64."
    )
    result = evaluate(context, "How many more people were under age 18 than age 18 to 24?", "3,966")
    assert result.status is ProofStatus.PROVED
    assert result.calculation_trace == ("abs(1875-5841)=3966",)


def test_numeric_answer_in_plain_prose_is_not_forced_into_table_frame():
    context = "The blockade began in 1923 and ended in 1924."
    result = evaluate(context, "When did the blockade begin?", "1923")
    assert result.status is ProofStatus.NOT_APPLICABLE
    assert result.family == "none"


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


def test_yes_no_ignores_only_a_bounded_future_research_tail():
    context = "The treatment did not improve survival in either group."
    result = evaluate(
        context,
        "Does the treatment improve survival?",
        "No. The treatment did not improve survival. Further randomized controlled trials are needed to confirm this finding.",
    )
    assert result.status is ProofStatus.PROVED


def test_yes_no_does_not_ignore_an_unsupported_clinical_recommendation():
    context = "The treatment did not improve survival in either group."
    result = evaluate(
        context,
        "Does the treatment improve survival?",
        "No. The treatment did not improve survival. Patients should stop treatment immediately.",
    )
    assert result.status is not ProofStatus.PROVED
    assert result.reason in {"ANSWER_CLAIM_NOT_ENTAILED", "ANSWER_CLAIM_POLARITY_CONTRADICTION"}


def test_yes_no_polarity_rejects_opposite_answer():
    context = "The treatment did not significantly increase residual activity."
    result = evaluate(context, "Does the treatment increase residual activity?", "Yes. It increases residual activity.")
    assert result.status is ProofStatus.DISPROVED
    assert result.reason == "POLARITY_CONTRADICTION"


def test_yes_no_polarity_does_not_promote_uncertain_evidence():
    context = "The treatment may possibly affect residual activity, but the result is uncertain."
    result = evaluate(context, "Does the treatment affect residual activity?", "Yes.")
    assert result.status is ProofStatus.UNRESOLVED


def test_yes_no_causal_clause_cannot_override_explicit_negated_mechanism():
    context = (
        "Simvastatin inhibited cytokine production. "
        "However, simvastatin did not enhance the expression of tristetraprolin."
    )
    result = evaluate(
        context,
        "Does simvastatin inhibit cytokine production?",
        "Yes. Simvastatin inhibits cytokine production by enhancing the expression of tristetraprolin.",
    )
    assert result.status is ProofStatus.DISPROVED
    assert result.reason == "ANSWER_CLAIM_POLARITY_CONTRADICTION"


def test_yes_no_role_swap_cannot_be_composed_from_two_sentences():
    context = (
        "Peplomycin induced apoptosis in Bel-7402. Cells were arrested in G2-phase. "
        "Almost all apoptosis occurred in G1-phase."
    )
    result = evaluate(
        context,
        "Does peplomycin induce G1-phase apoptosis involving G2-phase arrest?",
        "Yes. Peplomycin induced G2-phase apoptosis involving G1-phase arrest.",
    )
    assert result.status is ProofStatus.DISPROVED
    assert result.reason == "ANSWER_CLAIM_ROLE_CONTRADICTION"


def test_comparison_selects_the_larger_bound_value():
    context = "The census counted 55,893 Chinese residents and 5,289 residents from Australia."
    result = evaluate(context, "Were there more residents from China or Australia?", "China")
    assert result.status is ProofStatus.PROVED
    assert result.reason == "COMPARISON_PROVED"


def test_comparison_rejects_the_smaller_option():
    context = "The census counted 55,893 Chinese residents and 5,289 residents from Australia."
    result = evaluate(context, "Were there more residents from China or Australia?", "Australia")
    assert result.status is ProofStatus.DISPROVED


def test_lowercase_options_after_comma_are_bound_as_distinct_alternatives():
    context = "In 2016, 9.8% of residents carpooled and 2% used public transportation."
    result = evaluate(
        context,
        "Which did more residents use in 2016, carpool or public transportation?",
        "public transportation",
    )
    assert result.status is ProofStatus.DISPROVED
    assert result.family == "comparison"


def test_smaller_comparison_rejects_the_larger_census_group():
    result = StructuralReasoningGate().evaluate(StructuralProofRequest(
        context="22.5% were of German ancestry, 13.1% Irish, and 9.8% Italian.",
        question="Which group from the census is smaller: German or Irish?",
        answer="German",
    ))
    assert result.status is ProofStatus.DISPROVED
    assert result.reason == "COMPARISON_CONTRADICTION"


def test_larger_comparison_accepts_the_larger_language_group():
    result = StructuralReasoningGate().evaluate(StructuralProofRequest(
        context="The population reported 4.2% Urdu speakers and 7.6% Tamil speakers.",
        question="Which linguistic minority is larger, Urdu or Tamil?",
        answer="Tamil",
    ))
    assert result.status is ProofStatus.PROVED
    assert result.reason == "COMPARISON_PROVED"


def test_temporal_choice_rejects_later_timeline_event_for_first():
    result = StructuralReasoningGate().evaluate(StructuralProofRequest(
        context="1564: The city of Ryazan was burned. 1592: Suburbs of Moscow burned.",
        question="What was burned first: city of Ryazan or suburbs of Moscow?",
        answer="suburbs of Moscow",
    ))
    assert result.status is ProofStatus.DISPROVED
    assert result.reason == "TEMPORAL_CHOICE_CONTRADICTION"


def test_temporal_choice_accepts_later_dated_event_for_second():
    result = StructuralReasoningGate().evaluate(StructuralProofRequest(
        context="In 1611 De la Gardie captured Novgorod. A patriotic uprising followed in 1612.",
        question="What happened second: Gardie captured Novgorod or a patriotic uprising?",
        answer="a patriotic uprising",
    ))
    assert result.status is ProofStatus.PROVED
    assert result.reason == "TEMPORAL_CHOICE_PROVED"


def test_temporal_choice_does_not_borrow_a_date_from_another_sentence():
    result = StructuralReasoningGate().evaluate(StructuralProofRequest(
        context="The Treaty of Brétigny set the ransom. In 1364 the Battle of Cocherel occurred.",
        question="Which happened first, the Treaty of Brétigny or the Battle of Cocherel?",
        answer="the Treaty of Brétigny",
    ))
    assert result.family == "temporal_choice"
    assert result.status is ProofStatus.UNRESOLVED


def test_frequency_yes_answer_is_rejected_by_option_local_only_fraction():
    result = StructuralReasoningGate().evaluate(StructuralProofRequest(
        context="SV40 could be confirmed by sequencing in only 3 of the 30 samples.",
        question="Is presence of SV40 frequent in Swedish malignant mesotheliomas?",
        answer="Yes. SV40 is frequent in Swedish patients.",
    ))
    assert result.status is ProofStatus.DISPROVED
    assert result.reason == "DIRECT_RESULT_POLARITY_CONTRADICTION"


def test_vodcast_replacement_claim_is_rejected_by_direct_survey_result():
    result = StructuralReasoningGate().evaluate(StructuralProofRequest(
        context="A total of 191 students responded, with 79% indicating that VODcasts should not replace lectures.",
        question="Do prerecorded lecture VODcasts affect lecture attendance?",
        answer="Yes, students viewed VODcasts as a replacement for live lectures.",
    ))
    assert result.status is ProofStatus.DISPROVED
    assert result.reason == "DIRECT_RESULT_POLARITY_CONTRADICTION"


def test_scalar_count_question_rejects_conflicting_array_answers():
    result = StructuralReasoningGate().evaluate(StructuralProofRequest(
        context="The game included two 4-yard passing touchdowns.",
        question="How many 4-yard passing touchdowns were in the game?",
        answer="['2' '3']",
    ))
    assert result.status is ProofStatus.DISPROVED
    assert result.reason == "SCALAR_QUESTION_MULTIPLE_ANSWERS"


def test_factoid_relation_rejects_answer_borrowed_from_another_relation():
    result = evaluate(
        "The data used in the current study were collected from KEGG at https://www.kegg.jp/. UniProtKB was used for annotations.",
        "Where were the data collected for this study?",
        "UniProtKB",
    )
    assert result.status is ProofStatus.DISPROVED
    assert result.reason == "FACTOID_RELATION_CONTRADICTION"


def test_factoid_relation_binds_explicit_duration_and_count():
    duration = evaluate(
        "The denatured urea polyacrylamide gel was prepared and polymerized for 30 minutes.",
        "For how long was the denatured polyacrylamide gel polymerized?",
        "30 minutes",
    )
    count = evaluate(
        "Data were available for seven cases; five had no pre-existing conditions.",
        "How many cases had no pre-existing conditions?",
        "six",
    )
    assert duration.status is ProofStatus.PROVED
    assert count.status is ProofStatus.DISPROVED


def test_factoid_relation_preserves_signed_immune_phenotype():
    result = evaluate(
        "NK cells (CD3-/CD16+/CD56+), represent first-line cells for the clearing of virus-infected cells.",
        "What immune cells are primarily involved in eliminating virus-infected cells?",
        "NK cells (CD3+/CD16+/CD56+)",
    )
    assert result.status is ProofStatus.DISPROVED
    assert result.reason == "FACTOID_RELATION_CONTRADICTION"


def test_factoid_relation_binds_taxon_role_without_greek_symbol_loss():
    result = evaluate(
        "In the present study, we analyzed a complete genome and compared it with the genomes of related βCoVs.",
        "What is analyzed in this study?",
        "A complete genome compared with related αCoVs.",
    )
    assert result.status is ProofStatus.DISPROVED
    assert result.reason == "FACTOID_RELATION_CONTRADICTION"


def test_factoid_relation_rejects_positive_sufficiency_against_explicit_negation():
    result = evaluate(
        "NTCP itself is not sufficient to allow HBV infection.",
        "Is NTCP sufficient to allow HBV infection?",
        "sufficient",
    )
    assert result.status is ProofStatus.DISPROVED
    assert result.reason == "FACTOID_RELATION_CONTRADICTION"


def test_factoid_relation_distinguishes_direct_from_indirect_prefixes():
    result = evaluate(
        "Indirect transmission via fomites can also play a role.",
        "What can also play a role?",
        "direct transmission via fomites",
    )
    assert result.status is ProofStatus.DISPROVED


def test_factoid_relation_rejects_swapped_evolutionary_taxon_groups():
    result = evaluate(
        "Evolutionary analyses have shown that bats and rodents are the sources of most αCoVs and βCoVs, while avian species are the sources of most δCoVs and γCoVs.",
        "What do evolutionary analyses show?",
        "Bats and rodents are sources of αCoVs and γCoVs, while avian species are sources of δCoVs and βCoVs.",
    )
    assert result.status is ProofStatus.DISPROVED


def test_pertussis_vaccine_type_is_bound_to_country_usage_relation():
    result = evaluate(
        "Middle-and high-income countries use an acellular pertussis vaccine for the primary series.",
        "What kind of pertussis vaccine is used in middle and high income countries?",
        "whole cell",
    )
    assert result.status is ProofStatus.DISPROVED


def test_who_vaccine_recommendation_does_not_borrow_country_usage_type():
    context = (
        "Middle-and high-income countries use an acellular pertussis vaccine. "
        "The World Health Organization (WHO) recently recommended that countries using whole cell pertussis vaccines continue to do so."
    )
    correct = evaluate(context, "What type of pertussis vaccine has been recently recommended by the WHO?", "whole cell pertussis vaccines")
    wrong = evaluate(context, "What type of pertussis vaccine has been recently recommended by the WHO?", "acellular pertussis vaccines")
    assert correct.status is ProofStatus.PROVED
    assert wrong.status is ProofStatus.DISPROVED


def test_passage_corpus_rejects_acronym_number_role_swap():
    result = evaluate(
        "passage 1:The ADA applies to employers that have four to fifteen employees, whereas the FEHA affects more employers.",
        "What is the difference between FEHA and ADA?",
        "FEHA applies to employers with four to fifteen employees, while ADA applies to employers with twenty or more employees.",
    )
    assert result.status is ProofStatus.DISPROVED
    assert result.reason == "PASSAGE_ROLE_BINDING_CONTRADICTION"


def test_passage_corpus_accepts_same_acronym_range_in_words_or_digits():
    result = evaluate(
        "passage 1:One difference between FEHA and ADA is that ADA applies to private employers that have four to fifteen employees, whereas FEHA affects more employers.",
        "What is the difference between FEHA and ADA?",
        "FEHA affects more employers, while ADA applies to private employers with 4 to 15 employees.",
    )
    assert result.status is not ProofStatus.DISPROVED
    assert result.reason != "PASSAGE_ROLE_BINDING_CONTRADICTION"


def test_passage_corpus_rejects_unsupported_transfer_direction():
    result = evaluate(
        "passage 1:Transfer audiobooks from your computer to your Apple device using OverDrive.",
        "How do I sync an audiobook from iPhone to iTunes?",
        "Transfer the audiobook from OverDrive to your computer.",
    )
    assert result.status is ProofStatus.DISPROVED
    assert result.reason == "PASSAGE_DIRECTION_CONTRADICTION"


def test_passage_corpus_requires_direct_support_for_price_comparison():
    result = evaluate(
        "passage 1:Porterhouse has more tenderloin than T-bone and a corresponding price difference.\npassage 2:Sirloin is cut from the rear back portion.",
        "What is the difference between sirloin steak and porterhouse steak?",
        "Porterhouse has more tenderloin, which makes it more expensive than sirloin steak.",
    )
    assert result.status is ProofStatus.UNRESOLVED
    assert result.reason == "PASSAGE_COMPARISON_UNSUPPORTED"


def test_ranked_event_closes_misspelled_first_score_and_return_yardage_forms():
    first = evaluate(
        "The scoring began when Tyler blocked a punt that was recovered by Anthony Chickillo for a touchdown.",
        "Which player scored the fist points of the game?",
        "Tyler",
    )
    longest = evaluate(
        "Leon Washington had a 60-yard TD run. Brandon Flowers returned an interception 91 yards for a touchdown.",
        "Who scored on the longest touchdown play of the game?",
        "Leon Washington",
    )
    assert first.status is ProofStatus.DISPROVED
    assert longest.status is ProofStatus.DISPROVED


def test_comparison_binds_parenthetical_population_count_after_option():
    result = evaluate(
        "Macedonians had 338,358 inhabitants. Then came Turks (8,595).",
        "Which group is smaller: Macedonians or Turks?",
        "Macedonians",
    )
    assert result.status is ProofStatus.DISPROVED


def test_explicit_factoid_relations_close_author_opponent_and_shareholder_swaps():
    previous = evaluate(
        "Hoping to rebound from the road loss to the Chargers, the Rams hosted the Chiefs.",
        "Who did the Rams lose to in the previous game?",
        "Chiefs",
    )
    apology = evaluate(
        "The Apology, written by Philipp Melanchthon, was rejected by the Emperor.",
        "Whose Apology was rejected by Charles V?",
        "Martin Luther",
    )
    owner = evaluate(
        "Alan Sugar increased his stake and became the dominant partner with effective control of the club.",
        "Who was the dominant shareholder in 1992?",
        "Terry Venables",
    )
    assert previous.status is ProofStatus.DISPROVED
    assert apology.status is ProofStatus.DISPROVED
    assert owner.status is ProofStatus.DISPROVED


def test_arithmetic_uses_final_score_and_subject_touchdown_range():
    score = evaluate(
        "The final drive ended the game at 34-17.",
        "How many points did the Patriots win by?",
        "14",
    )
    touchdown_range = evaluate(
        "Jay Cutler threw a 39-yard TD pass. Later Cutler fired a 2-yard touchdown pass.",
        "How many yards longer was Jay Cutler's longest touchdown pass than his shortest?",
        "39",
    )
    assert score.status is ProofStatus.DISPROVED
    assert touchdown_range.status is ProofStatus.DISPROVED


def test_temporal_choice_uses_explicit_previous_and_current_relations():
    previous = evaluate(
        "The Battle of Vienna occurred in 1683. The empire had previously expanded in the wake of the Battle of Mohács.",
        "What battle started first: Battle of Vienna or Battle of Mohács?",
        "Battle of Vienna",
    )
    current = evaluate(
        "Screen versions include 1948's Bonnie Prince Charlie. The current Outlander TV series is another version.",
        "Which aired first, Bonnie Prince Charlie or the Outlander TV series?",
        "Outlander TV series",
    )
    assert previous.status is ProofStatus.DISPROVED
    assert current.status is ProofStatus.DISPROVED


def test_unbound_superlative_remains_fail_closed():
    result = evaluate(
        "Vincent caught a 10-yard pass and Malcolm caught a 12-yard pass.",
        "Who had the most receiving yards?",
        "Vincent",
    )
    assert result.status is ProofStatus.UNRESOLVED
    assert result.reason == "COMPARISON_OPTIONS_MISSING"


def test_explicit_superlative_relation_is_directly_entailed():
    context = "HMPV A2, the most frequently observed subgroup, was detected in the samples."
    result = evaluate(context, "What is the most common subgroup of HMPV?", "HMPV A2")
    assert result.status is ProofStatus.PROVED
    assert result.reason == "SUPERLATIVE_DIRECTLY_ENTAILED"


def test_explicit_superlative_can_use_a_local_relation_without_repeating_question_topic():
    context = "The report concerns COVID-19. Fever and cough constitute the most common presentations."
    result = evaluate(context, "What are the most common symptoms of COVID-19?", "Fever and cough")
    assert result.status is ProofStatus.PROVED
    assert result.reason == "SUPERLATIVE_DIRECTLY_ENTAILED"


def test_superlative_candidate_mentioned_without_relation_is_not_promoted():
    context = (
        "HMPV A2, the most frequently observed subgroup, was detected. "
        "The samples also contained HMPV B1 and HMPV B2."
    )
    result = evaluate(context, "What is the most common subgroup of HMPV?", "HMPV B1")
    assert result.status is ProofStatus.UNRESOLVED
    assert result.reason == "COMPARISON_OPTIONS_MISSING"


def test_second_ranked_candidate_after_followed_by_is_not_promoted_as_most_common():
    context = "The most prevalent viruses were rhinovirus, followed by parainfluenza viruses."
    result = evaluate(context, "What was the most common virus?", "parainfluenza viruses")
    assert result.status is ProofStatus.UNRESOLVED


def test_one_member_of_conjoined_superlative_subject_is_not_promoted_alone():
    context = "HCoV-OC43 and HCoV-229E were the most common strains in alternate seasons."
    result = evaluate(context, "What was the most common strain?", "HCoV-229E")
    assert result.status is ProofStatus.UNRESOLVED


def test_ordinal_respectively_binding_preserves_parallel_rank_and_group():
    context = "Colorectal cancer is the second and third most prevalent cancer among males and females, respectively."
    result = evaluate(
        context,
        "What is the third most prevalent cancer in females?",
        "colorectal cancer",
    )
    assert result.status is ProofStatus.PROVED


def test_superlative_numeric_detail_must_match_same_evidence():
    context = "Respiratory failure within 2 weeks was the most frequent manifestation."
    result = evaluate(context, "What was the most frequent manifestation?", "Respiratory failure within 1 week")
    assert result.status is ProofStatus.UNRESOLVED


def test_winner_relation_rejects_the_defeated_team():
    context = "The Redskins avenged their loss by defeating the Dallas Cowboys after a final field goal."
    result = evaluate(context, "Which team won the game?", "Cowboys")
    assert result.status is ProofStatus.DISPROVED
    assert result.reason == "WINNER_RELATION_CONTRADICTION"


def test_winner_relation_accepts_the_winner():
    context = "The Redskins avenged their loss by defeating the Dallas Cowboys after a final field goal."
    result = evaluate(context, "Which team won the game?", "Redskins")
    assert result.status is ProofStatus.PROVED


def test_safety_beneficiary_is_not_the_team_scored_on():
    context = (
        "The Lions hosted the San Francisco 49ers. "
        "San Francisco received a safety when Aldon Smith sacked Matthew Stafford in the end zone."
    )
    result = evaluate(context, "Which team had a safety scored on them?", "49ers")
    assert result.status is ProofStatus.DISPROVED
    assert result.reason == "SAFETY_BENEFICIARY_VICTIM_ROLE_CONTRADICTION"


def test_temporal_choice_with_one_unbound_date_is_not_accepted_lexically():
    context = "The Treaty created hostages. In 1364 the Battle of Cocherel occurred."
    result = evaluate(context, "Which happened first, the Treaty or the Battle of Cocherel?", "Battle of Cocherel")
    assert result.status is ProofStatus.UNRESOLVED
    assert result.reason == "TEMPORAL_YEAR_NOT_LOCALLY_BOUND"


def test_temporal_choice_allows_comma_before_or_and_binds_dated_before_current():
    context = "Screen versions include 1948's Bonnie Prince Charlie. The current Outlander TV series is also shown."
    result = evaluate(context, "Which aired first, Bonnie Prince Charlie, or the Outlander TV series?", "Outlander TV series")
    assert result.status is ProofStatus.DISPROVED
    assert result.reason == "TEMPORAL_CHOICE_CONTRADICTION"


def test_comparison_prefers_count_after_named_group_over_preceding_census_year():
    context = "According to the 2002 census, Macedonians were the largest group, with 338,358 inhabitants. Turks (8,595) followed."
    result = evaluate(context, "Which group is smaller: Macedonians or Turks?", "Macedonians")
    assert result.status is ProofStatus.DISPROVED
    assert "macedonians=338358" in result.calculation_trace


def test_listed_year_extremum_binds_year_to_count():
    context = "In 1981, 6,500 robberies were reported. By 2000, only 1,700 robberies were reported, and by 2010, only 1,100 robberies were reported."
    result = evaluate(context, "Which year had the fewest robberies?", "2000")
    assert result.status is ProofStatus.DISPROVED
    assert result.reason == "LISTED_EXTREMUM_CONTRADICTION"


def test_listed_state_extremum_binds_entity_to_count():
    context = "Maryland (69,400; 1.2%), Virginia (59,800; 0.7%), and Ohio (51,033; 0.5%)."
    result = evaluate(context, "Which state listed had the lowest number of residents?", "Maryland")
    assert result.status is ProofStatus.DISPROVED
    assert "selected=ohio" in result.calculation_trace


def test_listed_age_group_extremum_binds_percentage_to_group():
    context = "The population included 6.4% from 18 to 24, 22.8% from 25 to 44, and 25.4% from 45 to 64."
    result = evaluate(context, "Which age group had the lowest amount of people?", "18 to 24")
    assert result.status is ProofStatus.PROVED
    assert "selected=18 to 24" in result.calculation_trace


def test_temporal_choice_uses_months_when_events_share_a_year():
    context = (
        "On 10 September 1580, Papal troops landed in Smerwick. "
        "In October 1580, Grey de Wilton arrived at Smerwick."
    )
    result = evaluate(context, "Who arrived in Smerwick first, Grey de Wilton or Papal troops?", "Papal troops")
    assert result.status is ProofStatus.PROVED
    assert "papal troops=1580-09-10" in result.calculation_trace


def test_temporal_choice_uses_day_and_month_before_same_year_invasion():
    context = (
        "The Siamese captured Chiang Mai on 10 February 1663. "
        "In November 1663, Siam launched a two-pronged invasion."
    )
    result = evaluate(
        context,
        "What happened first: Siamese captured Chiang Mai or Siam launched a two-pronged invasion?",
        "Siamese captured Chiang Mai",
    )
    assert result.status is ProofStatus.PROVED
    assert "siamese captured chiang mai=1663-02-10" in result.calculation_trace


def test_touchdown_receiver_is_bound_to_requested_yardage():
    context = "Warner completed a 7-yard TD pass to WR Anquan Boldin. Bulger completed a 3-yard TD pass to WR Torry Holt."
    result = evaluate(context, "Who caught a 3 yard touchdown pass?", "Anquan Boldin")
    assert result.status is ProofStatus.DISPROVED
    assert "expected=torry holt" in result.calculation_trace


def test_gallery_sales_relation_chooses_the_explicit_option():
    context = "Art Euphoric has visual and craft exhibits and sales. The Trescott Street Gallery primarily exhibits visual arts."
    result = evaluate(context, "Which gallery had sales, Art Euphoric or Trescott Street Gallery?", "Trescott Street Gallery")
    assert result.status is ProofStatus.DISPROVED
    assert "expected=art euphoric" in result.calculation_trace


def test_semantic_opposition_requires_reformulation():
    result = evaluate("Momchil won in June and was defeated in July.", "When did the first success of a defeat happen?", "May")
    assert result.status is ProofStatus.UNRESOLVED
    assert result.reason == "QUESTION_SEMANTIC_OPPOSITION_REQUIRES_REFORMULATION"


def test_answer_year_cannot_replace_requested_year():
    context = "In July 2023, Pfizer changed its executive leadership."
    result = evaluate(context, "Did Pfizer change leadership in Q2 FY2022?", "Yes, in July 2023 it did.")
    assert result.status is ProofStatus.DISPROVED
    assert result.reason == "ANSWER_TIMEFRAME_CONTRADICTION"


def test_single_quantifier_cannot_replace_explicit_multiple_scope():
    context = "The rate was negative due to resolutions in multiple tax jurisdictions spanning multiple tax years."
    answer = "It was due to a resolution in a single tax jurisdiction for the current tax year."
    result = evaluate(context, "Why was the effective tax rate negative?", answer)
    assert result.status is ProofStatus.DISPROVED
    assert result.reason == "QUANTIFIER_SCOPE_CONTRADICTION"


def test_net_revenues_row_closes_ebitda_margin_formula():
    context = """Year Ended December 31,
2015
Net revenues
8592
Income from operations
2197
Depreciation and amortization
687
"""
    result = evaluate(context, "What is the FY2015 unadjusted EBITDA margin?", "34.2%")
    assert result.status is ProofStatus.DISPROVED
    assert result.reason == "FINANCE_FORMULA_CONTRADICTION"


def test_total_net_revenues_is_preferred_over_section_header_for_margin():
    context = """For the Years Ended December 31,
2022
2021
Net revenues
Product sales
1642
2311
In-game, subscription, and other revenues
5886
6492
Total net revenues
7528
8803
Operating income
1670
3259
"""
    result = evaluate(
        context,
        "What is the change in unadjusted operating income % margin from FY2021 to FY2022?",
        "-14.8%",
    )
    assert result.status is ProofStatus.PROVED
    assert "2021:3259/8803*100=37.0214699534" in result.calculation_trace


def test_respectively_year_value_binding_ignores_day_of_month():
    context = "The company paid $489 million and $466 million during the years ended December 31, 2022 and December 31, 2021, respectively."
    result = evaluate(context, "Has the company paid dividends in 2022?", "Yes, it paid $466 million in 2022.")
    assert result.status is ProofStatus.DISPROVED
    assert result.reason == "YEAR_VALUE_RELATION_CONTRADICTION"


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


def test_passage_citation_markers_do_not_become_factual_numbers():
    context = (
        "passage 1: DNA is a nucleic acid. It is composed of nucleotides. "
        "The order of its bases determines the genetic code."
    )
    answer = (
        "(Passage 1) DNA is a nucleic acid. "
        "(Passage 1) It is composed of nucleotides. "
        "(Passage 1) The order of its bases determines the genetic code."
    )
    result = evaluate(context, "What is DNA?", answer)
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
