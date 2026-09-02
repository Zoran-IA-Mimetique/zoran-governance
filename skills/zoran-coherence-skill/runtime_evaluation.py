from __future__ import annotations
import hashlib
from dataclasses import dataclass
from fractions import Fraction
from typing import Mapping, Sequence
from action_gate import MulticriteriaActionGate
from bounded_truth_engine import BoundedTruthStatus, SourceEvidence as BoundedSourceEvidence
from claim_evidence_gate import ClaimEvidenceEvaluation, ClaimEvidenceRequest, source_authority_receipts_sha256
from coherence_dynamics import CoherencePoint
from components.semantic_color_patterns_v0.discourse_realizer_v1 import SemanticDiscourse
from host_truth_guard import HostTruthRequest
from interchat_guard import AmygdalaPing
from phenomenal_coherence import PhenomenalCoherenceRequest
from phenomenal_resource_gate import PhenomenalResourceRequest
from progress_guard import ProgressAttempt, ProgressGuard, ProgressHistoryEntry
from proposition_coherence_gate import PropositionCoherenceRequest
from proxy_engine import ProxyMeasurement
from question_reformulation_gate import QuestionReformulationRequest
from raw_text_coherence_gate import RawTextCoherenceEvaluation, RawTextCoherenceRequest
from robot_handoff_guard import RobotHandoffRequest, RobotTrustRegistry
from semantic_non_conflation import SemanticNonConflationEvaluation, SemanticNonConflationRequest
from source_coherence import SourceClaim
from terminal_controller import ControlEvidence, PASS as TERMINAL_PASS
from tolerance_skill import Decision, EvaluationScope, MulticriteriaToleranceSkill, Observation
from law_engine import HardLaw
PROMOTION_SCORE_THRESHOLD = Fraction(9)

@dataclass(frozen=True)
class _TextStageResult:
    blocked: object | None
    raw_evaluation: RawTextCoherenceEvaluation | None = None
    speech_receipt: str | None = None
    claim_evaluation: ClaimEvidenceEvaluation | None = None
    semantic_evaluation: SemanticNonConflationEvaluation | None = None

@dataclass(frozen=True)
class _EvidenceStageResult:
    blocked: object | None
    score_s: str | None = None
    phenomenal_resource_receipt: str | None = None
    phenomenal_receipt: str | None = None
    host_truth_receipt: str | None = None

