import hashlib

from terminal_controller import PASS, FAIL, RETRY, ControlEvidence, TerminalController, TerminalVerdict, REQUIRED_CONTROL_IDS
from project_checklist import create_project_context, approve_checklist, validate_item, onboarding_cta, progress_summary
from delivery_reviewer import DeliveryReviewer, DeliveryReviewRequest, ReviewCheck, PASS as REVIEW_PASS
from parallel_context_guard import ParallelContextGuard, build_memory_fragment
from polymorphic_family_engine import PolymorphicFamilyEngine, SelectionContext

H='a'*64
O=hashlib.sha256('Objectif'.encode()).hexdigest()

def full_controls(status=PASS):
    return [ControlEvidence(x, True, True, status, H, 'ok') for x in REQUIRED_CONTROL_IDS]

def trust(controls): return {x.control_id:x.receipt_sha256 for x in controls}

def test_terminal_all_observed_passes():
    controls=full_controls(); assert TerminalController().evaluate(controls,trusted_receipts=trust(controls)).status==PASS

def test_terminal_silence_is_not_pass():
    assert TerminalController().evaluate([]).status==RETRY

def test_terminal_measured_failure_fails():
    controls=full_controls(); controls=[ControlEvidence(x.control_id,True,True,FAIL,H,'boom') if x.control_id=='k3_post' else x for x in controls]
    v=TerminalController().evaluate(controls,trusted_receipts=trust(controls))
    assert v.status==FAIL and any('k3_post' in x for x in v.reasons)

def test_terminal_github_alarm_proposes_connector():
    controls=full_controls(); controls.append(ControlEvidence('github_ci_required',True,True,FAIL,H,'CI_RUN_FAILED'))
    v=TerminalController().evaluate(controls,trusted_receipts=trust(controls))
    assert any(x.connector=='GitHub' for x in v.recovery)


def good_review():
    checks=(
        ReviewCheck('done','DONE',REVIEW_PASS,True,H,('objective',),'done',objective_sha256=O),
        ReviewCheck('objective','OBJECTIVE_CONFORMITY',REVIEW_PASS,True,H,('objective','contract'),'objective',objective_sha256=O),
        ReviewCheck('multi','MULTIFRAME_COHERENCE',REVIEW_PASS,True,H,('local','global'),'multi',objective_sha256=O),
        ReviewCheck('code','CODE_QUALITY',REVIEW_PASS,True,H,('code','runtime'),'code',observed_defects=0,objective_sha256=O),
        ReviewCheck('coherence','COHERENCE_QUALITY',REVIEW_PASS,True,H,('objective','global'),'coherence',observed_defects=0,objective_sha256=O),
        ReviewCheck('evidence','EVIDENCE_COMPLETENESS',REVIEW_PASS,True,H,('proof','scope'),'evidence',objective_sha256=O),
        ReviewCheck('independent','INDEPENDENT_REVIEW',REVIEW_PASS,True,H,('review','governance'),'independent',objective_sha256=O),
    )
    req=DeliveryReviewRequest('D','Objectif','BUILDER','REVIEWER',('a.py',),('a.py',),checks)
    return DeliveryReviewer().evaluate(req)

def test_checklist_cta_is_binary():
    assert onboarding_cta()['choices']==['Oui','Non']

def test_checklist_cannot_tick_without_terminal_pass():
    c=approve_checklist(create_project_context('P','Objectif',({'item_id':'1','title':'Tester'},),notify_progress=True))
    bad=TerminalVerdict(FAIL,('x',),(),(),H)
    try: validate_item(c,'1',terminal_verdict=bad,reviewer_verdict=good_review(),evidence={'ok':False},explanation='non')
    except ValueError as e: assert 'TERMINAL_PASS_REQUIRED' in str(e)
    else: raise AssertionError

def test_checklist_tick_after_terminal_pass():
    c=approve_checklist(create_project_context('P','Objectif',({'item_id':'1','title':'Tester'},),notify_progress=True))
    good=TerminalVerdict(PASS,(),(),(),H)
    review=good_review()
    c,msg=validate_item(c,'1',terminal_verdict=good,reviewer_verdict=review,evidence={'ok':True},explanation='preuve validée',trusted_terminal_receipts=(good.receipt_sha256,),trusted_reviewer_receipts=(review.receipt_sha256,))
    assert progress_summary(c)['percent']==100 and 'validée et conforme' in msg

def test_parallel_context_different_project_blocks():
    f=build_memory_fragment(fragment_id='old',source='HOST_MEMORY',text='projet beta terminé',provenance='host',project_id='B')
    r=ParallelContextGuard().evaluate(doubt=True,question='où en est le projet alpha ?',candidate='le projet alpha avance',fragments=(f,),active_project_id='A')
    assert r.status==RETRY and r.code=='PARALLEL_CONTEXT_RISK'

def test_parallel_context_aligned_is_context_only():
    f=build_memory_fragment(fragment_id='a',source='HOST_MEMORY',text='projet alpha objectif structure',provenance='host',project_id='A')
    r=ParallelContextGuard().evaluate(doubt=True,question='projet alpha structure',candidate='structure alpha',fragments=(f,),active_project_id='A')
    assert r.status==PASS and r.requires_external_grounding is True

def test_memory_absent_under_doubt_is_retry():
    r=ParallelContextGuard().evaluate(doubt=True,question='q projet alpha',candidate='alpha',fragments=())
    assert r.status==RETRY

def test_polymorphic_core_stays_17():
    p=PolymorphicFamilyEngine().select(SelectionContext('bonjour','generic','chat',()))
    assert len(p.core_families)==17 and p.total_active==17

