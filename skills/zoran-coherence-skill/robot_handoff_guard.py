from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Mapping

from robot_certificate import RobotCertificateError, trusted_certifier, verify_release_certificate

from semantic_non_conflation import (
    ActionDisposition,
    SemanticConcept,
    SemanticDistinction,
    SemanticNonConflationEngine,
    SemanticNonConflationRequest,
    evidence_sha256,
    semantic_vector_sha256,
)
from tolerance_skill import Decision


COMPONENT_ID = "ZORAN_ROBOT_HANDOFF_GUARD"
VERSION = "2.0.0"
VALIDATION_STATUSES = frozenset({"PENDING", "PASS", "FAIL"})


@dataclass(frozen=True)
class RobotHandoffRequest:
    mission_sha256: str
    candidate_sha256: str
    artifact_sha256: str
    required: bool
    applicability_evidence: str
    applicability_evidence_sha256: str
    discovery_completed: bool = False
    discovery_evidence: str | None = None
    discovery_evidence_sha256: str | None = None
    channel_id: str | None = None
    channel_evidence: str | None = None
    channel_evidence_sha256: str | None = None
    submission_id: str | None = None
    submission_evidence: str | None = None
    submission_evidence_sha256: str | None = None
    validation_status: str | None = None
    validation_receipt_sha256: str | None = None
    authority_id: str | None = None
    authority_fingerprint: str | None = None
    certification_envelope: Mapping[str, object] | None = None


@dataclass(frozen=True)
class RobotTrustRegistry:
    """Legacy caller-controlled trust input, retained only for explicit rejection."""

    authority_fingerprints: Mapping[str, str]
    validation_receipts: tuple[str, ...]


@dataclass(frozen=True)
class RobotHandoffEvaluation:
    decision: Decision
    state: str
    reasons: tuple[str, ...]
    semantic_receipt_sha256: str
    certificate_sha256: str | None
    request_sha256: str
    receipt_sha256: str

    def as_dict(self) -> dict:
        return {
            "component": COMPONENT_ID,
            "version": VERSION,
            "decision": self.decision.value,
            "state": self.state,
            "reasons": list(self.reasons),
            "semantic_receipt_sha256": self.semantic_receipt_sha256,
            "certificate_sha256": self.certificate_sha256,
            "request_sha256": self.request_sha256,
            "receipt_sha256": self.receipt_sha256,
        }


