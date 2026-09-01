from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import Enum

from tolerance_skill import Decision


COMPONENT_ID = "zoran.zmos-writer-coordination"
VERSION = "21.0.0"
_SHA256 = re.compile(r"[0-9a-f]{64}")
_GIT_SHA = re.compile(r"[0-9a-f]{40}")


class CoordinationAction(str, Enum):
    ENQUEUE_CANDIDATE = "ENQUEUE_CANDIDATE"
    INTEGRATE = "INTEGRATE"
    PUSH = "PUSH"
    SYNC_FINAL_GITHUB_SHA = "SYNC_FINAL_GITHUB_SHA"


@dataclass(frozen=True)
class WriterCoordinationRequest:
    program_id: str
    actor_id: str
    writer_id: str
    action: CoordinationAction
    canonical_github_head: str
    base_head: str
    candidate_sha: str
    test_receipts_sha256: tuple[str, ...]
    final_github_sha: str | None = None


@dataclass(frozen=True)
class WriterCoordinationReceipt:
    decision: Decision
    reasons: tuple[str, ...]
    writer_id: str
    action: str
    receipt_sha256: str


def _digest(payload: object) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class ZmosWriterCoordinationGate:
    """Validate ZMOS coordination envelopes without granting truth authority.

    GitHub remains canonical.  ZMOS stores the queue and receipts; it cannot
    turn a candidate into an integrated or published change.
    """

    def evaluate(self, request: WriterCoordinationRequest) -> WriterCoordinationReceipt:
        reasons: list[str] = []
        if not isinstance(request, WriterCoordinationRequest):
            return self._finish(Decision.VETO, ("COORDINATION_REQUEST_INVALID",), "", "")
        if not all(isinstance(value, str) and value.strip() for value in (request.program_id, request.actor_id, request.writer_id)):
            reasons.append("COORDINATION_ID_INVALID")
        if not isinstance(request.action, CoordinationAction):
            reasons.append("COORDINATION_ACTION_INVALID")
        for label, value in (
            ("CANONICAL_GITHUB_HEAD_INVALID", request.canonical_github_head),
            ("BASE_HEAD_INVALID", request.base_head),
            ("CANDIDATE_SHA_INVALID", request.candidate_sha),
        ):
            if not isinstance(value, str) or not _GIT_SHA.fullmatch(value):
                reasons.append(label)
        if request.base_head != request.canonical_github_head:
            reasons.append("BASE_HEAD_NOT_CANONICAL")
        if not request.test_receipts_sha256 or len(request.test_receipts_sha256) != len(set(request.test_receipts_sha256)):
            reasons.append("TEST_RECEIPTS_MISSING_OR_DUPLICATE")
        elif any(not isinstance(value, str) or not _SHA256.fullmatch(value) for value in request.test_receipts_sha256):
            reasons.append("TEST_RECEIPT_INVALID")
        writer_only = {
            CoordinationAction.INTEGRATE,
            CoordinationAction.PUSH,
            CoordinationAction.SYNC_FINAL_GITHUB_SHA,
        }
        if request.action in writer_only and request.actor_id != request.writer_id:
            reasons.append("WRITER_AUTHORITY_REQUIRED")
        if request.action is CoordinationAction.SYNC_FINAL_GITHUB_SHA:
            if not isinstance(request.final_github_sha, str) or not _GIT_SHA.fullmatch(request.final_github_sha):
                reasons.append("FINAL_GITHUB_SHA_INVALID")
            elif request.final_github_sha != request.candidate_sha:
                reasons.append("FINAL_GITHUB_SHA_NOT_CANDIDATE")
        elif request.final_github_sha is not None:
            reasons.append("FINAL_GITHUB_SHA_PREMATURE")
        return self._finish(Decision.VETO if reasons else Decision.PASS, tuple(reasons), request.writer_id, request.action.value)

    def _finish(self, decision: Decision, reasons: tuple[str, ...], writer_id: str, action: str) -> WriterCoordinationReceipt:
        receipt = _digest({
            "component": COMPONENT_ID,
            "version": VERSION,
            "decision": decision.value,
            "reasons": list(reasons),
            "writer_id": writer_id,
            "action": action,
        })
        return WriterCoordinationReceipt(decision, reasons, writer_id, action, receipt)
