import json
from pathlib import Path

import pytest

from components.semantic_color_patterns_v0.conversational_speech_v4 import (
    DeterministicFrenchSurfaceGateV4,
    JUDGE_SCHEMA,
    LISTENER_SCHEMA,
    NATURALNESS_RUBRIC,
    SPEAKER_SCHEMA,
    ConversationalSpeechRealizerV4,
)
from components.semantic_color_patterns_v0.discourse_realizer_v1 import (
    SemanticDiscourse,
    SemanticProposition,
)
from components.semantic_color_patterns_v0.listener_ontology_v4 import build_listener_ontology
from components.semantic_color_patterns_v0.semantic_equivalence_normalizer_v4 import (
    SemanticEquivalenceNormalizerV4,
)


FIXTURE = Path(__file__).with_name("fixtures") / "technical_microcorpus_v0" / "corpus.jsonl"
RECORDS = [json.loads(line) for line in FIXTURE.read_text(encoding="utf-8").splitlines() if line.strip()]
DISCOURSES = tuple(SemanticDiscourse.from_target(record["semantic_target"]) for record in RECORDS)
LEARNED_SPEECH_FIXTURE = FIXTURE.with_name("conversational_speech_v4.jsonl")
LEARNED_SPEECH = [
    json.loads(line)
    for line in LEARNED_SPEECH_FIXTURE.read_text(encoding="utf-8").splitlines()
    if line.strip()
]
BLIND_REVIEW = json.loads(
    FIXTURE.with_name("conversational_speech_v4_blind_review.json").read_text(encoding="utf-8")
)


def _target(discourse: SemanticDiscourse):
    return {
        "intent": discourse.intent,
        "propositions": [
            {
                "s": item.subject,
                "r": item.relation,
                "o": item.object,
                **({"polarity": item.polarity} if item.polarity is not None else {}),
                **({"modality": item.modality} if item.modality is not None else {}),
                **({"condition": item.condition} if item.condition is not None else {}),
                **({"cost": item.cost} if item.cost is not None else {}),
                **({"restriction": item.restriction} if item.restriction is not None else {}),
            }
            for item in discourse.propositions
        ],
        "temporal_order": list(discourse.temporal_order),
        "references": dict(discourse.references),
        "units": list(discourse.units),
    }


def _speech_for(discourse: SemanticDiscourse) -> str:
    first = discourse.propositions[0]
    relation = first.relation.replace("_", " ").replace("’", "'")
    return (
        f"Voici l'essentiel. « {first.subject} » {relation} « {first.object} ». "
        "Les autres précisions sont formulées dans le même ordre, sans rien ajouter au sens."
    )


class _ClosedProviders:
    def __init__(self, discourses=DISCOURSES):
        self.by_sha = {item.semantic_sha256: item for item in discourses}
        self.by_speech = {_speech_for(item): item for item in discourses}
        self.listener_prompts = []
        self.attempts = {}

    def speaker(self, prompt):
        request = json.loads(prompt)
        target_sha = request["target_sha256"]
        attempt = request["attempt"]
        self.attempts[target_sha] = attempt
        return json.dumps({
            "schema": SPEAKER_SCHEMA,
            "target_sha256": target_sha,
            "attempt": attempt,
            "speech": _speech_for(self.by_sha[target_sha]),
        }, ensure_ascii=False)

    def listener(self, prompt):
        request = json.loads(prompt)
        self.listener_prompts.append(request)
        discourse = self.by_speech[request["speech"]]
        return json.dumps({
            "schema": LISTENER_SCHEMA,
            "discourse": _target(discourse),
        }, ensure_ascii=False)

    @staticmethod
    def judge(prompt):
        request = json.loads(prompt)
        assert request["rubric_id"] == NATURALNESS_RUBRIC
        return json.dumps({
            "schema": JUDGE_SCHEMA,
            "rubric_id": NATURALNESS_RUBRIC,
            "scores": {
                "syntax": 2,
                "vocabulary": 2,
                "information_order": 2,
                "references": 2,
                "speakable_rhythm": 1,
                "concision": 1,
            },
            "failures": [],
        }, ensure_ascii=False)


