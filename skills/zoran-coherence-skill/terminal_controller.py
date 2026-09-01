from __future__ import annotations
import hashlib, json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

PASS='PASS'; FAIL='FAIL'; RETRY='RETRY'
REQUIRED_CONTROL_IDS=(
    'session_activation','zmos_pre_retrieval','zmos_trace_resolution_if_required','k3_pre',
    'candidate_17d_gate','semantic_non_conflation_gate','semantic_speech_gate','claim_evidence_gate','phenomenal_coherence_gate','robot_handoff_gate',
    'k3_post','zmos_post_append','tests_if_required',
    'external_alarm_surface_if_required',
)

def _canon(v:Any)->bytes:return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def _sha(v:Any)->str:return hashlib.sha256(_canon(v)).hexdigest()
def _valid_sha(v:str|None)->bool:return isinstance(v,str) and len(v)==64 and all(c in '0123456789abcdef' for c in v)

@dataclass(frozen=True)
class ControlEvidence:
    control_id:str; required:bool; observed:bool; status:str; receipt_sha256:str|None; detail:str=''

@dataclass(frozen=True)
class RecoveryDirective:
    owner:str; action:str; reason:str; connector:str|None=None; retry_full_cycle:bool=True
    def as_dict(self):return self.__dict__

@dataclass(frozen=True)
class TerminalVerdict:
    status:str; reasons:tuple[str,...]; checked_controls:tuple[str,...]; recovery:tuple[RecoveryDirective,...]; receipt_sha256:str
    def as_dict(self):
        return {'component':'zoran.terminal-controller-v1','version':'1.0.0','status':self.status,'reasons':list(self.reasons),'checked_controls':list(self.checked_controls),'recovery':[x.as_dict() for x in self.recovery],'receipt_sha256':self.receipt_sha256}

def _recovery(code:str)->RecoveryDirective:
    u=code.upper()
    if 'GITHUB' in u or 'REPOSITORY' in u or 'CI_' in u:return RecoveryDirective('CONNECTOR','Activer ou rétablir l’accès GitHub nécessaire, puis rejouer le cycle.',code,'GitHub')
    if 'ZMOS' in u or 'STORAGE' in u or 'DISK' in u:return RecoveryDirective('USER','Autoriser l’accès au stockage ZMOS ou fournir l’emplacement persistant demandé, puis rejouer.',code)
    if 'SOURCE' in u or 'TRACE' in u or 'WEB' in u:return RecoveryDirective('LLM','Chercher une preuve externe fiable, comparer à la demande et au candidat, puis reconstruire la sortie.',code)
    if 'PERMISSION' in u or 'AUTH' in u or 'ACCESS' in u:return RecoveryDirective('USER','Accorder l’accès minimal demandé ou activer le connecteur proposé, puis rejouer.',code)
    return RecoveryDirective('LLM','Diagnostiquer la cause exacte, corriger si possible, puis rejouer le cycle complet.',code)

class TerminalController:
    def evaluate(self,evidence:Sequence[ControlEvidence],*,trusted_receipts:Mapping[str,str]|None=None)->TerminalVerdict:
        items=tuple(evidence); reasons=[]; checked=[]; fail=False; unknown=False
        trust=dict(trusted_receipts or {})
        ids=[x.control_id for x in items]
        if any(not isinstance(x,str) or not x.strip() for x in ids):
            reasons.append('CONTROL_ID_MISSING'); fail=True
        duplicate_ids=sorted({x for x in ids if ids.count(x)>1})
        if duplicate_ids:
            reasons.extend(f'DUPLICATE_CONTROL_ID:{x}' for x in duplicate_ids); fail=True
        by={x.control_id:x for x in items}
        for cid in REQUIRED_CONTROL_IDS:
            x=by.get(cid)
            if x is None: reasons.append(f'CONTROL_UNDECLARED:{cid}'); unknown=True; continue
            checked.append(cid)
            if not isinstance(x.required,bool): reasons.append(f'CONTROL_REQUIRED_FLAG_INVALID:{cid}'); unknown=True; continue
            if x.required is not True: reasons.append(f'CONTROL_INTRINSIC_REQUIREMENT_DISABLED:{cid}'); unknown=True; continue
            if not isinstance(x.observed,bool) or not x.observed: reasons.append(f'CONTROL_NOT_OBSERVED:{cid}'); unknown=True; continue
            if not _valid_sha(x.receipt_sha256): reasons.append(f'CONTROL_RECEIPT_INVALID:{cid}'); unknown=True; continue
            if trust.get(cid)!=x.receipt_sha256: reasons.append(f'CONTROL_RECEIPT_UNTRUSTED:{cid}'); unknown=True; continue
            if x.status==FAIL: reasons.append(f'CONTROL_FAIL:{cid}:{x.detail or "UNSPECIFIED"}'); fail=True
            elif x.status == RETRY: reasons.append(f'CONTROL_RETRY:{cid}:{x.detail or "UNSPECIFIED"}'); unknown=True
            elif x.status!=PASS: reasons.append(f'CONTROL_STATUS_INVALID:{cid}:{x.status}'); unknown=True
        for x in items:
            if x.control_id in REQUIRED_CONTROL_IDS: continue
            if not isinstance(x.required,bool): reasons.append(f'EXTRA_CONTROL_REQUIRED_FLAG_INVALID:{x.control_id}'); unknown=True; continue
            if not x.required: continue
            checked.append(x.control_id)
            if not isinstance(x.observed,bool) or not x.observed or not _valid_sha(x.receipt_sha256): reasons.append(f'EXTRA_CONTROL_UNOBSERVED:{x.control_id}'); unknown=True
            elif trust.get(x.control_id)!=x.receipt_sha256: reasons.append(f'EXTRA_CONTROL_RECEIPT_UNTRUSTED:{x.control_id}'); unknown=True
            elif x.status==FAIL: reasons.append(f'EXTRA_CONTROL_FAIL:{x.control_id}:{x.detail or "UNSPECIFIED"}'); fail=True
            elif x.status == RETRY: reasons.append(f'EXTRA_CONTROL_RETRY:{x.control_id}:{x.detail or "UNSPECIFIED"}'); unknown=True
            elif x.status!=PASS: reasons.append(f'EXTRA_CONTROL_STATUS_INVALID:{x.control_id}:{x.status}'); unknown=True
        status=FAIL if fail else (RETRY if unknown else PASS)
        rec=tuple(dict.fromkeys(_recovery(r) for r in reasons)) if reasons else ()
        payload={'component':'zoran.terminal-controller-v2','status':status,'reasons':reasons,'checked_controls':sorted(set(checked)),'trusted_receipts':dict(sorted(trust.items())),'evidence':[x.__dict__ for x in sorted(items,key=lambda x:(x.control_id,x.status,x.detail))],'recovery':[x.as_dict() for x in rec]}
        return TerminalVerdict(status,tuple(reasons),tuple(sorted(set(checked))),rec,_sha(payload))
