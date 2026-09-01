from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Iterable


_PRIMITIVE_TRIGGERS: dict[str, frozenset[str]] = {
    "MOTION": frozenset({"déplacer", "deplacer", "mouvement", "marcher", "aller", "venir"}),
    "PERCEPTION": frozenset({"percevoir", "vue", "entendre", "oreille", "écouter", "ecouter", "regarder"}),
    "COMMUNICATION": frozenset({"cri", "cris", "voix", "parler", "prononcer", "annoncer", "proclamer", "dire"}),
    "STATE": frozenset({"être", "etre", "rester", "exister", "demeurer"}),
    "POSSESSION": frozenset({"avoir", "posséder", "posseder", "détenir", "detenir"}),
    "TRANSFER": frozenset({"donner", "remettre", "offrir", "transmettre"}),
    "LOCATION": frozenset({"lieu", "situer", "position", "emplacement"}),
    "CHANGE": frozenset({"devenir", "transformer", "changer", "modifier"}),
    "AVOIDANCE": frozenset({"abstenir", "éviter", "eviter", "prudence", "empêcher", "empecher"}),
    "PROTECTION": frozenset({"préserver", "preserver", "protéger", "proteger", "garantir", "surveiller", "veiller"}),
}

_TOKEN_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿŒœ'-]+", re.UNICODE)


@dataclass(frozen=True)
class DefinitionFrameResult:
    lemma: str
    state: str
    candidates: tuple[str, ...]
    matched_primitives: dict[str, tuple[str, ...]]
    trace_sha256: str
    promotion: str = "FORBIDDEN"


def _norm(token: str) -> str:
    return token.lower().strip("'’")


def infer_definition_frames(lemma: str, definitions: Iterable[str]) -> DefinitionFrameResult:
    """Infer bounded frame candidates from already-known primitive words.

    This is a bootstrap hypothesis generator only. It never promotes semantics.
    Multiple frame families remain explicitly ambiguous.
    """
    texts = tuple(str(item) for item in definitions if str(item).strip())
    tokens = {_norm(token) for text in texts for token in _TOKEN_RE.findall(text)}
    matches: dict[str, tuple[str, ...]] = {}
    for frame, triggers in sorted(_PRIMITIVE_TRIGGERS.items()):
        hit = tuple(sorted(tokens & triggers))
        if hit:
            matches[frame] = hit

    candidates = tuple(sorted(matches))
    if not candidates:
        state = "QUARANTINED_NO_PRIMITIVE_MATCH"
    elif len(candidates) == 1:
        state = "SEMANTIC_FRAME_CANDIDATE"
    else:
        state = "AMBIGUOUS_SEMANTIC_FRAMES"

    payload = {
        "lemma": lemma,
        "definitions": texts,
        "state": state,
        "candidates": candidates,
        "matches": matches,
        "promotion": "FORBIDDEN",
    }
    trace = sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
    return DefinitionFrameResult(
        lemma=lemma,
        state=state,
        candidates=candidates,
        matched_primitives=matches,
        trace_sha256=trace,
    )
