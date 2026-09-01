from dataclasses import replace

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
SOURCE_TEXT = "candidate cannot certify itself. host must submit candidate."


def _bind(request):
    vector = semantic_vector_sha256(request)
    return replace(request, authorized_vector_sha256=vector, regenerated_vector_sha256=vector)


def _concept(concept_id, *, definition, required=(), forbidden=()):
    evidence = f"source semantics:{concept_id}"
    is_self = concept_id == "self_certification_prohibition"
    return SemanticConcept(
        concept_id,
        definition,
        f"actor:{concept_id}",
        f"object:{concept_id}",
        "MUST" if required else "MUST_NOT",
        tuple(required),
        tuple(forbidden),
        evidence,
        evidence_sha256(evidence),
        definition,
        "candidate" if is_self else "host",
        "candidate",
        ("submit candidate",) if required else (),
        ("certify itself",) if forbidden else (),
    )


def _distinction(left="self_certification_prohibition", right="external_validation_requirement"):
    evidence = "authority does not equal handoff"
    return SemanticDistinction(
        left,
        right,
        "different actors and different actions",
        "false only if the two named actions have the same operational identity",
        evidence,
        evidence_sha256(evidence),
    )


def _disposition(action_id, status, grounds):
    evidence = f"action disposition:{action_id}:{status}"
    return ActionDisposition(action_id, status, tuple(grounds), evidence, evidence_sha256(evidence))


def make_request(*, submit_status="EXECUTED", submit_grounds=("external_validation_requirement",)):
    concepts = (
        _concept("self_certification_prohibition", definition="candidate cannot certify itself", forbidden=("self_certify",)),
        _concept("external_validation_requirement", definition="host must submit candidate", required=("submit_to_external_robot",)),
    )
    request = SemanticNonConflationRequest(
        MISSION,
        concepts,
        (_distinction(),),
        (
            _disposition("self_certify", "BLOCKED", ("self_certification_prohibition",)),
            _disposition("submit_to_external_robot", submit_status, submit_grounds),
        ),
        SOURCE_TEXT,
        evidence_sha256(SOURCE_TEXT),
    )
    return _bind(request)


def test_distinct_obligations_with_exact_actions_pass():
    result = SemanticNonConflationEngine().evaluate(make_request())
    assert result.decision is Decision.PASS
    assert result.reasons == ("SEMANTIC_NON_CONFLATION_ADMISSIBLE",)


def test_nonmatching_prohibition_cannot_block_required_robot_handoff():
    request = make_request(submit_status="BLOCKED", submit_grounds=("self_certification_prohibition",))
    result = SemanticNonConflationEngine().evaluate(request)
    assert result.decision is Decision.VETO
    assert "REQUIRED_ACTION_BLOCKED_BY_NONMATCHING_PROHIBITION:submit_to_external_robot" in result.reasons


def test_required_action_pending_is_retry_not_pass():
    result = SemanticNonConflationEngine().evaluate(make_request(submit_status="PENDING"))
    assert result.decision is Decision.RETRY
    assert "REQUIRED_ACTION_PENDING:submit_to_external_robot" in result.reasons


def test_required_action_cannot_be_erased_as_not_applicable():
    result = SemanticNonConflationEngine().evaluate(make_request(submit_status="NOT_APPLICABLE"))
    assert result.decision is Decision.VETO


def test_every_concept_pair_requires_explicit_falsifiable_distinction():
    request = replace(make_request(), distinctions=())
    result = SemanticNonConflationEngine().evaluate(request)
    assert result.decision is Decision.RETRY
    assert result.reasons == ("DISTINCTION_UNDECLARED:external_validation_requirement:self_certification_prohibition",)


def test_identical_concepts_cannot_be_declared_distinct():
    request = make_request()
    first = request.concepts[0]
    evidence = "source semantics:duplicate"
    duplicate = replace(first, concept_id="duplicate", evidence=evidence, evidence_sha256=evidence_sha256(evidence))
    relation = _distinction(first.concept_id, duplicate.concept_id)
    dispositions = (_disposition("self_certify", "BLOCKED", (first.concept_id, duplicate.concept_id)),)
    duplicate_source = "candidate cannot certify itself. candidate cannot certify itself."
    request = SemanticNonConflationRequest(MISSION, (first, duplicate), (relation,), dispositions, duplicate_source, evidence_sha256(duplicate_source))
    result = SemanticNonConflationEngine().evaluate(_bind(request))
    assert result.decision is Decision.VETO
    assert any(reason.startswith("DISTINCT_CONCEPTS_SEMANTICALLY_IDENTICAL") for reason in result.reasons)


