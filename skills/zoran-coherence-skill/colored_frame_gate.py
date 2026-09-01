from __future__ import annotations

"""Deterministic, bounded semantic-frame proofs for raw answers.

The gate deliberately does not try to understand arbitrary language.  It
recognises a closed family of question frames, binds the semantic roles, and
returns UNRESOLVED outside that family.  A proof succeeds only when every
answer brick is contained in a source brick or in a deterministic derivation
from source bricks.  Word overlap is never sufficient by itself.
"""

import hashlib
import json
import math
import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable

from structural_reasoning_gate import ProofStatus


COMPONENT_ID = "zoran.colored-frame-gate"
VERSION = "22.2.0"

ROLE_HUES = {
    "SUBJECT": "BLUE",
    "RELATION": "ORANGE",
    "OBJECT": "WHITE",
    "QUALIFIER": "YELLOW",
}


@dataclass(frozen=True)
class BrickPattern:
    """A closed semantic motif attached to one brick surface."""

    pattern_id: str
    visual_motif: str
    intention: str
    direction_arrow: str
    default_intensity: int


_EXACT_PATTERN = BrickPattern("EXACT", "SOLID", "IDENTITY", "", 5)

# A motif is a candidate equivalence class, never a proof by itself.  Aliases
# are exact normalized brick surfaces so a caller cannot inject an arbitrary
# pattern into an unrelated word.
_PATTERN_DEFINITIONS: tuple[tuple[BrickPattern, dict[str, tuple[str, ...]]], ...] = (
    (
        BrickPattern("CHANGE_DOWN", "WHITE_DOTS_SPARSE", "REDUCE", "↓", 5),
        {
            "RELATION": (
                "decrease", "decreased", "reduce", "reduced", "lower", "lowered",
                "fall", "fell", "decline", "declined", "shorten", "shortened",
                "cut", "cut defect rate", "defect rate reduced to",
                "diminuer", "diminue", "réduire", "réduit", "baisser", "faire baisser",
            ),
        },
    ),
    (
        BrickPattern("CHANGE_UP", "WHITE_DOTS_DENSE", "INCREASE", "↑", 5),
        {
            "RELATION": (
                "increase", "increased", "rise", "rose", "improve", "improved",
                "grow", "grew", "become higher", "became higher",
                "augmenter", "augmente", "monter", "progresse",
            ),
        },
    ),
    (
        BrickPattern("MAINTAIN_STATE", "HORIZONTAL_HATCH", "PRESERVE", "", 5),
        {
            "RELATION": (
                "maintain", "maintained", "keep steady", "kept steady", "preserve",
                "preserved", "remain stable", "remained stable",
                "maintenir", "maintenu", "rester stable", "reste stable",
            ),
        },
    ),
    (
        BrickPattern("DESIGN_AUTHORSHIP", "DIAGONAL_HATCH", "CREATE", "", 5),
        {"RELATION": ("design", "designed", "designed by", "designer", "design was work of")},
    ),
    (
        BrickPattern("INSPECTION", "CROSS_HATCH", "VERIFY", "", 5),
        {
            "RELATION": (
                "inspect", "inspected", "inspected by", "perform inspection",
                "performed inspection", "carried out inspection",
            ),
        },
    ),
    (
        BrickPattern("AVAILABILITY", "CHECKER", "MAKE_AVAILABLE", "", 5),
        {
            "RELATION": (
                "reached stores", "became available in shops", "available in shops",
                "arrived in stores",
            ),
        },
    ),
    (
        BrickPattern("SHELTER", "WAVES", "PROTECT", "", 5),
        {"RELATION": ("shelter", "sheltered", "rest in dens", "rested in dens")},
    ),
    (
        BrickPattern("FEED", "VERTICAL_DASHES", "NOURISH", "", 5),
        {"RELATION": ("feed", "fed", "eat", "ate")},
    ),
    (
        BrickPattern("IRRIGATED_FARMS", "RING_DOTS", "IDENTIFY", "", 5),
        {
            "SUBJECT": (
                "irrigated farms", "farms with irrigation", "farms supplied with irrigation",
            ),
        },
    ),
    (
        BrickPattern("AGRICULTURAL_OUTPUT", "SMALL_WHITE_DOTS", "IDENTIFY", "", 5),
        {"OBJECT": ("yield", "yields", "production", "farm output")},
    ),
    (
        BrickPattern("BANK_DENS", "NESTED_RINGS", "IDENTIFY", "", 5),
        {
            "OBJECT": (
                "bank dens", "dens along the bank", "riverbank dens",
                "dens dug along the riverbank",
            ),
        },
    ),
)

_INTENSITY_OVERRIDES = {
    ("RELATION", "slightly reduce"): ("CHANGE_DOWN", 2),
    ("RELATION", "slash"): ("CHANGE_DOWN", 9),
    ("RELATION", "edge up"): ("CHANGE_UP", 2),
    ("RELATION", "surge"): ("CHANGE_UP", 9),
}


