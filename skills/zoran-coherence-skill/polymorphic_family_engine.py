from __future__ import annotations
import hashlib,json,re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any,Sequence
from tolerance_skill import TOLERANCE_FAMILIES
PASS='PASS'; RETRY='RETRY'
@dataclass(frozen=True)
class FamilySpec:
 family_id:str; title:str; frame_triggers:tuple[str,...]=(); risk_triggers:tuple[str,...]=(); keyword_triggers:tuple[str,...]=(); required_evidence:tuple[str,...]=(); calibration_required:bool=True; hard_veto:bool=False
 def __post_init__(self):
  for name in ('frame_triggers','risk_triggers','keyword_triggers','required_evidence'):
   object.__setattr__(self,name,tuple(getattr(self,name)))
@dataclass(frozen=True)
class SelectionContext:
 text:str; domain_id:str; object_type:str; frames:tuple[str,...]; risk_tags:tuple[str,...]=(); available_evidence:tuple[str,...]=(); calibrated_families:tuple[str,...]=()
 def __post_init__(self):
  for name in ('frames','risk_tags','available_evidence','calibrated_families'):
   object.__setattr__(self,name,tuple(getattr(self,name)))
@dataclass(frozen=True)
class FamilyActivation:
 family_id:str; source:str; status:str; reason:str; required_evidence:tuple[str,...]; hard_veto:bool
@dataclass(frozen=True)
class FamilyPlan:
 core_families:tuple[str,...]; extensions:tuple[FamilyActivation,...]; total_active:int; status:str; receipt_sha256:str
 def as_dict(self):return {'core_families':list(self.core_families),'extensions':[x.__dict__ for x in self.extensions],'total_active':self.total_active,'status':self.status,'receipt_sha256':self.receipt_sha256}
DEFAULT_EXTENSION_FAMILIES=(
 FamilySpec('prompt_quality','Qualité du prompt',risk_triggers=('ambiguity','prompt_noise','prompt_conflict'),keyword_triggers=('instruction','consigne','prompt','objectif'),required_evidence=('prompt_contract',)),
 FamilySpec('contract_coherence','Cohérence demande / critères',risk_triggers=('hidden_rubric','contract_mismatch'),keyword_triggers=('critère','rubrique','validation','contrat'),required_evidence=('evaluation_contract',),hard_veto=True),
 FamilySpec('context_continuity','Continuité de contexte',risk_triggers=('context_drift','parallel_topic'),frame_triggers=('temporal','project','memory'),required_evidence=('context_receipt',),hard_veto=True),
 FamilySpec('source_independence','Indépendance des sources',risk_triggers=('factual','source_copy_risk'),frame_triggers=('proof','science'),required_evidence=('source_provenance',),hard_veto=True),
 FamilySpec('source_freshness','Fraîcheur des sources',risk_triggers=('current_fact','temporal'),frame_triggers=('temporal',),required_evidence=('source_timestamp',),hard_veto=True),
 FamilySpec('physical_constraints','Contraintes physiques',risk_triggers=('physical','engineering','safety'),frame_triggers=('physics','safety','resources'),required_evidence=('physical_law_receipt',),hard_veto=True),
 FamilySpec('coherence_kinematics','Cinématique de cohérence',risk_triggers=('trajectory','progress'),frame_triggers=('temporal','trajectory'),required_evidence=('kinematics_receipt',)),
 FamilySpec('probable_future','Futur probable',risk_triggers=('forecast','future'),frame_triggers=('future','temporal'),required_evidence=('past_state_receipt','frame_proxy_receipt')),
 FamilySpec('memory_integrity','Intégrité mémoire',risk_triggers=('memory','cross_session'),frame_triggers=('memory','project'),required_evidence=('zmos_receipt',),hard_veto=True),
 FamilySpec('terminal_completion','Clôture terminale indépendante',risk_triggers=('completion','delivery','validated'),frame_triggers=('terminal_condition','proof'),required_evidence=('terminal_controller_receipt',),hard_veto=True),
)
def _norm(t):return ' '.join(re.findall(r'[a-z0-9à-ÿ_-]+',t.casefold()))
def _sha(v:Any):return hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
class PolymorphicFamilyEngine:
 def __init__(self,specs:Sequence[FamilySpec]=DEFAULT_EXTENSION_FAMILIES):
  registry={}
  for s in specs:
   if not s.family_id or s.family_id in TOLERANCE_FAMILIES or s.family_id in registry:raise ValueError('INVALID_OR_DUPLICATE_EXTENSION_FAMILY')
   if any(not isinstance(x,str) or not x.strip() for x in s.frame_triggers+s.risk_triggers+s.keyword_triggers+s.required_evidence):raise ValueError('INVALID_EXTENSION_FAMILY')
   if not isinstance(s.calibration_required,bool) or not isinstance(s.hard_veto,bool):raise ValueError('INVALID_EXTENSION_FAMILY')
   registry[s.family_id]=s
  self.registry=MappingProxyType(registry)
 def select(self,c:SelectionContext):
  text=_norm(' '.join((c.text,c.domain_id,c.object_type))); frames={x.casefold() for x in c.frames}; risks={x.casefold() for x in c.risk_tags}; ev=set(c.available_evidence); cal=set(c.calibrated_families); ext=[]
  for fid in sorted(self.registry):
   s=self.registry[fid]; reasons=[]
   if {x.casefold() for x in s.frame_triggers}&frames:reasons.append('FRAME')
   if {x.casefold() for x in s.risk_triggers}&risks:reasons.append('RISK')
   if any(_norm(k) in text for k in s.keyword_triggers):reasons.append('TEXT')
   if not reasons:continue
   missing=[x for x in s.required_evidence if x not in ev]
   if s.calibration_required and fid not in cal:status=RETRY; reason='CALIBRATION_REQUIRED:'+ '+'.join(reasons)
   elif missing:status=RETRY; reason='EVIDENCE_REQUIRED:'+','.join(missing)
   else:status=PASS; reason='ACTIVATED_BY:'+ '+'.join(reasons)
   ext.append(FamilyActivation(fid,'POLYMORPHIC',status,reason,s.required_evidence,s.hard_veto))
  status=RETRY if any(x.status!=PASS for x in ext) else PASS
  p={'request':{'text':c.text,'domain_id':c.domain_id,'object_type':c.object_type,'frames':list(c.frames),'risk_tags':list(c.risk_tags),'available_evidence':list(c.available_evidence),'calibrated_families':list(c.calibrated_families)},'core':list(TOLERANCE_FAMILIES),'extensions':[x.__dict__ for x in ext],'total':len(TOLERANCE_FAMILIES)+len(ext),'status':status}
  return FamilyPlan(tuple(TOLERANCE_FAMILIES),tuple(ext),p['total'],status,_sha(p))
 def require_registered(self,ids):
  unknown=sorted(set(ids)-set(TOLERANCE_FAMILIES)-set(self.registry))
  if unknown:raise ValueError('UNREGISTERED_FAMILY:'+','.join(unknown))
  return tuple(ids)
