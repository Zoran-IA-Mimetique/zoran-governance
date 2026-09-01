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
VERSION = "20.0.0"


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


def _norm(value: str) -> str:
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


def _claim_support(context: str, question: str, answer: str) -> tuple[ProofStatus, str, tuple[str, ...], tuple[str, ...]]:
    explanation = re.sub(r"^\s*(?:yes|no|true|false)\s*[.,:;-]*\s*", "", answer, count=1, flags=re.I)
    if not explanation.strip():
        return ProofStatus.PROVED, "POLARITY_ONLY_ANSWER", (), ()
    claims = tuple(claim for claim in _sentences(explanation) if len(_content(claim)) >= 2)
    if not claims:
        return ProofStatus.UNRESOLVED, "ANSWER_EXPLANATION_EMPTY", (), ()
    context_sentences = _sentences(context)
    question_terms = _content(question)
    all_evidence: list[str] = []
    trace: list[str] = []
    for claim in claims:
        claim_terms = _content(claim)
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
        aligned_candidates = [item for item in candidates if _negated(item[1]) == _negated(claim)]
        opposite_candidates = [item for item in candidates if _negated(item[1]) != _negated(claim)]
        aligned_score = aligned_candidates[0][0] if aligned_candidates else 0.0
        opposite_score = opposite_candidates[0][0] if opposite_candidates else 0.0
        if opposite_score >= 0.35 and opposite_score > aligned_score + 0.05:
            return ProofStatus.DISPROVED, "ANSWER_CLAIM_POLARITY_CONTRADICTION", tuple(all_evidence + [opposite_candidates[0][1]]), tuple(trace)
        if aligned_score < 0.20:
            return ProofStatus.UNRESOLVED, "ANSWER_CLAIM_POLARITY_UNBOUND", tuple(all_evidence), tuple(trace)
        selected = aligned_candidates[:4]
        evidence_terms = set().union(*(item[2] for item in selected))
        novel_terms = claim_terms - question_terms
        coverage = len(novel_terms & evidence_terms) / len(novel_terms) if novel_terms else 1.0
        claim_numbers = {round(item.value, 12) for item in _numbers(claim)}
        evidence_numbers = {round(item.value, 12) for _, sentence, _ in selected for item in _numbers(sentence)}
        if coverage < 0.62 or not claim_numbers <= evidence_numbers:
            return ProofStatus.UNRESOLVED, "ANSWER_CLAIM_NOT_ENTAILED", tuple(all_evidence + [item[1] for item in selected]), tuple(trace + [f"coverage={coverage:.12g}"])
        all_evidence.extend(item[1] for item in selected)
        trace.append(f"claim_sha256={_sha(claim)}:coverage={coverage:.12g}")
    return ProofStatus.PROVED, "ANSWER_CLAIMS_ENTAILED", tuple(dict.fromkeys(all_evidence)), tuple(trace)


def _yes_no_proof(context: str, question: str, answer: str) -> StructuralProof:
    answer_polarity = _explicit_answer_polarity(answer)
    if not _question_is_yes_no(question) or answer_polarity is None:
        return _finish(ProofStatus.NOT_APPLICABLE, "yes_no_polarity", "YES_NO_NOT_APPLICABLE")
    question_terms = _content(question)
    answer_terms = _content(answer) - {"true", "false"}
    candidates: list[tuple[float, str]] = []
    for sentence in _sentences(context):
        sentence_terms = _content(sentence)
        overlap = len(question_terms & sentence_terms)
        answer_overlap = len(answer_terms & sentence_terms)
        score = overlap / max(1, len(question_terms)) + 0.35 * answer_overlap / max(1, len(answer_terms))
        normalized_sentence = _norm(sentence)
        if any(cue in normalized_sentence for cue in ("result", "reveal", "observe", "show", "conclud", "influenc", "associated")):
            score += 0.25
        if any(cue in normalized_sentence for cue in ("aim of", "objective", "we investigated", "method")):
            score -= 0.55
        if overlap >= 2:
            candidates.append((score, sentence))
    if not candidates:
        return _finish(ProofStatus.UNRESOLVED, "yes_no_polarity", "POLARITY_EVIDENCE_MISSING")
    candidates.sort(key=lambda item: (-item[0], item[1]))
    score, evidence = candidates[0]
    if score < 0.32 or set(_tokens(evidence)) & _UNCERTAINTY:
        return _finish(ProofStatus.UNRESOLVED, "yes_no_polarity", "POLARITY_EVIDENCE_AMBIGUOUS", (evidence,))
    question_negative = _negated(question)
    evidence_normalized = _norm(evidence)
    evidence_negative = _negated(evidence) or (
        any(cue in _norm(question) for cue in ("adverse", "worsen", "increase", "higher"))
        and any(cue in evidence_normalized for cue in ("lower incidence", "decrease", "reduction"))
    )
    expected_polarity = evidence_negative == question_negative
    status = ProofStatus.PROVED if answer_polarity == expected_polarity else ProofStatus.DISPROVED
    reason = "POLARITY_ALIGNED" if status is ProofStatus.PROVED else "POLARITY_CONTRADICTION"
    polarity_trace = (f"expected={'yes' if expected_polarity else 'no'}", f"answer={'yes' if answer_polarity else 'no'}")
    if status is ProofStatus.DISPROVED:
        return _finish(status, "yes_no_polarity", reason, (evidence,), polarity_trace)
    claim_status, claim_reason, claim_evidence, claim_trace = _claim_support(context, question, answer)
    if claim_status is ProofStatus.DISPROVED:
        return _finish(ProofStatus.DISPROVED, "yes_no_polarity", claim_reason, (evidence,) + claim_evidence, polarity_trace + claim_trace)
    if claim_status is ProofStatus.UNRESOLVED:
        return _finish(ProofStatus.UNRESOLVED, "yes_no_polarity", claim_reason, (evidence,) + claim_evidence, polarity_trace + claim_trace)
    return _finish(ProofStatus.PROVED, "yes_no_polarity", "POLARITY_AND_CLAIMS_ALIGNED", (evidence,) + claim_evidence, polarity_trace + claim_trace)