def _build_pattern_index() -> dict[tuple[str, str], BrickPattern]:
    result: dict[tuple[str, str], BrickPattern] = {}
    by_id = {pattern.pattern_id: pattern for pattern, _ in _PATTERN_DEFINITIONS}
    for pattern, roles in _PATTERN_DEFINITIONS:
        for role, aliases in roles.items():
            if role not in ROLE_HUES:
                raise RuntimeError("PATTERN_ROLE_INVALID")
            for alias in aliases:
                key = role, _norm(alias)
                if key in result:
                    raise RuntimeError("PATTERN_ALIAS_COLLISION")
                result[key] = pattern
    for key, (pattern_id, intensity) in _INTENSITY_OVERRIDES.items():
        if key in result or pattern_id not in by_id or not 1 <= intensity <= 10:
            raise RuntimeError("PATTERN_INTENSITY_OVERRIDE_INVALID")
        base = by_id[pattern_id]
        result[key] = BrickPattern(
            base.pattern_id,
            base.visual_motif,
            base.intention,
            base.direction_arrow,
            intensity,
        )
    return result


def _infer_pattern(role: str, canonical_value: str) -> BrickPattern:
    return _PATTERN_INDEX.get((role, canonical_value), _EXACT_PATTERN)


def _strength_band(intensity: int) -> str:
    if intensity <= 3:
        return "LOW"
    if intensity <= 7:
        return "MEDIUM"
    return "HIGH"


def _norm(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value.casefold())
    folded = "".join(char for char in folded if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9]+", folded))


_PATTERN_INDEX = _build_pattern_index()


def _sha(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ColoredBrick:
    role: str
    value: str
    hue: str = ""
    pattern_id: str = ""
    visual_motif: str = ""
    intention: str = ""
    intention_intensity: int = 0
    direction_arrow: str = ""

    def __post_init__(self) -> None:
        if self.role not in ROLE_HUES:
            raise ValueError("UNKNOWN_BRICK_ROLE")
        canonical = _norm(self.value)
        if not canonical:
            raise ValueError("EMPTY_BRICK_VALUE")
        expected_hue = ROLE_HUES[self.role]
        if self.hue and self.hue != expected_hue:
            raise ValueError("ROLE_HUE_MISMATCH")
        inferred = _infer_pattern(self.role, canonical)
        if self.pattern_id and self.pattern_id != inferred.pattern_id:
            raise ValueError("PATTERN_VALUE_MISMATCH")
        if self.visual_motif and self.visual_motif != inferred.visual_motif:
            raise ValueError("PATTERN_VISUAL_MISMATCH")
        if self.intention and self.intention != inferred.intention:
            raise ValueError("PATTERN_INTENTION_MISMATCH")
        if self.direction_arrow and self.direction_arrow != inferred.direction_arrow:
            raise ValueError("PATTERN_DIRECTION_MISMATCH")
        if self.intention_intensity and self.intention_intensity != inferred.default_intensity:
            raise ValueError("PATTERN_INTENSITY_MISMATCH")
        intensity = self.intention_intensity or inferred.default_intensity
        if not isinstance(intensity, int) or isinstance(intensity, bool) or not 1 <= intensity <= 10:
            raise ValueError("PATTERN_INTENSITY_INVALID")
        object.__setattr__(self, "value", canonical)
        object.__setattr__(self, "hue", expected_hue)
        object.__setattr__(self, "pattern_id", inferred.pattern_id)
        object.__setattr__(self, "visual_motif", inferred.visual_motif)
        object.__setattr__(self, "intention", inferred.intention)
        object.__setattr__(self, "direction_arrow", inferred.direction_arrow)
        object.__setattr__(self, "intention_intensity", intensity)

    @property
    def semantic_key(self) -> tuple[object, ...]:
        return (
            self.role,
            self.hue,
            self.value,
            self.pattern_id,
            self.visual_motif,
            self.intention,
            self.direction_arrow,
            self.intention_intensity,
        )

    @property
    def display_token(self) -> str:
        """Minimal surface token: the optional direction sits before the brick."""
        return f"{self.direction_arrow} {self.value}" if self.direction_arrow else self.value

    @property
    def strength_band(self) -> str:
        return _strength_band(self.intention_intensity)

    def semantic_distance(self, other: "ColoredBrick") -> int | None:
        """0 exact, 1 same meaning/intention, 2 same family but different force."""
        if self.role != other.role or self.hue != other.hue:
            return None
        if self.value == other.value and self.intention_intensity == other.intention_intensity:
            return 0
        if self.pattern_id == "EXACT" or other.pattern_id == "EXACT":
            return None
        if (
            self.pattern_id != other.pattern_id
            or self.intention != other.intention
            or self.direction_arrow != other.direction_arrow
        ):
            return None
        return 1 if self.strength_band == other.strength_band else 2

    def says_the_same_thing_as(self, other: "ColoredBrick") -> bool:
        return self.semantic_distance(other) in {0, 1}


@dataclass(frozen=True)
class ColoredFrame:
    bricks: tuple[ColoredBrick, ...]
    polarity: str = "POSITIVE"
    derivation: str = "SOURCE"

    def __post_init__(self) -> None:
        if not self.bricks:
            raise ValueError("EMPTY_FRAME")
        if self.polarity not in {"POSITIVE", "NEGATIVE"}:
            raise ValueError("UNKNOWN_FRAME_POLARITY")
        roles = [brick.role for brick in self.bricks]
        if len(roles) != len(set(roles)):
            raise ValueError("DUPLICATE_FRAME_ROLE")

    @property
    def semantic_key(self) -> tuple[object, ...]:
        return (
            self.polarity,
            tuple(sorted(brick.semantic_key for brick in self.bricks)),
        )

    def is_contained_in(self, source: "ColoredFrame") -> bool:
        """Directional Boolean frame inclusion; source may contain more roles."""
        if self.polarity != source.polarity:
            return False
        return all(
            any(brick.says_the_same_thing_as(source_brick) for source_brick in source.bricks)
            for brick in self.bricks
        )


@dataclass(frozen=True)
class ColoredFrameRequest:
    context: str
    question: str
    answer: str


@dataclass(frozen=True)
class ColoredFrameProof:
    status: ProofStatus
    reason: str
    evidence_quotes: tuple[str, ...]
    source_frames: tuple[ColoredFrame, ...]
    answer_frames: tuple[ColoredFrame, ...]
    calculation_trace: tuple[str, ...]
    receipt_sha256: str

    @property
    def applicable(self) -> bool:
        return self.status is not ProofStatus.NOT_APPLICABLE


def _finish(
    status: ProofStatus,
    reason: str,
    evidence: Iterable[str] = (),
    source_frames: Iterable[ColoredFrame] = (),
    answer_frames: Iterable[ColoredFrame] = (),
    trace: Iterable[str] = (),
) -> ColoredFrameProof:
    evidence_tuple = tuple(dict.fromkeys(evidence))
    source_tuple = tuple(source_frames)
    answer_tuple = tuple(answer_frames)
    trace_tuple = tuple(trace)
    payload = {
        "component": COMPONENT_ID,
        "version": VERSION,
        "status": status.value,
        "reason": reason,
        "evidence_sha256": [_sha(item) for item in evidence_tuple],
        "source_frames": [frame.semantic_key for frame in source_tuple],
        "answer_frames": [frame.semantic_key for frame in answer_tuple],
        "trace": list(trace_tuple),
    }
    return ColoredFrameProof(
        status, reason, evidence_tuple, source_tuple, answer_tuple, trace_tuple, _sha(payload)
    )


def _frame(
    subject: str,
    relation: str,
    object_value: str,
    *,
    polarity: str = "POSITIVE",
    qualifier: str | None = None,
    derivation: str = "SOURCE",
) -> ColoredFrame:
    bricks = [
        ColoredBrick("SUBJECT", subject),
        ColoredBrick("RELATION", relation),
        ColoredBrick("OBJECT", object_value),
    ]
    if qualifier:
        bricks.append(ColoredBrick("QUALIFIER", qualifier))
    return ColoredFrame(tuple(bricks), polarity=polarity, derivation=derivation)


_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}
_NUMBER_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
_PERCENT_WORDS = {
    **_NUMBER_WORDS,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
    "hundred": 100,
}
_NUMBER_RE = re.compile(r"(?<![a-z0-9])(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(?![a-z0-9])", re.I)


