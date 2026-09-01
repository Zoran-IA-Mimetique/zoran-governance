from __future__ import annotations

from tolerance_skill import Decision
from progress_guard import ProgressAttempt, ProgressGuard, ProgressPolicy, AtomicBundleProof, ProgressHistoryEntry
from prompt_quality import PromptQualityEngine, EvaluatorCriterion, RangeAlignment
from decomposition_calibration import (
    DecompositionCalibrationEngine, DecompositionSchema, PartRule, CalibrationProfile,
)
from k3_adapter import K3Adapter, K3_CONTINUE, K3_REPLAN, K3_STOP, K3_MEASURE


def policy():
    return ProgressPolicy(
        objective_id='reach_100', direction='maximize', target_value=100,
        min_absolute_gain=1, min_fraction_of_remaining=0.05,
        min_gain_per_cost=0.1, max_projected_steps=20,
    )


def bundle(**overrides):
    base=dict(
        bundle_id='B10', step_id='prepare-source-index', step_index=0, step_count=3,
        expected_total_gain=10.0, min_required_total_gain=10.0,
        expected_total_cost=3.0, max_total_cost=5.0, evidence_id='a'*64,
        preregistered=True, causal_dependency=True,
    )
    base.update(overrides)
    return AtomicBundleProof(**base)


def attempt(value_after, *, b=None):
    return ProgressAttempt(
        attempt_id='A', state_before_fingerprint='S65', action_fingerprint='PREP',
        context_fingerprint='C', value_before=65.0, value_after=value_after, cost=1.0,
        evidence_measured=True, atomic_bundle=b,
    )


def test_zero_gain_autonomous_still_blocked():
    assert ProgressGuard(policy()).evaluate(attempt(65.0)).decision is Decision.VETO


def test_zero_gain_inside_valid_atomic_bundle_passes():
    r=ProgressGuard(policy(),trusted_bundle_receipts=('a'*64,)).evaluate(attempt(65.0,b=bundle()))
    assert r.decision is Decision.PASS
    assert r.reasons == ('ATOMIC_BUNDLE_PREPARATORY_STEP',)


def test_marginal_gain_inside_valid_atomic_bundle_passes():
    history=(ProgressHistoryEntry('S64|PREP1','S65','PASS','b'*64,'B10','prepare-source-index',0),)
    r=ProgressGuard(policy(),trusted_bundle_receipts=('a'*64,)).evaluate(attempt(65.2,b=bundle(step_index=1,step_id='prep-2')),history)
    assert r.decision is Decision.PASS
    assert r.reasons == ('ATOMIC_BUNDLE_MARGINAL_STEP',)


def test_regression_blocked_even_inside_bundle():
    r=ProgressGuard(policy(),trusted_bundle_receipts=('a'*64,)).evaluate(attempt(64.9,b=bundle()))
    assert r.decision is Decision.VETO
    assert r.reasons == ('OBJECTIVE_REGRESSION',)


def test_unproven_bundle_fails_closed():
    r=ProgressGuard(policy()).evaluate(attempt(65.0,b=bundle(preregistered=False)))
    assert r.decision is Decision.RETRY
    assert 'ATOMIC_BUNDLE_INVALID' in r.reasons


def test_prompt_contract_detects_hidden_evaluator_criterion():
    prompt="Argue for or against the claim. 120-180 words. Cite one example and address the strongest counter-argument."
    criteria=(
        EvaluatorCriterion('named_source',('cite','source','example')),
        EvaluatorCriterion('counter_argument',('counter-argument','counter argument')),
        EvaluatorCriterion('concrete_number',('year','percentage','study size','number','%')),
    )
    r=PromptQualityEngine().evaluate(prompt,evaluator_criteria=criteria)
    assert r.decision is Decision.RETRY
    assert r.hidden_criteria == ('concrete_number',)


def test_prompt_contract_detects_evaluator_range_mismatch():
    r=PromptQualityEngine().evaluate(
        'Write 120-180 words.',
        range_alignments=(RangeAlignment('word_count',120,180,120,220),),
    )
    assert r.decision is Decision.RETRY
    assert r.range_mismatches == ('word_count',)


def test_prompt_contract_clean_passes():
    r=PromptQualityEngine().evaluate(
        'Write 120-180 words. Include a named source and a concrete year.',
        evaluator_criteria=(EvaluatorCriterion('concrete_number',('year','percentage','number')),),
        range_alignments=(RangeAlignment('word_count',120,180,120,180),),
    )
    assert r.decision is Decision.PASS


def decomp_engine():
    return DecompositionCalibrationEngine(
        schemas=(DecompositionSchema('aircraft','1',(
            PartRule('engine','critical','zero'), PartRule('pilot_seat','high','tight'), PartRule('wc','low','loose'),
        )),),
        profiles=(
            CalibrationProfile('zero',{'safety':0.0},('safety',),'a'*64),
            CalibrationProfile('tight',{'integration':0.05},(), 'b'*64),
            CalibrationProfile('loose',{'integration':0.20},(), 'c'*64),
        ),
    )


def test_bounded_decomposition_resolves_known_domain():
    r=decomp_engine().evaluate('aircraft',observed_parts=('engine','pilot_seat','wc'))
    assert r.decision is Decision.PASS
    assert r.parts == ('engine','pilot_seat','wc')


def test_unknown_domain_is_retrye_not_invented():
    assert decomp_engine().evaluate('unknown').decision is Decision.RETRY


def test_missing_required_part_is_retrye():
    assert decomp_engine().evaluate('aircraft',observed_parts=('engine','wc')).decision is Decision.RETRY


def test_k3_translation_is_unambiguous():
    k=K3Adapter()
    assert k.translate(Decision.PASS).k3_instruction == K3_CONTINUE
    assert k.translate(Decision.RETRY).k3_instruction == K3_REPLAN
    assert k.translate(Decision.VETO).k3_instruction == K3_STOP
    assert k.translate(Decision.RETRY, trace_required=True).k3_instruction == K3_MEASURE
