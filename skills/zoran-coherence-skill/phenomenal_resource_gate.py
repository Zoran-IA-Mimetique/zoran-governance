from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping, Sequence

from phenomenal_coherence import CANONICAL_FRAMES
from phenomenal_resource_attestation import PhenomenalResourceAttestationError, verify_resource_attestation
from tolerance_skill import Decision


COMPONENT_ID = "zoran.phenomenal-resource-gate"
VERSION = "17.0.0"
SHA_RE = re.compile(r"[0-9a-f]{64}")
CANONICAL_PROXY_IDS = ("beta", "dphi", "T", "sigma")


@dataclass(frozen=True)
class ProxyResource:
    proxy_id: str
    value: float
    unit: str
    source_receipt_sha256: str
    observed_at: str


@dataclass(frozen=True)
class PhenomenalResourceRound:
    round_index: int
    resource_ids: Sequence[str]
    frame_receipts: Mapping[str, str]
    proxy_resources: Sequence[ProxyResource]
    completed_at: str
    authority_certificate: Mapping[str, object] | None = None


@dataclass(frozen=True)
class PhenomenalResourceRequest:
    mission_sha256: str
    required_proxy_ids: Sequence[str]
    rounds: Sequence[PhenomenalResourceRound]


@dataclass(frozen=True)
class PhenomenalResourceEvaluation:
    decision: Decision
    state: str
    completed_round: int | None
    reasons: tuple[str, ...]
    receipt_sha256: str