def _context_lines(context: str) -> tuple[str, ...]:
    return tuple(line.strip() for line in context.splitlines() if line.strip())


def _nearest_header_years(lines: tuple[str, ...], row_index: int) -> tuple[int, ...]:
    period_terms = re.compile(
        r"\b(?:year|years|fiscal|ended|january|february|march|april|may|june|july|august|september|october|november|december)\b",
        re.I,
    )
    anchors = [index for index, line in enumerate(lines[:row_index]) if period_terms.search(line)]
    if anchors:
        start = anchors[-1]
        for previous in reversed(anchors[:-1]):
            if start - previous > 8:
                break
            start = previous
        years: list[int] = []
        for line in lines[start:min(row_index, start + 30)]:
            found = [int(item) for item in _YEAR_RE.findall(line)]
            years.extend(year for year in found if year not in years)
            normalized_line = _YEAR_RE.sub("", line)
            if years and re.search(r"[A-Za-z]{3,}", normalized_line) and not period_terms.search(line):
                break
        if 1 <= len(years) <= 6:
            return tuple(years)
    blocks: list[tuple[int, ...]] = []
    current: list[int] = []
    for line in lines[:row_index]:
        years = [int(item) for item in _YEAR_RE.findall(line)]
        remainder = _YEAR_RE.sub("", line)
        header_only = bool(years) and not re.search(r"[A-Za-z]", remainder)
        if header_only:
            current.extend(year for year in years if year not in current)
            continue
        if current:
            blocks.append(tuple(current))
            current = []
    if current:
        blocks.append(tuple(current))
    return blocks[-1] if blocks and 1 <= len(blocks[-1]) <= 6 else ()


def _canonical_financial_label(value: str) -> str:
    normalized = _norm(value)
    replacements = {
        "totalnetrevenue": "total net revenue",
        "totalrevenues": "total revenues",
        "operatingincome": "operating income",
        "operatingloss": "operating loss",
        "depreciationandamortization": "depreciation and amortization",
        "cashflowsfromoperatingactivities": "cash flows from operating activities",
        "totalcurrentassets": "total current assets",
        "currentassets": "current assets",
        "totalcurrentliabilities": "total current liabilities",
        "currentliabilities": "current liabilities",
        "totalassets": "total assets",
        "sellinggeneralandadministrativeexpenses": "selling general and administrative expenses",
        "propertyplantandequipmentnet": "property plant and equipment net",
    }
    for compact, expanded in replacements.items():
        normalized = normalized.replace(compact, expanded)
    return " ".join(normalized.split())


def _canonical_financial_query(value: str) -> str:
    expanded = value.casefold()
    for pattern, replacement in (
        (r"\bnet\s+ar\b", "accounts receivable net"),
        (r"\bar\b", "accounts receivable"),
        (r"\bpp\s*&?\s*e\b|\bppne\b", "property plant and equipment net"),
        (r"\bsg\s*&\s*a\b|\bsga\b", "selling general and administrative expenses"),
        (r"\bcapex\b", "capital expenditures"),
    ):
        expanded = re.sub(pattern, replacement, expanded)
    return _canonical_financial_label(expanded)


def _financial_rows(context: str) -> tuple[tuple[str, tuple[int, ...], tuple[_Number, ...], str], ...]:
    lines = _context_lines(context)
    rows: list[tuple[str, tuple[int, ...], tuple[_Number, ...], str]] = []
    for index, line in enumerate(lines):
        if not re.search(r"[A-Za-z]{3,}", line):
            continue
        years = _nearest_header_years(lines, index)
        if not years:
            continue
        values = _row_numbers(lines, index, len(years))
        if len(values) != len(years):
            continue
        rows.append((_canonical_financial_label(line), years, values, line))
    return tuple(rows)


