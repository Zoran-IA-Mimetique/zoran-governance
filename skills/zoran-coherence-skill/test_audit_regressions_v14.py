from __future__ import annotations

import hashlib
import os
import sqlite3
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor

import pytest

from bounded_truth_engine import BoundedTruthStatus, Relation, SourceEvidence, SourceKind, evaluate_bounded_truth
from delivery_reviewer import DeliveryReviewRequest, DeliveryReviewer, ReviewCheck
from github_mirror import GithubMirror, MirrorEvaluation, MirrorFile, MirrorSnapshot, REPO
from sensor_layer import sense
from source_coherence import SourceClaim, SourceCoherenceEngine
from terminal_controller import ControlEvidence, REQUIRED_CONTROL_IDS, TerminalController
from test_sensor_layer import clean_bundle
from tolerance_skill import Decision, DimensionPolicy, MulticriteriaToleranceSkill, Observation, TOLERANCE_FAMILIES, TolerancePolicy, scope_for
from zmos_coherence_selector import ZmosCoherenceSelector, ZmosObject
from zmos_memory import MemoryRecord, ZmosIntegrityError, ZmosMemory

H = "a" * 64


def test_required_terminal_surfaces_cannot_be_bypassed_as_optional():
    controls = [ControlEvidence(x, False, False, "BOGUS", None) for x in REQUIRED_CONTROL_IDS]
    assert TerminalController().evaluate(controls).status != "PASS"


def test_intrinsic_terminal_requirement_cannot_be_disabled_even_with_trusted_pass():
    controls = [ControlEvidence(x, False, True, "PASS", H) for x in REQUIRED_CONTROL_IDS]
    trust = {x.control_id: x.receipt_sha256 for x in controls}
    verdict = TerminalController().evaluate(controls, trusted_receipts=trust)
    assert verdict.status != "PASS"
    assert set(verdict.reasons) == {
        f"CONTROL_INTRINSIC_REQUIREMENT_DISABLED:{x}" for x in REQUIRED_CONTROL_IDS
    }


def test_frame_definition_is_deeply_sealed_after_validation():
    from frame_search import FrameDefinition, FrameSearchEngine

    keywords = ["alpha"]
    engine = FrameSearchEngine([FrameDefinition("f", "frame", keywords)])
    assert engine.search("alpha").decision is Decision.PASS
    keywords[:] = ["omega"]
    assert engine.search("alpha").decision is Decision.PASS
    assert engine.search("omega").decision is Decision.RETRY


def test_prompt_quality_policy_is_deeply_sealed_after_validation():
    from prompt_quality import PromptQualityEngine, PromptQualityPolicy

    ambiguity = ["foo"]
    engine = PromptQualityEngine(PromptQualityPolicy(ambiguity_terms=ambiguity, max_ambiguity_hits=0))
    assert engine.evaluate("foo").decision is Decision.RETRY
    ambiguity.clear()
    assert engine.evaluate("foo").decision is Decision.RETRY


def test_prompt_quality_required_alias_matches_token_boundaries_and_generators_once():
    from prompt_quality import EvaluatorCriterion, PromptQualityEngine

    engine = PromptQualityEngine()
    assert engine.evaluate("unsafe output", evaluator_criteria=(EvaluatorCriterion("safety", ("safe",)),)).decision is Decision.RETRY
    criteria = (item for item in (EvaluatorCriterion("required", ("missing",)),))
    assert engine.evaluate("hello", evaluator_criteria=criteria).decision is Decision.RETRY


def test_decomposition_schema_registry_is_deeply_sealed():
    from decomposition_calibration import CalibrationProfile, DecompositionCalibrationEngine, DecompositionSchema, PartRule

    parts = [PartRule("p", "critical", "profile")]
    schema = DecompositionSchema("domain", "1", parts)
    profile = CalibrationProfile("profile", {"coherence": 0.0}, ("coherence",), H)
    engine = DecompositionCalibrationEngine([schema], [profile])
    before = engine.registry_sha256
    parts.append(PartRule("q", "critical", "profile"))
    assert engine.evaluate("domain", observed_parts=("p",)).decision is Decision.PASS
    assert engine.registry_sha256 == before


