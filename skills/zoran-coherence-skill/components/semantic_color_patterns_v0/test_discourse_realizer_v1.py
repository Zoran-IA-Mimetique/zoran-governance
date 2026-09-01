from hashlib import sha256
import json
from pathlib import Path

import pytest

from components.semantic_color_patterns_v0.discourse_realizer_v1 import (
    ControlledDiscourseRealizerV1,
    SemanticDiscourse,
    SemanticProposition,
)


def _target():
    return {
        "intent": "EXPLIQUER_CAUSALITÉ",
        "propositions": [
            {
                "s": "envoi",
                "r": "ne_prouve_pas",
                "o": "réception",
                "polarity": "negative",
            },
            {
                "s": "acquittement_absent_après_délai",
                "r": "autorise_sous_condition",
                "o": "réessai",
                "condition": "politique de reprise",
            },
            {
                "s": "réessai",
                "r": "peut_créer",
                "o": "doublon",
                "modality": "possible",
                "cost": "traitement supplémentaire",
                "restriction": "déduplication active",
            },
        ],
        "temporal_order": ["envoi", "attente", "délai", "réessai éventuel"],
        "references": {
            "cette_confirmation": "acquittement du destinataire",
            "il": "coupe-circuit",
        },
        "units": ["seconde", "nombre de tentatives"],
        "features": ["negation", "causalité", "condition", "références", "unités"],
    }


def test_target_mapping_and_discourse_round_trip_are_exact():
    discourse = SemanticDiscourse.from_target(_target())
    result = ControlledDiscourseRealizerV1().realize(discourse)
    assert result.status == "SPEECH_READY"
    assert result.reason == "EXACT_DISCOURSE_ROUND_TRIP"
    assert result.attempts[-1].semantic_alignment == 1.0
    assert result.attempts[-1].differing_fields == ()
    assert result.attempts[-1].reunderstood_sha256 == discourse.semantic_sha256
    assert "«envoi» — «ne prouve pas» — «réception»" in result.speech
    assert "Temporalité : «envoi» → «attente» → «délai» → «réessai éventuel»." in result.speech


@pytest.mark.parametrize(
    "target",
    [
        {
            "intent": "DÉFINIR_ET_CALCULER",
            "propositions": [
                {"s": "énergie", "r": "égale_si_puissance_constante", "o": "puissance fois durée"}
            ],
            "references": {},
            "units": ["kilowatt", "heure", "kilowattheure"],
        },
        {
            "intent": "DISTINGUER",
            "propositions": [
                {"s": "corrélation temporelle", "r": "ne_démontre_pas_seule", "o": "causalité", "polarity": "negative"}
            ],
            "temporal_order": ["observation", "hypothèse", "vérification"],
            "references": {"elle": "corrélation temporelle"},
            "units": [],
        },
        {
            "intent": "EXPLIQUER_LIMITE",
            "propositions": [
                {"s": "filtre", "r": "peut_réduire_apparence_sans_réduire", "o": "cause", "restriction": "bande connue"}
            ],
            "references": {},
            "units": ["décibel"],
        },
    ],
)
def test_varied_technical_targets_remain_exact(target):
    discourse = SemanticDiscourse.from_target(target)
    result = ControlledDiscourseRealizerV1().realize(discourse)
    assert result.status == "SPEECH_READY"
    assert result.attempts[-1].semantic_alignment == 1.0


class _FirstNegationLost(ControlledDiscourseRealizerV1):
    def _candidate(self, discourse, attempt):
        candidate = super()._candidate(discourse, attempt)
        if attempt == 1:
            return candidate.replace("«ne prouve pas»", "«prouve»")
        return candidate


def test_negation_loss_restarts_candidate_then_recovers():
    discourse = SemanticDiscourse.from_target(_target())
    result = _FirstNegationLost().realize(discourse)
    assert result.status == "SPEECH_READY"
    assert len(result.attempts) == 2
    assert result.attempts[0].decision == "RESTART_CANDIDATE"
    assert "propositions" in result.attempts[0].differing_fields
    assert result.attempts[1].decision == "EMIT"
    assert result.speech.startswith("Précision contrôlée.")


class _EveryUnitCorrupted(ControlledDiscourseRealizerV1):
    def _candidate(self, discourse, attempt):
        return super()._candidate(discourse, attempt).replace("«seconde»", "«kilowatt»")


def test_unit_corruption_restarts_mission_without_speech():
    discourse = SemanticDiscourse.from_target(_target())
    result = _EveryUnitCorrupted().realize(discourse)
    assert result.status == "MISSION_RESTART"
    assert result.speech is None
    assert result.reason == "DISCOURSE_ALIGNMENT_INSUFFICIENT"
    assert all(attempt.decision == "RESTART_CANDIDATE" for attempt in result.attempts)
    assert all("units" in attempt.differing_fields for attempt in result.attempts)