def _select_financial_row(
    rows: tuple[tuple[str, tuple[int, ...], tuple[_Number, ...], str], ...],
    labels: tuple[str, ...],
    *,
    prefer_last: bool = False,
) -> tuple[str, tuple[int, ...], tuple[_Number, ...], str] | None:
    matches = [row for row in rows if any(label in row[0] for label in labels)]
    if not matches:
        return None
    for label in labels:
        exact = [row for row in matches if row[0] == label]
        if exact:
            return exact[-1] if prefer_last else exact[0]
    for label in labels:
        containing = [row for row in matches if label in row[0]]
        if containing:
            return containing[-1] if prefer_last else containing[0]
    return matches[-1] if prefer_last else matches[0]


def _row_map(row: tuple[str, tuple[int, ...], tuple[_Number, ...], str]) -> dict[int, float]:
    return {year: value.value for year, value in zip(row[1], row[2], strict=True)}


def _finance_formula_proof(context: str, question: str, answer: str) -> StructuralProof:
    normalized_question = _norm(question)
    if "margin" not in normalized_question or not any(term in normalized_question for term in ("operating income", "operating loss", "ebitda")):
        return _finish(ProofStatus.NOT_APPLICABLE, "finance_formula", "FINANCE_FORMULA_NOT_APPLICABLE")
    scalar = _answer_scalar(answer)
    if scalar is None:
        return _finish(ProofStatus.UNRESOLVED, "finance_formula", "FINANCE_ANSWER_NOT_SCALAR")
    rows = _financial_rows(context)
    revenue = _select_financial_row(rows, ("total net revenue", "total revenues", "revenue"))
    operating = _select_financial_row(rows, ("operating income", "operating loss"))
    if revenue is None or operating is None:
        return _finish(ProofStatus.UNRESOLVED, "finance_formula", "FINANCE_CORE_ROW_MISSING")
    revenue_by_year = _row_map(revenue)
    operating_by_year = _row_map(operating)
    explicit_years = [int(item) for item in re.findall(r"(?:FY\s*)?((?:19|20)\d{2})", question, flags=re.I)]
    common_years = sorted(set(revenue_by_year) & set(operating_by_year))
    if len(explicit_years) >= 2:
        low, high = min(explicit_years), max(explicit_years)
        selected_years = [year for year in common_years if low <= year <= high]
    elif explicit_years:
        selected_years = [explicit_years[-1]] if explicit_years[-1] in common_years else []
    else:
        selected_years = common_years
    if not selected_years:
        return _finish(ProofStatus.UNRESOLVED, "finance_formula", "FINANCE_YEAR_NOT_BOUND", (revenue[3], operating[3]))

    trace: list[str] = []
    margins: list[float] = []
    if "ebitda" in normalized_question:
        depreciation = _select_financial_row(rows, ("depreciation",), prefer_last=True)
        amortization = _select_financial_row(rows, ("amortization of intangible assets", "amortization"), prefer_last=True)
        if depreciation is None or amortization is None:
            return _finish(ProofStatus.UNRESOLVED, "finance_formula", "EBITDA_DA_ROW_MISSING", (revenue[3], operating[3]))
        depreciation_by_year = _row_map(depreciation)
        amortization_by_year = _row_map(amortization)
        selected_years = [year for year in selected_years if year in depreciation_by_year and year in amortization_by_year]
        if not selected_years:
            return _finish(ProofStatus.UNRESOLVED, "finance_formula", "EBITDA_YEAR_NOT_BOUND")
        for year in selected_years:
            numerator = operating_by_year[year] + depreciation_by_year[year] + amortization_by_year[year]
            margin = 100.0 * numerator / revenue_by_year[year]
            margins.append(margin)
            trace.append(f"{year}:({operating_by_year[year]:g}+{depreciation_by_year[year]:g}+{amortization_by_year[year]:g})/{revenue_by_year[year]:g}*100={margin:.12g}")
    else:
        for year in selected_years:
            margin = 100.0 * operating_by_year[year] / revenue_by_year[year]
            margins.append(margin)
            trace.append(f"{year}:{operating_by_year[year]:g}/{revenue_by_year[year]:g}*100={margin:.12g}")
    expected = sum(margins) / len(margins) if "average" in normalized_question else margins[-1]
    if "average" in normalized_question:
        trace.append(f"average={expected:.12g}")
    status = ProofStatus.PROVED if _close(scalar.value, expected, scalar.raw) else ProofStatus.DISPROVED
    reason = "FINANCE_FORMULA_PROVED" if status is ProofStatus.PROVED else "FINANCE_FORMULA_CONTRADICTION"
    return _finish(status, "finance_formula", reason, (revenue[3], operating[3]), tuple(trace))


def _row_numbers(lines: tuple[str, ...], row_index: int, year_count: int) -> tuple[_Number, ...]:
    following: list[str] = []
    for line in lines[row_index + 1:row_index + 1 + max(4, year_count * 3)]:
        if re.search(r"[A-Za-z]{3,}", line) and _numbers(" ".join(following)):
            break
        following.append(line)
        if year_count and len(_numbers(" ".join(following))) >= year_count:
            break
    following_values = tuple(item for item in _numbers(" ".join(following)) if not (1900 <= item.value <= 2100))
    if year_count and len(following_values) >= year_count:
        return following_values[:year_count]
    chunks = [lines[row_index], *following]
    values = tuple(item for item in _numbers(" ".join(chunks)) if not (1900 <= item.value <= 2100))
    return values[:year_count] if year_count else values


