from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from math import isfinite
from typing import Sequence

from tolerance_skill import Decision


def _q(value):
    if isinstance(value, Fraction):
        return value
    return Fraction(Decimal(str(value)))


def _safe_q(value):
    try:
        q=_q(value)
        if not isfinite(float(q)):
            return None
        return q
    except (ValueError, TypeError, ArithmeticError, InvalidOperation, OverflowError):
        return None


def _fmt(value):
    if value is None:
        return None
    return str(value.numerator) if value.denominator==1 else f'{value.numerator}/{value.denominator}'


@dataclass(frozen=True)
class CoherencePoint:
    t:int
    score_s:float
    validated:bool
    frame_ids:tuple[str,...]
    proxy_ids:tuple[str,...]


@dataclass(frozen=True)
class DynamicsEvaluation:
    decision:Decision
    velocity:str|None
    acceleration:str|None
    projected_s:str|None
    interval_low:str|None
    interval_high:str|None
    reasons:tuple[str,...]
    receipt_sha256:str


class CoherenceDynamics:
    def evaluate(self, history:Sequence[CoherencePoint], *, horizon:int=1)->DynamicsEvaluation:
        request_sha=hashlib.sha256(json.dumps({'history':[p.__dict__ for p in history],'horizon':horizon},sort_keys=True,separators=(',',':'),allow_nan=True,default=repr).encode()).hexdigest()
        finish=lambda decision,velocity,acceleration,projected,low,high,reasons:self._f(decision,velocity,acceleration,projected,low,high,reasons,request_sha)
        if not isinstance(horizon,int) or isinstance(horizon,bool) or horizon<1:
            return finish(Decision.VETO,None,None,None,None,None,('INVALID_HORIZON',))
        if any(not isinstance(p.validated,bool) for p in history):
            return finish(Decision.RETRY,None,None,None,None,None,('VALIDATION_FLAG_INVALID',))
        pts=[p for p in history if p.validated]
        if len(pts)<2:
            return finish(Decision.RETRY,None,None,None,None,None,('INSUFFICIENT_COHERENT_PAST',))
        if any(not isinstance(p.t,int) or isinstance(p.t,bool) for p in pts):
            return finish(Decision.RETRY,None,None,None,None,None,('TIME_INVALID',))
        if any(_safe_q(p.score_s) is None or not (0<=_safe_q(p.score_s)<=100) for p in pts):
            return finish(Decision.RETRY,None,None,None,None,None,('COHERENCE_SCORE_INVALID',))
        if any(not p.frame_ids or not p.proxy_ids for p in pts):
            return finish(Decision.RETRY,None,None,None,None,None,('FRAME_OR_PROXY_BINDING_MISSING',))
        if any(len(set(p.frame_ids))!=len(p.frame_ids) or len(set(p.proxy_ids))!=len(p.proxy_ids) for p in pts):
            return finish(Decision.VETO,None,None,None,None,None,('DUPLICATE_FRAME_OR_PROXY_ID',))

        pts=sorted(pts,key=lambda p:p.t)
        if len({p.t for p in pts})!=len(pts):
            return finish(Decision.VETO,None,None,None,None,None,('DUPLICATE_TIME',))
        base_frames=set(pts[-1].frame_ids)
        base_proxies=set(pts[-1].proxy_ids)
        if any(set(p.frame_ids)!=base_frames or set(p.proxy_ids)!=base_proxies for p in pts):
            return finish(Decision.RETRY,None,None,None,None,None,('INCOMPARABLE_FRAMES_OR_PROXIES',))

        a,b=pts[-2],pts[-1]
        dt=b.t-a.t
        if dt<=0:
            return finish(Decision.VETO,None,None,None,None,None,('NON_MONOTONIC_TIME',))
        aq=_safe_q(a.score_s); bq=_safe_q(b.score_s)
        assert aq is not None and bq is not None
        velocity=(bq-aq)/dt

        acceleration=None
        if len(pts)>=3:
            p=pts[-3]
            pq=_safe_q(p.score_s)
            assert pq is not None
            prev_dt=a.t-p.t
            if prev_dt<=0:
                return finish(Decision.VETO,None,None,None,None,None,('NON_MONOTONIC_TIME',))
            previous_velocity=(aq-pq)/prev_dt
            acceleration=(velocity-previous_velocity)/dt

        projected=bq+velocity*horizon
        residual=[]
        if len(pts)>=3:
            for i in range(2,len(pts)):
                p0,p1,p2=pts[i-2:i+1]
                q0=_safe_q(p0.score_s); q1=_safe_q(p1.score_s); q2=_safe_q(p2.score_s)
                assert q0 is not None and q1 is not None and q2 is not None
                local_dt=p1.t-p0.t
                step_dt=p2.t-p1.t
                if local_dt<=0 or step_dt<=0:
                    return finish(Decision.VETO,None,None,None,None,None,('NON_MONOTONIC_TIME',))
                local_velocity=(q1-q0)/local_dt
                prediction=q1+local_velocity*step_dt
                residual.append(abs(q2-prediction))
        band=max(residual) if residual else Fraction(0)
        low,high=projected-band,projected+band
        if projected<0 or projected>100 or low<0 or high>100:
            return finish(Decision.RETRY,velocity,acceleration,projected,low,high,('PROJECTION_OUT_OF_CANONICAL_RANGE',))
        return finish(
            Decision.PASS,velocity,acceleration,projected,low,high,
            ('KINEMATICS_MEASURED','FUTURE_PROBABLE_BOUNDED'),
        )

    def _f(self,decision,velocity,acceleration,projected,low,high,reasons,request_sha):
        payload={
            'request_sha256':request_sha,
            'decision':decision.value,
            'velocity':_fmt(velocity),
            'acceleration':_fmt(acceleration),
            'projected_s':_fmt(projected),
            'interval_low':_fmt(low),
            'interval_high':_fmt(high),
            'reasons':list(reasons),
        }
        receipt=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
        return DynamicsEvaluation(decision,payload['velocity'],payload['acceleration'],payload['projected_s'],payload['interval_low'],payload['interval_high'],tuple(reasons),receipt)