class _EveryReferenceCorrupted(ControlledDiscourseRealizerV1):
    def _candidate(self, discourse, attempt):
        return super()._candidate(discourse, attempt).replace(
            "«acquittement du destinataire»",
            "«émetteur»",
        )


def test_reference_corruption_restarts_mission_without_speech():
    discourse = SemanticDiscourse.from_target(_target())
    result = _EveryReferenceCorrupted().realize(discourse)
    assert result.status == "MISSION_RESTART"
    assert result.speech is None
    assert all("references" in attempt.differing_fields for attempt in result.attempts)


class _EveryTemporalOrderCorrupted(ControlledDiscourseRealizerV1):
    def _candidate(self, discourse, attempt):
        return super()._candidate(discourse, attempt).replace(
            "«envoi» → «attente»",
            "«attente» → «envoi»",
        )


def test_temporal_inversion_restarts_mission_without_speech():
    discourse = SemanticDiscourse.from_target(_target())
    result = _EveryTemporalOrderCorrupted().realize(discourse)
    assert result.status == "MISSION_RESTART"
    assert result.speech is None
    assert all("temporal_order" in attempt.differing_fields for attempt in result.attempts)


class _EveryCriticalFieldCorrupted(ControlledDiscourseRealizerV1):
    def __init__(self, old, new):
        super().__init__()
        self._old = old
        self._new = new

    def _candidate(self, discourse, attempt):
        candidate = super()._candidate(discourse, attempt)
        assert self._old in candidate
        return candidate.replace(self._old, self._new, 1)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("«autorise sous condition»", "«interdit»"),
        ("«politique de reprise»", "«aucune condition»"),
        ("«déduplication active»", "«aucune restriction»"),
    ],
    ids=("causality", "condition", "restriction"),
)
def test_causal_condition_and_restriction_drift_restart_mission(old, new):
    discourse = SemanticDiscourse.from_target(_target())
    result = _EveryCriticalFieldCorrupted(old, new).realize(discourse)
    assert result.status == "MISSION_RESTART"
    assert result.speech is None
    assert all("propositions" in attempt.differing_fields for attempt in result.attempts)


def test_correction_inversion_restarts_mission():
    discourse = SemanticDiscourse.from_target({
        "intent": "SYNTHÉTISER",
        "propositions": [{
            "s": "résolution numérique",
            "r": "ne_corrige_pas",
            "o": "saturation déjà produite",
            "polarity": "negative",
        }],
        "references": {},
        "units": [],
    })
    result = _EveryCriticalFieldCorrupted(
        "«ne corrige pas»",
        "«corrige»",
    ).realize(discourse)
    assert result.status == "MISSION_RESTART"
    assert result.speech is None
    assert all("propositions" in attempt.differing_fields for attempt in result.attempts)


def test_deterministic_replay_is_byte_identical():
    discourse = SemanticDiscourse.from_target(_target())
    first = ControlledDiscourseRealizerV1().realize(discourse)
    second = ControlledDiscourseRealizerV1().realize(discourse)
    assert first == second


@pytest.mark.parametrize(
    "target",
    [
        {"intent": "EXPLIQUER", "propositions": []},
        {"intent": "EXPLIQUER", "propositions": [{"s": "a", "r": "b", "o": "c", "unknown": "x"}]},
        {"intent": "EXPLIQUER", "propositions": [{"s": "a", "r": "b", "o": "c"}], "references": []},
        {"intent": "EXPLIQUER", "propositions": [{"s": "a", "r": "b", "o": "c"}], "units": ["v", "V"]},
    ],
)
def test_invalid_or_ambiguous_targets_fail_closed(target):
    with pytest.raises(ValueError):
        SemanticDiscourse.from_target(target)


def test_reserved_speech_markers_fail_closed():
    with pytest.raises(ValueError):
        SemanticProposition("acteur", "relation", "objet » injecté")


def test_all_thirty_quarantined_technical_targets_round_trip_exactly():
    fixture = Path(__file__).with_name("fixtures") / "technical_microcorpus_v0"
    manifest = json.loads((fixture / "manifest.json").read_text(encoding="utf-8"))
    corpus_bytes = (fixture / "corpus.jsonl").read_bytes()
    declared = next(
        item["sha256"] for item in manifest["artifacts"]
        if item["path"] == "corpus.jsonl"
    )
    assert sha256(corpus_bytes).hexdigest() == declared

    records = [
        json.loads(line) for line in corpus_bytes.decode("utf-8").splitlines()
        if line.strip()
    ]
    assert len(records) == manifest["corpus"]["record_count"] == 30
    realizer = ControlledDiscourseRealizerV1()
    for record in records:
        discourse = SemanticDiscourse.from_target(record["semantic_target"])
        result = realizer.realize(discourse)
        assert result.status == "SPEECH_READY", record["id"]
        assert result.attempts[-1].semantic_alignment == 1.0, record["id"]
        assert result.attempts[-1].reunderstood_sha256 == discourse.semantic_sha256
