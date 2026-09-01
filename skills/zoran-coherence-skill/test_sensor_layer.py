from __future__ import annotations

import copy
import itertools

import pytest

from sensor_layer import (
    EvidenceFact,
    NumericConstraint,
    NumericExpectation,
    RelationEvidence,
    SensorBundle,
    sense,
)
from tolerance_skill import Decision, MulticriteriaToleranceSkill, conservative_default_policy


def clean_bundle() -> SensorBundle:
    return SensorBundle(
        request_text="Quelles limites et quel risque ?",  # LIMITATION only (same intent family)
        response_text=(
            "certain: limite=acceptable [S1]; "
            "charge=100 kN [S2]; "
            "cause(pluie->inondation) [S3]; "
            "time(A before B) [S4]; "
            "risque=2 [S5]; "
            "ratio=0.5 [S6]"
        ),
        domain_id="btp",
        allowed_domains=("btp", "finance", "medical", "software", "text_ai"),
        facts=(EvidenceFact("limite", "acceptable", "S1", modality="certain", polarity="positive"),),
        numeric_expectations=(NumericExpectation("charge", 100.0, 0.5, "S2", "kn"),),
        relations=(
            RelationEvidence("pluie", "cause", "inondation", "S3"),
            RelationEvidence("A", "before", "B", "S4"),
        ),
        required_response_keys=("limite",),
        measurement_uncertainty=0.1,
        measurement_uncertainty_cap=0.2,
        safety_constraints=(NumericConstraint("max_risk", "risque", "<=", 3.0),),
        regulatory_constraints=(NumericConstraint("max_ratio", "ratio", "<=", 0.8),),
        resource_used=50,
        resource_budget=100,
        repeat_fingerprints=("abc", "abc"),
        required_output_fields=("text", "claims"),
        output_fields={"text": "ok", "claims": ["C1"]},
        metier_id="generic",
        frame_id="general",
    )


def engine_eval(bundle: SensorBundle):
    sr = sense(bundle)
    policy = conservative_default_policy(metier_ids=("generic",), frame_ids=("general",), metier_budget=100, frame_budget=100, global_budget=100)
    result = MulticriteriaToleranceSkill(policy).evaluate(sr.observations, scope=sr.scope)
    return sr, result


def mutate(bundle: SensorBundle, dimension: str) -> SensorBundle:
    b = copy.deepcopy(bundle)
    if dimension == "metier":
        return SensorBundle(**{**b.__dict__, "domain_id": "unknown_domain"})
    if dimension == "coherence":
        return SensorBundle(**{**b.__dict__, "response_text": b.response_text + "; limite=inacceptable [S1]"})
    if dimension == "semantic":
        return SensorBundle(**{**b.__dict__, "response_text": b.response_text.replace("certain: limite=acceptable", "certain: not limite=acceptable")})
    if dimension == "factual":
        return SensorBundle(**{**b.__dict__, "response_text": b.response_text.replace("limite=acceptable", "limite=inacceptable")})
    if dimension == "numeric":
        return SensorBundle(**{**b.__dict__, "response_text": b.response_text.replace("charge=100 kN", "charge=110 kN")})
    if dimension == "measurement":
        return SensorBundle(**{**b.__dict__, "measurement_uncertainty": 0.5})
    if dimension == "temporal":
        return SensorBundle(**{**b.__dict__, "response_text": b.response_text.replace("time(A before B)", "time(A after B)")})
    if dimension == "source":
        return SensorBundle(**{**b.__dict__, "response_text": b.response_text.replace("limite=acceptable [S1]", "limite=acceptable [BAD]")})
    if dimension == "ambiguity":
        return SensorBundle(**{**b.__dict__, "request_text": "Quelles limites et pourquoi ?"})
    if dimension == "causal":
        return SensorBundle(**{**b.__dict__, "response_text": b.response_text.replace("cause(pluie->inondation)", "cause(inondation->pluie)")})
    if dimension == "safety":
        return SensorBundle(**{**b.__dict__, "response_text": b.response_text.replace("risque=2", "risque=9")})
    if dimension == "regulatory":
        return SensorBundle(**{**b.__dict__, "response_text": b.response_text.replace("ratio=0.5", "ratio=1.2")})
    if dimension == "resource":
        return SensorBundle(**{**b.__dict__, "resource_used": 200})
    if dimension == "repeatability":
        return SensorBundle(**{**b.__dict__, "repeat_fingerprints": ("abc", "xyz")})
    if dimension == "integration":
        return SensorBundle(**{**b.__dict__, "output_fields": {"text": "ok"}})
    if dimension == "intentional":
        return SensorBundle(**{**b.__dict__, "response_text": b.response_text.replace("certain: limite=acceptable [S1]; ", "")})
    if dimension == "epistemic":
        facts = (EvidenceFact("limite", "acceptable", "S1", modality="possible", polarity="positive"),)
        return SensorBundle(**{**b.__dict__, "facts": facts})
    raise AssertionError(dimension)


def test_clean_all_17_pass():
    sr, result = engine_eval(clean_bundle())
    assert len(sr.observations) == 17
    assert result.decision is Decision.PASS


