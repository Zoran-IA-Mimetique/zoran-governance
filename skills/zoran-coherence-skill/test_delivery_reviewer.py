from delivery_reviewer import (
    PASS, FAIL, RETRY,
    DeliveryReviewer, DeliveryReviewRequest, ReviewCheck,
)

H = 'a' * 64
O = __import__('hashlib').sha256('Construire et livrer un skill conforme'.encode()).hexdigest()


def _checks(code_defects=0, coherence_defects=0):
    return (
        ReviewCheck('done','DONE',PASS,True,H,('objective',),'Livraison exécutée',objective_sha256=O),
        ReviewCheck('objective','OBJECTIVE_CONFORMITY',PASS,True,H,('objective','user_contract'),'Conforme à la demande',objective_sha256=O),
        ReviewCheck('multi','MULTIFRAME_COHERENCE',PASS,True,H,('local','global'),'Cohérence locale et générale',objective_sha256=O),
        ReviewCheck('code','CODE_QUALITY',PASS,True,H,('code','runtime'),'Code revu',observed_defects=code_defects,objective_sha256=O),
        ReviewCheck('coherence','COHERENCE_QUALITY',PASS,True,H,('objective','global'),'Cohérence revue',observed_defects=coherence_defects,objective_sha256=O),
        ReviewCheck('evidence','EVIDENCE_COMPLETENESS',PASS,True,H,('proof','scope'),'Preuves complètes',objective_sha256=O),
        ReviewCheck('independent','INDEPENDENT_REVIEW',PASS,True,H,('review','governance'),'Reviewer séparé',objective_sha256=O),
    )


def _req(checks=None, reviewed=('a.py','b.py'), reviewer='ZORAN_REVIEWER'):
    return DeliveryReviewRequest(
        'D1','Construire et livrer un skill conforme',
        'BUILDER_SESSION',reviewer,
        ('a.py','b.py'),tuple(reviewed),tuple(_checks() if checks is None else checks),
    )


def test_complete_delivery_review_passes():
    r=DeliveryReviewer().evaluate(_req())
    assert r.status==PASS
    assert r.observed_code_defects==0
    assert r.observed_coherence_defects==0


def test_done_is_not_enough_without_conformity():
    checks=tuple(x for x in _checks() if x.category!='OBJECTIVE_CONFORMITY')
    r=DeliveryReviewer().evaluate(_req(checks))
    assert r.status==RETRY
    assert any('OBJECTIVE_CONFORMITY' in x for x in r.reasons)


def test_unreviewed_file_blocks_closure():
    r=DeliveryReviewer().evaluate(_req(reviewed=('a.py',)))
    assert r.status==RETRY
    assert 'FILE_NOT_REVIEWED:b.py' in r.reasons


def test_code_defect_vetoes_delivery():
    r=DeliveryReviewer().evaluate(_req(_checks(code_defects=1)))
    assert r.status==FAIL
    assert 'CODE_DEFECTS_OBSERVED:1' in r.reasons


def test_coherence_defect_vetoes_delivery():
    r=DeliveryReviewer().evaluate(_req(_checks(coherence_defects=2)))
    assert r.status==FAIL
    assert 'COHERENCE_DEFECTS_OBSERVED:2' in r.reasons


def test_multiframe_requires_two_distinct_frames():
    checks=list(_checks())
    i=next(i for i,x in enumerate(checks) if x.category=='MULTIFRAME_COHERENCE')
    checks[i]=ReviewCheck('multi','MULTIFRAME_COHERENCE',PASS,True,H,('local',),'Cohérence locale seulement',objective_sha256=O)
    r=DeliveryReviewer().evaluate(_req(checks))
    assert r.status==RETRY
    assert 'MULTIFRAME_REVIEW_REQUIRES_AT_LEAST_TWO_FRAMES' in r.reasons


def test_missing_evidence_never_passes():
    checks=list(_checks())
    checks[0]=ReviewCheck('done','DONE',PASS,True,None,('objective',),'Livraison exécutée',objective_sha256=O)
    assert DeliveryReviewer().evaluate(_req(checks)).status==RETRY


def test_self_review_is_forbidden():
    r=DeliveryReviewer().evaluate(_req(reviewer='BUILDER_SESSION'))
    assert r.status==FAIL
    assert 'SELF_REVIEW_FORBIDDEN' in r.reasons


def test_receipt_is_deterministic():
    a=DeliveryReviewer().evaluate(_req())
    b=DeliveryReviewer().evaluate(_req())
    assert a.receipt_sha256==b.receipt_sha256

def test_reviewer_blocks_unregistered_category():
    checks=_checks()+(ReviewCheck('x','UNDECLARED',PASS,True,H,('x',),'x',objective_sha256=O),)
    assert DeliveryReviewer().evaluate(_req(checks)).status==FAIL