def test_polymorphic_uncalibrated_never_passes():
    p=PolymorphicFamilyEngine().select(SelectionContext('source actuelle','generic','chat',('temporal',),risk_tags=('current_fact',),available_evidence=('source_timestamp',)))
    assert p.status==RETRY

def test_polymorphic_physics_only_when_relevant():
    e=PolymorphicFamilyEngine()
    a=e.select(SelectionContext('poème','creative','text',('semantic',),calibrated_families=('physical_constraints',),available_evidence=('physical_law_receipt',)))
    b=e.select(SelectionContext('calcul structure','construction','beam',('physics','safety'),risk_tags=('engineering',),calibrated_families=('physical_constraints',),available_evidence=('physical_law_receipt',)))
    assert 'physical_constraints' not in {x.family_id for x in a.extensions}
    assert next(x for x in b.extensions if x.family_id=='physical_constraints').status==PASS

def test_polymorphic_can_reach_27_families():
    calibrated=('prompt_quality','contract_coherence','context_continuity','source_independence','source_freshness','physical_constraints','coherence_kinematics','probable_future','memory_integrity','terminal_completion')
    evidence=('prompt_contract','evaluation_contract','context_receipt','source_provenance','source_timestamp','physical_law_receipt','kinematics_receipt','past_state_receipt','frame_proxy_receipt','zmos_receipt','terminal_controller_receipt')
    p=PolymorphicFamilyEngine().select(SelectionContext('prompt objectif critère validation instruction','construction','project',('proof','science','temporal','physics','safety','resources','trajectory','future','memory','project','terminal_condition'),risk_tags=('ambiguity','hidden_rubric','context_drift','factual','current_fact','engineering','trajectory','forecast','memory','completion'),available_evidence=evidence,calibrated_families=calibrated))
    assert p.status==PASS and p.total_active==27 and len(p.extensions)==10

def test_unregistered_family_fails_closed():
    try: PolymorphicFamilyEngine().require_registered(('factual','invented'))
    except ValueError as e: assert 'UNREGISTERED_FAMILY' in str(e)
    else: raise AssertionError

from memory_context_integration import check_memory_context_on_doubt
from recovery_loop import BoundedRecoveryLoop, CycleResult

def test_memory_provider_failure_is_retry():
    def provider(q,c): raise RuntimeError('offline')
    r=check_memory_context_on_doubt(doubt=True,question='projet alpha',candidate='alpha',memory_provider=provider,active_project_id='A')
    assert r.status==RETRY and r.code=='HOST_MEMORY_QUERY_FAILED'

def test_memory_provider_aligned_context_passes_but_needs_external_grounding():
    def provider(q,c): return (build_memory_fragment(fragment_id='a',source='HOST_MEMORY',text='projet alpha structure',provenance='host',project_id='A'),)
    r=check_memory_context_on_doubt(doubt=True,question='projet alpha structure',candidate='structure alpha',memory_provider=provider,active_project_id='A')
    assert r.status==PASS and r.requires_external_grounding

def test_recovery_loop_replays_full_cycle_until_pass():
    calls=[]
    fail_v=TerminalVerdict(FAIL,('TEST_FAIL',),(),(),H)
    pass_v=TerminalVerdict(PASS,(),(),(),H)
    def cycle(n):
        calls.append(n)
        if n==1:
            from terminal_controller import RecoveryDirective
            return CycleResult(TerminalVerdict(FAIL,('TEST_FAIL',),(),(RecoveryDirective('LLM','corriger','TEST_FAIL'),),H))
        return CycleResult(pass_v,product='ok')
    def repair(d,n): return True
    r=BoundedRecoveryLoop(3).run(cycle,repair)
    assert r.status==PASS and r.attempts==2 and calls==[1,2]

def test_recovery_loop_never_bypasses_connector_permission():
    from terminal_controller import RecoveryDirective
    v=TerminalVerdict(FAIL,('GITHUB_ACCESS',),(),(RecoveryDirective('CONNECTOR','Activer GitHub','GITHUB_ACCESS','GitHub'),),H)
    r=BoundedRecoveryLoop().run(lambda n:CycleResult(v),lambda d,n:True)
    assert r.status==RETRY and r.connector=='GitHub' and r.user_action

def test_recovery_loop_watchdog_stops_repeated_state_action():
    from terminal_controller import RecoveryDirective
    v=TerminalVerdict(FAIL,('SAME_FAIL',),(),(RecoveryDirective('LLM','corriger','SAME_FAIL'),),H)
    def cycle(n):
        return CycleResult(v,state_fingerprint='same-state',action_fingerprint='same-action',progress_fingerprint=f'p{n}',checkpoint='CHK-42')
    r=BoundedRecoveryLoop(max_attempts=5).run(cycle,lambda d,n:True)
    assert r.status==RETRY
    assert r.attempts==2
    assert r.user_action=='Relance-moi, je suis bloqué.'
    assert r.resume_checkpoint=='CHK-42'
    assert r.watchdog_receipt_sha256

def test_checklist_cannot_tick_without_reviewer_pass():
    c=approve_checklist(create_project_context('P','Objectif',({'item_id':'1','title':'Tester'},),notify_progress=True))
    good_terminal=TerminalVerdict(PASS,(),(),(),H)
    bad_review=good_review().__class__(FAIL,('x',),(),1,1,1,0,'b'*64,'c'*64)
    try:
        validate_item(c,'1',terminal_verdict=good_terminal,reviewer_verdict=bad_review,evidence={'ok':True},explanation='non conforme')
    except ValueError as e:
        assert 'DELIVERY_REVIEWER_PASS_REQUIRED' in str(e)
    else:
        raise AssertionError
