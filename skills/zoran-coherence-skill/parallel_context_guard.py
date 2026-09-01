from __future__ import annotations
import hashlib,json,re,unicodedata
from dataclasses import dataclass
from typing import Any,Sequence
PASS='PASS'; FAIL='FAIL'; RETRY='RETRY'
_TOKEN=re.compile(r'[a-z0-9à-ÿ][a-z0-9à-ÿ_-]{1,}',re.I)
_STOP={'avec','dans','pour','sur','une','des','les','est','sont','que','qui','quoi','comment','mais','donc','cette','cela','plus','moins','the','and','for','with','from','this','that','what','how','are'}
def _norm(t):
 t=unicodedata.normalize('NFKD',t.casefold()); t=''.join(c for c in t if not unicodedata.combining(c)); return ' '.join(t.replace('’',"'").split())
def _anchors(t):return frozenset(x for x in _TOKEN.findall(_norm(t)) if x not in _STOP and len(x)>=3)
def _sha(v):return hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
@dataclass(frozen=True)
class MemoryFragment:
 fragment_id:str; source:str; text:str; sha256:str; provenance:str; project_id:str|None=None
@dataclass(frozen=True)
class ParallelContextReceipt:
 status:str; code:str; aligned_fragments:tuple[str,...]; parallel_fragments:tuple[str,...]; memory_sources_observed:tuple[str,...]; requires_external_grounding:bool; receipt_sha256:str
 def as_dict(self):return self.__dict__
def build_memory_fragment(*,fragment_id,source,text,provenance,project_id=None):return MemoryFragment(fragment_id,source,text,hashlib.sha256(text.encode()).hexdigest(),provenance,project_id)
def _valid(f):return bool(f.fragment_id and f.source and f.text.strip() and f.provenance and f.sha256==hashlib.sha256(f.text.encode()).hexdigest())
class ParallelContextGuard:
 def __init__(self,minimum_anchor_overlap=.20):
  if not 0<=minimum_anchor_overlap<=1:raise ValueError('INVALID_MINIMUM_ANCHOR_OVERLAP')
  self.minimum_anchor_overlap=minimum_anchor_overlap
 def evaluate(self,*,doubt,question,candidate,fragments:Sequence[MemoryFragment],active_project_id=None):
  items=tuple(fragments)
  request={'doubt':doubt if isinstance(doubt,bool) else repr(doubt),'question_sha256':hashlib.sha256(question.encode()).hexdigest() if isinstance(question,str) else hashlib.sha256(repr(question).encode()).hexdigest(),'candidate_sha256':hashlib.sha256(candidate.encode()).hexdigest() if isinstance(candidate,str) else hashlib.sha256(repr(candidate).encode()).hexdigest(),'fragments':[f.__dict__ if isinstance(f,MemoryFragment) else repr(f) for f in items],'active_project_id':active_project_id,'minimum_anchor_overlap':self.minimum_anchor_overlap}
  request_sha=_sha(request); finish=lambda status,code,aligned,parallel,sources,external:self._finish(status,code,aligned,parallel,sources,external,request_sha)
  if not isinstance(doubt,bool):return finish(RETRY,'DOUBT_FLAG_INVALID',[],[],[],True)
  if not doubt:return finish(PASS,'NO_DOUBT_NO_MEMORY_ESCALATION',[],[],[],False)
  if not isinstance(question,str) or not isinstance(candidate,str) or not question.strip() or not candidate.strip():return finish(RETRY,'QUESTION_OR_CANDIDATE_MISSING',[],[],[],True)
  if not items:return finish(RETRY,'MEMORY_CONTEXT_NOT_EXPOSED',[],[],[],True)
  q=_anchors(question); aligned=[]; parallel=[]; sources=[]
  for f in items:
   if not isinstance(f,MemoryFragment):return finish(FAIL,'MEMORY_FRAGMENT_RECEIPT_INVALID',aligned,parallel,sources,True)
   sources.append(f.source)
   if not _valid(f):return finish(FAIL,'MEMORY_FRAGMENT_RECEIPT_INVALID',aligned,parallel,sources,True)
   a=_anchors(f.text); union=q|a; overlap=len(q&a)/len(union) if union else 0
   conflict=active_project_id is not None and f.project_id is not None and f.project_id!=active_project_id
   if conflict:parallel.append(f.fragment_id)
   elif overlap>=self.minimum_anchor_overlap:aligned.append(f.fragment_id)
   elif f.source in {'HOST_MEMORY','CHAT_CONTEXT','PROJECT_CHECKLIST'}:parallel.append(f.fragment_id)
  if parallel and not aligned:return finish(RETRY,'PARALLEL_CONTEXT_RISK',aligned,parallel,sources,True)
  if parallel and aligned:return finish(RETRY,'MIXED_CONTEXT_RISK',aligned,parallel,sources,True)
  if aligned:return finish(PASS,'CONTEXT_ALIGNED_MEMORY_NOT_TRUTH_PROOF',aligned,parallel,sources,True)
  return finish(RETRY,'CONTEXT_ALIGNMENT_TRACE_PENDING',aligned,parallel,sources,True)
 def _finish(self,status,code,aligned,parallel,sources,external,request_sha):
  p={'request_sha256':request_sha,'status':status,'code':code,'aligned':sorted(aligned),'parallel':sorted(parallel),'sources':sorted(set(sources)),'external':external}
  return ParallelContextReceipt(status,code,tuple(sorted(aligned)),tuple(sorted(parallel)),tuple(sorted(set(sources))),external,_sha(p))