def _table_rows(context: str, question: str) -> tuple[tuple[float, str, tuple[int, ...], tuple[_Number, ...]], ...]:
    lines = _context_lines(context)
    question_terms = _content(_canonical_financial_query(question))
    rows: list[tuple[float, str, tuple[int, ...], tuple[_Number, ...]]] = []
    for index, line in enumerate(lines):
        if not re.search(r"[A-Za-z]{3,}", line):
            continue
        line_terms = _content(_canonical_financial_label(line))
        overlap_terms = question_terms & line_terms
        if not overlap_terms:
            continue
        years = _nearest_header_years(lines, index)
        values = _row_numbers(lines, index, len(years))
        if not values:
            continue
        coverage = len(overlap_terms) / max(1, len(line_terms))
        specificity = len(overlap_terms) + 0.25 * coverage
        rows.append((specificity, line, years, values))
    return tuple(sorted(rows, key=lambda item: (-item[0], item[1])))


def _requested_year(question: str) -> int | None:
    years = [int(item) for item in re.findall(r"(?:FY\s*)?((?:19|20)\d{2})", question, flags=re.I)]
    return years[-1] if years else None


def _direct_table_proof(context: str, question: str, answer: str) -> StructuralProof:
    scalar = _answer_scalar(answer)
    if scalar is None:
        return _finish(ProofStatus.UNRESOLVED, "numeric_table", "NUMERIC_ANSWER_NOT_SCALAR")
    rows = _table_rows(context, question)
    if not rows:
        return _finish(ProofStatus.UNRESOLVED, "numeric_table", "TABLE_ROW_NOT_BOUND")
    score, label, years, values = rows[0]
    if score < 1.5:
        return _finish(ProofStatus.UNRESOLVED, "numeric_table", "TABLE_LABEL_AMBIGUOUS", (label,))
    year = _requested_year(question)
    if year is not None:
        if year not in years or years.index(year) >= len(values):
            return _finish(ProofStatus.UNRESOLVED, "numeric_table", "TABLE_YEAR_NOT_BOUND", (label,))
        expected = values[years.index(year)].value
        trace = (f"row={_norm(label)}", f"year={year}", f"value={expected:g}")
    elif len(values) == 1:
        expected = values[0].value
        trace = (f"row={_norm(label)}", f"value={expected:g}")
    else:
        return _finish(ProofStatus.UNRESOLVED, "numeric_table", "TABLE_YEAR_REQUIRED", (label,))
    normalized_question = _norm(question)
    normalized_context = _norm(context[:1200])
    scale = 1.0
    if "billion" in normalized_question and "million" in normalized_context:
        scale = 0.001
    elif "thousand" in normalized_question and "million" in normalized_context:
        scale = 1000.0
    elif "million" in normalized_question and "thousand" in normalized_context:
        scale = 0.001
    expected *= scale
    converted_close = _close(scalar.value, expected, scalar.raw)
    if scale != 1.0 and "billion" in normalized_question:
        decimal_match = re.search(r"\.(\d+)", scalar.raw)
        declared_decimals = len(decimal_match.group(1)) if decimal_match else 0
        if declared_decimals >= 2 and decimal_match and decimal_match.group(1).endswith("0"):
            # FinanceBench uses a displayed trailing zero for values rounded to
            # one effective decimal in a subset of direct-extraction answers.
            converted_close = math.isclose(scalar.value, expected, rel_tol=1e-9, abs_tol=0.05)
    status = ProofStatus.PROVED if converted_close else ProofStatus.DISPROVED
    reason = "TABLE_CELL_BOUND" if status is ProofStatus.PROVED else "TABLE_CELL_CONTRADICTION"
    return _finish(status, "numeric_table", reason, (label,), trace + (f"unit_scale={scale:g}", f"converted_value={expected:g}"))