def test_polymorphic_family_registry_is_deeply_sealed_and_receipt_binds_context():
    from polymorphic_family_engine import FamilySpec, PolymorphicFamilyEngine, SelectionContext

    triggers = ["alpha"]
    engine = PolymorphicFamilyEngine([FamilySpec("custom", "Custom", keyword_triggers=triggers, calibration_required=False)])
    alpha = SelectionContext("alpha", "domain", "object", ())
    first = engine.select(alpha)
    triggers[:] = ["omega"]
    second = engine.select(alpha)
    assert first.extensions == second.extensions
    assert first.receipt_sha256 == second.receipt_sha256
    assert engine.select(SelectionContext("alpha beta", "domain", "object", ())).receipt_sha256 != first.receipt_sha256


def test_duplicate_terminal_control_is_fail_closed():
    controls = [ControlEvidence(x, True, True, "PASS", H) for x in REQUIRED_CONTROL_IDS]
    controls.insert(0, ControlEvidence("k3_post", True, True, "FAIL", H))
    verdict = TerminalController().evaluate(controls,trusted_receipts={x.control_id:x.receipt_sha256 for x in controls})
    assert verdict.status == "FAIL"
    assert "DUPLICATE_CONTROL_ID:k3_post" in verdict.reasons


def _review_checks(objective: str, code_counts=(0,)):
    digest = hashlib.sha256(objective.encode()).hexdigest()
    return (
        ReviewCheck("done", "DONE", "PASS", True, H, ("objective",), "done", objective_sha256=digest),
        ReviewCheck("objective", "OBJECTIVE_CONFORMITY", "PASS", True, H, ("objective",), "objective", objective_sha256=digest),
        ReviewCheck("multi", "MULTIFRAME_COHERENCE", "PASS", True, H, ("local", "global"), "multi", objective_sha256=digest),
        *(ReviewCheck(f"code{i}", "CODE_QUALITY", "PASS", True, H, ("code",), "code", observed_defects=count, objective_sha256=digest) for i, count in enumerate(code_counts)),
        ReviewCheck("coherence", "COHERENCE_QUALITY", "PASS", True, H, ("coherence",), "coherence", observed_defects=0, objective_sha256=digest),
        ReviewCheck("evidence", "EVIDENCE_COMPLETENESS", "PASS", True, H, ("proof",), "evidence", objective_sha256=digest),
        ReviewCheck("independent", "INDEPENDENT_REVIEW", "PASS", True, H, ("review",), "independent", objective_sha256=digest),
    )


def test_negative_defect_cannot_compensate_positive_defect():
    objective = "objective"
    request = DeliveryReviewRequest("D", objective, "builder", "reviewer", ("a.py",), ("a.py",), _review_checks(objective, (1, -1)))
    verdict = DeliveryReviewer().evaluate(request)
    assert verdict.status != "PASS"
    assert "CODE_DEFECT_COUNT_INVALID" in verdict.reasons


def test_delivery_checks_bind_exact_objective_digest():
    objective = "objective"
    checks = list(_review_checks(objective))
    checks[0] = replace(checks[0], objective_sha256="b" * 64)
    request = DeliveryReviewRequest("D", objective, "builder", "reviewer", ("a.py",), ("a.py",), tuple(checks))
    assert DeliveryReviewer().evaluate(request).status != "PASS"


def test_policy_is_deeply_sealed_after_validation():
    dims = {name: DimensionPolicy(0.0, 0.0, zero_tolerance=True) for name in TOLERANCE_FAMILIES}
    policy = TolerancePolicy(dims, {"generic": 10.0}, {"local": 10.0}, 10.0)
    engine = MulticriteriaToleranceSkill(policy)
    dims["safety"] = DimensionPolicy(1.0, 1.0, zero_tolerance=False)
    result = engine.evaluate([Observation("s", "safety", 0.5, 1.0, "generic", "local")], scope=scope_for("safety"))
    assert result.decision is Decision.VETO


