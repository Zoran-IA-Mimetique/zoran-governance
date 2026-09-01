from __future__ import annotations
import hashlib,json,os,re,sqlite3,stat,time
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable,Sequence
from tolerance_skill import Decision
from zmos_coherence_selector import ZmosCoherenceSelector, ZmosObject

STATUSES={'CANDIDATE','BLOCKED','VALIDATED'}
SCHEMA_VERSION=3
APP_ID=0x5A4D4D31

class ZmosError(RuntimeError): pass
class ZmosIntegrityError(ZmosError): pass
class ZmosConflict(ZmosError): pass


def _canon(v)->bytes:return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
def _sha(v)->str:return hashlib.sha256(_canon(v)).hexdigest()
def _tokens(s:str)->set[str]:return set(re.findall(r'[a-z0-9]+',s.lower()))
def _valid_sha(v:str|None)->bool:return isinstance(v,str) and len(v)==64 and all(c in '0123456789abcdef' for c in v)

_RECORD_FIELDS=('record_id','chat_id','turn_id','content','content_sha256','frame_ids','proxy_ids','source_ids','score_s','delta_s','decision','provenance_sha256','timestamp','modality')
def _record_sha(values)->str:return _sha(dict(zip(_RECORD_FIELDS,values)))
def _bounded_decimal(value,minimum,maximum):
    if value is None:return True
    try:x=Decimal(str(value))
    except (InvalidOperation,ValueError):return False
    return x.is_finite() and Decimal(str(minimum))<=x<=Decimal(str(maximum))
def _valid_timestamp(value):
    if not isinstance(value,str) or not value:return False
    try:d=datetime.fromisoformat(value.replace('Z','+00:00'))
    except ValueError:return False
    return d.tzinfo is not None

def _safe_path(p:Path,allow_absent=True):
    if not p.parent.exists(): raise ZmosError('memory parent must exist')
    if p.exists():
        st=p.lstat()
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode) or st.st_nlink!=1: raise ZmosIntegrityError('unsafe memory path')
    elif not allow_absent: raise ZmosIntegrityError('memory absent')

@dataclass(frozen=True)
class MemoryRecord:
    record_id:str; chat_id:str; turn_id:str; content:str; status:str
    frame_ids:tuple[str,...]=(); proxy_ids:tuple[str,...]=(); source_ids:tuple[str,...]=()
    score_s:str|None=None; delta_s:str|None=None; decision:str='RETRY'; provenance_sha256:str=''; timestamp:str=''
    gate_receipt_sha256:str|None=None
    modality:str='RETRY'

@dataclass(frozen=True)
class RecallResult:
    decision:Decision; record_ids:tuple[str,...]; contents:tuple[str,...]; context_digest:str; chars_used:int; reasons:tuple[str,...]

