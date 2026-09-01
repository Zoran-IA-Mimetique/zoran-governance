from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import re
from typing import Iterable, Sequence

from components.semantic_color_patterns_v0.discourse_realizer_v1 import (
    DiscourseAttempt,
    DiscourseRealizationResult,
    SemanticDiscourse,
    SemanticProposition,
    _canonical_text,
)


_REPAIR_HEADERS = (None, "Précision.", "Reformulation.")
_CORE_RE = re.compile(r"^([1-9][0-9]*)\. (.+)\.$")
_INTENT_RE = re.compile(r"^L'objectif est d(?:e |')(.+)\.$")
_REFERENCE_RE = re.compile(r"^(.+) désigne ici (.+)\.$")
_MODALITY_TO_SPEECH = {
    "possible": "Cette relation exprime une possibilité.",
    "tendance": "Cette relation exprime une tendance.",
    "must not": "Cette relation exprime une interdiction.",
}
_SPEECH_TO_MODALITY = {value: key for key, value in _MODALITY_TO_SPEECH.items()}


def _quote(term: str) -> str:
    return f"«{term}»"


def _natural_surface_text(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text")
    text = " ".join(value.replace("’", "'").replace("_", " ").casefold().split())
    if not text or len(text) > 720 or "\n" in value or "\r" in value:
        raise ValueError(f"{field} is outside the controlled natural surface")
    return text


def _unquote(term: str, *, field: str) -> str:
    surface = _natural_surface_text(term, field=field)
    if not surface.startswith("«") or not surface.endswith("»"):
        raise ValueError(f"{field} is not delimited")
    return _canonical_text(surface[1:-1], field=field)


class NaturalDiscourseRecomprehenderV2:
    def __init__(self, relation_inventory: Iterable[str]) -> None:
        relations = {
            _canonical_text(item, field="relation") for item in relation_inventory
        }
        if not relations:
            raise ValueError("natural recomprehension requires a relation inventory")
        self._relations = tuple(sorted(relations, key=lambda item: (-len(item), item)))

    def _split_core(self, body: str) -> tuple[str, str, str]:
        canonical = _natural_surface_text(body, field="natural_clause")
        padded = f" {canonical} "
        matches: list[tuple[int, str, str, str]] = []
        for relation in self._relations:
            marker = f" {relation} "
            start = 0
            while True:
                index = padded.find(marker, start)
                if index < 0:
                    break
                subject = padded[:index].strip()
                object_text = padded[index + len(marker) :].strip()
                if subject and object_text:
                    matches.append((len(relation), subject, relation, object_text))
                start = index + 1
        if not matches:
            raise ValueError("natural relation is unresolved")
        longest = max(item[0] for item in matches)
        winners = [item for item in matches if item[0] == longest]
        if len(winners) != 1:
            raise ValueError("natural relation is ambiguous")
        _, subject, relation, object_text = winners[0]
        return (
            _unquote(subject, field="subject"),
            relation,
            _unquote(object_text, field="object"),
        )

    def parse(self, candidate: str) -> SemanticDiscourse:
        lines = [line.strip() for line in candidate.splitlines() if line.strip()]
        if lines and lines[0] in _REPAIR_HEADERS[1:]:
            lines.pop(0)
        intent_match = None if not lines else _INTENT_RE.fullmatch(lines[0])
        if intent_match is None:
            raise ValueError("natural intent is missing")
        lines.pop(0)
        intent = intent_match.group(1)

        propositions: list[SemanticProposition] = []
        expected_index = 1
        while lines:
            match = _CORE_RE.fullmatch(lines[0])
            if match is None:
                break
            lines.pop(0)
            if int(match.group(1)) != expected_index:
                raise ValueError("natural proposition sequence is malformed")
            subject, relation, object_text = self._split_core(match.group(2))
            values: dict[str, str | None] = {
                "polarity": "negative" if relation.startswith(("ne ", "n'")) else None,
                "modality": None,
                "condition": None,
                "cost": None,
                "restriction": None,
            }
            while lines:
                line = lines[0]
                if line in _SPEECH_TO_MODALITY:
                    if values["modality"] is not None:
                        raise ValueError("natural modality is duplicated")
                    values["modality"] = _SPEECH_TO_MODALITY[line]
                elif line.startswith("Cette relation vaut si ") and line.endswith("."):
                    values["condition"] = _unquote(
                        line[len("Cette relation vaut si ") : -1], field="condition"
                    )
                elif line.startswith("Le coût associé est ") and line.endswith("."):
                    values["cost"] = _unquote(
                        line[len("Le coût associé est ") : -1], field="cost"
                    )
                elif line.startswith("La restriction est ") and line.endswith("."):
                    values["restriction"] = _unquote(
                        line[len("La restriction est ") : -1], field="restriction"
                    )
                else:
                    break
                lines.pop(0)
            # In the canonical representation, a prohibition is encoded by
            # its modality.  The French relation can start with ``ne``
            # without adding a second explicit polarity value.
            if values["modality"] == "must not":
                values["polarity"] = None
            propositions.append(SemanticProposition(
                subject=subject,
                relation=relation,
                object=object_text,
                **values,
            ))
            expected_index += 1
        if not propositions:
            raise ValueError("natural speech contains no proposition")

        temporal: tuple[str, ...] = ()
        if lines and lines[0].startswith("D'abord ") and lines[0].endswith("."):
            temporal = tuple(
                _unquote(item, field="temporal")
                for item in lines.pop(0)[len("D'abord ") : -1].split(", puis ")
            )

        references: list[tuple[str, str]] = []
        while lines:
            match = _REFERENCE_RE.fullmatch(lines[0])
            if match is None or lines[0].startswith("Les unités utilisées sont :"):
                break
            lines.pop(0)
            references.append((
                _unquote(match.group(1), field="reference_source"),
                _unquote(match.group(2), field="reference_target"),
            ))

        units: tuple[str, ...] = ()
        if lines and lines[0].startswith("Les unités utilisées sont : ") and lines[0].endswith("."):
            units = tuple(
                _unquote(item, field="unit")
                for item in lines.pop(0)[len("Les unités utilisées sont : ") : -1].split(" ; ")
            )
        if lines:
            raise ValueError("natural speech contains unresolved material")
        return SemanticDiscourse(
            intent=intent,
            propositions=tuple(propositions),
            temporal_order=temporal,
            references=tuple(references),
            units=units,
        )


class NaturalDiscourseRealizerV2:
    def __init__(
        self,
        relation_inventory: Sequence[str],
        *,
        max_attempts: int = 3,
    ) -> None:
        if not 1 <= max_attempts <= len(_REPAIR_HEADERS):
            raise ValueError("max_attempts outside bounded repair strategies")
        self.max_attempts = max_attempts
        self._recomprehender = NaturalDiscourseRecomprehenderV2(relation_inventory)

    @classmethod
    def from_discourses(cls, discourses: Sequence[SemanticDiscourse]) -> NaturalDiscourseRealizerV2:
        return cls(tuple(
            proposition.relation
            for discourse in discourses
            for proposition in discourse.propositions
        ))

    @staticmethod
    def _capitalise(text: str) -> str:
        return text[:1].upper() + text[1:]

    @staticmethod
    def _intent_line(intent: str) -> str:
        elision = intent[:1].lower() in "aàâäeéèêëiîïoôöuùûüyÿh"
        return f"L'objectif est d'{intent}." if elision else f"L'objectif est de {intent}."

    def _candidate(self, discourse: SemanticDiscourse, attempt: int) -> str:
        lines: list[str] = []
        header = _REPAIR_HEADERS[attempt - 1]
        if header:
            lines.append(header)
        lines.append(self._intent_line(discourse.intent))
        for index, proposition in enumerate(discourse.propositions, 1):
            clause = (
                f"{_quote(self._capitalise(proposition.subject))} "
                f"{proposition.relation} {_quote(proposition.object)}"
            )
            lines.append(f"{index}. {clause}.")
            if proposition.modality is not None:
                speech = _MODALITY_TO_SPEECH.get(proposition.modality)
                if speech is None:
                    raise ValueError("unknown natural modality")
                lines.append(speech)
            if proposition.condition is not None:
                lines.append(f"Cette relation vaut si {_quote(proposition.condition)}.")
            if proposition.cost is not None:
                lines.append(f"Le coût associé est {_quote(proposition.cost)}.")
            if proposition.restriction is not None:
                lines.append(f"La restriction est {_quote(proposition.restriction)}.")
        if discourse.temporal_order:
            lines.append(
                "D'abord "
                + ", puis ".join(_quote(item) for item in discourse.temporal_order)
                + "."
            )
        lines.extend(
            f"{_quote(self._capitalise(source))} désigne ici {_quote(target)}."
            for source, target in discourse.references
        )
        if discourse.units:
            lines.append(
                "Les unités utilisées sont : "
                + " ; ".join(_quote(item) for item in discourse.units)
                + "."
            )
        return "\n".join(lines)

    @staticmethod
    def _alignment(target: SemanticDiscourse, observed: SemanticDiscourse | None):
        target_fields = target.as_dict()
        if observed is None:
            return 0.0, tuple(target_fields)
        observed_fields = observed.as_dict()
        differing = tuple(
            field for field in target_fields
            if target_fields[field] != observed_fields[field]
        )
        return (len(target_fields) - len(differing)) / len(target_fields), differing

    def realize(self, discourse: SemanticDiscourse) -> DiscourseRealizationResult:
        attempts: list[DiscourseAttempt] = []
        target_sha = discourse.semantic_sha256
        for number in range(1, self.max_attempts + 1):
            candidate = self._candidate(discourse, number)
            try:
                observed = self._recomprehender.parse(candidate)
            except ValueError:
                observed = None
            alignment, differing = self._alignment(discourse, observed)
            exact = observed is not None and observed.semantic_sha256 == target_sha
            attempts.append(DiscourseAttempt(
                attempt=number,
                candidate_sha256=sha256(candidate.encode("utf-8")).hexdigest(),
                semantic_alignment=alignment,
                differing_fields=differing,
                reunderstood_sha256=None if observed is None else observed.semantic_sha256,
                decision="EMIT" if exact else "RESTART_CANDIDATE",
            ))
            if exact:
                return DiscourseRealizationResult(
                    status="SPEECH_READY",
                    speech=candidate,
                    target_sha256=target_sha,
                    attempts=tuple(attempts),
                    reason="EXACT_NATURAL_ROUND_TRIP",
                )
        return DiscourseRealizationResult(
            status="MISSION_RESTART",
            speech=None,
            target_sha256=target_sha,
            attempts=tuple(attempts),
            reason="NATURAL_ALIGNMENT_INSUFFICIENT",
        )
