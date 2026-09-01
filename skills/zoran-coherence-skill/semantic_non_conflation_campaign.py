#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
from dataclasses import replace
from pathlib import Path

from robot_handoff_guard import RobotHandoffGuard, RobotHandoffRequest
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


MISSION = "a" * 64
CANDIDATE = "b" * 64
ROBOT_CERTIFICATE = json.loads((Path(__file__).resolve().parent / "audit" / "ROBOT_TEST_CERTIFICATE.json").read_text(encoding="utf-8"))
AUTHORITY_FINGERPRINT = ROBOT_CERTIFICATE["authority_fingerprint"]
VALIDATION_RECEIPT = ROBOT_CERTIFICATE["envelope_sha256"]


def _disposition(action_id: str, status: str, grounds: tuple[str, ...]) -> ActionDisposition:
    evidence = f"campaign disposition:{action_id}:{status}"
    return ActionDisposition(action_id, status, grounds, evidence, evidence_sha256(evidence))


def make_semantic_request() -> SemanticNonConflationRequest:
    source_text = "candidate cannot certify itself. host must submit candidate."
    self_evidence = "campaign concept:self certification prohibition"
    robot_evidence = "campaign concept:external validation requirement"
    distinction_evidence = "campaign distinction:authority differs from handoff"
    concepts = (
        SemanticConcept(
            "self_certification_prohibition", "candidate cannot certify itself", "candidate", CANDIDATE,
            "MUST_NOT", (), ("self_certify",), self_evidence, evidence_sha256(self_evidence),
            "candidate cannot certify itself", "candidate", "candidate", (), ("certify itself",),
        ),
        SemanticConcept(
            "external_validation_requirement", "host must submit candidate", "host", CANDIDATE,
            "MUST", ("submit_to_external_robot",), (), robot_evidence, evidence_sha256(robot_evidence),
            "host must submit candidate", "host", "candidate", ("submit candidate",), (),
        ),
    )
    distinction = SemanticDistinction(
        concepts[0].concept_id,
        concepts[1].concept_id,
        "different actors and different actions",
        "false only if self certification and external submission have identical operational identity",
        distinction_evidence,
        evidence_sha256(distinction_evidence),
    )
    request = SemanticNonConflationRequest(MISSION, concepts, (distinction,), (
        _disposition("self_certify", "BLOCKED", (concepts[0].concept_id,)),
        _disposition("submit_to_external_robot", "EXECUTED", (concepts[1].concept_id,)),
    ), source_text, evidence_sha256(source_text))
    vector_sha = semantic_vector_sha256(request)
    return replace(request, authorized_vector_sha256=vector_sha, regenerated_vector_sha256=vector_sha)


def make_robot_request(*, required=True, discovery=True, channel=True, submission=True, validation_status="PASS") -> RobotHandoffRequest:
    applicability = "campaign applicability:required" if required else "campaign applicability:not required"
    discovery_evidence = "campaign robot discovery complete"
    channel_evidence = "campaign robot channel resolved"
    submission_evidence = "campaign robot submission complete"
    return RobotHandoffRequest(
        MISSION, CANDIDATE, CANDIDATE, required, applicability, evidence_sha256(applicability),
        discovery_completed=discovery,
        discovery_evidence=discovery_evidence if discovery else None,
        discovery_evidence_sha256=evidence_sha256(discovery_evidence) if discovery else None,
        channel_id="zoran-host:dual-robot-v1" if channel else None,
        channel_evidence=channel_evidence if channel else None,
        channel_evidence_sha256=evidence_sha256(channel_evidence) if channel else None,
        submission_id=f"sha256:{CANDIDATE}" if submission else None,
        submission_evidence=submission_evidence if submission else None,
        submission_evidence_sha256=evidence_sha256(submission_evidence) if submission else None,
        validation_status=validation_status,
        validation_receipt_sha256=VALIDATION_RECEIPT if validation_status in {"PASS", "FAIL"} else None,
        authority_id=ROBOT_CERTIFICATE["authority_id"] if validation_status in {"PASS", "FAIL"} else None,
        authority_fingerprint=AUTHORITY_FINGERPRINT if validation_status in {"PASS", "FAIL"} else None,
        certification_envelope=ROBOT_CERTIFICATE if validation_status == "PASS" else None,
    )


