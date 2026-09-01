from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import re
from typing import Callable, Mapping

from components.semantic_color_patterns_v0.discourse_realizer_v1 import (
    DiscourseAttempt,
    DiscourseRealizationResult,
    SemanticDiscourse,
)
from components.semantic_color_patterns_v0.semantic_equivalence_normalizer_v4 import (
    SemanticEquivalenceNormalizerV4,
)


SPEAKER_SCHEMA = "zoran.conversational-speaker.v4"
LISTENER_SCHEMA = "zoran.conversational-listener.v4"
JUDGE_SCHEMA = "zoran.french-naturalness-judge.v1"
NATURALNESS_RUBRIC = "FR-NAT-V0-20260901"

_BANNED_PUBLIC_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bintention\s*:",
        r"\bproposition\s+[0-9]+\s*:",
        r"\btemporalit[ée]\s*:",
        r"\br[ée]f[ée]rence\s+[0-9]+\s*:",
        r"\bunit[ée]\s+[0-9]+\s*:",
        r"\brelation exprim[ée]e\b",
        r"\bsemantic(?:que)?\s+(?:field|sha|json|schema)\b",
        r"\b(subject|object|relation|polarity|modality|condition|cost|restriction)\s*:",
    )
)
_RUBRIC_KEYS = (
    "syntax",
    "vocabulary",
    "information_order",
    "references",
    "speakable_rhythm",
    "concision",
)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _strict_object(raw: str, *, schema: str, keys: set[str]) -> Mapping[str, object]:
    if not isinstance(raw, str) or not raw.strip() or len(raw) > 100_000:
        raise ValueError("provider output is missing or oversized")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("provider output must be pure JSON") from exc
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError("provider output object does not match the closed contract")
    if value.get("schema") != schema:
        raise ValueError("provider output schema mismatch")
    return value


def _target_mapping(discourse: SemanticDiscourse) -> dict[str, object]:
    return {
        "intent": discourse.intent,
        "propositions": [
            {
                "s": proposition.subject,
                "r": proposition.relation,
                "o": proposition.object,
                **({"polarity": proposition.polarity} if proposition.polarity is not None else {}),
                **({"modality": proposition.modality} if proposition.modality is not None else {}),
                **({"condition": proposition.condition} if proposition.condition is not None else {}),
                **({"cost": proposition.cost} if proposition.cost is not None else {}),
                **({"restriction": proposition.restriction} if proposition.restriction is not None else {}),
            }
            for proposition in discourse.propositions
        ],
        "temporal_order": list(discourse.temporal_order),
        "references": dict(discourse.references),
        "units": list(discourse.units),
    }


@dataclass(frozen=True)
class NaturalnessReceipt:
    rubric_id: str
    scores: tuple[tuple[str, int], ...]
    failures: tuple[str, ...]
    total: int
    accepted: bool


class DeterministicFrenchSurfaceGateV4:
    """Mechanical pre-gate; it does not replace the blind French judge."""

    def evaluate(self, speech: str) -> tuple[bool, tuple[str, ...]]:
        failures: list[str] = []
        if not isinstance(speech, str) or not speech.strip() or len(speech) > 12_000:
            return False, ("SPEECH_MISSING_OR_OVERSIZED",)
        normalized = " ".join(speech.split())
        if len(normalized.split()) < 5:
            failures.append("SPEECH_TOO_SHORT")
        if "_" in normalized:
            failures.append("INTERNAL_TOKEN_EXPOSED")
        if any(pattern.search(normalized) for pattern in _BANNED_PUBLIC_PATTERNS):
            failures.append("FIELD_DUMP_OR_META_RELATION_EXPOSED")
        sentences = [item.strip() for item in re.split(r"(?<=[.!?])\s+", normalized) if item.strip()]
        if not sentences or any(item[-1:] not in ".!?" for item in sentences):
            failures.append("UNFINISHED_SENTENCE")
        if len(sentences) != len(set(sentences)):
            failures.append("MECHANICAL_REPETITION")
        if re.search(r"(?:\([^)]{30,}\)){2,}", normalized):
            failures.append("PARENTHETICAL_OVERLOAD")
        return not failures, tuple(sorted(set(failures)))


