from __future__ import annotations
import hashlib,json
from dataclasses import dataclass
from typing import Callable,Sequence
from parallel_context_guard import MemoryFragment,ParallelContextGuard,PASS,RETRY

MemoryProvider=Callable[[str,str],Sequence[MemoryFragment]]

@dataclass(frozen=True)
class MemoryContextDecision:
    status:str; code:str; receipt_sha256:str; requires_external_grounding:bool


def _decision(status,code,inner_receipt,requires_external_grounding,*,doubt,question,candidate,active_project_id,provider_outcome):
    request={'doubt':doubt,'question_sha256':hashlib.sha256(question.encode()).hexdigest() if isinstance(question,str) else hashlib.sha256(repr(question).encode()).hexdigest(),'candidate_sha256':hashlib.sha256(candidate.encode()).hexdigest() if isinstance(candidate,str) else hashlib.sha256(repr(candidate).encode()).hexdigest(),'active_project_id':active_project_id,'provider_outcome':provider_outcome}
    payload={'request':request,'status':status,'code':code,'inner_receipt_sha256':inner_receipt,'requires_external_grounding':requires_external_grounding}
    receipt=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':'),ensure_ascii=False,default=repr).encode()).hexdigest()
    return MemoryContextDecision(status,code,receipt,requires_external_grounding)


def check_memory_context_on_doubt(*,doubt:bool,question:str,candidate:str,memory_provider:MemoryProvider|None,active_project_id:str|None=None,guard:ParallelContextGuard|None=None)->MemoryContextDecision:
    g=guard or ParallelContextGuard()
    if not doubt:
        r=g.evaluate(doubt=False,question=question,candidate=candidate,fragments=(),active_project_id=active_project_id)
        return _decision(r.status,r.code,r.receipt_sha256,r.requires_external_grounding,doubt=doubt,question=question,candidate=candidate,active_project_id=active_project_id,provider_outcome='NOT_REQUIRED')
    if memory_provider is None:
        r=g.evaluate(doubt=True,question=question,candidate=candidate,fragments=(),active_project_id=active_project_id)
        return _decision(r.status,r.code,r.receipt_sha256,True,doubt=doubt,question=question,candidate=candidate,active_project_id=active_project_id,provider_outcome='ABSENT')
    try:
        fragments=tuple(memory_provider(question,candidate))
    except Exception:
        # Provider failure is not converted to evidence.
        r=g.evaluate(doubt=True,question=question,candidate=candidate,fragments=(),active_project_id=active_project_id)
        return _decision(RETRY,'HOST_MEMORY_QUERY_FAILED',r.receipt_sha256,True,doubt=doubt,question=question,candidate=candidate,active_project_id=active_project_id,provider_outcome='ERROR')
    r=g.evaluate(doubt=True,question=question,candidate=candidate,fragments=fragments,active_project_id=active_project_id)
    return _decision(r.status,r.code,r.receipt_sha256,r.requires_external_grounding,doubt=doubt,question=question,candidate=candidate,active_project_id=active_project_id,provider_outcome='RETURNED')