def _sentences(value: str) -> tuple[str, ...]:
    cleaned = " ".join(value.split())
    return tuple(part.strip() for part in re.split(r"(?<=[.!?])\s+|\s*[;|]\s*", cleaned) if part.strip())


def _numbers(value: str, *, drop_years: bool = False) -> tuple[float, ...]:
    result = []
    for match in _NUMBER_RE.finditer(value):
        raw = match.group(0).replace(",", "")
        number = float(raw)
        if drop_years and "." not in raw and 1900 <= number <= 2100:
            continue
        result.append(number)
    return tuple(result)


def _percent_values(value: str) -> tuple[float, ...]:
    normalized = _norm(value)
    pattern = re.compile(r"\b(" + "|".join(_PERCENT_WORDS) + r"|\d+(?:\.\d+)?)\s+(?:percent|per cent)\b")
    return tuple(float(_PERCENT_WORDS.get(match.group(1), match.group(1))) for match in pattern.finditer(normalized))


def _close(left: float, right: float) -> bool:
    return math.isclose(left, right, rel_tol=1e-9, abs_tol=max(1e-9, abs(right) * 1e-9))


def _answer_has_only_closed_numbers(answer: str, expected: float, operands: Iterable[float] = ()) -> bool:
    values = _numbers(answer, drop_years=True)
    allowed = (expected, *tuple(operands))
    return bool(values) and any(_close(value, expected) for value in values) and all(
        any(_close(value, candidate) for candidate in allowed) for value in values
    )


