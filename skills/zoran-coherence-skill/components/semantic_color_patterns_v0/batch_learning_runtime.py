from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from hashlib import sha256
import json
from pathlib import Path
from threading import Lock
import time
from typing import Callable, Iterable, Mapping, Sequence

from components.semantic_color_patterns_v0.bounded_acquisition_gate import (
    ExperimentalLexicon,
    evaluate_bounded_acquisition,
)
from components.semantic_color_patterns_v0.definition_bootstrap import infer_definition_frames
from components.semantic_color_patterns_v0.french_surface_normalizer import (
    SurfaceToken,
    normalize_french_surface,
)
from components.semantic_color_patterns_v0.gma4_google_transport import call_gma4_teacher
from components.semantic_color_patterns_v0.gma4_teacher_adapter import (
    GMA4TeacherAdapter,
    TeacherReceipt,
    TeacherRequest,
)
from components.semantic_color_patterns_v0.quarantine_watcher import (
    QuarantineVerdict,
    QuarantineWatcher,
    SemanticObservation,
)
from components.semantic_color_patterns_v0.prototype_parser_v1 import known_surface_seed
from components.semantic_color_patterns_v0.semantic_candidate_identity import (
    SemanticCandidateIdentity,
    candidate_identity,
)
from components.semantic_color_patterns_v0.wiktionary_client import (
    fetch_french_wiktionary_entry,
)
from components.semantic_color_patterns_v0.wiktionary_cache import (
    WiktionaryDiskCache,
)
from components.semantic_color_patterns_v0.wiktionary_parser import (
    WiktionaryEntry,
)
from components.true_learning_v1.generic_symbolic_synthesizer import (
    synthesize_generic_categorical_rule,
)
from components.true_learning_v1.learning_loop import (
    ExperienceMemory,
    LanguageExperience,
    run_learning_cycle,
)
from components.true_learning_v1.synthesizer import Example


CORPUS_SCHEMA = "zoran.semantic-learning-frozen-corpus.v1"
EXPERIMENT_SCHEMA = "zoran.semantic-learning-batch-experiment.v1"
PASSAGE_SCHEMA = "zoran.semantic-learning-batch-passage.v1"
STATE_SCHEMA_V1 = "zoran.semantic-learning-batch-state.v1"
STATE_SCHEMA = "zoran.semantic-learning-batch-state.v2"
STATE_STATUS = "EXPERIMENTAL_QUARANTINE"
STATE_MAX_BYTES = 20_000_000


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


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _norm(value: str) -> str:
    return value.casefold().replace("’", "'").strip()


def _safe_error_label(error: Exception) -> str:
    value = str(error)
    if (
        1 <= len(value) <= 80
        and value.startswith(("GMA4_", "WIKTIONARY_", "TEACHER_"))
        and all(character.isupper() or character.isdigit() or character == "_" for character in value)
    ):
        return value
    return type(error).__name__


def oracle_key(surface: str, route_signature: str) -> str:
    return f"{_norm(surface)}\u001f{route_signature}"


@dataclass(frozen=True)
class FrozenCorpus:
    corpus_id: str
    source_uri: str
    source_sha256: str
    paragraphs: tuple[str, ...]
    semantic_oracle: Mapping[str, str] = field(default_factory=dict)
    schema: str = CORPUS_SCHEMA
    corpus_sha256: str = ""

    def __post_init__(self) -> None:
        if self.schema != CORPUS_SCHEMA:
            raise ValueError("frozen corpus schema mismatch")
        if not self.corpus_id or not self.source_uri:
            raise ValueError("frozen corpus identity required")
        if len(self.source_sha256) != 64:
            raise ValueError("frozen source sha256 required")
        if not self.paragraphs or any(not item.strip() for item in self.paragraphs):
            raise ValueError("frozen corpus paragraphs required")
        payload = {
            "schema": self.schema,
            "corpus_id": self.corpus_id,
            "source_uri": self.source_uri,
            "source_sha256": self.source_sha256,
            "paragraphs": list(self.paragraphs),
            "semantic_oracle": dict(sorted(self.semantic_oracle.items())),
        }
        expected = _digest(payload)
        if self.corpus_sha256 and self.corpus_sha256 != expected:
            raise ValueError("frozen corpus sha256 mismatch")
        object.__setattr__(self, "corpus_sha256", expected)

    def to_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "corpus_id": self.corpus_id,
            "source_uri": self.source_uri,
            "source_sha256": self.source_sha256,
            "paragraph_count": len(self.paragraphs),
            "paragraphs": list(self.paragraphs),
            "semantic_oracle": dict(sorted(self.semantic_oracle.items())),
            "corpus_sha256": self.corpus_sha256,
        }


def load_frozen_corpus(path: str | Path) -> FrozenCorpus:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    required = {
        "schema",
        "corpus_id",
        "source_uri",
        "source_sha256",
        "paragraph_count",
        "paragraphs",
        "semantic_oracle",
        "corpus_sha256",
    }
    if not isinstance(payload, dict) or set(payload) != required:
        raise ValueError("frozen corpus payload schema mismatch")
    paragraphs = payload["paragraphs"]
    oracle = payload["semantic_oracle"]
    if not isinstance(paragraphs, list) or not all(isinstance(x, str) for x in paragraphs):
        raise ValueError("invalid frozen paragraphs")
    if payload["paragraph_count"] != len(paragraphs):
        raise ValueError("frozen paragraph count mismatch")
    if not isinstance(oracle, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in oracle.items()
    ):
        raise ValueError("invalid frozen semantic oracle")
    return FrozenCorpus(
        schema=payload["schema"],
        corpus_id=payload["corpus_id"],
        source_uri=payload["source_uri"],
        source_sha256=payload["source_sha256"],
        paragraphs=tuple(paragraphs),
        semantic_oracle=oracle,
        corpus_sha256=payload["corpus_sha256"],
    )


@dataclass(frozen=True)
class _Occurrence:
    surface: str
    route_signature: str
    paragraph_index: int
    paragraph: str


@dataclass(frozen=True)
class _AcquiredRoute:
    surface: str
    route_signature: str
    candidate: SemanticCandidateIdentity
    hypothesis: str


@dataclass(frozen=True)
class _BlockedRoute:
    surface: str
    route_signature: str
    observed_hypothesis: str
    expected_hypothesis: str
    reason: str
    evidence_sha256: str


def _surface_schema(token: SurfaceToken) -> str:
    origin = _norm(token.origin)
    if "-" not in origin:
        return token.normalized
    parts = [item for item in origin.split("-") if item]
    return parts[0] + "".join("-CLITIC" for _ in parts[1:])


def _learning_surface(token: SurfaceToken) -> str:
    origin = _norm(token.origin)
    return origin if "-" in origin else token.normalized


