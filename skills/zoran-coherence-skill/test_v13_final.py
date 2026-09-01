from pathlib import Path

from bounded_truth_engine import SourceEvidence, SourceKind, Relation
from frame_search import FrameSearchEngine, FrameDefinition
from zmos_memory import ZmosMemory, MemoryRecord
from tolerance_skill import Decision
from zoran_runtime import ZoranRuntime


def _runtime():
    return ZoranRuntime(frame_engine=FrameSearchEngine([FrameDefinition('general','General',('general',),priority=1)]))


def _mem(rid, content, s, modality, provenance_char):
    return MemoryRecord(
        record_id=rid, chat_id='c', turn_id=rid, content=content, status='VALIDATED',
        score_s=s, decision='PASS', provenance_sha256=provenance_char*64,
        timestamp='2026-08-31T00:00:00Z', gate_receipt_sha256='c'*64,
        modality=modality,
    )


def test_runtime_zmos_recall_is_coherence_ordered(tmp_path: Path):
    db=tmp_path/'zmos.db'
    with ZmosMemory(db) as z:
        z.append(_mem('a1','alpha memory low', '4','SUPPORTE','a'))
        z.append(_mem('b1','alpha memory high','9','PROUVE','b'))
        r=z.recall('alpha',context_budget_chars=1000)
        assert r.decision is Decision.PASS
        assert r.record_ids[:2]==('b1','a1')
        assert 'COHERENCE_ORDERED_RECALL' in r.reasons


def test_runtime_zmos_recall_preserves_relevant_contradiction(tmp_path: Path):
    db=tmp_path/'zmos.db'
    with ZmosMemory(db) as z:
        z.append(_mem('a1','alpha stable','10','PROUVE','a'))
        z.append(_mem('c1','alpha contradiction','1','CONTRADICTOIRE','c'))
        r=z.recall('alpha',context_budget_chars=len('alpha contradiction'))
        assert r.decision is Decision.PASS
        assert 'c1' in r.record_ids
        assert 'CONTRADICTORY_MEMORY_SURFACED' in r.reasons


def test_old_v1_memory_migrates_without_promoting_truth(tmp_path: Path):
    import sqlite3, hashlib, json
    db=tmp_path/'old.db'
    con=sqlite3.connect(db)
    con.executescript('''
    CREATE TABLE records(record_id TEXT PRIMARY KEY, chat_id TEXT NOT NULL,turn_id TEXT NOT NULL,content TEXT NOT NULL,content_sha256 TEXT NOT NULL,frame_ids TEXT NOT NULL,proxy_ids TEXT NOT NULL,source_ids TEXT NOT NULL,score_s TEXT,delta_s TEXT,decision TEXT NOT NULL,provenance_sha256 TEXT NOT NULL,timestamp TEXT NOT NULL);
    CREATE TABLE status_events(event_seq INTEGER PRIMARY KEY AUTOINCREMENT,record_id TEXT NOT NULL REFERENCES records(record_id),status TEXT NOT NULL CHECK(status IN ('CANDIDATE','BLOCKED','VALIDATED')),gate_receipt_sha256 TEXT,prev_chain_sha256 TEXT NOT NULL,event_sha256 TEXT NOT NULL);
    CREATE TABLE meta(k TEXT PRIMARY KEY,v TEXT NOT NULL);
    INSERT INTO meta VALUES('chain_head','0000000000000000000000000000000000000000000000000000000000000000');
    PRAGMA user_version=1; PRAGMA application_id=1515015473;
    ''')
    con.commit(); con.close()
    with ZmosMemory(db) as z:
        cols=[row[1] for row in z.conn.execute('PRAGMA table_info(records)')]
        assert 'modality' in cols
        assert 'record_sha256' in cols
        assert z.conn.execute('PRAGMA user_version').fetchone()[0]==3


def test_runtime_bounded_truth_plan_and_verification():
    rt=_runtime()
    plan=rt.bounded_truth_search_plan(scientific=True,time_sensitive=True)
    assert 'ARXIV_PREPRINTS' in plan and 'PEER_REVIEWED_LITERATURE' in plan
    evidence=[
        SourceEvidence('o1',SourceKind.OFFICIAL_PRIMARY,Relation.SUPPORTS,'a','a'*64),
        SourceEvidence('p1',SourceKind.PEER_REVIEWED_PRIMARY,Relation.SUPPORTS,'b','b'*64),
    ]
    r=rt.verify_bounded_truth('claim',evidence)
    assert r.status.value=='BOUNDED_TRUTH_STRONGLY_SUPPORTED'


def test_runtime_bounded_truth_arxiv_only_never_becomes_strong_support():
    rt=_runtime()
    evidence=[SourceEvidence('a1',SourceKind.ARXIV_PREPRINT,Relation.SUPPORTS,'lab','a'*64)]
    r=rt.verify_bounded_truth('claim',evidence)
    assert r.status.value=='BOUNDED_TRUTH_PROVISIONAL'


def test_onboarding_ctas_are_dead_simple_and_binary():
    from onboarding import zmos_consent_cta, storage_cta, project_progress_cta
    z=zmos_consent_cta()
    assert '[Oui]' in z and '[Non]' in z and 'ZMOS' in z
    assert 'espace' in storage_cta().lower()
    p=project_progress_cta()
    assert '[Oui]' in p and '[Non]' in p