def _canonical_sha(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timezone required")
    return parsed.astimezone(timezone.utc)


class PhenomenalResourceGate:
    """Bounded two-round resource search before any phenomenal score exists."""

    def evaluate(self, request: PhenomenalResourceRequest | None) -> PhenomenalResourceEvaluation:
        if not isinstance(request, PhenomenalResourceRequest):
            return self._finish(Decision.RETRY, "GYROPHARE", None, self._retry_reasons(
                "PHENOMENAL_RESOURCE_REQUEST_REQUIRED", "PHENOMENAL_RESOURCE_REQUEST", "HOST_RETRIEVAL_CONNECTOR", "SEARCH_DISTINCT_RESOURCE_ROUND_1", 2
            ))
        if not SHA_RE.fullmatch(request.mission_sha256):
            return self._finish(Decision.RETRY, "GYROPHARE", None, self._retry_reasons(
                "MISSION_IDENTITY_INVALID", "SIGNED_MISSION_IDENTITY", "HOST_MISSION_SEALER", "SEAL_EXACT_MISSION_AND_RESTART_ROUND_1", 2
            ))
        required = tuple(request.required_proxy_ids)
        if required != CANONICAL_PROXY_IDS:
            return self._finish(Decision.VETO, "GYROPHARE", None, ("REQUIRED_PROXY_CONTRACT_INVALID", "RETOUR_ENVOYEUR"))
        rounds = tuple(request.rounds)
        if not rounds:
            return self._finish(Decision.RETRY, "GYROPHARE", None, self._retry_reasons(
                "PHENOMENAL_RESOURCE_SEARCH_NOT_STARTED", "SIX_FRAMES_AND_FOUR_PROXIES", "HOST_RETRIEVAL_CONNECTOR", "SEARCH_DISTINCT_RESOURCE_ROUND_1", 2
            ))
        if len(rounds) > 2 or any(not isinstance(item, PhenomenalResourceRound) for item in rounds):
            return self._finish(Decision.VETO, "GYROPHARE", None, ("RESOURCE_SEARCH_ROUND_LIMIT_VIOLATED",))
        if tuple(item.round_index for item in rounds) != tuple(range(1, len(rounds) + 1)):
            return self._finish(Decision.VETO, "GYROPHARE", None, ("RESOURCE_SEARCH_ROUND_ORDER_INVALID",))

        first_ids: set[str] = set()
        for position, item in enumerate(rounds):
            resource_ids = tuple(item.resource_ids)
            if not resource_ids or len(resource_ids) != len(set(resource_ids)) or any(not isinstance(value, str) or not value.strip() for value in resource_ids):
                if item.round_index == 2:
                    return self._finish(Decision.VETO, "GYROPHARE", 2, self._exhausted_reasons(f"RESOURCE_IDENTITIES_INVALID:ROUND_{item.round_index}"))
                return self._finish(Decision.RETRY, "GYROPHARE", 1, self._retry_reasons(
                    "RESOURCE_IDENTITIES_INVALID:ROUND_1", "DISTINCT_RESOURCE_IDENTITIES", "HOST_RETRIEVAL_CONNECTOR", "SEARCH_DISTINCT_RESOURCE_ROUND_2", 1
                ))
            current_ids = set(resource_ids)
            if position == 1 and not current_ids - first_ids:
                return self._finish(Decision.VETO, "GYROPHARE", item.round_index, ("SECOND_ROUND_HAS_NO_NEW_RESOURCE",))
            if position == 0:
                first_ids = current_ids
            complete, reasons = self._round_complete(item, required)
            if complete:
                if not isinstance(item.authority_certificate, Mapping):
                    return self._finish(Decision.VETO, "GYROPHARE", item.round_index, ("HALLUCINATION_BLOQUANTE_MESURE_SANS_ATTESTATION",))
                try:
                    attestation_sha = verify_resource_attestation(
                        item.authority_certificate,
                        mission_sha256=request.mission_sha256,
                        round_=item,
                    )
                except PhenomenalResourceAttestationError as exc:
                    return self._finish(Decision.VETO, "GYROPHARE", item.round_index, (str(exc),))
                if item.round_index == 1 and len(rounds) == 2:
                    return self._finish(Decision.VETO, "GYROPHARE", 1, ("SECOND_ROUND_NOT_AUTHORIZED_AFTER_COMPLETE_FIRST_ROUND",))
                return self._finish(
                    Decision.PASS,
                    "MESURE_DISPONIBLE",
                    item.round_index,
                    (f"PHENOMENAL_RESOURCES_COMPLETE:ROUND_{item.round_index}", f"PHENOMENAL_RESOURCE_ATTESTATION:{attestation_sha}"),
                )
            if item.round_index == 1 and len(rounds) == 1:
                missing = ",".join(reasons)
                return self._finish(Decision.RETRY, "GYROPHARE", 1, self._retry_reasons(
                    "GYROPHARE_MESURE_INCOMPLETE_RECHERCHE_TOUR_2_REQUISE",
                    missing,
                    "HOST_RETRIEVAL_CONNECTOR",
                    "SEARCH_DISTINCT_RESOURCE_ROUND_2",
                    1,
                ) + reasons)
            if item.round_index == 2:
                return self._finish(Decision.VETO, "GYROPHARE", 2, self._exhausted_reasons(*reasons))
        return self._finish(Decision.VETO, "GYROPHARE", None, ("HALLUCINATION_BLOQUANTE_OU_PHENOMENE_INEXISTANT", "RETOUR_ENVOYEUR"))

    @staticmethod
    def _retry_reasons(reason: str, missing_trace: str, owner: str, action: str, remaining_budget: int) -> tuple[str, ...]:
        return (
            reason,
            f"TRACE_MANQUANTE:{missing_trace}",
            f"OWNER:{owner}",
            f"NEXT_ACTION:{action}",
            f"REMAINING_SEARCH_BUDGET:{remaining_budget}",
            "EXIT_CONDITION:SIGNED_COMPLETE_MEASURE_OR_VETO",
        )

    @staticmethod
    def _exhausted_reasons(*details: str) -> tuple[str, ...]:
        return (
            "GYROPHARE_TRACE_ABSENTE_APRES_DEUX_RECHERCHES",
            "HALLUCINATION_BLOQUANTE_OU_PHENOMENE_INEXISTANT",
            "RETOUR_ENVOYEUR",
        ) + details

    @staticmethod
    def _round_complete(item: PhenomenalResourceRound, required: tuple[str, ...]) -> tuple[bool, tuple[str, ...]]:
        reasons: list[str] = []
        if set(item.frame_receipts) != set(CANONICAL_FRAMES) or any(not SHA_RE.fullmatch(value) for value in item.frame_receipts.values()):
            reasons.append(f"FRAME_RESOURCES_INCOMPLETE:ROUND_{item.round_index}")
        proxies = tuple(item.proxy_resources)
        ids = [proxy.proxy_id for proxy in proxies if isinstance(proxy, ProxyResource)]
        if set(ids) != set(required) or len(ids) != len(set(ids)):
            reasons.append(f"PROXY_RESOURCES_INCOMPLETE:ROUND_{item.round_index}")
        try:
            completed_at = _time(item.completed_at)
        except Exception:
            reasons.append(f"ROUND_COMPLETION_TIME_INVALID:ROUND_{item.round_index}")
            completed_at = None
        for proxy in proxies:
            if (
                not isinstance(proxy, ProxyResource)
                or isinstance(proxy.value, bool)
                or not isinstance(proxy.value, (int, float))
                or not math.isfinite(float(proxy.value))
                or not isinstance(proxy.unit, str)
                or not proxy.unit.strip()
                or not SHA_RE.fullmatch(proxy.source_receipt_sha256)
                or not isinstance(proxy.observed_at, str)
                or not proxy.observed_at.strip()
            ):
                reasons.append(f"PROXY_VALUE_OR_SOURCE_INVALID:ROUND_{item.round_index}")
                break
            try:
                if completed_at is not None and _time(proxy.observed_at) > completed_at:
                    reasons.append(f"PROXY_OBSERVED_AFTER_ROUND:ROUND_{item.round_index}")
                    break
            except Exception:
                reasons.append(f"PROXY_OBSERVED_TIME_INVALID:ROUND_{item.round_index}")
                break
        return not reasons, tuple(reasons)

    @staticmethod
    def _finish(decision: Decision, state: str, completed_round: int | None, reasons: tuple[str, ...]) -> PhenomenalResourceEvaluation:
        body = {
            "component": COMPONENT_ID,
            "version": VERSION,
            "decision": decision.value,
            "state": state,
            "completed_round": completed_round,
            "reasons": list(reasons),
        }
        return PhenomenalResourceEvaluation(decision, state, completed_round, reasons, _canonical_sha(body))