def _right_schema(tokens: Sequence[SurfaceToken], index: int) -> str:
    origin = tokens[index].origin
    cursor = index + 1
    while cursor < len(tokens) and tokens[cursor].origin == origin:
        cursor += 1
    while cursor < len(tokens) and tokens[cursor].kind == "PUNCT":
        cursor += 1
    if cursor >= len(tokens):
        return "END"
    first = tokens[cursor]
    if first.kind == "CLITIC" and first.normalized == "d":
        following = cursor + 1
        if following < len(tokens) and tokens[following].kind == "CORE":
            return "de+CORE"
    if first.kind == "CORE" and first.normalized == "de":
        following = cursor + 1
        if following < len(tokens) and tokens[following].kind == "CORE":
            return "de+CORE"
    if first.kind == "CORE" and first.normalized in {
        "à", "a", "pour", "par", "avec", "sans", "sur", "dans", "en", "que", "qui",
    }:
        return f"{first.normalized}+CORE"
    return first.kind


def _occurrences(paragraphs: Sequence[str]) -> tuple[_Occurrence, ...]:
    out: list[_Occurrence] = []
    for paragraph_index, paragraph in enumerate(paragraphs):
        tokens = normalize_french_surface(paragraph)
        for index, token in enumerate(tokens):
            if token.kind != "CORE":
                continue
            surface = _learning_surface(token)
            signature = f"{_surface_schema(token)}|{_right_schema(tokens, index)}"
            out.append(_Occurrence(surface, signature, paragraph_index, paragraph))
    return tuple(out)


def route_signature_for_text(surface: str, text: str) -> str:
    target = _norm(surface)
    for item in _occurrences((text,)):
        if item.surface == target:
            return item.route_signature
    raise ValueError("surface absent from text")


def _candidate_identities(
    receipt: TeacherReceipt,
    route_signature: str,
) -> tuple[SemanticCandidateIdentity, ...]:
    proposal = receipt.proposal
    identities: dict[str, SemanticCandidateIdentity] = {}
    combinations = (
        len(proposal.lemma_candidates)
        * len(proposal.pos_candidates)
        * len(proposal.semantic_frame_candidates)
    )
    if combinations > 128:
        raise ValueError("teacher candidate product exceeds bound")
    for lemma in proposal.lemma_candidates:
        for pos in proposal.pos_candidates:
            for frame in proposal.semantic_frame_candidates:
                construction = f"{_norm(lemma)}|{route_signature}"
                item = candidate_identity(
                    language=proposal.language,
                    surface=proposal.surface,
                    lemma=lemma,
                    pos=pos,
                    semantic_frame=frame,
                    construction=construction,
                )
                identities[item.object_key] = item
    return tuple(identities[key] for key in sorted(identities))


def _context_hash(text: str) -> str:
    return sha256(" ".join(_norm(text).split()).encode("utf-8")).hexdigest()[:20]


def _wiktionary_lemma_query(lemma: str) -> str:
    """Bound a teacher lemma to its lexical Wiktionary head.

    French pronominal markers and a final construction preposition are removed
    only for source lookup. Candidate identity keeps the complete teacher lemma.
    """
    words = _norm(lemma).split()
    if words and words[0] in {"se", "s'"}:
        words = words[1:]
    if words and words[-1] in {"de", "à", "a"}:
        words = words[:-1]
    if len(words) != 1 or not words[0]:
        raise ValueError("lemma cannot be bounded to one lexical head")
    return words[0]


def _wiktionary_supports_candidate(
    entry: WiktionaryEntry,
    candidate: SemanticCandidateIdentity,
) -> bool:
    for sense in entry.senses:
        if sense.pos != candidate.canonical_payload["pos"]:
            continue
        inferred = infer_definition_frames(entry.surface, (sense.definition,))
        if inferred.candidates == (candidate.semantic_frame,):
            return True
    return False


def _semantic_learning_object(
    object_key: str,
    watcher: QuarantineVerdict,
    *,
    replay_count: int,
):
    gate = "PASS" if (
        watcher.state == "CANDIDATE_STABLE"
        and watcher.consensus >= 0.80
        and watcher.contradictions == 0
    ) else "FAIL"
    train = (
        Example("T1", {"semantic_match": True, "gate": gate}, "REUSE"),
        Example("T2", {"semantic_match": True, "gate": gate, "variant": "B"}, "REUSE"),
        Example("T3", {"semantic_match": False, "gate": "PASS"}, "REJECT"),
        Example("T4", {"semantic_match": True, "gate": "FAIL"}, "REJECT"),
    )
    validation = (
        Example("V1", {"semantic_match": True, "gate": gate, "variant": "V"}, "REUSE"),
        Example("V2", {"semantic_match": False, "gate": "PASS", "variant": "V"}, "REJECT"),
    )
    holdout = (
        Example("H1", {"semantic_match": True, "gate": gate, "variant": "H"}, "REUSE"),
        Example("H2", {"semantic_match": True, "gate": "FAIL", "variant": "H"}, "REJECT"),
    )
    experience = LanguageExperience(
        experience_id="SEM-" + sha256(
            f"{object_key}:{watcher.trace_sha256}".encode("utf-8"),
        ).hexdigest()[:24],
        family=object_key,
        train=train,
        validation=validation,
        holdout=holdout,
        source="SEMANTIC_WATCHER_BOUNDED_GATE",
    )

    def synthesizer(train_items, validation_items, holdout_items):
        return synthesize_generic_categorical_rule(
            train_items,
            validation_items,
            holdout_items,
            family=object_key,
            max_rules=2,
        )

    return run_learning_cycle(
        ExperienceMemory(),
        experience,
        synthesizer,
        replay_count=replay_count,
    )


def _candidate_payload(candidate: SemanticCandidateIdentity) -> dict[str, object]:
    return {
        **candidate.canonical_payload,
        "object_key": candidate.object_key,
    }


def _candidate_from_payload(payload: object) -> SemanticCandidateIdentity:
    required = {
        "language", "surface", "lemma", "pos", "semantic_frame",
        "construction", "object_key",
    }
    if not isinstance(payload, dict) or set(payload) != required:
        raise ValueError("persisted candidate schema mismatch")
    construction = payload["construction"]
    if construction is not None and not isinstance(construction, str):
        raise ValueError("persisted candidate construction invalid")
    values = {
        key: payload[key]
        for key in ("language", "surface", "lemma", "pos", "semantic_frame")
    }
    if not all(isinstance(value, str) for value in values.values()):
        raise ValueError("persisted candidate value invalid")
    candidate = candidate_identity(
        language=values["language"],
        surface=values["surface"],
        lemma=values["lemma"],
        pos=values["pos"],
        semantic_frame=values["semantic_frame"],
        construction=construction,
    )
    if candidate.object_key != payload["object_key"]:
        raise ValueError("persisted candidate identity mismatch")
    if _candidate_payload(candidate) != payload:
        raise ValueError("persisted candidate is not canonical")
    return candidate