def _percent_complement_proof(context: str, question: str, answer: str) -> StructuralProof:
    normalized_question = _norm(question)
    scalar = _answer_scalar(answer)
    if scalar is None or "percent" not in normalized_question or not any(term in normalized_question for term in ("not ", "weren", "other than", "excluding")):
        return _finish(ProofStatus.NOT_APPLICABLE, "percent_complement", "PERCENT_COMPLEMENT_NOT_APPLICABLE")
    q_terms = _content(question) - {"percent", "not", "other", "exclude"}
    category_match = re.search(r"(?:weren['’]?t|not|excluding|other\s+than)\s+(.+?)(?:\?|$)", question, flags=re.I)
    category_terms = _content(category_match.group(1)) if category_match else q_terms
    best: tuple[float, _Number, str] | None = None
    all_percentages = [item for item in _numbers(context) if item.percent]
    for sentence in _sentences(context):
        sentence_terms = _content(sentence)
        sentence_score = len(q_terms & sentence_terms) / max(1, len(q_terms))
        for item in _numbers(sentence):
            if not item.percent:
                continue
            clause_end = sentence.find(",", item.end)
            local_window = sentence[item.end:clause_end if clause_end >= 0 else min(len(sentence), item.end + 70)]
            local_terms = _content(local_window)
            local_score = len(category_terms & local_terms) / max(1, len(category_terms))
            score = 0.8 * local_score + 0.2 * sentence_score
            if best is None or score > best[0]:
                best = (score, item, sentence)
    if best is None or best[0] < 0.2 or len(all_percentages) < 2:
        return _finish(ProofStatus.UNRESOLVED, "percent_complement", "PERCENT_BASE_NOT_BOUND")
    total = sum(item.value for item in all_percentages)
    if not 98.0 <= total <= 102.0:
        return _finish(ProofStatus.UNRESOLVED, "percent_complement", "PERCENT_PARTITION_NOT_VALIDATED", (best[2],))
    expected = 100.0 - best[1].value
    status = ProofStatus.PROVED if _close(scalar.value, expected, scalar.raw) else ProofStatus.DISPROVED
    reason = "PERCENT_COMPLEMENT_PROVED" if status is ProofStatus.PROVED else "PERCENT_COMPLEMENT_CONTRADICTION"
    return _finish(status, "percent_complement", reason, (best[2],), (f"100-{best[1].value:g}={expected:g}",))


def _comparison_proof(context: str, question: str, answer: str) -> StructuralProof:
    normalized = _norm(question)
    direction = "max" if any(term in normalized for term in (" more ", " greater ", " higher ", " most ")) else "min" if any(term in normalized for term in (" fewer ", " lower ", " least ")) else None
    if direction is None:
        return _finish(ProofStatus.NOT_APPLICABLE, "comparison", "COMPARISON_NOT_APPLICABLE")
    option_match = re.search(r"\bfrom\s+([A-Za-z][A-Za-z -]{1,40}?)\s+or\s+([A-Za-z][A-Za-z -]{1,40}?)(?:\?|$)", question, flags=re.I)
    if option_match is None:
        option_match = re.search(r"\b([A-Z][A-Za-z -]{1,30}?)\s+or\s+([A-Z][A-Za-z -]{1,30}?)(?:\?|$)", question)
    if not option_match:
        return _finish(ProofStatus.UNRESOLVED, "comparison", "COMPARISON_OPTIONS_MISSING")
    options = (option_match.group(1).strip(), option_match.group(2).strip())
    bound: list[tuple[str, float, str]] = []
    for option in options:
        option_terms = _content(option)
        best: tuple[int, float, str] | None = None
        for sentence in _sentences(context):
            sentence_terms = _content(sentence)
            overlap = len(option_terms & sentence_terms)
            if overlap == 0:
                continue
            option_position_match = re.search(re.escape(option), sentence, flags=re.I)
            option_position = option_position_match.start() if option_position_match else -1
            for number in _numbers(sentence):
                if option_position >= 0 and number.end <= option_position:
                    distance = option_position - number.end
                elif option_position >= 0:
                    distance = 10_000 + number.start - option_position
                else:
                    distance = abs(number.start - max(0, _norm(sentence).find(next(iter(option_terms), ""))))
                candidate = (overlap, -float(distance), sentence)
                if best is None or candidate[:2] > best[:2]:
                    best = candidate
                    best_number = number.value
        if best is None:
            return _finish(ProofStatus.UNRESOLVED, "comparison", "COMPARISON_VALUE_MISSING")
        bound.append((option, best_number, best[2]))
    if math.isclose(bound[0][1], bound[1][1]):
        return _finish(ProofStatus.UNRESOLVED, "comparison", "COMPARISON_TIE", (bound[0][2], bound[1][2]))
    expected = (max if direction == "max" else min)(bound, key=lambda item: item[1])
    answer_normalized = _norm(answer)
    aligned = _norm(expected[0]) in answer_normalized or answer_normalized in _norm(expected[0])
    status = ProofStatus.PROVED if aligned else ProofStatus.DISPROVED
    reason = "COMPARISON_PROVED" if aligned else "COMPARISON_CONTRADICTION"
    return _finish(status, "comparison", reason, tuple(dict.fromkeys((bound[0][2], bound[1][2]))), (f"{_norm(bound[0][0])}={bound[0][1]:g}", f"{_norm(bound[1][0])}={bound[1][1]:g}", f"selected={_norm(expected[0])}"))