def _realizer(providers):
    return ConversationalSpeechRealizerV4(
        speaker=providers.speaker,
        listener=providers.listener,
        naturalness_judge=providers.judge,
        speaker_id="speaker-fixture-v1",
        listener_id="listener-fixture-v1",
        judge_id="judge-fixture-v1",
    )


def test_all_thirty_targets_cross_the_generate_recomprehend_judge_gate():
    providers = _ClosedProviders()
    realizer = _realizer(providers)
    for discourse in DISCOURSES:
        result = realizer.realize(discourse)
        assert result.status == "SPEECH_READY"
        assert result.reason == "EXACT_RECOMPREHENSION_AND_BLIND_NATURALNESS"
        assert result.attempts[-1].semantic_alignment == 1.0


def test_thirty_teacher_candidates_are_complete_unique_and_surface_admissible():
    assert [item["id"] for item in LEARNED_SPEECH] == [record["id"] for record in RECORDS]
    assert len({item["speech"] for item in LEARNED_SPEECH}) == len(RECORDS) == 30
    gate = DeterministicFrenchSurfaceGateV4()
    assert all(gate.evaluate(item["speech"]) == (True, ()) for item in LEARNED_SPEECH)


def test_blind_review_accepts_every_final_route_inside_three_attempts():
    final = BLIND_REVIEW["final"]
    assert BLIND_REVIEW["external_certification"] is False
    assert final["accepted_ids"] == [record["id"] for record in RECORDS]
    assert final["accepted_count"] == final["total_count"] == 30
    assert final["acceptance_rate"] == 1.0
    assert final["maximum_attempts_used"] <= 3


def test_listener_ontology_is_global_closed_and_target_independent():
    ontology = build_listener_ontology()
    assert set(ontology) == {
        "intents", "subjects", "relations", "objects", "polarities",
        "modalities", "conditions", "costs", "restrictions",
        "temporal_steps", "reference_sources", "reference_targets", "units",
    }
    assert all(values == sorted(set(values)) for values in ontology.values())
    assert len(ontology["relations"]) >= 90


UNSEEN_HOLDOUT = tuple(
    SemanticDiscourse(
        intent=f"expliquer le cas inédit {number}",
        propositions=(
            SemanticProposition(
                f"objet inédit {number}",
                f"agit de façon bornée {number}",
                f"résultat inédit {number}",
                condition=f"condition inédite {number}" if number % 2 else None,
                restriction=f"limite inédite {number}" if number % 3 == 0 else None,
            ),
        ),
        temporal_order=(f"départ {number}", f"arrivée {number}"),
        units=("seconde",),
    )
    for number in range(1, 11)
)


def test_ten_frozen_unseen_discourses_use_the_same_closed_protocol():
    providers = _ClosedProviders(UNSEEN_HOLDOUT)
    realizer = _realizer(providers)
    assert all(realizer.realize(discourse).status == "SPEECH_READY" for discourse in UNSEEN_HOLDOUT)


def test_listener_receives_speech_only_not_target_or_repair_trace():
    providers = _ClosedProviders((DISCOURSES[0],))
    result = _realizer(providers).realize(DISCOURSES[0])
    assert result.status == "SPEECH_READY"
    prompt = providers.listener_prompts[0]
    assert set(prompt) == {"role", "schema", "speech", "output_contract", "constraints"}
    assert "target_sha256" not in json.dumps(prompt)
    assert "semantic_target" not in json.dumps(prompt)
    assert "repair" not in prompt