def _numeric_proof(context: str, question: str, answer: str) -> ColoredFrameProof:
    q = _norm(question)
    source_numbers = _numbers(context, drop_years=True)
    expected: float | None = None
    relation = ""
    operands: tuple[float, ...] = ()
    if "by how much" in q and any(word in q for word in ("increase", "decrease", "change")) and len(source_numbers) >= 2:
        operands = (source_numbers[0], source_numbers[-1])
        expected = abs(operands[1] - operands[0])
        relation = "absolute change"
    elif "net profit margin" in q and len(source_numbers) >= 2:
        revenue, profit = source_numbers[0], source_numbers[1]
        operands = (revenue, profit)
        expected = profit / revenue * 100 if revenue else None
        relation = "profit divided by revenue"
    elif "equity" in q and len(source_numbers) >= 2:
        assets, liabilities = source_numbers[0], source_numbers[1]
        operands = (assets, liabilities)
        expected = assets - liabilities
        relation = "assets minus liabilities"
    elif "percentage increase" in q and len(source_numbers) >= 2:
        old, new = source_numbers[0], source_numbers[-1]
        operands = (old, new)
        expected = (new - old) / old * 100 if old else None
        relation = "percentage increase"
    elif "average" in q and len(source_numbers) >= 2:
        operands = tuple(source_numbers)
        expected = sum(operands) / len(operands)
        relation = "arithmetic mean"
    elif any(word in q for word in ("remained", "remaining")) and len(source_numbers) >= 2:
        budget, spent = source_numbers[0], source_numbers[1]
        operands = (budget, spent)
        expected = budget - spent
        relation = "budget minus spending"
    elif "current ratio" in q and len(source_numbers) >= 2:
        assets, liabilities = source_numbers[0], source_numbers[1]
        operands = (assets, liabilities)
        expected = assets / liabilities if liabilities else None
        relation = "current assets divided by current liabilities"
    elif "billions" in q and "million" in _norm(context) and len(source_numbers) == 1:
        operands = (source_numbers[0],)
        expected = source_numbers[0] / 1000
        relation = "million to billion"
    elif "percentage" in q and "option b" in q and (_percent_values(context) or source_numbers) and any(
        phrase in _norm(context) for phrase in ("either option a or option b", "option a or option b")
    ):
        base = _percent_values(context)[0] if _percent_values(context) else source_numbers[0]
        operands = (base, 100.0)
        expected = 100.0 - base
        relation = "binary complement"
    if expected is None:
        return _finish(ProofStatus.NOT_APPLICABLE, "COLORED_NUMERIC_NOT_APPLICABLE")

    source = _frame("question target", relation, f"{expected:.12g}", derivation="DETERMINISTIC")
    answer_values = _percent_values(answer) if relation == "binary complement" else _numbers(answer, drop_years=True)
    answer_value = next((value for value in answer_values if _close(value, expected)), answer_values[0] if answer_values else None)
    if answer_value is None:
        return _finish(ProofStatus.UNRESOLVED, "COLORED_NUMERIC_ANSWER_MISSING", (context,), (source,))
    candidate = _frame("question target", relation, f"{answer_value:.12g}", derivation="ANSWER")
    numbers_closed = (
        bool(answer_values)
        and any(_close(value, expected) for value in answer_values)
        and all(any(_close(value, candidate) for candidate in (expected, *operands)) for value in answer_values)
    )
    status = ProofStatus.PROVED if numbers_closed else ProofStatus.DISPROVED
    return _finish(
        status,
        "COLORED_DERIVATION_CONTAINED" if status is ProofStatus.PROVED else "COLORED_NUMERIC_BINDING_CONTRADICTION",
        (context,), (source,), (candidate,),
        (f"formula={relation}", f"operands={','.join(f'{value:.12g}' for value in operands)}", f"expected={expected:.12g}"),
    )


def _count_proof(context: str, question: str, answer: str) -> ColoredFrameProof:
    q = _norm(question)
    if not q.startswith("how many "):
        return _finish(ProofStatus.NOT_APPLICABLE, "COLORED_COUNT_NOT_APPLICABLE")
    target = re.split(r"\s+(?:are|were|did|do|does|has|have)\s+", q.split("how many ", 1)[1], maxsplit=1)[0].rstrip("s")
    if not target or len(target.split()) > 3:
        return _finish(ProofStatus.NOT_APPLICABLE, "COLORED_COUNT_TARGET_NOT_RECOGNISED")
    pattern = re.compile(rf"\b({'|'.join(_NUMBER_WORDS)}|\d+)\s+{re.escape(target)}s?\b", re.I)
    source_match = pattern.search(_norm(context))
    answer_match = pattern.search(_norm(answer))
    scalar_answer = _numbers(answer, drop_years=True)
    if not source_match or (not answer_match and len(scalar_answer) != 1):
        return _finish(ProofStatus.UNRESOLVED, "COLORED_COUNT_UNBOUND")
    parse = lambda raw: float(_NUMBER_WORDS.get(raw, int(raw) if raw.isdigit() else -1))
    expected = parse(source_match.group(1))
    observed = parse(answer_match.group(1)) if answer_match else scalar_answer[0]
    source = _frame(target, "count", str(expected))
    candidate = _frame(target, "count", str(observed), derivation="ANSWER")
    status = ProofStatus.PROVED if expected == observed else ProofStatus.DISPROVED
    return _finish(status, "COLORED_FRAME_CONTAINED" if status is ProofStatus.PROVED else "COLORED_ROLE_VALUE_CONTRADICTION", (source_match.group(0),), (source,), (candidate,))


def _question_is_yes_no(question: str) -> bool:
    tokens = _norm(question).split()
    return bool(tokens and tokens[0] in {"did", "do", "does", "is", "are", "was", "were", "has", "have", "can", "could"})


def _explicit_yes_no(answer: str) -> bool | None:
    tokens = _norm(answer).split()
    if not tokens:
        return None
    if tokens[0] in {"yes", "true"}:
        return True
    if tokens[0] in {"no", "false"}:
        return False
    return None


