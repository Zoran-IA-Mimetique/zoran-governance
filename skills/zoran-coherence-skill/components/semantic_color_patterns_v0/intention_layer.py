from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence


SEMANTIC_HUES: dict[str, str] = {
    "ACTOR": "BLUE",
    "ACTION": "RED",
    "OBJECT": "GREEN",
    "CONTEXT": "YELLOW",
    "SWITCH": "MAGENTA",
    "UNKNOWN": "GRAY",
}

SWITCH_TYPES = frozenset({
    "NEGATION",
    "CONTRAST",
    "CORRECTION",
    "CONCESSION",
    "RESTRICTION",
    "CONDITION",
    "REVISION",
    "INVERSION",
})


@dataclass(frozen=True)
class IntentionBrick:
    surface: str
    semantic_family: str
    frame_id: str
    intention_vector: Mapping[str, float]
    utility_delta: float
    redundancy_count: int = 0
    switch_type: str | None = None
    switch_scope: str | None = None

    def __post_init__(self) -> None:
        if not self.surface:
            raise ValueError("surface must be non-empty")
        if self.semantic_family not in SEMANTIC_HUES:
            raise ValueError("unknown semantic_family")
        if not self.frame_id:
            raise ValueError("frame_id must be non-empty")
        if self.redundancy_count < 0:
            raise ValueError("redundancy_count must be >= 0")
        if self.switch_type is not None and self.switch_type not in SWITCH_TYPES:
            raise ValueError("unknown switch_type")
        if self.switch_type is not None and not self.switch_scope:
            raise ValueError("switch_scope required for semantic switch")
        for key, value in self.intention_vector.items():
            if not key or not isinstance(value, (int, float)):
                raise ValueError("invalid intention vector")
            if value < -1.0 or value > 1.0:
                raise ValueError("intention values must be in [-1, 1]")

    @property
    def intention_strength(self) -> float:
        if not self.intention_vector:
            return 0.0
        return max(abs(float(v)) for v in self.intention_vector.values())

    @property
    def visual_family(self) -> str:
        return "SWITCH" if self.switch_type else self.semantic_family


@dataclass(frozen=True)
class VisualBrick:
    surface: str
    hue_family: str
    intensity_0_100: int
    utility_state: str
    switch_type: str | None
    switch_scope: str | None


@dataclass(frozen=True)
class ParagraphIntention:
    verdict: str
    dominant_intention: str | None
    vector: dict[str, float]
    dark_bricks: int
    aligned_share: float
    reason: str


def classify_utility(
    brick: IntentionBrick,
    *,
    neutral_epsilon: float = 0.02,
) -> str:
    """Classify usefulness independently from semantic hue.

    WHITE: no measurable contribution.
    SEMANTIC: positive contribution.
    PARASITE_GRAY: negative contribution but not strongly redundant.
    REDUNDANT_BLACK: negative contribution reinforced by repetition.
    """
    if abs(brick.utility_delta) <= neutral_epsilon:
        return "WHITE"
    if brick.utility_delta > neutral_epsilon:
        return "SEMANTIC"
    if brick.redundancy_count >= 2:
        return "REDUNDANT_BLACK"
    return "PARASITE_GRAY"


def visual_brick(brick: IntentionBrick) -> VisualBrick:
    state = classify_utility(brick)

    if state == "WHITE":
        intensity = 0
        hue = "WHITE"
    elif state == "PARASITE_GRAY":
        # More harmful => darker gray. Clamp to 25..75.
        intensity = max(25, min(75, round(abs(brick.utility_delta) * 100)))
        hue = "GRAY"
    elif state == "REDUNDANT_BLACK":
        # Repetition reinforces blackness, without changing computational identity.
        penalty = abs(brick.utility_delta) * 70 + min(brick.redundancy_count, 6) * 5
        intensity = max(70, min(100, round(penalty)))
        hue = "BLACK"
    else:
        intensity = max(1, min(100, round(brick.intention_strength * 100)))
        hue = SEMANTIC_HUES[brick.visual_family]

    return VisualBrick(
        surface=brick.surface,
        hue_family=hue,
        intensity_0_100=intensity,
        utility_state=state,
        switch_type=brick.switch_type,
        switch_scope=brick.switch_scope,
    )


def paragraph_intention(
    bricks: Sequence[IntentionBrick],
    *,
    dark_threshold: float = 0.65,
    min_dark_bricks: int = 3,
    min_aligned_share: float = 0.60,
) -> ParagraphIntention:
    """Infer paragraph intention only from useful, strong bricks.

    A result is deliberately unresolved when evidence is too sparse or when
    strong bricks point in competing directions. Switch bricks remain evidence,
    but their scope is preserved separately and can later trigger frame rebuild.
    """
    eligible = [
        b for b in bricks
        if b.utility_delta > 0.02 and b.intention_strength >= dark_threshold
    ]
    if len(eligible) < min_dark_bricks:
        return ParagraphIntention(
            verdict="INTENTION_NON_RESOLUE",
            dominant_intention=None,
            vector={},
            dark_bricks=len(eligible),
            aligned_share=0.0,
            reason="insufficient_dark_bricks",
        )

    aggregate: dict[str, float] = {}
    total_mass = 0.0
    for brick in eligible:
        weight = brick.intention_strength * max(brick.utility_delta, 0.0)
        for key, value in brick.intention_vector.items():
            contribution = float(value) * weight
            aggregate[key] = aggregate.get(key, 0.0) + contribution
            total_mass += abs(contribution)

    if not aggregate or total_mass == 0.0:
        return ParagraphIntention(
            verdict="INTENTION_NON_RESOLUE",
            dominant_intention=None,
            vector=aggregate,
            dark_bricks=len(eligible),
            aligned_share=0.0,
            reason="zero_intention_mass",
        )

    dominant, dominant_value = max(
        aggregate.items(), key=lambda item: (abs(item[1]), item[0])
    )
    aligned_share = abs(dominant_value) / total_mass
    if aligned_share < min_aligned_share:
        return ParagraphIntention(
            verdict="MULTI_INTENTION",
            dominant_intention=None,
            vector=aggregate,
            dark_bricks=len(eligible),
            aligned_share=aligned_share,
            reason="strong_bricks_diverge",
        )

    return ParagraphIntention(
        verdict="PASS",
        dominant_intention=dominant,
        vector=aggregate,
        dark_bricks=len(eligible),
        aligned_share=aligned_share,
        reason="dark_bricks_converge",
    )
