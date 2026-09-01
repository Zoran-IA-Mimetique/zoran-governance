from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from chemistry_profile import ChemistryDecision, ChemistryProfile, ChemistryRequest
from colored_frame_gate import ColoredFrameGate, ColoredFrameRequest
from exact_math_engine import ExactMathEngine, ExactMathRequest
from structural_reasoning_gate import ProofStatus, StructuralProof, StructuralProofRequest, StructuralReasoningGate
from tolerance_skill import Decision


COMPONENT_ID = "zoran.raw-text-coherence-gate"
VERSION = "22.3.0"
MODEL_ID = "halueval-context-faithfulness-multiframe-logit-v2"
MODEL_PATH = Path(__file__).with_name("raw_text_coherence_model.json")
MODEL_TRAINING_CORPUS_SHA256 = ""
MODEL_FEATURES: tuple[str, ...] = ()
MODEL_SUBMODELS: dict[str, dict[str, object]] = {}
MODEL_THRESHOLD = 0.5
MODEL_READY = False
MODEL_LOAD_ERROR = "MODEL_FILE_MISSING"


STOPWORDS = frozenset({
    "a", "about", "after", "again", "against", "all", "also", "am", "an", "and", "any", "are",
    "as", "at", "be", "because", "been", "before", "being", "between", "both", "but", "by", "can",
    "could", "did", "do", "does", "doing", "during", "each", "few", "for", "from", "further", "had",
    "has", "have", "having", "he", "her", "here", "hers", "herself", "him", "himself", "his", "how",
    "i", "if", "in", "into", "is", "it", "its", "itself", "just", "me", "more", "most", "my",
    "myself", "of", "off", "on", "once", "only", "or", "other", "our", "ours", "ourselves", "out",
    "over", "own", "same", "she", "should", "so", "some", "such", "than", "that", "the", "their",
    "theirs", "them", "themselves", "then", "there", "these", "they", "this", "those", "through", "to",
    "too", "under", "until", "up", "very", "was", "we", "were", "what", "when", "where", "which",
    "while", "who", "whom", "why", "will", "with", "would", "you", "your", "yours", "yourself",
    "yourselves", "yes", "no",
})
NEGATIONS = frozenset({"no", "non", "not", "never", "none", "neither", "without", "cannot", "cant", "wont"})
HEDGES = frozenset({"apparently", "approximately", "likely", "maybe", "might", "perhaps", "possibly", "probably"})
CERTAINTY = frozenset({"certainly", "definitely", "undoubtedly", "always", "never"})
ANTONYM_GROUPS = (
    ({"increase", "rise", "gain", "grow", "higher"}, {"decrease", "fall", "loss", "decline", "lower"}),
    ({"before", "earlier", "prior"}, {"after", "later", "subsequent"}),
    ({"win", "victory", "defeat"}, {"lose", "loss", "lost"}),
    ({"accept", "approve", "support"}, {"reject", "refuse", "oppose"}),
    ({"include", "contain", "with"}, {"exclude", "omit", "without"}),
    ({"alive", "living"}, {"dead", "died", "death"}),
    ({"first", "earliest"}, {"last", "latest"}),
    ({"true", "correct"}, {"false", "incorrect"}),
)


def _norm(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value.casefold())
    folded = "".join(char for char in folded if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9]+", folded))


def _tokens(value: str) -> tuple[str, ...]:
    normalized = _norm(value)
    return tuple(normalized.split()) if normalized else ()


def _stem(token: str) -> str:
    irregular = {
        "wrote": "write", "written": "write", "writes": "write", "authored": "write",
        "born": "birth", "birthplace": "birth", "died": "death", "dead": "death",
        "won": "win", "winning": "win", "lost": "lose", "rose": "rise", "risen": "rise", "increased": "rise",
        "located": "locate",
        "founded": "found", "established": "found", "children": "child", "men": "man", "women": "woman",
    }
    if token in irregular:
        return irregular[token]
    for suffix, replacement, minimum in (
        ("ization", "ize", 5), ("ational", "ate", 5), ("fulness", "ful", 5),
        ("iveness", "ive", 5), ("ments", "", 5), ("ment", "", 5),
        ("ingly", "", 5), ("edly", "", 5), ("ing", "", 5), ("ied", "y", 4),
        ("ies", "y", 4), ("ed", "", 4), ("es", "", 4), ("s", "", 3),
    ):
        if token.endswith(suffix) and len(token) - len(suffix) >= minimum:
            return token[:-len(suffix)] + replacement
    return token