class ConversationalSpeechRealizerV4:
    """Generate, recomprehend, judge, then release speech.

    The listener receives the candidate speech only.  It never receives the
    target semantic object, its SHA, the speaker prompt, or repair feedback.
    The public candidate remains withheld until exact semantic equality and
    the frozen naturalness threshold both pass.
    """

    def __init__(
        self,
        *,
        speaker: Callable[[str], str],
        listener: Callable[[str], str],
        naturalness_judge: Callable[[str], str],
        speaker_id: str,
        listener_id: str,
        judge_id: str,
        equivalence_normalizer: SemanticEquivalenceNormalizerV4 | None = None,
        max_attempts: int = 3,
        minimum_naturalness: int = 10,
    ) -> None:
        if not 1 <= max_attempts <= 3:
            raise ValueError("max_attempts must stay inside the frozen bound")
        if minimum_naturalness != 10:
            raise ValueError("naturalness threshold is frozen at 10/12")
        identities = (speaker_id.strip(), listener_id.strip(), judge_id.strip())
        if any(not identity for identity in identities) or len(set(identities)) != 3:
            raise ValueError("speaker, listener and judge roles require distinct identities")
        self.speaker = speaker
        self.listener = listener
        self.naturalness_judge = naturalness_judge
        self.speaker_id, self.listener_id, self.judge_id = identities
        self.max_attempts = max_attempts
        self.minimum_naturalness = minimum_naturalness
        self.equivalence_normalizer = equivalence_normalizer
        self._surface_gate = DeterministicFrenchSurfaceGateV4()

    @staticmethod
    def _speaker_prompt(
        discourse: SemanticDiscourse,
        *,
        attempt: int,
        prior_differing_fields: tuple[str, ...],
        prior_surface_failures: tuple[str, ...],
    ) -> str:
        payload = {
            "role": "FRENCH_CONVERSATIONAL_SPEAKER",
            "schema": SPEAKER_SCHEMA,
            "attempt": attempt,
            "target_sha256": discourse.semantic_sha256,
            "semantic_target": _target_mapping(discourse),
            "repair": {
                "differing_fields": list(prior_differing_fields),
                "surface_failures": list(prior_surface_failures),
                "instruction": "Rewrite the whole answer naturally; do not append a correction.",
            },
            "constraints": [
                "ordinary idiomatic spoken French",
                "preserve every actor, object, negation, modality, condition, order, reference and unit",
                "no JSON, field labels, semantic commentary or meta-relational wording in speech",
                "return pure JSON with exactly schema, target_sha256, attempt and speech",
            ],
        }
        return _canonical_json(payload)

    @staticmethod
    def _listener_prompt(speech: str) -> str:
        # Deliberately contains no target object, target SHA or repair trace.
        payload = {
            "role": "FRENCH_SEMANTIC_RECOMPREHENDER",
            "schema": LISTENER_SCHEMA,
            "speech": speech,
            "output_contract": {
                "intent": "string",
                "propositions": "array of closed s/r/o objects with optional polarity, modality, condition, cost, restriction",
                "temporal_order": "array of strings",
                "references": "object mapping surface reference to resolved target",
                "units": "array of strings",
            },
            "constraints": [
                "extract only what the speech says",
                "do not repair, infer or import a hidden target",
                "return pure JSON with exactly schema and discourse",
            ],
        }
        return _canonical_json(payload)

    @staticmethod
    def _judge_prompt(speech: str) -> str:
        payload = {
            "role": "BLIND_FRENCH_NATURALNESS_JUDGE",
            "schema": JUDGE_SCHEMA,
            "rubric_id": NATURALNESS_RUBRIC,
            "speech": speech,
            "dimensions": list(_RUBRIC_KEYS),
            "scale": {"minimum": 0, "maximum": 2},
            "acceptance": "total >= 10 and no dimension equals 0",
            "constraints": [
                "judge the public French only",
                "reject field dumps, telegraphic data sheets, ambiguous pronouns and internal commentary",
                "diagnostic notes may explain a lowered non-zero score; every blocking defect must set at least one dimension to 0",
                "return pure JSON with exactly schema, rubric_id, scores and failures",
            ],
        }
        return _canonical_json(payload)

    @staticmethod
    def _parse_speaker(raw: str, *, target_sha256: str, attempt: int) -> str:
        value = _strict_object(
            raw,
            schema=SPEAKER_SCHEMA,
            keys={"schema", "target_sha256", "attempt", "speech"},
        )
        if value["target_sha256"] != target_sha256 or value["attempt"] != attempt:
            raise ValueError("speaker changed the bound target or attempt")
        speech = value["speech"]
        if not isinstance(speech, str):
            raise ValueError("speaker speech must be text")
        return speech.strip()

    @staticmethod
    def _parse_listener(raw: str) -> SemanticDiscourse:
        value = _strict_object(
            raw,
            schema=LISTENER_SCHEMA,
            keys={"schema", "discourse"},
        )
        discourse = value["discourse"]
        if not isinstance(discourse, Mapping):
            raise ValueError("listener discourse must be an object")
        return SemanticDiscourse.from_target(discourse)

    def _parse_judge(self, raw: str) -> NaturalnessReceipt:
        value = _strict_object(
            raw,
            schema=JUDGE_SCHEMA,
            keys={"schema", "rubric_id", "scores", "failures"},
        )
        if value["rubric_id"] != NATURALNESS_RUBRIC:
            raise ValueError("judge changed the frozen rubric")
        scores = value["scores"]
        failures = value["failures"]
        if not isinstance(scores, Mapping) or tuple(scores) != _RUBRIC_KEYS:
            raise ValueError("judge score dimensions changed")
        if any(not isinstance(scores[key], int) or isinstance(scores[key], bool) or not 0 <= scores[key] <= 2 for key in _RUBRIC_KEYS):
            raise ValueError("judge score is outside the closed scale")
        if not isinstance(failures, list) or any(not isinstance(item, str) or not item.strip() for item in failures):
            raise ValueError("judge failures must be text")
        ordered = tuple((key, int(scores[key])) for key in _RUBRIC_KEYS)
        total = sum(score for _, score in ordered)
        accepted = total >= self.minimum_naturalness and all(score > 0 for _, score in ordered)
        return NaturalnessReceipt(
            rubric_id=NATURALNESS_RUBRIC,
            scores=ordered,
            failures=tuple(failures),
            total=total,
            accepted=accepted,
        )

    @staticmethod
    def _alignment(target: SemanticDiscourse, observed: SemanticDiscourse | None) -> tuple[float, tuple[str, ...]]:
        target_fields = target.as_dict()
        if observed is None:
            return 0.0, tuple(target_fields)
        observed_fields = observed.as_dict()
        differing = tuple(field for field in target_fields if target_fields[field] != observed_fields[field])
        return (len(target_fields) - len(differing)) / len(target_fields), differing

    def realize(self, discourse: SemanticDiscourse) -> DiscourseRealizationResult:
        if not isinstance(discourse, SemanticDiscourse):
            raise ValueError("a semantic discourse is required")
        attempts: list[DiscourseAttempt] = []
        prior_candidates: set[str] = set()
        differing_fields: tuple[str, ...] = ()
        surface_failures: tuple[str, ...] = ()

        for attempt in range(1, self.max_attempts + 1):
            candidate: str | None = None
            observed: SemanticDiscourse | None = None
            naturalness: NaturalnessReceipt | None = None
            try:
                raw = self.speaker(self._speaker_prompt(
                    discourse,
                    attempt=attempt,
                    prior_differing_fields=differing_fields,
                    prior_surface_failures=surface_failures,
                ))
                candidate = self._parse_speaker(raw, target_sha256=discourse.semantic_sha256, attempt=attempt)
                candidate_sha = sha256(candidate.encode("utf-8")).hexdigest()
                if candidate_sha in prior_candidates:
                    raise ValueError("speaker repeated a refused candidate")
                prior_candidates.add(candidate_sha)

                surface_ok, surface_failures = self._surface_gate.evaluate(candidate)
                if surface_ok:
                    observed = self._parse_listener(self.listener(self._listener_prompt(candidate)))
                    naturalness = self._parse_judge(self.naturalness_judge(self._judge_prompt(candidate)))
                else:
                    differing_fields = ("speech_surface",)
            except (TypeError, ValueError, RuntimeError):
                candidate_sha = sha256((candidate or "").encode("utf-8")).hexdigest()

            if observed is not None and self.equivalence_normalizer is not None:
                equivalence = self.equivalence_normalizer.compare(discourse, observed)
                alignment = equivalence.alignment
                semantic_differences = (
                    *equivalence.missing_atoms,
                    *equivalence.extra_atoms,
                    *equivalence.vetoes,
                )
                exact = equivalence.decision == "PASS"
            else:
                alignment, semantic_differences = self._alignment(discourse, observed)
                exact = observed is not None and observed.semantic_sha256 == discourse.semantic_sha256
            if observed is not None:
                differing_fields = semantic_differences
            natural = naturalness is not None and naturalness.accepted
            attempts.append(DiscourseAttempt(
                attempt=attempt,
                candidate_sha256=candidate_sha,
                semantic_alignment=alignment,
                differing_fields=differing_fields if exact or differing_fields else tuple(discourse.as_dict()),
                reunderstood_sha256=None if observed is None else observed.semantic_sha256,
                decision="EMIT" if exact and natural else "RESTART_CANDIDATE",
            ))
            if exact and natural and candidate is not None:
                return DiscourseRealizationResult(
                    status="SPEECH_READY",
                    speech=candidate,
                    target_sha256=discourse.semantic_sha256,
                    attempts=tuple(attempts),
                    reason=(
                        "SEMANTIC_EQUIVALENCE_AND_BLIND_NATURALNESS"
                        if self.equivalence_normalizer is not None
                        else "EXACT_RECOMPREHENSION_AND_BLIND_NATURALNESS"
                    ),
                )
            if exact and not natural:
                differing_fields = ("naturalness",)
                surface_failures = ("BLIND_NATURALNESS_BELOW_10_OF_12",)

        return DiscourseRealizationResult(
            status="MISSION_RESTART",
            speech=None,
            target_sha256=discourse.semantic_sha256,
            attempts=tuple(attempts),
            reason="CONVERSATIONAL_SPEECH_NOT_ADMISSIBLE",
        )
