from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass

from tolerance_skill import Decision


COMPONENT_ID = "zoran.proposition-coherence-gate"
VERSION = "18.0.0"
SHA_RE = re.compile(r"[0-9a-f]{64}")


def _norm(value: str | None) -> str | None:
    if value is None:
        return None
    folded = unicodedata.normalize("NFKD", value.casefold())
    return " ".join("".join(char for char in folded if not unicodedata.combining(char)).split())


def _canonical_sha(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Proposition:
    claim_id: str
    subject: str
    relation: str
    object: str
    polarity: str = "POSITIVE"
    number: str | None = None
    unit: str | None = None
    date: str | None = None
    modality: str = "ASSERTED"
    evidence_id: str | None = None
    exact_quote: str = ""
    public_person_fact: bool = False

    def semantic_key(self) -> tuple[str | None, ...]:
        return (
            _norm(self.subject),
            _norm(self.relation),
            _norm(self.object),
            _norm(self.polarity),
            _norm(self.number),
            _norm(self.unit),
            _norm(self.date),
            _norm(self.modality),
        )


@dataclass(frozen=True)
class PropositionCoherenceRequest:
    question_receipt_sha256: str
    expected_subjects: tuple[str, ...]
    expected_relations: tuple[str, ...]
    claims: tuple[Proposition, ...]
    evidence: tuple[Proposition, ...]
    internet_receipts: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class PropositionCoherenceEvaluation:
    decision: Decision
    reasons: tuple[str, ...]
    checked_claims: int
    receipt_sha256: str


class PropositionCoherenceGate:
    """Bind each answer proposition to the matching local evidence proposition."""

    def evaluate(self, request: PropositionCoherenceRequest | None) -> PropositionCoherenceEvaluation:
        if not isinstance(request, PropositionCoherenceRequest):
            return self._finish(Decision.RETRY, ("PROPOSITION_REQUEST_MISSING",), 0)
        if not SHA_RE.fullmatch(request.question_receipt_sha256):
            return self._finish(Decision.RETRY, ("QUESTION_RECEIPT_INVALID",), 0)
        if not request.expected_subjects or not request.expected_relations:
            return self._finish(Decision.RETRY, ("QUESTION_CONTRACT_INCOMPLETE",), 0)
        if not request.claims:
            return self._finish(Decision.RETRY, ("CLAIM_PROPOSITIONS_MISSING",), 0)

        expected_subjects = {_norm(item) for item in request.expected_subjects}
        expected_relations = {_norm(item) for item in request.expected_relations}
        receipts = {_norm(subject): digest for subject, digest in request.internet_receipts}
        if len(receipts) != len(request.internet_receipts):
            return self._finish(Decision.VETO, ("INTERNET_RECEIPT_SUBJECT_DUPLICATE",), 0)

        evidence_by_id: dict[str, Proposition] = {}
        for item in request.evidence:
            if not item.evidence_id or item.evidence_id in evidence_by_id:
                return self._finish(Decision.VETO, ("EVIDENCE_PROPOSITION_ID_INVALID",), 0)
            if not item.exact_quote.strip():
                return self._finish(Decision.RETRY, (f"LOCAL_EVIDENCE_QUOTE_MISSING:{item.evidence_id}",), 0)
            evidence_by_id[item.evidence_id] = item

        checked = 0
        for claim in request.claims:
            if not claim.claim_id or not claim.subject.strip() or not claim.relation.strip() or not claim.object.strip():
                return self._finish(Decision.VETO, ("CLAIM_PROPOSITION_INVALID",), checked)
            if _norm(claim.subject) not in expected_subjects:
                return self._finish(Decision.VETO, (f"QUESTION_SUBJECT_MISMATCH:{claim.claim_id}",), checked)
            if _norm(claim.relation) not in expected_relations:
                return self._finish(Decision.VETO, (f"QUESTION_RELATION_MISMATCH:{claim.claim_id}",), checked)
            if not claim.evidence_id or claim.evidence_id not in evidence_by_id:
                return self._finish(Decision.RETRY, (f"LOCAL_EVIDENCE_MISSING:{claim.claim_id}",), checked)
            evidence = evidence_by_id[claim.evidence_id]
            if claim.semantic_key() != evidence.semantic_key():
                return self._finish(
                    Decision.VETO,
                    (f"SUBJECT_RELATION_OBJECT_BINDING_FAILURE:{claim.claim_id}",),
                    checked,
                )
            if claim.public_person_fact:
                digest = receipts.get(_norm(claim.subject))
                if not SHA_RE.fullmatch(digest or ""):
                    return self._finish(
                        Decision.RETRY,
                        (f"PUBLIC_PERSON_INTERNET_VERIFICATION_REQUIRED:{claim.claim_id}",),
                        checked,
                    )
            checked += 1

        return self._finish(Decision.PASS, ("ALL_PROPOSITIONS_LOCALLY_ENTAILED",), checked)

    @staticmethod
    def _finish(decision: Decision, reasons: tuple[str, ...], checked: int) -> PropositionCoherenceEvaluation:
        payload = {
            "component": COMPONENT_ID,
            "version": VERSION,
            "decision": decision.value,
            "reasons": list(reasons),
            "checked_claims": checked,
        }
        return PropositionCoherenceEvaluation(decision, reasons, checked, _canonical_sha(payload))
