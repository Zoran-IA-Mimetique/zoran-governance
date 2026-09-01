import hashlib
from tolerance_skill import Decision
from zmos_coherence_selector import ZmosCoherenceSelector,ZmosObject


def o(i,mod,s,rel=1,content='x'):
    return ZmosObject(i,content,mod,rel,s,hashlib.sha256((i or 'a').encode()).hexdigest())


def test_coherence_orders_relevant_objects():
    r=ZmosCoherenceSelector().select([o('a1','SUPPORTE','7'),o('b1','PROUVE','9')])
    assert [x.object_id for x in r.selected][:2]==['b1','a1']


def test_irrelevant_object_is_not_recalled_even_if_high_coherence():
    r=ZmosCoherenceSelector().select([o('a1','PROUVE','99',0),o('b1','SUPPORTE','4',2)])
    assert [x.object_id for x in r.selected]==['b1']


def test_relevant_contradiction_is_surfaced_and_label_preserved():
    r=ZmosCoherenceSelector().select([o('a1','PROUVE','10',5),o('c1','CONTRADICTOIRE','1',9)],max_objects=1)
    assert len(r.selected)==1 and r.selected[0].object_id=='c1'
    assert r.selected[0].modality=='CONTRADICTOIRE'
    assert 'CONTRADICTORY_MEMORY_SURFACED' in r.reasons


def test_trace_pending_memory_stays_explicit_not_promoted():
    r=ZmosCoherenceSelector().select([o('u1','RETRY',None,3)])
    assert r.decision is Decision.PASS
    assert r.selected[0].modality=='RETRY'
    assert 'TRACE_PENDING_MEMORY_SURFACED_AS_TRACE_PENDING' in r.reasons


def test_unknown_modality_fails_closed():
    r=ZmosCoherenceSelector().select([o('x1','MAGIC','5')])
    assert r.decision is Decision.RETRY


def test_replay_is_deterministic():
    xs=[o('a1','SUPPORTE','7',2),o('b1','PROUVE','9',1),o('c1','CONTRADICTOIRE','2',4)]
    a=ZmosCoherenceSelector().select(xs,max_objects=3)
    b=ZmosCoherenceSelector().select(list(reversed(xs)),max_objects=3)
    assert a.receipt_sha256==b.receipt_sha256