def _observation_payload(observation: SemanticObservation) -> dict[str, object]:
    return {
        "observation_id": observation.observation_id,
        "object_key": observation.object_key,
        "source_id": observation.source_id,
        "context_signature": list(observation.context_signature),
        "hypothesis": observation.hypothesis,
        "provenance": observation.provenance,
    }


def _observation_from_payload(payload: object) -> SemanticObservation:
    required = {
        "observation_id", "object_key", "source_id", "context_signature",
        "hypothesis", "provenance",
    }
    if not isinstance(payload, dict) or set(payload) != required:
        raise ValueError("persisted observation schema mismatch")
    strings = (
        payload["observation_id"], payload["object_key"],
        payload["source_id"], payload["provenance"],
    )
    if not all(isinstance(value, str) and value for value in strings):
        raise ValueError("persisted observation identity invalid")
    context = payload["context_signature"]
    if not isinstance(context, list) or not context or not all(
        isinstance(value, str) and value for value in context
    ):
        raise ValueError("persisted observation context invalid")
    hypothesis = payload["hypothesis"]
    if hypothesis is not None and not isinstance(hypothesis, str):
        raise ValueError("persisted observation hypothesis invalid")
    return SemanticObservation(
        observation_id=payload["observation_id"],
        object_key=payload["object_key"],
        source_id=payload["source_id"],
        context_signature=tuple(context),
        hypothesis=hypothesis,
        provenance=payload["provenance"],
    )


@dataclass(frozen=True)
class BatchPassageMetrics:
    paragraphs: int
    characters: int
    core_surfaces: int
    unique_surfaces: int
    known_hits: int
    seed_known_occurrences: int
    recalled_route_groups: int
    recalled_route_occurrences: int
    blocked_route_groups: int
    blocked_route_occurrences: int
    prior_candidate_groups: int
    new_to_state_groups: int
    unknown_surfaces_unique: int
    unknown_groups: int
    gma4_requests: int
    gma4_calls: int
    gma4_contract_retries: int
    wiktionary_requests: int
    wiktionary_calls: int
    wiktionary_cache_hits: int
    wiktionary_cache_misses: int
    gma4_failures: int
    wiktionary_failures: int
    invalid_teacher_json: int
    ambiguity_signals: int
    contradictions: int
    candidate_stable: int
    experimentally_acquired: int
    observed_false_acquisitions: int
    oracle_false_acquisitions: int | None
    oracle_checked_acquisitions: int
    oracle_total_acquisitions: int
    D_GMA4: float
    A_autonomy: float
    coverage_after: float
    latency_seconds: float
    cost: float | None = None


@dataclass(frozen=True)
class BatchPassageResult:
    schema: str
    corpus_id: str
    corpus_sha256: str
    status: str
    metrics: BatchPassageMetrics
    candidate_keys: tuple[str, ...]
    acquired_routes: tuple[str, ...]
    errors: tuple[str, ...]
    promotion: str = "FORBIDDEN"