def _content(value: str, *, stem: bool = False) -> tuple[str, ...]:
    result = [token for token in _tokens(value) if token not in STOPWORDS and len(token) > 1]
    return tuple(_stem(token) for token in result) if stem else tuple(result)


def _sentences(value: str) -> tuple[str, ...]:
    cleaned = " ".join(value.split())
    if not cleaned:
        return ()
    parts = re.split(r"(?<=[.!?])\s+|(?<=[.!?])(?=[A-Z0-9])|\s*[;|]\s*", cleaned)
    return tuple(part.strip() for part in parts if part.strip())


def _ratio(num: float, den: float, default: float = 0.0) -> float:
    return float(num / den) if den else default


def _set_precision(left: set[str], right: set[str]) -> float:
    return _ratio(len(left & right), len(left), 1.0 if not left else 0.0)


def _set_recall(left: set[str], right: set[str]) -> float:
    return _ratio(len(left & right), len(right), 1.0 if not right else 0.0)


def _f1(precision: float, recall: float) -> float:
    return _ratio(2.0 * precision * recall, precision + recall)


def _ngrams(tokens: tuple[str, ...], size: int) -> set[tuple[str, ...]]:
    return {tokens[index:index + size] for index in range(max(0, len(tokens) - size + 1))}


def _char_ngrams(value: str, size: int = 4) -> set[str]:
    compact = _norm(value).replace(" ", "_")
    return {compact[index:index + size] for index in range(max(0, len(compact) - size + 1))}


def _numbers(value: str) -> set[str]:
    return {item.replace(",", "").removesuffix("%") for item in re.findall(r"(?<![A-Za-z])[-+]?\d+(?:[,.]\d+)?%?", value)}


def _entities(value: str) -> set[str]:
    entities: set[str] = set()
    for match in re.finditer(r"\b(?:[A-Z][\w'’.-]*|[A-Z]{2,})(?:\s+(?:[A-Z][\w'’.-]*|[A-Z]{2,})){0,4}", value):
        candidate = _norm(match.group(0))
        if candidate and candidate not in {"the", "a", "an", "i"}:
            entities.add(candidate)
    return entities


def _question_scope_omitted(question: str, answer: str) -> bool:
    question_tokens = _tokens(question)
    if not question_tokens or question_tokens[0] not in {"are", "can", "could", "did", "do", "does", "has", "have", "is", "was", "were"}:
        return False
    if "both" not in question_tokens:
        return False
    answer_tokens = set(_tokens(answer))
    if answer_tokens & {"both", "neither", "no", "yes"}:
        return False
    question_entities = set()
    for entity in _entities(question):
        parts = entity.split()
        if parts and parts[0] in {"are", "can", "could", "did", "do", "does", "has", "have", "is", "was", "were"}:
            parts = parts[1:]
        if len(parts) >= 2:
            question_entities.add(" ".join(parts))
    normalized_answer = _norm(answer)
    return len(question_entities) >= 2 and not all(entity in normalized_answer for entity in question_entities)


def _collapse_redundant_answer_fragments(answer: str) -> tuple[str, int]:
    """Collapse only exact comma-separated repetitions of one answer.

    Some multi-hop evaluators concatenate identical subanswers (``27, 27,
    27``).  Repetition adds no proposition and must therefore be idempotent.
    Distinct lists and thousands-formatted scalars remain byte-for-byte
    unchanged.
    """
    fragments = tuple(fragment.strip() for fragment in answer.split(","))
    if len(fragments) < 2 or any(not fragment for fragment in fragments):
        return answer, 1
    normalized = tuple(_norm(fragment) for fragment in fragments)
    if normalized[0] and len(set(normalized)) == 1:
        return fragments[0], len(fragments)
    return answer, 1


def _antonym_conflict(answer_tokens: set[str], evidence_tokens: set[str]) -> float:
    conflicts = 0
    opportunities = 0
    for left, right in ANTONYM_GROUPS:
        answer_left = bool(answer_tokens & left)
        answer_right = bool(answer_tokens & right)
        if not (answer_left or answer_right):
            continue
        opportunities += 1
        evidence_left = bool(evidence_tokens & left)
        evidence_right = bool(evidence_tokens & right)
        if (answer_left and evidence_right and not evidence_left) or (answer_right and evidence_left and not evidence_right):
            conflicts += 1
    return _ratio(conflicts, opportunities)