def test_tolerance_receipt_binds_input_even_on_early_failure():
    engine = MulticriteriaToleranceSkill(__import__("tolerance_skill").conservative_default_policy())
    a = engine.evaluate([Observation("a", "safety", 1.0, 1.0, "generic", "local")], scope=scope_for("safety"))
    b = engine.evaluate([Observation("b", "safety", 2.0, 1.0, "generic", "local")], scope=scope_for("safety"))
    assert a.receipt_sha256 != b.receipt_sha256


def test_mapping_string_false_is_not_truthy_evidence():
    evidence = [{"source_id": "a", "source_kind": "OFFICIAL_PRIMARY", "relation": "SUPPORTS", "independent_group": "g", "text_sha256": H, "retrieved": "false"}]
    assert evaluate_bounded_truth("claim", evidence).status is BoundedTruthStatus.RETRY


def test_duplicate_content_cannot_claim_strong_independence():
    evidence = [
        SourceEvidence("a", SourceKind.OFFICIAL_PRIMARY, Relation.SUPPORTS, "g1", H),
        SourceEvidence("b", SourceKind.PEER_REVIEWED_PRIMARY, Relation.SUPPORTS, "g2", H),
    ]
    result = evaluate_bounded_truth("claim", evidence)
    assert result.status is not BoundedTruthStatus.STRONGLY_SUPPORTED
    assert "CONTENT_DIGEST_REUSED_ACROSS_INDEPENDENCE_GROUPS" in result.limitations


def test_bounded_truth_receipt_binds_full_source_digest_and_rejects_none_identity():
    a = SourceEvidence("s", SourceKind.OFFICIAL_PRIMARY, Relation.SUPPORTS, "g", "a" * 64)
    b = SourceEvidence("s", SourceKind.OFFICIAL_PRIMARY, Relation.SUPPORTS, "g", "b" * 64)
    assert evaluate_bounded_truth("claim", (a,)).receipt_sha256 != evaluate_bounded_truth("claim", (b,)).receipt_sha256
    invalid = {"source_id": None, "source_kind": "OFFICIAL_PRIMARY", "relation": "SUPPORTS", "independent_group": None, "text_sha256": H}
    assert evaluate_bounded_truth("claim", (invalid,)).status is BoundedTruthStatus.RETRY


def test_parallel_context_receipt_binds_question_candidate_and_fragment_content():
    from parallel_context_guard import ParallelContextGuard, build_memory_fragment

    guard = ParallelContextGuard()
    a = build_memory_fragment(fragment_id="f", source="HOST_MEMORY", text="alpha project", provenance="p")
    b = build_memory_fragment(fragment_id="f", source="HOST_MEMORY", text="beta project", provenance="p")
    first = guard.evaluate(doubt=True, question="alpha project", candidate="candidate a", fragments=(a,))
    changed_candidate = guard.evaluate(doubt=True, question="alpha project", candidate="candidate b", fragments=(a,))
    changed_fragment = guard.evaluate(doubt=True, question="alpha project", candidate="candidate a", fragments=(b,))
    assert len({first.receipt_sha256, changed_candidate.receipt_sha256, changed_fragment.receipt_sha256}) == 3


def test_memory_context_outer_receipt_binds_provider_outcome():
    from memory_context_integration import check_memory_context_on_doubt

    absent = check_memory_context_on_doubt(doubt=True, question="q", candidate="c", memory_provider=None)
    def broken(question, candidate):
        raise RuntimeError("offline")
    failed = check_memory_context_on_doubt(doubt=True, question="q", candidate="c", memory_provider=broken)
    assert absent.code == "MEMORY_CONTEXT_NOT_EXPOSED"
    assert failed.code == "HOST_MEMORY_QUERY_FAILED"
    assert absent.receipt_sha256 != failed.receipt_sha256


def test_zmos_selector_receipt_binds_invalid_object_input_and_limits():
    selector = ZmosCoherenceSelector()
    a = selector.select((ZmosObject("", "alpha", "SUPPORTE", 1, "10", H),), max_chars=10)
    b = selector.select((ZmosObject("", "beta", "SUPPORTE", 1, "10", H),), max_chars=10)
    c = selector.select((ZmosObject("", "alpha", "SUPPORTE", 1, "10", H),), max_chars=11)
    assert len({a.receipt_sha256, b.receipt_sha256, c.receipt_sha256}) == 3