class BatchLearningRuntime:
    """Batch seam over the existing teacher, Wiktionary, watcher and TRUE_LEARNING.

    Acquisition is parallel. Watcher mutation and bounded admission are
    deliberately sequential and deterministic.
    """

    def __init__(
        self,
        *,
        adapter: GMA4TeacherAdapter,
        wiktionary_fetcher: Callable[[str], WiktionaryEntry],
        known_surfaces: Iterable[str] = (),
        max_workers: int = 16,
        replay_count: int = 1000,
        wiktionary_min_interval_seconds: float = 0.0,
    ) -> None:
        if max_workers < 1 or max_workers > 64:
            raise ValueError("max_workers outside bounded contract")
        if replay_count < 1:
            raise ValueError("replay_count must be positive")
        if wiktionary_min_interval_seconds < 0 or wiktionary_min_interval_seconds > 5:
            raise ValueError("Wiktionary interval outside bounded contract")
        self.adapter = adapter
        self.wiktionary_fetcher = wiktionary_fetcher
        self.known_seed = set(known_surface_seed())
        self.known_seed.update(_norm(item) for item in known_surfaces if item.strip())
        self.max_workers = max_workers
        self.replay_count = replay_count
        self.wiktionary_min_interval_seconds = wiktionary_min_interval_seconds
        self._wiktionary_lock = Lock()
        self._wiktionary_next_at = 0.0
        self.watcher = QuarantineWatcher()
        self.lexicon = ExperimentalLexicon()
        self._routes: dict[tuple[str, str], _AcquiredRoute] = {}
        self._blocked_routes: dict[tuple[str, str], _BlockedRoute] = {}
        self._candidates: dict[str, SemanticCandidateIdentity] = {}
        self._loaded_state_sha256: str | None = None
        self._state_generation = 0

    def _fetch_wiktionary(self, surface: str) -> WiktionaryEntry:
        if self.wiktionary_min_interval_seconds:
            with self._wiktionary_lock:
                now = time.monotonic()
                delay = max(0.0, self._wiktionary_next_at - now)
                self._wiktionary_next_at = max(now, self._wiktionary_next_at) + self.wiktionary_min_interval_seconds
            if delay:
                time.sleep(delay)
        return self.wiktionary_fetcher(surface)

    def _rebuild_lexicon(self) -> None:
        lexicon = ExperimentalLexicon()
        for key in sorted(self._routes):
            route = self._routes[key]
            verdict = self.watcher.evaluate(route.candidate.object_key)
            learning = _semantic_learning_object(
                route.candidate.object_key,
                verdict,
                replay_count=self.replay_count,
            )
            bounded = evaluate_bounded_acquisition(
                object_key=route.candidate.object_key,
                watcher=verdict,
                learning_object=learning,
            )
            if not bounded.experimental_reuse:
                raise ValueError("remaining route no longer passes acquisition gate")
            lexicon.admit(route.surface, bounded)
        self.lexicon = lexicon

    def block_route(
        self,
        surface: str,
        route_signature: str,
        *,
        observed_hypothesis: str,
        expected_hypothesis: str,
        reason: str,
        evidence_sha256: str,
    ) -> None:
        key = (_norm(surface), route_signature)
        if not reason or not _is_sha256(evidence_sha256):
            raise ValueError("blocked route evidence invalid")
        if not observed_hypothesis or not expected_hypothesis:
            raise ValueError("blocked route hypotheses required")
        route = self._routes.get(key)
        if route is None:
            previous = self._blocked_routes.get(key)
            proposed = _BlockedRoute(
                key[0], key[1], observed_hypothesis,
                expected_hypothesis, reason, evidence_sha256,
            )
            if previous != proposed:
                raise ValueError("route is not reusable or conflicts with prior block")
            return
        if route.hypothesis != observed_hypothesis:
            raise ValueError("blocked route observed hypothesis mismatch")
        blocked = _BlockedRoute(
            surface=key[0],
            route_signature=key[1],
            observed_hypothesis=observed_hypothesis,
            expected_hypothesis=expected_hypothesis,
            reason=reason,
            evidence_sha256=evidence_sha256,
        )
        self._blocked_routes[key] = blocked
        del self._routes[key]
        self._rebuild_lexicon()

    @property
    def loaded_state_sha256(self) -> str | None:
        return self._loaded_state_sha256

    @property
    def state_generation(self) -> int:
        return self._state_generation

    def state_payload(self, *, source_head: str) -> dict[str, object]:
        if not isinstance(source_head, str) or len(source_head) != 40 or any(
            character not in "0123456789abcdef" for character in source_head
        ):
            raise ValueError("exact 40-character source HEAD required")
        observations = [
            _observation_payload(observation)
            for object_key in sorted(self.watcher.snapshot())
            for observation in self.watcher.snapshot()[object_key]
        ]
        candidate_keys = set(self._candidates)
        if any(item["object_key"] not in candidate_keys for item in observations):
            raise ValueError("watcher contains an untracked candidate")
        routes = []
        for key in sorted(self._routes):
            route = self._routes[key]
            verdict = self.watcher.evaluate(route.candidate.object_key)
            if (
                verdict.state != "CANDIDATE_STABLE"
                or verdict.hypothesis != route.hypothesis
                or verdict.contradictions != 0
            ):
                raise ValueError("reusable route no longer passes watcher gate")
            routes.append({
                "surface": route.surface,
                "route_signature": route.route_signature,
                "object_key": route.candidate.object_key,
                "hypothesis": route.hypothesis,
                "watcher_trace_sha256": verdict.trace_sha256,
            })
        core = {
            "schema": STATE_SCHEMA,
            "status": STATE_STATUS,
            "promotion": "FORBIDDEN",
            "source_head": source_head,
            "generation": self._state_generation + 1,
            "parent_state_sha256": self._loaded_state_sha256,
            "candidates": [
                _candidate_payload(self._candidates[key])
                for key in sorted(self._candidates)
            ],
            "routes": routes,
            "blocked_routes": [
                asdict(self._blocked_routes[key])
                for key in sorted(self._blocked_routes)
            ],
            "observations": observations,
            "counts": {
                "candidates": len(self._candidates),
                "routes": len(routes),
                "blocked_routes": len(self._blocked_routes),
                "observations": len(observations),
            },
        }
        return {**core, "state_sha256": _digest(core)}

    def save_state(self, path: str | Path, *, source_head: str) -> dict[str, object]:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = self.state_payload(source_head=source_head)
        rendered = json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        ) + "\n"
        if len(rendered.encode("utf-8")) > STATE_MAX_BYTES:
            raise ValueError("experimental state exceeds bounded size")
        with target.open("x", encoding="utf-8") as handle:
            handle.write(rendered)
            handle.flush()
        self._loaded_state_sha256 = str(payload["state_sha256"])
        self._state_generation = int(payload["generation"])
        return payload

    @classmethod
    def from_state(
        cls,
        path: str | Path,
        *,
        adapter: GMA4TeacherAdapter,
        wiktionary_fetcher: Callable[[str], WiktionaryEntry],
        known_surfaces: Iterable[str] = (),
        max_workers: int = 16,
        replay_count: int = 1000,
        wiktionary_min_interval_seconds: float = 0.0,
        expected_source_head: str | None = None,
    ) -> "BatchLearningRuntime":
        source = Path(path)
        if source.stat().st_size > STATE_MAX_BYTES:
            raise ValueError("experimental state exceeds bounded size")
        payload = json.loads(source.read_text(encoding="utf-8"))
        required_v1 = {
            "schema", "status", "promotion", "source_head", "generation",
            "parent_state_sha256", "candidates", "routes", "observations",
            "counts", "state_sha256",
        }
        required_v2 = required_v1 | {"blocked_routes"}
        if not isinstance(payload, dict):
            raise ValueError("experimental state schema mismatch")
        schema = payload.get("schema")
        expected_keys = required_v1 if schema == STATE_SCHEMA_V1 else required_v2
        if set(payload) != expected_keys:
            raise ValueError("experimental state schema mismatch")
        if (
            schema not in {STATE_SCHEMA_V1, STATE_SCHEMA}
            or payload["status"] != STATE_STATUS
            or payload["promotion"] != "FORBIDDEN"
        ):
            raise ValueError("experimental state boundary mismatch")
        source_head = payload["source_head"]
        if (
            not isinstance(source_head, str)
            or len(source_head) != 40
            or any(character not in "0123456789abcdef" for character in source_head)
        ):
            raise ValueError("experimental state source HEAD invalid")
        if expected_source_head is not None and source_head != expected_source_head:
            raise ValueError("experimental state source HEAD drift")
        generation = payload["generation"]
        if not isinstance(generation, int) or isinstance(generation, bool) or generation < 1:
            raise ValueError("experimental state generation invalid")
        parent = payload["parent_state_sha256"]
        if parent is not None and not _is_sha256(parent):
            raise ValueError("experimental state parent invalid")
        supplied_sha = payload["state_sha256"]
        core = {key: value for key, value in payload.items() if key != "state_sha256"}
        if not _is_sha256(supplied_sha) or _digest(core) != supplied_sha:
            raise ValueError("experimental state sha256 mismatch")
        candidates_raw = payload["candidates"]
        routes_raw = payload["routes"]
        blocked_raw = payload.get("blocked_routes", [])
        observations_raw = payload["observations"]
        counts = payload["counts"]
        if not isinstance(candidates_raw, list) or not isinstance(routes_raw, list) or not isinstance(blocked_raw, list) or not isinstance(observations_raw, list):
            raise ValueError("experimental state collections invalid")
        count_fields = (
            {"candidates", "routes", "observations"}
            if schema == STATE_SCHEMA_V1
            else {"candidates", "routes", "blocked_routes", "observations"}
        )
        if not isinstance(counts, dict) or set(counts) != count_fields:
            raise ValueError("experimental state counts invalid")
        expected_counts = {
            "candidates": len(candidates_raw),
            "routes": len(routes_raw),
            "observations": len(observations_raw),
        }
        if schema == STATE_SCHEMA:
            expected_counts["blocked_routes"] = len(blocked_raw)
        if counts != expected_counts:
            raise ValueError("experimental state counts mismatch")

        runtime = cls(
            adapter=adapter,
            wiktionary_fetcher=wiktionary_fetcher,
            known_surfaces=known_surfaces,
            max_workers=max_workers,
            replay_count=replay_count,
            wiktionary_min_interval_seconds=wiktionary_min_interval_seconds,
        )
        for raw_candidate in candidates_raw:
            candidate = _candidate_from_payload(raw_candidate)
            if candidate.object_key in runtime._candidates:
                raise ValueError("duplicate persisted candidate")
            runtime._candidates[candidate.object_key] = candidate
        for raw_observation in observations_raw:
            observation = _observation_from_payload(raw_observation)
            if observation.object_key not in runtime._candidates:
                raise ValueError("persisted observation candidate missing")
            runtime.watcher.observe(observation)
        route_fields = {
            "surface", "route_signature", "object_key", "hypothesis",
            "watcher_trace_sha256",
        }
        for raw_route in routes_raw:
            if not isinstance(raw_route, dict) or set(raw_route) != route_fields:
                raise ValueError("persisted route schema mismatch")
            if not all(
                isinstance(raw_route[field], str) and raw_route[field]
                for field in route_fields
            ):
                raise ValueError("persisted route value invalid")
            candidate = runtime._candidates.get(raw_route["object_key"])
            if candidate is None:
                raise ValueError("persisted route candidate missing")
            surface = _norm(raw_route["surface"])
            signature = raw_route["route_signature"]
            if (
                candidate.canonical_payload["surface"] != surface
                or candidate.semantic_frame != raw_route["hypothesis"]
                or candidate.canonical_payload["construction"]
                != _norm(f"{candidate.canonical_payload['lemma']}|{signature}")
            ):
                raise ValueError("persisted route identity mismatch")
            key = (surface, signature)
            if key in runtime._routes:
                raise ValueError("duplicate persisted route")
            watcher_verdict = runtime.watcher.evaluate(candidate.object_key)
            if (
                watcher_verdict.state != "CANDIDATE_STABLE"
                or watcher_verdict.hypothesis != candidate.semantic_frame
                or watcher_verdict.contradictions != 0
                or watcher_verdict.trace_sha256 != raw_route["watcher_trace_sha256"]
            ):
                raise ValueError("persisted route watcher gate mismatch")
            learning = _semantic_learning_object(
                candidate.object_key,
                watcher_verdict,
                replay_count=replay_count,
            )
            bounded = evaluate_bounded_acquisition(
                object_key=candidate.object_key,
                watcher=watcher_verdict,
                learning_object=learning,
            )
            if not bounded.experimental_reuse:
                raise ValueError("persisted route no longer passes acquisition gate")
            runtime.lexicon.admit(surface, bounded)
            runtime._routes[key] = _AcquiredRoute(
                surface=surface,
                route_signature=signature,
                candidate=candidate,
                hypothesis=candidate.semantic_frame,
            )
        blocked_fields = {
            "surface", "route_signature", "observed_hypothesis",
            "expected_hypothesis", "reason", "evidence_sha256",
        }
        for raw_blocked in blocked_raw:
            if not isinstance(raw_blocked, dict) or set(raw_blocked) != blocked_fields:
                raise ValueError("persisted blocked route schema mismatch")
            if not all(isinstance(raw_blocked[field], str) and raw_blocked[field] for field in blocked_fields):
                raise ValueError("persisted blocked route value invalid")
            if not _is_sha256(raw_blocked["evidence_sha256"]):
                raise ValueError("persisted blocked route evidence invalid")
            key = (_norm(raw_blocked["surface"]), raw_blocked["route_signature"])
            if key in runtime._routes or key in runtime._blocked_routes:
                raise ValueError("persisted blocked route collision")
            runtime._blocked_routes[key] = _BlockedRoute(
                surface=key[0],
                route_signature=key[1],
                observed_hypothesis=raw_blocked["observed_hypothesis"],
                expected_hypothesis=raw_blocked["expected_hypothesis"],
                reason=raw_blocked["reason"],
                evidence_sha256=raw_blocked["evidence_sha256"],
            )
        runtime._loaded_state_sha256 = supplied_sha
        runtime._state_generation = generation
        return runtime

    def _observe_corpus(
        self,
        corpus: FrozenCorpus,
        occurrence: _Occurrence,
        candidate: SemanticCandidateIdentity,
    ) -> None:
        context = _context_hash(occurrence.paragraph)
        observation_id = (
            f"corpus:{corpus.corpus_sha256[:12]}:{occurrence.paragraph_index}:"
            f"{context}:{candidate.candidate_id}"
        )
        self.watcher.observe(SemanticObservation(
            observation_id=observation_id,
            object_key=candidate.object_key,
            source_id=f"CORPUS:{corpus.corpus_id}",
            context_signature=(
                "CORPUS_CONSTRUCTION_RECURRENCE",
                corpus.corpus_id,
                context,
                occurrence.route_signature,
            ),
            hypothesis=candidate.semantic_frame,
            provenance=(
                "BOUNDED_CONSTRUCTION_RECURRENCE:"
                f"{corpus.source_uri}#{occurrence.paragraph_index}"
            ),
        ))

    def _observe_teacher(
        self,
        receipt: TeacherReceipt,
        request: TeacherRequest,
        candidate: SemanticCandidateIdentity,
    ) -> None:
        context = _context_hash(request.context)
        self.watcher.observe(SemanticObservation(
            observation_id=(
                f"gma4:{receipt.response_sha256[:16]}:{context}:"
                f"{candidate.candidate_id}"
            ),
            object_key=candidate.object_key,
            source_id=f"GMA4:{receipt.model}",
            context_signature=(
                "GMA4_TEACHING",
                receipt.proposal.language,
                context,
                candidate.canonical_payload["construction"] or "",
            ),
            hypothesis=candidate.semantic_frame,
            provenance=f"GMA4_TEACHER:{receipt.response_sha256}",
        ))

    def _observe_wiktionary(
        self,
        entry: WiktionaryEntry,
        candidate: SemanticCandidateIdentity,
    ) -> int:
        added = 0
        source_id = (
            f"WIKTIONARY:{entry.revision_id}"
            if entry.revision_id is not None
            else f"WIKTIONARY:{entry.source_uri}"
        )
        for index, sense in enumerate(entry.senses):
            if sense.pos != candidate.canonical_payload["pos"]:
                continue
            inferred = infer_definition_frames(entry.surface, (sense.definition,))
            if inferred.candidates != (candidate.semantic_frame,):
                continue
            self.watcher.observe(SemanticObservation(
                observation_id=(
                    f"wikt:{entry.revision_id or 'na'}:{index}:"
                    f"{candidate.candidate_id}"
                ),
                object_key=candidate.object_key,
                source_id=source_id,
                context_signature=(
                    "WIKTIONARY_DEFINITION",
                    entry.language,
                    sense.pos,
                    candidate.semantic_frame,
                    *inferred.matched_primitives.get(candidate.semantic_frame, ()),
                ),
                hypothesis=candidate.semantic_frame,
                provenance=f"WIKTIONARY:{entry.source_uri}",
            ))
            added += 1
        return added

    def process(self, corpus: FrozenCorpus) -> BatchPassageResult:
        started = time.perf_counter()
        cache_hits_before = int(getattr(self.wiktionary_fetcher, "cache_hits", 0))
        cache_misses_before = int(getattr(self.wiktionary_fetcher, "cache_misses", 0))
        occurrences = _occurrences(corpus.paragraphs)
        groups: dict[tuple[str, str], list[_Occurrence]] = {}
        for occurrence in occurrences:
            groups.setdefault(
                (occurrence.surface, occurrence.route_signature),
                [],
            ).append(occurrence)

        known_hits = 0
        unknown_groups: list[tuple[str, str]] = []
        recalled_route_groups = 0
        recalled_route_occurrences = 0
        blocked_route_groups = 0
        blocked_route_occurrences = 0
        for key in sorted(groups):
            if key in self._routes:
                recalled_route_groups += 1
                recalled_route_occurrences += len(groups[key])
                known_hits += len(groups[key])
            elif key in self._blocked_routes:
                blocked_route_groups += 1
                blocked_route_occurrences += len(groups[key])
            elif key[0] in self.known_seed:
                known_hits += len(groups[key])
            else:
                unknown_groups.append(key)
        prior_candidate_groups = sum(
            1
            for surface, signature in unknown_groups
            if any(
                candidate.canonical_payload["surface"] == surface
                and candidate.canonical_payload["construction"] is not None
                and candidate.canonical_payload["construction"].endswith(
                    "|" + _norm(signature)
                )
                for candidate in self._candidates.values()
            )
        )

        errors: list[str] = []
        invalid_teacher_json = 0
        gma4_failures = 0
        wiktionary_failures = 0
        ambiguity_signals = 0
        teacher_results: dict[tuple[str, str], TeacherReceipt | Exception] = {}
        wiktionary_results: dict[str, WiktionaryEntry | Exception] = {}
        wiktionary_fallback_results: dict[str, WiktionaryEntry | Exception] = {}

        unique_unknown_surfaces = sorted({surface for surface, _ in unknown_groups})
        worker_count = min(
            self.max_workers,
            max(1, len(unknown_groups) + len(unique_unknown_surfaces)),
        )
        with ThreadPoolExecutor(max_workers=worker_count) as pool:
            teacher_futures = {}
            for key in unknown_groups:
                occurrence = groups[key][0]
                request = TeacherRequest(
                    surface=key[0],
                    context=occurrence.paragraph,
                    language="fr",
                    known_primitives=tuple(sorted(self.known_seed)),
                )
                teacher_futures[key] = (
                    request,
                    pool.submit(self.adapter.teach, request),
                )
            wiktionary_futures = {
                surface: pool.submit(self._fetch_wiktionary, surface)
                for surface in unique_unknown_surfaces
            }
            for key in sorted(teacher_futures):
                _, future = teacher_futures[key]
                try:
                    teacher_results[key] = future.result()
                except Exception as exc:
                    teacher_results[key] = exc
            for surface in unique_unknown_surfaces:
                try:
                    wiktionary_results[surface] = wiktionary_futures[surface].result()
                except Exception as exc:
                    wiktionary_results[surface] = exc

        # A conjugated/clitic surface may not own a Wiktionary page. Keep the
        # initial surface lookup parallel with GMA4, then batch only the bounded
        # lexical heads supplied by successful teacher proposals. No watcher
        # mutation occurs until all acquisition is complete.
        fallback_queries: set[str] = set()
        fallback_by_group: dict[tuple[str, str], set[str]] = {}
        for key in unknown_groups:
            surface_entry = wiktionary_results.get(key[0])
            teacher = teacher_results.get(key)
            if not isinstance(teacher, TeacherReceipt):
                continue
            try:
                preview_candidates = _candidate_identities(teacher, key[1])
            except ValueError:
                continue
            if isinstance(surface_entry, WiktionaryEntry) and any(
                _wiktionary_supports_candidate(surface_entry, candidate)
                for candidate in preview_candidates
            ):
                continue
            for lemma in teacher.proposal.lemma_candidates:
                try:
                    query = _wiktionary_lemma_query(lemma)
                except ValueError:
                    continue
                if query == key[0]:
                    continue
                fallback_queries.add(query)
                fallback_by_group.setdefault(key, set()).add(query)
        if fallback_queries:
            with ThreadPoolExecutor(
                max_workers=min(self.max_workers, len(fallback_queries)),
            ) as pool:
                futures = {
                    query: pool.submit(self._fetch_wiktionary, query)
                    for query in sorted(fallback_queries)
                }
                for query in sorted(futures):
                    try:
                        wiktionary_fallback_results[query] = futures[query].result()
                    except Exception as exc:
                        wiktionary_fallback_results[query] = exc

        all_candidates: dict[str, SemanticCandidateIdentity] = {}
        group_candidates: dict[tuple[str, str], list[SemanticCandidateIdentity]] = {}
        newly_acquired: list[_AcquiredRoute] = []
        oracle_checked = 0
        oracle_false = 0

        # Existing acquired routes still receive held-out corpus observations,
        # without another teacher or Wiktionary call.
        for key in sorted(groups):
            route = self._routes.get(key)
            if route is None:
                continue
            for occurrence in groups[key]:
                self._observe_corpus(corpus, occurrence, route.candidate)
            verdict = self.watcher.evaluate(route.candidate.object_key)
            if oracle_key(*key) in corpus.semantic_oracle:
                oracle_checked += 1
                if corpus.semantic_oracle[oracle_key(*key)] != route.hypothesis:
                    oracle_false += 1
            all_candidates[route.candidate.object_key] = route.candidate
            self._candidates[route.candidate.object_key] = route.candidate

        for key in unknown_groups:
            teacher = teacher_results[key]
            if isinstance(teacher, Exception):
                gma4_failures += 1
                if isinstance(teacher, ValueError):
                    invalid_teacher_json += 1
                errors.append(f"GMA4:{key[0]}:{_safe_error_label(teacher)}")
                continue
            ambiguity_signals += len(teacher.proposal.ambiguities)
            if (
                len(teacher.proposal.lemma_candidates) != 1
                or len(teacher.proposal.pos_candidates) != 1
                or len(teacher.proposal.semantic_frame_candidates) != 1
            ):
                ambiguity_signals += 1
            try:
                candidates = _candidate_identities(teacher, key[1])
            except ValueError as exc:
                invalid_teacher_json += 1
                errors.append(f"GMA4_CANDIDATES:{key[0]}:{type(exc).__name__}")
                continue
            group_candidates[key] = list(candidates)
            request = TeacherRequest(
                surface=key[0],
                context=groups[key][0].paragraph,
                language="fr",
                known_primitives=tuple(sorted(self.known_seed)),
            )
            entries: list[WiktionaryEntry] = []
            surface_entry = wiktionary_results.get(key[0])
            if isinstance(surface_entry, WiktionaryEntry):
                entries.append(surface_entry)
            for query in sorted(fallback_by_group.get(key, ())):
                fallback_entry = wiktionary_fallback_results.get(query)
                if isinstance(fallback_entry, WiktionaryEntry):
                    entries.append(fallback_entry)
            for candidate in candidates:
                all_candidates[candidate.object_key] = candidate
                self._candidates[candidate.object_key] = candidate
                self._observe_teacher(teacher, request, candidate)
                for entry in entries:
                    self._observe_wiktionary(entry, candidate)
                for occurrence in groups[key]:
                    self._observe_corpus(corpus, occurrence, candidate)

        for surface in unique_unknown_surfaces:
            result = wiktionary_results[surface]
            if isinstance(result, Exception):
                wiktionary_failures += 1
                errors.append(f"WIKTIONARY:{surface}:{_safe_error_label(result)}")
        for query in sorted(wiktionary_fallback_results):
            result = wiktionary_fallback_results[query]
            if isinstance(result, Exception):
                wiktionary_failures += 1
                errors.append(f"WIKTIONARY_LEMMA:{query}:{_safe_error_label(result)}")

        stable_keys: set[str] = set()
        contradictions = 0
        observed_false = 0
        for object_key in sorted(all_candidates):
            verdict = self.watcher.evaluate(object_key)
            contradictions += verdict.contradictions
            if verdict.state == "CANDIDATE_STABLE":
                stable_keys.add(object_key)
            if object_key in {
                route.candidate.object_key for route in self._routes.values()
            } and (
                verdict.state != "CANDIDATE_STABLE"
                or verdict.contradictions > 0
            ):
                observed_false += 1

        for key in unknown_groups:
            stable = [
                candidate
                for candidate in group_candidates.get(key, ())
                if candidate.object_key in stable_keys
            ]
            if len(stable) != 1:
                if len(stable) > 1:
                    ambiguity_signals += 1
                continue
            candidate = stable[0]
            watcher_verdict = self.watcher.evaluate(candidate.object_key)
            learning = _semantic_learning_object(
                candidate.object_key,
                watcher_verdict,
                replay_count=self.replay_count,
            )
            bounded = evaluate_bounded_acquisition(
                object_key=candidate.object_key,
                watcher=watcher_verdict,
                learning_object=learning,
            )
            if not bounded.experimental_reuse:
                errors.extend(
                    f"ACQUISITION:{key[0]}:{reason}"
                    for reason in bounded.reasons
                )
                continue
            self.lexicon.admit(key[0], bounded)
            route = _AcquiredRoute(
                surface=key[0],
                route_signature=key[1],
                candidate=candidate,
                hypothesis=candidate.semantic_frame,
            )
            self._routes[key] = route
            newly_acquired.append(route)
            oracle_value = corpus.semantic_oracle.get(oracle_key(*key))
            if oracle_value is not None:
                oracle_checked += 1
                if oracle_value != route.hypothesis:
                    oracle_false += 1

        acquired_occurrences = sum(
            len(groups[(route.surface, route.route_signature)])
            for route in newly_acquired
        )
        core_count = len(occurrences)
        gma4_calls = sum(
            result.provider_attempts
            if isinstance(result, TeacherReceipt)
            else max(1, int(getattr(result, "attempts", 1)))
            for result in teacher_results.values()
        )
        known_after = known_hits + acquired_occurrences
        wiktionary_requests = (
            len(unique_unknown_surfaces) + len(wiktionary_fallback_results)
        )
        cache_hits = max(
            0,
            int(getattr(self.wiktionary_fetcher, "cache_hits", 0))
            - cache_hits_before,
        )
        cache_misses = max(
            0,
            int(getattr(self.wiktionary_fetcher, "cache_misses", 0))
            - cache_misses_before,
        )
        wiktionary_calls = (
            cache_misses
            if isinstance(self.wiktionary_fetcher, WiktionaryDiskCache)
            else wiktionary_requests
        )
        total_oracle_targets = len(newly_acquired) + sum(
            1 for key in groups if key in self._routes and key not in unknown_groups
        )
        oracle_status_measured = (
            total_oracle_targets > 0 and oracle_checked == total_oracle_targets
        )
        metrics = BatchPassageMetrics(
            paragraphs=len(corpus.paragraphs),
            characters=sum(len(item) for item in corpus.paragraphs),
            core_surfaces=core_count,
            unique_surfaces=len({item.surface for item in occurrences}),
            known_hits=known_hits,
            seed_known_occurrences=known_hits - recalled_route_occurrences,
            recalled_route_groups=recalled_route_groups,
            recalled_route_occurrences=recalled_route_occurrences,
            blocked_route_groups=blocked_route_groups,
            blocked_route_occurrences=blocked_route_occurrences,
            prior_candidate_groups=prior_candidate_groups,
            new_to_state_groups=len(unknown_groups) - prior_candidate_groups,
            unknown_surfaces_unique=len(unique_unknown_surfaces),
            unknown_groups=len(unknown_groups),
            gma4_requests=len(unknown_groups),
            gma4_calls=gma4_calls,
            gma4_contract_retries=max(0, gma4_calls - len(unknown_groups)),
            wiktionary_requests=wiktionary_requests,
            wiktionary_calls=wiktionary_calls,
            wiktionary_cache_hits=cache_hits,
            wiktionary_cache_misses=cache_misses,
            gma4_failures=gma4_failures,
            wiktionary_failures=wiktionary_failures,
            invalid_teacher_json=invalid_teacher_json,
            ambiguity_signals=ambiguity_signals,
            contradictions=contradictions,
            candidate_stable=len(stable_keys),
            experimentally_acquired=len(newly_acquired),
            observed_false_acquisitions=observed_false,
            oracle_false_acquisitions=oracle_false if oracle_status_measured else None,
            oracle_checked_acquisitions=oracle_checked,
            oracle_total_acquisitions=total_oracle_targets,
            D_GMA4=0.0 if core_count == 0 else gma4_calls / core_count,
            A_autonomy=1.0 if core_count == 0 else known_hits / core_count,
            coverage_after=1.0 if core_count == 0 else known_after / core_count,
            latency_seconds=time.perf_counter() - started,
        )
        if gma4_failures == len(unknown_groups) and unknown_groups:
            status = "FAILED_CLOSED_GMA4_UNAVAILABLE"
        elif errors:
            status = "EXPERIMENTAL_WITH_ERRORS"
        elif blocked_route_groups:
            status = "EXPERIMENTAL_WITH_BLOCKED_ROUTES"
        else:
            status = "EXPERIMENTAL_PASSAGE_COMPLETE"
        return BatchPassageResult(
            schema=PASSAGE_SCHEMA,
            corpus_id=corpus.corpus_id,
            corpus_sha256=corpus.corpus_sha256,
            status=status,
            metrics=metrics,
            candidate_keys=tuple(sorted(all_candidates)),
            acquired_routes=tuple(sorted(
                oracle_key(item.surface, item.route_signature)
                for item in newly_acquired
            )),
            errors=tuple(sorted(errors)),
        )


