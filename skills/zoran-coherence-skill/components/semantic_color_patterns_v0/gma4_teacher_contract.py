from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Mapping, Sequence

from components.semantic_color_patterns_v0.dual_vector_layer import (
    DISCOURSE_INTENTIONS,
    SEMANTIC_FRAMES,
)

_ALLOWED_POS = frozenset({
    "NOUN", "VERB", "ADJECTIVE", "ADVERB", "PRONOUN", "DETERMINER",
    "PREPOSITION", "CONJUNCTION", "INTERJECTION", "PARTICLE", "PROPER_NOUN",
    "AUXILIARY", "OTHER",
})
_POS_BY_CASEFOLD = {item.casefold(): item for item in _ALLOWED_POS}
_REQUIRED_KEYS = frozenset({
    "schema",
    "surface",
    "language",
    "lemma_candidates",
    "pos_candidates",
    "definition",
    "semantic_frame_candidates",
    "discourse_intention_candidates",
    "components",
    "ambiguities",
    "examples",
    "needs_external_evidence",
})
_SCHEMA = "zoran.gma4-teacher-proposal.v1"


@dataclass(frozen=True)
class TeacherProposal:
    surface: str
    language: str
    lemma_candidates: tuple[str, ...]
    pos_candidates: tuple[str, ...]
    definition: str
    semantic_frame_candidates: tuple[str, ...]
    discourse_intention_candidates: tuple[str, ...]
    components: tuple[str, ...]
    ambiguities: tuple[str, ...]
    examples: tuple[str, ...]
    needs_external_evidence: bool
    source: str = "GMA4_TEACHER"
    promotion: str = "FORBIDDEN"


def _tuple_of_strings(value: Any, *, field: str, max_items: int = 16) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > max_items:
        raise ValueError(f"{field} must be a bounded list")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip() or len(item) > 240:
            raise ValueError(f"invalid {field} item")
        out.append(item.strip())
    return tuple(out)


def _canonical_pos(values: tuple[str, ...]) -> tuple[str, ...]:
    """Canonicalize casing only; unknown POS labels still fail closed."""
    out: list[str] = []
    for item in values:
        canonical = _POS_BY_CASEFOLD.get(item.casefold())
        if canonical is None:
            raise ValueError("unknown POS candidate")
        out.append(canonical)
    return tuple(out)


def parse_teacher_json(raw: str) -> TeacherProposal:
    """Parse GMA4 output fail-closed.

    Markdown, prose wrappers, unknown fields, unknown frames and malformed values
    are rejected. Exact POS labels are accepted case-insensitively and normalized
    to the closed Zoran enum. A teacher proposal is evidence only and can never
    promote an object by itself.
    """
    if not isinstance(raw, str) or not raw.strip() or len(raw) > 20_000:
        raise ValueError("invalid teacher payload")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("teacher output must be pure JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("teacher payload must be an object")
    keys = frozenset(payload)
    if keys != _REQUIRED_KEYS:
        raise ValueError("teacher payload schema mismatch")
    if payload.get("schema") != _SCHEMA:
        raise ValueError("teacher schema mismatch")

    surface = payload.get("surface")
    language = payload.get("language")
    definition = payload.get("definition")
    needs_external = payload.get("needs_external_evidence")
    if not isinstance(surface, str) or not surface.strip() or len(surface) > 200:
        raise ValueError("invalid surface")
    if not isinstance(language, str) or not 2 <= len(language.strip()) <= 12:
        raise ValueError("invalid language")
    if not isinstance(definition, str) or not definition.strip() or len(definition) > 2_000:
        raise ValueError("invalid definition")
    if not isinstance(needs_external, bool):
        raise ValueError("needs_external_evidence must be boolean")

    lemmas = _tuple_of_strings(payload["lemma_candidates"], field="lemma_candidates")
    pos = _canonical_pos(_tuple_of_strings(payload["pos_candidates"], field="pos_candidates"))
    frames = _tuple_of_strings(payload["semantic_frame_candidates"], field="semantic_frame_candidates")
    intentions = _tuple_of_strings(payload["discourse_intention_candidates"], field="discourse_intention_candidates")
    components = _tuple_of_strings(payload["components"], field="components", max_items=32)
    ambiguities = _tuple_of_strings(payload["ambiguities"], field="ambiguities", max_items=16)
    examples = _tuple_of_strings(payload["examples"], field="examples", max_items=8)

    if any(item not in SEMANTIC_FRAMES for item in frames):
        raise ValueError("unknown semantic frame candidate")
    if any(item not in DISCOURSE_INTENTIONS for item in intentions):
        raise ValueError("unknown discourse intention candidate")

    return TeacherProposal(
        surface=surface.strip(),
        language=language.strip().lower(),
        lemma_candidates=lemmas,
        pos_candidates=pos,
        definition=definition.strip(),
        semantic_frame_candidates=frames,
        discourse_intention_candidates=intentions,
        components=components,
        ambiguities=ambiguities,
        examples=examples,
        needs_external_evidence=needs_external,
    )


def teacher_schema_example() -> Mapping[str, object]:
    return {
        "schema": _SCHEMA,
        "surface": "garde-toi",
        "language": "fr",
        "lemma_candidates": ["se garder de"],
        "pos_candidates": ["VERB"],
        "definition": "S'abstenir consciemment de faire quelque chose par prudence.",
        "semantic_frame_candidates": ["AVOIDANCE"],
        "discourse_intention_candidates": ["COMMAND"],
        "components": ["garde", "toi"],
        "ambiguities": ["la forme garde possède aussi des lectures indicatives hors contexte"],
        "examples": ["Garde-toi d'ouvrir."],
        "needs_external_evidence": True,
    }


def teacher_closed_enums() -> Mapping[str, Sequence[str]]:
    """Return the exact labels accepted by the fail-closed contract."""
    return {
        "pos_candidates": tuple(sorted(_ALLOWED_POS)),
        "semantic_frame_candidates": tuple(sorted(SEMANTIC_FRAMES)),
        "discourse_intention_candidates": tuple(sorted(DISCOURSE_INTENTIONS)),
    }
