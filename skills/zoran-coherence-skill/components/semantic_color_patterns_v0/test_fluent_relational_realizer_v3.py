import json
from pathlib import Path

import pytest

from components.semantic_color_patterns_v0.discourse_realizer_v1 import (
    SemanticDiscourse,
    SemanticProposition,
)
from components.semantic_color_patterns_v0.fluent_relational_realizer_v3 import (
    FluentRelationalRealizerV3,
)


FIXTURE = Path(__file__).with_name("fixtures") / "technical_microcorpus_v0" / "corpus.jsonl"
RECORDS = [json.loads(line) for line in FIXTURE.read_text(encoding="utf-8").splitlines() if line.strip()]
DISCOURSES = tuple(SemanticDiscourse.from_target(record["semantic_target"]) for record in RECORDS)


def test_all_thirty_targets_recomprehend_from_grammatical_relational_speech():
    realizer = FluentRelationalRealizerV3()
    for record, discourse in zip(RECORDS, DISCOURSES):
        result = realizer.realize(discourse)
        assert result.status == "SPEECH_READY", record["id"]
        assert result.reason == "EXACT_FLUENT_RELATIONAL_ROUND_TRIP", record["id"]
        assert result.attempts[-1].semantic_alignment == 1.0, record["id"]


UNSEEN_RELATION_HOLDOUT = (
    SemanticDiscourse(
        intent="expliquer un contrôle inédit",
        propositions=(
            SemanticProposition(
                "capteur auxiliaire",
                "stabilise sans remplacer",
                "mesure principale",
                restriction="validation locale seulement",
            ),
        ),
        temporal_order=("mesure principale", "contrôle auxiliaire", "comparaison"),
        references=(("celui-ci", "contrôle auxiliaire"),),
        units=("microseconde",),
    ),
    SemanticDiscourse(
        intent="distinguer une interdiction inédite",
        propositions=(
            SemanticProposition(
                "estimation locale",
                "ne doit jamais certifier",
                "état global",
                modality="must not",
                condition="preuve globale absente",
            ),
        ),
    ),
    SemanticDiscourse(
        intent="comparer un compromis inédit",
        propositions=(
            SemanticProposition(
                "filtre réversible",
                "améliore avec coût borné",
                "lisibilité",
                modality="possible",
                cost="un passage supplémentaire",
            ),
        ),
        units=("passage",),
    ),
)


def test_unseen_relations_need_no_learned_relation_inventory():
    realizer = FluentRelationalRealizerV3()
    for discourse in UNSEEN_RELATION_HOLDOUT:
        result = realizer.realize(discourse)
        assert result.status == "SPEECH_READY"
        assert result.attempts[-1].semantic_alignment == 1.0


def test_public_surface_is_grammatical_relational_french_not_a_field_dump():
    speech = FluentRelationalRealizerV3().realize(DISCOURSES[0]).speech
    assert speech is not None
    assert speech.startswith("Le but est d'expliquer.")
    assert "Entre «envoi» et «réception», la relation exprimée est «ne prouve pas»." in speech
    assert "Dans ce discours, «cette confirmation» désigne «acquittement du destinataire»." in speech
    assert "Proposition 1 :" not in speech
    assert "Temporalité :" not in speech


class _CorruptEveryCandidate(FluentRelationalRealizerV3):
    def __init__(self, old, new):
        super().__init__()
        self.old = old
        self.new = new

    def _candidate(self, discourse, attempt):
        return super()._candidate(discourse, attempt).replace(self.old, self.new, 1)


@pytest.mark.parametrize(
    ("record_id", "old", "new", "field"),
    [
        ("NET-01", "«ne prouve pas»", "«prouve»", "propositions"),
        ("NET-01", "«politique de reprise»", "«aucune condition»", "propositions"),
        ("NET-01", "«acquittement du destinataire»", "«émetteur»", "references"),
        ("NET-04", "«pas de capacité durable»", "«capacité durable»", "propositions"),
        ("NET-04", "«cause»", "«empêche»", "propositions"),
        ("ENE-01", "«kilowattheure»", "«kilowatt»", "units"),
        ("ACO-05", "d'abord «émission»", "d'abord «réflexions précoces»", "temporal_order"),
        ("ACO-06", "«reformulation avant parole»", "«parole sans reformulation»", "propositions"),
    ],
)
def test_critical_fluent_drift_restarts_mission(record_id, old, new, field):
    index = next(i for i, record in enumerate(RECORDS) if record["id"] == record_id)
    result = _CorruptEveryCandidate(old, new).realize(DISCOURSES[index])
    assert result.status == "MISSION_RESTART"
    assert result.speech is None
    assert all(field in attempt.differing_fields for attempt in result.attempts)


class _CorruptFirstCandidate(FluentRelationalRealizerV3):
    def _candidate(self, discourse, attempt):
        candidate = super()._candidate(discourse, attempt)
        return candidate.replace("«ne prouve pas»", "«prouve»", 1) if attempt == 1 else candidate


def test_fluent_candidate_is_repaired_before_speech():
    result = _CorruptFirstCandidate().realize(DISCOURSES[0])
    assert result.status == "SPEECH_READY"
    assert len(result.attempts) == 2
    assert result.attempts[0].decision == "RESTART_CANDIDATE"
    assert result.attempts[1].decision == "EMIT"
    assert result.speech.startswith("Je précise.")
