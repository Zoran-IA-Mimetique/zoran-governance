from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass

from tolerance_skill import Decision


COMPONENT_ID = "zoran.question-reformulation-gate"
VERSION = "18.0.0"
SHA_RE = re.compile(r"[0-9a-f]{64}")


def _norm(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value.casefold())
    return " ".join("".join(char for char in folded if not unicodedata.combining(char)).split())


def _canonical_sha(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SemanticVector:
    actors: tuple[str, ...]
    relations: tuple[str, ...]
    objects: tuple[str, ...]
    numbers: tuple[str, ...] = ()
    dates: tuple[str, ...] = ()
    negated_relations: tuple[str, ...] = ()
    modality: str = "QUESTION"

    def canonical(self) -> tuple[object, ...]:
        return (
            tuple(_norm(value) for value in self.actors),
            tuple(_norm(value) for value in self.relations),
            tuple(_norm(value) for value in self.objects),
            tuple(_norm(value) for value in self.numbers),
            tuple(_norm(value) for value in self.dates),
            tuple(_norm(value) for value in self.negated_relations),
            _norm(self.modality),
        )


@dataclass(frozen=True)
class ReformulationCandidate:
    text: str
    semantic_vector: SemanticVector


@dataclass(frozen=True)
class QuestionReformulationRequest:
    original_text: str
    original_vector: SemanticVector
    candidates: tuple[ReformulationCandidate, ...] = ()
    doubt: bool = False
    multiframe_incoherence: bool = False
    factual_intent: bool = False
    public_persons: tuple[str, ...] = ()


@dataclass(frozen=True)
class QuestionReformulationEvaluation:
    decision: Decision
    reasons: tuple[str, ...]
    selected_text: str | None
    reformulations: tuple[str, ...]
    internet_verification_required: bool
    receipt_sha256: str


class QuestionReformulationGate:
    """Resolve doubt before retrieval without allowing semantic drift.

    Two distinct surface reformulations must converge on the same structured
    meaning.  Retrieval is explicitly downstream of this receipt.
    """

    def evaluate(self, request: QuestionReformulationRequest | None) -> QuestionReformulationEvaluation:
        if not isinstance(request, QuestionReformulationRequest):
            return self._finish(Decision.RETRY, ("QUESTION_REFORMULATION_REQUEST_MISSING",), None, (), False)
        if not isinstance(request.original_text, str) or not request.original_text.strip():
            return self._finish(Decision.RETRY, ("QUESTION_TEXT_MISSING",), None, (), False)
        if not isinstance(request.original_vector, SemanticVector):
            return self._finish(Decision.RETRY, ("ORIGINAL_SEMANTIC_VECTOR_MISSING",), None, (), False)

        lookup_required = bool(request.factual_intent and request.public_persons)
        trigger = request.doubt or request.multiframe_incoherence
        if not trigger:
            return self._finish(
                Decision.PASS,
                ("QUESTION_UNAMBIGUOUS",),
                request.original_text,
                (),
                lookup_required,
            )

        candidates = tuple(request.candidates)
        if len(candidates) != 2:
            return self._finish(
                Decision.RETRY,
                ("TWO_REFORMULATIONS_REQUIRED_BEFORE_RETRIEVAL",),
                None,
                tuple(item.text for item in candidates if isinstance(item, ReformulationCandidate)),
                lookup_required,
            )
        if any(not isinstance(item, ReformulationCandidate) or not item.text.strip() for item in candidates):
            return self._finish(Decision.VETO, ("REFORMULATION_CANDIDATE_INVALID",), None, (), lookup_required)

        surfaces = tuple(_norm(item.text) for item in candidates)
        if len(set(surfaces)) != 2 or _norm(request.original_text) in set(surfaces):
            return self._finish(
                Decision.RETRY,
                ("REFORMULATIONS_NOT_INDEPENDENT_SURFACES",),
                None,
                tuple(item.text for item in candidates),
                lookup_required,
            )
        expected = request.original_vector.canonical()
        for index, item in enumerate(candidates):
            if item.semantic_vector.canonical() != expected:
                return self._finish(
                    Decision.VETO,
                    (f"SEMANTIC_ROUND_TRIP_DRIFT:{index}",),
                    None,
                    tuple(candidate.text for candidate in candidates),
                    lookup_required,
                )
            folded = _norm(item.text)
            for person in request.public_persons:
                if _norm(person) not in folded:
                    return self._finish(
                        Decision.VETO,
                        (f"PUBLIC_PERSON_DROPPED:{person}",),
                        None,
                        tuple(candidate.text for candidate in candidates),
                        lookup_required,
                    )

        return self._finish(
            Decision.PASS,
            ("TWO_REFORMULATIONS_CONVERGE", "REFORMULATION_PRECEDES_RETRIEVAL"),
            candidates[0].text,
            tuple(item.text for item in candidates),
            lookup_required,
        )

    @staticmethod
    def _finish(
        decision: Decision,
        reasons: tuple[str, ...],
        selected_text: str | None,
        reformulations: tuple[str, ...],
        lookup_required: bool,
    ) -> QuestionReformulationEvaluation:
        payload = {
            "component": COMPONENT_ID,
            "version": VERSION,
            "decision": decision.value,
            "reasons": list(reasons),
            "selected_text": selected_text,
            "reformulations": list(reformulations),
            "internet_verification_required": lookup_required,
        }
        return QuestionReformulationEvaluation(
            decision,
            reasons,
            selected_text,
            reformulations,
            lookup_required,
            _canonical_sha(payload),
        )
