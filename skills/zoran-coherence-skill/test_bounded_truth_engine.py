from bounded_truth_engine import BoundedTruthStatus, Relation, SourceEvidence, SourceKind, build_search_plan, evaluate_bounded_truth


def ev(source_id, kind, relation, group, current=True):
    return SourceEvidence(source_id, kind, relation, group, __import__('hashlib').sha256(source_id.encode()).hexdigest(), current_for_claim=current)


def test_arxiv_only_is_provisional():
    r=evaluate_bounded_truth('claim',[ev('a1',SourceKind.ARXIV_PREPRINT,Relation.SUPPORTS,'lab-a')])
    assert r.status is BoundedTruthStatus.PROVISIONAL
    assert 'PREPRINT_NOT_PEER_REVIEWED_BY_DEFAULT' in r.limitations


def test_two_independent_high_grade_sources_strongly_support():
    r=evaluate_bounded_truth('claim',[ev('o1',SourceKind.OFFICIAL_PRIMARY,Relation.SUPPORTS,'inst-a'),ev('p1',SourceKind.PEER_REVIEWED_PRIMARY,Relation.SUPPORTS,'team-b')])
    assert r.status is BoundedTruthStatus.STRONGLY_SUPPORTED


def test_strong_contradiction_is_preserved():
    r=evaluate_bounded_truth('claim',[ev('p1',SourceKind.PEER_REVIEWED_PRIMARY,Relation.SUPPORTS,'a'),ev('r1',SourceKind.INDEPENDENT_REPLICATION,Relation.CONTRADICTS,'b')])
    assert r.status is BoundedTruthStatus.CONTESTED
    assert r.contradicting_ids==('r1',)


def test_no_verified_support_is_retrye():
    x=SourceEvidence('x1',SourceKind.OFFICIAL_PRIMARY,Relation.SUPPORTS,'g','a'*64,provenance_verified=False)
    assert evaluate_bounded_truth('claim',[x]).status is BoundedTruthStatus.RETRY


def test_stale_current_claim_is_retrye():
    r=evaluate_bounded_truth('claim',[ev('o1',SourceKind.OFFICIAL_PRIMARY,Relation.SUPPORTS,'g',False)],time_sensitive=True)
    assert r.status is BoundedTruthStatus.RETRY


def test_search_plan_has_science_layers():
    p=build_search_plan(scientific=True,time_sensitive=True)
    assert p[0]=='OFFICIAL_OR_PRIMARY_SOURCE'
    assert 'PEER_REVIEWED_LITERATURE' in p and 'INDEPENDENT_REPLICATION' in p and 'ARXIV_PREPRINTS' in p


def test_receipt_deterministic_under_input_order():
    xs=[ev('o1',SourceKind.OFFICIAL_PRIMARY,Relation.SUPPORTS,'a'),ev('p1',SourceKind.PEER_REVIEWED_PRIMARY,Relation.SUPPORTS,'b')]
    assert evaluate_bounded_truth('claim',xs).receipt_sha256==evaluate_bounded_truth('claim',list(reversed(xs))).receipt_sha256
