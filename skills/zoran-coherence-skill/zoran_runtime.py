from __future__ import annotations
import hashlib,json
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Mapping, Sequence

from tolerance_skill import Decision, EvaluationScope, Observation, MulticriteriaToleranceSkill
from progress_guard import ProgressAttempt, ProgressHistoryEntry, ProgressGuard
from action_gate import MulticriteriaActionGate
from activation_guard import ActivationEvaluation
from prompt_security import PromptSecurity
from prompt_quality import PromptQualityEngine, EvaluatorCriterion, RangeAlignment
from decomposition_calibration import DecompositionCalibrationEngine
from zmos_memory import ZmosMemory, RecallResult, MemoryRecord, sliding_context
from github_mirror import GithubMirror, MirrorEvaluation
from frame_search import FrameSearchEngine
from proxy_engine import ProxyEngine, ProxyMeasurement
from source_coherence import SourceCoherenceEngine, SourceClaim
from law_engine import LawEngine, HardLaw
from coherence_dynamics import CoherenceDynamics, CoherencePoint
from interchat_guard import InterchatGuard, AmygdalaPing
from terminal_controller import TerminalController, ControlEvidence, PASS as TERMINAL_PASS
from parallel_context_guard import ParallelContextGuard, MemoryFragment
from polymorphic_family_engine import PolymorphicFamilyEngine, SelectionContext
from bounded_truth_engine import BoundedTruthStatus, SourceEvidence as BoundedSourceEvidence, evaluate_bounded_truth, build_search_plan
from zmos_coherence_selector import ZmosCoherenceSelector, ZmosObject
from read_progress import ReadProgressTracker, ReadProgressReceipt, terminal_read_status
from recovery_loop import BoundedRecoveryLoop, CycleResult, RecoveryResult
from delivery_reviewer import DeliveryReviewer, DeliveryReviewRequest
from phenomenal_coherence import PhenomenalCoherenceEngine, PhenomenalCoherenceEvaluation, PhenomenalCoherenceRequest
from phenomenal_resource_gate import PhenomenalResourceEvaluation, PhenomenalResourceGate, PhenomenalResourceRequest
from semantic_non_conflation import SemanticNonConflationEngine, SemanticNonConflationEvaluation, SemanticNonConflationRequest
from robot_handoff_guard import RobotHandoffGuard, RobotHandoffEvaluation, RobotHandoffRequest, RobotTrustRegistry
from claim_evidence_gate import ClaimEvidenceEvaluation, ClaimEvidenceGate, ClaimEvidenceRequest, source_authority_receipts_sha256
from host_session_guard import HostSessionGuard, HostSessionRequest
from host_truth_guard import HostTruthEvaluation, HostTruthGuard, HostTruthRequest
from question_reformulation_gate import (
    QuestionReformulationEvaluation,
    QuestionReformulationGate,
    QuestionReformulationRequest,
)
from proposition_coherence_gate import (
    PropositionCoherenceEvaluation,
    PropositionCoherenceGate,
    PropositionCoherenceRequest,
)
from contrastive_corpus_gate import ContrastiveCorpusGate, ContrastiveCorpusRequest
from raw_text_coherence_gate import RawTextCoherenceEvaluation, RawTextCoherenceGate, RawTextCoherenceRequest
from execution_governor import ExecutionGovernor, ExecutionPolicy, ExecutionRequest, ExecutionReceipt
from semantic_speech_gate import SemanticSpeechEvaluation, SemanticSpeechGate
from components.semantic_color_patterns_v0.discourse_realizer_v1 import SemanticDiscourse
from runtime_evaluation import RuntimeEvaluationMixin

COMPONENT_ID='ZORAN_COHERENCE_SKILL'; VERSION='23.1.0'
PROMOTION_SCORE_THRESHOLD=Fraction(9)

@dataclass(frozen=True)
class PreChatResult:
    decision:Decision; sliding_context:tuple[str,...]; zmos:RecallResult|None; mirror:MirrorEvaluation|None; prompt_quality_receipt_sha256:str|None; reasons:tuple[str,...]; receipt_sha256:str

@dataclass(frozen=True)
class FullEvaluation:
    decision:Decision; reasons:tuple[str,...]; score_s:str|None; receipts:dict[str,str]; receipt_sha256:str