class RuntimeEvaluationMixin:

    def evaluate(self, *, text: str, evidence_terms: Sequence[str], proxy_measurements: dict[str, ProxyMeasurement], source_claims: Sequence[SourceClaim], hard_laws: Sequence[HardLaw], tolerance_skill: MulticriteriaToleranceSkill, tolerance_observations: Sequence[Observation], scope: EvaluationScope, progress_guard: ProgressGuard, progress_attempt: ProgressAttempt, raw_text_coherence_request: RawTextCoherenceRequest | None=None, semantic_request: SemanticNonConflationRequest | None=None, semantic_speech_request: SemanticDiscourse | None=None, question_reformulation_request: QuestionReformulationRequest | None=None, proposition_coherence_request: PropositionCoherenceRequest | None=None, claim_evidence_request: ClaimEvidenceRequest | None=None, phenomenal_resources_request: PhenomenalResourceRequest | None=None, phenomenal_request: PhenomenalCoherenceRequest | None=None, host_truth_request: HostTruthRequest | None=None, robot_handoff_request: RobotHandoffRequest | None=None, robot_trust_registry: RobotTrustRegistry | None=None, progress_history: Sequence[ProgressHistoryEntry]=(), dynamics_history: Sequence[CoherencePoint]=(), dynamics_required: bool=False, previous_s: float | None=None, current_s: float | None=None, previous_frames: tuple[str, ...]=(), current_frames: tuple[str, ...]=(), previous_proxies: tuple[str, ...]=(), current_proxies: tuple[str, ...]=(), amygdala_ping: AmygdalaPing | None=None, decomposition_required: bool=False, domain_id: str | None=None, observed_parts: Sequence[str]=(), terminal_controls: Sequence[ControlEvidence]=(), terminal_required: bool=True, terminal_receipt_registry: Mapping[str, str] | None=None, bounded_truth_claim: str | None=None, bounded_truth_evidence: Sequence[BoundedSourceEvidence]=(), bounded_truth_required: bool=False, bounded_truth_time_sensitive: bool=False) -> FullEvaluation:
        receipts: dict[str, str] = {}
        text_stage = self._evaluate_text_stage(text=text, receipts=receipts, raw_text_coherence_request=raw_text_coherence_request, semantic_request=semantic_request, semantic_speech_request=semantic_speech_request, question_reformulation_request=question_reformulation_request, proposition_coherence_request=proposition_coherence_request, claim_evidence_request=claim_evidence_request, decomposition_required=decomposition_required, domain_id=domain_id, observed_parts=observed_parts)
        if text_stage.blocked is not None:
            return text_stage.blocked
        evidence_stage = self._evaluate_evidence_stage(text=text, receipts=receipts, evidence_terms=evidence_terms, proxy_measurements=proxy_measurements, source_claims=source_claims, hard_laws=hard_laws, semantic_request=semantic_request, claim_evidence_request=claim_evidence_request, claim_evaluation=text_stage.claim_evaluation, semantic_evaluation=text_stage.semantic_evaluation, phenomenal_resources_request=phenomenal_resources_request, phenomenal_request=phenomenal_request, host_truth_request=host_truth_request, bounded_truth_claim=bounded_truth_claim, bounded_truth_evidence=bounded_truth_evidence, bounded_truth_required=bounded_truth_required, bounded_truth_time_sensitive=bounded_truth_time_sensitive, dynamics_history=dynamics_history, dynamics_required=dynamics_required)
        if evidence_stage.blocked is not None:
            return evidence_stage.blocked
        return self._evaluate_decision_stage(receipts=receipts, score_s=evidence_stage.score_s, speech_receipt=text_stage.speech_receipt, raw_evaluation=text_stage.raw_evaluation, claim_evaluation=text_stage.claim_evaluation, semantic_evaluation=text_stage.semantic_evaluation, phenomenal_resource_receipt=evidence_stage.phenomenal_resource_receipt, phenomenal_receipt=evidence_stage.phenomenal_receipt, host_truth_receipt=evidence_stage.host_truth_receipt, question_reformulation_request=question_reformulation_request, proposition_coherence_request=proposition_coherence_request, tolerance_skill=tolerance_skill, tolerance_observations=tolerance_observations, scope=scope, progress_guard=progress_guard, progress_attempt=progress_attempt, progress_history=progress_history, previous_s=previous_s, current_s=current_s, previous_frames=previous_frames, current_frames=current_frames, previous_proxies=previous_proxies, current_proxies=current_proxies, amygdala_ping=amygdala_ping, robot_handoff_request=robot_handoff_request, robot_trust_registry=robot_trust_registry, terminal_controls=terminal_controls, terminal_required=terminal_required, terminal_receipt_registry=terminal_receipt_registry)

    def _evaluate_text_stage(self, *, text: str, receipts: dict[str, str], raw_text_coherence_request: RawTextCoherenceRequest | None, semantic_request: SemanticNonConflationRequest | None, semantic_speech_request: SemanticDiscourse | None, question_reformulation_request: QuestionReformulationRequest | None, proposition_coherence_request: PropositionCoherenceRequest | None, claim_evidence_request: ClaimEvidenceRequest | None, decomposition_required: bool, domain_id: str | None, observed_parts: Sequence[str]) -> _TextStageResult:
        if not isinstance(semantic_speech_request, SemanticDiscourse):
            return _TextStageResult(self._full(Decision.RETRY, ('SEMANTIC_SPEECH_REQUEST_MISSING',), None, receipts))
        speech = self.semantic_speech.evaluate(semantic_speech_request)
        receipts['semantic_speech'] = speech.receipt_sha256
        if speech.decision is not Decision.PASS:
            return _TextStageResult(self._full(speech.decision, ('SEMANTIC_SPEECH_BLOCK',) + speech.reasons, None, receipts))
        if speech.speech != text:
            return _TextStageResult(self._full(Decision.VETO, ('SEMANTIC_SPEECH_OUTPUT_IDENTITY_MISMATCH',), None, receipts))
        raw_evaluation = None
        if raw_text_coherence_request is not None:
            raw_evaluation = self.raw_text_coherence.evaluate(raw_text_coherence_request)
            receipts['raw_text_coherence'] = raw_evaluation.receipt_sha256
            if raw_evaluation.decision is not Decision.PASS:
                return _TextStageResult(self._full(raw_evaluation.decision, ('RAW_TEXT_COHERENCE_BLOCK',) + raw_evaluation.reasons, None, receipts))
        question_gate_used = question_reformulation_request is not None or proposition_coherence_request is not None
        qr = None
        if question_gate_used:
            qr = self.question_reformulation.evaluate(question_reformulation_request)
            receipts['question_reformulation'] = qr.receipt_sha256
            if qr.decision is not Decision.PASS:
                return _TextStageResult(self._full(qr.decision, ('QUESTION_REFORMULATION_BLOCK',) + qr.reasons, None, receipts))
            pc = self.proposition_coherence.evaluate(proposition_coherence_request)
            receipts['proposition_coherence'] = pc.receipt_sha256
            if pc.decision is not Decision.PASS:
                return _TextStageResult(self._full(pc.decision, ('PROPOSITION_COHERENCE_BLOCK',) + pc.reasons, None, receipts))
            if not isinstance(proposition_coherence_request, PropositionCoherenceRequest) or proposition_coherence_request.question_receipt_sha256 != qr.receipt_sha256:
                return _TextStageResult(self._full(Decision.VETO, ('PROPOSITION_QUESTION_RECEIPT_MISMATCH',), None, receipts))
        ce = self.claim_evidence.evaluate(claim_evidence_request)
        receipts['claim_evidence'] = ce.receipt_sha256
        if ce.decision is not Decision.PASS:
            return _TextStageResult(self._full(ce.decision, ('CLAIM_EVIDENCE_BLOCK',) + ce.reasons, None, receipts))
        if question_gate_used:
            blocked = self._validate_question_claim_bindings(receipts=receipts, question_reformulation_request=question_reformulation_request, proposition_coherence_request=proposition_coherence_request, claim_evidence_request=claim_evidence_request, question_evaluation=qr)
            if blocked is not None:
                return _TextStageResult(blocked)
        snc = self.semantic_non_conflation.evaluate(semantic_request)
        receipts['semantic_non_conflation'] = snc.receipt_sha256
        if snc.decision is not Decision.PASS:
            return _TextStageResult(self._full(snc.decision, ('SEMANTIC_NON_CONFLATION_BLOCK',) + snc.reasons, None, receipts))
        if isinstance(claim_evidence_request, ClaimEvidenceRequest):
            if claim_evidence_request.semantic_receipt_sha256 != snc.receipt_sha256:
                return _TextStageResult(self._full(Decision.VETO, ('CLAIM_EVIDENCE_SEMANTIC_RECEIPT_MISMATCH',), None, receipts))
            if claim_evidence_request.output_text != text or ce.output_sha256 != hashlib.sha256(text.encode('utf-8')).hexdigest():
                return _TextStageResult(self._full(Decision.VETO, ('CLAIM_EVIDENCE_OUTPUT_IDENTITY_MISMATCH',), None, receipts))
        if decomposition_required:
            if self.decomposition is None or not domain_id:
                return _TextStageResult(self._full(Decision.RETRY, ('DECOMPOSITION_CALIBRATION_REQUIRED_UNAVAILABLE',), None, receipts))
            dc = self.decomposition.evaluate(domain_id, observed_parts=observed_parts)
            receipts['decomposition_calibration'] = dc.receipt_sha256
            if dc.decision is not Decision.PASS:
                return _TextStageResult(self._full(dc.decision, ('DECOMPOSITION_CALIBRATION_BLOCK',) + dc.reasons, None, receipts))
        return _TextStageResult(None, raw_evaluation, speech.receipt_sha256, ce, snc)

    def _validate_question_claim_bindings(self, *, receipts: dict[str, str], question_reformulation_request: QuestionReformulationRequest | None, proposition_coherence_request: PropositionCoherenceRequest | None, claim_evidence_request: ClaimEvidenceRequest | None, question_evaluation):
        if not isinstance(claim_evidence_request, ClaimEvidenceRequest):
            return self._full(Decision.RETRY, ('CLAIM_EVIDENCE_REQUEST_MISSING_AFTER_PROPOSITION_GATE',), None, receipts)
        if claim_evidence_request.question_reformulation_receipt_sha256 != receipts['question_reformulation']:
            return self._full(Decision.VETO, ('CLAIM_QUESTION_RECEIPT_MISMATCH',), None, receipts)
        if claim_evidence_request.proposition_coherence_receipt_sha256 != receipts['proposition_coherence']:
            return self._full(Decision.VETO, ('CLAIM_PROPOSITION_RECEIPT_MISMATCH',), None, receipts)
        proposition_ids = {item.claim_id for item in proposition_coherence_request.claims}
        factual_ids = {item.claim_id for item in claim_evidence_request.units if item.kind.value == 'FACTUAL'}
        if proposition_ids != factual_ids:
            return self._full(Decision.VETO, ('PROPOSITION_CLAIM_IDENTITY_MISMATCH',), None, receipts)
        public_person_claims = tuple((item for item in proposition_coherence_request.claims if item.public_person_fact))
        if public_person_claims and (not question_evaluation.internet_verification_required):
            return self._full(Decision.VETO, ('PUBLIC_PERSON_RETRIEVAL_NOT_TRIGGERED_BY_QUESTION_GATE',), None, receipts)
        return None

    def _evaluate_evidence_stage(self, *, text: str, receipts: dict[str, str], evidence_terms: Sequence[str], proxy_measurements: dict[str, ProxyMeasurement], source_claims: Sequence[SourceClaim], hard_laws: Sequence[HardLaw], semantic_request: SemanticNonConflationRequest | None, claim_evidence_request: ClaimEvidenceRequest | None, claim_evaluation: ClaimEvidenceEvaluation, semantic_evaluation: SemanticNonConflationEvaluation, phenomenal_resources_request: PhenomenalResourceRequest | None, phenomenal_request: PhenomenalCoherenceRequest | None, host_truth_request: HostTruthRequest | None, bounded_truth_claim: str | None, bounded_truth_evidence: Sequence[BoundedSourceEvidence], bounded_truth_required: bool, bounded_truth_time_sensitive: bool, dynamics_history: Sequence[CoherencePoint], dynamics_required: bool) -> _EvidenceStageResult:
        fs = self.frames.search(text, evidence_terms=evidence_terms)
        receipts['frames'] = fs.receipt_sha256
        if fs.decision is not Decision.PASS:
            return _EvidenceStageResult(self._full(fs.decision, ('FRAME_GATE_BLOCK',) + fs.reasons, None, receipts))
        pe = self.proxies.evaluate(proxy_measurements)
        receipts['proxies'] = pe.receipt_sha256
        if pe.decision is not Decision.PASS:
            return _EvidenceStageResult(self._full(pe.decision, ('PROXY_GATE_BLOCK',) + pe.reasons, None, receipts))
        try:
            score_q = Fraction(pe.score_s)
        except Exception:
            return _EvidenceStageResult(self._full(Decision.RETRY, ('SCORE_PROMOTION_BOUND_TRACE_PENDING',), pe.score_s, receipts))
        if score_q <= PROMOTION_SCORE_THRESHOLD:
            return _EvidenceStageResult(self._full(Decision.VETO, ('SCORE_PROMOTION_THRESHOLD_NOT_MET:S_MUST_BE_STRICTLY_GREATER_THAN_9',), pe.score_s, receipts))
        se = self.sources.evaluate(source_claims)
        receipts['sources'] = se.receipt_sha256
        if se.decision is not Decision.PASS:
            return _EvidenceStageResult(self._full(se.decision, ('SOURCE_GATE_BLOCK',) + se.reasons, pe.score_s, receipts))
        pr = self.phenomenal_resources.evaluate(phenomenal_resources_request)
        receipts['phenomenal_resources'] = pr.receipt_sha256
        if pr.decision is not Decision.PASS:
            return _EvidenceStageResult(self._full(pr.decision, ('PHENOMENAL_RESOURCE_BLOCK',) + pr.reasons, pe.score_s, receipts))
        if not isinstance(phenomenal_request, PhenomenalCoherenceRequest) or phenomenal_request.resource_gate_receipt_sha256 != pr.receipt_sha256:
            return _EvidenceStageResult(self._full(Decision.VETO, ('PHENOMENAL_RESOURCE_RECEIPT_MISMATCH',), pe.score_s, receipts))
        ph = self.phenomenal.evaluate(phenomenal_request)
        receipts['phenomenal_coherence'] = ph.receipt_sha256
        if ph.decision is not Decision.PASS:
            return _EvidenceStageResult(self._full(ph.decision, ('PHENOMENAL_COHERENCE_BLOCK',) + ph.reasons, pe.score_s, receipts))
        if not isinstance(host_truth_request, HostTruthRequest):
            return _EvidenceStageResult(self._full(Decision.RETRY, ('HOST_TRUTH_ATTESTATION_MISSING',), pe.score_s, receipts))
        expected_truth = (semantic_request.mission_sha256 if isinstance(semantic_request, SemanticNonConflationRequest) else None, semantic_request.source_text if isinstance(semantic_request, SemanticNonConflationRequest) else None, text, claim_evaluation.receipt_sha256, semantic_evaluation.receipt_sha256, pr.receipt_sha256, ph.receipt_sha256, source_authority_receipts_sha256(claim_evidence_request))
        actual_truth = (host_truth_request.mission_sha256, host_truth_request.source_text, host_truth_request.output_text, host_truth_request.claim_receipt_sha256, host_truth_request.semantic_receipt_sha256, host_truth_request.phenomenal_resource_receipt_sha256, host_truth_request.phenomenal_receipt_sha256, host_truth_request.source_authority_receipts_sha256)
        if actual_truth != expected_truth:
            return _EvidenceStageResult(self._full(Decision.VETO, ('HOST_TRUTH_REQUEST_IDENTITY_MISMATCH',), pe.score_s, receipts))
        ht = self.host_truth.evaluate(host_truth_request)
        receipts['host_truth'] = ht.receipt_sha256
        if ht.decision is not Decision.PASS:
            return _EvidenceStageResult(self._full(ht.decision, ('HOST_TRUTH_BLOCK',) + ht.reasons, pe.score_s, receipts))
        if bounded_truth_required or bounded_truth_claim is not None:
            if not bounded_truth_claim:
                return _EvidenceStageResult(self._full(Decision.RETRY, ('BOUNDED_TRUTH_CLAIM_MISSING',), pe.score_s, receipts))
            bt = self.verify_bounded_truth(bounded_truth_claim, bounded_truth_evidence, time_sensitive=bounded_truth_time_sensitive)
            receipts['bounded_truth'] = bt.receipt_sha256
            if bt.status not in {BoundedTruthStatus.STRONGLY_SUPPORTED, BoundedTruthStatus.SUPPORTED}:
                return _EvidenceStageResult(self._full(Decision.RETRY, ('BOUNDED_TRUTH_REFORMULATION_REQUIRED', bt.status.value, bt.code) + bt.limitations, pe.score_s, receipts))
        le = self.laws.evaluate(hard_laws)
        receipts['laws'] = le.receipt_sha256
        if le.decision is not Decision.PASS:
            return _EvidenceStageResult(self._full(le.decision, ('LAW_GATE_BLOCK',) + le.reasons, pe.score_s, receipts))
        if dynamics_required:
            de = self.dynamics.evaluate(dynamics_history)
            receipts['dynamics'] = de.receipt_sha256
            if de.decision is not Decision.PASS:
                return _EvidenceStageResult(self._full(de.decision, ('DYNAMICS_GATE_BLOCK',) + de.reasons, pe.score_s, receipts))
        return _EvidenceStageResult(None, pe.score_s, pr.receipt_sha256, ph.receipt_sha256, ht.receipt_sha256)

    def _evaluate_decision_stage(self, *, receipts: dict[str, str], score_s: str, speech_receipt: str, raw_evaluation: RawTextCoherenceEvaluation | None, claim_evaluation: ClaimEvidenceEvaluation, semantic_evaluation: SemanticNonConflationEvaluation, phenomenal_resource_receipt: str, phenomenal_receipt: str, host_truth_receipt: str, question_reformulation_request: QuestionReformulationRequest | None, proposition_coherence_request: PropositionCoherenceRequest | None, tolerance_skill: MulticriteriaToleranceSkill, tolerance_observations: Sequence[Observation], scope: EvaluationScope, progress_guard: ProgressGuard, progress_attempt: ProgressAttempt, progress_history: Sequence[ProgressHistoryEntry], previous_s: float | None, current_s: float | None, previous_frames: tuple[str, ...], current_frames: tuple[str, ...], previous_proxies: tuple[str, ...], current_proxies: tuple[str, ...], amygdala_ping: AmygdalaPing | None, robot_handoff_request: RobotHandoffRequest | None, robot_trust_registry: RobotTrustRegistry | None, terminal_controls: Sequence[ControlEvidence], terminal_required: bool, terminal_receipt_registry: Mapping[str, str] | None) -> FullEvaluation:
        ag = MulticriteriaActionGate(tolerance_skill, progress_guard).evaluate(tolerance_observations, scope=scope, progress_attempt=progress_attempt, progress_history=progress_history)
        receipts['action'] = ag.receipt_sha256
        if ag.decision is not Decision.PASS:
            return self._full(ag.decision, ('ACTION_GATE_BLOCK',) + ag.reasons, score_s, receipts)
        if previous_s is not None or current_s is not None:
            ie = self.interchat.evaluate(previous_s, current_s, previous_frames=previous_frames, current_frames=current_frames, previous_proxies=previous_proxies, current_proxies=current_proxies, ping=amygdala_ping)
            receipts['interchat'] = ie.receipt_sha256
            if ie.decision is not Decision.PASS:
                return self._full(ie.decision, ('INTERCHAT_GATE_BLOCK',) + ie.reasons, score_s, receipts)
        rh = self.robot_handoff.evaluate(robot_handoff_request, trust_registry=robot_trust_registry)
        receipts['robot_handoff'] = rh.receipt_sha256
        if rh.decision is not Decision.PASS:
            return self._full(rh.decision, ('ROBOT_HANDOFF_BLOCK',) + rh.reasons, score_s, receipts)
        if not terminal_required:
            return self._full(Decision.RETRY, ('ZORAN_ADMISSIBLE_PENDING_TERMINAL',), score_s, receipts)
        controls = tuple(terminal_controls)
        internal_controls = {'semantic_non_conflation_gate': semantic_evaluation.receipt_sha256, 'semantic_speech_gate': speech_receipt, 'claim_evidence_gate': claim_evaluation.receipt_sha256, 'phenomenal_resource_gate': phenomenal_resource_receipt, 'phenomenal_coherence_gate': phenomenal_receipt, 'host_truth_gate': host_truth_receipt, 'robot_handoff_gate': rh.receipt_sha256}
        if question_reformulation_request is not None or proposition_coherence_request is not None:
            internal_controls['question_reformulation_gate'] = receipts['question_reformulation']
            internal_controls['proposition_coherence_gate'] = receipts['proposition_coherence']
        if isinstance(raw_evaluation, RawTextCoherenceEvaluation):
            internal_controls['raw_text_coherence_gate'] = raw_evaluation.receipt_sha256
        for control_id, receipt_sha256 in internal_controls.items():
            matching = tuple((x for x in controls if x.control_id == control_id))
            if len(matching) > 1:
                return self._full(Decision.VETO, (f'INTERNAL_TERMINAL_CONTROL_DUPLICATE:{control_id}',), score_s, receipts)
            if matching and (matching[0].receipt_sha256 != receipt_sha256 or matching[0].status != TERMINAL_PASS):
                return self._full(Decision.VETO, (f'INTERNAL_TERMINAL_RECEIPT_MISMATCH:{control_id}',), score_s, receipts)
            if control_id == 'raw_text_coherence_gate' and (not matching):
                controls = controls + (ControlEvidence(control_id, True, True, TERMINAL_PASS, receipt_sha256, 'candidate-owned raw text coherence receipt'),)
        registry = dict(terminal_receipt_registry or {})
        for control_id, receipt_sha256 in internal_controls.items():
            if registry.get(control_id) not in {None, receipt_sha256}:
                return self._full(Decision.VETO, (f'INTERNAL_TERMINAL_REGISTRY_CONFLICT:{control_id}',), score_s, receipts)
            registry[control_id] = receipt_sha256
        tv = self.terminal.evaluate(controls, trusted_receipts=registry)
        receipts['terminal'] = tv.receipt_sha256
        if tv.status != TERMINAL_PASS:
            decision = Decision.VETO if tv.status == 'FAIL' else Decision.RETRY
            return self._full(decision, ('TERMINAL_CONTROLLER_BLOCK',) + tv.reasons, score_s, receipts)
        return self._full(Decision.PASS, ('ZORAN_TERMINAL_VALIDATED',), score_s, receipts)
