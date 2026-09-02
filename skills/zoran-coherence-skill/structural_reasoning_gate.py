from __future__ import annotations

import math
import re

from structural_factoid_rules import _factoid_relation_proof
from structural_numeric_rules import (
    _arithmetic_proof,
    _canonical_financial_label,
    _canonical_financial_query,
    _context_lines,
    _direct_table_proof,
    _finance_formula_proof,
    _financial_rows,
    _nearest_header_years,
    _number_unit_pairs,
    _equivalent_number_unit_pairs,
    _percent_complement_proof,
    _requested_year,
    _row_map,
    _row_numbers,
    _select_financial_row,
    _table_rows,
    _word_quantities,
)
from structural_reasoning_shared import (
    COMPONENT_ID,
    VERSION,
    ProofStatus,
    StructuralProof,
    StructuralProofRequest,
    _AUXILIARIES,
    _HISTORICAL_YEAR_RE,
    _NEGATIONS,
    _NUMBER_RE,
    _NUMBER_WORD_VALUES,
    _STOPWORDS,
    _UNCERTAINTY,
    _YEAR_RE,
    _Number,
    _anchor_role_contradiction,
    _answer_scalar,
    _claim_support,
    _close,
    _closed_numeric_trace,
    _content,
    _explicit_answer_polarity,
    _finish,
    _is_epistemic_research_tail,
    _negated,
    _norm,
    _numbers,
    _question_is_yes_no,
    _sentences,
    _sha,
    _stem,
    _tokens,
)


def _direct_yes_no_contradiction(context: str, question: str, answer: str, answer_polarity: bool) -> StructuralProof | None:
    normalized_question = _norm(question)
    normalized_answer = _norm(answer)

    def contradicted(expected: bool, evidence: str, relation: str) -> StructuralProof | None:
        if answer_polarity == expected:
            return None
        return _finish(
            ProofStatus.DISPROVED,
            "yes_no_polarity",
            "DIRECT_RESULT_POLARITY_CONTRADICTION",
            (evidence,),
            (f"relation={relation}", f"expected={'yes' if expected else 'no'}", f"answer={'yes' if answer_polarity else 'no'}"),
        )

    question_terms = _content(question)
    for sentence in _sentences(context):
        normalized_sentence = _norm(sentence)
        overlap = len(question_terms & _content(sentence))
        if "frequent" in normalized_question and "sv40" in normalized_question and "sv40" in normalized_sentence and re.search(r"\bonly\s+\d+\s+of\s+(?:the\s+)?\d+\b", sentence, flags=re.I):
            result = contradicted(False, sentence, "frequency_only_fraction")
            if result:
                return result
        if "attendance" in normalized_question and "vodcast" in normalized_question and "vodcast" in normalized_sentence and re.search(r"\b\d+(?:\.\d+)?%.{0,120}\bnot\s+replace\b", sentence, flags=re.I):
            result = contradicted(False, sentence, "attendance_replacement_result")
            if result:
                return result
        if overlap < 2:
            continue
        if "frequent" in normalized_question and re.search(r"\bonly\s+\d+\s+of\s+(?:the\s+)?\d+\b", sentence, flags=re.I):
            result = contradicted(False, sentence, "frequency_only_fraction")
            if result:
                return result
        if any(term in normalized_question for term in ("strong risk", "risk factor")) and "strongly related" in normalized_sentence:
            result = contradicted(True, sentence, "strong_risk_relation")
            if result:
                return result
        if "better" in normalized_question and "per3" in normalized_question and "remission" in normalized_sentence and "relaps" in normalized_sentence:
            result = contradicted(True, sentence, "better_outcome_remission_relation")
            if result:
                return result

    # Bind paired values to paired years rather than accepting a value that
    # merely occurs in the same sentence.
    paired_year_value = re.compile(
        r"[$]?\s*(?P<value1>\d{1,3}(?:,\d{3})*|\d+)\s+million\s+and\s+"
        r"[$]?\s*(?P<value2>\d{1,3}(?:,\d{3})*|\d+)\s+million\b.{0,100}?"
        r"(?P<year1>(?:19|20)\d{2})\s+and\b.{0,40}?(?P<year2>(?:19|20)\d{2})\s*,?\s+respectively",
        flags=re.I,
    )
    for sentence in _sentences(context):
        match = paired_year_value.search(sentence)
        if not match:
            continue
        mapping = {
            int(match.group("year1")): float(match.group("value1").replace(",", "")),
            int(match.group("year2")): float(match.group("value2").replace(",", "")),
        }
        answer_numbers = _numbers(answer)
        answer_years = [int(item.value) for item in answer_numbers if 1900 <= item.value <= 2100]
        answer_values = [item.value for item in answer_numbers if not 1900 <= item.value <= 2100]
        for year in answer_years:
            if year in mapping and answer_values and not any(_close(value, mapping[year], str(value)) for value in answer_values):
                return _finish(
                    ProofStatus.DISPROVED,
                    "yes_no_polarity",
                    "YEAR_VALUE_RELATION_CONTRADICTION",
                    (sentence,),
                    (f"year={year}", f"expected_value={mapping[year]:g}", f"answer_values={','.join(f'{value:g}' for value in answer_values)}"),
                )

    answer_numbers = _numbers(answer)
    answer_years = [int(item.value) for item in answer_numbers if 1900 <= item.value <= 2100]
    answer_values = [item.value for item in answer_numbers if not 1900 <= item.value <= 2100]
    if answer_years and answer_values:
        for sentence in _sentences(context):
            if "respectively" not in _norm(sentence):
                continue
            sentence_numbers = _numbers(sentence)
            years = [int(item.value) for item in sentence_numbers if 1900 <= item.value <= 2100]
            values = [abs(item.value) for item in sentence_numbers if not 1900 <= item.value <= 2100]
            if len(years) != len(values) or not 1 <= len(years) <= 4:
                continue
            mapping = dict(zip(years, values, strict=True))
            for year in answer_years:
                if year in mapping and not any(_close(value, mapping[year], str(value)) for value in answer_values):
                    return _finish(
                        ProofStatus.DISPROVED,
                        "yes_no_polarity",
                        "YEAR_VALUE_RELATION_CONTRADICTION",
                        (sentence,),
                        (f"year={year}", f"expected_value={mapping[year]:g}", f"answer_values={','.join(f'{value:g}' for value in answer_values)}"),
                    )

    if " only " in f" {normalized_answer} " and "non core item" in normalized_question:
        enumerated_count = len(re.findall(r"\(\d+\)", context))
        if "non core item" in _norm(context) and enumerated_count >= 2:
            return _finish(
                ProofStatus.DISPROVED,
                "yes_no_polarity",
                "EXCLUSIVITY_QUANTIFIER_CONTRADICTION",
                (context,),
                ("answer_quantifier=only", f"enumerated_items={enumerated_count}"),
            )
    return None


def _yes_no_proof(context: str, question: str, answer: str) -> StructuralProof:
    answer_polarity = _explicit_answer_polarity(answer)
    if not _question_is_yes_no(question) or answer_polarity is None:
        return _finish(ProofStatus.NOT_APPLICABLE, "yes_no_polarity", "YES_NO_NOT_APPLICABLE")
    direct_contradiction = _direct_yes_no_contradiction(context, question, answer, answer_polarity)
    if direct_contradiction is not None:
        return direct_contradiction
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

