from pathlib import Path
import pytest

from zmos_memory import ZmosMemory, MemoryRecord, ZmosConflict
from zmos_coherence_selector import ZmosCoherenceSelector, ZmosObject
from tolerance_skill import Decision

H='a'*64


def rec(status='CANDIDATE', decision='RETRY', gate=None, provenance=H):
    return MemoryRecord('r','c','t','content',status,decision=decision,provenance_sha256=provenance,timestamp='2026-08-31T00:00:00Z',gate_receipt_sha256=gate)


def test_validated_memory_requires_real_sha256(tmp_path:Path):
    with ZmosMemory(tmp_path/'z.db') as z:
        with pytest.raises(ZmosConflict):
            z.append(rec('VALIDATED','PASS','not-a-sha'))


def test_memory_requires_real_provenance_sha256(tmp_path:Path):
    with ZmosMemory(tmp_path/'z.db') as z:
        with pytest.raises(ZmosConflict):
            z.append(rec(provenance='x'*64))


def test_blocked_memory_is_terminal(tmp_path:Path):
    with ZmosMemory(tmp_path/'z.db') as z:
        z.append(rec())
        z.promote('r','BLOCKED',gate_decision='VETO',gate_receipt_sha256=H)
        with pytest.raises(ZmosConflict):
            z.promote('r','CANDIDATE',gate_decision='RETRY',gate_receipt_sha256=None)


def test_blocked_memory_requires_gate_receipt(tmp_path:Path):
    with ZmosMemory(tmp_path/'z.db') as z:
        z.append(rec())
        with pytest.raises(ZmosConflict):
            z.promote('r','BLOCKED',gate_decision='VETO',gate_receipt_sha256=None)


def test_selector_rejects_non_hex_provenance():
    r=ZmosCoherenceSelector().select((ZmosObject('r','content','PROUVE',1,'7','x'*64),))
    assert r.decision is Decision.RETRY


def test_selector_rejects_boolean_relevance():
    r=ZmosCoherenceSelector().select((ZmosObject('r','content','PROUVE',True,'7',H),))
    assert r.decision is Decision.RETRY
