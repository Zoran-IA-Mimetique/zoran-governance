from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence


@dataclass(frozen=True)
class SemanticState:
    frame_id: str
    propositions: Mapping[str, float]
    intention_vector: Mapping[str, float]


@dataclass(frozen=True)
class SemanticSwitch:
    switch_type: str
    scope_ids: tuple[str, ...]
    strength: float = 1.0

    def __post_init__(self) -> None:
        if self.switch_type not in {
            "NEGATION", "CONTRAST", "CORRECTION", "CONCESSION",
            "RESTRICTION", "CONDITION", "REVISION", "INVERSION",
        }:
            raise ValueError("unknown switch type")
        if not self.scope_ids:
            raise ValueError("semantic switch requires explicit scope")
        if not 0.0 <= self.strength <= 1.0:
            raise ValueError("strength must be in [0,1]")


@dataclass(frozen=True)
class SwitchResult:
    propositions: dict[str, float]
    changed_ids: tuple[str, ...]
    requires_rebuild: bool
    reason: str


def apply_switch(state: SemanticState, switch: SemanticSwitch) -> SwitchResult:
    """Apply a bounded semantic switch to explicit proposition scope.

    The operator never infers scope from adjacency alone. Scope must already be
    resolved by the frame/parser layer. Values are bounded in [-1,1], where the
    sign carries polarity and magnitude carries support/activation strength.
    """
    current = dict(state.propositions)
    missing = [pid for pid in switch.scope_ids if pid not in current]
    if missing:
        return SwitchResult(current, (), True, "scope_unresolved")

    changed: list[str] = []

    if switch.switch_type in {"NEGATION", "INVERSION"}:
        for pid in switch.scope_ids:
            current[pid] = -float(current[pid]) * switch.strength
            changed.append(pid)
        return SwitchResult(current, tuple(changed), False, "polarity_inverted")

    if switch.switch_type == "RESTRICTION":
        for pid in switch.scope_ids:
            current[pid] = float(current[pid]) * (1.0 - switch.strength)
            changed.append(pid)
        return SwitchResult(current, tuple(changed), False, "scope_restricted")

    if switch.switch_type in {"CONTRAST", "CONCESSION", "CONDITION"}:
        # These operators alter relation topology rather than proposition truth
        # directly. A frame-level rebuild is therefore mandatory.
        return SwitchResult(current, (), True, "relation_topology_changed")

    if switch.switch_type in {"CORRECTION", "REVISION"}:
        # Previous interpretation is not silently overwritten. The affected
        # scope must be reconstructed from the corrected/revised clause.
        return SwitchResult(current, (), True, "interpretation_revision_required")

    raise AssertionError("unreachable")


def switch_interaction_signature(
    switch: SemanticSwitch,
    action_ids: Sequence[str],
) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    """Return an auditable interaction identity without assuming adjacency."""
    impacted_actions = tuple(sorted(set(switch.scope_ids) & set(action_ids)))
    return switch.switch_type, tuple(sorted(switch.scope_ids)), impacted_actions