def robot_registry():
    """Compatibility shim: trust is pinned inside the candidate, never caller supplied."""
    return None


def expected_semantic(self_status: str, submit_status: str, submit_ground: str) -> Decision:
    if self_status == "EXECUTED":
        return Decision.VETO
    if submit_status in {"BLOCKED", "NOT_APPLICABLE"}:
        return Decision.VETO
    if submit_ground != "external_validation_requirement":
        return Decision.RETRY
    if self_status == "PENDING" or submit_status == "PENDING":
        return Decision.RETRY
    return Decision.PASS


def semantic_cases():
    statuses = ("EXECUTED", "PENDING", "BLOCKED", "NOT_APPLICABLE")
    grounds = ("external_validation_requirement", "self_certification_prohibition")
    base = make_semantic_request()
    for self_status, submit_status, submit_ground in itertools.product(statuses, statuses, grounds):
        dispositions = (
            _disposition("self_certify", self_status, ("self_certification_prohibition",)),
            _disposition("submit_to_external_robot", submit_status, (submit_ground,)),
        )
        request = replace(base, dispositions=dispositions, authorized_vector_sha256="", regenerated_vector_sha256="")
        vector_sha = semantic_vector_sha256(request)
        yield replace(request, authorized_vector_sha256=vector_sha, regenerated_vector_sha256=vector_sha), expected_semantic(self_status, submit_status, submit_ground)


def robot_cases():
    scenarios = (
        (dict(required=False, discovery=False, channel=False, submission=False, validation_status=None), Decision.PASS),
        (dict(discovery=False, channel=False, submission=False, validation_status=None), Decision.RETRY),
        (dict(channel=False, submission=False, validation_status=None), Decision.RETRY),
        (dict(submission=False, validation_status=None), Decision.RETRY),
        (dict(validation_status="PENDING"), Decision.RETRY),
        (dict(validation_status="FAIL"), Decision.VETO),
        (dict(validation_status="PASS"), Decision.PASS),
    )
    for kwargs, expected in scenarios:
        yield make_robot_request(**kwargs), expected


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--replays", type=int, default=10000)
    parser.add_argument("--output", type=Path, default=Path("SEMANTIC_NON_CONFLATION_CAMPAIGN_RESULTS.json"))
    args = parser.parse_args()
    semantic_engine = SemanticNonConflationEngine()
    robot_engine = RobotHandoffGuard(semantic_engine)
    cases = list(semantic_cases())
    robot = list(robot_cases())
    false_pass = 0
    false_block = 0
    receipts = []
    for request, expected in cases:
        result = semantic_engine.evaluate(request)
        receipts.append(result.receipt_sha256)
        false_pass += int(result.decision is Decision.PASS and expected is not Decision.PASS)
        false_block += int(result.decision is not Decision.PASS and expected is Decision.PASS)
        if result.decision is not expected:
            raise SystemExit(f"semantic mismatch: expected={expected.value} actual={result.decision.value} reasons={result.reasons}")
    for request, expected in robot:
        result = robot_engine.evaluate(request)
        receipts.append(result.receipt_sha256)
        false_pass += int(result.decision is Decision.PASS and expected is not Decision.PASS)
        false_block += int(result.decision is not Decision.PASS and expected is Decision.PASS)
        if result.decision is not expected:
            raise SystemExit(f"robot mismatch: expected={expected.value} actual={result.decision.value} reasons={result.reasons}")

    replay_seed = cases[0][0]
    expected_receipt = semantic_engine.evaluate(replay_seed).receipt_sha256
    divergences = sum(semantic_engine.evaluate(replay_seed).receipt_sha256 != expected_receipt for _ in range(args.replays))
    payload = {
        "component": "zoran.semantic-non-conflation-campaign-v1",
        "semantic_cases": len(cases),
        "robot_cases": len(robot),
        "total_cases": len(cases) + len(robot),
        "false_pass": false_pass,
        "false_block": false_block,
        "deterministic_replays": args.replays,
        "replay_divergences": divergences,
        "receipt_set_sha256": hashlib.sha256("\n".join(receipts).encode("utf-8")).hexdigest(),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    args.output.write_text(raw + "\n", encoding="utf-8")
    print(raw)
    if false_pass or false_block or divergences:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