@pytest.mark.parametrize("dim", __import__("tolerance_skill").TOLERANCE_FAMILIES)
def test_each_single_family_mutation_blocks(dim):
    _, result = engine_eval(mutate(clean_bundle(), dim))
    assert result.decision is not Decision.PASS, (dim, result.as_dict())


@pytest.mark.parametrize("dim", __import__("tolerance_skill").TOLERANCE_FAMILIES)
def test_each_clean_family_is_measured_and_zero(dim):
    sr = sense(clean_bundle())
    item = next(o for o in sr.observations if o.dimension == dim)
    assert item.evidence_measured is True
    assert item.delta == 0.0


def test_all_2pow17_mutation_combinations_block_except_clean():
    from tolerance_skill import TOLERANCE_FAMILIES
    base = clean_bundle()
    clean_sr = sense(base)
    mutated = {d: sense(mutate(base, d)) for d in TOLERANCE_FAMILIES}
    clean_by = {o.dimension: o for o in clean_sr.observations}
    mut_by = {d: {o.dimension: o for o in sr.observations} for d, sr in mutated.items()}

    # Prove the fast exhaustive predicate equivalent to the release engine on
    # the clean case and every independent mutation before using it on 2^17.
    _, clean_release = engine_eval(base)
    assert clean_release.decision is Decision.PASS
    for d in TOLERANCE_FAMILIES:
        _, release = engine_eval(mutate(base, d))
        fast_nonpass = (not mut_by[d][d].evidence_measured) or (mut_by[d][d].delta != 0.0)
        assert fast_nonpass is True
        assert release.decision is not Decision.PASS

    false_pass = 0
    false_block = 0
    for mask in range(1 << 17):
        any_blocking_signal = False
        for i, d in enumerate(TOLERANCE_FAMILIES):
            o = mut_by[d][d] if (mask >> i) & 1 else clean_by[d]
            if (not o.evidence_measured) or o.delta != 0.0:
                any_blocking_signal = True
                break
        predicted_pass = not any_blocking_signal
        expected_pass = mask == 0
        false_pass += int(predicted_pass and not expected_pass)
        false_block += int((not predicted_pass) and expected_pass)
    assert false_pass == 0
    assert false_block == 0


def test_missing_required_inputs_retry():
    variants = [
        ("facts", ()),
        ("numeric_expectations", ()),
        ("relations", ()),
        ("measurement_uncertainty", None),
        ("safety_constraints", ()),
        ("regulatory_constraints", ()),
        ("resource_used", None),
        ("repeat_fingerprints", ()),
        ("required_output_fields", ()),
        ("required_response_keys", ()),
    ]
    base = clean_bundle()
    for field, value in variants:
        b = SensorBundle(**{**base.__dict__, field: value})
        _, result = engine_eval(b)
        assert result.decision is Decision.RETRY, (field, result.as_dict())


def test_unsupported_clause_makes_semantic_path_retry():
    base = clean_bundle()
    b = SensorBundle(**{**base.__dict__, "response_text": base.response_text + "; Ceci est une phrase libre non supportée."})
    _, result = engine_eval(b)
    assert result.decision is Decision.RETRY


def test_replay_10000_sensor_and_engine_receipts_identical():
    base = clean_bundle()
    sr, result = engine_eval(base)
    for _ in range(10_000):
        sr2, result2 = engine_eval(base)
        assert sr2.receipt_sha256 == sr.receipt_sha256
        assert result2.receipt_sha256 == result.receipt_sha256


def test_parser_extracts_bounded_text_signals():
    sr = sense(clean_bundle())
    kinds = {x.kind for x in sr.parsed_assertions}
    assert {"fact", "causal", "temporal"}.issubset(kinds)
    assert sr.intent_matches == ("LIMITATION",)


def _obs_by_dim(bundle: SensorBundle, dim: str):
    return next(o for o in sense(bundle).observations if o.dimension == dim)


def test_empty_response_makes_coherence_trace_pending_not_clean_pass():
    base = clean_bundle()
    b = SensorBundle(**{**base.__dict__, "response_text": ""})
    coherence = _obs_by_dim(b, "coherence")
    assert coherence.evidence_measured is False
    _, result = engine_eval(b)
    assert result.decision is Decision.RETRY


def test_numeric_provenance_is_checked_independently_of_numeric_value():
    base = clean_bundle()
    b = SensorBundle(**{**base.__dict__, "response_text": base.response_text.replace("charge=100 kN [S2]", "charge=100 kN [BAD]")})
    numeric = _obs_by_dim(b, "numeric")
    source = _obs_by_dim(b, "source")
    assert numeric.evidence_measured is True and numeric.delta == 0.0
    assert source.evidence_measured is True and source.delta == 1.0


def test_causal_provenance_is_covered_by_source_sensor():
    base = clean_bundle()
    b = SensorBundle(**{**base.__dict__, "response_text": base.response_text.replace("cause(pluie->inondation) [S3]", "cause(pluie->inondation) [BAD]")})
    source = _obs_by_dim(b, "source")
    assert source.evidence_measured is True and source.delta == 1.0


def test_temporal_provenance_is_covered_by_source_sensor():
    base = clean_bundle()
    b = SensorBundle(**{**base.__dict__, "response_text": base.response_text.replace("time(A before B) [S4]", "time(A before B) [BAD]")})
    source = _obs_by_dim(b, "source")
    assert source.evidence_measured is True and source.delta == 1.0