def _best_evidence(answer_sentence: str, question: str, context_sentences: tuple[str, ...]) -> tuple[str, float]:
    answer = set(_content(answer_sentence, stem=True))
    question_tokens = set(_content(question, stem=True))
    best_text = ""
    best_score = -1.0
    for sentence in context_sentences:
        evidence = set(_content(sentence, stem=True))
        answer_precision = _set_precision(answer, evidence)
        question_overlap = _ratio(len(question_tokens & evidence), max(1, len(question_tokens)))
        score = 0.82 * answer_precision + 0.18 * question_overlap
        if score > best_score:
            best_score = score
            best_text = sentence
    return best_text, max(0.0, best_score)


def extract_features(context: str, question: str, answer: str) -> dict[str, float]:
    if not all(isinstance(value, str) for value in (context, question, answer)):
        raise TypeError("RAW_TEXT_FIELDS_MUST_BE_STRINGS")
    answer_tokens = _tokens(answer)
    context_tokens = _tokens(context)
    question_tokens = _tokens(question)
    answer_content = set(_content(answer))
    context_content = set(_content(context))
    question_content = set(_content(question))
    answer_stems = set(_content(answer, stem=True))
    context_stems = set(_content(context, stem=True))
    question_stems = set(_content(question, stem=True))

    precision = _set_precision(answer_content, context_content)
    recall = _set_recall(answer_content, context_content)
    stem_precision = _set_precision(answer_stems, context_stems)
    answer_bigrams = _ngrams(tuple(_content(answer, stem=True)), 2)
    context_bigrams = _ngrams(tuple(_content(context, stem=True)), 2)
    bigram_precision = _ratio(len(answer_bigrams & context_bigrams), len(answer_bigrams), 1.0 if not answer_bigrams else 0.0)
    answer_chars = _char_ngrams(answer)
    context_chars = _char_ngrams(context)
    char_precision = _ratio(len(answer_chars & context_chars), len(answer_chars), 1.0 if not answer_chars else 0.0)

    answer_numbers = _numbers(answer)
    context_numbers = _numbers(context)
    numeric_coverage = _set_precision(answer_numbers, context_numbers)
    answer_entities = _entities(answer)
    context_normalized = _norm(context)
    entity_coverage = _ratio(sum(entity in context_normalized for entity in answer_entities), len(answer_entities), 1.0 if not answer_entities else 0.0)

    context_sentences = _sentences(context) or (context,)
    answer_sentences = _sentences(answer) or (answer,)
    sentence_precision: list[float] = []
    sentence_stem_precision: list[float] = []
    sentence_bigram_precision: list[float] = []
    local_number_coverage: list[float] = []
    local_entity_coverage: list[float] = []
    negation_alignment: list[float] = []
    antonym_conflicts: list[float] = []
    evidence_scores: list[float] = []
    for sentence in answer_sentences:
        evidence, evidence_score = _best_evidence(sentence, question, context_sentences)
        evidence_scores.append(evidence_score)
        sentence_words = set(_content(sentence))
        evidence_words = set(_content(evidence))
        sentence_stems = set(_content(sentence, stem=True))
        evidence_stems = set(_content(evidence, stem=True))
        sentence_precision.append(_set_precision(sentence_words, evidence_words))
        sentence_stem_precision.append(_set_precision(sentence_stems, evidence_stems))
        sentence_bigrams = _ngrams(tuple(_content(sentence, stem=True)), 2)
        evidence_bigrams = _ngrams(tuple(_content(evidence, stem=True)), 2)
        sentence_bigram_precision.append(_ratio(len(sentence_bigrams & evidence_bigrams), len(sentence_bigrams), 1.0 if not sentence_bigrams else 0.0))
        local_number_coverage.append(_set_precision(_numbers(sentence), _numbers(evidence)))
        sentence_entities = _entities(sentence)
        evidence_normalized = _norm(evidence)
        local_entity_coverage.append(_ratio(sum(entity in evidence_normalized for entity in sentence_entities), len(sentence_entities), 1.0 if not sentence_entities else 0.0))
        answer_negated = bool(set(_tokens(sentence)) & NEGATIONS)
        evidence_negated = bool(set(_tokens(evidence)) & NEGATIONS)
        negation_alignment.append(1.0 if answer_negated == evidence_negated else 0.0)
        antonym_conflicts.append(_antonym_conflict(set(_content(sentence, stem=True)), evidence_stems))

    normalized_answer = _norm(answer)
    normalized_context = _norm(context)
    q_and_a = question_stems | answer_stems
    first_question = " ".join(question_tokens[:3])
    question_casefold = question.casefold()
    answer_token_set = set(answer_tokens)
    return {
        "log_answer_tokens": math.log1p(len(answer_tokens)),
        "log_context_tokens": math.log1p(len(context_tokens)),
        "answer_context_length_ratio": min(4.0, _ratio(len(answer_tokens), len(context_tokens))),
        "answer_context_precision": precision,
        "answer_context_recall": recall,
        "answer_context_f1": _f1(precision, recall),
        "answer_context_stem_precision": stem_precision,
        "answer_context_bigram_precision": bigram_precision,
        "answer_context_char4_precision": char_precision,
        "exact_answer_span": float(bool(normalized_answer and normalized_answer in normalized_context)),
        "numeric_coverage": numeric_coverage,
        "new_number_ratio": 1.0 - numeric_coverage,
        "entity_coverage": entity_coverage,
        "new_entity_ratio": 1.0 - entity_coverage,
        "question_answer_overlap": _set_precision(question_content, answer_content),
        "question_answer_stem_overlap": _set_precision(question_stems, answer_stems),
        "question_answer_context_coverage": _set_precision(q_and_a, context_stems),
        "best_sentence_precision": max(sentence_precision, default=0.0),
        "mean_sentence_precision": _ratio(sum(sentence_precision), len(sentence_precision)),
        "min_sentence_precision": min(sentence_precision, default=0.0),
        "mean_sentence_stem_precision": _ratio(sum(sentence_stem_precision), len(sentence_stem_precision)),
        "mean_sentence_bigram_precision": _ratio(sum(sentence_bigram_precision), len(sentence_bigram_precision)),
        "mean_evidence_selection_score": _ratio(sum(evidence_scores), len(evidence_scores)),
        "local_number_coverage": _ratio(sum(local_number_coverage), len(local_number_coverage)),
        "local_entity_coverage": _ratio(sum(local_entity_coverage), len(local_entity_coverage)),
        "negation_alignment": _ratio(sum(negation_alignment), len(negation_alignment)),
        "antonym_conflict": _ratio(sum(antonym_conflicts), len(antonym_conflicts)),
        "answer_sentence_count": min(20.0, float(len(answer_sentences))),
        "is_short_answer": float(len(answer_tokens) <= 5),
        "is_yes_no_answer": float(normalized_answer in {"yes", "no", "true", "false"}),
        "is_summary_question": float("summar" in _norm(question)),
        "is_dialogue_question": float("[human]" in question_casefold and "[assistant]" in question_casefold),
        "question_who": float(first_question.startswith("who") or first_question.startswith("which person")),
        "question_when": float(first_question.startswith("when") or "what year" in _norm(question)),
        "question_where": float(first_question.startswith("where") or "what state" in _norm(question) or "what country" in _norm(question)),
        "question_why": float(first_question.startswith("why")),
        "question_how_many": float("how many" in _norm(question) or "how much" in _norm(question)),
        "answer_hedge": float(bool(answer_token_set & HEDGES)),
        "answer_certainty": float(bool(answer_token_set & CERTAINTY)),
    }


