from __future__ import annotations

import unittest

from colored_frame_gate import (
    ColoredBrick,
    ColoredFrame,
    ColoredFrameGate,
    ColoredFrameRequest,
)
from structural_reasoning_gate import ProofStatus


class ColoredFrameBooleanTest(unittest.TestCase):
    def test_source_may_contain_more_roles(self) -> None:
        answer = ColoredFrame((
            ColoredBrick("SUBJECT", "Maya"),
            ColoredBrick("RELATION", "designed"),
            ColoredBrick("OBJECT", "bridge"),
        ))
        source = ColoredFrame((
            ColoredBrick("SUBJECT", "Maya"),
            ColoredBrick("RELATION", "designed"),
            ColoredBrick("OBJECT", "bridge"),
            ColoredBrick("QUALIFIER", "in March"),
        ))
        self.assertTrue(answer.is_contained_in(source))

    def test_same_words_with_swapped_roles_fail(self) -> None:
        source = ColoredFrame((
            ColoredBrick("SUBJECT", "Maya"),
            ColoredBrick("RELATION", "designed"),
            ColoredBrick("OBJECT", "bridge"),
        ))
        swapped = ColoredFrame((
            ColoredBrick("SUBJECT", "bridge"),
            ColoredBrick("RELATION", "designed"),
            ColoredBrick("OBJECT", "Maya"),
        ))
        self.assertFalse(swapped.is_contained_in(source))

    def test_polarity_mismatch_fails(self) -> None:
        bricks = (
            ColoredBrick("SUBJECT", "treatment"),
            ColoredBrick("RELATION", "reduced"),
            ColoredBrick("OBJECT", "duration"),
        )
        self.assertFalse(ColoredFrame(bricks, "NEGATIVE").is_contained_in(ColoredFrame(bricks)))

    def test_role_hue_is_fixed(self) -> None:
        with self.assertRaisesRegex(ValueError, "ROLE_HUE_MISMATCH"):
            ColoredBrick("SUBJECT", "Maya", "ORANGE")

    def test_different_words_same_pattern_and_intention_match(self) -> None:
        source = ColoredBrick("RELATION", "reduce")
        answer = ColoredBrick("RELATION", "lower")
        self.assertEqual(source.pattern_id, "CHANGE_DOWN")
        self.assertEqual(source.visual_motif, answer.visual_motif)
        self.assertEqual(source.intention, answer.intention)
        self.assertEqual(source.semantic_distance(answer), 1)
        self.assertTrue(source.says_the_same_thing_as(answer))

    def test_french_paraphrases_share_a_pattern(self) -> None:
        source = ColoredBrick("RELATION", "diminuer")
        answer = ColoredBrick("RELATION", "faire baisser")
        self.assertTrue(source.says_the_same_thing_as(answer))

    def test_opposite_intentions_do_not_match(self) -> None:
        self.assertFalse(
            ColoredBrick("RELATION", "reduce").says_the_same_thing_as(
                ColoredBrick("RELATION", "increase")
            )
        )

    def test_direction_arrow_is_outside_and_before_the_brick(self) -> None:
        down = ColoredBrick("RELATION", "reduce")
        up = ColoredBrick("RELATION", "increase")
        neutral = ColoredBrick("RELATION", "maintained")
        self.assertEqual(down.direction_arrow, "↓")
        self.assertEqual(down.display_token, "↓ reduce")
        self.assertEqual(up.direction_arrow, "↑")
        self.assertEqual(up.display_token, "↑ increase")
        self.assertEqual(neutral.direction_arrow, "")
        self.assertEqual(neutral.display_token, "maintained")

    def test_paraphrases_keep_the_same_direction_arrow(self) -> None:
        for value in ("reduce", "lower", "diminuer", "faire baisser"):
            with self.subTest(value=value):
                self.assertEqual(ColoredBrick("RELATION", value).direction_arrow, "↓")
        for value in ("increase", "rise", "augmenter", "monter"):
            with self.subTest(value=value):
                self.assertEqual(ColoredBrick("RELATION", value).direction_arrow, "↑")

    def test_direction_arrow_cannot_be_spoofed_by_caller(self) -> None:
        with self.assertRaisesRegex(ValueError, "PATTERN_DIRECTION_MISMATCH"):
            ColoredBrick("RELATION", "increase", direction_arrow="↓")

    def test_negation_remains_frame_polarity_not_downward_intention(self) -> None:
        relation = ColoredBrick("RELATION", "maintained")
        frame = ColoredFrame((relation,), polarity="NEGATIVE")
        self.assertEqual(relation.direction_arrow, "")
        self.assertEqual(frame.polarity, "NEGATIVE")

    def test_direction_field_preserves_previous_positional_api(self) -> None:
        brick = ColoredBrick(
            "RELATION", "reduce", "ORANGE", "CHANGE_DOWN",
            "WHITE_DOTS_SPARSE", "REDUCE", 5,
        )
        self.assertEqual(brick.intention_intensity, 5)
        self.assertEqual(brick.direction_arrow, "↓")

    def test_pattern_cannot_be_spoofed_by_caller(self) -> None:
        with self.assertRaisesRegex(ValueError, "PATTERN_VALUE_MISMATCH"):
            ColoredBrick("RELATION", "increase", pattern_id="CHANGE_DOWN")
        with self.assertRaisesRegex(ValueError, "PATTERN_INTENSITY_MISMATCH"):
            ColoredBrick("RELATION", "reduce", intention_intensity=9)

    def test_force_difference_is_preserved(self) -> None:
        slight = ColoredBrick("RELATION", "slightly reduce")
        strong = ColoredBrick("RELATION", "slash")
        self.assertEqual(slight.pattern_id, strong.pattern_id)
        self.assertEqual(slight.semantic_distance(strong), 2)
        self.assertFalse(slight.says_the_same_thing_as(strong))

    def test_motif_does_not_override_role(self) -> None:
        source = ColoredFrame((
            ColoredBrick("SUBJECT", "irrigated farms"),
            ColoredBrick("RELATION", "maintained"),
            ColoredBrick("OBJECT", "yields"),
        ))
        swapped = ColoredFrame((
            ColoredBrick("SUBJECT", "production"),
            ColoredBrick("RELATION", "kept steady"),
            ColoredBrick("OBJECT", "farms supplied with irrigation"),
        ))
        self.assertFalse(swapped.is_contained_in(source))

    def test_patterned_frame_cartesian_paraphrases(self) -> None:
        source = ColoredFrame((
            ColoredBrick("SUBJECT", "irrigated farms"),
            ColoredBrick("RELATION", "maintained"),
            ColoredBrick("OBJECT", "yields"),
        ))
        for subject in ("irrigated farms", "farms with irrigation", "farms supplied with irrigation"):
            for relation in ("maintained", "kept steady", "preserved", "remained stable"):
                for object_value in ("yield", "yields", "production", "farm output"):
                    with self.subTest(subject=subject, relation=relation, object_value=object_value):
                        answer = ColoredFrame((
                            ColoredBrick("SUBJECT", subject),
                            ColoredBrick("RELATION", relation),
                            ColoredBrick("OBJECT", object_value),
                        ))
                        self.assertTrue(answer.is_contained_in(source))


class ColoredFrameGateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.gate = ColoredFrameGate()

    def evaluate(self, context: str, question: str, answer: str):
        return self.gate.evaluate(ColoredFrameRequest(context, question, answer))

    def test_paraphrased_yes_no_is_proved(self) -> None:
        proof = self.evaluate(
            "The treated group recovered two days sooner. The treatment shortened symptom duration.",
            "Did the treatment shorten symptom duration?",
            "Yes. Participants receiving treatment recovered earlier.",
        )
        self.assertEqual(proof.status, ProofStatus.PROVED)

    def test_opposite_yes_no_is_disproved(self) -> None:
        proof = self.evaluate(
            "The intervention lowered systolic blood pressure by 8 mmHg.",
            "Did the intervention lower systolic blood pressure?",
            "No. Systolic pressure was unchanged.",
        )
        self.assertEqual(proof.status, ProofStatus.DISPROVED)

    def test_derived_value_is_proved(self) -> None:
        proof = self.evaluate(
            "Revenue was 120 million euros in 2024 and 150 million euros in 2025.",
            "By how much did revenue increase from 2024 to 2025?",
            "Revenue increased by 30 million euros.",
        )
        self.assertEqual(proof.status, ProofStatus.PROVED)

    def test_wrong_derived_value_is_disproved(self) -> None:
        proof = self.evaluate(
            "Revenue was 120 million euros in 2024 and 150 million euros in 2025.",
            "By how much did revenue increase from 2024 to 2025?",
            "Revenue increased by 20 million euros.",
        )
        self.assertEqual(proof.status, ProofStatus.DISPROVED)

    def test_swapped_people_are_disproved(self) -> None:
        proof = self.evaluate(
            "Maya designed the bridge. Luis supervised construction. Chen performed the final safety inspection.",
            "Who designed the bridge and who inspected it?",
            "Luis was the designer, while Maya carried out the final safety inspection.",
        )
        self.assertEqual(proof.status, ProofStatus.DISPROVED)

    def test_unknown_family_stays_not_applicable(self) -> None:
        proof = self.evaluate(
            "A deliberately unusual source sentence.",
            "Why is this poetic?",
            "Because it is unusual.",
        )
        self.assertEqual(proof.status, ProofStatus.NOT_APPLICABLE)

    def test_patterned_paraphrase_is_proved(self) -> None:
        proof = self.evaluate(
            "Irrigated farms maintained yields during the dry year.",
            "Which farms maintained yields?",
            "Farms supplied with irrigation kept production steady.",
        )
        self.assertEqual(proof.status, ProofStatus.PROVED)

    def test_patterned_contradiction_is_disproved(self) -> None:
        proof = self.evaluate(
            "Irrigated farms maintained yields during the dry year.",
            "Which farms maintained yields?",
            "Non-irrigated farms kept production steady.",
        )
        self.assertEqual(proof.status, ProofStatus.DISPROVED)

    def test_pattern_does_not_hide_opposite_relation(self) -> None:
        proof = self.evaluate(
            "Irrigated farms maintained yields during the dry year.",
            "Which farms maintained yields?",
            "Irrigated farms increased production.",
        )
        self.assertEqual(proof.status, ProofStatus.DISPROVED)

    def test_pattern_does_not_hide_negation(self) -> None:
        proof = self.evaluate(
            "Irrigated farms maintained yields during the dry year.",
            "Which farms maintained yields?",
            "Irrigated farms did not maintain their yields.",
        )
        self.assertEqual(proof.status, ProofStatus.DISPROVED)


