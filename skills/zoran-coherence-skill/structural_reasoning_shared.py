from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from typing import Iterable


COMPONENT_ID = "zoran.structural-reasoning-gate"
VERSION = "21.0.1"


class ProofStatus(str, Enum):
    PROVED = "PROVED"
    DISPROVED = "DISPROVED"
    UNRESOLVED = "UNRESOLVED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True)
class StructuralProofRequest:
    context: str
    question: str
    answer: str


@dataclass(frozen=True)
class StructuralProof:
    status: ProofStatus
    family: str
    reason: str
    evidence_quotes: tuple[str, ...]
    calculation_trace: tuple[str, ...]
    receipt_sha256: str

    @property
    def applicable(self) -> bool:
        return self.status is not ProofStatus.NOT_APPLICABLE


_STOPWORDS = frozenset({
    "a", "about", "according", "after", "all", "an", "and", "answer", "are", "as", "at",
    "based", "basing", "be", "been", "before", "between", "both", "by", "calculate", "can", "could",
    "did", "do", "does", "either", "end", "following", "for", "from", "given", "has", "have", "how", "if", "in", "information",
    "is", "it", "its", "judgment", "many", "much", "of", "off", "on", "or", "plainly", "provided",
    "neither", "not", "question", "relying", "round", "should", "statement", "than", "that", "the", "their", "these", "this", "to", "units",
    "using", "was", "were", "what", "when", "where", "which", "who", "with", "year", "yes", "you", "no",
})
_NEGATIONS = frozenset({"no", "not", "never", "neither", "without", "cannot", "cant", "wont", "lack", "lacked"})
_UNCERTAINTY = frozenset({"may", "might", "possibly", "unclear", "uncertain", "unknown", "insufficient"})
_AUXILIARIES = frozenset({"are", "can", "could", "did", "do", "does", "has", "have", "is", "was", "were", "will", "would"})
_NUMBER_RE = re.compile(r"(?<![A-Za-z0-9])(?P<open>\()?\s*(?P<currency>[$€£])?\s*(?P<sign>[-+])?\s*(?P<number>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*(?P<percent>%)?\s*(?P<close>\))?")
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_HISTORICAL_YEAR_RE = re.compile(r"\b(?:1\d{3}|20\d{2})\b")


def _norm(value: str) -> str:
    value = value.translate(str.maketrans({"α": " alpha ", "β": " beta ", "γ": " gamma ", "δ": " delta "}))
    folded = unicodedata.normalize("NFKD", value.casefold())
    folded = "".join(char for char in folded if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9]+", folded))


def _tokens(value: str) -> tuple[str, ...]:
    normalized = _norm(value)
    return tuple(normalized.split()) if normalized else ()


def _stem(token: str) -> str:
    aliases = {
        "adversely": "adverse", "affected": "affect", "affects": "affect", "applicant": "application", "applicants": "application", "attempt": "try",
        "attempted": "try", "chinese": "china", "close": "shut", "closed": "shut", "ensure": "sure",
        "conclusions": "conclusion", "decreased": "decrease", "decreasing": "decrease",
        "enhanced": "enhance", "enhances": "enhance", "enhancing": "enhance",
        "increased": "increase", "increasing": "increase", "outcomes": "outcome",
        "percentages": "percent", "place": "set", "placed": "set", "statins": "statin", "weren": "not", "won": "win",
    }
    if token in aliases:
        return aliases[token]
    for suffix, replacement, minimum in (
        ("ization", "ize", 5), ("ational", "ate", 5), ("ments", "", 5), ("ment", "", 5),
        ("ingly", "", 5), ("edly", "", 5), ("ing", "", 5), ("ied", "y", 4),
        ("ies", "y", 4), ("ed", "", 4), ("es", "", 4), ("s", "", 3),
    ):
        if token.endswith(suffix) and len(token) - len(suffix) >= minimum:
            return token[:-len(suffix)] + replacement
    return token


def _content(value: str) -> set[str]:
    result: set[str] = set()
    for token in _tokens(value):
        if token in _STOPWORDS or len(token) <= 1:
            continue
        stem = _stem(token)
        result.add(stem)
        if stem in {"affect", "influenc", "impact", "effect"}:
            result.add("impact")
        if stem in {"increase", "enhance", "strengthen", "augment"}:
            result.update(("increase", "impact"))
        if stem in {"decrease", "reduce", "lower", "decline"}:
            result.update(("decrease", "impact"))
        if stem in {"outcome", "prognosi"}:
            result.add("outcome")
    return result


