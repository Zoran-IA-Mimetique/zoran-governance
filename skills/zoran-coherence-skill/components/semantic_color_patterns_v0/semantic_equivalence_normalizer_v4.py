from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Mapping, Sequence

from components.semantic_color_patterns_v0.discourse_realizer_v1 import (
    SemanticDiscourse,
    SemanticProposition,
)


_ONTOLOGY_FIELDS = {
    "intents",
    "subjects",
    "relations",
    "objects",
    "polarities",
    "modalities",
    "conditions",
    "costs",
    "restrictions",
    "temporal_steps",
    "reference_sources",
    "reference_targets",
    "units",
}
_NEGATIVE = {"n", "ne", "non", "pas", "jamais", "aucun", "aucune", "sans", "negative", "negatif"}
_POSITIVE = {"positive", "positif", "affirmatif"}
_POSSIBLE = {"peut", "peuvent", "possible", "possibles", "may", "can"}
_REQUIRED = {"doit", "doivent", "obligatoire", "must", "required"}
_RELATION_FILLERS = {"a", "au", "aux", "de", "des", "du", "d", "la", "le", "les", "l"}


def _surface(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("semantic equivalence values must be non-empty text")
    value = unicodedata.normalize("NFKD", value.replace("’", "'").replace("_", " "))
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = value.casefold().replace("'", " ").replace("-", " ")
    return " ".join(re.findall(r"[a-z0-9]+", value))


def _stem(token: str) -> str:
    for suffix in ("issements", "issement", "atrices", "ateurs", "ation", "ments", "ement", "aient", "eront", "iront", "ent", "ees", "ee", "es", "er", "ir", "re", "e", "s"):
        if token.endswith(suffix) and len(token) - len(suffix) >= 4:
            return token[: -len(suffix)]
    return token


def _phrase_key(value: str) -> str:
    return " ".join(_stem(token) for token in _surface(value).split())


def _polarity(value: str | None, relation_tokens: Sequence[str]) -> str:
    if value is not None:
        key = set(_surface(value).split())
        if key & _NEGATIVE:
            return "negative"
        if key & _POSITIVE:
            return "positive"
    return "negative" if set(relation_tokens) & _NEGATIVE else "positive"


def _modality(value: str | None, relation_tokens: Sequence[str], polarity: str) -> str | None:
    tokens = set(relation_tokens)
    if value is not None:
        tokens.update(_surface(value).split())
    if tokens & _REQUIRED:
        return "must_not" if polarity == "negative" else "required"
    if tokens & _POSSIBLE:
        return "possible"
    return None


def _intent_key(value: str) -> str:
    tokens = _phrase_key(value).split()
    if not tokens:
        raise ValueError("intent is empty")
    # The propositions carry the technical subtype.  The intent atom preserves
    # the public speech act without forcing a corpus-specific intent label.
    return tokens[0]


@dataclass(frozen=True)
class SemanticEquivalenceReceiptV4:
    decision: str
    alignment: float
    target_atom_count: int
    observed_atom_count: int
    matched_atom_count: int
    missing_atoms: tuple[str, ...]
    extra_atoms: tuple[str, ...]
    vetoes: tuple[str, ...]


class SemanticEquivalenceNormalizerV4:
    """Target-independent semantic graph normalizer.

    The constructor receives one global, depaired ontology.  It never receives
    case identifiers, target hashes or target/listener pair mappings.  Equality
    is non-compensatory: every normalized atom must be present, and any detected
    contradiction vetoes the candidate before aggregate alignment is considered.
    """

    def __init__(self, ontology: Mapping[str, Sequence[str]]) -> None:
        if not isinstance(ontology, Mapping) or set(ontology) != _ONTOLOGY_FIELDS:
            raise ValueError("listener ontology does not match the closed V4 contract")
        indexes: dict[str, dict[str, str]] = {}
        for field in sorted(_ONTOLOGY_FIELDS):
            values = ontology[field]
            if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
                raise ValueError("listener ontology values must be sequences")
            index: dict[str, str] = {}
            for raw in values:
                if not isinstance(raw, str):
                    raise ValueError("listener ontology entries must be text")
                key = _phrase_key(raw)
                previous = index.get(key)
                surface = _surface(raw)
                # Singular/plural and inflectional aliases may deliberately
                # collapse.  The lexical winner is stable and carries no
                # target-pair information.
                index[key] = surface if previous is None else min(previous, surface)
            indexes[field] = index
        self._indexes = indexes

    def _canonical(self, field: str, value: str) -> str:
        key = _phrase_key(value)
        return self._indexes[field].get(key, _surface(value))

    def _proposition(self, proposition: SemanticProposition) -> tuple[str, tuple[str, ...]]:
        subject = self._canonical("subjects", proposition.subject)
        object_ = self._canonical("objects", proposition.object)
        relation_tokens = _surface(proposition.relation).split()
        polarity = _polarity(proposition.polarity, relation_tokens)
        modality = _modality(proposition.modality, relation_tokens, polarity)
        relation_core_tokens = [
            _stem(token)
            for token in relation_tokens
            if token not in _NEGATIVE | _POSSIBLE | _REQUIRED | _RELATION_FILLERS
        ]
        relation_core = " ".join(relation_core_tokens) or "relation"
        core = f"proposition:{subject}|{relation_core}|{object_}"
        qualifiers = [f"{core}|polarity={polarity}"]
        if modality is not None:
            qualifiers.append(f"{core}|modality={modality}")
        for field, ontology_field in (
            ("condition", "conditions"),
            ("cost", "costs"),
            ("restriction", "restrictions"),
        ):
            value = getattr(proposition, field)
            if value is not None:
                qualifiers.append(f"{core}|{field}={self._canonical(ontology_field, value)}")
        return core, tuple(qualifiers)

    def atoms(self, discourse: SemanticDiscourse) -> tuple[str, ...]:
        if not isinstance(discourse, SemanticDiscourse):
            raise ValueError("semantic discourse is required")
        atoms: set[str] = {f"intent:{_intent_key(discourse.intent)}"}
        for proposition in discourse.propositions:
            core, qualifiers = self._proposition(proposition)
            atoms.add(core)
            atoms.update(qualifiers)
        atoms.update(
            f"temporal:{index}:{self._canonical('temporal_steps', value)}"
            for index, value in enumerate(discourse.temporal_order)
        )
        atoms.update(
            "reference:"
            + self._canonical("reference_sources", source)
            + "->"
            + self._canonical("reference_targets", target)
            for source, target in discourse.references
        )
        atoms.update(f"unit:{self._canonical('units', unit)}" for unit in discourse.units)
        return tuple(sorted(atoms))

    @staticmethod
    def _polarity_map(atoms: Sequence[str]) -> dict[str, str]:
        result: dict[str, str] = {}
        for atom in atoms:
            if atom.startswith("proposition:") and "|polarity=" in atom:
                core, value = atom.rsplit("|polarity=", 1)
                result[core] = value
        return result

    def compare(self, target: SemanticDiscourse, observed: SemanticDiscourse) -> SemanticEquivalenceReceiptV4:
        target_atoms = self.atoms(target)
        observed_atoms = self.atoms(observed)
        target_set, observed_set = set(target_atoms), set(observed_atoms)
        matched = target_set & observed_set
        missing = tuple(sorted(target_set - observed_set))
        extra = tuple(sorted(observed_set - target_set))

        vetoes: list[str] = []
        target_polarity = self._polarity_map(target_atoms)
        observed_polarity = self._polarity_map(observed_atoms)
        for core in sorted(target_polarity.keys() & observed_polarity.keys()):
            if target_polarity[core] != observed_polarity[core]:
                vetoes.append("POLARITY_CONTRADICTION")

        denominator = len(target_set) + len(observed_set)
        alignment = 1.0 if denominator == 0 else (2.0 * len(matched)) / denominator
        if vetoes:
            decision = "VETO"
        elif not missing and not extra:
            decision = "PASS"
        else:
            decision = "RETRY"
        return SemanticEquivalenceReceiptV4(
            decision=decision,
            alignment=alignment,
            target_atom_count=len(target_set),
            observed_atom_count=len(observed_set),
            matched_atom_count=len(matched),
            missing_atoms=missing,
            extra_atoms=extra,
            vetoes=tuple(sorted(set(vetoes))),
        )