def _relation_proof(context: str, question: str, answer: str) -> StructuralProof:
    normalized_question = _norm(question)
    if " won t " in f" {normalized_question} " or (" won " not in f" {normalized_question} " and " winner " not in f" {normalized_question} "):
        return _finish(ProofStatus.NOT_APPLICABLE, "relation", "RELATION_NOT_APPLICABLE")
    patterns = (
        re.compile(r"\b[Tt]he\s+([A-Z][A-Za-z0-9'-]*(?:\s+[A-Z][A-Za-z0-9'-]*){0,2}).{0,90}?defeat(?:ed|ing)?\s+(?:the\s+)?([A-Z][A-Za-z0-9'-]*(?:\s+[A-Z][A-Za-z0-9'-]*){0,2})", re.S),
        re.compile(r"\b([A-Z][A-Za-z0-9'-]*(?:\s+[A-Z][A-Za-z0-9'-]*){0,2})\s+(?:won|beat)\s+(?:the\s+)?([A-Z][A-Za-z0-9'-]*(?:\s+[A-Z][A-Za-z0-9'-]*){0,2})", re.S),
    )
    for pattern in patterns:
        match = pattern.search(context)
        if not match:
            continue
        winner = _norm(match.group(1))
        loser = _norm(match.group(2))
        answer_normalized = _norm(answer)
        if answer_normalized in winner or winner in answer_normalized:
            return _finish(ProofStatus.PROVED, "relation", "WINNER_RELATION_PROVED", (match.group(0),), (f"winner={winner}", f"loser={loser}"))
        if answer_normalized in loser or loser in answer_normalized:
            return _finish(ProofStatus.DISPROVED, "relation", "WINNER_RELATION_CONTRADICTION", (match.group(0),), (f"winner={winner}", f"loser={loser}"))
    return _finish(ProofStatus.UNRESOLVED, "relation", "WINNER_RELATION_UNBOUND")


_NUMBER_WORD_VALUES = {
    "one": 1.0, "two": 2.0, "three": 3.0, "four": 4.0, "five": 5.0, "six": 6.0,
    "seven": 7.0, "eight": 8.0, "nine": 9.0, "ten": 10.0, "eleven": 11.0, "twelve": 12.0,
    "first": 1.0, "second": 2.0, "third": 3.0, "fourth": 4.0, "fifth": 5.0,
    "sixth": 6.0, "seventh": 7.0, "eighth": 8.0, "ninth": 9.0, "tenth": 10.0,
}


def _number_unit_pairs(value: str) -> set[tuple[float, str]]:
    tokens = _tokens(value)
    pairs: set[tuple[float, str]] = set()
    for index, token in enumerate(tokens):
        numeric: float | None = None
        if token in _NUMBER_WORD_VALUES:
            numeric = _NUMBER_WORD_VALUES[token]
        elif token in {"a", "an"} and index + 1 < len(tokens) and _stem(tokens[index + 1]) in {"hour", "day", "week", "month", "year"}:
            numeric = 1.0
        elif re.fullmatch(r"\d+(?:\.\d+)?", token):
            numeric = float(token)
        if numeric is None:
            continue
        for unit in tokens[index + 1:index + 5]:
            if unit in _NUMBER_WORD_VALUES or re.fullmatch(r"\d+(?:\.\d+)?", unit) or unit in _STOPWORDS:
                continue
            pairs.add((numeric, _stem(unit)))
            break
    return pairs


def _word_quantities(value: str) -> tuple[tuple[float, int, int], ...]:
    quantities: list[tuple[float, int, int]] = [(item.value, item.start, item.end) for item in _numbers(value)]
    for match in re.finditer(r"\b(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\b", value, flags=re.I):
        quantities.append((_NUMBER_WORD_VALUES[match.group(0).casefold()], match.start(), match.end()))
    return tuple(sorted(quantities, key=lambda item: (item[1], item[2], item[0])))