class ZmosMemory:
    """Local SQLite WAL memory. No fixed object-count ceiling; recall is bounded only by explicit context budget."""
    def __init__(self,database:str|Path,*,max_storage_bytes:int|None=None):
        self.path=Path(database).resolve(); _safe_path(self.path,True)
        if max_storage_bytes is not None and (not isinstance(max_storage_bytes,int) or isinstance(max_storage_bytes,bool) or max_storage_bytes<=0):raise ValueError('max_storage_bytes must be a positive integer')
        self.max_storage_bytes=max_storage_bytes
        self.conn=sqlite3.connect(self.path,isolation_level=None,timeout=30)
        self.conn.execute('PRAGMA busy_timeout=30000'); self.conn.execute('PRAGMA journal_mode=WAL'); self.conn.execute('PRAGMA synchronous=FULL'); self.conn.execute('PRAGMA foreign_keys=ON')
        self._init(); self._secure_files(); self.verify()
    def close(self): self.conn.close()
    def __enter__(self): return self
    def __exit__(self,*_): self.close()
    def _init(self):
        self.conn.execute('BEGIN IMMEDIATE')
        try:
            tables=self.conn.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='records'").fetchone()[0]
            if not tables:
                self.conn.execute("CREATE TABLE records(record_id TEXT PRIMARY KEY, chat_id TEXT NOT NULL,turn_id TEXT NOT NULL,content TEXT NOT NULL,content_sha256 TEXT NOT NULL,frame_ids TEXT NOT NULL,proxy_ids TEXT NOT NULL,source_ids TEXT NOT NULL,score_s TEXT,delta_s TEXT,decision TEXT NOT NULL,provenance_sha256 TEXT NOT NULL,timestamp TEXT NOT NULL,modality TEXT NOT NULL DEFAULT 'RETRY',record_sha256 TEXT NOT NULL)")
                self.conn.execute("CREATE TABLE status_events(event_seq INTEGER PRIMARY KEY AUTOINCREMENT,record_id TEXT NOT NULL REFERENCES records(record_id),status TEXT NOT NULL CHECK(status IN ('CANDIDATE','BLOCKED','VALIDATED')),gate_receipt_sha256 TEXT,prev_chain_sha256 TEXT NOT NULL,event_sha256 TEXT NOT NULL)")
                self.conn.execute("CREATE TABLE meta(k TEXT PRIMARY KEY,v TEXT NOT NULL)")
                self.conn.execute("INSERT INTO meta VALUES('chain_head',?)",('0'*64,))
                self.conn.execute('PRAGMA user_version=3'); self.conn.execute(f'PRAGMA application_id={APP_ID}')
            version=self.conn.execute('PRAGMA user_version').fetchone()[0]
            app_id=self.conn.execute('PRAGMA application_id').fetchone()[0]
            if app_id!=APP_ID: raise ZmosIntegrityError('foreign memory schema')
            if version==1:
                self.conn.execute("ALTER TABLE records ADD COLUMN modality TEXT NOT NULL DEFAULT 'RETRY'")
                self.conn.execute('PRAGMA user_version=2'); version=2
            if version==2:
                self.conn.execute("ALTER TABLE records ADD COLUMN record_sha256 TEXT NOT NULL DEFAULT ''")
                rows=self.conn.execute('SELECT record_id,chat_id,turn_id,content,content_sha256,frame_ids,proxy_ids,source_ids,score_s,delta_s,decision,provenance_sha256,timestamp,modality FROM records').fetchall()
                for row in rows:self.conn.execute('UPDATE records SET record_sha256=? WHERE record_id=?',(_record_sha(row),row[0]))
                self.conn.execute('PRAGMA user_version=3'); version=3
            if version!=SCHEMA_VERSION: raise ZmosIntegrityError('foreign memory schema')
            self.conn.execute('COMMIT')
        except Exception:
            if self.conn.in_transaction:self.conn.execute('ROLLBACK')
            raise
    def _secure_files(self):
        for path in (self.path,Path(str(self.path)+'-wal'),Path(str(self.path)+'-shm')):
            if path.exists():os.chmod(path,0o600)
    def _ensure_quota(self,incoming_bytes:int):
        if self.max_storage_bytes is None:return
        page_size=self.conn.execute('PRAGMA page_size').fetchone()[0]; page_count=self.conn.execute('PRAGMA page_count').fetchone()[0]
        wal=Path(str(self.path)+'-wal'); physical=page_size*page_count+(wal.stat().st_size if wal.exists() else 0)
        if physical+incoming_bytes+2*page_size>self.max_storage_bytes:raise ZmosConflict('ZMOS storage quota exceeded')
    def _current_status(self,record_id):
        row=self.conn.execute('SELECT status,gate_receipt_sha256 FROM status_events WHERE record_id=? ORDER BY event_seq DESC LIMIT 1',(record_id,)).fetchone(); return row
    def append(self,r:MemoryRecord)->bool:
        if r.status not in STATUSES: raise ValueError('invalid status')
        if not r.record_id.strip() or not r.chat_id.strip() or not r.turn_id.strip() or not r.content:
            raise ZmosConflict('record identity/content required')
        if not _valid_sha(r.provenance_sha256): raise ZmosConflict('valid provenance SHA-256 required')
        if r.modality not in {'PROUVE','SUPPORTE','DEDUIT','INCERTAIN','CONTRADICTOIRE','INCONNU','RETRY'}: raise ZmosConflict('invalid modality')
        if r.decision not in {x.value for x in Decision}: raise ZmosConflict('invalid decision')
        if not _bounded_decimal(r.score_s,0,100): raise ZmosConflict('score S must be finite and inside [0,100]')
        if not _bounded_decimal(r.delta_s,-100,100): raise ZmosConflict('delta S must be finite and inside [-100,100]')
        if not _valid_timestamp(r.timestamp): raise ZmosConflict('timezone-aware timestamp required')
        for name,values in (('frame_ids',r.frame_ids),('proxy_ids',r.proxy_ids),('source_ids',r.source_ids)):
            if len(values)!=len(set(values)) or any(not isinstance(x,str) or not x.strip() for x in values): raise ZmosConflict(f'invalid {name}')
        if r.gate_receipt_sha256 is not None and not _valid_sha(r.gate_receipt_sha256): raise ZmosConflict('invalid gate receipt SHA-256')
        if r.status=='VALIDATED' and (r.decision!='PASS' or not _valid_sha(r.gate_receipt_sha256)): raise ZmosConflict('validated requires PASS gate receipt')
        content_sha=hashlib.sha256(r.content.encode()).hexdigest()
        payload=(r.record_id,r.chat_id,r.turn_id,r.content,content_sha,json.dumps(sorted(r.frame_ids)),json.dumps(sorted(r.proxy_ids)),json.dumps(sorted(r.source_ids)),r.score_s,r.delta_s,r.decision,r.provenance_sha256,r.timestamp,r.modality)
        payload=payload+(_record_sha(payload),)
        existing=self.conn.execute('SELECT chat_id,turn_id,content,content_sha256,frame_ids,proxy_ids,source_ids,score_s,delta_s,decision,provenance_sha256,timestamp,modality,record_sha256 FROM records WHERE record_id=?',(r.record_id,)).fetchone()
        expected=payload[1:]
        if existing:
            if tuple(existing)!=tuple(expected): raise ZmosConflict('record identity reused for different content')
            st=self._current_status(r.record_id)
            if st and st[0]==r.status and st[1]==r.gate_receipt_sha256:return True
            return self.promote(r.record_id,r.status,gate_decision=r.decision,gate_receipt_sha256=r.gate_receipt_sha256)
        try:
            self.conn.execute('BEGIN IMMEDIATE')
            self._ensure_quota(sum(len(str(value).encode()) for value in payload))
            self.conn.execute('INSERT INTO records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',payload)
            self._append_event(r.record_id,r.status,r.gate_receipt_sha256)
            self.conn.execute('COMMIT')
        except Exception:
            if self.conn.in_transaction:self.conn.execute('ROLLBACK')
            raise
        self._secure_files(); return False
    def promote(self,record_id:str,status:str,*,gate_decision:str,gate_receipt_sha256:str|None):
        if status not in STATUSES: raise ValueError
        if status=='CANDIDATE': raise ZmosConflict('candidate is an initial state, not a promotion target')
        if gate_receipt_sha256 is not None and not _valid_sha(gate_receipt_sha256): raise ZmosConflict('invalid gate receipt SHA-256')
        row=self.conn.execute('SELECT record_id FROM records WHERE record_id=?',(record_id,)).fetchone()
        if not row: raise ZmosConflict('record absent')
        old=self._current_status(record_id)
        if status=='VALIDATED' and (gate_decision!='PASS' or not _valid_sha(gate_receipt_sha256)): raise ZmosConflict('invalid direct validation')
        if status=='BLOCKED' and gate_decision=='PASS': raise ZmosConflict('blocked status incompatible with PASS gate')
        if old and old[0]=='BLOCKED' and status!='BLOCKED': raise ZmosConflict('blocked record immutable; create corrected record')
        if old and old[0]=='VALIDATED' and status!='VALIDATED': raise ZmosConflict('validated record immutable')
        if old and old[0]==status:
            if old[1]==gate_receipt_sha256:return True
            raise ZmosConflict('terminal status receipt immutable')
        self.conn.execute('BEGIN IMMEDIATE')
        try:self._ensure_quota(len(record_id.encode())+len(status.encode())+(len(gate_receipt_sha256) if gate_receipt_sha256 else 0)); self._append_event(record_id,status,gate_receipt_sha256); self.conn.execute('COMMIT')
        except Exception:
            if self.conn.in_transaction:self.conn.execute('ROLLBACK')
            raise
        self._secure_files(); return False
    def _append_event(self,record_id,status,gate):
        if gate is not None and not _valid_sha(gate): raise ZmosConflict('invalid gate receipt SHA-256')
        if status in {'BLOCKED','VALIDATED'} and not _valid_sha(gate): raise ZmosConflict('terminal status requires gate receipt SHA-256')
        prev=self.conn.execute("SELECT v FROM meta WHERE k='chain_head'").fetchone()[0]
        body={'record_id':record_id,'status':status,'gate_receipt_sha256':gate,'prev_chain_sha256':prev}
        h=_sha(body)
        self.conn.execute('INSERT INTO status_events(record_id,status,gate_receipt_sha256,prev_chain_sha256,event_sha256) VALUES(?,?,?,?,?)',(record_id,status,gate,prev,h))
        self.conn.execute("UPDATE meta SET v=? WHERE k='chain_head'",(h,))
    def verify(self):
        _safe_path(self.path,False)
        started=not self.conn.in_transaction
        if started:self.conn.execute('BEGIN')
        try:
            if self.conn.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ZmosIntegrityError('quick_check failed')
            prev='0'*64
            for rec,status,gate,p,h in self.conn.execute('SELECT record_id,status,gate_receipt_sha256,prev_chain_sha256,event_sha256 FROM status_events ORDER BY event_seq'):
                if p!=prev: raise ZmosIntegrityError('event chain truncated/reordered')
                calc=_sha({'record_id':rec,'status':status,'gate_receipt_sha256':gate,'prev_chain_sha256':p})
                if calc!=h: raise ZmosIntegrityError('event tamper')
                prev=h
            head=self.conn.execute("SELECT v FROM meta WHERE k='chain_head'").fetchone()[0]
            if head!=prev:raise ZmosIntegrityError('chain head mismatch')
            for row in self.conn.execute('SELECT record_id,chat_id,turn_id,content,content_sha256,frame_ids,proxy_ids,source_ids,score_s,delta_s,decision,provenance_sha256,timestamp,modality,record_sha256 FROM records'):
                if hashlib.sha256(row[3].encode()).hexdigest()!=row[4]:raise ZmosIntegrityError('record content tamper')
                if _record_sha(row[:-1])!=row[-1]:raise ZmosIntegrityError('record metadata tamper')
            if started:self.conn.execute('COMMIT')
            self._secure_files(); return True
        except Exception:
            if started and self.conn.in_transaction:self.conn.execute('ROLLBACK')
            raise
    def recall(self,query:str,*,frame_ids:Sequence[str]=(),proxy_ids:Sequence[str]=(),source_ids:Sequence[str]=(),context_budget_chars:int|None=200000)->RecallResult:
        request={'query_sha256':hashlib.sha256(query.encode()).hexdigest() if isinstance(query,str) else hashlib.sha256(repr(query).encode()).hexdigest(),'frame_ids':list(frame_ids),'proxy_ids':list(proxy_ids),'source_ids':list(source_ids),'context_budget_chars':context_budget_chars}
        request_sha=_sha(request)
        finish=lambda decision,ids,contents,selection_sha,used,reasons:RecallResult(decision,tuple(ids),tuple(contents),_sha({'request_sha256':request_sha,'selection_receipt_sha256':selection_sha,'record_ids':list(ids),'content_sha256':[hashlib.sha256(x.encode()).hexdigest() for x in contents]}),used,tuple(reasons))
        if not isinstance(query,str) or context_budget_chars is not None and (not isinstance(context_budget_chars,int) or isinstance(context_budget_chars,bool) or context_budget_chars<0):return finish(Decision.RETRY,(),(),None,0,('ZMOS_RECALL_REQUEST_INVALID',))
        if any(len(values)!=len(set(values)) or any(not isinstance(x,str) or not x.strip() for x in values) for values in (frame_ids,proxy_ids,source_ids)):return finish(Decision.RETRY,(),(),None,0,('ZMOS_RECALL_REQUEST_INVALID',))
        try:self.verify()
        except Exception:return finish(Decision.RETRY,(),(),None,0,('ZMOS_CORRUPT_OR_UNAVAILABLE',))
        qtok=_tokens(query); f=set(frame_ids); p=set(proxy_ids); s=set(source_ids); objects=[]
        rows=self.conn.execute("""SELECT r.record_id,r.content,r.frame_ids,r.proxy_ids,r.source_ids,r.score_s,r.provenance_sha256,r.modality FROM records r JOIN status_events e ON e.event_seq=(SELECT max(e2.event_seq) FROM status_events e2 WHERE e2.record_id=r.record_id) WHERE e.status='VALIDATED' ORDER BY r.record_id""").fetchall()
        for rid,content,fj,pj,sj,score_s,provenance,modality in rows:
            rf=set(json.loads(fj)); rp=set(json.loads(pj)); rs=set(json.loads(sj))
            relevance=100*len(f&rf)+60*len(p&rp)+40*len(s&rs)+len(qtok&_tokens(content))
            if not qtok and not f and not p and not s:
                relevance=max(1,relevance)
            if relevance>0:
                objects.append(ZmosObject(rid,content,modality,relevance,score_s,provenance))
        selection=ZmosCoherenceSelector().select(objects,max_chars=context_budget_chars)
        if selection.decision is not Decision.PASS:
            return finish(selection.decision,(),(),selection.receipt_sha256,0,('ZMOS_COHERENCE_SELECTION_BLOCK',)+selection.reasons)
        ids=tuple(x.object_id for x in selection.selected); contents=tuple(x.content for x in selection.selected); used=sum(len(x.content) for x in selection.selected)
        return finish(Decision.PASS,ids,contents,selection.receipt_sha256,used,selection.reasons)
    def latest_validated_score(self,chat_id:str):
        self.verify()
        row=self.conn.execute('''SELECT r.score_s FROM records r JOIN status_events e ON e.event_seq=(SELECT max(e2.event_seq) FROM status_events e2 WHERE e2.record_id=r.record_id) WHERE e.status='VALIDATED' AND r.chat_id=? AND r.score_s IS NOT NULL ORDER BY e.event_seq DESC LIMIT 1''',(chat_id,)).fetchone(); return None if not row else row[0]


def sliding_context(turns:Sequence[str], *, max_chars:int)->tuple[str,...]:
    if max_chars<0: raise ValueError
    out=[]; used=0
    for t in reversed(turns):
        if used+len(t)>max_chars: break
        out.append(t); used+=len(t)
    return tuple(reversed(out))
