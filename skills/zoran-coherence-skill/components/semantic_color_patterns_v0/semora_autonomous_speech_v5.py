from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from typing import Callable, Protocol, Sequence

from components.semantic_color_patterns_v0.discourse_realizer_v1 import (
    DiscourseRealizationResult,
    SemanticDiscourse,
)


TEACHER_SCHEMA = "zoran.semora-speech-teacher.v5"
MEMORY_SCHEMA = "zoran.semora-speech-memory.v5"
CAMPAIGN_SCHEMA = "zoran.semora-autonomous-speech-campaign.v5"
_SHA256 = re.compile(r"[0-9a-f]{64}")
_CASE_TOKEN = re.compile(r"\b[A-Z]{2,8}-[0-9]{1,6}\b")


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _digest(value: object) -> str:
    return sha256(_canonical_bytes(value)).hexdigest()


def _failure_class(value: str) -> str:
    normalized = " ".join(str(value).casefold().replace("_", " ").split())
    if normalized.startswith("unit:") or "unit" in normalized:
        return "MISSING_UNIT"
    if normalized.startswith("reference:") or "reference" in normalized:
        return "REFERENCE_DRIFT"
    if normalized.startswith("temporal:") or "temporal" in normalized or "order" in normalized:
        return "TEMPORAL_DRIFT"
    if "polarity" in normalized or "negation" in normalized:
        return "POLARITY_DRIFT"
    if "modality" in normalized:
        return "MODALITY_DRIFT"
    if "naturalness" in normalized:
        return "NATURALNESS"
    if "speech surface" in normalized:
        return "SURFACE_DEFECT"
    if normalized.startswith("proposition:") or "proposition" in normalized:
        return "PROPOSITION_DRIFT"
    return "SEMANTIC_DRIFT"


def failure_classes(result: DiscourseRealizationResult) -> tuple[str, ...]:
    if result.status == "SPEECH_READY":
        return ()
    if not result.attempts:
        return ("PROVIDER_FAILURE",)
    classes = {_failure_class(item) for item in result.attempts[-1].differing_fields}
    return tuple(sorted(classes or {"SEMANTIC_DRIFT"}))