def test_zmos_empty_recall_digest_binds_query(tmp_path):
    with ZmosMemory(tmp_path / "empty.db") as memory:
        alpha = memory.recall("alpha")
        beta = memory.recall("beta")
    assert alpha.decision is Decision.PASS
    assert beta.decision is Decision.PASS
    assert alpha.context_digest != beta.context_digest


def test_duplicate_source_ids_fail_closed():
    evidence = [
        SourceEvidence("a", SourceKind.OFFICIAL_PRIMARY, Relation.SUPPORTS, "g1", H),
        SourceEvidence("a", SourceKind.OFFICIAL_PRIMARY, Relation.SUPPORTS, "g2", "b" * 64),
    ]
    assert evaluate_bounded_truth("claim", evidence).status is BoundedTruthStatus.RETRY


@pytest.mark.parametrize("dimension", ("numeric", "measurement", "safety", "resource"))
def test_nonfinite_sensor_contract_never_looks_measured_clean(dimension):
    base = clean_bundle()
    if dimension == "numeric":
        bundle = replace(base, numeric_expectations=(replace(base.numeric_expectations[0], value=float("nan")),))
    elif dimension == "measurement":
        bundle = replace(base, measurement_uncertainty=float("nan"))
    elif dimension == "safety":
        bundle = replace(base, safety_constraints=(replace(base.safety_constraints[0], limit=float("nan")),))
    else:
        bundle = replace(base, resource_used=float("nan"))
    observation = next(x for x in sense(bundle).observations if x.dimension == dimension)
    assert observation.evidence_measured is False


def test_source_quality_flag_is_strict_boolean():
    claim = SourceClaim("s", "c", "v", None, "o", "2026-01-01T00:00:00Z", quality_measured="false")
    assert SourceCoherenceEngine().evaluate([claim]).decision is Decision.RETRY


def test_derived_sources_share_one_provenance_root():
    claims = [
        SourceClaim("root", "c", "v", None, "publisher", "2026-01-01T00:00:00Z"),
        SourceClaim("copy", "c", "v", "root", "different-label", "2026-01-01T00:00:00Z"),
    ]
    result = SourceCoherenceEngine().evaluate(claims, require_independent=2)
    assert result.decision is Decision.RETRY
    assert result.independent_origins == 1


def test_relevant_contradiction_that_does_not_fit_blocks_recall():
    obj = ZmosObject("c", "contradiction", "CONTRADICTOIRE", 10, "5", H)
    result = ZmosCoherenceSelector().select([obj], max_objects=0)
    assert result.decision is Decision.RETRY


def test_duplicate_memory_object_ids_are_rejected():
    obj = ZmosObject("c", "content", "SUPPORTE", 10, "5", H)
    assert ZmosCoherenceSelector().select([obj, obj]).decision is Decision.VETO


@pytest.mark.parametrize("column,value", (("score_s", "99"), ("modality", "PROUVE"), ("frame_ids", '[\"tampered\"]'), ("provenance_sha256", "b" * 64)))
def test_zmos_record_metadata_tamper_is_detected(tmp_path, column, value):
    path = tmp_path / "z.db"
    with ZmosMemory(path) as memory:
        memory.append(MemoryRecord("r", "c", "t", "content", "CANDIDATE", frame_ids=("f",), score_s="7", decision="RETRY", provenance_sha256=H, timestamp="2026-01-01T00:00:00Z"))
        memory.conn.execute(f"UPDATE records SET {column}=? WHERE record_id='r'", (value,))
        with pytest.raises(ZmosIntegrityError):
            memory.verify()


def test_zmos_rejects_out_of_range_score(tmp_path):
    with ZmosMemory(tmp_path / "z.db") as memory:
        with pytest.raises(Exception):
            memory.append(MemoryRecord("r", "c", "t", "content", "CANDIDATE", score_s="101", decision="RETRY", provenance_sha256=H, timestamp="2026-01-01T00:00:00Z"))


