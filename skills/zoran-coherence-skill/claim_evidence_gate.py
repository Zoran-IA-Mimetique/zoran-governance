from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Mapping, Sequence

from tolerance_skill import Decision
from wikimedia_evidence import WikimediaEvidenceError, verify_wikimedia_certificate


COMPONENT_ID = "zoran.claim-evidence-gate"
# Keep the legacy receipt schema stable so v17 host-truth certificates remain
# replayable. New v18 semantics are bound by the separate reformulation and
# proposition receipts in zoran_runtime.
VERSION = "17.0.0"
LOGIC_VERSION = "18.0.0"
SHA_RE = re.compile(r"[0-9a-f]{64}")


class UnitKind(str, Enum):
    FACTUAL = "FACTUAL"
    NON_FACTUAL = "NON_FACTUAL"


class Disposition(str, Enum):
    ASSERT = "ASSERT"
    ABSTAIN = "ABSTAIN"
    NON_FACTUAL = "NON_FACTUAL"


class EvidenceRelation(str, Enum):
    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"


class EvidenceGrade(str, Enum):
    OFFICIAL_PRIMARY = "OFFICIAL_PRIMARY"
    PEER_REVIEWED = "PEER_REVIEWED"
    INDEPENDENT_REPLICATION = "INDEPENDENT_REPLICATION"
    REPUTABLE_SECONDARY = "REPUTABLE_SECONDARY"
    OTHER = "OTHER"


class SourceReliability(str, Enum):
    DEMONSTRATED = "SOURCE_DEMONTREE"
    REPUTABLE_SECONDARY = "SOURCE_SECONDAIRE_REPUTEE"
    LOW_RELIABILITY = "SOURCE_PEU_FIABLE"
    UNDEMONSTRATED = "SOURCE_NON_DEMONTREE"
    UNRELIABLE = "SOURCE_NON_FIABLE"


GRADE = {
    EvidenceGrade.OFFICIAL_PRIMARY: 5,
    EvidenceGrade.INDEPENDENT_REPLICATION: 5,
    EvidenceGrade.PEER_REVIEWED: 4,
    EvidenceGrade.REPUTABLE_SECONDARY: 2,
    EvidenceGrade.OTHER: 1,
}


@dataclass(frozen=True)
class EvidenceSpan:
    source_id: str
    source_text: str
    source_sha256: str
    exact_quote: str
    quote_sha256: str
    relation: EvidenceRelation
    grade: EvidenceGrade
    provenance_root: str
    observed_at: str
    valid_until: str | None = None
    reliability: SourceReliability = SourceReliability.UNDEMONSTRATED
    authority_receipt_sha256: str | None = None
    wikimedia_certificate: Mapping[str, object] | None = None


@dataclass(frozen=True)
class ClaimUnit:
    unit_index: int
    text: str
    kind: UnitKind
    disposition: Disposition
    claim_id: str | None = None
    evidence: tuple[EvidenceSpan, ...] = ()
    intrinsic_status: str = "RETRY"
    public_verifiable: bool = True
    time_sensitive: bool = False
    public_person_fact: bool = False


@dataclass(frozen=True)
class ClaimEvidenceRequest:
    output_text: str
    units: tuple[ClaimUnit, ...]
    as_of: str
    semantic_receipt_sha256: str
    wikimedia_checked_claim_ids: tuple[str, ...] = ()
    question_reformulation_receipt_sha256: str | None = None
    proposition_coherence_receipt_sha256: str | None = None


@dataclass(frozen=True)
class ClaimEvidenceEvaluation:
    decision: Decision
    reasons: tuple[str, ...]
    factual_units: int
    asserted_units: int
    abstained_units: int
    output_sha256: str
    receipt_sha256: str