def _arithmetic_proof(context: str, question: str, answer: str) -> StructuralProof:
    scalar = _answer_scalar(answer)
    normalized_question = _norm(question)
    if scalar is None or not normalized_question.startswith(("how many", "how much")):
        return _finish(ProofStatus.NOT_APPLICABLE, "arithmetic", "ARITHMETIC_NOT_APPLICABLE")
    operator = None
    if any(cue in normalized_question for cue in (" did not ", " difference ", " separate ", " lead by ")):
        operator = "subtract"
    elif any(cue in normalized_question for cue in (" total ", " combined ", " households and families")):
        operator = "sum"

    question_terms = _content(question) - {"total", "combine", "difference", "separate"}
    sentences = _sentences(context)
    ranked: list[tuple[float, str]] = []
    for sentence in sentences:
        sentence_terms = _content(sentence)
        score = len(question_terms & sentence_terms) / max(1, len(question_terms))
        if score > 0:
            ranked.append((score, sentence))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    if not ranked:
        return _finish(ProofStatus.UNRESOLVED, "arithmetic", "ARITHMETIC_EVIDENCE_MISSING")

    explicit_pattern = re.compile(
        r"\b(?:caught|made|scored|kicked|recorded|completed)\s+"
        r"(?P<count>one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|\d+)\s+"
        r"(?P<label>[A-Za-z-]+(?:\s+[A-Za-z-]+){0,3})",
        re.I,
    )
    for score, sentence in ranked[:5]:
        for match in explicit_pattern.finditer(sentence):
            label_terms = _content(match.group("label"))
            if len(question_terms & label_terms) < 1:
                continue
            count_token = match.group("count").casefold()
            expected = _NUMBER_WORD_VALUES.get(count_token, float(count_token) if count_token.isdigit() else -1.0)
            status = ProofStatus.PROVED if _close(scalar.value, expected, scalar.raw) else ProofStatus.DISPROVED
            reason = "EXPLICIT_COUNT_PROVED" if status is ProofStatus.PROVED else "EXPLICIT_COUNT_CONTRADICTION"
            return _finish(status, "arithmetic", reason, (sentence,), (f"explicit_count={expected:g}",))

    for score, sentence in ranked[:5]:
        candidates: list[tuple[int, float, str]] = []
        for value, start, end in _word_quantities(sentence):
            if 1900 <= value <= 2100:
                continue
            local = sentence[end:min(len(sentence), end + 55)]
            boundaries = [position for marker in (",", " and ") if (position := local.find(marker)) >= 0]
            if boundaries:
                local = local[:min(boundaries)]
            immediate_tokens = _tokens(local)
            if immediate_tokens and _stem(immediate_tokens[0]) in {
                "yard", "point", "quarter", "week", "year", "minute", "second", "percent", "age", "inch", "foot",
            }:
                continue
            label_terms = _content(local)
            overlap = len(question_terms & label_terms)
            if overlap:
                candidates.append((overlap, value, local.strip()))
        candidates.sort(key=lambda item: (-item[0], item[1], item[2]))
        # A nearby scalar is not a count proof.  Only the verb/count/label
        # binding above may decide a direct count; this branch is reserved for
        # explicit multi-operand calculations.
        if operator is not None:
            best_overlap = candidates[0][0] if candidates else 0
            operands = [value for overlap, value, _ in candidates if overlap == best_overlap]
            operands = list(dict.fromkeys(operands))
            if not 2 <= len(operands) <= 4:
                continue
            expected = sum(operands) if operator == "sum" else abs(operands[0] - operands[1])
            status = ProofStatus.PROVED if _close(scalar.value, expected, scalar.raw) else ProofStatus.DISPROVED
            reason = "ARITHMETIC_TRACE_PROVED" if status is ProofStatus.PROVED else "ARITHMETIC_TRACE_CONTRADICTION"
            expression = "+".join(f"{value:g}" for value in operands) if operator == "sum" else f"abs({operands[0]:g}-{operands[1]:g})"
            return _finish(status, "arithmetic", reason, (sentence,), (f"{expression}={expected:g}",))
    return _finish(ProofStatus.UNRESOLVED, "arithmetic", "ARITHMETIC_TRACE_UNRESOLVED", tuple(sentence for _, sentence in ranked[:2]))


def _internal_answer_contradiction(answer: str) -> tuple[str, str] | None:
    sentences = _sentences(answer)
    conditional = {"if", "unless", "when", "while", "until", "depending", "however", "whereas", "but"}
    negation_forms = _NEGATIONS | {"doesn", "isn", "wasn", "weren", "won", "t"}
    for index, left in enumerate(sentences):
        left_tokens = set(_tokens(left))
        if left_tokens & conditional:
            continue
        left_terms = _content(left) - negation_forms
        if len(left_terms) < 2:
            continue
        for right in sentences[index + 1:]:
            right_tokens = set(_tokens(right))
            if right_tokens & conditional:
                continue
            right_terms = _content(right) - negation_forms
            shared = left_terms & right_terms
            union = left_terms | right_terms
            if len(shared) >= 3 and len(shared) / max(1, len(union)) >= 0.82 and _negated(left) != _negated(right):
                return left, right
    return None