def _canonical_sha(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _load_model() -> None:
    global MODEL_TRAINING_CORPUS_SHA256, MODEL_FEATURES, MODEL_SUBMODELS
    global MODEL_THRESHOLD, MODEL_READY, MODEL_LOAD_ERROR
    if not MODEL_PATH.is_file():
        return
    try:
        model = json.loads(MODEL_PATH.read_text(encoding="utf-8"))
        required = {
            "schema", "model_id", "training_dataset", "training_split_sha256", "features",
            "models", "validation", "model_sha256",
        }
        if not isinstance(model, dict) or set(model) != required:
            raise ValueError("MODEL_SCHEMA_INVALID")
        payload = {key: model[key] for key in sorted(required - {"model_sha256"})}
        if model["model_sha256"] != _canonical_sha(payload):
            raise ValueError("MODEL_DIGEST_INVALID")
        if model["schema"] != "zoran.raw-text-coherence-model.v2" or model["model_id"] != MODEL_ID:
            raise ValueError("MODEL_ID_INVALID")
        features = tuple(model["features"])
        if not features or len(set(features)) != len(features):
            raise ValueError("MODEL_SHAPE_INVALID")
        probe = extract_features("A is B.", "What is A?", "A is B.")
        if set(features) != set(probe):
            raise ValueError("MODEL_FEATURE_CONTRACT_INVALID")
        if not isinstance(model["models"], dict) or set(model["models"]) != {"dialogue", "qa", "summarization"}:
            raise ValueError("MODEL_FRAMES_INVALID")
        submodels: dict[str, dict[str, object]] = {}
        for frame, submodel in model["models"].items():
            if not isinstance(submodel, dict) or set(submodel) != {"mean", "scale", "coefficients", "intercept", "threshold", "validation"}:
                raise ValueError("MODEL_FRAME_SCHEMA_INVALID")
            mean = tuple(float(value) for value in submodel["mean"])
            scale = tuple(float(value) for value in submodel["scale"])
            coefficients = tuple(float(value) for value in submodel["coefficients"])
            intercept = float(submodel["intercept"])
            threshold = float(submodel["threshold"])
            if not (len(features) == len(mean) == len(scale) == len(coefficients)):
                raise ValueError("MODEL_FRAME_SHAPE_INVALID")
            numeric = (*mean, *scale, *coefficients, intercept, threshold)
            if any(not math.isfinite(value) for value in numeric) or any(value <= 0 for value in scale):
                raise ValueError("MODEL_NUMERIC_INVALID")
            if not 0.0 < threshold < 1.0:
                raise ValueError("MODEL_THRESHOLD_INVALID")
            submodels[frame] = {"mean": mean, "scale": scale, "coefficients": coefficients, "intercept": intercept, "threshold": threshold}
        MODEL_TRAINING_CORPUS_SHA256 = str(model["training_split_sha256"])
        MODEL_FEATURES = features
        MODEL_SUBMODELS = submodels
        MODEL_READY = True
        MODEL_LOAD_ERROR = ""
    except Exception as exc:
        MODEL_READY = False
        MODEL_LOAD_ERROR = f"MODEL_LOAD_FAILURE:{type(exc).__name__}:{exc}"


def _model_frame(features: Mapping[str, float]) -> str:
    if features["is_summary_question"]:
        return "summarization"
    if features["is_dialogue_question"]:
        return "dialogue"
    return "qa"


def _probability(features: Mapping[str, float], frame: str) -> tuple[float, float]:
    if not MODEL_READY or not MODEL_FEATURES or frame not in MODEL_SUBMODELS:
        raise RuntimeError("RAW_TEXT_MODEL_NOT_READY")
    model = MODEL_SUBMODELS[frame]
    mean = model["mean"]
    scale = model["scale"]
    coefficients = model["coefficients"]
    intercept = float(model["intercept"])
    threshold = float(model["threshold"])
    if not (len(MODEL_FEATURES) == len(mean) == len(scale) == len(coefficients)):
        raise RuntimeError("RAW_TEXT_MODEL_SHAPE_INVALID")
    score = intercept
    for name, center, spread, coefficient in zip(MODEL_FEATURES, mean, scale, coefficients, strict=True):
        value = float(features[name])
        if not math.isfinite(value) or not math.isfinite(center) or not math.isfinite(spread) or not math.isfinite(coefficient) or spread <= 0:
            raise RuntimeError("RAW_TEXT_MODEL_NONFINITE")
        score += coefficient * ((value - center) / spread)
    if score >= 0:
        exp_value = math.exp(-score)
        return 1.0 / (1.0 + exp_value), threshold
    exp_value = math.exp(score)
    return exp_value / (1.0 + exp_value), threshold


@dataclass(frozen=True)
class RawTextCoherenceRequest:
    context: str
    question: str
    answer: str
    as_of: str


@dataclass(frozen=True)
class RawTextCoherenceEvaluation:
    decision: Decision
    reasons: tuple[str, ...]
    faithful_probability: float | None
    threshold: float
    evidence_quotes: tuple[str, ...]
    reformulations: tuple[str, ...]
    feature_sha256: str
    structural_status: str
    structural_family: str
    structural_trace: tuple[str, ...]
    structural_receipt_sha256: str
    receipt_sha256: str


class RawTextCoherenceGate:
    """Candidate-owned deterministic path from raw text to a bounded decision."""

    def __init__(self) -> None:
        self.chemistry = ChemistryProfile()
        self.exact_math = ExactMathEngine()
        self.colored_frames = ColoredFrameGate()
        self.structural = StructuralReasoningGate()

    def evaluate(self, request: RawTextCoherenceRequest | None) -> RawTextCoherenceEvaluation:
        if not isinstance(request, RawTextCoherenceRequest):
            return self._finish(Decision.RETRY, ("RAW_TEXT_REQUEST_MISSING",), None, (), (), {})
        if not all(isinstance(value, str) and value.strip() for value in (request.context, request.question, request.answer, request.as_of)):
            return self._finish(Decision.RETRY, ("RAW_TEXT_FIELD_MISSING",), None, (), (), {})
        if not MODEL_READY:
            return self._finish(Decision.RETRY, (f"RAW_TEXT_MODEL_NOT_READY:{MODEL_LOAD_ERROR}",), None, (), (), {})
        analysis_answer, repetition_count = _collapse_redundant_answer_fragments(request.answer)
        normalization_reasons = (
            (f"REDUNDANT_ANSWER_FRAGMENTS_COLLAPSED:{repetition_count}",)
            if repetition_count > 1
            else ()
        )

        def audited(reasons: tuple[str, ...]) -> tuple[str, ...]:
            return reasons + normalization_reasons

        features = extract_features(request.context, request.question, analysis_answer)
        frame = _model_frame(features)
        probability, threshold = _probability(features, frame)
        scope_omission = _question_scope_omitted(request.question, analysis_answer)
        if scope_omission:
            return self._finish(
                Decision.VETO,
                audited(("QUESTION_SCOPE_OMISSION",)),
                probability,
                (),
                (
                    f"Verify from the supplied context: {request.question.strip()}",
                    f"Determine the exact context-grounded answer to: {request.question.strip()}",
                ),
                features,
                threshold=threshold,
                frame=frame,
            )
        chemistry = self.chemistry.evaluate(
            ChemistryRequest(request.question, analysis_answer, request.context)
        )
        chemistry_calculation = chemistry.reason in {
            "MOLAR_MASS_CALCULATED", "MOLAR_MASS_CONTRADICTION",
            "REACTION_BALANCED", "REACTION_BALANCE_CONTRADICTION",
        }
        chemistry_block = chemistry.reason == "DANGEROUS_PROCEDURE_BLOCKED"
        chemistry_retry = chemistry.reason in {
            "FORMULA_SYNTAX_UNSUPPORTED", "ELEMENT_UNSUPPORTED",
            "FORMULA_PARENTHESIS_UNCLOSED", "REACTION_ARROW_MISSING",
            "REACTION_SCOPE_UNSUPPORTED", "STOICHIOMETRY_NOT_UNIQUE",
            "STOICHIOMETRY_NONPOSITIVE",
        }
        if chemistry_calculation or chemistry_block or chemistry_retry:
            chemistry_status = (
                ProofStatus.PROVED if chemistry.decision is ChemistryDecision.PASS
                else ProofStatus.DISPROVED if chemistry.decision is ChemistryDecision.VETO
                else ProofStatus.UNRESOLVED
            )
            chemistry_structural = StructuralProof(
                chemistry_status,
                "chemistry",
                chemistry.reason,
                (request.context,) if request.context else (),
                chemistry.calculation_trace,
                chemistry.receipt_sha256,
            )
            decision = (
                Decision.PASS if chemistry_status is ProofStatus.PROVED
                else Decision.VETO if chemistry_status is ProofStatus.DISPROVED
                else Decision.RETRY
            )
            reason_prefix = {
                Decision.PASS: "CHEMISTRY_PROOF_FAITHFUL",
                Decision.VETO: "CHEMISTRY_PROOF_CONTRADICTION",
                Decision.RETRY: "CHEMISTRY_PROOF_INCOMPLETE",
            }[decision]
            reformulations = () if decision is not Decision.RETRY else (
                f"Provide the exact formula or equation required by: {request.question.strip()}",
                f"Check every chemical species before recalculating: {request.question.strip()}",
            )
            return self._finish(
                decision,
                audited((f"{reason_prefix}:{chemistry.reason}",)),
                probability,
                chemistry_structural.evidence_quotes,
                reformulations,
                features,
                threshold=threshold,
                frame=frame,
                structural=chemistry_structural,
            )
        exact_math = self.exact_math.evaluate(
            ExactMathRequest(request.context, request.question, analysis_answer)
        )
        if exact_math.applicable:
            exact_structural = StructuralProof(
                exact_math.status,
                "exact_math",
                exact_math.reason,
                exact_math.evidence_quotes,
                exact_math.inverse_trace,
                exact_math.receipt_sha256,
            )
            if exact_math.status is ProofStatus.PROVED:
                return self._finish(
                    Decision.PASS,
                    audited((f"EXACT_MATH_PROOF_FAITHFUL:{exact_math.reason}",)),
                    probability,
                    exact_math.evidence_quotes,
                    (),
                    features,
                    threshold=threshold,
                    frame=frame,
                    structural=exact_structural,
                )
            if exact_math.status is ProofStatus.DISPROVED:
                return self._finish(
                    Decision.VETO,
                    audited((f"EXACT_MATH_PROOF_CONTRADICTION:{exact_math.reason}",)),
                    probability,
                    exact_math.evidence_quotes,
                    (),
                    features,
                    threshold=threshold,
                    frame=frame,
                    structural=exact_structural,
                )
            return self._finish(
                Decision.RETRY,
                audited((f"EXACT_MATH_BINDING_INCOMPLETE:{exact_math.reason}",)),
                probability,
                exact_math.evidence_quotes,
                (
                    f"Name the exact operands and units required by: {request.question.strip()}",
                    f"Recalculate only after binding every operand in: {request.question.strip()}",
                ),
                features,
                threshold=threshold,
                frame=frame,
                structural=exact_structural,
            )
        colored = self.colored_frames.evaluate(
            ColoredFrameRequest(request.context, request.question, analysis_answer)
        )
        if colored.applicable:
            colored_structural = StructuralProof(
                colored.status,
                "colored_frame",
                colored.reason,
                colored.evidence_quotes,
                colored.calculation_trace,
                colored.receipt_sha256,
            )
            if colored.status is ProofStatus.PROVED:
                return self._finish(
                    Decision.PASS,
                    audited((f"COLORED_FRAME_PROOF_FAITHFUL:{colored.reason}",)),
                    probability,
                    colored.evidence_quotes,
                    (),
                    features,
                    threshold=threshold,
                    frame=frame,
                    structural=colored_structural,
                )
            if colored.status is ProofStatus.DISPROVED:
                return self._finish(
                    Decision.VETO,
                    audited((f"COLORED_FRAME_PROOF_CONTRADICTION:{colored.reason}",)),
                    probability,
                    colored.evidence_quotes,
                    (),
                    features,
                    threshold=threshold,
                    frame=frame,
                    structural=colored_structural,
                )
            return self._finish(
                Decision.VETO,
                audited((f"COLORED_FRAME_PROOF_REQUIRED:{colored.reason}",)),
                probability,
                colored.evidence_quotes,
                (
                    f"Verify every semantic role from the supplied context: {request.question.strip()}",
                    f"State only source-contained or explicitly derived frames for: {request.question.strip()}",
                ),
                features,
                threshold=threshold,
                frame=frame,
                structural=colored_structural,
            )
        structural = self.structural.evaluate(StructuralProofRequest(request.context, request.question, analysis_answer))
        answer_sentences = _sentences(analysis_answer) or (analysis_answer,)
        context_sentences = _sentences(request.context) or (request.context,)
        lexical_evidence = tuple(_best_evidence(sentence, request.question, context_sentences)[0] for sentence in answer_sentences)
        evidence = tuple(dict.fromkeys(structural.evidence_quotes + lexical_evidence))
        numeric_binding_failure = (
            frame == "qa"
            and bool(_numbers(analysis_answer))
            and features["local_number_coverage"] < 0.999999
        )
        strict_structural_family = structural.family in {
            "yes_no_polarity", "percent_complement", "comparison", "ranked_event", "temporal_choice", "relation", "exclusive_relation", "local_scalar_relation", "multi_claim", "semantic_alignment", "finance_formula"
        } or (
            structural.family == "numeric_table"
            and any(term in _norm(request.question) for term in ("fy", "usd", "financial", "balance sheet", "income statement", "margin"))
        )
        doubt = structural.status in {ProofStatus.DISPROVED, ProofStatus.UNRESOLVED} and strict_structural_family or numeric_binding_failure or scope_omission or abs(probability - threshold) <= 0.08 or (
            features["answer_context_precision"] >= 0.95
            and features["mean_sentence_precision"] < 0.75
        )
        reformulations = (
            f"Verify from the supplied context: {request.question.strip()}",
            f"Determine the exact context-grounded answer to: {request.question.strip()}",
        ) if doubt else ()
        if scope_omission:
            return self._finish(Decision.VETO, audited(("QUESTION_SCOPE_OMISSION",)), probability, evidence, reformulations, features, threshold=threshold, frame=frame, structural=structural)
        if structural.status is ProofStatus.DISPROVED:
            return self._finish(Decision.VETO, audited((f"STRUCTURAL_PROOF_CONTRADICTION:{structural.family}:{structural.reason}",)), probability, evidence, reformulations, features, threshold=threshold, frame=frame, structural=structural)
        if structural.status is ProofStatus.PROVED:
            return self._finish(Decision.PASS, audited((f"STRUCTURAL_PROOF_FAITHFUL:{structural.family}:{structural.reason}",)), probability, evidence, reformulations, features, threshold=threshold, frame=frame, structural=structural)
        if strict_structural_family and structural.status is ProofStatus.UNRESOLVED:
            return self._finish(Decision.VETO, audited((f"STRUCTURAL_PROOF_REQUIRED:{structural.family}:{structural.reason}",)), probability, evidence, reformulations, features, threshold=threshold, frame=frame, structural=structural)
        if numeric_binding_failure:
            return self._finish(Decision.VETO, audited(("LOCAL_NUMBER_BINDING_FAILURE",)), probability, evidence, reformulations, features, threshold=threshold, frame=frame, structural=structural)
        if probability >= threshold:
            return self._finish(Decision.PASS, audited(("RAW_CONTEXT_FAITHFUL",)), probability, evidence, reformulations, features, threshold=threshold, frame=frame, structural=structural)
        return self._finish(Decision.VETO, audited(("RAW_CONTEXT_INCOHERENCE",)), probability, evidence, reformulations, features, threshold=threshold, frame=frame, structural=structural)

    @staticmethod
    def _finish(
        decision: Decision,
        reasons: tuple[str, ...],
        probability: float | None,
        evidence: tuple[str, ...],
        reformulations: tuple[str, ...],
        features: Mapping[str, float],
        *,
        threshold: float = MODEL_THRESHOLD,
        frame: str | None = None,
        structural: StructuralProof | None = None,
    ) -> RawTextCoherenceEvaluation:
        feature_sha256 = _canonical_sha(dict(features))
        payload = {
            "component": COMPONENT_ID,
            "version": VERSION,
            "model_id": MODEL_ID,
            "model_training_corpus_sha256": MODEL_TRAINING_CORPUS_SHA256,
            "model_frame": frame,
            "decision": decision.value,
            "reasons": list(reasons),
            "faithful_probability": probability,
            "threshold": threshold,
            "evidence_sha256": [_canonical_sha(item) for item in evidence],
            "reformulations": list(reformulations),
            "feature_sha256": feature_sha256,
            "structural_status": structural.status.value if structural else ProofStatus.NOT_APPLICABLE.value,
            "structural_family": structural.family if structural else "none",
            "structural_trace": list(structural.calculation_trace) if structural else [],
            "structural_receipt_sha256": structural.receipt_sha256 if structural else "",
        }
        return RawTextCoherenceEvaluation(
            decision,
            reasons,
            probability,
            threshold,
            evidence,
            reformulations,
            feature_sha256,
            structural.status.value if structural else ProofStatus.NOT_APPLICABLE.value,
            structural.family if structural else "none",
            structural.calculation_trace if structural else (),
            structural.receipt_sha256 if structural else "",
            _canonical_sha(payload),
        )


_load_model()
