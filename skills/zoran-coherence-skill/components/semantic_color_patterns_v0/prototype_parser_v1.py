from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

from components.semantic_color_patterns_v0.intention_layer import IntentionBrick

_TOKEN_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿŒœ’'-]+|[.,;:!?]", re.UNICODE)
_PUNCT = frozenset({".", ",", ";", ":", "!", "?"})

_ARTICLES = frozenset({"le", "la", "les", "un", "une", "des", "du", "de", "l", "d"})
_DETERMINERS = _ARTICLES | frozenset({
    "ce", "cet", "cette", "ces", "ma", "mon", "mes", "ta", "ton", "tes", "sa", "son", "ses",
    "notre", "nos", "votre", "vos", "leur", "leurs",
})
_PRONOUNS = frozenset({"il", "elle", "ils", "elles", "je", "tu", "nous", "vous", "on", "qui", "que", "qu", "lui"})
_CONNECTORS = frozenset({"avec", "pour", "par", "dans", "sur", "sous", "à", "au", "aux", "en", "vers", "contre", "depuis"})
_MODIFIERS = frozenset({"assez", "plus", "moins", "très", "tres", "encore", "bien", "peu", "fort", "seul", "seule"})

_SWITCHES = {
    "mais": "CONTRAST",
    "pourtant": "CONTRAST",
    "cependant": "CONTRAST",
    "or": "CONTRAST",
    "pas": "NEGATION",
    "jamais": "NEGATION",
    "aucun": "NEGATION",
    "aucune": "NEGATION",
    "sans": "NEGATION",
    "si": "CONDITION",
    "sauf": "RESTRICTION",
    "excepté": "RESTRICTION",
    "réalité": "REVISION",
}

# Closed lexical seeds are kept only for high-frequency auxiliaries/copulas and E3 compatibility.
_COPULAS = frozenset({"est", "était", "étaient", "sont", "semble", "paraît", "parait", "reste", "restait"})
_AUXILIARIES = frozenset({"a", "avait", "ont", "avaient", "est", "était", "sont", "étaient"})
_KNOWN_ACTIONS = frozenset({
    "annonçait", "nommait", "croit", "crois", "vient", "viendra", "remet", "remettra", "donne", "offre", "ouvre",
    "ferme", "fonctionne", "manque", "avance", "avançons", "revient", "redémarre", "partir",
})
_DESCRIPTION_ADJECTIVES = frozenset({
    "droit", "simple", "douces", "doux", "claire", "clair", "vieux", "silencieuse", "silencieux",
})


def known_surface_seed() -> frozenset[str]:
    """Return only the closed surface knowledge already owned by this parser.

    Morphological guesses are deliberately excluded: a form that merely looks
    verbal is still unknown. This seed contains explicit grammatical/function
    surfaces and lexical items whose bounded behavior is already encoded here.
    """
    return frozenset().union(
        _DETERMINERS,
        _PRONOUNS,
        _CONNECTORS,
        _MODIFIERS,
        _SWITCHES,
        _COPULAS,
        _AUXILIARIES,
        _KNOWN_ACTIONS,
        _DESCRIPTION_ADJECTIVES,
    )


@dataclass(frozen=True)
class ParsedSentenceV1:
    text: str
    bricks: tuple[IntentionBrick, ...]
    predicate_indices: tuple[int, ...]


def _norm(token: str) -> str:
    return token.lower().replace("’", "'").strip("'")


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.replace("’", "'"))


def split_sentences(text: str) -> list[str]:
    parts = re.findall(r"[^.!?]+[.!?]?", text, flags=re.UNICODE)
    return [part.strip() for part in parts if part.strip()]


def _looks_finite_verb(n: str) -> bool:
    # General French finite-form candidates. These are morphology gates, not target-word lists.
    if len(n) < 4:
        return False
    return n.endswith((
        "ait", "aient", "ais", "ions", "iez",           # imperfect
        "era", "eront", "erez", "erai", "eras",       # future -er
        "ira", "iront", "irez", "irai", "iras",       # future -ir
        "èrent", "erent", "èrent",                       # passé simple plural
    ))


def _looks_participle(n: str) -> bool:
    if len(n) < 4:
        return False
    return n.endswith(("é", "ée", "és", "ées", "i", "ie", "is", "ies", "u", "ue", "us", "ues"))


def _looks_gerund_or_participle(n: str) -> bool:
    return len(n) >= 5 and n.endswith("ant")


def _candidate_predicates(tokens: Sequence[str]) -> tuple[set[int], set[int]]:
    predicate: set[int] = set()
    auxiliary_used: set[int] = set()
    norms = [_norm(token) for token in tokens]

    for i, token in enumerate(tokens):
        n = norms[i]
        if token in _PUNCT or n in _SWITCHES:
            continue
        if n in _KNOWN_ACTIONS or n in _COPULAS or _looks_finite_verb(n) or _looks_gerund_or_participle(n):
            predicate.add(i)

    # Compound tense: auxiliary + following participle becomes one action predicate frame.
    for i in range(len(tokens) - 1):
        if norms[i] in _AUXILIARIES and _looks_participle(norms[i + 1]):
            predicate.add(i + 1)
            auxiliary_used.add(i)
            predicate.discard(i)

    return predicate, auxiliary_used


