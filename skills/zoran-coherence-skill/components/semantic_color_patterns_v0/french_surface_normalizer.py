from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

_RAW_TOKEN_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿŒœ’'-]+|[.,;:!?]", re.UNICODE)
_PUNCT = frozenset({".", ",", ";", ":", "!", "?"})
_APOSTROPHE_CLITICS = frozenset({"l", "d", "j", "t", "m", "s", "n", "c", "qu"})
_HYPHEN_CLITICS = frozenset({
    "je", "tu", "il", "elle", "on", "nous", "vous", "ils", "elles",
    "moi", "toi", "le", "la", "les", "lui", "leur", "en", "y", "t",
})


@dataclass(frozen=True)
class SurfaceToken:
    surface: str
    normalized: str
    origin: str
    kind: str


def _norm(value: str) -> str:
    return value.lower().replace("’", "'").strip("'")


def _split_apostrophe(token: str) -> list[SurfaceToken]:
    canonical = token.replace("’", "'")
    if "'" not in canonical:
        return [SurfaceToken(token, _norm(token), token, "CORE")]
    prefix, remainder = canonical.split("'", 1)
    if _norm(prefix) in _APOSTROPHE_CLITICS and remainder:
        return [
            SurfaceToken(prefix + "'", _norm(prefix), token, "CLITIC"),
            SurfaceToken(remainder, _norm(remainder), token, "CORE"),
        ]
    return [SurfaceToken(token, _norm(token), token, "CORE")]


def _split_hyphen(token: SurfaceToken) -> list[SurfaceToken]:
    if token.kind != "CORE" or "-" not in token.surface:
        return [token]
    parts = token.surface.split("-")
    if len(parts) < 2:
        return [token]

    # Split only grammatical enclitics/inversion chains. Lexical compounds such
    # as `porte-cigares` remain one semantic surface candidate.
    suffixes = [_norm(part) for part in parts[1:]]
    if not suffixes or any(part not in _HYPHEN_CLITICS for part in suffixes):
        return [token]

    out = [SurfaceToken(parts[0], _norm(parts[0]), token.origin, "CORE")]
    for part in parts[1:]:
        kind = "LINKER" if _norm(part) == "t" else "CLITIC"
        out.append(SurfaceToken(part, _norm(part), token.origin, kind))
    return out


def normalize_french_surface(text: str) -> tuple[SurfaceToken, ...]:
    out: list[SurfaceToken] = []
    for raw in _RAW_TOKEN_RE.findall(text):
        if raw in _PUNCT:
            out.append(SurfaceToken(raw, raw, raw, "PUNCT"))
            continue
        for first in _split_apostrophe(raw):
            out.extend(_split_hyphen(first))
    return tuple(out)


def core_surfaces(tokens: Iterable[SurfaceToken]) -> tuple[str, ...]:
    return tuple(item.normalized for item in tokens if item.kind == "CORE")
