from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import re

from tolerance_skill import Decision
from components.semantic_color_patterns_v0.discourse_realizer_v1 import SemanticDiscourse
from components.semantic_color_patterns_v0.fluent_relational_realizer_v3 import (
    FluentRelationalRealizerV3,
    FluentRelationalRecomprehenderV3,
)
from components.semantic_color_patterns_v0.listener_ontology_v4 import build_listener_ontology
from components.semantic_color_patterns_v0.semantic_equivalence_normalizer_v4 import (
    SemanticEquivalenceNormalizerV4,
)
from components.semantic_color_patterns_v0.switch_resolver_v1 import resolve_switches


SOURCE_HEAD = "7b00352914aaacd429f550ce4224d2b3133dea7d"
COMPONENT_ID = "ZORAN_SEMANTIC_SPEECH_GATE"
VERSION = "23.0.0"
_TOKEN = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]+|[.,;:!?]", re.UNICODE)


def _digest(value: object) -> str:
    return sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class SemanticSpeechEvaluation:
    decision: Decision
    status: str
    speech: str | None
    target_sha256: str | None
    observed_sha256: str | None
    equivalence_decision: str | None
    reasons: tuple[str, ...]
    promotion: str
    source_head: str
    receipt_sha256: str


class SemanticSpeechGate:
    """Release speech only after exact reconstruction and semantic equivalence.

    This adapter does not replace K3, the claim/evidence gate, or the terminal
    controller.  It governs only the semantic-object-to-public-speech boundary.
    """

    def __init__(self) -> None:
        self._realizer = FluentRelationalRealizerV3()
        self._recomprehender = FluentRelationalRecomprehenderV3()
        self._normalizer = SemanticEquivalenceNormalizerV4(build_listener_ontology())

    @staticmethod
    def switches(text: str) -> tuple[tuple[int, str, str, tuple[int, ...]], ...]:
        if not isinstance(text, str) or not text.strip() or len(text) > 12_000:
            raise ValueError("switch analysis requires bounded non-empty text")
        tokens = _TOKEN.findall(text)
        resolved = resolve_switches(tokens)
        return tuple(
            (index, item.switch_type, item.scope_hint, item.evidence)
            for index, item in sorted(resolved.items())
        )

    def evaluate(self, discourse: SemanticDiscourse | None) -> SemanticSpeechEvaluation:
        if not isinstance(discourse, SemanticDiscourse):
            return self._finish(
                Decision.VETO,
                "SPEECH_BLOCKED",
                None,
                None,
                None,
                None,
                ("SEMANTIC_DISCOURSE_REQUIRED",),
            )
        try:
            realized = self._realizer.realize(discourse)
        except (TypeError, ValueError) as exc:
            return self._finish(
                Decision.VETO,
                "SPEECH_BLOCKED",
                None,
                discourse.semantic_sha256,
                None,
                None,
                (f"INVALID_SEMANTIC_DISCOURSE:{type(exc).__name__}",),
            )
        if realized.status != "SPEECH_READY" or realized.speech is None:
            return self._finish(
                Decision.RETRY,
                "SPEECH_WITHHELD",
                None,
                discourse.semantic_sha256,
                None,
                None,
                ("EXACT_RECOMPREHENSION_NOT_REACHED",),
            )
        try:
            observed = self._recomprehender.parse(realized.speech)
            equivalence = self._normalizer.compare(discourse, observed)
        except (TypeError, ValueError) as exc:
            return self._finish(
                Decision.VETO,
                "SPEECH_BLOCKED",
                None,
                discourse.semantic_sha256,
                None,
                None,
                (f"RECOMPREHENSION_FAILURE:{type(exc).__name__}",),
            )
        decision = {
            "PASS": Decision.PASS,
            "RETRY": Decision.RETRY,
            "VETO": Decision.VETO,
        }[equivalence.decision]
        reasons = (
            ("EXACT_SEMANTIC_SPEECH_READY",)
            if decision is Decision.PASS
            else ("SEMANTIC_EQUIVALENCE_BLOCK", *equivalence.vetoes)
        )
        return self._finish(
            decision,
            "SPEECH_READY" if decision is Decision.PASS else "SPEECH_WITHHELD",
            realized.speech if decision is Decision.PASS else None,
            discourse.semantic_sha256,
            observed.semantic_sha256,
            equivalence.decision,
            reasons,
        )

    @staticmethod
    def _finish(
        decision: Decision,
        status: str,
        speech: str | None,
        target_sha256: str | None,
        observed_sha256: str | None,
        equivalence_decision: str | None,
        reasons: tuple[str, ...],
    ) -> SemanticSpeechEvaluation:
        payload = {
            "component": COMPONENT_ID,
            "version": VERSION,
            "decision": decision.value,
            "status": status,
            "speech_sha256": None if speech is None else sha256(speech.encode("utf-8")).hexdigest(),
            "target_sha256": target_sha256,
            "observed_sha256": observed_sha256,
            "equivalence_decision": equivalence_decision,
            "reasons": list(reasons),
            "promotion": "FORBIDDEN",
            "source_head": SOURCE_HEAD,
        }
        return SemanticSpeechEvaluation(
            decision=decision,
            status=status,
            speech=speech,
            target_sha256=target_sha256,
            observed_sha256=observed_sha256,
            equivalence_decision=equivalence_decision,
            reasons=reasons,
            promotion="FORBIDDEN",
            source_head=SOURCE_HEAD,
            receipt_sha256=_digest(payload),
        )