@dataclass(frozen=True)
class SpeechRepairRuleV5:
    triggers: tuple[str, ...]
    instruction: str
    teacher_id: str
    evidence_sha256: str
    rule_sha256: str = ""
    status: str = "EXPERIMENTAL_QUARANTINED"
    promotion: str = "FORBIDDEN"

    def __post_init__(self) -> None:
        triggers = tuple(sorted(set(self.triggers)))
        if not triggers or any(not re.fullmatch(r"[A-Z][A-Z0-9_]{2,63}", item) for item in triggers):
            raise ValueError("repair rule triggers are invalid")
        instruction = " ".join(self.instruction.split())
        if not 12 <= len(instruction) <= 600:
            raise ValueError("repair instruction is outside the bounded contract")
        if _CASE_TOKEN.search(instruction) or _SHA256.search(instruction.casefold()):
            raise ValueError("repair rule must be general, not case-addressed")
        if not self.teacher_id.strip() or not _SHA256.fullmatch(self.evidence_sha256):
            raise ValueError("teacher identity and evidence digest are required")
        if self.status != "EXPERIMENTAL_QUARANTINED" or self.promotion != "FORBIDDEN":
            raise ValueError("teacher rules must remain quarantined")
        payload = {
            "triggers": list(triggers),
            "instruction": instruction,
            "teacher_id": self.teacher_id.strip(),
            "evidence_sha256": self.evidence_sha256,
            "status": self.status,
            "promotion": self.promotion,
        }
        expected = _digest(payload)
        if self.rule_sha256 and self.rule_sha256 != expected:
            raise ValueError("repair rule digest mismatch")
        object.__setattr__(self, "triggers", triggers)
        object.__setattr__(self, "instruction", instruction)
        object.__setattr__(self, "teacher_id", self.teacher_id.strip())
        object.__setattr__(self, "rule_sha256", expected)

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def teacher_prompt(failures: Sequence[str]) -> str:
    classes = tuple(sorted(set(failures)))
    if not classes:
        raise ValueError("teacher requires at least one observed failure class")
    return json.dumps({
        "role": "SPEECH_REPAIR_TEACHER",
        "schema": TEACHER_SCHEMA,
        "observed_failure_classes": list(classes),
        "constraints": [
            "teach one reusable rule, never one case answer",
            "preserve actors, relations, polarity, modality, order, references and units",
            "return pure JSON with exactly schema, teacher_id, triggers and instruction",
            "the lesson remains experimental and cannot authorize speech or promotion",
        ],
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def parse_teacher_rule(raw: str, *, expected_failures: Sequence[str]) -> SpeechRepairRuleV5:
    if not isinstance(raw, str) or not raw.strip() or len(raw) > 20_000:
        raise ValueError("teacher response is missing or oversized")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("teacher response must be pure JSON") from exc
    expected_keys = {"schema", "teacher_id", "triggers", "instruction"}
    if not isinstance(payload, dict) or set(payload) != expected_keys:
        raise ValueError("teacher response does not match the closed contract")
    if payload["schema"] != TEACHER_SCHEMA:
        raise ValueError("teacher schema mismatch")
    triggers = payload["triggers"]
    if not isinstance(triggers, list) or any(not isinstance(item, str) for item in triggers):
        raise ValueError("teacher triggers must be text")
    allowed = set(expected_failures)
    if (
        not allowed
        or set(triggers) != allowed
        or len(triggers) != len(set(triggers))
    ):
        raise ValueError("teacher changed the observed failure scope")
    teacher_id = payload["teacher_id"]
    instruction = payload["instruction"]
    if not isinstance(teacher_id, str) or not isinstance(instruction, str):
        raise ValueError("teacher identity and instruction must be text")
    return SpeechRepairRuleV5(
        triggers=tuple(triggers),
        instruction=instruction,
        teacher_id=teacher_id,
        evidence_sha256=sha256(raw.encode("utf-8")).hexdigest(),
    )


@dataclass(frozen=True)
class VerifiedSpeechRouteV5:
    target_sha256: str
    speech: str
    speech_sha256: str = ""

    def __post_init__(self) -> None:
        if not _SHA256.fullmatch(self.target_sha256):
            raise ValueError("route target digest is invalid")
        speech = " ".join(self.speech.split())
        if not speech:
            raise ValueError("verified speech route is empty")
        expected = sha256(speech.encode("utf-8")).hexdigest()
        if self.speech_sha256 and self.speech_sha256 != expected:
            raise ValueError("speech route digest mismatch")
        object.__setattr__(self, "speech", speech)
        object.__setattr__(self, "speech_sha256", expected)


class SpeechLearningMemoryV5:
    def __init__(self) -> None:
        self._rules: dict[str, SpeechRepairRuleV5] = {}
        self._routes: dict[str, VerifiedSpeechRouteV5] = {}

    @property
    def rules(self) -> tuple[SpeechRepairRuleV5, ...]:
        return tuple(self._rules[key] for key in sorted(self._rules))

    @property
    def routes(self) -> tuple[VerifiedSpeechRouteV5, ...]:
        return tuple(self._routes[key] for key in sorted(self._routes))

    def add_rule(self, rule: SpeechRepairRuleV5) -> bool:
        if not isinstance(rule, SpeechRepairRuleV5):
            raise ValueError("speech repair rule required")
        previous = self._rules.get(rule.rule_sha256)
        if previous is not None and previous != rule:
            raise ValueError("repair rule digest collision")
        self._rules[rule.rule_sha256] = rule
        return previous is None

    def record_verified_route(self, target: SemanticDiscourse, speech: str) -> bool:
        route = VerifiedSpeechRouteV5(target.semantic_sha256, speech)
        previous = self._routes.get(route.target_sha256)
        if previous is not None and previous != route:
            raise ValueError("a verified route cannot be silently rewritten")
        self._routes[route.target_sha256] = route
        return previous is None

    def snapshot(self) -> dict[str, object]:
        core = {
            "schema": MEMORY_SCHEMA,
            "rules": [item.as_dict() for item in self.rules],
            "routes": [asdict(item) for item in self.routes],
            "promotion": "FORBIDDEN",
        }
        return {**core, "memory_sha256": _digest(core)}

    def save_content_addressed(self, directory: Path) -> Path:
        payload = self.snapshot()
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{payload['memory_sha256']}.json"
        encoded = _canonical_bytes(payload)
        if path.exists():
            if path.read_bytes() != encoded:
                raise ValueError("content-addressed speech memory was altered")
            return path
        with path.open("xb") as handle:
            handle.write(encoded)
        os.chmod(path, 0o600)
        return path

    @classmethod
    def load(cls, path: Path) -> "SpeechLearningMemoryV5":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or set(payload) != {
            "schema", "rules", "routes", "promotion", "memory_sha256",
        }:
            raise ValueError("speech memory snapshot schema mismatch")
        core = {key: payload[key] for key in ("schema", "rules", "routes", "promotion")}
        if payload["schema"] != MEMORY_SCHEMA or payload["promotion"] != "FORBIDDEN":
            raise ValueError("speech memory authority changed")
        if payload["memory_sha256"] != _digest(core) or path.stem != payload["memory_sha256"]:
            raise ValueError("speech memory digest mismatch")
        memory = cls()
        for item in payload["rules"]:
            canonical_rule = dict(item)
            canonical_rule["triggers"] = tuple(canonical_rule["triggers"])
            memory.add_rule(SpeechRepairRuleV5(**canonical_rule))
        for item in payload["routes"]:
            route = VerifiedSpeechRouteV5(**item)
            memory._routes[route.target_sha256] = route
        if _canonical_bytes(memory.snapshot()) != _canonical_bytes(payload):
            raise ValueError("speech memory replay is not deterministic")
        return memory


class SpeechRealizerV5(Protocol):
    def realize(self, discourse: SemanticDiscourse) -> DiscourseRealizationResult: ...


@dataclass(frozen=True)
class SpeechCurriculumCaseV5:
    id: str
    discourse: SemanticDiscourse

    def __post_init__(self) -> None:
        if not self.id.strip() or not isinstance(self.discourse, SemanticDiscourse):
            raise ValueError("curriculum case identity and discourse are required")


@dataclass(frozen=True)
class SpeechLearningCaseReceiptV5:
    id: str
    status: str
    selected_cycle: int | None
    failure_classes: tuple[str, ...]


@dataclass(frozen=True)
class AutonomousSpeechCampaignReceiptV5:
    schema: str
    training_count: int
    training_ready_count: int
    holdout_count: int
    holdout_ready_count: int
    teacher_calls: int
    learned_rule_count: int
    verified_route_count: int
    false_emission_count: int
    training_coverage_10: float
    holdout_coverage_10: float | None
    maximum_learning_cycles: int
    memory_sha256: str
    status: str
    promotion: str
    cases: tuple[SpeechLearningCaseReceiptV5, ...]


class AutonomousSpeechLearnerV5:
    """Bounded corpus -> speech -> recomprehension -> teacher -> cold-reuse loop."""

    def __init__(
        self,
        *,
        realizer_factory: Callable[[tuple[SpeechRepairRuleV5, ...]], SpeechRealizerV5],
        teacher: Callable[[str], str],
        memory: SpeechLearningMemoryV5 | None = None,
        max_learning_cycles: int = 8,
    ) -> None:
        if not 1 <= max_learning_cycles <= 12:
            raise ValueError("learning cycles must remain bounded")
        self.realizer_factory = realizer_factory
        self.teacher = teacher
        self.memory = memory or SpeechLearningMemoryV5()
        self.max_learning_cycles = max_learning_cycles

    def run(
        self,
        *,
        training: Sequence[SpeechCurriculumCaseV5],
        holdout: Sequence[SpeechCurriculumCaseV5] = (),
    ) -> AutonomousSpeechCampaignReceiptV5:
        training = tuple(training)
        holdout = tuple(holdout)
        ids = [item.id for item in (*training, *holdout)]
        if not training or len(ids) != len(set(ids)):
            raise ValueError("training cases are required and all identities must be unique")

        unresolved = {item.id: item for item in training}
        receipts: dict[str, SpeechLearningCaseReceiptV5] = {}
        taught: set[tuple[str, ...]] = set()
        teacher_calls = 0

        for cycle in range(1, self.max_learning_cycles + 1):
            new_rule = False
            newly_ready = False
            realizer = self.realizer_factory(self.memory.rules)
            failures_this_cycle: dict[tuple[str, ...], list[str]] = {}
            for id_ in sorted(unresolved):
                case = unresolved[id_]
                result = realizer.realize(case.discourse)
                if result.status == "SPEECH_READY" and result.speech is not None:
                    self.memory.record_verified_route(case.discourse, result.speech)
                    receipts[id_] = SpeechLearningCaseReceiptV5(id_, "SPEECH_READY", cycle, ())
                    newly_ready = True
                else:
                    classes = failure_classes(result)
                    receipts[id_] = SpeechLearningCaseReceiptV5(id_, "MISSION_RESTART", None, classes)
                    failures_this_cycle.setdefault(classes, []).append(id_)
            unresolved = {id_: case for id_, case in unresolved.items() if receipts[id_].status != "SPEECH_READY"}
            if not unresolved:
                break

            for classes in sorted(failures_this_cycle):
                if classes in taught:
                    continue
                raw = self.teacher(teacher_prompt(classes))
                teacher_calls += 1
                rule = parse_teacher_rule(raw, expected_failures=classes)
                taught.add(classes)
                new_rule = self.memory.add_rule(rule) or new_rule
            if not new_rule and not newly_ready:
                break

        realizer = self.realizer_factory(self.memory.rules)
        for case in holdout:
            result = realizer.realize(case.discourse)
            if result.status == "SPEECH_READY" and result.speech is not None:
                self.memory.record_verified_route(case.discourse, result.speech)
                receipts[case.id] = SpeechLearningCaseReceiptV5(case.id, "SPEECH_READY", 0, ())
            else:
                receipts[case.id] = SpeechLearningCaseReceiptV5(
                    case.id, "MISSION_RESTART", None, failure_classes(result),
                )

        ordered = tuple(receipts[id_] for id_ in ids)
        training_ready = sum(receipts[item.id].status == "SPEECH_READY" for item in training)
        holdout_ready = sum(receipts[item.id].status == "SPEECH_READY" for item in holdout)
        training_coverage = 10.0 * training_ready / len(training)
        holdout_coverage = None if not holdout else 10.0 * holdout_ready / len(holdout)
        complete = training_ready == len(training) and holdout_ready == len(holdout)
        snapshot = self.memory.snapshot()
        return AutonomousSpeechCampaignReceiptV5(
            schema=CAMPAIGN_SCHEMA,
            training_count=len(training),
            training_ready_count=training_ready,
            holdout_count=len(holdout),
            holdout_ready_count=holdout_ready,
            teacher_calls=teacher_calls,
            learned_rule_count=len(self.memory.rules),
            verified_route_count=len(self.memory.routes),
            false_emission_count=0,
            training_coverage_10=training_coverage,
            holdout_coverage_10=holdout_coverage,
            maximum_learning_cycles=self.max_learning_cycles,
            memory_sha256=str(snapshot["memory_sha256"]),
            status="EXPERIMENTAL_CAMPAIGN_COMPLETE" if complete else "MISSION_RESTART",
            promotion="FORBIDDEN",
            cases=ordered,
        )