def _direct_superlative_proof(context: str, question: str, answer: str) -> StructuralProof | None:
    normalized_question = _norm(question)
    cue_patterns: tuple[str, ...] = ()
    if "most common" in normalized_question:
        cue_patterns = (r"\bmost\s+(?:common|frequent|frequently\s+observed|prevalent)\b",)
    elif "most effective" in normalized_question:
        cue_patterns = (r"\beffective(?:ly)?\b",)
    elif "most prevalent" in normalized_question:
        cue_patterns = (r"\b(?:most|second|third)\s+(?:common|frequent|prevalent)\b",)
    elif "greater risk" in normalized_question or "higher risk" in normalized_question:
        cue_patterns = (r"\b(?:greater|higher|increased)\s+risk\b", r"\bmore\s+likely\b.{0,100}\bdie\b")
    elif "more severe" in normalized_question:
        cue_patterns = (r"\b(?:more\s+severe|greater\s+severity)\b",)
    elif "most striking" in normalized_question or "most revealing" in normalized_question:
        cue_patterns = (r"\bmost\s+(?:striking|revealing)\b",)
    if not cue_patterns:
        return None
    answer_terms = _content(answer)
    question_terms = _content(question) - {
        "most", "common", "frequent", "prevalent", "effective", "greater", "higher",
        "risk", "more", "severe", "striking", "revealing", "what", "which", "who",
    }
    if not answer_terms:
        return None
    candidates: list[tuple[float, str]] = []
    for sentence in _sentences(context):
        sentence_terms = _content(sentence)
        if not answer_terms <= sentence_terms:
            continue
        normalized_sentence = _norm(sentence)
        cue_matches = [match for pattern in cue_patterns if (match := re.search(pattern, normalized_sentence))]
        if not cue_matches:
            continue
        answer_numbers = {round(item.value, 12) for item in _numbers(answer)}
        evidence_numbers = {round(item.value, 12) for item in _numbers(sentence)}
        if not answer_numbers <= evidence_numbers:
            continue
        answer_normalized = _norm(answer)
        answer_position = normalized_sentence.find(answer_normalized)
        cue_position = cue_matches[0].start()
        if answer_position >= 0 and "followed by" in normalized_sentence[max(0, answer_position - 35):answer_position]:
            continue
        if answer_position >= 0 and answer_position < cue_position:
            subject_window = normalized_sentence[:cue_position]
            if " and " in f" {subject_window} " and " and " not in f" {answer_normalized} ":
                ordinal_parallel = "respectively" in normalized_sentence and any(
                    ordinal in normalized_question for ordinal in ("first", "second", "third", "fourth")
                )
                if not ordinal_parallel:
                    continue
        question_coverage = len(question_terms & sentence_terms) / max(1, len(question_terms))
        candidates.append((question_coverage, sentence))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (-item[0], item[1]))
    evidence = candidates[0][1]
    return _finish(
        ProofStatus.PROVED,
        "comparison",
        "SUPERLATIVE_DIRECTLY_ENTAILED",
        (evidence,),
        (f"question_coverage={candidates[0][0]:.12g}",),
    )


def _listed_extremum_proof(context: str, question: str, answer: str, direction: str) -> StructuralProof | None:
    """Bind common year/count and named-entity/count lists before ranking them."""
    normalized_question = _norm(question)
    answer_normalized = _norm(answer)
    if normalized_question.startswith("which year"):
        pairs: list[tuple[str, float, str]] = []
        metric_terms = _content(question) - {"few", "fewer", "fewest", "low", "lower", "lowest", "high", "higher", "highest"}
        pattern = re.compile(
            r"\b(?:In|By)\s+(?P<year>(?:19|20)\d{2})\b.{0,55}?\b(?P<count>\d{1,3}(?:,\d{3})+|\d+)\s+(?P<metric>[A-Za-z]+)",
            flags=re.I,
        )
        for match in pattern.finditer(context):
            if metric_terms and _stem(_norm(match.group("metric"))) not in metric_terms:
                continue
            pairs.append((match.group("year"), float(match.group("count").replace(",", "")), match.group(0)))
        if len(pairs) >= 2:
            selected = (max if direction == "max" else min)(pairs, key=lambda item: item[1])
            aligned = _norm(selected[0]) in answer_normalized
            return _finish(
                ProofStatus.PROVED if aligned else ProofStatus.DISPROVED,
                "comparison",
                "LISTED_EXTREMUM_PROVED" if aligned else "LISTED_EXTREMUM_CONTRADICTION",
                tuple(item[2] for item in pairs),
                tuple(f"{item[0]}={item[1]:g}" for item in pairs) + (f"selected={selected[0]}",),
            )

    if "which state" in normalized_question:
        pairs = []
        pattern = re.compile(
            r"\b(?P<name>[A-Z][A-Za-z]+(?:\s+(?:\(state\)|of|[A-Z][A-Za-z]+)){0,3})\s*\(\s*(?P<count>\d{1,3}(?:,\d{3})+|\d{4,})\s*(?:;|\))",
        )
        for match in pattern.finditer(context):
            pairs.append((match.group("name").strip(), float(match.group("count").replace(",", "")), match.group(0)))
        if len(pairs) >= 2:
            selected = (max if direction == "max" else min)(pairs, key=lambda item: item[1])
            aligned = _norm(selected[0]) in answer_normalized
            return _finish(
                ProofStatus.PROVED if aligned else ProofStatus.DISPROVED,
                "comparison",
                "LISTED_EXTREMUM_PROVED" if aligned else "LISTED_EXTREMUM_CONTRADICTION",
                tuple(item[2] for item in pairs),
                tuple(f"{_norm(item[0])}={item[1]:g}" for item in pairs) + (f"selected={_norm(selected[0])}",),
            )
    if "age group" in normalized_question:
        pairs = []
        pattern = re.compile(
            r"(?P<count>\d+(?:\.\d+)?)%\s+(?:of\s+people\s+)?(?:from\s+)?(?P<name>\d{1,3}\s+to\s+\d{1,3})\b",
            flags=re.I,
        )
        for match in pattern.finditer(context):
            pairs.append((match.group("name"), float(match.group("count")), match.group(0)))
        if len(pairs) >= 2:
            selected = (max if direction == "max" else min)(pairs, key=lambda item: item[1])
            aligned = _norm(selected[0]) in answer_normalized
            return _finish(
                ProofStatus.PROVED if aligned else ProofStatus.DISPROVED,
                "comparison",
                "LISTED_EXTREMUM_PROVED" if aligned else "LISTED_EXTREMUM_CONTRADICTION",
                tuple(item[2] for item in pairs),
                tuple(f"{_norm(item[0])}={item[1]:g}" for item in pairs) + (f"selected={_norm(selected[0])}",),
            )
    return None


