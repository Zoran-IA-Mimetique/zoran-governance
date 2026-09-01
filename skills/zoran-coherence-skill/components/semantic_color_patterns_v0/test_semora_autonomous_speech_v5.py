import json

import pytest

from components.semantic_color_patterns_v0.discourse_realizer_v1 import (
    DiscourseAttempt,
    DiscourseRealizationResult,
    SemanticDiscourse,
    SemanticProposition,
)
from components.semantic_color_patterns_v0.semora_autonomous_speech_v5 import (
    TEACHER_SCHEMA,
    AutonomousSpeechLearnerV5,
    SpeechCurriculumCaseV5,
    SpeechLearningMemoryV5,
    parse_teacher_rule,
)


def _discourse(number: int, failure: str) -> SemanticDiscourse:
    kwargs = {}
    if failure == "MISSING_UNIT":
        kwargs["units"] = ("seconde",)
    elif failure == "REFERENCE_DRIFT":
        kwargs["references"] = (("il", f"acteur {number}"),)
    elif failure == "TEMPORAL_DRIFT":
        kwargs["temporal_order"] = ("avant", "après")
    relation = "ne déclenche pas" if failure == "POLARITY_DRIFT" else "déclenche"
    return SemanticDiscourse(
        intent="expliquer",
        propositions=(SemanticProposition(f"acteur {number}", relation, f"effet {number}"),),
        **kwargs,
    )


class _RuleAwareRealizer:
    def __init__(self, triggers, requirements):
        self.triggers = set(triggers)
        self.requirements = requirements

    def realize(self, discourse):
        required = self.requirements[discourse.semantic_sha256]
        if required in self.triggers:
            return DiscourseRealizationResult(
                status="SPEECH_READY",
                speech="La formulation conserve entièrement le sens et reste naturelle à l'oral.",
                target_sha256=discourse.semantic_sha256,
                attempts=(DiscourseAttempt(1, "a" * 64, 1.0, (), discourse.semantic_sha256, "EMIT"),),
                reason="SEMANTIC_EQUIVALENCE_AND_BLIND_NATURALNESS",
            )
        raw_failure = {
            "MISSING_UNIT": "unit:seconde",
            "REFERENCE_DRIFT": "reference:il->acteur",
            "TEMPORAL_DRIFT": "temporal:0:avant",
            "POLARITY_DRIFT": "polarity=negative",
            "NATURALNESS": "naturalness",
        }[required]
        return DiscourseRealizationResult(
            status="MISSION_RESTART",
            speech=None,
            target_sha256=discourse.semantic_sha256,
            attempts=(DiscourseAttempt(1, "b" * 64, 0.8, (raw_failure,), None, "RESTART_CANDIDATE"),),
            reason="CONVERSATIONAL_SPEECH_NOT_ADMISSIBLE",
        )


class _ClosedTeacher:
    def __init__(self):
        self.calls = 0

    def __call__(self, prompt):
        self.calls += 1
        request = json.loads(prompt)
        triggers = request["observed_failure_classes"]
        return json.dumps({
            "schema": TEACHER_SCHEMA,
            "teacher_id": "gma4-closed-teacher",
            "triggers": triggers,
            "instruction": "Reformuler entièrement en conservant explicitement chaque propriété de cette famille.",
        }, ensure_ascii=False)


def _campaign():
    classes = ("MISSING_UNIT", "REFERENCE_DRIFT", "TEMPORAL_DRIFT", "POLARITY_DRIFT", "NATURALNESS")
    training = tuple(
        SpeechCurriculumCaseV5(f"TRAIN-{index:02d}", _discourse(index, classes[(index - 1) % len(classes)]))
        for index in range(1, 21)
    )
    holdout = tuple(
        SpeechCurriculumCaseV5(f"HOLD-{index:02d}", _discourse(index + 100, classes[(index - 1) % len(classes)]))
        for index in range(1, 11)
    )
    requirements = {
        item.discourse.semantic_sha256: classes[(position - 1) % len(classes)]
        for position, item in enumerate((*training, *holdout), 1)
    }
    teacher = _ClosedTeacher()
    learner = AutonomousSpeechLearnerV5(
        realizer_factory=lambda rules: _RuleAwareRealizer(
            [trigger for rule in rules for trigger in rule.triggers], requirements,
        ),
        teacher=teacher,
        max_learning_cycles=4,
    )
    return learner, teacher, training, holdout


