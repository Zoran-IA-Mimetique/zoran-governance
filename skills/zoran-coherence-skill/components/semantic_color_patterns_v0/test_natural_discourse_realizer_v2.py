import json
from pathlib import Path

import pytest

from components.semantic_color_patterns_v0.discourse_realizer_v1 import SemanticDiscourse
from components.semantic_color_patterns_v0.natural_discourse_realizer_v2 import NaturalDiscourseRealizerV2


FIXTURE = Path(__file__).with_name("fixtures") / "technical_microcorpus_v0" / "corpus.jsonl"
RECORDS = [json.loads(line) for line in FIXTURE.read_text(encoding="utf-8").splitlines() if line.strip()]
DISCOURSES = tuple(SemanticDiscourse.from_target(record["semantic_target"]) for record in RECORDS)


def test_all_thirty_targets_recomprehend_from_natural_surface():
    realizer = NaturalDiscourseRealizerV2.from_discourses(DISCOURSES)
    for record, discourse in zip(RECORDS, DISCOURSES):
        result = realizer.realize(discourse)
        assert result.status == "SPEECH_READY", record["id"]
        assert result.reason == "EXACT_NATURAL_ROUND_TRIP", record["id"]
        assert result.attempts[-1].semantic_alignment == 1.0, record["id"]


class _CorruptEveryCandidate(NaturalDiscourseRealizerV2):
    def __init__(self, old, new):
        super().__init__(tuple(p.relation for d in DISCOURSES for p in d.propositions))
        self.old = old
        self.new = new

    def _candidate(self, discourse, attempt):
        candidate = super()._candidate(discourse, attempt)
        return candidate.replace(self.old, self.new, 1)


@pytest.mark.parametrize(
    ("record_id", "old", "new", "field"),
    [
        ("NET-01", "ne prouve pas", "prouve", "propositions"),
        ("NET-01", "politique de reprise", "aucune condition", "propositions"),
        ("NET-01", "acquittement du destinataire", "émetteur", "references"),
        ("NET-04", "pas de capacité durable", "capacité durable", "propositions"),
        ("NET-04", " cause ", " empêche ", "propositions"),
        ("ENE-01", "kilowattheure", "kilowatt", "units"),
        ("ACO-05", "son direct", "réflexions", "temporal_order"),
        ("ACO-06", "reformulation avant parole", "parole sans reformulation", "propositions"),
    ],
)
def test_critical_natural_drift_restarts_mission(record_id, old, new, field):
    index = next(i for i, record in enumerate(RECORDS) if record["id"] == record_id)
    result = _CorruptEveryCandidate(old, new).realize(DISCOURSES[index])
    assert result.status == "MISSION_RESTART"
    assert result.speech is None
    assert all(field in attempt.differing_fields for attempt in result.attempts)


class _CorruptFirstCandidate(NaturalDiscourseRealizerV2):
    def _candidate(self, discourse, attempt):
        candidate = super()._candidate(discourse, attempt)
        return candidate.replace("ne prouve pas", "prouve", 1) if attempt == 1 else candidate


def test_natural_candidate_is_repaired_before_speech():
    realizer = _CorruptFirstCandidate(tuple(p.relation for d in DISCOURSES for p in d.propositions))
    result = realizer.realize(DISCOURSES[0])
    assert result.status == "SPEECH_READY"
    assert len(result.attempts) == 2
    assert result.attempts[0].decision == "RESTART_CANDIDATE"
    assert result.attempts[1].decision == "EMIT"
    assert result.speech.startswith("Précision.")
