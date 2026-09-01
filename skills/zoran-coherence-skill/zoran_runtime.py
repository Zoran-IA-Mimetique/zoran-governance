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

COMPONENT_ID='ZORAN_COHERENCE_SKILL'; VERSION='22.3.0'
PROMOTION_SCORE_THRESHOLD=Fraction(9)

@dataclass(frozen=True)
class PreChatResult:
    decision:Decision; sliding_context:tuple[str,...]; zmos:RecallResult|None; mirror:MirrorEvaluation|None; prompt_quality_receipt_sha256:str|None; reasons:tuple[str,...]; receipt_sha256:str

@dataclass(frozen=True)
class FullEvaluation:
    decision:Decision; reasons:tuple[str,...]; score_s:str|None; receipts:dict[str,str]; receipt_sha256:str

class ZoranRuntime:
    def __init__(self, *, frame_engine:FrameSearchEngine, proxy_engine:ProxyEngine|None=None, source_engine:SourceCoherenceEngine|None=None, law_engine:LawEngine|None=None, decomposition_engine:DecompositionCalibrationEngine|None=None, execution_state_root:str|Path|None=None, execution_policy:ExecutionPolicy|None=None, execution_clock=None):
        self.frames=frame_engine; self.proxies=proxy_engine or ProxyEngine(); self.sources=source_engine or SourceCoherenceEngine(); self.laws=law_engine or LawEngine(); self.security=PromptSecurity(); self.prompt_quality=PromptQualityEngine(); self.decomposition=decomposition_engine; self.dynamics=CoherenceDynamics(); self.phenomenal_resources=PhenomenalResourceGate(); self.phenomenal=PhenomenalCoherenceEngine(self.dynamics); self.semantic_non_conflation=SemanticNonConflationEngine(); self.question_reformulation=QuestionReformulationGate(); self.proposition_coherence=PropositionCoherenceGate(); self.contrastive_corpus=ContrastiveCorpusGate(); self.raw_text_coherence=RawTextCoherenceGate(); self.claim_evidence=ClaimEvidenceGate(); self.host_truth=HostTruthGuard(); self.robot_handoff=RobotHandoffGuard(self.semantic_non_conflation); self.host_session=HostSessionGuard(); self.interchat=InterchatGuard(); self.terminal=TerminalController(); self.parallel_context=ParallelContextGuard(); self.family_engine=PolymorphicFamilyEngine(); self.zmos_selector=ZmosCoherenceSelector(); self.read_progress=ReadProgressTracker(); self.recovery_loop=BoundedRecoveryLoop(); self.delivery_reviewer=DeliveryReviewer(); self.execution_governor=ExecutionGovernor(execution_state_root,policy=execution_policy,clock=execution_clock) if execution_state_root is not None else None

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

    def evaluate(self, *, text:str, evidence_terms:Sequence[str], proxy_measurements:dict[str,ProxyMeasurement], source_claims:Sequence[SourceClaim], hard_laws:Sequence[HardLaw], tolerance_skill:MulticriteriaToleranceSkill, tolerance_observations:Sequence[Observation], scope:EvaluationScope, progress_guard:ProgressGuard, progress_attempt:ProgressAttempt, raw_text_coherence_request:RawTextCoherenceRequest|None=None, semantic_request:SemanticNonConflationRequest|None=None, question_reformulation_request:QuestionReformulationRequest|None=None, proposition_coherence_request:PropositionCoherenceRequest|None=None, claim_evidence_request:ClaimEvidenceRequest|None=None, phenomenal_resources_request:PhenomenalResourceRequest|None=None, phenomenal_request:PhenomenalCoherenceRequest|None=None, host_truth_request:HostTruthRequest|None=None, robot_handoff_request:RobotHandoffRequest|None=None, robot_trust_registry:RobotTrustRegistry|None=None, progress_history:Sequence[ProgressHistoryEntry]=(), dynamics_history:Sequence[CoherencePoint]=(), dynamics_required:bool=False, previous_s:float|None=None,current_s:float|None=None, previous_frames:tuple[str,...]=(),current_frames:tuple[str,...]=(),previous_proxies:tuple[str,...]=(),current_proxies:tuple[str,...]=(), amygdala_ping:AmygdalaPing|None=None, decomposition_required:bool=False, domain_id:str|None=None, observed_parts:Sequence[str]=(), terminal_controls:Sequence[ControlEvidence]=(), terminal_required:bool=True, terminal_receipt_registry:Mapping[str,str]|None=None, bounded_truth_claim:str|None=None, bounded_truth_evidence:Sequence[BoundedSourceEvidence]=(), bounded_truth_required:bool=False, bounded_truth_time_sensitive:bool=False)->FullEvaluation:
        receipts={}
        raw_evaluation=None
        if raw_text_coherence_request is not None:
            raw_evaluation=self.raw_text_coherence.evaluate(raw_text_coherence_request); receipts['raw_text_coherence']=raw_evaluation.receipt_sha256
            if raw_evaluation.decision is not Decision.PASS:return self._full(raw_evaluation.decision,('RAW_TEXT_COHERENCE_BLOCK',)+raw_evaluation.reasons,None,receipts)
        if question_reformulation_request is not None or proposition_coherence_request is not None:
            qr=self.question_reformulation.evaluate(question_reformulation_request); receipts['question_reformulation']=qr.receipt_sha256
            if qr.decision is not Decision.PASS:return self._full(qr.decision,('QUESTION_REFORMULATION_BLOCK',)+qr.reasons,None,receipts)
            pc=self.proposition_coherence.evaluate(proposition_coherence_request); receipts['proposition_coherence']=pc.receipt_sha256
            if pc.decision is not Decision.PASS:return self._full(pc.decision,('PROPOSITION_COHERENCE_BLOCK',)+pc.reasons,None,receipts)
            if not isinstance(proposition_coherence_request,PropositionCoherenceRequest) or proposition_coherence_request.question_receipt_sha256!=qr.receipt_sha256:
                return self._full(Decision.VETO,('PROPOSITION_QUESTION_RECEIPT_MISMATCH',),None,receipts)
        ce=self.claim_evidence.evaluate(claim_evidence_request); receipts['claim_evidence']=ce.receipt_sha256
        if ce.decision is not Decision.PASS:return self._full(ce.decision,('CLAIM_EVIDENCE_BLOCK',)+ce.reasons,None,receipts)
        if question_reformulation_request is not None or proposition_coherence_request is not None:
            if not isinstance(claim_evidence_request,ClaimEvidenceRequest):
                return self._full(Decision.RETRY,('CLAIM_EVIDENCE_REQUEST_MISSING_AFTER_PROPOSITION_GATE',),None,receipts)
            if claim_evidence_request.question_reformulation_receipt_sha256!=receipts['question_reformulation']:
                return self._full(Decision.VETO,('CLAIM_QUESTION_RECEIPT_MISMATCH',),None,receipts)
            if claim_evidence_request.proposition_coherence_receipt_sha256!=receipts['proposition_coherence']:
                return self._full(Decision.VETO,('CLAIM_PROPOSITION_RECEIPT_MISMATCH',),None,receipts)
            proposition_ids={item.claim_id for item in proposition_coherence_request.claims}
            factual_ids={item.claim_id for item in claim_evidence_request.units if item.kind.value=='FACTUAL'}
            if proposition_ids!=factual_ids:
                return self._full(Decision.VETO,('PROPOSITION_CLAIM_IDENTITY_MISMATCH',),None,receipts)
            public_person_claims=tuple(item for item in proposition_coherence_request.claims if item.public_person_fact)
            if public_person_claims and not qr.internet_verification_required:
                return self._full(Decision.VETO,('PUBLIC_PERSON_RETRIEVAL_NOT_TRIGGERED_BY_QUESTION_GATE',),None,receipts)
        snc=self.semantic_non_conflation.evaluate(semantic_request); receipts['semantic_non_conflation']=snc.receipt_sha256
        if snc.decision is not Decision.PASS:return self._full(snc.decision,('SEMANTIC_NON_CONFLATION_BLOCK',)+snc.reasons,None,receipts)
        if isinstance(claim_evidence_request,ClaimEvidenceRequest):
            if claim_evidence_request.semantic_receipt_sha256!=snc.receipt_sha256:
                return self._full(Decision.VETO,('CLAIM_EVIDENCE_SEMANTIC_RECEIPT_MISMATCH',),None,receipts)
            if claim_evidence_request.output_text!=text or ce.output_sha256!=hashlib.sha256(text.encode('utf-8')).hexdigest():
                return self._full(Decision.VETO,('CLAIM_EVIDENCE_OUTPUT_IDENTITY_MISMATCH',),None,receipts)
        if decomposition_required:
            if self.decomposition is None or not domain_id:
                return self._full(Decision.RETRY,('DECOMPOSITION_CALIBRATION_REQUIRED_UNAVAILABLE',),None,receipts)
            dc=self.decomposition.evaluate(domain_id,observed_parts=observed_parts); receipts['decomposition_calibration']=dc.receipt_sha256
            if dc.decision is not Decision.PASS:return self._full(dc.decision,('DECOMPOSITION_CALIBRATION_BLOCK',)+dc.reasons,None,receipts)
        fs=self.frames.search(text,evidence_terms=evidence_terms); receipts['frames']=fs.receipt_sha256
        if fs.decision is not Decision.PASS:return self._full(fs.decision,('FRAME_GATE_BLOCK',)+fs.reasons,None,receipts)
        pe=self.proxies.evaluate(proxy_measurements); receipts['proxies']=pe.receipt_sha256
        if pe.decision is not Decision.PASS:return self._full(pe.decision,('PROXY_GATE_BLOCK',)+pe.reasons,None,receipts)
        try:score_q=Fraction(pe.score_s)
        except Exception:return self._full(Decision.RETRY,('SCORE_PROMOTION_BOUND_TRACE_PENDING',),pe.score_s,receipts)
        if score_q<=PROMOTION_SCORE_THRESHOLD:return self._full(Decision.VETO,('SCORE_PROMOTION_THRESHOLD_NOT_MET:S_MUST_BE_STRICTLY_GREATER_THAN_9',),pe.score_s,receipts)
        se=self.sources.evaluate(source_claims); receipts['sources']=se.receipt_sha256
        if se.decision is not Decision.PASS:return self._full(se.decision,('SOURCE_GATE_BLOCK',)+se.reasons,pe.score_s,receipts)
        pr=self.phenomenal_resources.evaluate(phenomenal_resources_request); receipts['phenomenal_resources']=pr.receipt_sha256
        if pr.decision is not Decision.PASS:
            return self._full(pr.decision,('PHENOMENAL_RESOURCE_BLOCK',)+pr.reasons,pe.score_s,receipts)
        if not isinstance(phenomenal_request,PhenomenalCoherenceRequest) or phenomenal_request.resource_gate_receipt_sha256!=pr.receipt_sha256:
            return self._full(Decision.VETO,('PHENOMENAL_RESOURCE_RECEIPT_MISMATCH',),pe.score_s,receipts)
        ph=self.phenomenal.evaluate(phenomenal_request); receipts['phenomenal_coherence']=ph.receipt_sha256
        if ph.decision is not Decision.PASS:
            return self._full(ph.decision,('PHENOMENAL_COHERENCE_BLOCK',)+ph.reasons,pe.score_s,receipts)
        if not isinstance(host_truth_request,HostTruthRequest):
            return self._full(Decision.RETRY,('HOST_TRUTH_ATTESTATION_MISSING',),pe.score_s,receipts)
        expected_truth=(
            semantic_request.mission_sha256 if isinstance(semantic_request,SemanticNonConflationRequest) else None,
            semantic_request.source_text if isinstance(semantic_request,SemanticNonConflationRequest) else None,
            text,
            ce.receipt_sha256,snc.receipt_sha256,pr.receipt_sha256,ph.receipt_sha256,
            source_authority_receipts_sha256(claim_evidence_request),
        )
        actual_truth=(host_truth_request.mission_sha256,host_truth_request.source_text,host_truth_request.output_text,host_truth_request.claim_receipt_sha256,host_truth_request.semantic_receipt_sha256,host_truth_request.phenomenal_resource_receipt_sha256,host_truth_request.phenomenal_receipt_sha256,host_truth_request.source_authority_receipts_sha256)
        if actual_truth!=expected_truth:
            return self._full(Decision.VETO,('HOST_TRUTH_REQUEST_IDENTITY_MISMATCH',),pe.score_s,receipts)
        ht=self.host_truth.evaluate(host_truth_request); receipts['host_truth']=ht.receipt_sha256
        if ht.decision is not Decision.PASS:
            return self._full(ht.decision,('HOST_TRUTH_BLOCK',)+ht.reasons,pe.score_s,receipts)
        if bounded_truth_required or bounded_truth_claim is not None:
            if not bounded_truth_claim:
                return self._full(Decision.RETRY,('BOUNDED_TRUTH_CLAIM_MISSING',),pe.score_s,receipts)
            bt=self.verify_bounded_truth(bounded_truth_claim,bounded_truth_evidence,time_sensitive=bounded_truth_time_sensitive); receipts['bounded_truth']=bt.receipt_sha256
            if bt.status not in {BoundedTruthStatus.STRONGLY_SUPPORTED,BoundedTruthStatus.SUPPORTED}:
                return self._full(Decision.RETRY,('BOUNDED_TRUTH_REFORMULATION_REQUIRED',bt.status.value,bt.code)+bt.limitations,pe.score_s,receipts)
        le=self.laws.evaluate(hard_laws); receipts['laws']=le.receipt_sha256
        if le.decision is not Decision.PASS:return self._full(le.decision,('LAW_GATE_BLOCK',)+le.reasons,pe.score_s,receipts)
        if dynamics_required:
            de=self.dynamics.evaluate(dynamics_history); receipts['dynamics']=de.receipt_sha256
            if de.decision is not Decision.PASS:return self._full(de.decision,('DYNAMICS_GATE_BLOCK',)+de.reasons,pe.score_s,receipts)
        ag=MulticriteriaActionGate(tolerance_skill,progress_guard).evaluate(tolerance_observations,scope=scope,progress_attempt=progress_attempt,progress_history=progress_history); receipts['action']=ag.receipt_sha256
        if ag.decision is not Decision.PASS:return self._full(ag.decision,('ACTION_GATE_BLOCK',)+ag.reasons,pe.score_s,receipts)
        if previous_s is not None or current_s is not None:
            ie=self.interchat.evaluate(previous_s,current_s,previous_frames=previous_frames,current_frames=current_frames,previous_proxies=previous_proxies,current_proxies=current_proxies,ping=amygdala_ping); receipts['interchat']=ie.receipt_sha256
            if ie.decision is not Decision.PASS:return self._full(ie.decision,('INTERCHAT_GATE_BLOCK',)+ie.reasons,pe.score_s,receipts)
        rh=self.robot_handoff.evaluate(robot_handoff_request,trust_registry=robot_trust_registry); receipts['robot_handoff']=rh.receipt_sha256
        if rh.decision is not Decision.PASS:return self._full(rh.decision,('ROBOT_HANDOFF_BLOCK',)+rh.reasons,pe.score_s,receipts)
        if terminal_required:
            controls=tuple(terminal_controls)
            internal_controls={
                'semantic_non_conflation_gate':snc.receipt_sha256,
                'claim_evidence_gate':ce.receipt_sha256,
                'phenomenal_resource_gate':pr.receipt_sha256,
                'phenomenal_coherence_gate':ph.receipt_sha256,
                'host_truth_gate':ht.receipt_sha256,
                'robot_handoff_gate':rh.receipt_sha256,
            }
            if question_reformulation_request is not None or proposition_coherence_request is not None:
                internal_controls['question_reformulation_gate']=receipts['question_reformulation']
                internal_controls['proposition_coherence_gate']=receipts['proposition_coherence']
            if isinstance(raw_evaluation,RawTextCoherenceEvaluation):
                internal_controls['raw_text_coherence_gate']=raw_evaluation.receipt_sha256
            for control_id,receipt_sha256 in internal_controls.items():
                matching=tuple(x for x in controls if x.control_id==control_id)
                if len(matching)>1:
                    return self._full(Decision.VETO,(f'INTERNAL_TERMINAL_CONTROL_DUPLICATE:{control_id}',),pe.score_s,receipts)
                if matching and (matching[0].receipt_sha256!=receipt_sha256 or matching[0].status!=TERMINAL_PASS):
                    return self._full(Decision.VETO,(f'INTERNAL_TERMINAL_RECEIPT_MISMATCH:{control_id}',),pe.score_s,receipts)
                if control_id=='raw_text_coherence_gate' and not matching:
                    controls=controls+(ControlEvidence(control_id,True,True,TERMINAL_PASS,receipt_sha256,'candidate-owned raw text coherence receipt'),)
            registry=dict(terminal_receipt_registry or {})
            for control_id,receipt_sha256 in internal_controls.items():
                if registry.get(control_id) not in {None,receipt_sha256}:
                    return self._full(Decision.VETO,(f'INTERNAL_TERMINAL_REGISTRY_CONFLICT:{control_id}',),pe.score_s,receipts)
                registry[control_id]=receipt_sha256
            tv=self.terminal.evaluate(controls,trusted_receipts=registry); receipts['terminal']=tv.receipt_sha256
            if tv.status!=TERMINAL_PASS:
                decision=Decision.VETO if tv.status=='FAIL' else Decision.RETRY
                return self._full(decision,('TERMINAL_CONTROLLER_BLOCK',)+tv.reasons,pe.score_s,receipts)
            return self._full(Decision.PASS,('ZORAN_TERMINAL_VALIDATED',),pe.score_s,receipts)
        return self._full(Decision.RETRY,('ZORAN_ADMISSIBLE_PENDING_TERMINAL',),pe.score_s,receipts)


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

    def evaluate_robot_handoff(self, request:RobotHandoffRequest|None, *, trust_registry:RobotTrustRegistry|None=None):
        return self.robot_handoff.evaluate(request,trust_registry=trust_registry)

    def finalize_output(self, request:HostSessionRequest|None, *, trust_registry:object|None=None):
        """Authorize display only from the pinned host session certificate."""
        return self.host_session.evaluate(request,trust_registry=trust_registry)

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
