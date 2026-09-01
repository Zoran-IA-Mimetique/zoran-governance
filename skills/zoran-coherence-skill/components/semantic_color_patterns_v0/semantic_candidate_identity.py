from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json

from components.semantic_color_patterns_v0.dual_vector_layer import SEMANTIC_FRAMES


@dataclass(frozen=True)
class SemanticCandidateIdentity:
    language: str
    surface: str
    lemma: str
    pos: str
    semantic_frame: str
    construction: str | None = None

    def __post_init__(self) -> None:
        for value, name in ((self.language, "language"), (self.surface, "surface"), (self.lemma, "lemma"), (self.pos, "pos")):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} required")
        if self.semantic_frame not in SEMANTIC_FRAMES:
            raise ValueError("unknown semantic frame")

    @property
    def canonical_payload(self) -> dict[str, str | None]:
        return {
            "language": self.language.casefold().strip(),
            "surface": self.surface.casefold().strip(),
            "lemma": self.lemma.casefold().strip(),
            "pos": self.pos.upper().strip(),
            "semantic_frame": self.semantic_frame,
            "construction": self.construction.casefold().strip() if self.construction else None,
        }

    @property
    def candidate_id(self) -> str:
        raw = json.dumps(self.canonical_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return "SC-" + sha256(raw.encode("utf-8")).hexdigest()[:24]

    @property
    def object_key(self) -> str:
        return f"sense:{self.language.casefold().strip()}:{self.candidate_id}"


def candidate_identity(
    *,
    language: str,
    surface: str,
    lemma: str,
    pos: str,
    semantic_frame: str,
    construction: str | None = None,
) -> SemanticCandidateIdentity:
    return SemanticCandidateIdentity(
        language=language,
        surface=surface,
        lemma=lemma,
        pos=pos,
        semantic_frame=semantic_frame,
        construction=construction,
    )
