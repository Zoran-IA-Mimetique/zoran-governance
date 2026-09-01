from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass

from tolerance_skill import Decision


COMPONENT_ID = "zoran.contrastive-corpus-gate"
VERSION = "18.0.0"
CATEGORIES = (
    "FAITHFUL_PARAPHRASE",
    "ENTITY_RELATION_SWAP",
    "NUMBER_DATE_UNIT",
    "NEGATION_SCOPE",
    "LONG_CONTEXT_DIALOGUE",
)
DEFAULT_RATIOS = {
    "FAITHFUL_PARAPHRASE": 0.40,
    "ENTITY_RELATION_SWAP": 0.25,
    "NUMBER_DATE_UNIT": 0.15,
    "NEGATION_SCOPE": 0.10,
    "LONG_CONTEXT_DIALOGUE": 0.10,
}


def _sha(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _is_sha(value: str) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


@dataclass(frozen=True)
class ContrastiveCase:
    case_id: str
    category: str
    split: str
    provenance_root: str
    source_uri: str
    source_sha256: str
    question: str
    context: str
    evidence_quote: str
    faithful_answer: str
    hallucinated_answer: str
    question_vector_sha256: str
    faithful_proposition_sha256: str
    hallucinated_proposition_sha256: str
    used_for_learning: bool = False


def corpus_sha256(cases: tuple[ContrastiveCase, ...]) -> str:
    return _sha([asdict(item) for item in cases])


@dataclass(frozen=True)
class ContrastiveCorpusRequest:
    cases: tuple[ContrastiveCase, ...]
    frozen_corpus_sha256: str
    expected_total: int = 1000
    ratios: tuple[tuple[str, float], ...] = tuple(DEFAULT_RATIOS.items())


@dataclass(frozen=True)
class ContrastiveCorpusEvaluation:
    decision: Decision
    reasons: tuple[str, ...]
    case_count: int
    category_counts: tuple[tuple[str, int], ...]
    receipt_sha256: str


class ContrastiveCorpusGate:
    """Freeze a real, source-grounded train/validation/holdout corpus."""

    def evaluate(self, request: ContrastiveCorpusRequest | None) -> ContrastiveCorpusEvaluation:
        if not isinstance(request, ContrastiveCorpusRequest):
            return self._finish(Decision.RETRY, ("CONTRASTIVE_CORPUS_REQUEST_MISSING",), ())
        cases = tuple(request.cases)
        if request.expected_total < 10 or len(cases) != request.expected_total:
            return self._finish(Decision.RETRY, ("CONTRASTIVE_CASE_COUNT_MISMATCH",), cases)
        if request.frozen_corpus_sha256 != corpus_sha256(cases):
            return self._finish(Decision.VETO, ("CONTRASTIVE_CORPUS_DIGEST_MISMATCH",), cases)
        if len({item.case_id for item in cases}) != len(cases):
            return self._finish(Decision.VETO, ("CONTRASTIVE_CASE_ID_DUPLICATE",), cases)

        ratios = dict(request.ratios)
        if set(ratios) != set(CATEGORIES) or abs(sum(ratios.values()) - 1.0) > 1e-12:
            return self._finish(Decision.VETO, ("CONTRASTIVE_RATIO_CONTRACT_INVALID",), cases)
        counts = Counter(item.category for item in cases)
        expected_counts = {category: round(request.expected_total * ratios[category]) for category in CATEGORIES}
        if counts != Counter(expected_counts):
            return self._finish(Decision.VETO, ("CONTRASTIVE_CATEGORY_QUOTA_MISMATCH",), cases)

        roots_by_split: dict[str, set[str]] = defaultdict(set)
        split_counts = Counter()
        for item in cases:
            if item.split not in {"train", "validation", "holdout"}:
                return self._finish(Decision.VETO, (f"CONTRASTIVE_SPLIT_INVALID:{item.case_id}",), cases)
            split_counts[item.split] += 1
            roots_by_split[item.split].add(item.provenance_root)
            if item.used_for_learning and item.split != "train":
                return self._finish(Decision.VETO, (f"HOLDOUT_OR_VALIDATION_LEAK:{item.case_id}",), cases)
            strings = (
                item.case_id, item.provenance_root, item.source_uri, item.question,
                item.context, item.evidence_quote, item.faithful_answer, item.hallucinated_answer,
            )
            if any(not value.strip() for value in strings):
                return self._finish(Decision.RETRY, (f"CONTRASTIVE_TRACE_MISSING:{item.case_id}",), cases)
            if not all(_is_sha(value) for value in (
                item.source_sha256, item.question_vector_sha256,
                item.faithful_proposition_sha256, item.hallucinated_proposition_sha256,
            )):
                return self._finish(Decision.RETRY, (f"CONTRASTIVE_DIGEST_INVALID:{item.case_id}",), cases)
            if item.evidence_quote not in item.context:
                return self._finish(Decision.VETO, (f"CONTRASTIVE_QUOTE_NOT_LOCAL:{item.case_id}",), cases)
            if item.faithful_answer.strip().casefold() == item.hallucinated_answer.strip().casefold():
                return self._finish(Decision.VETO, (f"CONTRASTIVE_PAIR_NOT_DISTINCT:{item.case_id}",), cases)
            if item.faithful_proposition_sha256 == item.hallucinated_proposition_sha256:
                return self._finish(Decision.VETO, (f"CONTRASTIVE_PROPOSITION_NOT_DISTINCT:{item.case_id}",), cases)

        if set(split_counts) != {"train", "validation", "holdout"}:
            return self._finish(Decision.RETRY, ("THREE_WAY_SPLIT_REQUIRED",), cases)
        if any(
            roots_by_split[left] & roots_by_split[right]
            for left, right in (("train", "validation"), ("train", "holdout"), ("validation", "holdout"))
        ):
            return self._finish(Decision.VETO, ("PROVENANCE_ROOT_LEAK_ACROSS_SPLITS",), cases)
        return self._finish(Decision.PASS, ("CONTRASTIVE_CORPUS_FROZEN_AND_SEPARATED",), cases)

    @staticmethod
    def _finish(decision: Decision, reasons: tuple[str, ...], cases: tuple[ContrastiveCase, ...]) -> ContrastiveCorpusEvaluation:
        counts = tuple(sorted(Counter(item.category for item in cases).items()))
        body = {
            "component": COMPONENT_ID,
            "version": VERSION,
            "decision": decision.value,
            "reasons": list(reasons),
            "case_count": len(cases),
            "category_counts": list(counts),
        }
        return ContrastiveCorpusEvaluation(decision, reasons, len(cases), counts, _sha(body))