def _sentences(value: str) -> tuple[str, ...]:
    cleaned = " ".join(value.split())
    if not cleaned:
        return ()
    return tuple(part.strip() for part in re.split(r"(?<=[.!?])\s+|\s*[;|]\s*", cleaned) if part.strip())


@dataclass(frozen=True)
class _Number:
    value: float
    raw: str
    start: int
    end: int
    percent: bool


def _numbers(value: str) -> tuple[_Number, ...]:
    result: list[_Number] = []
    for match in _NUMBER_RE.finditer(value):
        number = float(match.group("number").replace(",", ""))
        negative = match.group("sign") == "-" or (match.group("open") and match.group("close"))
        result.append(_Number(-number if negative else number, match.group(0).strip(), match.start(), match.end(), bool(match.group("percent"))))
    return tuple(result)


def _answer_scalar(answer: str) -> _Number | None:
    values = _numbers(answer)
    if not values:
        return None
    unique = {round(item.value, 12) for item in values}
    return values[0] if len(unique) == 1 else None


def _close(actual: float, expected: float, raw_answer: str) -> bool:
    decimals = 0
    if "." in raw_answer:
        decimals = len(raw_answer.split(".", 1)[1].rstrip("%) "))
    tolerance = max(1e-9, 0.5 * (10 ** -decimals))
    return math.isclose(actual, expected, rel_tol=1e-9, abs_tol=tolerance)


def _closed_numeric_trace(answer: str, expected: float, operands: Iterable[float] = ()) -> bool:
    values = _numbers(answer)
    if not values:
        return False
    allowed = (expected, *tuple(operands))
    has_result = any(_close(item.value, expected, item.raw) for item in values)
    trace_closed = all(any(_close(item.value, value, item.raw) for value in allowed) for item in values)
    unique_values = {round(item.value, 12) for item in values}
    if len(unique_values) > 1:
        trace_closed = trace_closed and all(
            any(_close(item.value, operand, item.raw) for item in values)
            for operand in operands
        )
    return has_result and trace_closed


