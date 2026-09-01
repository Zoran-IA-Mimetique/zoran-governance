from __future__ import annotations

from dataclasses import dataclass, field

from components.semantic_color_patterns_v0.quarantine_watcher import QuarantineVerdict
from components.true_learning_v1.learning_loop import LearningObject


@dataclass(frozen=True)
class BoundedAcquisitionVerdict:
    state: str
    object_key: str
    semantic_hypothesis: str | None
    reasons: tuple[str, ...]
    experimental_reuse: bool
    canon_promotion: str = "FORBIDDEN"


def evaluate_bounded_acquisition(
    *,
    object_key: str,
    watcher: QuarantineVerdict,
    learning_object: LearningObject,
    minimum_replay: int = 1000,
) -> BoundedAcquisitionVerdict:
    reasons: list[str] = []
    if watcher.object_key != object_key:
        reasons.append("WATCHER_OBJECT_MISMATCH")
    if learning_object.family != object_key:
        reasons.append("TRUE_LEARNING_OBJECT_MISMATCH")
    if watcher.state != "CANDIDATE_STABLE":
        reasons.append("SEMANTIC_CANDIDATE_NOT_STABLE")
    if watcher.hypothesis is None:
        reasons.append("SEMANTIC_HYPOTHESIS_MISSING")
    if watcher.consensus < 0.80:
        reasons.append("SEMANTIC_CONSENSUS_TOO_LOW")
    if learning_object.synthesis_status != "ACQUIRED_BOUNDED":
        reasons.append("TRUE_LEARNING_NOT_ACQUIRED_BOUNDED")
    if learning_object.state != "QUARANTINED":
        reasons.append("TRUE_LEARNING_STATE_NOT_QUARANTINED")
    if not learning_object.replay_identical:
        reasons.append("TRUE_LEARNING_REPLAY_DIVERGED")
    if learning_object.replay_count < minimum_replay:
        reasons.append("TRUE_LEARNING_REPLAY_TOO_LOW")
    if learning_object.promotion != "FORBIDDEN":
        reasons.append("TRUE_LEARNING_PROMOTION_BOUNDARY_BROKEN")

    reusable = not reasons
    return BoundedAcquisitionVerdict(
        state="EXPERIMENTALLY_ACQUIRED" if reusable else "BLOCKED",
        object_key=object_key,
        semantic_hypothesis=watcher.hypothesis if reusable else None,
        reasons=tuple(reasons),
        experimental_reuse=reusable,
    )


@dataclass
class ExperimentalLexicon:
    """Append-only reuse set for the experimental branch only.

    It changes routing cost, not truth/canon authority. A surface may carry
    several sense-aware object identities; admitting one sense must never erase
    or silently replace another construction/meaning.
    """

    _surfaces: dict[str, dict[str, str]] = field(default_factory=dict)

    def admit(self, surface: str, verdict: BoundedAcquisitionVerdict) -> None:
        if not verdict.experimental_reuse or verdict.state != "EXPERIMENTALLY_ACQUIRED":
            raise ValueError("bounded acquisition gate did not pass")
        key = surface.casefold().strip()
        if not key:
            raise ValueError("surface required")
        senses = self._surfaces.setdefault(key, {})
        hypothesis = verdict.semantic_hypothesis or ""
        previous = senses.get(verdict.object_key)
        if previous is not None and previous != hypothesis:
            raise ValueError("experimental lexicon sense conflict")
        senses[verdict.object_key] = hypothesis

    def known_surfaces(self) -> tuple[str, ...]:
        return tuple(sorted(self._surfaces))

    def contains(self, surface: str) -> bool:
        return bool(self._surfaces.get(surface.casefold().strip()))

    def candidate_keys(self, surface: str) -> tuple[str, ...]:
        return tuple(sorted(self._surfaces.get(surface.casefold().strip(), {})))

    def hypotheses(self, surface: str) -> tuple[str, ...]:
        senses = self._surfaces.get(surface.casefold().strip(), {})
        return tuple(sorted(set(senses.values())))