def _predicate_intention(token: str, *, auxiliary_used: bool) -> dict[str, float]:
    n = _norm(token)
    if auxiliary_used:
        return {}
    if n in _COPULAS:
        return {"DESCRIBE": 0.90}
    if n == "annonçait":
        # Kept from E3: here it is a descriptive relation, not a physical action.
        return {"DESCRIBE": 0.88}
    return {"ACT": 0.90}


def _semantic_family(token: str, *, index: int, predicate_indices: set[int], sentence_initial: bool) -> tuple[str, str | None]:
    n = _norm(token)
    if token in _PUNCT:
        return "UNKNOWN", None
    if n in _SWITCHES:
        return "SWITCH", _SWITCHES[n]
    if index in predicate_indices:
        return "ACTION", None
    if n in _DESCRIPTION_ADJECTIVES or n in _MODIFIERS:
        return "CONTEXT", None
    if n in _DETERMINERS or n in _PRONOUNS or n in _CONNECTORS:
        return "CONTEXT", None
    if token[:1].isupper() and not sentence_initial:
        return "ACTOR", None
    return "OBJECT", None


def _utility(token: str, family: str, *, seen: dict[str, int]) -> tuple[float, int]:
    n = _norm(token)
    seen[n] = seen.get(n, 0) + 1
    redundancy = max(0, seen[n] - 1)
    if token in _PUNCT:
        return 0.0, redundancy
    if n in _DETERMINERS or n in _PRONOUNS:
        return 0.01, redundancy
    if family == "SWITCH":
        return 0.90, redundancy
    if n in _CONNECTORS:
        return 0.08, redundancy
    if n in _MODIFIERS:
        return 0.18, redundancy
    base = 0.80 if family == "ACTION" else 0.58 if family in {"ACTOR", "OBJECT"} else 0.30
    if redundancy >= 2:
        base -= min(0.70, 0.18 * redundancy)
    return base, redundancy


def parse_sentence_v1(text: str, *, frame_id: str = "SENTENCE") -> ParsedSentenceV1:
    tokens = tokenize(text)
    predicates, auxiliary_used = _candidate_predicates(tokens)

    # Frame seed: predicate intentions are computed first. Content words do not invent an intention.
    predicate_vectors: list[dict[str, float]] = [
        _predicate_intention(tokens[i], auxiliary_used=i in auxiliary_used)
        for i in sorted(predicates)
    ]
    nonempty = [v for v in predicate_vectors if v]
    sentence_seed: dict[str, float] = {}
    if nonempty:
        for vector in nonempty:
            for key, value in vector.items():
                sentence_seed[key] = sentence_seed.get(key, 0.0) + value
        scale = max(1, len(nonempty))
        sentence_seed = {key: value / scale for key, value in sentence_seed.items()}

    seen: dict[str, int] = {}
    bricks: list[IntentionBrick] = []
    lexical_index = 0
    for i, token in enumerate(tokens):
        sentence_initial = lexical_index == 0 and token not in _PUNCT
        if token not in _PUNCT:
            lexical_index += 1
        family, switch_type = _semantic_family(token, index=i, predicate_indices=predicates, sentence_initial=sentence_initial)
        utility, redundancy = _utility(token, family, seen=seen)
        n = _norm(token)

        if switch_type == "NEGATION":
            intention = {"NEGATE": 0.95}
        elif switch_type == "CONTRAST":
            intention = {"CONTRAST": 0.90}
        elif switch_type == "CONDITION":
            intention = {"CONDITION": 0.88}
        elif switch_type == "RESTRICTION":
            intention = {"RESTRICT": 0.88}
        elif switch_type == "REVISION":
            intention = {"REVISE": 0.90}
        elif i in predicates:
            intention = _predicate_intention(token, auxiliary_used=i in auxiliary_used)
        elif n in _DESCRIPTION_ADJECTIVES:
            intention = {"DESCRIBE": 0.70}
        elif sentence_seed and family in {"ACTOR", "OBJECT"}:
            # Supportive propagation stays below the dark-brick threshold; it cannot create the macro-intention by itself.
            intention = {key: max(-0.55, min(0.55, value * 0.55)) for key, value in sentence_seed.items()}
        else:
            intention = {}

        scope = f"{frame_id}:REBUILD" if switch_type else None
        bricks.append(IntentionBrick(
            surface=token,
            semantic_family=family,
            frame_id=frame_id,
            intention_vector=intention,
            utility_delta=utility,
            redundancy_count=redundancy,
            switch_type=switch_type,
            switch_scope=scope,
        ))

    return ParsedSentenceV1(text=text, bricks=tuple(bricks), predicate_indices=tuple(sorted(predicates)))


def parse_paragraph_v1(text: str) -> tuple[ParsedSentenceV1, ...]:
    return tuple(
        parse_sentence_v1(sentence, frame_id=f"SENTENCE_{index:03d}")
        for index, sentence in enumerate(split_sentences(text), start=1)
    )


def flatten_bricks_v1(sentences: Sequence[ParsedSentenceV1]) -> tuple[IntentionBrick, ...]:
    return tuple(brick for sentence in sentences for brick in sentence.bricks)
