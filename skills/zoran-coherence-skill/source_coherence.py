from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence

from tolerance_skill import Decision

COMPONENT_ID='ZORAN_SOURCE_COHERENCE'
VERSION='10.0.0'


def _dt(value:str)->datetime:
    z=value.replace('Z','+00:00')
    parsed=datetime.fromisoformat(z)
    if parsed.tzinfo is None:
        raise ValueError
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class SourceClaim:
    source_id:str
    claim_id:str
    normalized_value:str
    provenance_parent:str|None
    origin_group:str
    observed_at:str
    valid_from:str|None=None
    valid_until:str|None=None
    quality_measured:bool=True


@dataclass(frozen=True)
class SourceEvaluation:
    decision:Decision
    reasons:tuple[str,...]
    independent_origins:int
    receipt_sha256:str


class SourceCoherenceEngine:
    def evaluate(self, claims:Sequence[SourceClaim], *, as_of:str|None=None, require_independent:int=1)->SourceEvaluation:
        request_digest=hashlib.sha256(json.dumps({'claims':[c.__dict__ for c in claims],'as_of':as_of,'require_independent':require_independent},sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()
        finish=lambda decision,reasons,origins:self._finish(decision,reasons,origins,request_digest)
        if not isinstance(require_independent,int) or isinstance(require_independent,bool) or require_independent<1:
            return finish(Decision.VETO,('INVALID_INDEPENDENCE_REQUIREMENT',),0)
        if not claims:
            return finish(Decision.RETRY,('NO_SOURCES',),0)
        ids=[c.source_id for c in claims]
        if any(not x.strip() for x in ids):
            return finish(Decision.RETRY,('SOURCE_ID_MISSING',),0)
        if len(ids)!=len(set(ids)):
            return finish(Decision.VETO,('DUPLICATE_SOURCE_ID',),0)
        byid={c.source_id:c for c in claims}

        try:
            now=_dt(as_of) if as_of else max(_dt(c.observed_at) for c in claims)
        except Exception:
            return finish(Decision.RETRY,('SOURCE_TIME_INVALID',),0)

        for c in claims:
            if not c.claim_id.strip() or not c.normalized_value.strip() or not c.origin_group.strip():
                return finish(Decision.RETRY,(f'SOURCE_FIELDS_INCOMPLETE:{c.source_id}',),0)
            if c.quality_measured is not True:
                return finish(Decision.RETRY,(f'SOURCE_QUALITY_TRACE_PENDING:{c.source_id}',),0)
            try:
                _dt(c.observed_at)
                if c.valid_from and now<_dt(c.valid_from):
                    return finish(Decision.VETO,(f'SOURCE_NOT_YET_VALID:{c.source_id}',),0)
                if c.valid_until and now>_dt(c.valid_until):
                    return finish(Decision.VETO,(f'SOURCE_EXPIRED:{c.source_id}',),0)
            except Exception:
                return finish(Decision.RETRY,(f'SOURCE_TIME_INVALID:{c.source_id}',),0)
            if c.provenance_parent and c.provenance_parent not in byid:
                return finish(Decision.RETRY,(f'PROVENANCE_PARENT_MISSING:{c.source_id}',),0)

        for c in claims:
            seen=set()
            current=c
            while current.provenance_parent:
                if current.source_id in seen:
                    return finish(Decision.VETO,('PROVENANCE_CYCLE',),0)
                seen.add(current.source_id)
                current=byid[current.provenance_parent]

        grouped={}
        for c in claims:
            grouped.setdefault(c.claim_id,set()).add(c.normalized_value.strip())
        contradictions=[cid for cid,values in grouped.items() if len(values)>1]
        provenance_roots=set()
        for claim in claims:
            root=claim
            while root.provenance_parent:
                root=byid[root.provenance_parent]
            provenance_roots.add(root.origin_group)
        origins=len(provenance_roots)
        if contradictions:
            return finish(Decision.VETO,('SOURCE_CONTRADICTION:'+','.join(sorted(contradictions)),),origins)
        if origins<require_independent:
            return finish(Decision.RETRY,('INSUFFICIENT_INDEPENDENT_PROVENANCE_ROOTS',),origins)
        return finish(Decision.PASS,('SOURCES_COHERENT',),origins)

    def _finish(self,decision,reasons,origins,request_digest):
        payload={'component':COMPONENT_ID,'version':VERSION,'request_sha256':request_digest,'decision':decision.value,'reasons':list(reasons),'independent_origins':origins}
        receipt=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
        return SourceEvaluation(decision,tuple(reasons),origins,receipt)