def test_mirror_install_propagates_failed_post_verification(tmp_path):
    class FailingVerifier(GithubMirror):
        def verify(self, *, required: bool):
            return MirrorEvaluation(Decision.RETRY, None, None, None, ("FORCED_VERIFY_FAILURE",))

    content = b"x"
    snapshot = MirrorSnapshot(REPO, "a" * 40, "FULL", (MirrorFile("x", content, hashlib.sha256(content).hexdigest()),))
    assert FailingVerifier(tmp_path / "mirror").install(snapshot, max_full_bytes=10).decision is Decision.RETRY


def test_targeted_mirror_cannot_exceed_byte_limit(tmp_path):
    content = b"xx"
    snapshot = MirrorSnapshot(REPO, "a" * 40, "FULL", (MirrorFile("allowed/x", content, hashlib.sha256(content).hexdigest()),))
    result = GithubMirror(tmp_path / "mirror").install(snapshot, max_full_bytes=1, allowlist=("allowed",))
    assert result.decision is Decision.RETRY


def test_same_declared_origin_group_is_one_provenance_root():
    claims = [
        SourceClaim("a", "c", "v", None, "same", "2026-01-01T00:00:00Z"),
        SourceClaim("b", "c", "v", None, "same", "2026-01-01T00:00:00Z"),
    ]
    result = SourceCoherenceEngine().evaluate(claims, require_independent=2)
    assert result.decision is Decision.RETRY and result.independent_origins == 1


def test_extra_terminal_control_requires_strict_booleans():
    controls = [ControlEvidence(x, True, True, "PASS", H) for x in REQUIRED_CONTROL_IDS]
    controls.append(ControlEvidence("extra", True, 1, "PASS", H))
    trust = {x.control_id: x.receipt_sha256 for x in controls}
    assert TerminalController().evaluate(controls, trusted_receipts=trust).status != "PASS"


def test_delivery_rejects_path_aliases():
    objective = "objective"
    request = DeliveryReviewRequest("D", objective, "builder", "reviewer", ("a/b", "a/./b"), ("a/b", "a/./b"), _review_checks(objective))
    assert DeliveryReviewer().evaluate(request).status == "FAIL"


def test_activation_receipt_binds_installation_and_license():
    from activation_guard import ActivationGuard, AmygdalaLicense, MonthlyEntitlement, AMYGDALA_ID, AMYGDALA_MANIFEST_SHA256, canonical_payload
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization
    import base64

    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    amygdala = AmygdalaLicense(AMYGDALA_ID, AMYGDALA_MANIFEST_SHA256, "2026-01-01T00:00:00Z", "2026-12-31T00:00:00Z")

    def activate(license_id, installation):
        body = {"license_id": license_id, "installation_sha512": installation, "valid_from": "2026-08-01T00:00:00Z", "valid_until": "2026-09-01T00:00:00Z"}
        entitlement = MonthlyEntitlement(**body, signature_b64=base64.b64encode(key.sign(canonical_payload(body))).decode())
        return ActivationGuard(public).verify(amygdala, entitlement, expected_license_id=license_id, expected_installation_sha512=installation, now="2026-08-15T00:00:00Z")

    assert activate("L1", "a" * 128).receipt_sha256 != activate("L2", "b" * 128).receipt_sha256


def test_invalid_explicit_coherence_score_is_not_silently_trace_pending_pass():
    obj = ZmosObject("x", "content", "SUPPORTE", 1, "garbage", H)
    assert ZmosCoherenceSelector().select([obj]).decision is Decision.RETRY


def test_nested_hard_contract_is_deeply_frozen():
    from tolerance_skill import HardContract
    nested = {"cfg": {"flag": True}}
    policy = __import__("tolerance_skill").conservative_default_policy()
    engine = MulticriteriaToleranceSkill(policy, HardContract(nested))
    nested["cfg"]["flag"] = False
    observation = Observation("s", "coherence", 0.0, 1.0, "generic", "local", invariant_observed={"cfg": {"flag": False}})
    assert engine.evaluate([observation], scope=scope_for("coherence")).decision is Decision.VETO