@dataclass(frozen=True)
class FinalOutputEvaluation:
    decision:Decision; state:str; speech:str|None; semantic_speech_receipt_sha256:str|None; host_session_receipt_sha256:str|None; reasons:tuple[str,...]; receipt_sha256:str

class ZoranRuntime(RuntimeEvaluationMixin):
    def __init__(self, *, frame_engine:FrameSearchEngine, proxy_engine:ProxyEngine|None=None, source_engine:SourceCoherenceEngine|None=None, law_engine:LawEngine|None=None, decomposition_engine:DecompositionCalibrationEngine|None=None, execution_state_root:str|Path|None=None, execution_policy:ExecutionPolicy|None=None, execution_clock=None):
        self.frames=frame_engine; self.proxies=proxy_engine or ProxyEngine(); self.sources=source_engine or SourceCoherenceEngine(); self.laws=law_engine or LawEngine(); self.security=PromptSecurity(); self.prompt_quality=PromptQualityEngine(); self.decomposition=decomposition_engine; self.dynamics=CoherenceDynamics(); self.phenomenal_resources=PhenomenalResourceGate(); self.phenomenal=PhenomenalCoherenceEngine(self.dynamics); self.semantic_non_conflation=SemanticNonConflationEngine(); self.semantic_speech=SemanticSpeechGate(); self.question_reformulation=QuestionReformulationGate(); self.proposition_coherence=PropositionCoherenceGate(); self.contrastive_corpus=ContrastiveCorpusGate(); self.raw_text_coherence=RawTextCoherenceGate(); self.claim_evidence=ClaimEvidenceGate(); self.host_truth=HostTruthGuard(); self.robot_handoff=RobotHandoffGuard(self.semantic_non_conflation); self.host_session=HostSessionGuard(); self.interchat=InterchatGuard(); self.terminal=TerminalController(); self.parallel_context=ParallelContextGuard(); self.family_engine=PolymorphicFamilyEngine(); self.zmos_selector=ZmosCoherenceSelector(); self.read_progress=ReadProgressTracker(); self.recovery_loop=BoundedRecoveryLoop(); self.delivery_reviewer=DeliveryReviewer(); self.execution_governor=ExecutionGovernor(execution_state_root,policy=execution_policy,clock=execution_clock) if execution_state_root is not None else None

    def pre_chat(self, *, activation:ActivationEvaluation, prompt:str, recent_turns:Sequence[str], zmos:ZmosMemory|None, zmos_required:bool, zmos_query:str, zmos_budget_chars:int, mirror:GithubMirror|None=None, mirror_required:bool=False, sliding_budget_chars:int=12000, frame_ids:Sequence[str]=(), proxy_ids:Sequence[str]=(), source_ids:Sequence[str]=(), evaluator_criteria:Sequence[EvaluatorCriterion]=(), range_alignments:Sequence[RangeAlignment]=(), prompt_quality_required:bool=False, trusted_activation_receipts:Sequence[str]=())->PreChatResult:
        recent_turns=tuple(recent_turns); frame_ids=tuple(frame_ids); proxy_ids=tuple(proxy_ids); source_ids=tuple(source_ids); evaluator_criteria=tuple(evaluator_criteria); range_alignments=tuple(range_alignments); trusted_activation_receipts=tuple(trusted_activation_receipts)
        request={'activation':activation.__dict__ if isinstance(activation,ActivationEvaluation) else repr(activation),'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest() if isinstance(prompt,str) else hashlib.sha256(repr(prompt).encode()).hexdigest(),'recent_turns':list(recent_turns),'zmos_required':zmos_required,'zmos_query_sha256':hashlib.sha256(zmos_query.encode()).hexdigest() if isinstance(zmos_query,str) else hashlib.sha256(repr(zmos_query).encode()).hexdigest(),'zmos_budget_chars':zmos_budget_chars,'mirror_required':mirror_required,'sliding_budget_chars':sliding_budget_chars,'frame_ids':list(frame_ids),'proxy_ids':list(proxy_ids),'source_ids':list(source_ids),'evaluator_criteria':[x.__dict__ for x in evaluator_criteria],'range_alignments':[x.__dict__ for x in range_alignments],'prompt_quality_required':prompt_quality_required,'trusted_activation_receipts':sorted(trusted_activation_receipts)}
        request_sha=hashlib.sha256(json.dumps(request,sort_keys=True,separators=(',',':'),ensure_ascii=False,default=repr).encode()).hexdigest()
        finish=lambda d,slide,z,m,pq,r:self._pre(d,slide,z,m,pq,r,request_sha)
        if activation.decision is not Decision.PASS:
            return finish(activation.decision,(),None,None,None,('ACTIVATION_BLOCK',)+activation.reasons)
        if activation.receipt_sha256 not in frozenset(trusted_activation_receipts):
            return finish(Decision.RETRY,(),None,None,None,('ACTIVATION_RECEIPT_UNTRUSTED',))
        sec=self.security.check(prompt)
        if sec.decision is not Decision.PASS:return finish(sec.decision,(),None,None,None,('PROMPT_SECURITY_BLOCK',sec.reason))
        pq=None
        if prompt_quality_required or evaluator_criteria or range_alignments:
            pq=self.prompt_quality.evaluate(prompt,evaluator_criteria=evaluator_criteria,range_alignments=range_alignments)
            if pq.decision is not Decision.PASS:
                return finish(pq.decision,(),None,None,pq.receipt_sha256,('PROMPT_CONTRACT_REPAIR_REQUIRED',)+pq.reasons)
        slide=sliding_context(recent_turns,max_chars=sliding_budget_chars)
        recall=None
        if zmos_required:
            if zmos is None:return finish(Decision.RETRY,slide,None,None,None if pq is None else pq.receipt_sha256,('ZMOS_REQUIRED_UNAVAILABLE',))
            recall=zmos.recall(zmos_query,frame_ids=frame_ids,proxy_ids=proxy_ids,source_ids=source_ids,context_budget_chars=zmos_budget_chars)
            if recall.decision is not Decision.PASS:return finish(recall.decision,slide,recall,None,None if pq is None else pq.receipt_sha256,('ZMOS_RECALL_BLOCK',)+recall.reasons)
        mir=None
        if mirror_required:
            if mirror is None:return finish(Decision.RETRY,slide,recall,None,None if pq is None else pq.receipt_sha256,('MIRROR_REQUIRED_UNAVAILABLE',))
            mir=mirror.verify(required=True)
            if mir.decision is not Decision.PASS:return finish(mir.decision,slide,recall,mir,None if pq is None else pq.receipt_sha256,('MIRROR_BLOCK',)+mir.reasons)
        return finish(Decision.PASS,slide,recall,mir,None if pq is None else pq.receipt_sha256,('PRE_CHAT_READY',))

    def select_polymorphic_families(self, context:SelectionContext):
        return self.family_engine.select(context)

    def select_zmos_by_coherence(self, objects:Sequence[ZmosObject], *, max_objects:int|None=None, max_chars:int|None=None):
        return self.zmos_selector.select(objects,max_objects=max_objects,max_chars=max_chars)

    def bounded_truth_search_plan(self, *, scientific:bool, time_sensitive:bool):
        return build_search_plan(scientific=scientific,time_sensitive=time_sensitive)

    def measure_read_progress(self, *, object_id:str, object_type:str, total_units:int|None, read_units:Sequence[int]=(), unit_name:str|None=None)->ReadProgressReceipt:
        return self.read_progress.evaluate(object_id=object_id,object_type=object_type,total_units=total_units,read_units=read_units,unit_name=unit_name)

    def next_read_window(self, receipt:ReadProgressReceipt, *, max_units:int)->tuple[int,...]:
        return self.read_progress.next_window(receipt,max_units=max_units)

    def reading_terminal_control(self, receipt:ReadProgressReceipt, *, required:bool=True)->ControlEvidence:
        status,detail=terminal_read_status(receipt)
        return ControlEvidence('object_read_complete',required,True,status,receipt.receipt_sha256,detail)

    def govern_execution(self, request:ExecutionRequest)->ExecutionReceipt:
        """Authorize one execution step against the persistent program budget."""
        if self.execution_governor is None:
            raise RuntimeError('PERSISTENT_EXECUTION_GOVERNOR_REQUIRED')
        return self.execution_governor.evaluate(request)

    def recover_until_terminal(self, cycle, repair, *, execution_request_factory=None)->RecoveryResult:
        """Recover only through the persistent governor; a chat-local bound is insufficient."""
        if self.execution_governor is None or execution_request_factory is None:
            raise RuntimeError('PERSISTENT_EXECUTION_GOVERNOR_REQUIRED')
        return self.recovery_loop.run(
            cycle,
            repair,
            execution_guard=lambda result,attempt:self.execution_governor.evaluate(
                execution_request_factory(result,attempt)
            ),
        )

    def verify_bounded_truth(self, claim:str, evidence:Sequence[BoundedSourceEvidence], *, time_sensitive:bool=False):
        return evaluate_bounded_truth(claim,evidence,time_sensitive=time_sensitive)

    def evaluate_phenomenal_coherence(self, request:PhenomenalCoherenceRequest|None):
        return self.phenomenal.evaluate(request)

    def evaluate_phenomenal_resources(self, request:PhenomenalResourceRequest|None):
        return self.phenomenal_resources.evaluate(request)

    def evaluate_host_truth(self, request:HostTruthRequest|None):
        return self.host_truth.evaluate(request)

    def evaluate_semantic_non_conflation(self, request:SemanticNonConflationRequest|None):
        return self.semantic_non_conflation.evaluate(request)

    def evaluate_question_reformulation(self, request:QuestionReformulationRequest|None)->QuestionReformulationEvaluation:
        return self.question_reformulation.evaluate(request)

    def evaluate_proposition_coherence(self, request:PropositionCoherenceRequest|None)->PropositionCoherenceEvaluation:
        return self.proposition_coherence.evaluate(request)

    def evaluate_contrastive_corpus(self, request:ContrastiveCorpusRequest|None):
        return self.contrastive_corpus.evaluate(request)

    def evaluate_raw_text_coherence(self, request:RawTextCoherenceRequest|None)->RawTextCoherenceEvaluation:
        return self.raw_text_coherence.evaluate(request)

    def evaluate_semantic_speech(self, discourse:SemanticDiscourse|None)->SemanticSpeechEvaluation:
        return self.semantic_speech.evaluate(discourse)

    def evaluate_robot_handoff(self, request:RobotHandoffRequest|None, *, trust_registry:RobotTrustRegistry|None=None):
        return self.robot_handoff.evaluate(request,trust_registry=trust_registry)

    def finalize_output(self, request:HostSessionRequest|None, *, semantic_speech_request:SemanticDiscourse|None=None, trust_registry:object|None=None)->FinalOutputEvaluation:
        """Authorize only speech produced by the semantic round trip and host guard."""
        if not isinstance(semantic_speech_request,SemanticDiscourse):
            return self._final_output(Decision.RETRY,'SPEECH_WITHHELD',None,None,None,('SEMANTIC_SPEECH_REQUEST_MISSING',))
        speech=self.semantic_speech.evaluate(semantic_speech_request)
        if speech.decision is not Decision.PASS:
            return self._final_output(speech.decision,'SPEECH_WITHHELD',None,speech.receipt_sha256,None,('SEMANTIC_SPEECH_BLOCK',)+speech.reasons)
        if not isinstance(request,HostSessionRequest):
            return self._final_output(Decision.RETRY,'SPEECH_WITHHELD',None,speech.receipt_sha256,None,('HOST_SESSION_REQUEST_MISSING',))
        if request.output_text!=speech.speech:
            return self._final_output(Decision.VETO,'SPEECH_WITHHELD',None,speech.receipt_sha256,None,('SEMANTIC_SPEECH_OUTPUT_IDENTITY_MISMATCH',))
        host=self.host_session.evaluate(request,trust_registry=trust_registry)
        released=speech.speech if host.decision is Decision.PASS else None
        return self._final_output(host.decision,host.state,released,speech.receipt_sha256,host.receipt_sha256,host.reasons)

    def check_parallel_context(self, *, doubt:bool, question:str, candidate:str, fragments:Sequence[MemoryFragment], active_project_id:str|None=None):
        return self.parallel_context.evaluate(doubt=doubt,question=question,candidate=candidate,fragments=fragments,active_project_id=active_project_id)

    def terminal_validate(self, controls:Sequence[ControlEvidence],*,trusted_receipts:Mapping[str,str]):
        return self.terminal.evaluate(controls,trusted_receipts=trusted_receipts)

    def review_delivery(self, request:DeliveryReviewRequest):
        return self.delivery_reviewer.evaluate(request)

    def persist_candidate(self,zmos:ZmosMemory,record:MemoryRecord)->bool:
        if record.status!='CANDIDATE':raise ValueError('candidate status required')
        return zmos.append(record)
    def finalize_candidate(self,zmos:ZmosMemory,record_id:str,*,decision:Decision,gate_receipt_sha256:str,semantic_evaluation:SemanticNonConflationEvaluation|None=None,claim_evidence_evaluation:ClaimEvidenceEvaluation|None=None,phenomenal_resource_evaluation:PhenomenalResourceEvaluation|None=None,phenomenal_evaluation:PhenomenalCoherenceEvaluation|None=None,host_truth_evaluation:HostTruthEvaluation|None=None,robot_handoff_evaluation:RobotHandoffEvaluation|None=None):
        semantic_pass=isinstance(semantic_evaluation,SemanticNonConflationEvaluation) and semantic_evaluation.decision is Decision.PASS
        claim_pass=isinstance(claim_evidence_evaluation,ClaimEvidenceEvaluation) and claim_evidence_evaluation.decision is Decision.PASS
        phenomenal_resource_pass=isinstance(phenomenal_resource_evaluation,PhenomenalResourceEvaluation) and phenomenal_resource_evaluation.decision is Decision.PASS
        phenomenal_pass=isinstance(phenomenal_evaluation,PhenomenalCoherenceEvaluation) and phenomenal_evaluation.decision is Decision.PASS
        host_truth_pass=isinstance(host_truth_evaluation,HostTruthEvaluation) and host_truth_evaluation.decision is Decision.PASS
        robot_pass=isinstance(robot_handoff_evaluation,RobotHandoffEvaluation) and robot_handoff_evaluation.decision is Decision.PASS and robot_handoff_evaluation.state=='VALIDATED'
        status='VALIDATED' if decision is Decision.PASS and semantic_pass and claim_pass and phenomenal_resource_pass and phenomenal_pass and host_truth_pass and robot_pass else 'BLOCKED'
        if decision is Decision.PASS and not (semantic_pass and claim_pass and phenomenal_resource_pass and phenomenal_pass and host_truth_pass and robot_pass):
            decision=Decision.RETRY
        return zmos.promote(record_id,status,gate_decision=decision.value,gate_receipt_sha256=gate_receipt_sha256)

    def _pre(self,d,slide,z,m,pq,r,request_sha):
        p={'component':COMPONENT_ID,'version':VERSION,'request_sha256':request_sha,'decision':d.value,'slide':list(slide),'zmos_digest':None if z is None else z.context_digest,'mirror':None if m is None else m.manifest_sha256,'prompt_quality':pq,'reasons':list(r)}; h=hashlib.sha256(json.dumps(p,sort_keys=True,separators=(',',':')).encode()).hexdigest(); return PreChatResult(d,tuple(slide),z,m,pq,tuple(r),h)
    def _full(self,d,r,s,receipts):
        p={'component':COMPONENT_ID,'version':VERSION,'decision':d.value,'reasons':list(r),'score_s':s,'receipts':dict(sorted(receipts.items()))}; h=hashlib.sha256(json.dumps(p,sort_keys=True,separators=(',',':')).encode()).hexdigest(); return FullEvaluation(d,tuple(r),s,dict(receipts),h)
    def _final_output(self,d,state,speech,semantic_receipt,host_receipt,reasons):
        p={'component':'ZORAN_FINAL_OUTPUT','version':VERSION,'decision':d.value,'state':state,'speech_sha256':None if speech is None else hashlib.sha256(speech.encode('utf-8')).hexdigest(),'semantic_speech_receipt_sha256':semantic_receipt,'host_session_receipt_sha256':host_receipt,'reasons':list(reasons)}; h=hashlib.sha256(json.dumps(p,sort_keys=True,separators=(',',':')).encode()).hexdigest(); return FinalOutputEvaluation(d,state,speech,semantic_receipt,host_receipt,tuple(reasons),h)
