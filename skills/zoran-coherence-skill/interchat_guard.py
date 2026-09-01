from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from math import isfinite

from tolerance_skill import Decision

AMYGDALA_REPO='zorania2025/Zoran-IA-deteriniste'
AMYGDALA_REF='main'
AMYGDALA_PATH='components/amygdala_k3_v1_exact/ZORAN_ETALON_COHERENCE_AMYGDALA_HANDSHAKE_V1_2026-08-20.md'
AMYGDALA_BENCHMARK='ZORAN.COHERENCE.CALIBRATION.BENCHMARK.V1'
AMYGDALA_BLOB='f0821190885e5988e343fd20444f1463c01b9a22'
AMYGDALA_MANIFEST='720a4755b34617d7313dbf7552edc05d59dec9334a4de66a2972b5cd3f159682'


def _safe_q(value):
    try:
        q=Fraction(Decimal(str(value)))
        return q if isfinite(float(q)) else None
    except (ValueError, TypeError, ArithmeticError, InvalidOperation, OverflowError):
        return None


def _fmt(value):
    return str(value.numerator) if value.denominator==1 else f'{value.numerator}/{value.denominator}'


@dataclass(frozen=True)
class AmygdalaPing:
    repository:str
    ref:str
    path:str
    benchmark_id:str
    blob_sha:str
    manifest_sha256:str
    fresh:bool=True


@dataclass(frozen=True)
class InterchatEvaluation:
    decision:Decision
    delta_s:str|None
    drift:bool
    reset_required:bool
    ping_required:bool
    reasons:tuple[str,...]
    user_message:str|None
    receipt_sha256:str


class InterchatGuard:
    def evaluate(self, previous_s:float|None,current_s:float|None, *, previous_frames:tuple[str,...],current_frames:tuple[str,...],previous_proxies:tuple[str,...],current_proxies:tuple[str,...],ping:AmygdalaPing|None=None)->InterchatEvaluation:
        request_sha=self._request_sha({'previous_s':previous_s,'current_s':current_s,'previous_frames':previous_frames,'current_frames':current_frames,'previous_proxies':previous_proxies,'current_proxies':current_proxies,'ping':None if ping is None else ping.__dict__})
        finish=lambda decision,delta,drift,reset,ping_required,reasons,message:self._f(decision,delta,drift,reset,ping_required,reasons,message,request_sha)
        if previous_s is None or current_s is None:
            return finish(Decision.RETRY,None,False,False,False,('INTERCHAT_SCORE_TRACE_PENDING',),None)
        previous_q=_safe_q(previous_s); current_q=_safe_q(current_s)
        if previous_q is None or current_q is None or not (0<=previous_q<=100) or not (0<=current_q<=100):
            return finish(Decision.RETRY,None,False,False,False,('INTERCHAT_SCORE_INVALID',),None)
        if not previous_frames or not current_frames or not previous_proxies or not current_proxies:
            return finish(Decision.RETRY,None,False,False,False,('FRAME_OR_PROXY_BINDING_MISSING',),None)
        if len(set(previous_frames))!=len(previous_frames) or len(set(current_frames))!=len(current_frames) or len(set(previous_proxies))!=len(previous_proxies) or len(set(current_proxies))!=len(current_proxies):
            return finish(Decision.VETO,None,False,False,False,('DUPLICATE_FRAME_OR_PROXY_ID',),None)
        if set(previous_frames)!=set(current_frames) or set(previous_proxies)!=set(current_proxies):
            return finish(Decision.RETRY,None,False,False,False,('INCOMPARABLE_FRAMES_OR_PROXIES',),None)

        delta=current_q-previous_q
        below=current_q<6
        drift=delta<0
        msg=None
        if below:
            msg='Zoran🦋 te propose une réinitialisation de la cohérence de ton IA.'
            if ping is None:
                return finish(Decision.VETO,delta,drift,True,True,('COHERENCE_RESET_REQUIRED','AMYGDALA_PING_REQUIRED'),msg)
            if not self._valid_ping(ping):
                return finish(Decision.VETO,delta,drift,True,True,('AMYGDALA_PING_INVALID','COHERENCE_RESET_REQUIRED'),msg)
            return finish(Decision.VETO,delta,drift,True,False,('AMYGDALA_PING_VALID','COHERENCE_RESET_REQUIRED'),msg)
        if drift:return finish(Decision.VETO,delta,True,False,False,('COHERENCE_DRIFT',),None)
        return finish(Decision.PASS,delta,False,False,False,('INTERCHAT_COHERENCE_STABLE',),None)

    def confirm_reset(self, reset_s:float|None, *, frames_comparable:bool, proxies_comparable:bool, ping:AmygdalaPing|None)->InterchatEvaluation:
        request_sha=self._request_sha({'reset_s':reset_s,'frames_comparable':frames_comparable,'proxies_comparable':proxies_comparable,'ping':None if ping is None else ping.__dict__})
        finish=lambda decision,delta,drift,reset,ping_required,reasons,message:self._f(decision,delta,drift,reset,ping_required,reasons,message,request_sha)
        reset_q=_safe_q(reset_s) if reset_s is not None else None
        if reset_q is None or not (0<=reset_q<=100) or frames_comparable is not True or proxies_comparable is not True:
            return finish(Decision.RETRY,None,False,True,True,('RESET_EVIDENCE_INCOMPLETE',),None)
        if reset_q<6:
            return finish(Decision.VETO,None,False,True,True,('RESET_SCORE_BELOW_6',),None)
        if ping is None:
            return finish(Decision.VETO,None,False,True,True,('AMYGDALA_PING_REQUIRED',),None)
        if not self._valid_ping(ping):
            return finish(Decision.VETO,None,False,True,True,('AMYGDALA_PING_INVALID',),None)
        return finish(Decision.PASS,None,False,False,False,('COHERENCE_RESET_CONFIRMED',),None)

    @staticmethod
    def _valid_ping(ping:AmygdalaPing)->bool:
        expected=(AMYGDALA_REPO,AMYGDALA_REF,AMYGDALA_PATH,AMYGDALA_BENCHMARK,AMYGDALA_BLOB,AMYGDALA_MANIFEST,True)
        got=(ping.repository,ping.ref,ping.path,ping.benchmark_id,ping.blob_sha,ping.manifest_sha256,ping.fresh)
        return got==expected

    @staticmethod
    def _request_sha(payload):
        return hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=True,default=repr).encode()).hexdigest()

    def _f(self,decision,delta,drift,reset,ping_required,reasons,message,request_sha):
        payload={
            'request_sha256':request_sha,
            'decision':decision.value,
            'delta_s':None if delta is None else _fmt(delta),
            'drift':drift,
            'reset_required':reset,
            'ping_required':ping_required,
            'reasons':list(reasons),
            'user_message':message,
        }
        receipt=hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
        return InterchatEvaluation(decision,payload['delta_s'],drift,reset,ping_required,tuple(reasons),message,receipt)
