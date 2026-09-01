"""Governed learning loop for TRUE_LEARNING_V1.

The loop stores experiences, retrieves analogues deterministically, invokes a
bounded synthesizer, replays the frozen result, and emits a quarantined learning
object. It never promotes to canon. Fresh process memory may be seeded from
already-verified durable ZMOS analogue identities without importing examples or
granting recalled material any decision authority.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Callable, Iterable

from components.true_learning_v1.synthesizer import Example, SynthesisResult


@dataclass(frozen=True)
class LanguageExperience:
    experience_id: str
    family: str
    train: tuple[Example, ...]
    validation: tuple[Example, ...]
    holdout: tuple[Example, ...]
    source: str


@dataclass(frozen=True)
class LearningObject:
    learning_id: str
    family: str
    analogue_ids: tuple[str, ...]
    synthesis_status: str
    program_id: str | None
    trace_sha256: str
    replay_count: int
    replay_identical: bool
    state: str
    promotion: str


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _digest(value: object) -> str:
    return sha256(_canonical(value)).hexdigest()


class ExperienceMemory:
    """Append-only deterministic experience memory for the experiment."""

    def __init__(self) -> None:
        self._items: list[LanguageExperience] = []

    def append(self, experience: LanguageExperience) -> None:
        if any(item.experience_id == experience.experience_id for item in self._items):
            raise ValueError("duplicate experience_id")
        self._items.append(experience)

    def seed_recalled(self, experience_id: str, family: str, *, source: str = "ZMOS_DURABLE_RECALL") -> None:
        """Seed only a durable analogue identity into a fresh process memory.

        No TRAIN/VALIDATION/HOLDOUT example is reconstructed from memory. This
        preserves the boundary: recall can inform that an analogue exists but
        cannot silently become new training evidence.
        """
        if type(experience_id) is not str or not experience_id:
            raise ValueError("experience_id must be a non-empty exact string")
        if type(family) is not str or not family:
            raise ValueError("family must be a non-empty exact string")
        self.append(LanguageExperience(experience_id, family, (), (), (), source))

    def seed_durable_analogues(self, analogues: Iterable[object]) -> None:
        """Import verified analogue identities from a read-only durable view."""
        normalized: list[tuple[str, str]] = []
        for item in analogues:
            experience_id = getattr(item, "experience_id", None)
            family = getattr(item, "family", None)
            if type(experience_id) is not str or type(family) is not str:
                raise ValueError("durable analogue lacks exact experience_id/family")
            normalized.append((experience_id, family))
        for experience_id, family in sorted(set(normalized)):
            if not any(x.experience_id == experience_id for x in self._items):
                self.seed_recalled(experience_id, family)

    def analogues(self, family: str) -> tuple[LanguageExperience, ...]:
        return tuple(sorted((x for x in self._items if x.family == family), key=lambda x: x.experience_id))

    def snapshot_sha256(self) -> str:
        payload = [
            {
                "experience_id": x.experience_id,
                "family": x.family,
                "train_ids": [e.example_id for e in x.train],
                "validation_ids": [e.example_id for e in x.validation],
                "holdout_ids": [e.example_id for e in x.holdout],
                "source": x.source,
            }
            for x in self._items
        ]
        return _digest(payload)


def run_learning_cycle(
    memory: ExperienceMemory,
    experience: LanguageExperience,
    synthesizer: Callable[[list[Example], list[Example], list[Example]], SynthesisResult],
    replay_count: int = 1000,
) -> LearningObject:
    if replay_count < 1:
        raise ValueError("replay_count must be positive")

    analogues = memory.analogues(experience.family)
    frozen_train = list(experience.train)
    frozen_validation = list(experience.validation)
    frozen_holdout = list(experience.holdout)

    result = synthesizer(frozen_train, frozen_validation, frozen_holdout)
    replay_identical = True
    for _ in range(replay_count):
        replay = synthesizer(frozen_train, frozen_validation, frozen_holdout)
        if replay != result:
            replay_identical = False
            break

    state = "QUARANTINED" if result.status == "ACQUIRED_BOUNDED" and replay_identical else "REJECTED"
    payload = {
        "experience_id": experience.experience_id,
        "family": experience.family,
        "analogues": [x.experience_id for x in analogues],
        "result": asdict(result),
        "replay_count": replay_count,
        "replay_identical": replay_identical,
        "memory_before": memory.snapshot_sha256(),
        "state": state,
        "promotion": "FORBIDDEN",
    }
    learning_id = "LEARN-" + _digest(payload)[:24]
    memory.append(experience)
    return LearningObject(
        learning_id=learning_id,
        family=experience.family,
        analogue_ids=tuple(x.experience_id for x in analogues),
        synthesis_status=result.status,
        program_id=result.program_id,
        trace_sha256=result.trace_sha256,
        replay_count=replay_count,
        replay_identical=replay_identical,
        state=state,
        promotion="FORBIDDEN",
    )