class RobotHandoffGuard:
    def __init__(self, semantic_engine: SemanticNonConflationEngine | None = None):
        self.semantic = semantic_engine or SemanticNonConflationEngine()

    def evaluate(self, request: RobotHandoffRequest | None, *, trust_registry: RobotTrustRegistry | None = None) -> RobotHandoffEvaluation:
        request_sha = _sha(self._request_payload(request))
        if not isinstance(request, RobotHandoffRequest):
            return self._finish(Decision.RETRY, "UNDECLARED", ("ROBOT_HANDOFF_REQUEST_MISSING",), "0" * 64, None, request_sha)
        if trust_registry is not None:
            return self._finish(Decision.VETO, "CALLER_TRUST_FORBIDDEN", ("CALLER_SUPPLIED_ROBOT_TRUST_REGISTRY_FORBIDDEN",), "0" * 64, None, request_sha)
        if not all(_valid_sha(value) for value in (request.mission_sha256, request.candidate_sha256, request.artifact_sha256)):
            return self._finish(Decision.RETRY, "IDENTITY_INVALID", ("ROBOT_HANDOFF_IDENTITY_INVALID",), "0" * 64, None, request_sha)
        if request.candidate_sha256 != request.artifact_sha256:
            return self._finish(Decision.VETO, "IDENTITY_CONFLICT", ("ROBOT_CANDIDATE_ARTIFACT_IDENTITY_MISMATCH",), "0" * 64, None, request_sha)
        if not isinstance(request.required, bool) or not _evidence_valid(request.applicability_evidence, request.applicability_evidence_sha256):
            return self._finish(Decision.RETRY, "APPLICABILITY_UNKNOWN", ("ROBOT_HANDOFF_APPLICABILITY_UNPROVEN",), "0" * 64, None, request_sha)

        semantic = self.semantic.evaluate(self._semantic_request(request))
        if semantic.decision is Decision.VETO:
            return self._finish(semantic.decision, "SEMANTIC_BLOCK", ("ROBOT_HANDOFF_SEMANTIC_CONFLATION_BLOCK",) + semantic.reasons, semantic.receipt_sha256, None, request_sha)
        if request.required is False:
            return self._finish(Decision.PASS, "NOT_REQUIRED_PROVEN", ("ROBOT_HANDOFF_NOT_REQUIRED_PROVEN",), semantic.receipt_sha256, None, request_sha)

        if not isinstance(request.discovery_completed, bool):
            return self._finish(Decision.RETRY, "DISCOVERY_UNKNOWN", ("ROBOT_DISCOVERY_STATUS_INVALID",), semantic.receipt_sha256, None, request_sha)
        if request.discovery_completed is False:
            return self._finish(Decision.RETRY, "DISCOVERY_REQUIRED", ("ROBOT_DISCOVERY_NOT_RUN",), semantic.receipt_sha256, None, request_sha)
        if not _evidence_valid(request.discovery_evidence, request.discovery_evidence_sha256):
            return self._finish(Decision.RETRY, "DISCOVERY_UNPROVEN", ("ROBOT_DISCOVERY_EVIDENCE_INVALID",), semantic.receipt_sha256, None, request_sha)
        if not request.channel_id:
            return self._finish(Decision.RETRY, "CHANNEL_UNRESOLVED", ("ROBOT_CHANNEL_UNRESOLVED",), semantic.receipt_sha256, None, request_sha)
        if not _evidence_valid(request.channel_evidence, request.channel_evidence_sha256):
            return self._finish(Decision.RETRY, "CHANNEL_UNTRUSTED", ("ROBOT_CHANNEL_EVIDENCE_INVALID",), semantic.receipt_sha256, None, request_sha)
        if not request.submission_id:
            return self._finish(Decision.RETRY, "HANDOFF_REQUIRED", ("ROBOT_HANDOFF_NOT_TRIGGERED",), semantic.receipt_sha256, None, request_sha)
        if not _evidence_valid(request.submission_evidence, request.submission_evidence_sha256):
            return self._finish(Decision.RETRY, "SUBMISSION_UNPROVEN", ("ROBOT_SUBMISSION_EVIDENCE_INVALID",), semantic.receipt_sha256, None, request_sha)
        if request.validation_status is None or request.validation_status == "PENDING":
            return self._finish(Decision.RETRY, "VALIDATION_PENDING", ("ROBOT_VALIDATION_PENDING",), semantic.receipt_sha256, None, request_sha)
        if request.validation_status not in VALIDATION_STATUSES:
            return self._finish(Decision.RETRY, "VALIDATION_STATUS_UNKNOWN", ("ROBOT_VALIDATION_STATUS_INVALID",), semantic.receipt_sha256, None, request_sha)
        if request.validation_status == "FAIL":
            return self._finish(Decision.VETO, "REJECTED", ("ROBOT_VALIDATION_REJECTED",), semantic.receipt_sha256, None, request_sha)
        if not _valid_sha(request.validation_receipt_sha256) or not request.authority_id or not _valid_sha(request.authority_fingerprint):
            return self._finish(Decision.RETRY, "VALIDATION_UNPROVEN", ("ROBOT_VALIDATION_PROOF_INCOMPLETE",), semantic.receipt_sha256, None, request_sha)
        try:
            anchor = trusted_certifier()
            certificate, certificate_sha = verify_release_certificate(
                request.certification_envelope,
                mission_sha256=request.mission_sha256,
                candidate_sha256=request.candidate_sha256,
            )
        except RobotCertificateError as exc:
            return self._finish(Decision.VETO, "CERTIFICATE_INVALID", (str(exc),), semantic.receipt_sha256, None, request_sha)
        if request.authority_id != anchor["authority_id"] or request.authority_fingerprint != anchor["fingerprint_sha256"]:
            return self._finish(Decision.VETO, "AUTHORITY_UNTRUSTED", ("ROBOT_AUTHORITY_UNTRUSTED",), semantic.receipt_sha256, None, request_sha)
        if request.channel_id != certificate["channel_id"] or request.submission_id != certificate["submission_id"]:
            return self._finish(Decision.VETO, "HANDOFF_IDENTITY_CONFLICT", ("ROBOT_CERTIFICATE_HANDOFF_IDENTITY_MISMATCH",), semantic.receipt_sha256, certificate_sha, request_sha)
        if request.validation_receipt_sha256 != certificate_sha:
            return self._finish(Decision.VETO, "CERTIFICATE_SUBSTITUTED", ("ROBOT_VALIDATION_RECEIPT_SUBSTITUTED",), semantic.receipt_sha256, certificate_sha, request_sha)
        if semantic.decision is not Decision.PASS:
            return self._finish(Decision.RETRY, "SEMANTIC_RECOVERY_REQUIRED", ("ROBOT_HANDOFF_SEMANTIC_RECEIPT_NOT_PASS",) + semantic.reasons, semantic.receipt_sha256, certificate_sha, request_sha)
        return self._finish(Decision.PASS, "VALIDATED", ("ROBOT_SIGNED_CERTIFICATION_TRUSTED_PASS",), semantic.receipt_sha256, certificate_sha, request_sha)

    def _semantic_request(self, request: RobotHandoffRequest) -> SemanticNonConflationRequest:
        source_text = "The candidate must not certify itself as an external authority. The host must submit the candidate to the external robot when that handoff is required."
        self_quote = "The candidate must not certify itself as an external authority."
        external_quote = "The host must submit the candidate to the external robot when that handoff is required."
        self_evidence = "Self-certification is prohibited; this prohibition names only the self-certify action."
        external_evidence = "External validation is an independent handoff obligation when applicability is required."
        distinction_evidence = "Authority and handoff are different: who may decide does not erase the duty to submit."
        self_concept = SemanticConcept(
            "self_certification_prohibition",
            "The candidate must not certify itself as an external authority.",
            "candidate",
            request.candidate_sha256,
            "MUST_NOT",
            (),
            ("self_certify",),
            self_evidence,
            evidence_sha256(self_evidence),
            self_quote,
            "candidate",
            "itself",
            (),
            ("certify itself",),
        )
        external_concept = SemanticConcept(
            "external_validation_requirement",
            external_quote,
            "host",
            request.artifact_sha256,
            "MUST" if request.required else "NOT_APPLICABLE_PROVEN",
            ("submit_to_external_robot",) if request.required else (),
            (),
            external_evidence,
            evidence_sha256(external_evidence),
            external_quote,
            "host",
            "candidate",
            ("submit the candidate to the external robot",) if request.required else (),
            (),
        )
        distinction = SemanticDistinction(
            self_concept.concept_id,
            external_concept.concept_id,
            "self_certify and submit_to_external_robot are different actions performed by different actors",
            "The distinction is false only if host submission cryptographically equals candidate self-certification.",
            distinction_evidence,
            evidence_sha256(distinction_evidence),
        )
        self_action_evidence = "self_certify remains blocked by the self-certification prohibition"
        dispositions = [ActionDisposition("self_certify", "BLOCKED", (self_concept.concept_id,), self_action_evidence, evidence_sha256(self_action_evidence))]
        if request.required:
            submitted = bool(request.submission_id)
            submit_evidence = request.submission_evidence if submitted and request.submission_evidence else "external robot submission remains pending"
            dispositions.append(
                ActionDisposition(
                    "submit_to_external_robot",
                    "EXECUTED" if submitted else "PENDING",
                    (external_concept.concept_id,),
                    submit_evidence,
                    evidence_sha256(submit_evidence),
                )
            )
        semantic_request = SemanticNonConflationRequest(
            request.mission_sha256,
            (self_concept, external_concept),
            (distinction,),
            tuple(dispositions),
            source_text,
            evidence_sha256(source_text),
        )
        vector_sha = semantic_vector_sha256(semantic_request)
        return SemanticNonConflationRequest(
            semantic_request.mission_sha256,
            semantic_request.concepts,
            semantic_request.distinctions,
            semantic_request.dispositions,
            semantic_request.source_text,
            semantic_request.source_text_sha256,
            vector_sha,
            vector_sha,
        )

    def _request_payload(self, request: object) -> object:
        return request.__dict__ if isinstance(request, RobotHandoffRequest) else {"request": repr(request)}

    def _finish(self, decision: Decision, state: str, reasons: tuple[str, ...], semantic_receipt: str, certificate_sha: str | None, request_sha: str) -> RobotHandoffEvaluation:
        payload = {
            "component": COMPONENT_ID,
            "version": VERSION,
            "decision": decision.value,
            "state": state,
            "reasons": reasons,
            "semantic_receipt_sha256": semantic_receipt,
            "certificate_sha256": certificate_sha,
            "request_sha256": request_sha,
        }
        return RobotHandoffEvaluation(decision, state, reasons, semantic_receipt, certificate_sha, request_sha, _sha(payload))


def _valid_sha(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _evidence_valid(evidence: object, digest: object) -> bool:
    return isinstance(evidence, str) and bool(evidence.strip()) and _valid_sha(digest) and evidence_sha256(evidence) == digest


def _sha(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=repr).encode("utf-8")).hexdigest()