def run_two_pass_experiment(
    runtime: BatchLearningRuntime,
    passage_1: FrozenCorpus,
    passage_2: FrozenCorpus,
    *,
    minimum_paragraphs: int = 100,
) -> dict[str, object]:
    if len(passage_1.paragraphs) < minimum_paragraphs:
        raise ValueError("passage 1 below frozen paragraph minimum")
    if len(passage_2.paragraphs) < minimum_paragraphs:
        raise ValueError("passage 2 below frozen paragraph minimum")
    first = runtime.process(passage_1)
    second = runtime.process(passage_2)
    m1, m2 = first.metrics, second.metrics
    delta = {
        "D_GMA4": m2.D_GMA4 - m1.D_GMA4,
        "A_autonomy": m2.A_autonomy - m1.A_autonomy,
        "contradictions": m2.contradictions - m1.contradictions,
        "observed_false_acquisitions": (
            m2.observed_false_acquisitions - m1.observed_false_acquisitions
        ),
        "oracle_false_acquisitions": (
            None
            if m1.oracle_false_acquisitions is None
            or m2.oracle_false_acquisitions is None
            else m2.oracle_false_acquisitions - m1.oracle_false_acquisitions
        ),
        "coverage_after": m2.coverage_after - m1.coverage_after,
    }
    measured_false = delta["oracle_false_acquisitions"] is not None
    success = (
        m2.D_GMA4 < m1.D_GMA4
        and m2.A_autonomy > m1.A_autonomy
        and m2.contradictions <= m1.contradictions
        and measured_false
        and delta["oracle_false_acquisitions"] <= 0
        and m2.coverage_after >= m1.coverage_after
        and m1.gma4_failures == 0
        and m2.gma4_failures == 0
    )
    if success:
        verdict = "PASS"
    elif not measured_false:
        verdict = "VETO_TRACE_ABSENTE"
    else:
        verdict = "FAIL"
    return {
        "schema": EXPERIMENT_SCHEMA,
        "status": "EXPERIMENTAL_QUARANTINE",
        "promotion": "FORBIDDEN",
        "passage_1": {
            **asdict(first),
            "metrics": asdict(first.metrics),
        },
        "passage_2": {
            **asdict(second),
            "metrics": asdict(second.metrics),
        },
        "delta": delta,
        "success_gate": {
            "D_GMA4_down": m2.D_GMA4 < m1.D_GMA4,
            "A_autonomy_up": m2.A_autonomy > m1.A_autonomy,
            "coherence_non_regression": m2.contradictions <= m1.contradictions,
            "false_acquisition_non_increase": (
                None
                if not measured_false
                else delta["oracle_false_acquisitions"] <= 0
            ),
            "coverage_non_regression": m2.coverage_after >= m1.coverage_after,
        },
        "verdict": verdict,
    }