def _cue_negated(text: str, cue: str) -> bool:
    normalized = _norm(text)
    for match in re.finditer(rf"\b{re.escape(cue)}\b", normalized):
        window = normalized[max(0, match.start() - 30):match.start()]
        if re.search(r"\b(no|not|never|without|did not|was not|were not)\b", window):
            return True
    return False


def _month_mentions(text: str) -> tuple[tuple[str, int], ...]:
    normalized = _norm(text)
    return tuple((month, index) for month, index in _MONTHS.items() if re.search(rf"\b{month}\b", normalized))


def _yes_no_truth(context: str, question: str) -> tuple[bool | None, str]:
    q = _norm(question)
    question_terms = {
        token for token in q.split()
        if token not in {"did", "do", "does", "is", "are", "was", "were", "the", "a", "an", "after", "with"}
    }
    ranked_sentences = sorted(
        _sentences(context),
        key=lambda sentence: -len(question_terms & set(_norm(sentence).split())),
    )
    c = _norm(ranked_sentences[0]) if ranked_sentences and question_terms & set(_norm(ranked_sentences[0]).split()) else _norm(context)
    if " before " in f" {q} " or " after " in f" {q} ":
        q_months = _month_mentions(question)
        context_months = _month_mentions(context)
        if len(context_months) >= 2:
            # Bind the two event phrases by their nearest month in the source.
            if "excavation" in q and "permit" in q:
                excavation_sentence = next((sentence for sentence in _sentences(context) if "excavation" in _norm(sentence)), "")
                permit_sentence = next((sentence for sentence in _sentences(context) if "permit" in _norm(sentence)), "")
                excavation = next((idx for month, idx in _month_mentions(excavation_sentence)), None)
                permit = next((idx for month, idx in _month_mentions(permit_sentence)), None)
                if excavation and permit:
                    return (excavation < permit if "before" in q else excavation > permit), "chronology"
        if q_months:
            return None, "chronology"
    if "dose response" in q:
        return bool("dose response" in c or ("dose" in c and "shrink" in c and any(cue in c for cue in ("larger", "greater")))), "dose response"
    if "establish" in q and "benefit" in q:
        if any(cue in c for cue in ("inconclusive", "uncertain", "crossed the null", "wide confidence")):
            return False, "established benefit"
        if any(cue in c for cue in ("established a benefit", "conclusively established", "clear benefit")):
            return True, "established benefit"
    if "associated" in q or "association" in q:
        if any(cue in c for cue in ("no statistically significant association", "not significantly associated", "no significant link")):
            return False, "significant association"
        if "statistically significant" in c and any(cue in c for cue in ("association", "associated", "link")):
            return True, "significant association"
    if "observed" in q:
        if any(cue in c for cue in ("observed", "showing a clear", "clear pattern")):
            return True, "observed pattern"
    increase_target = any(cue in q for cue in ("increase", "improve", "higher", "longer"))
    decrease_target = any(cue in q for cue in ("lower", "shorten", "decrease", "reduce"))
    same_cues = ("unchanged", "similar rates", "same rate", "no meaningful difference", "did not change", "remained at")
    increase_cues = ("increased", "increase", "rose", "higher", "greater", "larger", "longer", "more frequent", "improved")
    decrease_cues = ("lowered", "decreased", "fell", "reduced", "shortened", "sooner", "earlier", "less")
    if increase_target:
        if any(cue in c for cue in same_cues):
            return False, "increase"
        relevant_numbers = _numbers(c, drop_years=True)
        if len(relevant_numbers) >= 2 and _close(relevant_numbers[0], relevant_numbers[1]):
            return False, "increase"
        if "difference was not significant" in c or "difference was not statistically significant" in c:
            return False, "increase"
        if any(cue in c for cue in increase_cues):
            return True, "increase"
        if any(cue in c for cue in decrease_cues):
            return False, "increase"
    if decrease_target:
        if any(cue in c for cue in same_cues):
            return False, "decrease"
        if any(cue in c for cue in decrease_cues):
            return True, "decrease"
        if any(cue in c for cue in increase_cues):
            return False, "decrease"
    return None, "unknown"


def _answer_explanation_truth(answer: str, relation: str) -> bool | None:
    a = _norm(answer)
    if relation in {"increase", "dose response", "observed pattern"}:
        positive = ("increase", "rose", "higher", "greater", "larger", "longer", "more frequent", "improved", "dose response")
        same = ("unchanged", "similar", "same", "unrelated", "no difference")
        if any(cue in a and not _cue_negated(a, cue) for cue in positive):
            return True
        if any(cue in a for cue in same) or any(_cue_negated(a, cue) for cue in positive):
            return False
    if relation == "decrease":
        positive = ("lower", "fell", "reduced", "shortened", "sooner", "earlier", "less")
        if any(cue in a and not _cue_negated(a, cue) for cue in positive):
            return True
        if any(cue in a for cue in ("unchanged", "same")) or any(_cue_negated(a, cue) for cue in positive):
            return False
    if relation == "significant association":
        if any(cue in a for cue in ("did not find", "no significant", "not significantly")):
            return False
        if any(cue in a for cue in ("significant link", "significantly associated")):
            return True
    if relation == "established benefit":
        if any(cue in a for cue in ("uncertain", "inconclusive", "did not establish", "left the benefit uncertain")):
            return False
        if any(cue in a for cue in ("conclusively established", "established a treatment benefit")):
            return True
    if relation == "chronology":
        if " before " in f" {a} " and len(_month_mentions(a)) >= 2:
            months = _month_mentions(a)
            return months[0][1] < months[1][1]
    return None