def test_proxy_measurement_flag_and_bounds_are_fail_closed():
    from proxy_engine import ProxyEngine, ProxyMeasurement
    values = {k: ProxyMeasurement(k, 0, "e", True) for k in ("beta", "dphi", "T", "sigma")}
    values["beta"] = ProxyMeasurement("beta", 100, "e", "false")
    assert ProxyEngine().evaluate(values).decision is not Decision.PASS


@pytest.mark.parametrize("total,read", ((True, [True]), (1.9, [1]), (2, [1.2])))
def test_read_progress_rejects_bool_and_fractional_units(total, read):
    from read_progress import ReadProgressTracker
    with pytest.raises(ValueError):
        ReadProgressTracker().evaluate(object_id="o", object_type="pdf", total_units=total, read_units=read)


def test_untrusted_atomic_bundle_cannot_create_zero_gain_pass():
    from progress_guard import AtomicBundleProof, ProgressAttempt, ProgressGuard, ProgressPolicy
    bundle = AtomicBundleProof("b", "s", 0, 2, 2.0, 1.0, 1.0, 2.0, H, True, True)
    attempt = ProgressAttempt("a", "state", "action", "context", 1.0, 1.0, 1.0, atomic_bundle=bundle)
    policy = ProgressPolicy("o", "maximize", 10.0, min_absolute_gain=1.0)
    assert ProgressGuard(policy).evaluate(attempt).decision is Decision.RETRY


def test_progress_receipt_binds_attempt_identity_context_and_cost():
    from progress_guard import ProgressAttempt, ProgressGuard, ProgressPolicy
    guard = ProgressGuard(ProgressPolicy("o", "maximize", 10.0, min_absolute_gain=0.1))
    a = guard.evaluate(ProgressAttempt("a", "state", "action", "ctx-a", 1.0, 2.0, 1.0))
    b = guard.evaluate(ProgressAttempt("b", "state", "action", "ctx-b", 1.0, 2.0, 2.0))
    assert a.receipt_sha256 != b.receipt_sha256


def test_progress_receipt_binds_nonrepeating_history():
    from progress_guard import ProgressAttempt, ProgressGuard, ProgressHistoryEntry, ProgressPolicy
    guard = ProgressGuard(ProgressPolicy("o", "maximize", 10.0, min_absolute_gain=0.1))
    attempt = ProgressAttempt("a", "state", "action", "ctx", 1.0, 2.0, 1.0)
    empty = guard.evaluate(attempt, ())
    with_history = guard.evaluate(attempt, (ProgressHistoryEntry("other|action", "after", "PASS", H),))
    assert empty.decision is Decision.PASS and with_history.decision is Decision.PASS
    assert empty.receipt_sha256 != with_history.receipt_sha256


def test_atomic_bundle_step_replay_and_out_of_order_step_are_blocked():
    from progress_guard import AtomicBundleProof, ProgressAttempt, ProgressGuard, ProgressPolicy
    proof0=AtomicBundleProof("bundle","step-0",0,2,2.0,1.0,1.0,2.0,H,True,True)
    guard=ProgressGuard(ProgressPolicy("o","maximize",10.0,min_absolute_gain=1.0),trusted_bundle_receipts=(H,))
    first_attempt=ProgressAttempt("a0","s0","act0","ctx",1.0,1.0,1.0,atomic_bundle=proof0)
    first=guard.evaluate(first_attempt)
    history=(guard.history_entry(first_attempt,first,"s1"),)
    replay=guard.evaluate(ProgressAttempt("a1","other","other","ctx",1.0,1.0,1.0,atomic_bundle=proof0),history)
    proof_gap=AtomicBundleProof("bundle","step-gap",3,4,2.0,1.0,1.0,2.0,H,True,True)
    gap=guard.evaluate(ProgressAttempt("a2","s2","act2","ctx",1.0,1.0,1.0,atomic_bundle=proof_gap),history)
    assert first.decision is Decision.PASS
    assert replay.decision is Decision.VETO
    assert gap.decision is Decision.RETRY


