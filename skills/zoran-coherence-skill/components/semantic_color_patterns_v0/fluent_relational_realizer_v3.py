from __future__ import annotations

from hashlib import sha256
import re

from components.semantic_color_patterns_v0.discourse_realizer_v1 import (
    DiscourseAttempt,
    DiscourseRealizationResult,
    SemanticDiscourse,
    SemanticProposition,
)


_REPAIR_HEADERS = (None, "Je précise.", "Je reformule.")
_INTENT_RE = re.compile(r"^Le but est d(?:e |')(.+)\.$")
_PROPOSITION_RE = re.compile(
    r"^([1-9][0-9]*)\. Entre «([^»]+)» et «([^»]+)», "
    r"la relation exprimée est «([^»]+)»\.$"
)
_REFERENCE_RE = re.compile(r"^Dans ce discours, «([^»]+)» désigne «([^»]+)»\.$")
_POLARITY_TO_SPEECH = {
    "negative": "Cette relation est négative.",
}
_MODALITY_TO_SPEECH = {
    "possible": "Elle exprime une possibilité.",
    "tendance": "Elle exprime une tendance.",
    "must not": "Elle exprime une interdiction.",
}
_SPEECH_TO_POLARITY = {value: key for key, value in _POLARITY_TO_SPEECH.items()}
_SPEECH_TO_MODALITY = {value: key for key, value in _MODALITY_TO_SPEECH.items()}
_METADATA = (
    ("condition", re.compile(r"^Elle s'applique si «([^»]+)»\.$")),
    ("cost", re.compile(r"^Son coût est «([^»]+)»\.$")),
    ("restriction", re.compile(r"^Elle reste limitée par «([^»]+)»\.$")),
)


class FluentRelationalRecomprehenderV3:
    """Rebuild semantics from the public grammatical surface only.

    Unlike V2, this parser receives no corpus-derived relation inventory.  The
    spoken relation is delimited inside a grammatical relational sentence, so
    a previously unseen relation can be reconstructed without a hidden target.
    """

    @staticmethod
    def _metadata(line: str) -> tuple[str, str] | None:
        if line in _SPEECH_TO_POLARITY:
            return "polarity", _SPEECH_TO_POLARITY[line]
        if line in _SPEECH_TO_MODALITY:
            return "modality", _SPEECH_TO_MODALITY[line]
        matches = [
            (field, match.group(1))
            for field, pattern in _METADATA
            if (match := pattern.fullmatch(line)) is not None
        ]
        if len(matches) > 1:
            raise ValueError("fluent metadata is ambiguous")
        return None if not matches else matches[0]

    def parse(self, candidate: str) -> SemanticDiscourse:
        if not isinstance(candidate, str):
            raise ValueError("candidate must be text")
        lines = [line.strip() for line in candidate.splitlines() if line.strip()]
        if lines and lines[0] in _REPAIR_HEADERS[1:]:
            lines.pop(0)

        intent_match = None if not lines else _INTENT_RE.fullmatch(lines[0])
        if intent_match is None:
            raise ValueError("fluent intent is missing")
        lines.pop(0)
        intent = intent_match.group(1)

        propositions: list[SemanticProposition] = []
        expected_index = 1
        while lines:
            match = _PROPOSITION_RE.fullmatch(lines[0])
            if match is None:
                break
            lines.pop(0)
            if int(match.group(1)) != expected_index:
                raise ValueError("fluent proposition sequence is malformed")
            values: dict[str, str] = {}
            while lines:
                metadata = self._metadata(lines[0])
                if metadata is None:
                    break
                lines.pop(0)
                field, value = metadata
                if field in values:
                    raise ValueError("fluent metadata is duplicated")
                values[field] = value
            propositions.append(SemanticProposition(
                subject=match.group(2),
                object=match.group(3),
                relation=match.group(4),
                **values,
            ))
            expected_index += 1
        if not propositions:
            raise ValueError("fluent speech contains no proposition")

        temporal: tuple[str, ...] = ()
        temporal_prefix = "L'ordre temporel est le suivant : d'abord "
        if lines and lines[0].startswith(temporal_prefix) and lines[0].endswith("."):
            body = lines.pop(0)[len(temporal_prefix) : -1]
            raw_items = body.split(", puis ")
            if any(not item.startswith("«") or not item.endswith("»") for item in raw_items):
                raise ValueError("fluent temporal sequence is malformed")
            temporal = tuple(item[1:-1] for item in raw_items)

        references: list[tuple[str, str]] = []
        while lines:
            match = _REFERENCE_RE.fullmatch(lines[0])
            if match is None:
                break
            lines.pop(0)
            references.append((match.group(1), match.group(2)))

        units: tuple[str, ...] = ()
        units_prefix = "Les unités utiles sont : "
        if lines and lines[0].startswith(units_prefix) and lines[0].endswith("."):
            raw_items = lines.pop(0)[len(units_prefix) : -1].split(" ; ")
            if any(not item.startswith("«") or not item.endswith("»") for item in raw_items):
                raise ValueError("fluent units are malformed")
            units = tuple(item[1:-1] for item in raw_items)

        if lines:
            raise ValueError("fluent speech contains unresolved material")
        return SemanticDiscourse(
            intent=intent,
            propositions=tuple(propositions),
            temporal_order=temporal,
            references=tuple(references),
            units=units,
        )