def _sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_sha(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return _sha_text(raw)


def source_authority_receipts_sha256(request: ClaimEvidenceRequest | None) -> str:
    receipts = []
    if isinstance(request, ClaimEvidenceRequest):
        for unit in request.units:
            if isinstance(unit, ClaimUnit):
                for span in unit.evidence:
                    if isinstance(span, EvidenceSpan):
                        receipts.append({
                            "claim_id": unit.claim_id,
                            "source_id": span.source_id,
                            "source_sha256": span.source_sha256,
                            "authority_receipt_sha256": span.authority_receipt_sha256,
                            "wikimedia_certificate_sha256": (
                                span.wikimedia_certificate.get("envelope_sha256")
                                if isinstance(span.wikimedia_certificate, Mapping)
                                else None
                            ),
                        })
    receipts.sort(key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
    return _canonical_sha(receipts)


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timezone required")
    return parsed.astimezone(timezone.utc)


def segment_output(text: str) -> tuple[str, ...]:
    if not isinstance(text, str):
        return ()
    units = []
    for paragraph in text.splitlines():
        numbered = re.match(r"^([1-9][0-9]*\.\s+)(.*)$", paragraph)
        prefix = "" if numbered is None else numbered.group(1)
        body = paragraph if numbered is None else numbered.group(2)
        sentence_units = [
            match.group(0).strip()
            for match in re.finditer(r"[^.!?]+(?:[.!?]+|$)", body)
            if match.group(0).strip()
        ]
        if prefix and sentence_units:
            sentence_units[0] = prefix + sentence_units[0]
        for value in sentence_units:
            if value:
                clauses = re.split(
                    r"(?i)(?=\b(?:mais|however|cependant|pourtant|toutefois)\b)|(?<=,)(?=\s*but\b)",
                    value,
                )
                units.extend(clause.strip() for clause in clauses if clause.strip())
    return tuple(units)


def _surface_tokens(text: str) -> tuple[str, ...]:
    normalized = unicodedata.normalize("NFKD", text.casefold())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return tuple(re.findall(r"[a-z0-9]+", normalized))


STOPWORDS = frozenset({
    "a", "au", "aux", "de", "des", "du", "d", "en", "est", "la", "le", "les", "l", "un", "une",
    "and", "are", "as", "at", "by", "for", "from", "in", "is", "of", "on", "the", "to", "was", "were",
})
NEGATIONS = frozenset({"aucun", "jamais", "ne", "non", "not", "never", "no", "without", "sans"})
CERTAINTY = frozenset({"certain", "certaine", "certainement", "definitely", "certainly", "surely", "prouve", "demontre"})


def _content_tokens(text: str) -> set[str]:
    return {token for token in _surface_tokens(text) if token not in STOPWORDS}


def _looks_factual(text: str) -> bool:
    stripped = text.strip()
    if not stripped or stripped.endswith("?") or stripped.endswith(":"):
        return False
    tokens = set(_surface_tokens(stripped))
    factual_verbs = {
        "est", "sont", "etait", "etaient", "sera", "seront", "a", "ont", "avait", "existe", "mesure",
        "is", "are", "was", "were", "will", "has", "have", "exists", "measures", "contains", "contient",
        "fabrique", "fabriquee", "made",
    }
    return stripped.endswith(".") or bool(tokens & factual_verbs) or bool(re.search(r"\d", stripped))


def _registered_intrinsic_conflict(text: str) -> bool:
    tokens = set(_surface_tokens(text))
    moon = bool(tokens & {"lune", "moon"})
    cheese = bool(tokens & {"fromage", "gruyere", "cheese"})
    material = bool(tokens & {"fabrique", "fabriquee", "faite", "composee", "made", "composed"})
    return moon and cheese and material


def _quote_entails_claim(claim: str, quote: str) -> bool:
    claim_tokens = _content_tokens(claim)
    quote_tokens = _content_tokens(quote)
    if not claim_tokens or not claim_tokens <= quote_tokens:
        return False
    claim_all = set(_surface_tokens(claim)); quote_all = set(_surface_tokens(quote))
    if bool(claim_all & NEGATIONS) != bool(quote_all & NEGATIONS):
        return False
    if set(re.findall(r"\d+(?:[.,]\d+)?", claim)) - set(re.findall(r"\d+(?:[.,]\d+)?", quote)):
        return False
    return True


def _abstention_visible(text: str) -> bool:
    normalized = " ".join(text.casefold().replace("_", " ").split())
    markers = (
        "en attente de mesure", "preuve en attente", "je ne peux pas établir", "je ne peux pas etablir",
        "absence de preuve", "preuve insuffisante", "incertain", "contesté", "conteste",
        "i cannot establish", "unverified", "insufficient evidence", "uncertain", "contested",
    )
    return any(marker in normalized for marker in markers)


class ClaimEvidenceGate:
    def evaluate(self, request: ClaimEvidenceRequest | None) -> ClaimEvidenceEvaluation:
        if not isinstance(request, ClaimEvidenceRequest):
            return self._finish(Decision.RETRY, ("CLAIM_EVIDENCE_REQUEST_MISSING",), 0, 0, 0, "")
        output = request.output_text
        units = tuple(request.units)
        if not isinstance(output, str) or not output.strip():
            return self._finish(Decision.RETRY, ("OUTPUT_TEXT_MISSING",), 0, 0, 0, output if isinstance(output, str) else "")
        if not SHA_RE.fullmatch(request.semantic_receipt_sha256):
            return self._finish(Decision.RETRY, ("SEMANTIC_RECEIPT_INVALID",), 0, 0, 0, output)
        try:
            as_of = _parse_time(request.as_of)
        except Exception:
            return self._finish(Decision.RETRY, ("AS_OF_INVALID",), 0, 0, 0, output)
        segmented = segment_output(output)
        if tuple(item.text for item in units) != segmented:
            return self._finish(Decision.VETO, ("OUTPUT_UNIT_COVERAGE_MISMATCH",), 0, 0, 0, output)
        if tuple(item.unit_index for item in units) != tuple(range(len(segmented))):
            return self._finish(Decision.VETO, ("OUTPUT_UNIT_INDEX_MISMATCH",), 0, 0, 0, output)
        claim_ids = [item.claim_id for item in units if item.kind is UnitKind.FACTUAL]
        if any(not isinstance(value, str) or not value.strip() for value in claim_ids):
            return self._finish(Decision.RETRY, ("FACTUAL_CLAIM_ID_MISSING",), len(claim_ids), 0, 0, output)
        if len(claim_ids) != len(set(claim_ids)):
            return self._finish(Decision.VETO, ("FACTUAL_CLAIM_ID_DUPLICATE",), len(claim_ids), 0, 0, output)

        asserted = 0
        abstained = 0
        reasons = []
        decision = Decision.PASS
        for unit in units:
            if _registered_intrinsic_conflict(unit.text):
                return self._finish(Decision.VETO, (f"INTRINSIC_MATERIAL_COHERENCE_CONFLICT:{unit.claim_id or unit.unit_index}",), len(claim_ids), asserted, abstained, output)
            if unit.kind is UnitKind.NON_FACTUAL:
                if _looks_factual(unit.text):
                    return self._finish(Decision.VETO, (f"FACTUALITY_RELABEL_BLOCKED:{unit.unit_index}",), len(claim_ids), asserted, abstained, output)
                if unit.disposition is not Disposition.NON_FACTUAL or unit.claim_id is not None or unit.evidence:
                    return self._finish(Decision.VETO, (f"NON_FACTUAL_UNIT_CONTRACT_INVALID:{unit.unit_index}",), len(claim_ids), asserted, abstained, output)
                continue
            if unit.disposition is Disposition.NON_FACTUAL:
                return self._finish(Decision.VETO, (f"FACTUAL_UNIT_MISDISPOSED:{unit.claim_id}",), len(claim_ids), asserted, abstained, output)
            if unit.disposition is Disposition.ABSTAIN:
                abstained += 1
                if not _abstention_visible(unit.text):
                    return self._finish(Decision.VETO, (f"ABSTENTION_NOT_VISIBLE:{unit.claim_id}",), len(claim_ids), asserted, abstained, output)
                if any(span.relation is EvidenceRelation.CONTRADICTS for span in unit.evidence):
                    folded = unit.text.casefold()
                    if "contradic" not in folded and "contest" not in folded:
                        return self._finish(Decision.VETO, (f"CONTRADICTION_NOT_DISCLOSED:{unit.claim_id}",), len(claim_ids), asserted, abstained, output)
                folded_tokens = set(_surface_tokens(unit.text))
                if folded_tokens & CERTAINTY or any(marker in folded_tokens for marker in ("mais", "but", "however", "cependant", "pourtant", "toutefois")):
                    return self._finish(Decision.VETO, (f"ABSTENTION_SMUGGLES_ASSERTION:{unit.claim_id}",), len(claim_ids), asserted, abstained, output)
                continue
            asserted += 1
            if unit.intrinsic_status != "PASS":
                reasons.append(f"GYROPHARE_INTRINSIC_COHERENCE_RETRY:{unit.claim_id}")
                decision = Decision.RETRY
                continue
            source_ids = [span.source_id for span in unit.evidence]
            if len(source_ids) != len(set(source_ids)):
                return self._finish(Decision.VETO, (f"EVIDENCE_SOURCE_ID_DUPLICATE:{unit.claim_id}",), len(claim_ids), asserted, abstained, output)
            supports = []
            contradicts = []
            wikimedia_supports = []
            for span in unit.evidence:
                problem = self._validate_span(span, as_of)
                if problem:
                    reasons.append(f"{problem}:{unit.claim_id}:{span.source_id or 'UNNAMED'}")
                    decision = Decision.RETRY if decision is Decision.PASS else decision
                    continue
                if span.reliability not in {SourceReliability.DEMONSTRATED, SourceReliability.REPUTABLE_SECONDARY}:
                    reasons.append(f"GYROPHARE_{span.reliability.value}:{unit.claim_id}:{span.source_id}")
                    decision = Decision.RETRY if decision is Decision.PASS else decision
                    continue
                if not SHA_RE.fullmatch(span.authority_receipt_sha256 or ""):
                    reasons.append(f"GYROPHARE_SOURCE_AUTHORITY_UNVERIFIED:{unit.claim_id}:{span.source_id}")
                    decision = Decision.RETRY if decision is Decision.PASS else decision
                    continue
                if span.relation is EvidenceRelation.SUPPORTS and not _quote_entails_claim(unit.text, span.exact_quote):
                    reasons.append(f"CITATION_CLAIM_COHERENCE_FAILURE:{unit.claim_id}:{span.source_id}")
                    decision = Decision.RETRY if decision is Decision.PASS else decision
                    continue
                if span.relation is EvidenceRelation.SUPPORTS and isinstance(span.wikimedia_certificate, Mapping):
                    try:
                        wikimedia_supports.append(
                            verify_wikimedia_certificate(
                                span.wikimedia_certificate,
                                claim_text=unit.text,
                                span=span,
                                as_of=as_of,
                            )
                        )
                    except WikimediaEvidenceError as exc:
                        reasons.append(f"GYROPHARE_{exc}:{unit.claim_id}:{span.source_id}")
                        decision = Decision.RETRY if decision is Decision.PASS else decision
                        continue
                if unit.time_sensitive is True and span.valid_until is None:
                    reasons.append(f"TIME_SENSITIVE_EVIDENCE_EXPIRY_MISSING:{unit.claim_id}:{span.source_id}")
                    decision = Decision.RETRY if decision is Decision.PASS else decision
                    continue
                (supports if span.relation is EvidenceRelation.SUPPORTS else contradicts).append(span)
            if not supports:
                reasons.append(f"ASSERTED_CLAIM_WITHOUT_VERIFIED_SUPPORT:{unit.claim_id}")
                decision = Decision.RETRY
                continue
            if (unit.public_verifiable is not False or unit.public_person_fact) and not wikimedia_supports:
                reasons.append(f"GYROPHARE_WIKIMEDIA_FIRST_PASS_MISSING:{unit.claim_id}")
                decision = Decision.RETRY
                continue
            strongest_support = max(GRADE[item.grade] for item in supports)
            strongest_contradiction = max((GRADE[item.grade] for item in contradicts), default=0)
            if strongest_contradiction >= strongest_support:
                reasons.append(f"STRONG_CONTRADICTION_BLOCKS_ASSERTION:{unit.claim_id}")
                decision = Decision.VETO
            roots = {item.provenance_root for item in supports}
            digests = {item.source_sha256 for item in supports}
            if len(roots) > len(digests):
                reasons.append(f"INDEPENDENCE_ALIAS_DETECTED:{unit.claim_id}")
                decision = Decision.VETO
        if decision is Decision.PASS:
            reasons.append("ALL_OUTPUT_UNITS_COVERED")
        return self._finish(decision, tuple(reasons), len(claim_ids), asserted, abstained, output)

    @staticmethod
    def _validate_span(span: EvidenceSpan, as_of: datetime) -> str | None:
        if not isinstance(span.source_id, str) or not span.source_id.strip() or not isinstance(span.provenance_root, str) or not span.provenance_root.strip():
            return "EVIDENCE_IDENTITY_MISSING"
        if not isinstance(span.source_text, str) or not isinstance(span.exact_quote, str) or not span.exact_quote.strip():
            return "EVIDENCE_QUOTE_MISSING"
        if not SHA_RE.fullmatch(span.source_sha256) or span.source_sha256 != _sha_text(span.source_text):
            return "SOURCE_DIGEST_MISMATCH"
        if not SHA_RE.fullmatch(span.quote_sha256) or span.quote_sha256 != _sha_text(span.exact_quote):
            return "QUOTE_DIGEST_MISMATCH"
        if span.exact_quote not in span.source_text:
            return "EXACT_QUOTE_NOT_IN_SOURCE"
        try:
            observed = _parse_time(span.observed_at)
            if observed > as_of:
                return "EVIDENCE_FROM_FUTURE"
            if span.valid_until is not None and as_of > _parse_time(span.valid_until):
                return "EVIDENCE_EXPIRED"
        except Exception:
            return "EVIDENCE_TIME_INVALID"
        return None

    @staticmethod
    def _finish(decision: Decision, reasons: tuple[str, ...], factual: int, asserted: int, abstained: int, output: str) -> ClaimEvidenceEvaluation:
        output_sha = _sha_text(output if isinstance(output, str) else "")
        body = {
            "component": COMPONENT_ID,
            "version": VERSION,
            "decision": decision.value,
            "reasons": list(reasons),
            "factual_units": factual,
            "asserted_units": asserted,
            "abstained_units": abstained,
            "output_sha256": output_sha,
        }
        return ClaimEvidenceEvaluation(decision, reasons, factual, asserted, abstained, output_sha, _canonical_sha(body))