def test_target_independent_equivalence_can_release_a_different_representation():
    target = SemanticDiscourse(
        intent="EXPLIQUER",
        propositions=(
            SemanticProposition("envoi", "ne_prouve_pas", "réception", polarity="negative"),
            SemanticProposition("réessai", "peut_créer", "doublon", modality="possible"),
        ),
    )
    observed = SemanticDiscourse(
        intent="EXPLIQUER_CAUSALITÉ",
        propositions=(
            SemanticProposition("envoi", "ne prouve pas", "réception"),
            SemanticProposition("réessai", "peut créer", "doublon"),
        ),
    )
    providers = _ClosedProviders((target,))

    def equivalent_listener(_prompt):
        return json.dumps({
            "schema": LISTENER_SCHEMA,
            "discourse": _target(observed),
        }, ensure_ascii=False)

    realizer = ConversationalSpeechRealizerV4(
        speaker=providers.speaker,
        listener=equivalent_listener,
        naturalness_judge=providers.judge,
        speaker_id="speaker-fixture-v1",
        listener_id="equivalent-listener-v1",
        judge_id="judge-fixture-v1",
        equivalence_normalizer=SemanticEquivalenceNormalizerV4(build_listener_ontology()),
    )
    result = realizer.realize(target)
    assert result.status == "SPEECH_READY"
    assert result.reason == "SEMANTIC_EQUIVALENCE_AND_BLIND_NATURALNESS"
    assert result.attempts[-1].semantic_alignment == 1.0


def test_equivalence_mode_still_restarts_when_one_unit_is_missing():
    target = SemanticDiscourse(
        intent="EXPLIQUER",
        propositions=(SemanticProposition("cache", "réduit", "latence et charge source"),),
        units=("seconde",),
    )
    observed = SemanticDiscourse(
        intent="EXPLIQUER",
        propositions=(SemanticProposition("cache", "réduit", "latence et charge source"),),
    )
    providers = _ClosedProviders((target,))

    def incomplete_listener(_prompt):
        return json.dumps({"schema": LISTENER_SCHEMA, "discourse": _target(observed)}, ensure_ascii=False)

    result = ConversationalSpeechRealizerV4(
        speaker=providers.speaker,
        listener=incomplete_listener,
        naturalness_judge=providers.judge,
        speaker_id="speaker-fixture-v1",
        listener_id="incomplete-listener-v1",
        judge_id="judge-fixture-v1",
        equivalence_normalizer=SemanticEquivalenceNormalizerV4(build_listener_ontology()),
    ).realize(target)
    assert result.status == "MISSION_RESTART"
    assert result.speech is None


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("intent", "autre intention"),
        ("propositions", []),
        ("temporal_order", ["ordre inversé"]),
        ("references", {"autre": "référent"}),
        ("units", ["autre unité"]),
    ],
)
def test_any_recomprehension_drift_restarts_without_speech(field, replacement):
    providers = _ClosedProviders((DISCOURSES[0],))

    def corrupt_listener(prompt):
        request = json.loads(prompt)
        target = _target(providers.by_speech[request["speech"]])
        target[field] = replacement
        return json.dumps({"schema": LISTENER_SCHEMA, "discourse": target}, ensure_ascii=False)

    realizer = ConversationalSpeechRealizerV4(
        speaker=providers.speaker,
        listener=corrupt_listener,
        naturalness_judge=providers.judge,
        speaker_id="speaker-fixture-v1",
        listener_id="corrupt-listener-v1",
        judge_id="judge-fixture-v1",
    )
    result = realizer.realize(DISCOURSES[0])
    assert result.status == "MISSION_RESTART"
    assert result.speech is None
    assert len(result.attempts) <= 3


def test_meta_relational_field_dump_is_blocked_before_listener():
    providers = _ClosedProviders((DISCOURSES[0],))

    def bad_speaker(prompt):
        request = json.loads(prompt)
        return json.dumps({
            "schema": SPEAKER_SCHEMA,
            "target_sha256": request["target_sha256"],
            "attempt": request["attempt"],
            "speech": f"Proposition 1 : la relation exprimée est relation. Essai {request['attempt']}.",
        })

    realizer = ConversationalSpeechRealizerV4(
        speaker=bad_speaker,
        listener=providers.listener,
        naturalness_judge=providers.judge,
        speaker_id="bad-speaker-v1",
        listener_id="listener-fixture-v1",
        judge_id="judge-fixture-v1",
    )
    result = realizer.realize(DISCOURSES[0])
    assert result.status == "MISSION_RESTART"
    assert not providers.listener_prompts