class FluentRelationalRealizerV3:
    def __init__(self, *, max_attempts: int = 3) -> None:
        if not 1 <= max_attempts <= len(_REPAIR_HEADERS):
            raise ValueError("max_attempts outside bounded repair strategies")
        self.max_attempts = max_attempts
        self._recomprehender = FluentRelationalRecomprehenderV3()

    @staticmethod
    def _intent_line(intent: str) -> str:
        elision = intent[:1].lower() in "aàâäeéèêëiîïoôöuùûüyÿh"
        return f"Le but est d'{intent}." if elision else f"Le but est de {intent}."

    def _candidate(self, discourse: SemanticDiscourse, attempt: int) -> str:
        lines: list[str] = []
        header = _REPAIR_HEADERS[attempt - 1]
        if header:
            lines.append(header)
        lines.append(self._intent_line(discourse.intent))

        for index, proposition in enumerate(discourse.propositions, 1):
            lines.append(
                f"{index}. Entre «{proposition.subject}» et «{proposition.object}», "
                f"la relation exprimée est «{proposition.relation}»."
            )
            if proposition.polarity is not None:
                try:
                    lines.append(_POLARITY_TO_SPEECH[proposition.polarity])
                except KeyError as exc:
                    raise ValueError("unknown fluent polarity") from exc
            if proposition.modality is not None:
                try:
                    lines.append(_MODALITY_TO_SPEECH[proposition.modality])
                except KeyError as exc:
                    raise ValueError("unknown fluent modality") from exc
            metadata = (
                (proposition.condition, "Elle s'applique si «{}»."),
                (proposition.cost, "Son coût est «{}»."),
                (proposition.restriction, "Elle reste limitée par «{}»."),
            )
            lines.extend(template.format(value) for value, template in metadata if value is not None)

        if discourse.temporal_order:
            sequence = ", puis ".join(f"«{item}»" for item in discourse.temporal_order)
            lines.append(f"L'ordre temporel est le suivant : d'abord {sequence}.")
        lines.extend(
            f"Dans ce discours, «{source}» désigne «{target}»."
            for source, target in discourse.references
        )
        if discourse.units:
            lines.append(
                "Les unités utiles sont : "
                + " ; ".join(f"«{item}»" for item in discourse.units)
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
                    reason="EXACT_FLUENT_RELATIONAL_ROUND_TRIP",
                )
        return DiscourseRealizationResult(
            status="MISSION_RESTART",
            speech=None,
            target_sha256=target_sha,
            attempts=tuple(attempts),
            reason="FLUENT_RELATIONAL_ALIGNMENT_INSUFFICIENT",
        )
