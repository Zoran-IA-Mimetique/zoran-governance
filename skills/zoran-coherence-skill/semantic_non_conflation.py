from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from itertools import combinations
from typing import Sequence

from tolerance_skill import Decision


COMPONENT_ID = "ZORAN_SEMANTIC_NON_CONFLATION_GATE"
VERSION = "2.0.0"
LAW_ID = "DER-NC-001"
LAW_STATUS = "ENGINEERING_DERIVATIVE_NOT_CORPUS_VERIFIED"
DERIVED_FROM = ("LAW-000", "DER-004", "DER-008", "DER-009")
DISPOSITIONS = frozenset({"EXECUTED", "PENDING", "BLOCKED", "NOT_APPLICABLE"})


def evidence_sha256(evidence: str) -> str:
    return hashlib.sha256(evidence.encode("utf-8")).hexdigest()


def _valid_sha(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _evidence_valid(evidence: object, digest: object) -> bool:
    return (
        isinstance(evidence, str)
        and bool(evidence.strip())
        and _valid_sha(digest)
        and evidence_sha256(evidence) == digest
    )


@dataclass(frozen=True)
class SemanticConcept:
    concept_id: str
    definition: str
    actor_id: str
    object_id: str
    modality: str
    required_action_ids: Sequence[str]
    forbidden_action_ids: Sequence[str]
    evidence: str
    evidence_sha256: str
    source_quote: str | None = None
    actor_text: str = ""
    object_text: str = ""
    required_action_texts: Sequence[str] = ()
    forbidden_action_texts: Sequence[str] = ()


@dataclass(frozen=True)
class SemanticDistinction:
    left_concept_id: str
    right_concept_id: str
    discriminant: str
    falsifier: str
    evidence: str
    evidence_sha256: str


@dataclass(frozen=True)
class ActionDisposition:
    action_id: str
    status: str
    grounding_concept_ids: Sequence[str]
    evidence: str
    evidence_sha256: str


@dataclass(frozen=True)
class SemanticNonConflationRequest:
    mission_sha256: str
    concepts: Sequence[SemanticConcept]
    distinctions: Sequence[SemanticDistinction]
    dispositions: Sequence[ActionDisposition]
    source_text: str = ""
    source_text_sha256: str = ""
    authorized_vector_sha256: str = ""
    regenerated_vector_sha256: str = ""


def _surface(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9]+", normalized))


def semantic_source_clauses(source_text: str) -> tuple[str, ...]:
    """Return every independently actionable source clause.

    This is deliberately conservative.  A connector creates another clause so
    that a caller cannot hide an omitted order behind a compound sentence.
    """
    if not isinstance(source_text, str):
        return ()
    parts = re.split(
        r"(?:[.!?;\n]+|\b(?:and\s+then|then|and|but|et\s+puis|puis|et|mais)\b)",
        source_text,
        flags=re.IGNORECASE,
    )
    return tuple(value.strip(" \t\r\n,") for value in parts if value.strip(" \t\r\n,"))


def semantic_vector_sha256(request: SemanticNonConflationRequest) -> str:
    payload = {
        "source_text_sha256": request.source_text_sha256,
        "concepts": [
            {
                "concept_id": item.concept_id,
                "definition": item.definition,
                "actor_id": item.actor_id,
                "actor_text": item.actor_text,
                "object_id": item.object_id,
                "object_text": item.object_text,
                "modality": item.modality,
                "required_action_ids": list(item.required_action_ids),
                "required_action_texts": list(item.required_action_texts),
                "forbidden_action_ids": list(item.forbidden_action_ids),
                "forbidden_action_texts": list(item.forbidden_action_texts),
                "source_quote": item.source_quote,
            }
            for item in request.concepts if isinstance(item, SemanticConcept)
        ],
        "dispositions": [
            {
                "action_id": item.action_id,
                "status": item.status,
                "grounding_concept_ids": list(item.grounding_concept_ids),
            }
            for item in request.dispositions if isinstance(item, ActionDisposition)
        ],
    }
    return _sha(payload)


@dataclass(frozen=True)
class SemanticNonConflationEvaluation:
    decision: Decision
    reasons: tuple[str, ...]
    checked_concepts: tuple[str, ...]
    checked_actions: tuple[str, ...]
    request_sha256: str
    receipt_sha256: str

    def as_dict(self) -> dict:
        return {
            "component": COMPONENT_ID,
            "version": VERSION,
            "law_id": LAW_ID,
            "law_status": LAW_STATUS,
            "derived_from": list(DERIVED_FROM),
            "decision": self.decision.value,
            "reasons": list(self.reasons),
            "checked_concepts": list(self.checked_concepts),
            "checked_actions": list(self.checked_actions),
            "request_sha256": self.request_sha256,
            "receipt_sha256": self.receipt_sha256,
        }


class SemanticNonConflationEngine:
    """Fail closed when distinct concepts leak obligations into each other.

    Exact action identity is intentional: a prohibition may block only the
    action it names.  It cannot block another required action by analogy,
    shared vocabulary, authority proximity, or an unproved implication.
    """

    def evaluate(self, request: SemanticNonConflationRequest | None) -> SemanticNonConflationEvaluation:
        if isinstance(request, SemanticNonConflationRequest):
            try:
                concepts = tuple(
                    SemanticConcept(
                        item.concept_id,
                        item.definition,
                        item.actor_id,
                        item.object_id,
                        item.modality,
                        tuple(item.required_action_ids),
                        tuple(item.forbidden_action_ids),
                        item.evidence,
                        item.evidence_sha256,
                        item.source_quote,
                        item.actor_text,
                        item.object_text,
                        tuple(item.required_action_texts),
                        tuple(item.forbidden_action_texts),
                    ) if isinstance(item, SemanticConcept) else item
                    for item in request.concepts
                )
                dispositions = tuple(
                    ActionDisposition(
                        item.action_id,
                        item.status,
                        tuple(item.grounding_concept_ids),
                        item.evidence,
                        item.evidence_sha256,
                    ) if isinstance(item, ActionDisposition) else item
                    for item in request.dispositions
                )
                request = SemanticNonConflationRequest(
                    request.mission_sha256,
                    concepts,
                    tuple(request.distinctions),
                    dispositions,
                    request.source_text,
                    request.source_text_sha256,
                    request.authorized_vector_sha256,
                    request.regenerated_vector_sha256,
                )
            except (TypeError, ValueError):
                request = None
        request_sha = _sha(self._request_payload(request), allow_repr=True)
        if not isinstance(request, SemanticNonConflationRequest):
            return self._finish(Decision.RETRY, ("SEMANTIC_REQUEST_MISSING",), (), (), request_sha)
        if not _valid_sha(request.mission_sha256):
            return self._finish(Decision.RETRY, ("MISSION_IDENTITY_INVALID",), (), (), request_sha)
        if not _evidence_valid(request.source_text, request.source_text_sha256):
            return self._finish(Decision.RETRY, ("SEMANTIC_SOURCE_TEXT_INVALID",), (), (), request_sha)

        source_clauses = semantic_source_clauses(request.source_text)
        quoted_clauses = tuple(
            item.source_quote.strip(" \t\r\n,")
            for item in request.concepts
            if isinstance(item, SemanticConcept) and isinstance(item.source_quote, str)
        )
        if not source_clauses or tuple(_surface(value) for value in quoted_clauses) != tuple(_surface(value) for value in source_clauses):
            return self._finish(
                Decision.RETRY,
                ("SEMANTIC_SOURCE_CLAUSE_COVERAGE_INCOMPLETE",),
                tuple(sorted(item.concept_id for item in request.concepts if isinstance(item, SemanticConcept))),
                (),
                request_sha,
            )
        vector_sha = semantic_vector_sha256(request)
        if request.authorized_vector_sha256 != vector_sha:
            return self._finish(Decision.VETO, ("AUTHORIZED_SEMANTIC_VECTOR_MISMATCH",), (), (), request_sha)
        if request.regenerated_vector_sha256 != vector_sha:
            return self._finish(Decision.VETO, ("SEMANTIC_ROUNDTRIP_DIVERGENCE",), (), (), request_sha)

        concepts = tuple(request.concepts)
        if len(concepts) < 2 or any(not isinstance(item, SemanticConcept) for item in concepts):
            return self._finish(Decision.RETRY, ("SEMANTIC_CONCEPT_COVERAGE_INCOMPLETE",), (), (), request_sha)
        concept_ids = [item.concept_id for item in concepts]
        if any(not _identifier(item) for item in concept_ids):
            return self._finish(Decision.RETRY, ("CONCEPT_ID_INVALID",), (), (), request_sha)
        if len(concept_ids) != len(set(concept_ids)):
            return self._finish(Decision.VETO, ("CONCEPT_ID_DUPLICATE",), (), (), request_sha)

        reasons: list[str] = []
        unknown = False
        veto = False
        required_by: dict[str, set[str]] = {}
        forbidden_by: dict[str, set[str]] = {}
        fingerprints: dict[tuple, str] = {}
        concept_set = set(concept_ids)

        for concept in concepts:
            required = tuple(concept.required_action_ids)
            forbidden = tuple(concept.forbidden_action_ids)
            required_texts = tuple(concept.required_action_texts)
            forbidden_texts = tuple(concept.forbidden_action_texts)
            fields = (concept.definition, concept.actor_id, concept.object_id, concept.modality)
            if any(not isinstance(value, str) or not value.strip() for value in fields):
                reasons.append(f"CONCEPT_SEMANTICS_INCOMPLETE:{concept.concept_id}")
                unknown = True
            if not _evidence_valid(concept.evidence, concept.evidence_sha256):
                reasons.append(f"CONCEPT_EVIDENCE_INVALID:{concept.concept_id}")
                unknown = True
            if not isinstance(concept.source_quote, str) or not concept.source_quote.strip() or concept.source_quote not in request.source_text:
                reasons.append(f"CONCEPT_SOURCE_QUOTE_UNBOUND:{concept.concept_id}")
                unknown = True
            else:
                quote_surface = _surface(concept.source_quote)
                if _surface(concept.definition) != quote_surface:
                    reasons.append(f"CONCEPT_DEFINITION_SOURCE_DIVERGENCE:{concept.concept_id}")
                    unknown = True
                for label, grounding in (("ACTOR", concept.actor_text), ("OBJECT", concept.object_text)):
                    if not isinstance(grounding, str) or not grounding.strip() or _surface(grounding) not in quote_surface:
                        reasons.append(f"{label}_SOURCE_GROUNDING_MISSING:{concept.concept_id}")
                        unknown = True
                if len(required_texts) != len(required) or len(forbidden_texts) != len(forbidden):
                    reasons.append(f"ACTION_SOURCE_GROUNDING_COVERAGE:{concept.concept_id}")
                    unknown = True
                for action_text in required_texts + forbidden_texts:
                    if not isinstance(action_text, str) or not action_text.strip() or _surface(action_text) not in quote_surface:
                        reasons.append(f"ACTION_SOURCE_GROUNDING_MISSING:{concept.concept_id}")
                        unknown = True
                modality_surface = quote_surface
                if concept.modality == "MUST" and not any(marker in modality_surface.split() for marker in ("must", "doit", "faut", "required", "obligatoire")):
                    reasons.append(f"MODALITY_SOURCE_GROUNDING_MISSING:{concept.concept_id}")
                    unknown = True
                if concept.modality == "MUST_NOT" and not any(marker in modality_surface for marker in ("cannot", "must not", "ne doit pas", "interdit", "forbidden")):
                    reasons.append(f"MODALITY_SOURCE_GROUNDING_MISSING:{concept.concept_id}")
                    unknown = True
            if any(not _identifier(action_id) for action_id in required + forbidden):
                reasons.append(f"ACTION_ID_INVALID:{concept.concept_id}")
                unknown = True
            if len(required) != len(set(required)) or len(forbidden) != len(set(forbidden)):
                reasons.append(f"ACTION_ID_DUPLICATE:{concept.concept_id}")
                veto = True
            overlap = set(required) & set(forbidden)
            if overlap:
                reasons.extend(f"INTRA_CONCEPT_NORM_CONFLICT:{action_id}" for action_id in sorted(overlap))
                veto = True
            fingerprint = (
                concept.definition.strip().casefold(),
                concept.actor_id.strip().casefold(),
                concept.object_id.strip().casefold(),
                concept.modality.strip().casefold(),
                tuple(sorted(required)),
                tuple(sorted(forbidden)),
            )
            if fingerprint in fingerprints:
                reasons.append(f"DISTINCT_CONCEPTS_SEMANTICALLY_IDENTICAL:{fingerprints[fingerprint]}:{concept.concept_id}")
                veto = True
            else:
                fingerprints[fingerprint] = concept.concept_id
            for action_id in required:
                required_by.setdefault(action_id, set()).add(concept.concept_id)
            for action_id in forbidden:
                forbidden_by.setdefault(action_id, set()).add(concept.concept_id)

        relations = tuple(request.distinctions)
        if any(not isinstance(item, SemanticDistinction) for item in relations):
            return self._finish(Decision.RETRY, ("DISTINCTION_SCHEMA_INVALID",), tuple(sorted(concept_set)), (), request_sha)
        expected_pairs = {frozenset(pair) for pair in combinations(concept_ids, 2)}
        seen_pairs: set[frozenset[str]] = set()
        for relation in relations:
            pair = frozenset((relation.left_concept_id, relation.right_concept_id))
            if len(pair) != 2 or not pair <= concept_set:
                reasons.append("DISTINCTION_CONCEPT_REFERENCE_INVALID")
                veto = True
                continue
            if pair in seen_pairs:
                reasons.append(f"DISTINCTION_DUPLICATE:{':'.join(sorted(pair))}")
                veto = True
            seen_pairs.add(pair)
            if (
                not isinstance(relation.discriminant, str)
                or not relation.discriminant.strip()
                or not isinstance(relation.falsifier, str)
                or not relation.falsifier.strip()
            ):
                reasons.append(f"DISTINCTION_NOT_FALSIFIABLE:{':'.join(sorted(pair))}")
                unknown = True
            if not _evidence_valid(relation.evidence, relation.evidence_sha256):
                reasons.append(f"DISTINCTION_EVIDENCE_INVALID:{':'.join(sorted(pair))}")
                unknown = True
        for pair in sorted(expected_pairs - seen_pairs, key=lambda item: tuple(sorted(item))):
            reasons.append(f"DISTINCTION_UNDECLARED:{':'.join(sorted(pair))}")
            unknown = True
        if seen_pairs - expected_pairs:
            veto = True

        conflicts = sorted(set(required_by) & set(forbidden_by))
        if conflicts:
            reasons.extend(f"ACTION_NORM_CONFLICT:{action_id}" for action_id in conflicts)
            veto = True

        dispositions = tuple(request.dispositions)
        if any(not isinstance(item, ActionDisposition) for item in dispositions):
            return self._finish(Decision.RETRY, ("ACTION_DISPOSITION_SCHEMA_INVALID",), tuple(sorted(concept_set)), (), request_sha)
        disposition_ids = [item.action_id for item in dispositions]
        if len(disposition_ids) != len(set(disposition_ids)):
            reasons.append("ACTION_DISPOSITION_DUPLICATE")
            veto = True
        action_set = set(required_by) | set(forbidden_by)
        disposition_set = set(disposition_ids)
        for action_id in sorted(action_set - disposition_set):
            reasons.append(f"ACTION_DISPOSITION_MISSING:{action_id}")
            unknown = True
        for action_id in sorted(disposition_set - action_set):
            reasons.append(f"ACTION_DISPOSITION_UNDECLARED:{action_id}")
            veto = True

        retry = False
        for item in dispositions:
            if item.action_id not in action_set:
                continue
            grounds = tuple(item.grounding_concept_ids)
            if item.status not in DISPOSITIONS:
                reasons.append(f"ACTION_DISPOSITION_STATUS_INVALID:{item.action_id}")
                unknown = True
                continue
            if not grounds or len(grounds) != len(set(grounds)) or not set(grounds) <= concept_set:
                reasons.append(f"ACTION_GROUNDING_INVALID:{item.action_id}")
                unknown = True
            if not _evidence_valid(item.evidence, item.evidence_sha256):
                reasons.append(f"ACTION_EVIDENCE_INVALID:{item.action_id}")
                unknown = True

            if item.action_id in required_by:
                if item.status == "PENDING":
                    reasons.append(f"REQUIRED_ACTION_PENDING:{item.action_id}")
                    retry = True
                    if not (required_by[item.action_id] & set(grounds)):
                        reasons.append(f"REQUIRED_ACTION_GROUNDING_MISMATCH:{item.action_id}")
                        unknown = True
                elif item.status == "NOT_APPLICABLE":
                    reasons.append(f"REQUIRED_ACTION_MARKED_NOT_APPLICABLE:{item.action_id}")
                    veto = True
                elif item.status == "BLOCKED":
                    exact_blockers = forbidden_by.get(item.action_id, set()) & set(grounds)
                    if not exact_blockers:
                        reasons.append(f"REQUIRED_ACTION_BLOCKED_BY_NONMATCHING_PROHIBITION:{item.action_id}")
                        veto = True
                elif not (required_by[item.action_id] & set(grounds)):
                    reasons.append(f"REQUIRED_ACTION_GROUNDING_MISMATCH:{item.action_id}")
                    unknown = True
            if item.action_id in forbidden_by:
                if item.status == "EXECUTED":
                    reasons.append(f"FORBIDDEN_ACTION_EXECUTED:{item.action_id}")
                    veto = True
                elif item.status == "PENDING":
                    reasons.append(f"FORBIDDEN_ACTION_ENFORCEMENT_PENDING:{item.action_id}")
                    retry = True
                elif item.status in {"BLOCKED", "NOT_APPLICABLE"} and not (forbidden_by[item.action_id] & set(grounds)):
                    reasons.append(f"FORBIDDEN_ACTION_GROUNDING_MISMATCH:{item.action_id}")
                    unknown = True

        if veto:
            decision = Decision.VETO
        elif unknown:
            decision = Decision.RETRY
        elif retry:
            decision = Decision.RETRY
        else:
            decision = Decision.PASS
            reasons.append("SEMANTIC_NON_CONFLATION_ADMISSIBLE")
        return self._finish(decision, tuple(dict.fromkeys(reasons)), tuple(sorted(concept_set)), tuple(sorted(action_set)), request_sha)

    def _request_payload(self, request: object) -> object:
        if not isinstance(request, SemanticNonConflationRequest):
            return {"request": repr(request)}
        return {
            "mission_sha256": request.mission_sha256,
            "source_text": request.source_text,
            "source_text_sha256": request.source_text_sha256,
            "authorized_vector_sha256": request.authorized_vector_sha256,
            "regenerated_vector_sha256": request.regenerated_vector_sha256,
            "concepts": [item.__dict__ if isinstance(item, SemanticConcept) else repr(item) for item in request.concepts],
            "distinctions": [item.__dict__ if isinstance(item, SemanticDistinction) else repr(item) for item in request.distinctions],
            "dispositions": [item.__dict__ if isinstance(item, ActionDisposition) else repr(item) for item in request.dispositions],
        }

    def _finish(self, decision: Decision, reasons: tuple[str, ...], concepts: tuple[str, ...], actions: tuple[str, ...], request_sha: str) -> SemanticNonConflationEvaluation:
        payload = {
            "component": COMPONENT_ID,
            "version": VERSION,
            "law_id": LAW_ID,
            "law_status": LAW_STATUS,
            "derived_from": DERIVED_FROM,
            "decision": decision.value,
            "reasons": reasons,
            "checked_concepts": concepts,
            "checked_actions": actions,
            "request_sha256": request_sha,
        }
        return SemanticNonConflationEvaluation(decision, reasons, concepts, actions, request_sha, _sha(payload))


def _identifier(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip()) and value == value.strip()


def _sha(value: object, *, allow_repr: bool = False) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=True,
            default=repr if allow_repr else None,
        ).encode("utf-8")
    ).hexdigest()
