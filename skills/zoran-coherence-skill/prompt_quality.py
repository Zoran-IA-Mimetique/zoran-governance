from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from math import isfinite
from typing import Sequence

from tolerance_skill import Decision

COMPONENT_ID = "ZORAN_PROMPT_QUALITY"
VERSION = "11.0.0"


def _norm(text: str) -> str:
    s = unicodedata.normalize("NFKD", text.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(re.findall(r"[a-z0-9%]+", s))


@dataclass(frozen=True)
class EvaluatorCriterion:
    criterion_id: str
    aliases: tuple[str, ...]
    required: bool = True

    def __post_init__(self):
        object.__setattr__(self, "aliases", tuple(self.aliases))


@dataclass(frozen=True)
class RangeAlignment:
    dimension_id: str
    prompt_min: float
    prompt_max: float
    evaluator_min: float
    evaluator_max: float


@dataclass(frozen=True)
class PromptQualityPolicy:
    max_repeat_trigram_ratio: float = 0.20
    max_symbol_noise_ratio: float = 0.35
    ambiguity_terms: tuple[str, ...] = (
        "best", "better", "strongest", "appropriate", "reasonable", "convincing",
        "relevant", "good", "optimal", "clear", "effective",
    )
    max_ambiguity_hits: int = 2

    def __post_init__(self):
        object.__setattr__(self, "ambiguity_terms", tuple(self.ambiguity_terms))


@dataclass(frozen=True)
class PromptQualityEvaluation:
    decision: Decision
    reasons: tuple[str, ...]
    hidden_criteria: tuple[str, ...]
    range_mismatches: tuple[str, ...]
    repeat_trigram_ratio: str
    symbol_noise_ratio: str
    ambiguity_hits: int
    receipt_sha256: str


class PromptQualityEngine:
    """Checks the coherence of the *input contract* before judging an output.

    This is intentionally bounded and deterministic. It does not infer a universal
    hidden intent. It compares the visible prompt with an explicit evaluator contract
    when that contract is available, and measures simple ambiguity/redundancy/noise.
    """

    def __init__(self, policy: PromptQualityPolicy | None = None):
        self.policy = policy or PromptQualityPolicy()
        if not isinstance(self.policy.max_repeat_trigram_ratio,(int,float)) or isinstance(self.policy.max_repeat_trigram_ratio,bool) or not isfinite(float(self.policy.max_repeat_trigram_ratio)) or not 0<=self.policy.max_repeat_trigram_ratio<=1:raise ValueError('invalid repeat threshold')
        if not isinstance(self.policy.max_symbol_noise_ratio,(int,float)) or isinstance(self.policy.max_symbol_noise_ratio,bool) or not isfinite(float(self.policy.max_symbol_noise_ratio)) or not 0<=self.policy.max_symbol_noise_ratio<=1:raise ValueError('invalid noise threshold')
        if not isinstance(self.policy.max_ambiguity_hits,int) or isinstance(self.policy.max_ambiguity_hits,bool) or self.policy.max_ambiguity_hits<0:raise ValueError('invalid ambiguity threshold')
        if any(not isinstance(x,str) or not x.strip() for x in self.policy.ambiguity_terms):raise ValueError('invalid ambiguity terms')

    def evaluate(
        self,
        prompt: str,
        *,
        evaluator_criteria: Sequence[EvaluatorCriterion] = (),
        range_alignments: Sequence[RangeAlignment] = (),
    ) -> PromptQualityEvaluation:
        evaluator_criteria=tuple(evaluator_criteria); range_alignments=tuple(range_alignments)
        request_sha=hashlib.sha256(json.dumps({'prompt':prompt,'evaluator_criteria':[x.__dict__ for x in evaluator_criteria],'range_alignments':[x.__dict__ for x in range_alignments],'policy':self.policy.__dict__},sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=True,default=repr).encode()).hexdigest()
        finish=lambda decision,reasons,hidden,mismatches,repeat,noise,hits:self._finish(decision,reasons,hidden,mismatches,repeat,noise,hits,request_sha)
        if not isinstance(prompt, str) or not prompt.strip():
            return finish(Decision.RETRY, ("PROMPT_MISSING",), (), (), 0.0, 0.0, 0)

        n = _norm(prompt)
        tokens = n.split()
        hidden: list[str] = []
        for c in evaluator_criteria:
            if not c.criterion_id or not c.aliases or not isinstance(c.required,bool) or any(not isinstance(alias,str) or not alias.strip() for alias in c.aliases):
                return finish(Decision.RETRY, ("EVALUATOR_CRITERION_INVALID",), (), (), 0.0, 0.0, 0)
            if c.required is True and not any(f" {_norm(alias)} " in f" {n} " for alias in c.aliases if _norm(alias)):
                hidden.append(c.criterion_id)

        mismatches: list[str] = []
        for r in range_alignments:
            values=(r.prompt_min,r.prompt_max,r.evaluator_min,r.evaluator_max)
            if not r.dimension_id or any(not isinstance(x,(int,float)) or isinstance(x,bool) or not isfinite(float(x)) for x in values) or r.prompt_min > r.prompt_max or r.evaluator_min > r.evaluator_max:
                return finish(Decision.RETRY, ("RANGE_ALIGNMENT_INVALID",), tuple(hidden), (), 0.0, 0.0, 0)
            if r.prompt_min != r.evaluator_min or r.prompt_max != r.evaluator_max:
                mismatches.append(r.dimension_id)

        tris = [tuple(tokens[i:i+3]) for i in range(max(0, len(tokens)-2))]
        repeat = ((len(tris) - len(set(tris))) / len(tris)) if tris else 0.0
        symbol_noise = sum(not (ch.isalnum() or ch.isspace()) for ch in prompt) / max(1, len(prompt))
        ambiguity_set = {_norm(x) for x in self.policy.ambiguity_terms}
        ambiguity_hits = sum(t in ambiguity_set for t in tokens)

        reasons: list[str] = []
        if hidden:
            reasons.append("EVALUATOR_CRITERIA_NOT_VISIBLE_IN_PROMPT")
        if mismatches:
            reasons.append("PROMPT_EVALUATOR_CONSTRAINT_MISMATCH")
        if repeat > self.policy.max_repeat_trigram_ratio:
            reasons.append("PROMPT_REDUNDANCY_HIGH")
        if symbol_noise > self.policy.max_symbol_noise_ratio:
            reasons.append("PROMPT_NOISE_HIGH")
        if ambiguity_hits > self.policy.max_ambiguity_hits:
            reasons.append("PROMPT_AMBIGUITY_HIGH")

        # Contract defects are repairable: RETRY, not VETO.
        decision = Decision.RETRY if reasons else Decision.PASS
        return finish(decision, tuple(reasons) or ("PROMPT_CONTRACT_COHERENT",), tuple(hidden), tuple(mismatches), repeat, symbol_noise, ambiguity_hits)

    def _finish(self, decision, reasons, hidden, mismatches, repeat, noise, ambiguity_hits,request_sha):
        payload = {
            "component": COMPONENT_ID,
            "version": VERSION,
            "request_sha256":request_sha,
            "decision": decision.value,
            "reasons": list(reasons),
            "hidden_criteria": list(hidden),
            "range_mismatches": list(mismatches),
            "repeat_trigram_ratio": f"{repeat:.12f}",
            "symbol_noise_ratio": f"{noise:.12f}",
            "ambiguity_hits": ambiguity_hits,
        }
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return PromptQualityEvaluation(
            decision, tuple(reasons), tuple(hidden), tuple(mismatches),
            payload["repeat_trigram_ratio"], payload["symbol_noise_ratio"], ambiguity_hits, digest
        )