# The bundled source-only release runner intentionally executes top-level test
# functions.  These wrappers keep the frame gate covered in clean extractions
# without requiring pytest.
def test_source_only_boolean_contract() -> None:
    case = ColoredFrameBooleanTest("test_same_words_with_swapped_roles_fail")
    case.test_same_words_with_swapped_roles_fail()
    case = ColoredFrameBooleanTest("test_source_may_contain_more_roles")
    case.test_source_may_contain_more_roles()
    for name in (
        "test_different_words_same_pattern_and_intention_match",
        "test_french_paraphrases_share_a_pattern",
        "test_opposite_intentions_do_not_match",
        "test_direction_arrow_is_outside_and_before_the_brick",
        "test_paraphrases_keep_the_same_direction_arrow",
        "test_direction_arrow_cannot_be_spoofed_by_caller",
        "test_negation_remains_frame_polarity_not_downward_intention",
        "test_direction_field_preserves_previous_positional_api",
        "test_pattern_cannot_be_spoofed_by_caller",
        "test_force_difference_is_preserved",
        "test_motif_does_not_override_role",
        "test_patterned_frame_cartesian_paraphrases",
    ):
        case = ColoredFrameBooleanTest(name)
        getattr(case, name)()


def test_source_only_gate_faithful_and_false() -> None:
    case = ColoredFrameGateTest("test_paraphrased_yes_no_is_proved")
    case.setUp()
    case.test_paraphrased_yes_no_is_proved()
    case = ColoredFrameGateTest("test_opposite_yes_no_is_disproved")
    case.setUp()
    case.test_opposite_yes_no_is_disproved()


def test_source_only_gate_derivation_and_role_swap() -> None:
    for name in (
        "test_derived_value_is_proved",
        "test_wrong_derived_value_is_disproved",
        "test_swapped_people_are_disproved",
        "test_patterned_paraphrase_is_proved",
        "test_patterned_contradiction_is_disproved",
        "test_pattern_does_not_hide_opposite_relation",
        "test_pattern_does_not_hide_negation",
    ):
        case = ColoredFrameGateTest(name)
        case.setUp()
        getattr(case, name)()


if __name__ == "__main__":
    unittest.main()
