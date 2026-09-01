from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
from typing import Iterable


@dataclass(frozen=True)
class SemanticObservation:
    observation_id: str
    object_key: str
    source_id: str
    context_signature: tuple[str, ...]
    hypothesis: str | None = None
    provenance: str = "TEXT_CONTEXT"


@dataclass(frozen=True)
class QuarantineVerdict:
    object_key: str
    state: str
    observations: int
    independent_sources: int
    context_families: int
    hypothesis: str | None
    consensus: float
    contradictions: int
    trace_sha256: str
    promotion: str = "FORBIDDEN"


@dataclass
class _Entry:
    observations: dict[str, SemanticObservation] = field(default_factory=dict)


class QuarantineWatcher:
    """Append-only deterministic watcher for semantic candidates.

    It may detect recurrence and hypothesis convergence, but it cannot promote an
    object to canon. The same copied source cannot inflate independent evidence.
    """

    def __init__(self) -> None:
        self._entries: dict[str, _Entry] = {}

    def observe(self, observation: SemanticObservation) -> None:
        if not observation.observation_id or not observation.object_key or not observation.source_id:
            raise ValueError("observation identity fields must be non-empty")
        if not observation.context_signature:
            raise ValueError("context_signature must be non-empty")
        entry = self._entries.setdefault(observation.object_key, _Entry())
        previous = entry.observations.get(observation.observation_id)
        if previous is not None and previous != observation:
            raise ValueError("observation_id collision")
        entry.observations[observation.observation_id] = observation

    def evaluate(
        self,
        object_key: str,
        *,
        min_observations: int = 5,
        min_independent_sources: int = 3,
        min_context_families: int = 3,
        min_consensus: float = 0.80,
    ) -> QuarantineVerdict:
        entry = self._entries.get(object_key, _Entry())
        observations = tuple(sorted(entry.observations.values(), key=lambda x: x.observation_id))
        sources = {item.source_id for item in observations}
        contexts = {item.context_signature for item in observations}

        votes: dict[str, set[str]] = {}
        for item in observations:
            if item.hypothesis is not None:
                # One source contributes at most one vote to a hypothesis.
                votes.setdefault(item.hypothesis, set()).add(item.source_id)

        hypothesis = None
        consensus = 0.0
        contradictions = 0
        if votes:
            ranked = sorted(votes.items(), key=lambda item: (-len(item[1]), item[0]))
            hypothesis, supporters = ranked[0]
            voting_sources = set().union(*(support for _, support in ranked))
            consensus = len(supporters) / max(1, len(voting_sources))
            contradictions = sum(len(support) for label, support in ranked[1:] if label != hypothesis)

        enough_structure = (
            len(observations) >= min_observations
            and len(sources) >= min_independent_sources
            and len(contexts) >= min_context_families
        )

        if not enough_structure:
            state = "QUARANTINED"
        elif hypothesis is None:
            state = "QUARANTINED_NO_SEMANTIC_HYPOTHESIS"
        elif contradictions > 0 and consensus < min_consensus:
            state = "AMBIGUOUS"
        elif consensus >= min_consensus:
            state = "CANDIDATE_STABLE"
        else:
            state = "QUARANTINED_LOW_CONSENSUS"

        payload = {
            "object_key": object_key,
            "state": state,
            "observations": len(observations),
            "independent_sources": len(sources),
            "context_families": len(contexts),
            "hypothesis": hypothesis,
            "consensus": round(consensus, 12),
            "contradictions": contradictions,
            "promotion": "FORBIDDEN",
            "observation_ids": [item.observation_id for item in observations],
        }
        trace = sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
        return QuarantineVerdict(
            object_key=object_key,
            state=state,
            observations=len(observations),
            independent_sources=len(sources),
            context_families=len(contexts),
            hypothesis=hypothesis,
            consensus=consensus,
            contradictions=contradictions,
            trace_sha256=trace,
        )

    def keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._entries))

    def snapshot(self) -> dict[str, tuple[SemanticObservation, ...]]:
        return {
            key: tuple(sorted(entry.observations.values(), key=lambda x: x.observation_id))
            for key, entry in sorted(self._entries.items())
        }
