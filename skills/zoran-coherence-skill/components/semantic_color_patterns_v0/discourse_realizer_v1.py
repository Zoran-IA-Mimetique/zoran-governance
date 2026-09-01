from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import re
from typing import Mapping, Sequence


_REPAIR_HEADERS = (None, "Précision contrôlée.", "Reformulation structurée.")
_PROPOSITION_RE = re.compile(
    r"^Proposition ([1-9][0-9]*) : «([^»]+)» — «([^»]+)» — «([^»]+)»(.*)\.$"
)
_METADATA_RE = re.compile(
    r" ; (polarité|modalité|condition|coût|restriction) : «([^»]+)»"
)
_TEMPORAL_RE = re.compile(r"^Temporalité : (.+)\.$")
_REFERENCE_RE = re.compile(r"^Référence ([1-9][0-9]*) : «([^»]+)» → «([^»]+)»\.$")
_UNIT_RE = re.compile(r"^Unité ([1-9][0-9]*) : «([^»]+)»\.$")
_QUOTED_SEQUENCE_RE = re.compile(r"«([^»]+)»(?: → |$)")
_METADATA_FIELDS = (
    ("polarity", "polarité"),
    ("modality", "modalité"),
    ("condition", "condition"),
    ("cost", "coût"),
    ("restriction", "restriction"),
)
_PUBLIC_TO_INTERNAL = {public: internal for internal, public in _METADATA_FIELDS}


def _canonical_text(value: object, *, field: str, max_length: int = 240) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text")
    text = " ".join(
        value.replace("’", "'").replace("_", " ").casefold().split()
    )
    if not text or len(text) > max_length:
        raise ValueError(f"{field} is outside the controlled surface")
    if any(marker in text for marker in ("«", "»", "\n", "\r")):
        raise ValueError(f"{field} contains a reserved marker")
    return text


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return sha256(payload).hexdigest()


@dataclass(frozen=True)
class SemanticProposition:
    subject: str
    relation: str
    object: str
    polarity: str | None = None
    modality: str | None = None
    condition: str | None = None
    cost: str | None = None
    restriction: str | None = None

    def __post_init__(self) -> None:
        for field in ("subject", "relation", "object"):
            object.__setattr__(
                self,
                field,
                _canonical_text(getattr(self, field), field=field),
            )
        for field, _ in _METADATA_FIELDS:
            value = getattr(self, field)
            if value is not None:
                object.__setattr__(
                    self,
                    field,
                    _canonical_text(value, field=field),
                )

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> SemanticProposition:
        allowed = {"s", "r", "o", "polarity", "modality", "condition", "cost", "restriction"}
        if not isinstance(value, Mapping) or not {"s", "r", "o"} <= set(value):
            raise ValueError("semantic proposition requires s, r and o")
        if set(value) - allowed:
            raise ValueError("semantic proposition contains unknown fields")
        return cls(
            subject=value["s"],
            relation=value["r"],
            object=value["o"],
            polarity=value.get("polarity"),
            modality=value.get("modality"),
            condition=value.get("condition"),
            cost=value.get("cost"),
            restriction=value.get("restriction"),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "subject": self.subject,
            "relation": self.relation,
            "object": self.object,
            "polarity": self.polarity,
            "modality": self.modality,
            "condition": self.condition,
            "cost": self.cost,
            "restriction": self.restriction,
        }