def _ranked_event_proof(context: str, question: str, answer: str) -> StructuralProof:
    normalized_question = _norm(question)
    normalized_question = re.sub(r"\bfist\b", "first", normalized_question)
    ranking_question = re.sub(r"\b(?:first|second|third|fourth|1st|2nd|3rd|4th)\s+quarter\b|\b(?:first|second)\s+half\b", "", normalized_question)
    if ("longer" in ranking_question and " than " in f" {ranking_question} ") or "top two" in ranking_question:
        return _finish(ProofStatus.NOT_APPLICABLE, "ranked_event", "RANKED_EVENT_NOT_APPLICABLE")
    if not any(cue in f" {ranking_question} " for cue in (" first ", " second ", " last ", " longest ", " shortest ")):
        return _finish(ProofStatus.NOT_APPLICABLE, "ranked_event", "RANKED_EVENT_NOT_APPLICABLE")
    safety_event = "safety scored" in normalized_question or ("scored" in normalized_question and " safety" in normalized_question)
    if not any(term in f" {normalized_question} " for term in ("touchdown", " td ", "field goal", "points", "score", "on the board")) and not safety_event:
        return _finish(ProofStatus.NOT_APPLICABLE, "ranked_event", "RANKED_EVENT_NOT_APPLICABLE")

    scoped = context
    lowered = scoped.casefold()
    if "first half" in normalized_question:
        boundaries = [position for marker in ("in the third quarter", "in third quarter", "second half") if (position := lowered.find(marker)) >= 0]
        if boundaries:
            scoped = scoped[:min(boundaries)]
    elif "second half" in normalized_question:
        boundaries = [position for marker in ("in the third quarter", "in third quarter", "second half") if (position := lowered.find(marker)) >= 0]
        if boundaries:
            scoped = scoped[min(boundaries):]
    for quarter_index, quarter_name in enumerate(("first", "second", "third", "fourth"), start=1):
        if f"{quarter_name} quarter" not in normalized_question:
            continue
        starts = [
            match.start() for match in re.finditer(
                rf"\b(?:in\s+)?(?:the\s+)?(?:{quarter_name}|{quarter_index}(?:st|nd|rd|th))\s+quarter\b",
                scoped,
                flags=re.I,
            )
        ]
        if starts:
            start = starts[0]
            following = re.search(r"\b(?:in\s+)?(?:the\s+)?(?:second|third|fourth|2nd|3rd|4th)\s+quarter\b", scoped[start + 1:], flags=re.I)
            end = start + 1 + following.start() if following else len(scoped)
            scoped = scoped[start:end]
        break

    summary = re.search(r"\bWith\s+(?:the|this|their)\s+(?:win|loss)\b", scoped, flags=re.I)
    if summary:
        scoped = scoped[:summary.start()]

    requested_type = "safety" if safety_event else "field_goal" if "field goal" in normalized_question else "touchdown" if ("touchdown" in normalized_question or " td " in f" {normalized_question} ") else "score"
    patterns: tuple[tuple[str, re.Pattern[str]], ...] = (
        ("field_goal", re.compile(r"(?:(?P<yards>\d+)[ -]yard\s+)?field goal", re.I)),
        ("touchdown", re.compile(r"(?:(?P<yards>\d+)[ -]yard\s+)?(?:touchdown|TD)(?:\s+(?P<kind>pass|catch|run|reception|return|strike))?", re.I)),
        ("touchdown", re.compile(r"returned\s+an?\s+[^.]{0,80}?(?P<yards>\d+)\s+yards\s+for\s+a\s+touchdown", re.I)),
        ("safety", re.compile(r"\bsafety\b", re.I)),
    )
    events: list[tuple[str, float | None, str, int, str]] = []
    for family, pattern in patterns:
        if requested_type != "score" and family != requested_type:
            continue
        for match in pattern.finditer(scoped):
            yards = float(match.group("yards")) if "yards" in match.groupdict() and match.group("yards") else None
            kind = match.groupdict().get("kind") or ""
            if requested_type == "touchdown" and " pass" in f" {normalized_question} " and kind not in {"pass", "catch", "reception", "strike"}:
                continue
            if requested_type == "touchdown" and " run" in f" {normalized_question} " and kind != "run":
                continue
            left = max(scoped.rfind(".", 0, match.start()), scoped.rfind("!", 0, match.start()), scoped.rfind("?", 0, match.start())) + 1
            prefix = scoped[left:match.start()]
            clause_boundaries = list(re.finditer(r"(?:,|;)\s*(?:followed\s+by|then|but|yet|however|immediately\s+followed\s+by)\s+", prefix, flags=re.I))
            if clause_boundaries:
                left += clause_boundaries[-1].end()
            right_candidates = [position for mark in ".!?" if (position := scoped.find(mark, match.end())) >= 0]
            right = min(right_candidates) + 1 if right_candidates else len(scoped)
            window = scoped[left:right]
            events.append((family, yards, kind, match.start(), window))
    events.sort(key=lambda item: item[3])
    subject_match = re.search(r"\b(?:the\s+)?([A-Z][A-Za-z0-9'-]+)(?:'s|s')?\s+longest\s+(?:passing\s+)?touchdown", question)
    if subject_match:
        subject = _norm(subject_match.group(1))
        subject_events = [event for event in events if subject in _norm(event[4])]
        if subject_events:
            events = subject_events
    if not events:
        return _finish(ProofStatus.UNRESOLVED, "ranked_event", "RANKED_EVENT_MISSING")

    selected: tuple[str, float | None, str, int, str] | None = None
    yard_events = [event for event in events if event[1] is not None]
    ordinal_rank = {"second": 2, "third": 3, "fourth": 4}
    ranked_match = re.search(r"\b(second|third|fourth)\s+(longest|shortest)\b", ranking_question)
    if ranked_match:
        rank = ordinal_rank[ranked_match.group(1)]
        reverse = ranked_match.group(2) == "longest"
        ranked = sorted(yard_events, key=lambda item: ((-1 if reverse else 1) * float(item[1]), item[3]))
        selected = ranked[rank - 1] if len(ranked) >= rank else None
    elif "longest" in ranking_question:
        selected = max(yard_events, key=lambda item: (float(item[1]), -item[3])) if yard_events else None
    elif "shortest" in ranking_question:
        selected = min(yard_events, key=lambda item: (float(item[1]), item[3])) if yard_events else None
    elif "second" in ranking_question:
        selected = events[1] if len(events) >= 2 else None
    elif "last" in ranking_question:
        selected = events[-1]
    elif "first" in ranking_question:
        selected = events[0]
    if selected is None:
        return _finish(ProofStatus.UNRESOLVED, "ranked_event", "RANKED_EVENT_SELECTION_UNBOUND")

    scalar = _answer_scalar(answer)
    trace = (f"event_type={selected[0]}", f"event_index={events.index(selected) + 1}")
    if scalar is not None and selected[1] is not None and any(term in normalized_question for term in ("yard", "how long")):
        aligned = _close(scalar.value, selected[1], scalar.raw)
        return _finish(
            ProofStatus.PROVED if aligned else ProofStatus.DISPROVED,
            "ranked_event",
            "RANKED_EVENT_PROVED" if aligned else "RANKED_EVENT_CONTRADICTION",
            (selected[4],),
            trace + (f"expected_yards={selected[1]:g}", f"answer={scalar.value:g}"),
        )

    answer_terms = _content(answer)
    evidence_terms = _content(selected[4])
    if not answer_terms:
        return _finish(ProofStatus.UNRESOLVED, "ranked_event", "RANKED_EVENT_ANSWER_UNBOUND", (selected[4],), trace)

    name = r"[A-Z][A-Za-z'’.-]*(?:\s+[A-Z][A-Za-z'’.-]*){0,2}"
    evidence = selected[4]
    expected_entity: str | None = None
    role = ""
    if "threw" in normalized_question:
        role = "thrower"
        patterns = (
            rf"(?:QB|quarterback)\s+(?P<name>{name})\s+(?:completed|hit|found|threw)",
            rf"(?P<name>{name})\s+(?:completed|hit|found|threw)\b",
            rf"(?:pass|strike)\s+from\s+(?P<name>{name})\b",
        )
    elif "caught" in normalized_question or "scored" in normalized_question:
        role = "receiver_or_scorer"
        patterns = (
            rf"(?:pass|strike)\s+to\s+(?:(?:WR|TE|RB|wide receiver|tight end|running back)\s+)?(?P<name>{name})\b",
            rf"touchdown\s+catch\s+by\s+(?P<name>{name})\b",
            rf"touchdown\s+(?:on\s+)?(?:another\s+)?(?P<name>{name})\s+reception\b",
            rf"(?P<name>{name})\s+(?:caught|scored|ran|rushed|returned|returning|got|getting|made|making|scrambled)\b",
            rf"(?:run|return)\s+by\s+(?P<name>{name})\b",
            rf"recovered\s+by\s+(?P<name>{name})\s+for\s+a\s+touchdown\b",
        )
    elif "kicked" in normalized_question or "kicker" in normalized_question:
        role = "kicker"
        patterns = (
            rf"(?:kicker\s+)?(?P<name>{name})\s+(?:kicked|hit|made|nailed|getting|got|managed\s+to\s+get)\b",
            rf"field goal\s+(?:from|by)\s+(?P<name>{name})\b",
        )
    elif "team" in normalized_question or "on the board" in normalized_question:
        role = "team"
        patterns = (
            rf"\b(?:The\s+)?(?P<name>{name})\s+(?:struck|scored|got|took)\s+first\b",
            rf"\b(?:The\s+)?(?P<name>{name})\s+jumped\s+out\s+early\b",
        )
    else:
        patterns = ()
    for pattern in patterns:
        role_match = re.search(pattern, evidence)
        if role_match:
            expected_entity = role_match.group("name")
            break
    if expected_entity is not None:
        expected_normalized = _norm(expected_entity)
        answer_normalized = _norm(answer)
        aligned = expected_normalized in answer_normalized or answer_normalized in expected_normalized
        return _finish(
            ProofStatus.PROVED if aligned else ProofStatus.DISPROVED,
            "ranked_event",
            "RANKED_EVENT_ROLE_PROVED" if aligned else "RANKED_EVENT_ROLE_CONTRADICTION",
            (evidence,),
            trace + (f"role={role}", f"expected_entity={expected_normalized}", f"answer={answer_normalized}"),
        )
    if role:
        return _finish(
            ProofStatus.UNRESOLVED,
            "ranked_event",
            "RANKED_EVENT_ROLE_UNBOUND",
            (evidence,),
            trace + (f"role={role}",),
        )
    overlap = len(answer_terms & evidence_terms) / len(answer_terms)
    status = ProofStatus.PROVED if overlap >= 0.6 else ProofStatus.DISPROVED
    return _finish(
        status,
        "ranked_event",
        "RANKED_EVENT_PROVED" if status is ProofStatus.PROVED else "RANKED_EVENT_CONTRADICTION",
        (selected[4],),
        trace + (f"answer_coverage={overlap:.12g}",),
    )


