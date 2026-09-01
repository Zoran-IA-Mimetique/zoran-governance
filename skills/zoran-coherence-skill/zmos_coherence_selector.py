"""Deterministic coherence-first selector for ZMOS memory objects.

Eligibility is established by explicit object relevance metadata. Among eligible
objects, recall is ordered by measured coherence, not by raw text similarity.
Relevant contradictory objects are preserved and surfaced as contradictory.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Sequence
from tolerance_skill import Decision

MODALITIES=('PROUVE','SUPPORTE','DEDUIT','INCERTAIN','CONTRADICTOIRE','INCONNU','RETRY')
_MODALITY_RANK={m:i for i,m in enumerate(reversed(MODALITIES))}

@dataclass(frozen=True)
class ZmosObject:
    object_id:str
    content:str
    modality:str
    relevance:int
    coherence_s:str|None
    provenance_sha256:str

@dataclass(frozen=True)
class SelectedMemory:
    object_id:str
    content:str
    modality:str
    coherence_s:str|None
    relevance:int
    provenance_sha256:str

@dataclass(frozen=True)
class SelectionReceipt:
    decision:Decision
    selected:tuple[SelectedMemory,...]
    reasons:tuple[str,...]
    receipt_sha256:str


def _score(value:str|None):
    if value is None:return None
    try:
        x=Decimal(value)
    except (InvalidOperation,ValueError):return None
    if not x.is_finite():return None
    return x


def _sha(payload):
    raw=json.dumps(payload,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


class ZmosCoherenceSelector:
    def select(self, objects:Sequence[ZmosObject], *, max_objects:int|None=None, max_chars:int|None=None)->SelectionReceipt:
        items=tuple(objects)
        object_binding=[{'object_id':o.object_id,'content_sha256':hashlib.sha256(o.content.encode()).hexdigest(),'modality':o.modality,'relevance':o.relevance,'coherence_s':o.coherence_s,'provenance_sha256':o.provenance_sha256} if isinstance(o,ZmosObject) and isinstance(o.content,str) else {'invalid_input':repr(o)} for o in items]
        object_binding.sort(key=lambda item:json.dumps(item,sort_keys=True,separators=(',',':'),ensure_ascii=False,default=repr))
        request_sha=_sha({'objects':object_binding,'max_objects':max_objects,'max_chars':max_chars})
        finish=lambda d,selected,reasons:self._finish(d,selected,reasons,request_sha=request_sha,max_objects=max_objects,max_chars=max_chars)
        if max_objects is not None and (not isinstance(max_objects,int) or isinstance(max_objects,bool) or max_objects<0):return finish(Decision.VETO,(),('INVALID_MAX_OBJECTS',))
        if max_chars is not None and (not isinstance(max_chars,int) or isinstance(max_chars,bool) or max_chars<0):return finish(Decision.VETO,(),('INVALID_MAX_CHARS',))
        if any(not isinstance(o,ZmosObject) or not isinstance(o.object_id,str) or not isinstance(o.content,str) or not isinstance(o.modality,str) or not isinstance(o.provenance_sha256,str) for o in items):return finish(Decision.RETRY,(),('OBJECT_INPUT_INVALID',))
        object_ids=[o.object_id for o in items]
        if len(object_ids)!=len(set(object_ids)):return finish(Decision.VETO,(),('DUPLICATE_OBJECT_ID',))
        eligible=[]
        for o in items:
            if not o.object_id.strip() or not o.content:return finish(Decision.RETRY,(),(f'OBJECT_ID_OR_CONTENT_MISSING:{o.object_id}',))
            if o.modality not in MODALITIES:return finish(Decision.RETRY,(),(f'UNKNOWN_MODALITY:{o.object_id}',))
            if not isinstance(o.relevance,int) or isinstance(o.relevance,bool):return finish(Decision.RETRY,(),(f'RELEVANCE_INVALID:{o.object_id}',))
            if o.relevance<=0:continue
            if len(o.provenance_sha256)!=64 or any(c not in '0123456789abcdef' for c in o.provenance_sha256):return finish(Decision.RETRY,(),(f'PROVENANCE_TRACE_PENDING:{o.object_id}',))
            cs=_score(o.coherence_s)
            if o.coherence_s is not None and cs is None:return finish(Decision.RETRY,(),(f'COHERENCE_SCORE_INVALID:{o.object_id}',))
            if cs is not None and not (Decimal('0')<=cs<=Decimal('100')):return finish(Decision.RETRY,(),(f'COHERENCE_SCORE_OUT_OF_RANGE:{o.object_id}',))
            # measured coherence first; trace_pending remains eligible but comes last and stays labelled.
            measured=1 if cs is not None else 0
            eligible.append((o,measured,cs if cs is not None else Decimal('-Infinity')))
        eligible.sort(key=lambda t:(-t[1],-t[2],-_MODALITY_RANK[t[0].modality],-t[0].relevance,t[0].object_id))

        selected=[]; used=0
        def can_add(o):
            if max_objects is not None and len(selected)>=max_objects:return False
            if max_chars is not None and used+len(o.content)>max_chars:return False
            return True
        for o,_,_ in eligible:
            if can_add(o):
                selected.append(o); used+=len(o.content)

        # A relevant contradiction must not disappear behind more coherent recalls.
        contradictions=[t[0] for t in eligible if t[0].modality=='CONTRADICTOIRE']
        if contradictions and all(o.modality!='CONTRADICTOIRE' for o in selected):
            c=max(contradictions,key=lambda o:(o.relevance,o.object_id))
            if max_objects is None or max_objects>0:
                while selected and ((max_objects is not None and len(selected)>=max_objects) or (max_chars is not None and used+len(c.content)>max_chars)):
                    dropped=selected.pop(); used-=len(dropped.content)
                if can_add(c):selected.append(c); used+=len(c.content)

        if contradictions and all(o.modality!='CONTRADICTOIRE' for o in selected):
            return finish(Decision.RETRY,(),('RELEVANT_CONTRADICTION_EXCLUDED_BY_BUDGET',))

        out=tuple(SelectedMemory(o.object_id,o.content,o.modality,o.coherence_s,o.relevance,o.provenance_sha256) for o in selected)
        reasons=['COHERENCE_ORDERED_RECALL']
        if not eligible:reasons.append('EMPTY_RECALL_OBSERVED')
        if any(x.modality=='CONTRADICTOIRE' for x in out):reasons.append('CONTRADICTORY_MEMORY_SURFACED')
        if any(x.coherence_s is None for x in out):reasons.append('TRACE_PENDING_MEMORY_SURFACED_AS_TRACE_PENDING')
        if len(out)<len(eligible):reasons.append('CONTEXT_BUDGET_TRUNCATED_RECALL')
        return finish(Decision.PASS,out,tuple(reasons))

    def _finish(self,d,selected,reasons,*,request_sha,max_objects=None,max_chars=None):
        payload={'request_sha256':request_sha,'decision':d.value,'limits':{'max_objects':max_objects,'max_chars':max_chars},'selected':[{'object_id':x.object_id,'content_sha256':hashlib.sha256(x.content.encode()).hexdigest(),'modality':x.modality,'coherence_s':x.coherence_s,'relevance':x.relevance,'provenance_sha256':x.provenance_sha256} for x in selected],'reasons':list(reasons)}
        return SelectionReceipt(d,tuple(selected),tuple(reasons),_sha(payload))
