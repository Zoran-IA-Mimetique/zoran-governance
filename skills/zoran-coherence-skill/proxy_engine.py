from __future__ import annotations
import hashlib,json
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from math import isfinite
from types import MappingProxyType
from typing import Mapping
from tolerance_skill import Decision

COMPONENT_ID='ZORAN_PROXY_ENGINE'; VERSION='10.0.0'
PROXY_IDS=('beta','dphi','T','sigma')

def _q(v): return v if isinstance(v,Fraction) else Fraction(Decimal(str(v)))
def _fmt(v:Fraction)->str: return str(v.numerator) if v.denominator==1 else f'{v.numerator}/{v.denominator}'

@dataclass(frozen=True)
class ProxyDefinition:
    proxy_id:str
    meaning:str
    minimum:float|None=None
    maximum:float|None=None

@dataclass(frozen=True)
class ProxyMeasurement:
    proxy_id:str
    value:float
    evidence_id:str
    measured:bool=True

@dataclass(frozen=True)
class ProxyEvaluation:
    decision:Decision
    proxies:Mapping[str,str]
    score_s:str|None
    reasons:tuple[str,...]
    receipt_sha256:str

class ProxyEngine:
    def __init__(self, definitions:Mapping[str,ProxyDefinition]|None=None):
        supplied=definitions or {
          'beta':ProxyDefinition('beta','direction/alignement',0,10),
          'dphi':ProxyDefinition('dphi','coherence interne',0,10),
          'T':ProxyDefinition('T','contradictions',0,10),
          'sigma':ProxyDefinition('sigma','ambiguite/incertitude',0,10),
        }
        self.definitions=MappingProxyType(dict(supplied))
        if set(self.definitions)!=set(PROXY_IDS): raise ValueError('exact four canonical proxies required')
        for pid,spec in self.definitions.items():
            if spec.proxy_id!=pid or not spec.meaning.strip() or spec.minimum is None or spec.maximum is None:raise ValueError(f'invalid proxy definition:{pid}')
            try:low,high=_q(spec.minimum),_q(spec.maximum)
            except Exception:raise ValueError(f'invalid proxy bounds:{pid}')
            if not isfinite(float(low)) or not isfinite(float(high)) or low<0 or high>10 or low>high:raise ValueError(f'invalid proxy bounds:{pid}')

    def evaluate(self, measurements:Mapping[str,ProxyMeasurement])->ProxyEvaluation:
        request_sha=hashlib.sha256(json.dumps({'definitions':{k:v.__dict__ for k,v in sorted(self.definitions.items())},'measurements':{k:v.__dict__ for k,v in sorted(measurements.items())}},sort_keys=True,separators=(',',':'),allow_nan=True,default=repr).encode()).hexdigest()
        finish=lambda decision,proxies,score,reasons:self._finish(decision,proxies,score,reasons,request_sha)
        if set(measurements)!=set(PROXY_IDS): return finish(Decision.RETRY,{},None,('PROXY_SET_INCOMPLETE',))
        vals={}
        for pid in PROXY_IDS:
            m=measurements[pid]
            if m.proxy_id!=pid or m.measured is not True or not isinstance(m.evidence_id,str) or not m.evidence_id.strip(): return finish(Decision.RETRY,{},None,(f'PROXY_TRACE_PENDING:{pid}',))
            try: q=_q(m.value)
            except Exception: return finish(Decision.RETRY,{},None,(f'PROXY_INVALID:{pid}',))
            if isinstance(m.value,bool) or not isfinite(float(q)): return finish(Decision.RETRY,{},None,(f'PROXY_INVALID:{pid}',))
            spec=self.definitions[pid]
            if spec.minimum is not None and q<_q(spec.minimum): return finish(Decision.VETO,{},None,(f'PROXY_BELOW_MIN:{pid}',))
            if spec.maximum is not None and q>_q(spec.maximum): return finish(Decision.VETO,{},None,(f'PROXY_ABOVE_MAX:{pid}',))
            vals[pid]=q
        # Internal canonical computation. Surface modules must not reveal this formula.
        score=(vals['beta']*vals['dphi'])/(Fraction(1)+vals['T']+vals['sigma'])
        if score<0 or score>100:return finish(Decision.VETO,{},None,('SCORE_OUT_OF_CANONICAL_RANGE',))
        return finish(Decision.PASS,{k:_fmt(v) for k,v in vals.items()},_fmt(score),('PROXIES_MEASURED',))

    def _finish(self,d,p,s,r,request_sha):
        payload={'component':COMPONENT_ID,'version':VERSION,'request_sha256':request_sha,'decision':d.value,'proxies':dict(p),'score_s':s,'reasons':list(r)}
        h=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        return ProxyEvaluation(d,dict(p),s,tuple(r),h)