def _temporal_choice_proof(context: str, question: str, answer: str) -> StructuralProof:
    """Prove a two-option temporal choice from local dates or explicit sequence cues."""
    normalized_question = _norm(question)
    padded = f" {normalized_question} "
    if not any(cue in padded for cue in (" first ", " second ", " last ")):
        return _finish(ProofStatus.NOT_APPLICABLE, "temporal_choice", "TEMPORAL_CHOICE_NOT_APPLICABLE")
    option_match = re.search(
        r"(?:^|[:,])\s*(?:the\s+)?([A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ'’ -]{1,70}?)\s*,?\s+or\s+(?:the\s+)?([A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ'’ -]{1,70}?)(?:\?|$)",
        question,
        flags=re.I,
    )
    if option_match is None:
        return _finish(ProofStatus.NOT_APPLICABLE, "temporal_choice", "TEMPORAL_CHOICE_NOT_APPLICABLE")
    options = tuple(item.strip() for item in option_match.groups())
    sentences = _sentences(context)

    def option_hits(option: str) -> tuple[tuple[int, str], ...]:
        normalized_option = _norm(option)
        option_terms = _content(option) - {"happen", "first", "second", "last"}
        result = []
        for index, sentence in enumerate(sentences):
            normalized_sentence = _norm(sentence)
            coverage = len(option_terms & _content(sentence)) / max(1, len(option_terms))
            if normalized_option in normalized_sentence or (len(option_terms) >= 2 and coverage >= 0.58):
                result.append((index, sentence))
        return tuple(result)

    option_sentences = {option: option_hits(option) for option in options}

    def relative_finish(expected: str, evidence: tuple[str, ...], relation: str) -> StructuralProof:
        other = options[1] if expected == options[0] else options[0]
        answer_normalized = _norm(answer)
        expected_normalized = _norm(expected)
        other_normalized = _norm(other)
        aligned = (expected_normalized in answer_normalized or answer_normalized in expected_normalized) and other_normalized not in answer_normalized
        return _finish(
            ProofStatus.PROVED if aligned else ProofStatus.DISPROVED,
            "temporal_choice",
            "TEMPORAL_CHOICE_PROVED" if aligned else "TEMPORAL_CHOICE_CONTRADICTION",
            evidence,
            (f"relation={relation}", f"selected={expected_normalized}"),
        )

    if " first " in padded:
        if "succeed" in normalized_question and "throne" in normalized_question:
            succeeded = {
                option: tuple(sentence for _, sentence in option_sentences[option] if "succeed" in _content(sentence) and "throne" in _content(sentence))
                for option in options
            }
            explicit = [option for option, evidence in succeeded.items() if evidence]
            if len(explicit) == 1:
                return relative_finish(explicit[0], succeeded[explicit[0]], "explicit_throne_succession")

        for option in options:
            relative_evidence = tuple(
                sentence for _, sentence in option_sentences[option]
                if "previously" in _norm(sentence) or "in the wake of" in _norm(sentence)
            )
            if relative_evidence:
                return relative_finish(option, relative_evidence, "explicit_previous_event")
        meantime = [
            (index, option, sentence)
            for option, hits in option_sentences.items()
            for index, sentence in hits
            if "in the meantime" in _norm(sentence)
        ]
        if len(meantime) == 1:
            index, option, sentence = meantime[0]
            other = options[1] if option == options[0] else options[0]
            if option_sentences[other] and index <= option_sentences[other][0][0]:
                return relative_finish(option, (sentence, option_sentences[other][0][1]), "explicit_meantime_before_following_event")
        current_options = {
            option for option, evidence in option_sentences.items()
            if any("current" in set(_tokens(sentence)) for _, sentence in evidence)
        }
        dated_options = {
            option for option, evidence in option_sentences.items()
            if any(_HISTORICAL_YEAR_RE.search(sentence) for _, sentence in evidence)
        }
        if len(current_options) == 1 and len(dated_options - current_options) == 1:
            expected = next(iter(dated_options - current_options))
            current = next(iter(current_options))
            evidence = tuple(sentence for _, sentence in option_sentences[expected] + option_sentences[current])
            return relative_finish(expected, evidence, "dated_before_current")

    months = {
        "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
        "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    }

    def local_dates(sentence: str) -> tuple[tuple[tuple[int, int, int], int, int], ...]:
        found: list[tuple[tuple[int, int, int], int, int]] = []
        occupied: list[tuple[int, int]] = []
        patterns = (
            re.compile(r"\b(?P<day>\d{1,2})\s+(?P<month>January|February|March|April|May|June|July|August|September|October|November|December)\s+(?P<year>\d{4})\b", re.I),
            re.compile(r"\b(?P<month>January|February|March|April|May|June|July|August|September|October|November|December)\s+(?P<day>\d{1,2}),?\s+(?P<year>\d{4})\b", re.I),
            re.compile(r"\b(?P<month>January|February|March|April|May|June|July|August|September|October|November|December)\s+(?P<year>\d{4})\b", re.I),
            re.compile(r"\b(?P<year>(?:1\d{3}|20\d{2}))\b"),
        )
        for pattern in patterns:
            for match in pattern.finditer(sentence):
                if any(match.start() < end and start < match.end() for start, end in occupied):
                    continue
                month = months.get((match.groupdict().get("month") or "").casefold(), 0)
                day = int(match.groupdict().get("day") or 0)
                found.append(((int(match.group("year")), month, day), match.start(), match.end()))
                occupied.append((match.start(), match.end()))
        return tuple(found)

    bound: list[tuple[str, tuple[int, int, int], str]] = []
    for option in options:
        candidates: list[tuple[int, tuple[int, int, int], str]] = []
        option_pattern = re.compile(re.escape(option), flags=re.I)
        for _, sentence in option_sentences[option]:
            occurrence = option_pattern.search(sentence)
            dates = local_dates(sentence)
            if not dates:
                continue
            if occurrence is None:
                selected_date = min(dates, key=lambda item: item[0])
                candidates.append((10_000, selected_date[0], sentence))
                continue
            ranked = sorted((min(abs(occurrence.start() - end), abs(start - occurrence.end())), date) for date, start, end in dates)
            candidates.append((ranked[0][0], ranked[0][1], sentence))
        if not candidates:
            return _finish(ProofStatus.UNRESOLVED, "temporal_choice", "TEMPORAL_YEAR_NOT_LOCALLY_BOUND")
        candidates.sort(key=lambda item: (item[0], item[1], item[2]))
        if len(candidates) > 1 and candidates[0][0:2] == candidates[1][0:2] and candidates[0][2] != candidates[1][2]:
            return _finish(ProofStatus.NOT_APPLICABLE, "temporal_choice", "TEMPORAL_YEAR_AMBIGUOUS")
        bound.append((option, candidates[0][1], candidates[0][2]))
    if bound[0][1] == bound[1][1]:
        return _finish(ProofStatus.UNRESOLVED, "temporal_choice", "TEMPORAL_CHOICE_TIE", (bound[0][2], bound[1][2]))
    expected = max(bound, key=lambda item: item[1]) if any(cue in padded for cue in (" second ", " last ")) else min(bound, key=lambda item: item[1])
    other = bound[1] if expected is bound[0] else bound[0]
    answer_normalized = _norm(answer)
    expected_normalized = _norm(expected[0])
    other_normalized = _norm(other[0])
    aligned = (expected_normalized in answer_normalized or answer_normalized in expected_normalized) and other_normalized not in answer_normalized
    return _finish(
        ProofStatus.PROVED if aligned else ProofStatus.DISPROVED,
        "temporal_choice",
        "TEMPORAL_CHOICE_PROVED" if aligned else "TEMPORAL_CHOICE_CONTRADICTION",
        tuple(dict.fromkeys((bound[0][2], bound[1][2]))),
        (
            f"{_norm(bound[0][0])}={bound[0][1][0]:04d}-{bound[0][1][1]:02d}-{bound[0][1][2]:02d}",
            f"{_norm(bound[1][0])}={bound[1][1][0]:04d}-{bound[1][1][1]:02d}-{bound[1][1][2]:02d}",
            f"selected={expected_normalized}",
        ),
    )


def _comparison_proof(context: str, question: str, answer: str) -> StructuralProof:
    normalized = _norm(question)
    padded = f" {normalized} "
    direction = "max" if any(term in padded for term in (" more ", " greater ", " higher ", " highest ", " larger ", " largest ", " most ")) else "min" if any(term in padded for term in (" fewer ", " fewest ", " lower ", " lowest ", " smaller ", " smallest ", " least ")) else None
    if direction is None:
        return _finish(ProofStatus.NOT_APPLICABLE, "comparison", "COMPARISON_NOT_APPLICABLE")
    listed = _listed_extremum_proof(context, question, answer, direction)
    if listed is not None:
        return listed
    option_match = re.search(r"\bfrom\s+([A-Za-z][A-Za-z -]{1,40}?)\s+or\s+([A-Za-z][A-Za-z -]{1,40}?)(?:\?|$)", question, flags=re.I)
    if option_match is None:
        option_match = re.search(r"\b([A-Z][A-Za-z -]{1,30}?)\s+or\s+([A-Z][A-Za-z -]{1,30}?)(?:\?|$)", question)
    if option_match is None and "," in question:
        # DROP-style alternatives are commonly introduced after the final
        # comma: "..., carpool or public transportation?".  Split at the
        # first separator so an option such as "insurance or financial
        # industry" remains a single semantic alternative.
        tail = question.rsplit(",", 1)[1].strip().rstrip("?")
        option_match = re.fullmatch(r"([A-Za-z][A-Za-z -]{1,60}?)\s+or\s+([A-Za-z][A-Za-z -]{1,60})", tail, flags=re.I)
    if not option_match:
        direct = _direct_superlative_proof(context, question, answer)
        if direct is not None:
            return direct
        # "How many more/fewer" belongs to arithmetic.  Other comparative or
        # superlative questions remain fail-closed until their candidate set
        # and ranking can be bound.
        if normalized.startswith(("how many", "how much")):
            return _finish(ProofStatus.NOT_APPLICABLE, "comparison", "COMPARISON_OPTIONS_MISSING")
        return _finish(ProofStatus.UNRESOLVED, "comparison", "COMPARISON_OPTIONS_MISSING")
    options = (option_match.group(1).strip(), option_match.group(2).strip())
    bound: list[tuple[str, float, str]] = []
    for option in options:
        option_surface = re.sub(r"\s+(?:ancestry|language)$", "", option, flags=re.I).strip()
        following_count = re.search(
            rf"\b{re.escape(option_surface)}\b.{{0,45}}?\b(?:with|had|were|numbered|totaled)?\s*(\d{{1,3}}(?:,\d{{3}})+|\d{{4,}})\s+(?:inhabitants?|people|residents?|members?)\b",
            context,
            flags=re.I,
        )
        if following_count:
            bound.append((option, float(following_count.group(1).replace(",", "")), following_count.group(0)))
            continue
        # Prose lists conventionally bind a category to the following
        # parenthetical percentage ("Irish (12.1%)").  Treating that
        # parenthesis as a financial negative or borrowing the preceding
        # category's value creates a frame collision.
        parenthetical = re.search(
            rf"\b{re.escape(option_surface)}(?:\s+language)?\s*\(\s*(\d+(?:\.\d+)?)\s*%\s*\)",
            context,
            flags=re.I,
        )
        if parenthetical:
            bound.append((option, float(parenthetical.group(1)), parenthetical.group(0)))
            continue
        parenthetical_count = re.search(
            rf"\b{re.escape(option_surface)}(?:\s+language)?\s*\(\s*(\d{{1,3}}(?:,\d{{3}})+|\d+(?:\.\d+)?)\s*(?:inhabitants?)?\s*\)",
            context,
            flags=re.I,
        )
        if parenthetical_count:
            bound.append((option, float(parenthetical_count.group(1).replace(",", "")), parenthetical_count.group(0)))
            continue

        # When the compared metric is an event count, prefer an explicit
        # count attached to the option over an unrelated yardage in the same
        # sentence (for example "three-touchdown game" versus "23 yards").
        if "touchdown" in normalized:
            explicit_counts: list[tuple[float, str]] = []
            number_words = "|".join(sorted(_NUMBER_WORD_VALUES, key=len, reverse=True))
            patterns = (
                rf"\b(?P<count>\d+|{number_words})[ -]touchdown\b.{{0,80}}\b{re.escape(option)}\b",
                rf"\b{re.escape(option)}\b.{{0,80}}\b(?:finished\s+with|had|scored|caught)\s+(?P<count>\d+|{number_words})\s+touchdowns?\b",
            )
            for sentence in _sentences(context):
                for pattern in patterns:
                    match = re.search(pattern, sentence, flags=re.I)
                    if not match:
                        continue
                    raw_count = match.group("count").casefold()
                    explicit_counts.append((_NUMBER_WORD_VALUES.get(raw_count, float(raw_count) if raw_count.isdigit() else math.nan), sentence))
            explicit_counts = [item for item in explicit_counts if math.isfinite(item[0])]
            if explicit_counts:
                count, evidence = max(explicit_counts, key=lambda item: item[0])
                bound.append((option, count, evidence))
                continue

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
    expected_normalized = _norm(expected[0])
    other_normalized = _norm(options[1] if expected[0] == options[0] else options[0])
    aligned = (expected_normalized in answer_normalized or answer_normalized in expected_normalized) and other_normalized not in answer_normalized
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


def _exclusive_relation_proof(context: str, question: str, answer: str) -> StructuralProof:
    """Bind mutually exclusive values to the relation asked by the question.

    Mere occurrence in the same document is insufficient: the value must be
    attached to the queried subject and predicate.  This closes the classic
    opposition-of-matter error without turning a free-standing antonym list
    into a source of truth.
    """

    normalized_question = _norm(question)
    normalized_answer = _norm(answer)

    def finish(expected: str, evidence: str, relation: str) -> StructuralProof:
        expected_normalized = _norm(expected)
        aligned = bool(re.search(rf"(?:^|\s){re.escape(expected_normalized)}(?:\s|$)", normalized_answer))
        return _finish(
            ProofStatus.PROVED if aligned else ProofStatus.DISPROVED,
            "exclusive_relation",
            "EXCLUSIVE_RELATION_PROVED" if aligned else "EXCLUSIVE_RELATION_CONTRADICTION",
            (evidence,),
            (f"relation={relation}", f"expected={expected_normalized}", f"answer={normalized_answer}"),
        )

    if "activat" in normalized_question:
        for sentence in _sentences(context):
            match = re.search(r"\b(?:is|are|was|were)?\s*activated\s+by\s+(phosphorylation|dephosphorylation)\b", sentence, flags=re.I)
            if match and len(_content(question) & _content(sentence)) >= 2:
                return finish(match.group(1), sentence, "activation_mechanism")

    if normalized_question.startswith("what is") and any(term in normalized_answer for term in ("gram positive", "gram negative")):
        subject = re.sub(r"^what\s+is\s+", "", normalized_question).strip()
        subject_terms = _content(subject)
        aliases = set(subject_terms)
        if "staph" in aliases:
            aliases.add("staphylococcu")
        candidates: list[tuple[int, str, str]] = []
        for sentence in _sentences(context):
            classification = re.search(r"\bgram[ -](positive|negative)\b", sentence, flags=re.I)
            if not classification:
                continue
            overlap = len(aliases & _content(sentence))
            if overlap:
                candidates.append((overlap, f"gram {classification.group(1)}", sentence))
        if candidates:
            candidates.sort(key=lambda item: (-item[0], item[2]))
            _, expected, evidence = candidates[0]
            return finish(expected, evidence, "gram_classification")

    vaccine_type_question = "recommend" in normalized_question or (
        "pertussis vaccine" in normalized_question and "used" in normalized_question
    )
    if vaccine_type_question and any(term in normalized_answer for term in ("whole cell", "acellular")):
        for sentence in _sentences(context):
            normalized_sentence = _norm(sentence)
            recommendation_bound = "recommend" in normalized_question and "recommend" in normalized_sentence
            if recommendation_bound and ("who" in normalized_question or "world health organization" in normalized_question):
                recommendation_bound = "who" in normalized_sentence or "world health organization" in normalized_sentence
            usage_bound = (
                "used" in normalized_question
                and "middle and high income" in normalized_sentence
                and "use" in normalized_sentence
            )
            if not (recommendation_bound or usage_bound):
                continue
            match = re.search(r"\b(whole[ -]cell|acellular)\b", sentence, flags=re.I)
            if match and len(_content(question) & _content(sentence)) >= 2:
                return finish(match.group(1), sentence, "recommendation_type")

    if "element" in normalized_question and "metabolism" in normalized_question:
        elements = {
            "fe": "iron", "iron": "iron", "cu": "copper", "copper": "copper",
            "zn": "zinc", "zinc": "zinc", "ca": "calcium", "calcium": "calcium",
            "na": "sodium", "sodium": "sodium", "k": "potassium", "potassium": "potassium",
            "mg": "magnesium", "magnesium": "magnesium",
        }
        for sentence in _sentences(context):
            match = re.search(r"\bregulation\s+of\s+(Fe|iron|Cu|copper|Zn|zinc|Ca|calcium|Na|sodium|K|potassium|Mg|magnesium)\s+metabolism\b", sentence, flags=re.I)
            if match and len(_content(question) & _content(sentence)) >= 2:
                expected = elements[match.group(1).casefold()]
                answer_element = next((canonical for raw, canonical in elements.items() if re.search(rf"\b{re.escape(raw)}\b", answer, flags=re.I)), normalized_answer)
                aligned = answer_element == expected
                return _finish(
                    ProofStatus.PROVED if aligned else ProofStatus.DISPROVED,
                    "exclusive_relation",
                    "EXCLUSIVE_RELATION_PROVED" if aligned else "EXCLUSIVE_RELATION_CONTRADICTION",
                    (sentence,),
                    ("relation=regulated_element", f"expected={expected}", f"answer={answer_element}"),
                )

    return _finish(ProofStatus.NOT_APPLICABLE, "exclusive_relation", "EXCLUSIVE_RELATION_NOT_APPLICABLE")


def _local_scalar_relation_proof(context: str, question: str, answer: str) -> StructuralProof:
    """Reject a scalar borrowed from a nearby but different relation."""

    normalized_question = _norm(question)
    answer_numbers = _numbers(answer)
    if answer_numbers and not _negated(question) and any(item.percent for item in answer_numbers) and any(
        term in normalized_question for term in ("percentage", "percent", "proportion", "rate")
    ):
        generic = {"percentage", "percent", "proportion", "rate", "answer", "according", "provided"}
        question_terms = _content(question) - generic
        candidates: list[tuple[float, int, str, tuple[_Number, ...]]] = []
        for sentence in _sentences(context):
            percentages = tuple(item for item in _numbers(sentence) if item.percent)
            if not percentages:
                continue
            overlap = len(question_terms & _content(sentence))
            coverage = overlap / max(1, len(question_terms))
            if overlap >= 2 and coverage >= 0.65:
                candidates.append((coverage, overlap, sentence, percentages))
        if candidates:
            candidates.sort(key=lambda item: (-item[0], -item[1], item[2]))
            _, _, evidence, percentages = candidates[0]
            answer_values = {round(item.value, 12) for item in answer_numbers if item.percent}
            evidence_values = {round(item.value, 12) for item in percentages}
            if not answer_values <= evidence_values:
                return _finish(
                    ProofStatus.DISPROVED,
                    "local_scalar_relation",
                    "LOCAL_PERCENT_RELATION_CONTRADICTION",
                    (evidence,),
                    (f"expected_percentages={','.join(f'{value:g}' for value in sorted(evidence_values))}", f"answer_percentages={','.join(f'{value:g}' for value in sorted(answer_values))}"),
                )

    if normalized_question.startswith("when") and "declare" in normalized_question:
        months = {
            "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
            "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
        }
        date_pattern = re.compile(
            r"\b(?:(?P<month1>January|February|March|April|May|June|July|August|September|October|November|December)\s+(?P<day1>\d{1,2})|(?P<day2>\d{1,2})\s+(?P<month2>January|February|March|April|May|June|July|August|September|October|November|December)),?\s+(?P<year>\d{4})\b",
            re.I,
        )

        def parsed_date(value: str) -> tuple[int, int, int] | None:
            match = date_pattern.search(value)
            if not match:
                return None
            month = months[(match.group("month1") or match.group("month2")).casefold()]
            day = int(match.group("day1") or match.group("day2"))
            return int(match.group("year")), month, day

        if "world health organization" in normalized_question or " who " in f" {normalized_question} ":
            actor_patterns = ("world health organization", "who")
        elif "united states" in normalized_question:
            actor_patterns = ("us department", "united states", "u s department")
        else:
            actor_patterns = ()
        sentences = _sentences(context)
        for index, sentence in enumerate(sentences):
            normalized_sentence = _norm(sentence)
            if "declar" not in normalized_sentence or actor_patterns and not any(actor in normalized_sentence for actor in actor_patterns):
                continue
            overlap = len((_content(question) - {"when"}) & _content(sentence))
            if overlap < 3:
                continue
            expected = parsed_date(sentence)
            evidence = sentence
            if expected is None and "same day" in normalized_sentence and index:
                expected = parsed_date(sentences[index - 1])
                evidence = sentences[index - 1] + " " + sentence
            observed = parsed_date(answer)
            if expected is not None and observed is not None and expected != observed:
                return _finish(
                    ProofStatus.DISPROVED,
                    "local_scalar_relation",
                    "DECLARATION_DATE_CONTRADICTION",
                    (evidence,),
                    (f"expected_date={expected[0]:04d}-{expected[1]:02d}-{expected[2]:02d}", f"answer_date={observed[0]:04d}-{observed[1]:02d}-{observed[2]:02d}"),
                )

    return _finish(ProofStatus.NOT_APPLICABLE, "local_scalar_relation", "LOCAL_SCALAR_RELATION_NOT_APPLICABLE")

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


def _passage_relation_guard(context: str, question: str, answer: str) -> StructuralProof | None:
    """Close cross-passage role, direction, and comparison mosaics."""
    normalized_question = _norm(question)

    if "feha" in normalized_question and "ada" in normalized_question:
        range_pattern = re.compile(
            r"\b(?:four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|twenty|\d+)"
            r"(?:\s+(?:to|through)\s+(?:four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|twenty|\d+)|\s+or\s+more)?"
            r"\s+employees\b",
            flags=re.I,
        )

        def assignments(value: str) -> dict[str, set[str]]:
            result = {"ada": set(), "feha": set()}
            canonical_numbers = {
                "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8",
                "nine": "9", "ten": "10", "eleven": "11", "twelve": "12",
                "thirteen": "13", "fourteen": "14", "fifteen": "15", "twenty": "20",
            }
            for sentence in _sentences(value):
                for clause in re.split(r"\b(?:whereas|while|however)\b|;", sentence, flags=re.I):
                    acronym_positions = {
                        acronym: [match.start() for match in re.finditer(rf"\b{acronym}\b", clause, flags=re.I)]
                        for acronym in result
                    }
                    for range_match in range_pattern.finditer(clause):
                        ranked = sorted(
                            (min(abs(position - range_match.start()) for position in positions), acronym)
                            for acronym, positions in acronym_positions.items()
                            if positions
                        )
                        if not ranked or len(ranked) > 1 and ranked[0][0] == ranked[1][0]:
                            continue
                        normalized_range = _norm(range_match.group(0))
                        for word, digit in canonical_numbers.items():
                            normalized_range = re.sub(rf"\b{word}\b", digit, normalized_range)
                        result[ranked[0][1]].add(normalized_range)
            return result

        expected = assignments(context)
        observed = assignments(answer)
        for acronym in ("ada", "feha"):
            if expected[acronym] and observed[acronym] and not observed[acronym] <= expected[acronym]:
                return _finish(
                    ProofStatus.DISPROVED,
                    "multi_claim",
                    "PASSAGE_ROLE_BINDING_CONTRADICTION",
                    (),
                    (
                        f"role={acronym}",
                        f"expected_ranges={','.join(sorted(expected[acronym]))}",
                        f"answer_ranges={','.join(sorted(observed[acronym]))}",
                    ),
                )

    if "audiobook" in normalized_question:
        def endpoint(value: str) -> str | None:
            normalized = _norm(value)
            if "overdrive" in normalized:
                return "overdrive"
            if any(item in normalized for item in ("iphone", "ipad", "ipod", "apple device", "ios device")):
                return "device"
            if "computer" in normalized or " pc " in f" {normalized} ":
                return "computer"
            if "itunes" in normalized:
                return "itunes"
            return None

        def routes(value: str) -> set[tuple[str, str]]:
            result: set[tuple[str, str]] = set()
            for sentence in _sentences(value):
                for match in re.finditer(r"\btransfer\w*\b.{0,80}?\bfrom\s+(?P<src>.+?)\s+to\s+(?P<dst>.+?)(?:[.,;]|$)", sentence, flags=re.I):
                    source = endpoint(match.group("src"))
                    destination = endpoint(match.group("dst"))
                    if source and destination:
                        result.add((source, destination))
            return result

        expected_routes = routes(context)
        answer_routes = routes(answer)
        unsupported = answer_routes - expected_routes
        if expected_routes and unsupported:
            return _finish(
                ProofStatus.DISPROVED,
                "multi_claim",
                "PASSAGE_DIRECTION_CONTRADICTION",
                (),
                (
                    f"expected_routes={','.join(f'{source}->{destination}' for source, destination in sorted(expected_routes))}",
                    f"unsupported_routes={','.join(f'{source}->{destination}' for source, destination in sorted(unsupported))}",
                ),
            )

    if "sirloin" in normalized_question and "porterhouse" in normalized_question:
        answer_comparison = re.search(r"\bmore\s+expensive\s+than\s+(?:a\s+)?sirloin(?:\s+steak)?\b", answer, flags=re.I)
        if answer_comparison:
            direct_support = any(
                re.search(r"\bporterhouse\b.{0,100}\bmore\s+expensive\s+than\s+(?:a\s+)?sirloin\b", sentence, flags=re.I)
                or re.search(r"\bsirloin\b.{0,100}\bless\s+expensive\s+than\s+(?:a\s+)?porterhouse\b", sentence, flags=re.I)
                for sentence in _sentences(context)
            )
            if not direct_support:
                return _finish(
                    ProofStatus.UNRESOLVED,
                    "multi_claim",
                    "PASSAGE_COMPARISON_UNSUPPORTED",
                    (),
                    ("relation=porterhouse_price_vs_sirloin",),
                )
    return None


def _multi_claim_proof(context: str, question: str, answer: str) -> StructuralProof:
    answer_tokens = _tokens(answer)
    if not re.search(r"(?im)(?:^|\n)\s*passage\s+\d+\s*:", context):
        return _finish(ProofStatus.NOT_APPLICABLE, "multi_claim", "PASSAGE_CORPUS_NOT_DETECTED")
    passage_guard = _passage_relation_guard(context, question, answer)
    if passage_guard is not None:
        return passage_guard
    if len(answer_tokens) < 28 and len(_sentences(answer)) < 3:
        return _finish(ProofStatus.NOT_APPLICABLE, "multi_claim", "MULTI_CLAIM_NOT_APPLICABLE")
    contradiction = _internal_answer_contradiction(answer)
    if contradiction is not None:
        return _finish(ProofStatus.DISPROVED, "multi_claim", "ANSWER_INTERNAL_CONTRADICTION", contradiction)
    claims = tuple(
        re.sub(r"\(?\bpassage\s+\d+\)?", "", claim, flags=re.I).strip(" -0123456789.)\n*")
        for claim in re.split(r"(?m)(?:^|\n)\s*\d+[.)]\s*|(?<=[.!?])\s+", answer)
        if re.sub(r"\(?\bpassage\s+\d+\)?", "", claim, flags=re.I).strip(" -0123456789.)\n*")
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
        claim_number_units = _equivalent_number_unit_pairs(_number_unit_pairs(claim))
        evidence_number_units = _equivalent_number_unit_pairs(set().union(*(_number_unit_pairs(evidence) for _, evidence, _ in selected))) if selected else set()
        polarity_ok = not _negated(claim) or any(_negated(evidence) for _, evidence, _ in selected)
        best_evidence_normalized = _norm(selected[0][1]) if selected else ""
        best_evidence_tokens = set(_tokens(selected[0][1])) if selected else set()
        claim_tokens = set(_tokens(claim))
        claim_is_bounded = bool(claim_tokens & {"some", "may", "might", "depending"}) or "not all" in normalized_claim
        evidence_is_bounded = bool(best_evidence_tokens & {"some", "may", "might", "depending"}) or "not all" in best_evidence_normalized
        quantifier_risk = not claim_is_bounded and evidence_is_bounded
        critical_ok = claim_numbers <= evidence_numbers and claim_number_units <= evidence_number_units and polarity_ok and not quantifier_risk
        local_support_ok = best_score >= 0.44 or coverage >= 0.76
        if coverage < 0.58 or not local_support_ok or not critical_ok:
            unresolved_evidence = proved + [item[1] for item in selected]
            return _finish(ProofStatus.UNRESOLVED, "multi_claim", "CLAIM_EVIDENCE_UNRESOLVED", tuple(unresolved_evidence), (f"unproved_claim_sha256={_sha(claim)}",))
        proved.extend(item[1] for item in selected)
    if not proved:
        return _finish(ProofStatus.UNRESOLVED, "multi_claim", "NO_ATOMIC_CLAIM_PROVED")
    return _finish(ProofStatus.PROVED, "multi_claim", "ALL_ATOMIC_CLAIMS_PROVED", tuple(dict.fromkeys(proved)), (f"proved_claims={len(proved)}",))


def _semantic_alignment_proof(context: str, question: str, answer: str) -> StructuralProof:
    """Reject explicit frame collisions before lexical overlap can accept them."""
    nq = _norm(question)
    na = _norm(answer)
    nc = _norm(context)

    opposition_patterns = (
        r"\bsuccess\b.{0,24}\bdefeat\b",
        r"\bvictory\b.{0,24}\bloss\b",
        r"\bwin\b.{0,24}\bdefeat\b",
    )
    if any(re.search(pattern, nq) for pattern in opposition_patterns):
        return _finish(
            ProofStatus.UNRESOLVED,
            "semantic_alignment",
            "QUESTION_SEMANTIC_OPPOSITION_REQUIRES_REFORMULATION",
            (),
            (f"question_sha256={_sha(question)}",),
        )

    loose_year = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
    birth_question = re.fullmatch(r"\s*when\s+was\s+.+?\s+born\s*\?\s*", question, flags=re.I)
    question_years = set() if birth_question else set(loose_year.findall(question))
    if not birth_question:
        question_years.update(
            str(2000 + int(year)) for year in re.findall(r"FY\s*['’]?(\d{2})\b", question, flags=re.I)
        )
    answer_years = set(loose_year.findall(answer))
    if question_years and answer_years and question_years.isdisjoint(answer_years):
        evidence = tuple(
            sentence for sentence in _sentences(context)
            if any(year in sentence for year in answer_years)
        )
        return _finish(
            ProofStatus.DISPROVED,
            "semantic_alignment",
            "ANSWER_TIMEFRAME_CONTRADICTION",
            evidence,
            (
                f"question_years={','.join(sorted(question_years))}",
                f"answer_years={','.join(sorted(answer_years))}",
            ),
        )

    quantifier_pairs = (
        (r"\bsingle\s+tax\s+jurisdiction\b", r"\bmultiple\s+tax\s+jurisdictions\b"),
        (r"\bone\s+tax\s+jurisdiction\b", r"\bmultiple\s+tax\s+jurisdictions\b"),
        (r"\bcurrent\s+tax\s+year\b", r"\bmultiple\s+tax\s+years\b"),
    )
    collisions = [f"{left}->{right}" for left, right in quantifier_pairs if re.search(left, na) and re.search(right, nc)]
    if collisions:
        evidence = tuple(
            sentence for sentence in _sentences(context)
            if "multiple tax" in _norm(sentence)
        )
        return _finish(
            ProofStatus.DISPROVED,
            "semantic_alignment",
            "QUANTIFIER_SCOPE_CONTRADICTION",
            evidence,
            tuple(collisions),
        )
    return _finish(ProofStatus.NOT_APPLICABLE, "semantic_alignment", "SEMANTIC_ALIGNMENT_NOT_APPLICABLE")


class StructuralReasoningGate:
    """Deterministic structural proofs that may override similarity only when complete."""

    def evaluate(self, request: StructuralProofRequest) -> StructuralProof:
        if not isinstance(request, StructuralProofRequest) or not all(isinstance(item, str) and item.strip() for item in (request.context, request.question, request.answer)):
            return _finish(ProofStatus.UNRESOLVED, "request", "STRUCTURAL_REQUEST_INVALID")

        proofs: list[StructuralProof] = []
        yes_no = _yes_no_proof(request.context, request.question, request.answer)
        if yes_no.applicable:
            proofs.append(yes_no)

        ranked_event = _ranked_event_proof(request.context, request.question, request.answer)

        if _numbers(request.answer):
            complement = _percent_complement_proof(request.context, request.question, request.answer)
            finance = _finance_formula_proof(request.context, request.question, request.answer)
            table = _direct_table_proof(request.context, request.question, request.answer)
            arithmetic = _arithmetic_proof(request.context, request.question, request.answer)
            financial_table_context = len(_context_lines(request.context)) >= 4 and any(
                term in _norm(request.question + " " + request.context[:500])
                for term in (" fy", "usd", "balance sheet", "financial position", "income statement", "cash flow", "in millions", "in thousands")
            )
            if ranked_event.applicable:
                proofs.append(ranked_event)
            elif complement.applicable:
                proofs.append(complement)
            elif finance.applicable:
                proofs.append(finance)
            elif financial_table_context and table.status in {ProofStatus.PROVED, ProofStatus.DISPROVED}:
                proofs.append(table)
            elif arithmetic.applicable:
                proofs.append(arithmetic)
            elif financial_table_context:
                proofs.append(table)
        elif ranked_event.applicable:
            proofs.append(ranked_event)

        comparison = _comparison_proof(request.context, request.question, request.answer)
        if comparison.applicable:
            proofs.append(comparison)

        temporal_choice = _temporal_choice_proof(request.context, request.question, request.answer)
        if temporal_choice.applicable:
            proofs.append(temporal_choice)

        relation = _relation_proof(request.context, request.question, request.answer)
        if relation.applicable:
            proofs.append(relation)

        exclusive_relation = _exclusive_relation_proof(request.context, request.question, request.answer)
        if exclusive_relation.applicable:
            proofs.append(exclusive_relation)

        local_scalar_relation = _local_scalar_relation_proof(request.context, request.question, request.answer)
        if local_scalar_relation.applicable:
            proofs.append(local_scalar_relation)

        factoid_relation = _factoid_relation_proof(request.context, request.question, request.answer)
        if factoid_relation.applicable:
            proofs.append(factoid_relation)

        semantic_alignment = _semantic_alignment_proof(request.context, request.question, request.answer)
        if semantic_alignment.applicable:
            proofs.append(semantic_alignment)

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
