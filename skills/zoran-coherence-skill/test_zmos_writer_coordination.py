from __future__ import annotations

from tolerance_skill import Decision
from zmos_writer_coordination import CoordinationAction, WriterCoordinationRequest, ZmosWriterCoordinationGate


HEAD = "a" * 40
CANDIDATE = "b" * 40
RECEIPT = "c" * 64


def request(action: CoordinationAction, *, actor: str = "writer", **changes):
    values = {
        "program_id": "zoran-v21",
        "actor_id": actor,
        "writer_id": "writer",
        "action": action,
        "canonical_github_head": HEAD,
        "base_head": HEAD,
        "candidate_sha": CANDIDATE,
        "test_receipts_sha256": (RECEIPT,),
        "final_github_sha": CANDIDATE if action is CoordinationAction.SYNC_FINAL_GITHUB_SHA else None,
    }
    values.update(changes)
    return WriterCoordinationRequest(**values)


def test_helper_may_enqueue_candidate_but_not_integrate_or_push():
    gate = ZmosWriterCoordinationGate()
    assert gate.evaluate(request(CoordinationAction.ENQUEUE_CANDIDATE, actor="helper")).decision is Decision.PASS
    assert gate.evaluate(request(CoordinationAction.INTEGRATE, actor="helper")).reasons == ("WRITER_AUTHORITY_REQUIRED",)
    assert gate.evaluate(request(CoordinationAction.PUSH, actor="helper")).reasons == ("WRITER_AUTHORITY_REQUIRED",)


def test_candidate_must_be_anchored_to_canonical_github_head():
    result = ZmosWriterCoordinationGate().evaluate(request(CoordinationAction.ENQUEUE_CANDIDATE, base_head="d" * 40))
    assert result.decision is Decision.VETO
    assert "BASE_HEAD_NOT_CANONICAL" in result.reasons


def test_only_writer_may_sync_exact_final_github_sha():
    gate = ZmosWriterCoordinationGate()
    assert gate.evaluate(request(CoordinationAction.SYNC_FINAL_GITHUB_SHA)).decision is Decision.PASS
    mismatch = gate.evaluate(request(CoordinationAction.SYNC_FINAL_GITHUB_SHA, final_github_sha="e" * 40))
    assert mismatch.decision is Decision.VETO
    assert "FINAL_GITHUB_SHA_NOT_CANDIDATE" in mismatch.reasons


def test_zmos_receipt_is_deterministic():
    gate = ZmosWriterCoordinationGate()
    first = gate.evaluate(request(CoordinationAction.PUSH))
    second = gate.evaluate(request(CoordinationAction.PUSH))
    assert first == second