def _sha(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _finish(
    status: ProofStatus,
    family: str,
    reason: str,
    evidence: Iterable[str] = (),
    trace: Iterable[str] = (),
) -> StructuralProof:
    evidence_tuple = tuple(evidence)
    trace_tuple = tuple(trace)
    payload = {
        "component": COMPONENT_ID,
        "version": VERSION,
        "status": status.value,
        "family": family,
        "reason": reason,
        "evidence_sha256": [_sha(item) for item in evidence_tuple],
        "calculation_trace": list(trace_tuple),
    }
    return StructuralProof(status, family, reason, evidence_tuple, trace_tuple, _sha(payload))


def _question_is_yes_no(question: str) -> bool:
    tokens = _tokens(question)
    return bool(tokens and tokens[0] in _AUXILIARIES)


def _explicit_answer_polarity(answer: str) -> bool | None:
    tokens = _tokens(answer)
    if not tokens:
        return None
    if tokens[0] in {"yes", "true"}:
        return True
    if tokens[0] in {"no", "false"}:
        return False
    return None


def _negated(value: str) -> bool:
    tokens = set(_tokens(value))
    normalized = _norm(value)
    return bool(
        tokens & _NEGATIONS
        or "no significant" in normalized
        or "failed to" in normalized
        or any(contraction in normalized for contraction in ("doesn t", "won t", "isn t", "weren t"))
    )


def _anchor_role_contradiction(context: str, claim: str) -> tuple[str, str, str] | None:
    """Detect a role swap between repeated symbolic/numeric anchors.

    Bag-of-words coverage cannot distinguish "G2 apoptosis / G1 arrest"
    from "G1 apoptosis / G2 arrest".  This check only decides when at least
    two anchors have distinct local roles in the supplied context.
    """
    claim_tokens = tuple(_stem(token) for token in _tokens(claim))
    anchors = tuple(dict.fromkeys(token for token in claim_tokens if any(char.isdigit() for char in token)))
    if len(anchors) < 2:
        return None
    associations: dict[str, set[str]] = {}
    evidence_by_anchor: dict[str, tuple[str, ...]] = {}
    for anchor in anchors:
        evidence = tuple(sentence for sentence in _sentences(context) if anchor in {_stem(token) for token in _tokens(sentence)})
        if not evidence:
            return None
        evidence_by_anchor[anchor] = evidence
        associations[anchor] = set().union(*(_content(sentence) for sentence in evidence))
    claim_terms = _content(claim)
    discriminating = {
        term for term in claim_terms
        if not any(char.isdigit() for char in term)
        and len(term) >= 3
        and sum(term in associations[anchor] for anchor in anchors) == 1
    }
    if not discriminating:
        return None
    for anchor in anchors:
        anchor_positions = [index for index, token in enumerate(claim_tokens) if token == anchor]
        candidates = [
            (min(abs(index - anchor_index) for anchor_index in anchor_positions), token)
            for index, token in enumerate(claim_tokens)
            if token in discriminating
        ]
        if not candidates:
            continue
        _, nearest_role = min(candidates)
        if nearest_role not in associations[anchor]:
            evidence = next(
                sentence
                for other_anchor in anchors
                if nearest_role in associations[other_anchor]
                for sentence in evidence_by_anchor[other_anchor]
                if nearest_role in _content(sentence)
            )
            return anchor, nearest_role, evidence
    return None


def _is_epistemic_research_tail(sentence: str) -> bool:
    """Return true only for a non-answer sentence that requests more research.

    Biomedical answers often append a conventional limitation such as
    "Further randomized trials are needed."  Requiring that sentence to be
    entailed by the supplied abstract blocks an otherwise proved answer, while
    treating every recommendation as disposable would hide actionable claims.
    The narrow predicate below therefore accepts only research-validation
    tails and never clinical, operational, or user-directed recommendations.
    """
    normalized = _norm(sentence)
    research_terms = (
        "additional research", "additional study", "additional studies", "additional trial", "additional trials",
        "further investigation", "further investigations", "further research", "further study", "further studies",
        "further trial", "further trials", "future investigation", "future investigations", "future research",
        "future study", "future studies", "future trial", "future trials", "larger study", "larger studies",
        "more research", "randomized controlled trial", "randomized controlled trials",
    )
    validation_terms = (
        "confirm", "confirmation", "establish", "examine", "investigate", "needed", "necessary", "required",
        "replicate", "replication", "validate", "validation", "warranted",
    )
    return any(term in normalized for term in research_terms) and any(term in normalized for term in validation_terms)


def _claim_support(context: str, question: str, answer: str) -> tuple[ProofStatus, str, tuple[str, ...], tuple[str, ...]]:
    explanation = re.sub(r"^\s*(?:yes|no|true|false)\s*[.,:;-]*\s*", "", answer, count=1, flags=re.I)
    if not explanation.strip():
        return ProofStatus.PROVED, "POLARITY_ONLY_ANSWER", (), ()
    overall_role_conflict = _anchor_role_contradiction(context, explanation)
    if overall_role_conflict is not None:
        anchor, role, evidence = overall_role_conflict
        return ProofStatus.DISPROVED, "ANSWER_CLAIM_ROLE_CONTRADICTION", (evidence,), (f"anchor={anchor}:role={role}",)
    claims: list[str] = []
    for sentence in _sentences(explanation):
        if _is_epistemic_research_tail(sentence):
            continue
        # A causal or role-bearing continuation is an independent atomic
        # claim.  Keeping it inside one bag of words permits relation swaps
        # (X causes Y / Y causes X) and evidence mosaics assembled from
        # unrelated sentences.
        parts = re.split(
            r"\s*,?\s+(?:by|thereby|whereas|rather\s+than|instead\s+of|involving|because|due\s+to)\s+",
            sentence,
            flags=re.I,
        )
        claims.extend(part for part in parts if len(_content(part)) >= 2)
    claims = tuple(claims)
    if not claims:
        return ProofStatus.UNRESOLVED, "ANSWER_EXPLANATION_EMPTY", (), ()
    context_sentences = _sentences(context)
    question_terms = _content(question)
    all_evidence: list[str] = []
    trace: list[str] = []
    for claim in claims:
        claim_terms = _content(claim)
        role_conflict = _anchor_role_contradiction(context, claim)
        if role_conflict is not None:
            anchor, role, evidence = role_conflict
            return ProofStatus.DISPROVED, "ANSWER_CLAIM_ROLE_CONTRADICTION", tuple(all_evidence + [evidence]), tuple(trace + [f"anchor={anchor}:role={role}"])
        proposition_terms = claim_terms | question_terms
        candidates: list[tuple[float, str, set[str]]] = []
        for sentence in context_sentences:
            sentence_terms = _content(sentence)
            overlap = len(proposition_terms & sentence_terms)
            if overlap < 2:
                continue
            precision = overlap / max(1, len(proposition_terms))
            normalized_sentence = _norm(sentence)
            if any(cue in normalized_sentence for cue in ("aim of", "objective", "we investigated", "method")):
                precision -= 0.35
            candidates.append((precision, sentence, sentence_terms))
        if not candidates:
            return ProofStatus.UNRESOLVED, "ANSWER_CLAIM_EVIDENCE_MISSING", tuple(all_evidence), tuple(trace)
        candidates.sort(key=lambda item: (-item[0], item[1]))
        for _, sentence, sentence_terms in candidates:
            if _negated(sentence) == _negated(claim):
                continue
            evidence_core = sentence_terms - question_terms
            evidence_coverage = len(claim_terms & evidence_core) / max(1, len(evidence_core))
            if len(claim_terms & evidence_core) >= 3 and evidence_coverage >= 0.75:
                return ProofStatus.DISPROVED, "ANSWER_CLAIM_POLARITY_CONTRADICTION", tuple(all_evidence + [sentence]), tuple(trace)
        aligned_candidates = [item for item in candidates if _negated(item[1]) == _negated(claim)]
        opposite_candidates = [item for item in candidates if _negated(item[1]) != _negated(claim)]
        direct_opposite = [
            item for item in opposite_candidates
            if len(claim_terms & item[2]) / max(1, len(claim_terms)) >= 0.70
        ]
        if direct_opposite:
            return ProofStatus.DISPROVED, "ANSWER_CLAIM_POLARITY_CONTRADICTION", tuple(all_evidence + [direct_opposite[0][1]]), tuple(trace)
        aligned_score = aligned_candidates[0][0] if aligned_candidates else 0.0
        opposite_score = opposite_candidates[0][0] if opposite_candidates else 0.0
        if opposite_score >= 0.35 and opposite_score > aligned_score + 0.05:
            return ProofStatus.DISPROVED, "ANSWER_CLAIM_POLARITY_CONTRADICTION", tuple(all_evidence + [opposite_candidates[0][1]]), tuple(trace)
        if aligned_score < 0.20:
            return ProofStatus.UNRESOLVED, "ANSWER_CLAIM_POLARITY_UNBOUND", tuple(all_evidence), tuple(trace)
        selected = aligned_candidates[:4]
        novel_terms = claim_terms - question_terms
        claim_numbers = {round(item.value, 12) for item in _numbers(claim)}
        localized: list[tuple[float, tuple[float, str, set[str]]]] = []
        for item in selected:
            evidence_numbers = {round(number.value, 12) for number in _numbers(item[1])}
            coverage = len(novel_terms & item[2]) / len(novel_terms) if novel_terms else 1.0
            if claim_numbers <= evidence_numbers:
                localized.append((coverage, item))
        localized.sort(key=lambda item: (-item[0], -item[1][0], item[1][1]))
        coverage = localized[0][0] if localized else 0.0
        if coverage < 0.62:
            return ProofStatus.UNRESOLVED, "ANSWER_CLAIM_NOT_ENTAILED", tuple(all_evidence + [item[1] for item in selected]), tuple(trace + [f"coverage={coverage:.12g}"])
        all_evidence.append(localized[0][1][1])
        trace.append(f"claim_sha256={_sha(claim)}:coverage={coverage:.12g}")
    return ProofStatus.PROVED, "ANSWER_CLAIMS_ENTAILED", tuple(dict.fromkeys(all_evidence)), tuple(trace)

_NUMBER_WORD_VALUES = {
    "one": 1.0, "two": 2.0, "three": 3.0, "four": 4.0, "five": 5.0, "six": 6.0,
    "seven": 7.0, "eight": 8.0, "nine": 9.0, "ten": 10.0, "eleven": 11.0, "twelve": 12.0,
    "first": 1.0, "second": 2.0, "third": 3.0, "fourth": 4.0, "fifth": 5.0,
    "sixth": 6.0, "seventh": 7.0, "eighth": 8.0, "ninth": 9.0, "tenth": 10.0,
}