def test_blind_naturalness_below_ten_restarts_even_when_semantics_are_exact():
    providers = _ClosedProviders((DISCOURSES[0],))

    def weak_judge(_prompt):
        return json.dumps({
            "schema": JUDGE_SCHEMA,
            "rubric_id": NATURALNESS_RUBRIC,
            "scores": {
                "syntax": 2,
                "vocabulary": 2,
                "information_order": 2,
                "references": 1,
                "speakable_rhythm": 1,
                "concision": 1,
            },
            "failures": [],
        })

    realizer = ConversationalSpeechRealizerV4(
        speaker=providers.speaker,
        listener=providers.listener,
        naturalness_judge=weak_judge,
        speaker_id="speaker-fixture-v1",
        listener_id="listener-fixture-v1",
        judge_id="weak-judge-v1",
    )
    result = realizer.realize(DISCOURSES[0])
    assert result.status == "MISSION_RESTART"
    assert result.speech is None


def test_non_blocking_judge_notes_do_not_override_the_frozen_score_rule():
    providers = _ClosedProviders((DISCOURSES[0],))

    def accepted_with_note(_prompt):
        return json.dumps({
            "schema": JUDGE_SCHEMA,
            "rubric_id": NATURALNESS_RUBRIC,
            "scores": {
                "syntax": 2,
                "vocabulary": 2,
                "information_order": 2,
                "references": 2,
                "speakable_rhythm": 1,
                "concision": 1,
            },
            "failures": ["Rythme dense mais encore admissible."],
        }, ensure_ascii=False)

    result = ConversationalSpeechRealizerV4(
        speaker=providers.speaker,
        listener=providers.listener,
        naturalness_judge=accepted_with_note,
        speaker_id="speaker-fixture-v1",
        listener_id="listener-fixture-v1",
        judge_id="noted-judge-v1",
    ).realize(DISCOURSES[0])
    assert result.status == "SPEECH_READY"


def test_repeated_refused_candidate_does_not_create_an_unbounded_loop():
    providers = _ClosedProviders((DISCOURSES[0],))

    def rejecting_judge(_prompt):
        return json.dumps({
            "schema": JUDGE_SCHEMA,
            "rubric_id": NATURALNESS_RUBRIC,
            "scores": {key: 1 for key in ("syntax", "vocabulary", "information_order", "references", "speakable_rhythm", "concision")},
            "failures": ["telegraphic"],
        })

    realizer = ConversationalSpeechRealizerV4(
        speaker=providers.speaker,
        listener=providers.listener,
        naturalness_judge=rejecting_judge,
        speaker_id="speaker-fixture-v1",
        listener_id="listener-fixture-v1",
        judge_id="rejecting-judge-v1",
    )
    result = realizer.realize(DISCOURSES[0])
    assert result.status == "MISSION_RESTART"
    assert len(result.attempts) == 3
    assert result.speech is None


def test_two_full_replays_are_byte_identical():
    providers_a = _ClosedProviders((DISCOURSES[0],))
    providers_b = _ClosedProviders((DISCOURSES[0],))
    first = _realizer(providers_a).realize(DISCOURSES[0])
    second = _realizer(providers_b).realize(DISCOURSES[0])
    assert first == second


def test_role_labels_must_be_structurally_distinct():
    providers = _ClosedProviders((DISCOURSES[0],))
    with pytest.raises(ValueError, match="distinct identities"):
        ConversationalSpeechRealizerV4(
            speaker=providers.speaker,
            listener=providers.listener,
            naturalness_judge=providers.judge,
            speaker_id="same",
            listener_id="same",
            judge_id="judge",
        )
