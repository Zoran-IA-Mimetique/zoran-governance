from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


SEMANTIC_FRAMES = frozenset({
    "MOTION", "PERCEPTION", "COMMUNICATION", "STATE", "POSSESSION", "TRANSFER",
    "CHANGE", "LOCATION", "CAUSE", "EXISTENCE", "AVOIDANCE", "PROTECTION", "UNKNOWN",
})

DISCOURSE_INTENTIONS = frozenset({
    "DESCRIBE", "NARRATE", "INFORM", "ARGUE", "QUESTION", "COMMAND",
    "EXPLAIN", "COMPARE", "CORRECT", "UNKNOWN",
})


@dataclass(frozen=True)
class DualVectorBrick:
    surface: str
    brick_type: str
    frame_id: str
    semantic_vector: Mapping[str, float]
    discourse_vector: Mapping[str, float]
    utility_delta: float
    semantic_state: str = "QUARANTINED"
    discourse_state: str = "INTENTION_NON_RESOLUE"
    switch_type: str | None = None
    switch_scope: str | None = None

    def __post_init__(self) -> None:
        if not self.surface or not self.brick_type or not self.frame_id:
            raise ValueError("surface/type/frame required")
        for key, value in self.semantic_vector.items():
            if key not in SEMANTIC_FRAMES or not -1.0 <= float(value) <= 1.0:
                raise ValueError("invalid semantic vector")
        for key, value in self.discourse_vector.items():
            if key not in DISCOURSE_INTENTIONS or not -1.0 <= float(value) <= 1.0:
                raise ValueError("invalid discourse vector")
        if self.switch_type is not None and not self.switch_scope:
            raise ValueError("switch scope required")

    @property
    def semantic_strength(self) -> float:
        return max((abs(float(value)) for value in self.semantic_vector.values()), default=0.0)

    @property
    def discourse_strength(self) -> float:
        return max((abs(float(value)) for value in self.discourse_vector.values()), default=0.0)

    @property
    def visual_intensity(self) -> int:
        # Darkness represents discourse-intention contribution only.
        return max(0, min(100, round(self.discourse_strength * 100)))


def semantic_candidate(
    surface: str,
    frame: str,
    *,
    strength: float,
    source_state: str = "QUARANTINED",
) -> dict[str, object]:
    if frame not in SEMANTIC_FRAMES:
        raise ValueError("unknown semantic frame")
    if not 0.0 <= strength <= 1.0:
        raise ValueError("strength outside [0,1]")
    return {
        "surface": surface,
        "semantic_vector": {frame: strength},
        "semantic_state": source_state,
        "discourse_vector": {},
        "discourse_state": "INTENTION_NON_RESOLUE",
    }