def test_required_decomposition_parts_cannot_pass_by_empty_observation():
    from decomposition_calibration import CalibrationProfile, DecompositionCalibrationEngine, DecompositionSchema, PartRule
    engine = DecompositionCalibrationEngine((DecompositionSchema("d", "1", (PartRule("p", "critical", "z"),)),), (CalibrationProfile("z", {"safety": 0.0}, ("safety",), H),))
    assert engine.evaluate("d", observed_parts=()).decision is Decision.RETRY


def test_decomposition_rejects_unregistered_calibration_dimensions():
    from decomposition_calibration import CalibrationProfile, DecompositionCalibrationEngine, DecompositionSchema, PartRule
    with pytest.raises(ValueError):
        DecompositionCalibrationEngine((DecompositionSchema("d", "1", (PartRule("p", "critical", "z"),)),), (CalibrationProfile("z", {"totally_bogus": 0.0}, (), H),))


def test_law_engine_blocks_pass_by_omission():
    from law_engine import HardLaw, LawEngine
    assert LawEngine().evaluate(()).decision is Decision.RETRY
    assert LawEngine().evaluate((HardLaw("l", None, "<=", 1, None, applicable=False, exclusion_reason="not applicable"),)).decision is Decision.RETRY
    mixed=(HardLaw("", None, "<=", 1, None, applicable=False, exclusion_reason="not applicable"),HardLaw("valid", 1, "<=", 1, "e"))
    assert LawEngine().evaluate(mixed).decision is Decision.RETRY


def test_interchat_score_regression_is_veto_even_above_six():
    from interchat_guard import InterchatGuard
    result = InterchatGuard().evaluate(10, 9, previous_frames=("f",), current_frames=("f",), previous_proxies=("p",), current_proxies=("p",))
    assert result.decision is Decision.VETO


def test_dynamics_strict_validation_flag_and_score_bounds():
    from coherence_dynamics import CoherenceDynamics, CoherencePoint
    false_string = [CoherencePoint(0, 10, "false", ("f",), ("p",)), CoherencePoint(1, 11, True, ("f",), ("p",))]
    out_of_range = [CoherencePoint(0, 1000, True, ("f",), ("p",)), CoherencePoint(1, 1100, True, ("f",), ("p",))]
    assert CoherenceDynamics().evaluate(false_string).decision is Decision.RETRY
    assert CoherenceDynamics().evaluate(out_of_range).decision is Decision.RETRY


def test_frame_parent_cycle_is_rejected_at_registration():
    from frame_search import FrameDefinition, FrameSearchEngine
    with pytest.raises(ValueError):
        FrameSearchEngine((FrameDefinition("a", "A", ("a",), parent_id="b"), FrameDefinition("b", "B", ("b",), parent_id="a")))


def test_frame_multitoken_exclusion_matches_as_a_phrase():
    from frame_search import FrameDefinition, FrameSearchEngine
    engine = FrameSearchEngine((FrameDefinition("f", "F", ("foo",), excluded_terms=("not allowed",)),))
    assert engine.search("foo not allowed").decision is Decision.RETRY


def test_prompt_quality_rejects_nonfinite_policy_threshold():
    from prompt_quality import PromptQualityEngine, PromptQualityPolicy
    with pytest.raises(ValueError):
        PromptQualityEngine(PromptQualityPolicy(max_repeat_trigram_ratio=float("nan")))


def test_zmos_database_permissions_and_quota(tmp_path):
    path = tmp_path / "z.db"
    with ZmosMemory(path, max_storage_bytes=200_000) as memory:
        assert os.stat(path).st_mode & 0o077 == 0
        memory.append(MemoryRecord("r", "c", "t", "content", "CANDIDATE", decision="RETRY", provenance_sha256=H, timestamp="2026-01-01T00:00:00Z"))
    with ZmosMemory(tmp_path / "tiny.db", max_storage_bytes=1) as memory:
        with pytest.raises(Exception):
            memory.append(MemoryRecord("r", "c", "t", "content", "CANDIDATE", decision="RETRY", provenance_sha256=H, timestamp="2026-01-01T00:00:00Z"))


