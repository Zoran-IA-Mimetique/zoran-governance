from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


_PUNCT = frozenset({".", ",", ";", ":", "!", "?"})
_DIRECT_SWITCHES = {
    "mais": "CONTRAST",
    "pourtant": "CONTRAST",
    "cependant": "CONTRAST",
    "or": "CONTRAST",
    "sans": "NEGATION",
    "jamais": "NEGATION",
    "aucun": "NEGATION",
    "aucune": "NEGATION",
    "si": "CONDITION",
    "sauf": "RESTRICTION",
    "excepté": "RESTRICTION",
    "réalité": "REVISION",
}
_NEGATION_CUES = frozenset({"ne", "n"})
_NEGATION_COMPLEMENTS = frozenset({"pas", "plus", "rien", "guère", "guere", "personne"})


@dataclass(frozen=True)
class ResolvedSwitch:
    index: int
    switch_type: str
    scope_hint: str
    evidence: tuple[int, ...]


def _norm(token: str) -> str:
    return token.lower().replace("’", "'").strip("'")


def _bounded_left(tokens: Sequence[str], index: int, max_tokens: int = 6) -> range:
    start = max(0, index - max_tokens)
    for j in range(index - 1, start - 1, -1):
        if tokens[j] in _PUNCT:
            start = j + 1
            break
    return range(start, index)


def resolve_switches(tokens: Sequence[str]) -> dict[int, ResolvedSwitch]:
    """Resolve semantic switch tokens using bounded local evidence.

    Critical V1 rule: lexical surface alone is insufficient for ambiguous items.
    `pas` and `plus` are NEGATION only when a bounded `ne/n'` cue exists in the
    same punctuation-bounded clause. Thus `un pas allongé` is not a switch.
    """
    norms = [_norm(token) for token in tokens]
    out: dict[int, ResolvedSwitch] = {}

    for i, n in enumerate(norms):
        if n in _DIRECT_SWITCHES:
            out[i] = ResolvedSwitch(i, _DIRECT_SWITCHES[n], "CLAUSE_REBUILD", (i,))
            continue

        if n in _NEGATION_COMPLEMENTS:
            evidence = [j for j in _bounded_left(tokens, i) if norms[j] in _NEGATION_CUES]
            if evidence:
                out[i] = ResolvedSwitch(i, "NEGATION", "NEGATION_SCOPE", tuple(evidence + [i]))
            continue

        # `ne/n'` is an attention cue only when a complement is found ahead in
        # the same short clause. The complement receives the switch identity;
        # the cue remains available as evidence and is not double-counted.
        if n in _NEGATION_CUES:
            for j in range(i + 1, min(len(tokens), i + 7)):
                if tokens[j] in _PUNCT:
                    break
                if norms[j] in _NEGATION_COMPLEMENTS:
                    break

    return out
