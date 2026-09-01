from __future__ import annotations

import hashlib, json, re, unicodedata
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Iterable, Mapping, Sequence
from tolerance_skill import Decision

COMPONENT_ID='ZORAN_FRAME_SEARCH'
VERSION='10.0.0'


def _norm(s:str)->str:
    s=unicodedata.normalize('NFKD', s.lower())
    s=''.join(c for c in s if not unicodedata.combining(c))
    return ' '.join(re.findall(r'[a-z0-9]+', s))

def _tokens(s:str)->set[str]: return set(_norm(s).split())

@dataclass(frozen=True)
class FrameDefinition:
    frame_id:str
    label:str
    keywords:tuple[str,...]
    parent_id:str|None=None
    required_terms:tuple[str,...]=()
    excluded_terms:tuple[str,...]=()
    priority:int=0
    proxies:tuple[str,...]=()

    def __post_init__(self):
        for name in ('keywords','required_terms','excluded_terms','proxies'):
            object.__setattr__(self,name,tuple(getattr(self,name)))

@dataclass(frozen=True)
class FrameSelection:
    decision:Decision
    selected:tuple[str,...]
    scores:Mapping[str,int]
    reasons:tuple[str,...]
    receipt_sha256:str

class FrameSearchEngine:
    def __init__(self, frames:Sequence[FrameDefinition]):
        ids=[f.frame_id for f in frames]
        if len(ids)!=len(set(ids)) or any(not x for x in ids): raise ValueError('frame ids must be unique/nonempty')
        self.frames=tuple(frames)
        idset=set(ids)
        for f in frames:
            if f.parent_id and f.parent_id not in idset: raise ValueError('unknown parent')
            if not f.label.strip() or not isinstance(f.priority,int) or isinstance(f.priority,bool):raise ValueError('invalid frame definition')
        frame_map={f.frame_id:f for f in frames}
        for fid in ids:
            seen=set(); current=fid
            while current:
                if current in seen:raise ValueError('frame parent cycle')
                seen.add(current); current=frame_map[current].parent_id

    def search(self, text:str, *, evidence_terms:Iterable[str]=(), min_score:int=1, max_frames:int|None=None)->FrameSelection:
        evidence=tuple(evidence_terms)
        request_sha=hashlib.sha256(json.dumps({'text':text,'evidence_terms':evidence,'min_score':min_score,'max_frames':max_frames,'frames':[f.__dict__ for f in self.frames]},sort_keys=True,separators=(',',':'),ensure_ascii=False,default=repr).encode()).hexdigest()
        finish=lambda decision,selected,scores,reasons:self._finish(decision,selected,scores,reasons,request_sha)
        if not isinstance(text,str) or not text.strip(): return finish(Decision.RETRY,(),{},('FRAME_INPUT_MISSING',))
        if not isinstance(min_score,int) or isinstance(min_score,bool):return finish(Decision.VETO,(),{},('MIN_SCORE_INVALID',))
        if max_frames is not None and (not isinstance(max_frames,int) or isinstance(max_frames,bool) or max_frames<1):return finish(Decision.VETO,(),{},('MAX_FRAMES_INVALID',))
        if any(not isinstance(x,str) for x in evidence):return finish(Decision.RETRY,(),{},('EVIDENCE_TERM_INVALID',))
        corpus=' '.join(_norm(x) for x in (text,)+evidence)
        present=lambda term:bool(_norm(term)) and f' {_norm(term)} ' in f' {corpus} '
        scores={}
        for f in self.frames:
            if any(present(x) for x in f.excluded_terms): continue
            required=tuple(f.required_terms)
            if required and not all(present(x) for x in required): continue
            matched=sum(present(x) for x in f.keywords)
            if matched==0 and not required:
                continue
            score=matched*10 + len(required)*20 + f.priority
            if score>=min_score: scores[f.frame_id]=score
        if not scores: return finish(Decision.RETRY,(),{},('NO_FRAME_MEASURED',))
        ordered=sorted(scores, key=lambda k:(-scores[k],k))
        if max_frames is not None:
            ordered=ordered[:max_frames]
        # include ancestors for coherence of hierarchy
        frame_map={f.frame_id:f for f in self.frames}
        selected=list(ordered)
        for fid in list(selected):
            p=frame_map[fid].parent_id
            while p:
                if p not in selected: selected.append(p)
                p=frame_map[p].parent_id
        selected=tuple(sorted(set(selected), key=lambda x:(0 if x in ordered else 1, ordered.index(x) if x in ordered else x)))
        return finish(Decision.PASS,selected,scores,('FRAMES_SELECTED',))

    def _finish(self,d,s,sc,r,request_sha):
        payload={'component':COMPONENT_ID,'version':VERSION,'request_sha256':request_sha,'decision':d.value,'selected':list(s),'scores':dict(sorted(sc.items())),'reasons':list(r)}
        h=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        return FrameSelection(d,tuple(s),MappingProxyType(dict(sc)),tuple(r),h)