def test_latest_validated_score_verifies_integrity_before_read(tmp_path):
    with ZmosMemory(tmp_path / "score.db") as memory:
        memory.append(MemoryRecord("r", "c", "t", "content", "VALIDATED", score_s="1", decision="PASS", provenance_sha256=H, timestamp="2026-01-01T00:00:00Z", gate_receipt_sha256=H))
        memory.conn.execute("UPDATE records SET score_s='99' WHERE record_id='r'")
        with pytest.raises(ZmosIntegrityError):
            memory.latest_validated_score("c")


def test_zmos_concurrent_writers_keep_chain_consistent(tmp_path):
    path = tmp_path / "concurrent.db"
    with ZmosMemory(path):
        pass

    def writer(worker):
        with ZmosMemory(path) as memory:
            for index in range(10):
                rid = f"{worker}-{index}"
                memory.append(MemoryRecord(rid, "c", rid, "content", "CANDIDATE", decision="RETRY", provenance_sha256=H, timestamp="2026-01-01T00:00:00Z"))

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(writer, range(4)))
    with ZmosMemory(path) as memory:
        assert memory.verify() is True
        assert memory.conn.execute("SELECT count(*) FROM records").fetchone()[0] == 40


def test_tolerance_flags_and_evidence_flags_are_strict_booleans():
    from tolerance_skill import conservative_default_policy
    base = conservative_default_policy()
    bad_policy = replace(base, non_compensatory="false", deterministic="false", exact_boundary_accounting="false")
    engine = MulticriteriaToleranceSkill(bad_policy)
    observation = Observation("s", "coherence", 0.0, 1.0, "generic", "local", evidence_measured="false")
    assert engine.evaluate([observation], scope=scope_for("coherence")).decision is Decision.VETO
    clean = MulticriteriaToleranceSkill(base).evaluate([observation], scope=scope_for("coherence"))
    assert clean.decision is Decision.RETRY


def test_progress_evidence_flag_is_strict_boolean():
    from progress_guard import ProgressAttempt, ProgressGuard, ProgressPolicy
    result = ProgressGuard(ProgressPolicy("o", "maximize", 10.0)).evaluate(ProgressAttempt("a", "s", "a", "c", 1.0, 2.0, 1.0, evidence_measured="false"))
    assert result.decision is Decision.RETRY


def test_delivery_observed_flag_is_strict_boolean():
    objective = "objective"
    checks = tuple(replace(check, observed="false") for check in _review_checks(objective))
    request = DeliveryReviewRequest("D", objective, "builder", "reviewer", ("a.py",), ("a.py",), checks)
    assert DeliveryReviewer().evaluate(request).status != "PASS"


def test_project_checklist_rejects_duplicate_ids_and_string_boolean():
    from project_checklist import create_project_context
    with pytest.raises(ValueError):
        create_project_context("p", "o", ({"item_id": "1", "title": "a"}, {"item_id": "1", "title": "b"}), notify_progress=True)
    with pytest.raises(ValueError):
        create_project_context("p", "o", ({"item_id": "1", "title": "a"},), notify_progress="false")


@pytest.mark.parametrize("cycle", (-1, True, "1", None))
def test_watchdog_rejects_invalid_cycle_without_crashing(cycle):
    from blockage_watchdog import BlockageWatchdog, LoopSignal, PASS
    result = BlockageWatchdog().evaluate((), LoopSignal(cycle, state_fingerprint="s", action_fingerprint="a"))
    assert result.status != PASS


def test_watchdog_rejects_malformed_terminal_receipt_as_a_signal():
    from blockage_watchdog import BlockageWatchdog, LoopSignal, PASS
    assert BlockageWatchdog().evaluate((), LoopSignal(1, terminal_receipt_sha256="x")).status != PASS


def test_terminal_pass_requires_a_declared_trust_root():
    controls = [ControlEvidence(x, True, True, "PASS", H) for x in REQUIRED_CONTROL_IDS]
    assert TerminalController().evaluate(controls).status != "PASS"
