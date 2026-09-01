from __future__ import annotations

import hashlib
import json
import operator
from dataclasses import dataclass
from math import isfinite
from typing import Sequence

from tolerance_skill import Decision


@dataclass(frozen=True)
class HardLaw:
    law_id:str
    observed:float|None
    op:str
    limit:float
    evidence_id:str|None
    applicable:bool=True
    exclusion_reason:str=''


@dataclass(frozen=True)
class LawEvaluation:
    decision:Decision
    reasons:tuple[str,...]
    receipt_sha256:str


OPS={'<=':operator.le,'<':operator.lt,'>=':operator.ge,'>':operator.gt,'==':operator.eq}


def _finite_number(value)->bool:
    return isinstance(value,(int,float)) and not isinstance(value,bool) and isfinite(float(value))


class LawEngine:
    def evaluate(self,laws:Sequence[HardLaw])->LawEvaluation:
        items=tuple(laws)
        request_sha=hashlib.sha256(json.dumps([x.__dict__ for x in items],sort_keys=True,separators=(',',':'),allow_nan=True,default=repr).encode()).hexdigest()
        finish=lambda decision,reasons:self._f(decision,reasons,request_sha)
        ids=[law.law_id for law in items]
        if any(not isinstance(law_id,str) or not law_id.strip() for law_id in ids):return finish(Decision.RETRY,('LAW_ID_MISSING',))
        if len(ids)!=len(set(ids)):return finish(Decision.VETO,('DUPLICATE_LAW_ID',))
        if not items:return finish(Decision.RETRY,('NO_HARD_LAWS_DECLARED',))
        applicable_count=0
        for law in items:
            if not isinstance(law.applicable,bool):return finish(Decision.RETRY,(f'LAW_APPLICABILITY_INVALID:{law.law_id}',))
            if not law.applicable:
                if not isinstance(law.exclusion_reason,str) or not law.exclusion_reason.strip():return finish(Decision.RETRY,(f'LAW_EXCLUSION_REASON_MISSING:{law.law_id}',))
                continue
            applicable_count+=1
            if law.op not in OPS:
                return finish(Decision.VETO,(f'INVALID_LAW_OPERATOR:{law.law_id}',))
            if law.observed is None or not law.evidence_id:
                return finish(Decision.RETRY,(f'LAW_TRACE_PENDING:{law.law_id}',))
            if not _finite_number(law.observed) or not _finite_number(law.limit):
                return finish(Decision.RETRY,(f'LAW_VALUE_INVALID:{law.law_id}',))
            if not OPS[law.op](law.observed,law.limit):
                return finish(Decision.VETO,(f'HARD_LAW_VIOLATION:{law.law_id}',))
        if not applicable_count:return finish(Decision.RETRY,('NO_APPLICABLE_HARD_LAW',))
        return finish(Decision.PASS,('HARD_LAWS_SATISFIED',))

    def _f(self,decision,reasons,request_sha):
        payload={'request_sha256':request_sha,'decision':decision.value,'reasons':list(reasons)}
        receipt=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
        return LawEvaluation(decision,tuple(reasons),receipt)