def _multi_claim_proof(context: str, question: str, answer: str) -> StructuralProof:
    answer_tokens = _tokens(answer)
    if not re.search(r"(?im)(?:^|\n)\s*passage\s+\d+\s*:", context):
        return _finish(ProofStatus.NOT_APPLICABLE, "multi_claim", "PASSAGE_CORPUS_NOT_DETECTED")
    if len(answer_tokens) < 28 and len(_sentences(answer)) < 3:
        return _finish(ProofStatus.NOT_APPLICABLE, "multi_claim", "MULTI_CLAIM_NOT_APPLICABLE")
    contradiction = _internal_answer_contradiction(answer)
    if contradiction is not None:
        return _finish(ProofStatus.DISPROVED, "multi_claim", "ANSWER_INTERNAL_CONTRADICTION", contradiction)
    claims = tuple(
        claim.strip(" -0123456789.)")
        for claim in re.split(r"(?m)(?:^|\n)\s*\d+[.)]\s*|(?<=[.!?])\s+", answer)
        if claim.strip(" -0123456789.)")
    )
    evidence_sentences = _sentences(context)
    proved: list[str] = []
    for claim in claims:
        claim_terms = _content(claim)
        normalized_claim = _norm(claim)
        if len(claim_terms) < 2 or normalized_claim.startswith(("following these steps", "based on the passages", "based on the provided passages")) or "following steps based on" in normalized_claim:
            continue
        candidates: list[tuple[float, str, set[str]]] = []
        for evidence in evidence_sentences:
            evidence_terms = _content(evidence)
            precision = len(claim_terms & evidence_terms) / max(1, len(claim_terms))
            recall = len(claim_terms & evidence_terms) / max(1, len(evidence_terms))
            score = 0.8 * precision + 0.2 * recall
            if score > 0:
                candidates.append((score, evidence, evidence_terms))
        candidates.sort(key=lambda item: (-item[0], item[1]))
        selected = candidates[:3]
        evidence_terms = set().union(*(item[2] for item in selected)) if selected else set()
        coverage = len(claim_terms & evidence_terms) / max(1, len(claim_terms))
        best_score = selected[0][0] if selected else 0.0
        claim_numbers = {round(item.value, 12) for item in _numbers(claim)}
        evidence_numbers = {round(item.value, 12) for _, evidence, _ in selected for item in _numbers(evidence)}
        claim_number_units = _number_unit_pairs(claim)
        evidence_number_units = set().union(*(_number_unit_pairs(evidence) for _, evidence, _ in selected)) if selected else set()
        polarity_ok = not _negated(claim) or any(_negated(evidence) for _, evidence, _ in selected)
        quantifier_risk = not any(term in normalized_claim for term in ("some", "may", "might", "depending", "not all")) and any(
            term in _norm(evidence) for _, evidence, _ in selected for term in ("some ", "may ", "might ", "depending", "not all")
        )
        critical_ok = claim_numbers <= evidence_numbers and claim_number_units <= evidence_number_units and polarity_ok and not quantifier_risk
        local_support_ok = best_score >= 0.44 or coverage >= 0.76
        if coverage < 0.58 or not local_support_ok or not critical_ok:
            unresolved_evidence = proved + [item[1] for item in selected]
            return _finish(ProofStatus.UNRESOLVED, "multi_claim", "CLAIM_EVIDENCE_UNRESOLVED", tuple(unresolved_evidence), (f"unproved_claim_sha256={_sha(claim)}",))
        proved.extend(item[1] for item in selected)
    if not proved:
        return _finish(ProofStatus.UNRESOLVED, "multi_claim", "NO_ATOMIC_CLAIM_PROVED")
    return _finish(ProofStatus.PROVED, "multi_claim", "ALL_ATOMIC_CLAIMS_PROVED", tuple(dict.fromkeys(proved)), (f"proved_claims={len(proved)}",))


class StructuralReasoningGate:
    """Deterministic structural proofs that may override similarity only when complete."""

    def evaluate(self, request: StructuralProofRequest) -> StructuralProof:
        if not isinstance(request, StructuralProofRequest) or not all(isinstance(item, str) and item.strip() for item in (request.context, request.question, request.answer)):
            return _finish(ProofStatus.UNRESOLVED, "request", "STRUCTURAL_REQUEST_INVALID")

        proofs: list[StructuralProof] = []
        yes_no = _yes_no_proof(request.context, request.question, request.answer)
        if yes_no.applicable:
            proofs.append(yes_no)

        if _answer_scalar(request.answer) is not None:
            complement = _percent_complement_proof(request.context, request.question, request.answer)
            finance = _finance_formula_proof(request.context, request.question, request.answer)
            table = _direct_table_proof(request.context, request.question, request.answer)
            arithmetic = _arithmetic_proof(request.context, request.question, request.answer)
            financial_table_context = len(_context_lines(request.context)) >= 4 and any(
                term in _norm(request.question + " " + request.context[:500])
                for term in (" fy", "usd", "balance sheet", "financial position", "income statement", "cash flow", "in millions", "in thousands")
            )
            if complement.applicable:
                proofs.append(complement)
            elif finance.applicable:
                proofs.append(finance)
            elif financial_table_context and table.status in {ProofStatus.PROVED, ProofStatus.DISPROVED}:
                proofs.append(table)
            elif arithmetic.applicable:
                proofs.append(arithmetic)
            else:
                proofs.append(table)

        comparison = _comparison_proof(request.context, request.question, request.answer)
        if comparison.applicable:
            proofs.append(comparison)

        relation = _relation_proof(request.context, request.question, request.answer)
        if relation.applicable:
            proofs.append(relation)

        if not yes_no.applicable:
            multi_claim = _multi_claim_proof(request.context, request.question, request.answer)
            if multi_claim.applicable:
                proofs.append(multi_claim)

        if not proofs:
            return _finish(ProofStatus.NOT_APPLICABLE, "none", "NO_STRUCTURAL_FAMILY")
        disproved = next((proof for proof in proofs if proof.status is ProofStatus.DISPROVED), None)
        if disproved is not None:
            return disproved
        unresolved = next((proof for proof in proofs if proof.status is ProofStatus.UNRESOLVED), None)
        if unresolved is not None:
            return unresolved
        proved = proofs[0]
        if all(proof.status is ProofStatus.PROVED for proof in proofs):
            if len(proofs) == 1:
                return proved
            return _finish(
                ProofStatus.PROVED,
                "composed",
                "ALL_APPLICABLE_STRUCTURAL_PROOFS_PASSED",
                tuple(quote for proof in proofs for quote in proof.evidence_quotes),
                tuple(f"{proof.family}:{proof.receipt_sha256}" for proof in proofs),
            )
        return _finish(ProofStatus.UNRESOLVED, "composed", "STRUCTURAL_COMPOSITION_UNRESOLVED")