@dataclass(frozen=True)
class SemanticDiscourse:
    intent: str
    propositions: tuple[SemanticProposition, ...]
    temporal_order: tuple[str, ...] = ()
    references: tuple[tuple[str, str], ...] = ()
    units: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "intent", _canonical_text(self.intent, field="intent"))
        propositions = tuple(self.propositions)
        if not propositions or any(not isinstance(item, SemanticProposition) for item in propositions):
            raise ValueError("discourse requires semantic propositions")
        object.__setattr__(self, "propositions", propositions)

        temporal = tuple(
            _canonical_text(item, field="temporal_order")
            for item in self.temporal_order
        )
        object.__setattr__(self, "temporal_order", temporal)

        references: list[tuple[str, str]] = []
        seen_sources: set[str] = set()
        for source, target in self.references:
            pair = (
                _canonical_text(source, field="reference_source"),
                _canonical_text(target, field="reference_target"),
            )
            if pair[0] in seen_sources:
                raise ValueError("reference source must be unique")
            seen_sources.add(pair[0])
            references.append(pair)
        object.__setattr__(self, "references", tuple(sorted(references)))

        units = tuple(_canonical_text(item, field="unit") for item in self.units)
        if len(units) != len(set(units)):
            raise ValueError("units must be unique")
        object.__setattr__(self, "units", units)

    @classmethod
    def from_target(cls, target: Mapping[str, object]) -> SemanticDiscourse:
        allowed = {"intent", "propositions", "temporal_order", "references", "units", "features"}
        if not isinstance(target, Mapping) or set(target) - allowed:
            raise ValueError("semantic target contains unknown fields")
        raw_propositions = target.get("propositions")
        if not isinstance(raw_propositions, Sequence) or isinstance(raw_propositions, (str, bytes)):
            raise ValueError("semantic target propositions must be a sequence")
        raw_references = target.get("references", {})
        if not isinstance(raw_references, Mapping):
            raise ValueError("semantic target references must be a mapping")
        return cls(
            intent=target.get("intent"),
            propositions=tuple(
                SemanticProposition.from_mapping(item) for item in raw_propositions
            ),
            temporal_order=tuple(target.get("temporal_order", ())),
            references=tuple((str(key), str(value)) for key, value in raw_references.items()),
            units=tuple(target.get("units", ())),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "intent": self.intent,
            "propositions": [item.as_dict() for item in self.propositions],
            "temporal_order": list(self.temporal_order),
            "references": [
                {"source": source, "target": target}
                for source, target in self.references
            ],
            "units": list(self.units),
        }

    @property
    def semantic_sha256(self) -> str:
        return _canonical_sha256(self.as_dict())


@dataclass(frozen=True)
class DiscourseAttempt:
    attempt: int
    candidate_sha256: str
    semantic_alignment: float
    differing_fields: tuple[str, ...]
    reunderstood_sha256: str | None
    decision: str


@dataclass(frozen=True)
class DiscourseRealizationResult:
    status: str
    speech: str | None
    target_sha256: str
    attempts: tuple[DiscourseAttempt, ...]
    reason: str


class ControlledDiscourseRecomprehender:
    @staticmethod
    def _parse_proposition(line: str, expected_index: int) -> SemanticProposition:
        match = _PROPOSITION_RE.fullmatch(line)
        if match is None or int(match.group(1)) != expected_index:
            raise ValueError("proposition sequence is malformed")
        metadata_text = match.group(5)
        metadata: dict[str, str] = {}
        position = 0
        for item in _METADATA_RE.finditer(metadata_text):
            if item.start() != position:
                raise ValueError("proposition metadata is malformed")
            field = _PUBLIC_TO_INTERNAL[item.group(1)]
            if field in metadata:
                raise ValueError("proposition metadata is duplicated")
            metadata[field] = item.group(2)
            position = item.end()
        if position != len(metadata_text):
            raise ValueError("proposition metadata is unresolved")
        return SemanticProposition(
            subject=match.group(2),
            relation=match.group(3),
            object=match.group(4),
            **metadata,
        )

    @staticmethod
    def _parse_temporal(line: str) -> tuple[str, ...]:
        match = _TEMPORAL_RE.fullmatch(line)
        if match is None:
            raise ValueError("temporal line is malformed")
        body = match.group(1)
        values = tuple(item.group(1) for item in _QUOTED_SEQUENCE_RE.finditer(body))
        rebuilt = " → ".join(f"«{item}»" for item in values)
        if not values or rebuilt != body:
            raise ValueError("temporal sequence is unresolved")
        return values

    def parse(self, candidate: str) -> SemanticDiscourse:
        if not isinstance(candidate, str):
            raise ValueError("candidate must be text")
        lines = [line.strip() for line in candidate.splitlines() if line.strip()]
        if lines and lines[0] in _REPAIR_HEADERS[1:]:
            lines.pop(0)
        if not lines or not lines[0].startswith("Intention : «") or not lines[0].endswith("»."):
            raise ValueError("intent line is missing")
        intent = lines.pop(0)[len("Intention : «") : -2]

        propositions: list[SemanticProposition] = []
        while lines and lines[0].startswith("Proposition "):
            propositions.append(self._parse_proposition(lines.pop(0), len(propositions) + 1))
        if not propositions:
            raise ValueError("candidate contains no propositions")

        temporal: tuple[str, ...] = ()
        if lines and lines[0].startswith("Temporalité :"):
            temporal = self._parse_temporal(lines.pop(0))

        references: list[tuple[str, str]] = []
        while lines and lines[0].startswith("Référence "):
            match = _REFERENCE_RE.fullmatch(lines.pop(0))
            if match is None or int(match.group(1)) != len(references) + 1:
                raise ValueError("reference sequence is malformed")
            references.append((match.group(2), match.group(3)))

        units: list[str] = []
        while lines and lines[0].startswith("Unité "):
            match = _UNIT_RE.fullmatch(lines.pop(0))
            if match is None or int(match.group(1)) != len(units) + 1:
                raise ValueError("unit sequence is malformed")
            units.append(match.group(2))

        if lines:
            raise ValueError("candidate contains unresolved speech")
        return SemanticDiscourse(
            intent=intent,
            propositions=tuple(propositions),
            temporal_order=temporal,
            references=tuple(references),
            units=tuple(units),
        )