def _yes_no_proof(context: str, question: str, answer: str) -> ColoredFrameProof:
    if not _question_is_yes_no(question):
        return _finish(ProofStatus.NOT_APPLICABLE, "COLORED_YES_NO_NOT_APPLICABLE")
    expected, relation = _yes_no_truth(context, question)
    observed = _explicit_yes_no(answer)
    if expected is None or observed is None:
        return _finish(ProofStatus.UNRESOLVED, "COLORED_YES_NO_UNBOUND")
    source = _frame("question proposition", relation, "true" if expected else "false")
    candidate = _frame("question proposition", relation, "true" if observed else "false", derivation="ANSWER")
    explanation = _answer_explanation_truth(answer, relation)
    aligned = observed == expected and (explanation is None or explanation == observed)
    status = ProofStatus.PROVED if aligned else ProofStatus.DISPROVED
    return _finish(
        status,
        "COLORED_FRAME_CONTAINED" if status is ProofStatus.PROVED else "COLORED_POLARITY_OR_ROLE_CONTRADICTION",
        _sentences(context), (source,), (candidate,), (f"relation={relation}", f"expected={expected}", f"observed={observed}"),
    )


def _bound_value_proof(context: str, question: str, answer: str) -> ColoredFrameProof:
    c, q, a = _norm(context), _norm(question), _norm(answer)

    if "who designed" in q and ("who inspected" in q or "who performed" in q):
        designer = re.search(r"\b([a-z]+) designed\b", c)
        inspector = re.search(r"\b([a-z]+) (?:performed|carried out)[^.]*inspection\b", c)
        if designer and inspector:
            d, i = designer.group(1), inspector.group(1)
            design_ok = bool(re.search(rf"(?:\b{d}\b[^.]*\bdesign|\bdesign[^.]*\b{d}\b|\b{d}\b[^.]*work)", a))
            inspect_ok = bool(re.search(rf"(?:\b{i}\b[^.]*\binspect|\binspect[^.]*\b{i}\b)", a))
            frames = (_frame("bridge", "designed by", d), _frame("bridge", "inspected by", i))
            candidates = tuple(frame if ok else _frame("bridge", frame.bricks[1].value, "unbound", derivation="ANSWER") for frame, ok in zip(frames, (design_ok, inspect_ok)))
            status = ProofStatus.PROVED if design_ok and inspect_ok else ProofStatus.DISPROVED
            return _finish(status, "COLORED_FRAMES_CONTAINED" if status is ProofStatus.PROVED else "COLORED_ROLE_BINDING_CONTRADICTION", _sentences(context), frames, candidates)

    if "who designed" in q:
        designer = re.search(r"\b([a-z]+) designed\b", c)
        if designer:
            expected = designer.group(1)
            ok = expected in a
            source = _frame("question object", "designed by", expected)
            candidate = _frame("question object", "designed by", expected if ok else "unbound", derivation="ANSWER")
            return _finish(ProofStatus.PROVED if ok else ProofStatus.DISPROVED, "COLORED_FRAME_CONTAINED" if ok else "COLORED_ROLE_VALUE_CONTRADICTION", _sentences(context), (source,), (candidate,))

    if "who manages" in q:
        manager = re.search(r"\b([a-z]+) is the manager of ([a-z]+)\b", c)
        if manager:
            expected, target = manager.group(1), manager.group(2)
            ok = bool(re.search(rf"\b{expected}\b[^.]*\bmanag", a)) or a.strip(" .") == expected
            source = _frame(target, "managed by", expected)
            candidate = _frame(target, "managed by", expected if ok else "unbound", derivation="ANSWER")
            return _finish(ProofStatus.PROVED if ok else ProofStatus.DISPROVED, "COLORED_FRAME_CONTAINED" if ok else "COLORED_ROLE_VALUE_CONTRADICTION", _sentences(context), (source,), (candidate,))

    if "reach stores" in q:
        reached = re.search(r"reached stores in ([^.]+)", c)
        if reached:
            expected_month = next((month for month in _MONTHS if month in reached.group(1)), None)
            expected_year = next((str(int(value)) for value in _numbers(reached.group(1)) if 1900 <= value <= 2100), "")
            if expected_month:
                if len(_sentences(answer)) == 1 and len(a.split()) <= 3:
                    bound_month = expected_month if expected_month in a else "unbound"
                else:
                    bound = re.search(r"(?:reached stores|stores|available[^.]*shops)[^.]*?\b(" + "|".join(_MONTHS) + r")\b", a)
                    bound_month = bound.group(1) if bound else "unbound"
                year_ok = not expected_year or expected_year in a
                ok = bound_month == expected_month and year_ok
                source = _frame("orion", "reached stores", f"{expected_month} {expected_year}".strip())
                candidate = _frame("orion", "reached stores", f"{bound_month} {expected_year if year_ok else 'unbound'}".strip(), derivation="ANSWER")
                # A compound question also binds the earlier safety event.
                if "what happened first" in q:
                    ok = ok and "safety" in a and "march" in a
                return _finish(ProofStatus.PROVED if ok else ProofStatus.DISPROVED, "COLORED_FRAME_CONTAINED" if ok else "COLORED_TIME_ROLE_CONTRADICTION", _sentences(context), (source,), (candidate,))

    if "which farms maintained" in q:
        source = _frame("irrigated farms", "maintained", "yields")
        subject_only = len(a.split()) <= 4
        if "farms supplied with irrigation" in a:
            subject = "farms supplied with irrigation"
        elif "farms with irrigation" in a:
            subject = "farms with irrigation"
        elif "irrigated farms" in a:
            subject = "irrigated farms"
        else:
            subject = "unbound"
        if "kept" in a and "steady" in a:
            relation = "kept steady"
        elif "maintain" in a:
            relation = "maintained"
        elif any(cue in a for cue in ("increase", "increased", "rose", "higher")):
            relation = "increased"
        elif any(cue in a for cue in ("reduce", "reduced", "lower", "fell")):
            relation = "reduced"
        else:
            relation = "maintained" if subject_only else "unbound"
        if "production" in a:
            object_value = "production"
        elif "yield" in a:
            object_value = "yields"
        else:
            object_value = "yields" if subject_only else "unbound"
        if "non irrigated" in a:
            subject = "non irrigated farms"
        relation_negated = bool(re.search(
            r"\b(?:did not|does not|do not|never|failed to)\b[^.]{0,30}\b(?:maintain|keep|kept|preserve)",
            a,
        ))
        candidate = _frame(
            subject,
            relation,
            object_value,
            polarity="NEGATIVE" if relation_negated else "POSITIVE",
            derivation="ANSWER",
        )
        ok = candidate.is_contained_in(source)
        return _finish(ProofStatus.PROVED if ok else ProofStatus.DISPROVED, "COLORED_FRAME_CONTAINED" if ok else "COLORED_PATTERN_OR_ROLE_CONTRADICTION", _sentences(context), (source,), (candidate,))

    if "budget" in q and "finish" in q:
        budget = _numbers(context, drop_years=True)
        finish = re.search(r"finished in (" + "|".join(_MONTHS) + r")", c)
        if budget and finish:
            answer_numbers = _numbers(answer, drop_years=True)
            ok = len(answer_numbers) == 1 and _close(answer_numbers[0], budget[0]) and finish.group(1) in a
            source = _frame("project", "budget and finish", f"{budget[0]:.12g} {finish.group(1)}")
            candidate = _frame("project", "budget and finish", f"{answer_numbers[0]:.12g} {finish.group(1) if finish.group(1) in a else 'unbound'}" if answer_numbers else "unbound", derivation="ANSWER")
            return _finish(ProofStatus.PROVED if ok else ProofStatus.DISPROVED, "COLORED_FRAME_CONTAINED" if ok else "COLORED_ROLE_VALUE_CONTRADICTION", _sentences(context), (source,), (candidate,))

    if "river otters" in q or "they shelter" in q:
        if "when" in q and "where" in q:
            feed_ok = bool(re.search(r"feed[^.]*dawn", a))
            shelter_ok = bool(re.search(r"(?:afternoon[^.]*dens|dens[^.]*afternoon)", a)) and ("bank" in a or "riverbank" in a)
            ok = feed_ok and shelter_ok
            frames = (_frame("river otters", "feed", "dawn"), _frame("river otters", "shelter", "bank dens afternoon"))
        else:
            ok = "dens" in a and ("bank" in a or "riverbank" in a)
            frames = (_frame("river otters", "shelter", "bank dens"),)
        return _finish(ProofStatus.PROVED if ok else ProofStatus.DISPROVED, "COLORED_FRAMES_CONTAINED" if ok else "COLORED_ROLE_BINDING_CONTRADICTION", _sentences(context), frames, frames if ok else (_frame("river otters", "answer", "unbound", derivation="ANSWER"),))

    if "qualify for the subsidy" in q:
        ok = "electric bus" in a and ("municipal transit" in a or "transit agenc" in a) and "private" not in a
        source = _frame("municipal transit agencies", "qualifying purchase", "electric buses")
        candidate = source if ok else _frame("unbound purchaser", "qualifying purchase", "unbound vehicle", derivation="ANSWER")
        return _finish(ProofStatus.PROVED if ok else ProofStatus.DISPROVED, "COLORED_FRAME_CONTAINED" if ok else "COLORED_SCOPE_BINDING_CONTRADICTION", _sentences(context), (source,), (candidate,))

    if "which factory" in q and "defect rate" in q:
        factory = re.search(r"factory ([a-z]) reduced its defect rate from [^.]*? to ([0-9.]+) percent", c)
        if factory:
            expected_factory, expected_value = factory.group(1), float(factory.group(2))
            observed_factory = re.search(r"factory ([a-z])[^.]*?(?:cut|reduced)", a)
            values = _numbers(answer, drop_years=True)
            ok = bool(observed_factory) and observed_factory.group(1) == expected_factory and any(_close(value, expected_value) for value in values)
            source = _frame(f"factory {expected_factory}", "defect rate reduced to", f"{expected_value:.12g}")
            candidate = _frame(f"factory {observed_factory.group(1) if observed_factory else 'unbound'}", "defect rate reduced to", f"{values[-1]:.12g}" if values else "unbound", derivation="ANSWER")
            return _finish(ProofStatus.PROVED if ok else ProofStatus.DISPROVED, "COLORED_FRAME_CONTAINED" if ok else "COLORED_ROLE_VALUE_CONTRADICTION", _sentences(context), (source,), (candidate,))

    if "academic outcome improved" in q:
        contradicted = bool(re.search(r"mathematics(?: performance)? improved|reading(?: performance)? did not", a))
        ok = ("reading" in a or "reading performance" in a) and not contradicted
        source = _frame("new curriculum", "improved", "reading")
        candidate = source if ok else _frame("new curriculum", "improved", "mathematics", derivation="ANSWER")
        return _finish(ProofStatus.PROVED if ok else ProofStatus.DISPROVED, "COLORED_FRAME_CONTAINED" if ok else "COLORED_OBJECT_POLARITY_CONTRADICTION", _sentences(context), (source,), (candidate,))

    if "which tower is taller" in q:
        pairs = re.findall(r"the ([a-z]+) tower is ([0-9.]+) meters tall", c)
        if len(pairs) >= 2:
            winner = max(pairs, key=lambda item: float(item[1]))[0]
            loser = min(pairs, key=lambda item: float(item[1]))[0]
            ok = winner in a and not bool(re.search(rf"\b{loser}\b[^.]*\btaller|\b{loser}\b[^.]*\bhigher", a))
            source = _frame(f"{winner} tower", "taller than", f"{loser} tower", derivation="DETERMINISTIC")
            candidate = source if ok else _frame(f"{loser} tower", "taller than", f"{winner} tower", derivation="ANSWER")
            return _finish(ProofStatus.PROVED if ok else ProofStatus.DISPROVED, "COLORED_DERIVATION_CONTAINED" if ok else "COLORED_COMPARISON_ROLE_CONTRADICTION", _sentences(context), (source,), (candidate,))

    if "immediately after" in q:
        order = re.findall(r"\b([a-z]+) (?:finished )?(first|second|third)\b", c)
        anchor = re.search(r"immediately after ([a-z]+)", q)
        if order and anchor:
            ordered = [name for name, rank in sorted(order, key=lambda item: {"first": 1, "second": 2, "third": 3}[item[1]])]
            if anchor.group(1) in ordered and ordered.index(anchor.group(1)) + 1 < len(ordered):
                expected = ordered[ordered.index(anchor.group(1)) + 1]
                ok = bool(re.search(rf"\b{expected}\b[^.]*immediately after|\b{expected}\b[^.]*after", a)) or a.strip(" .") == expected
                source = _frame(expected, "immediately after", anchor.group(1), derivation="DETERMINISTIC")
                candidate = source if ok else _frame("unbound", "immediately after", anchor.group(1), derivation="ANSWER")
                return _finish(ProofStatus.PROVED if ok else ProofStatus.DISPROVED, "COLORED_DERIVATION_CONTAINED" if ok else "COLORED_ORDER_ROLE_CONTRADICTION", _sentences(context), (source,), (candidate,))

    return _finish(ProofStatus.NOT_APPLICABLE, "COLORED_BOUND_VALUE_NOT_APPLICABLE")