def _known_from_file(path: str | None) -> set[str]:
    if path is None:
        return set()
    raw = Path(path).read_text(encoding="utf-8")
    if Path(path).suffix.lower() == ".json":
        value = json.loads(raw)
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError("known JSON must be a list of strings")
        return {_norm(item) for item in value if item.strip()}
    return {_norm(line) for line in raw.splitlines() if line.strip()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Experimental batch seam over the existing Zoran learner",
    )
    parser.add_argument("--passage-1")
    parser.add_argument("--passage-2")
    parser.add_argument("--passage")
    parser.add_argument("--known")
    parser.add_argument("--output")
    parser.add_argument("--state-in")
    parser.add_argument("--state-out")
    parser.add_argument("--source-head")
    parser.add_argument("--minimum-paragraphs", type=int, default=100)
    parser.add_argument("--max-workers", type=int, default=16)
    parser.add_argument("--wiktionary-min-interval", type=float, default=1.25)
    parser.add_argument("--wiktionary-cache", default=".zoran/wiktionary-cache")
    args = parser.parse_args(argv)

    one_pass = args.passage is not None
    two_pass = args.passage_1 is not None or args.passage_2 is not None
    if one_pass == two_pass:
        parser.error("choose exactly one-pass --passage or two-pass --passage-1/--passage-2")
    if two_pass and (not args.passage_1 or not args.passage_2):
        parser.error("two-pass mode requires both passages")
    if two_pass and (args.state_in or args.state_out or args.source_head):
        parser.error("state options belong to one-pass cold-restart mode")
    if one_pass and (not args.state_out or not args.source_head):
        parser.error("one-pass mode requires --state-out and --source-head")

    adapter = GMA4TeacherAdapter(call_gma4_teacher, max_contract_attempts=3)
    wiktionary_fetcher = fetch_french_wiktionary_entry
    if args.wiktionary_cache:
        wiktionary_fetcher = WiktionaryDiskCache(
            args.wiktionary_cache,
            wiktionary_fetcher,
        )
    runtime_kwargs = {
        "adapter": adapter,
        "wiktionary_fetcher": wiktionary_fetcher,
        "known_surfaces": _known_from_file(args.known),
        "max_workers": args.max_workers,
        "wiktionary_min_interval_seconds": args.wiktionary_min_interval,
    }
    if args.state_in:
        runtime = BatchLearningRuntime.from_state(
            args.state_in,
            **runtime_kwargs,
            expected_source_head=args.source_head,
        )
    else:
        runtime = BatchLearningRuntime(**runtime_kwargs)

    if one_pass:
        corpus = load_frozen_corpus(args.passage)
        if len(corpus.paragraphs) < args.minimum_paragraphs:
            raise ValueError("passage below frozen paragraph minimum")
        passage = runtime.process(corpus)
        state = runtime.save_state(args.state_out, source_head=args.source_head)
        measured_false = passage.metrics.oracle_false_acquisitions is not None
        if (
            passage.metrics.gma4_failures > 0
            or passage.metrics.invalid_teacher_json > 0
            or passage.metrics.contradictions > 0
            or (
                passage.metrics.oracle_false_acquisitions is not None
                and passage.metrics.oracle_false_acquisitions > 0
            )
        ):
            verdict = "FAIL"
        elif not measured_false or passage.metrics.blocked_route_groups > 0:
            verdict = "VETO_TRACE_ABSENTE"
        else:
            verdict = "PASS"
        result = {
            "schema": "zoran.semantic-learning-cold-passage.v1",
            "status": STATE_STATUS,
            "promotion": "FORBIDDEN",
            "cold_start_loaded": args.state_in is not None,
            "passage": {**asdict(passage), "metrics": asdict(passage.metrics)},
            "state": {
                "generation": state["generation"],
                "parent_state_sha256": state["parent_state_sha256"],
                "state_sha256": state["state_sha256"],
                "counts": state["counts"],
            },
            "verdict": verdict,
        }
    else:
        result = run_two_pass_experiment(
            runtime,
            load_frozen_corpus(args.passage_1),
            load_frozen_corpus(args.passage_2),
            minimum_paragraphs=args.minimum_paragraphs,
        )
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0 if result["verdict"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