def test_cross_concept_required_forbidden_collision_is_veto():
    request = make_request()
    second = replace(request.concepts[1], required_action_ids=("submit_to_external_robot", "self_certify"))
    result = SemanticNonConflationEngine().evaluate(_bind(replace(request, concepts=(request.concepts[0], second))))
    assert result.decision is Decision.VETO
    assert "ACTION_NORM_CONFLICT:self_certify" in result.reasons


def test_forbidden_action_execution_is_veto():
    request = make_request()
    dispositions = (_disposition("self_certify", "EXECUTED", ("self_certification_prohibition",)), request.dispositions[1])
    result = SemanticNonConflationEngine().evaluate(_bind(replace(request, dispositions=dispositions)))
    assert result.decision is Decision.VETO
    assert "FORBIDDEN_ACTION_EXECUTED:self_certify" in result.reasons


def test_forbidden_action_enforcement_pending_is_retry():
    request = make_request()
    dispositions = (_disposition("self_certify", "PENDING", ("self_certification_prohibition",)), request.dispositions[1])
    result = SemanticNonConflationEngine().evaluate(_bind(replace(request, dispositions=dispositions)))
    assert result.decision is Decision.RETRY
    assert "FORBIDDEN_ACTION_ENFORCEMENT_PENDING:self_certify" in result.reasons


def test_missing_action_disposition_is_retry():
    request = replace(make_request(), dispositions=make_request().dispositions[:1])
    result = SemanticNonConflationEngine().evaluate(_bind(request))
    assert result.decision is Decision.RETRY
    assert "ACTION_DISPOSITION_MISSING:submit_to_external_robot" in result.reasons


def test_evidence_tamper_is_retry():
    request = make_request()
    damaged = replace(request.concepts[0], evidence="tampered")
    result = SemanticNonConflationEngine().evaluate(replace(request, concepts=(damaged, request.concepts[1])))
    assert result.decision is Decision.RETRY
    assert "CONCEPT_EVIDENCE_INVALID:self_certification_prohibition" in result.reasons


def test_every_concept_must_bind_an_exact_source_quote():
    request = make_request()
    damaged = replace(request.concepts[0], source_quote="words absent from source")
    result = SemanticNonConflationEngine().evaluate(replace(request, concepts=(damaged, request.concepts[1])))
    assert result.decision is Decision.RETRY
    assert result.reasons == ("SEMANTIC_SOURCE_CLAUSE_COVERAGE_INCOMPLETE",)


def test_source_text_digest_tamper_is_retry():
    result = SemanticNonConflationEngine().evaluate(replace(make_request(), source_text="tampered"))
    assert result.decision is Decision.RETRY
    assert result.reasons == ("SEMANTIC_SOURCE_TEXT_INVALID",)


def test_source_clause_omission_is_retry():
    request = make_request()
    source = SOURCE_TEXT + " robot must promote candidate."
    result = SemanticNonConflationEngine().evaluate(replace(request, source_text=source, source_text_sha256=evidence_sha256(source)))
    assert result.decision is Decision.RETRY
    assert result.reasons == ("SEMANTIC_SOURCE_CLAUSE_COVERAGE_INCOMPLETE",)


def test_semantic_roundtrip_divergence_is_veto():
    result = SemanticNonConflationEngine().evaluate(replace(make_request(), regenerated_vector_sha256="f" * 64))
    assert result.decision is Decision.VETO
    assert result.reasons == ("SEMANTIC_ROUNDTRIP_DIVERGENCE",)


def test_authorized_vector_substitution_is_veto():
    result = SemanticNonConflationEngine().evaluate(replace(make_request(), authorized_vector_sha256="f" * 64))
    assert result.decision is Decision.VETO
    assert result.reasons == ("AUTHORIZED_SEMANTIC_VECTOR_MISMATCH",)


def test_unknown_concept_in_distinction_is_veto():
    request = replace(make_request(), distinctions=(_distinction(right="unknown"),))
    result = SemanticNonConflationEngine().evaluate(request)
    assert result.decision is Decision.VETO
    assert "DISTINCTION_CONCEPT_REFERENCE_INVALID" in result.reasons


def test_receipt_is_deterministic_and_request_bound():
    engine = SemanticNonConflationEngine()
    first = engine.evaluate(make_request())
    second = engine.evaluate(make_request())
    changed = engine.evaluate(replace(make_request(), mission_sha256="b" * 64))
    assert first.receipt_sha256 == second.receipt_sha256
    assert changed.receipt_sha256 != first.receipt_sha256