def test_thirty_case_curriculum_reaches_ten_of_ten_without_false_emission():
    learner, teacher, training, holdout = _campaign()
    receipt = learner.run(training=training, holdout=holdout)
    assert receipt.training_ready_count == receipt.training_count == 20
    assert receipt.holdout_ready_count == receipt.holdout_count == 10
    assert receipt.training_coverage_10 == receipt.holdout_coverage_10 == 10.0
    assert receipt.false_emission_count == 0
    assert receipt.teacher_calls == teacher.calls == 5
    assert receipt.learned_rule_count == 5
    assert receipt.status == "EXPERIMENTAL_CAMPAIGN_COMPLETE"
    assert receipt.promotion == "FORBIDDEN"


def test_teacher_is_called_once_per_general_failure_not_once_per_case():
    learner, teacher, training, holdout = _campaign()
    learner.run(training=training, holdout=holdout)
    assert teacher.calls == 5
    assert len(training) + len(holdout) == 30


def test_content_addressed_memory_survives_cold_replay(tmp_path):
    learner, _, training, holdout = _campaign()
    first = learner.run(training=training, holdout=holdout)
    path = learner.memory.save_content_addressed(tmp_path)
    loaded = SpeechLearningMemoryV5.load(path)
    assert loaded.snapshot()["memory_sha256"] == first.memory_sha256
    assert loaded.snapshot() == learner.memory.snapshot()
    assert loaded.save_content_addressed(tmp_path) == path


def test_cold_memory_solves_unseen_holdout_without_calling_teacher():
    learner, _, training, holdout = _campaign()
    learner.run(training=training)
    requirements = {
        item.discourse.semantic_sha256: ("MISSING_UNIT", "REFERENCE_DRIFT", "TEMPORAL_DRIFT", "POLARITY_DRIFT", "NATURALNESS")[(index - 1) % 5]
        for index, item in enumerate(holdout, 1)
    }

    def forbidden_teacher(_prompt):
        raise AssertionError("teacher must not be called during holdout replay")

    cold = AutonomousSpeechLearnerV5(
        realizer_factory=lambda rules: _RuleAwareRealizer(
            [trigger for rule in rules for trigger in rule.triggers], requirements,
        ),
        teacher=forbidden_teacher,
        memory=learner.memory,
    )
    # One seed item is required by the campaign contract; it already passes from memory.
    receipt = cold.run(training=(holdout[0],), holdout=holdout[1:])
    assert receipt.training_coverage_10 == receipt.holdout_coverage_10 == 10.0
    assert receipt.teacher_calls == 0


def test_teacher_cannot_expand_scope_or_return_case_specific_rule():
    raw = json.dumps({
        "schema": TEACHER_SCHEMA,
        "teacher_id": "teacher",
        "triggers": ["MISSING_UNIT", "POLARITY_DRIFT"],
        "instruction": "Toujours préserver les unités et la polarité de chaque proposition.",
    })
    with pytest.raises(ValueError, match="changed the observed failure scope"):
        parse_teacher_rule(raw, expected_failures=("MISSING_UNIT",))

    case_specific = json.dumps({
        "schema": TEACHER_SCHEMA,
        "teacher_id": "teacher",
        "triggers": ["MISSING_UNIT"],
        "instruction": "Corriger uniquement le cas ACO-04 en ajoutant exactement son unité manquante.",
    })
    with pytest.raises(ValueError, match="general"):
        parse_teacher_rule(case_specific, expected_failures=("MISSING_UNIT",))


def test_teacher_must_cover_all_observed_failures_exactly_once():
    missing = json.dumps({
        "schema": TEACHER_SCHEMA,
        "teacher_id": "teacher",
        "triggers": ["MISSING_UNIT"],
        "instruction": "Toujours préserver les unités et chaque référence observée.",
    })
    with pytest.raises(ValueError, match="changed the observed failure scope"):
        parse_teacher_rule(
            missing,
            expected_failures=("MISSING_UNIT", "REFERENCE_DRIFT"),
        )

    duplicate = json.dumps({
        "schema": TEACHER_SCHEMA,
        "teacher_id": "teacher",
        "triggers": ["MISSING_UNIT", "MISSING_UNIT"],
        "instruction": "Toujours préserver explicitement toutes les unités observées.",
    })
    with pytest.raises(ValueError, match="changed the observed failure scope"):
        parse_teacher_rule(duplicate, expected_failures=("MISSING_UNIT",))


def test_invalid_teacher_output_never_enters_memory():
    memory = SpeechLearningMemoryV5()
    with pytest.raises(ValueError, match="pure JSON"):
        parse_teacher_rule("Voici la règle", expected_failures=("MISSING_UNIT",))
    assert memory.rules == ()
    assert memory.routes == ()