class ControlledDiscourseRealizerV1:
    def __init__(self, *, max_attempts: int = 3) -> None:
        if not 1 <= max_attempts <= len(_REPAIR_HEADERS):
            raise ValueError("max_attempts outside bounded repair strategies")
        self.max_attempts = max_attempts
        self._recomprehender = ControlledDiscourseRecomprehender()

    @staticmethod
    def _proposition_line(item: SemanticProposition, index: int) -> str:
        line = (
            f"Proposition {index} : «{item.subject}» — «{item.relation}» — «{item.object}»"
        )
        for field, public_name in _METADATA_FIELDS:
            value = getattr(item, field)
            if value is not None:
                line += f" ; {public_name} : «{value}»"
        return line + "."

    def _candidate(self, discourse: SemanticDiscourse, attempt: int) -> str:
        lines: list[str] = []
        header = _REPAIR_HEADERS[attempt - 1]
        if header is not None:
            lines.append(header)
        lines.append(f"Intention : «{discourse.intent}».")
        lines.extend(
            self._proposition_line(item, index)
            for index, item in enumerate(discourse.propositions, 1)
        )
        if discourse.temporal_order:
            temporal = " → ".join(f"«{item}»" for item in discourse.temporal_order)
            lines.append(f"Temporalité : {temporal}.")
        lines.extend(
            f"Référence {index} : «{source}» → «{target}»."
            for index, (source, target) in enumerate(discourse.references, 1)
        )
        lines.extend(
            f"Unité {index} : «{unit}»."
            for index, unit in enumerate(discourse.units, 1)
        )
        return "\n".join(lines)

    @staticmethod
    def _alignment(
        target: SemanticDiscourse,
        observed: SemanticDiscourse | None,
    ) -> tuple[float, tuple[str, ...]]:
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
        if not isinstance(discourse, SemanticDiscourse):
            raise ValueError("a semantic discourse is required")
        attempts: list[DiscourseAttempt] = []
        target_sha = discourse.semantic_sha256
        for attempt_number in range(1, self.max_attempts + 1):
            candidate = self._candidate(discourse, attempt_number)
            try:
                observed = self._recomprehender.parse(candidate)
            except ValueError:
                observed = None
            alignment, differing = self._alignment(discourse, observed)
            exact = observed is not None and observed.semantic_sha256 == target_sha
            attempts.append(DiscourseAttempt(
                attempt=attempt_number,
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
                    reason="EXACT_DISCOURSE_ROUND_TRIP",
                )
        return DiscourseRealizationResult(
            status="MISSION_RESTART",
            speech=None,
            target_sha256=target_sha,
            attempts=tuple(attempts),
            reason="DISCOURSE_ALIGNMENT_INSUFFICIENT",
        )