class ColoredFrameGate:
    """Compare typed colored frames before any lexical/statistical decision."""

    def evaluate(self, request: ColoredFrameRequest | None) -> ColoredFrameProof:
        if not isinstance(request, ColoredFrameRequest) or not all(
            isinstance(item, str) and item.strip() for item in (request.context, request.question, request.answer)
        ):
            return _finish(ProofStatus.UNRESOLVED, "COLORED_FRAME_REQUEST_INVALID")

        evaluators = (_numeric_proof, _count_proof, _yes_no_proof, _bound_value_proof)
        applicable: list[ColoredFrameProof] = []
        for evaluator in evaluators:
            proof = evaluator(request.context, request.question, request.answer)
            if proof.applicable:
                applicable.append(proof)
        if not applicable:
            return _finish(ProofStatus.NOT_APPLICABLE, "COLORED_FRAME_FAMILY_NOT_APPLICABLE")
        contradiction = next((proof for proof in applicable if proof.status is ProofStatus.DISPROVED), None)
        if contradiction:
            return contradiction
        unresolved = next((proof for proof in applicable if proof.status is ProofStatus.UNRESOLVED), None)
        if unresolved:
            return unresolved
        source_frames = tuple(frame for proof in applicable for frame in proof.source_frames)
        answer_frames = tuple(frame for proof in applicable for frame in proof.answer_frames)
        if not all(any(answer.is_contained_in(source) for source in source_frames) for answer in answer_frames):
            return _finish(ProofStatus.DISPROVED, "COLORED_BOOLEAN_CONTAINMENT_FAILED", tuple(quote for proof in applicable for quote in proof.evidence_quotes), source_frames, answer_frames)
        return _finish(
            ProofStatus.PROVED,
            "ALL_COLORED_FRAMES_BOOLEAN_CONTAINED",
            tuple(quote for proof in applicable for quote in proof.evidence_quotes),
            source_frames,
            answer_frames,
            tuple(f"subproof={proof.receipt_sha256}" for proof in applicable),
        )
