from coherence_dynamics import CoherenceDynamics, CoherencePoint
from interchat_guard import InterchatGuard
from law_engine import LawEngine, HardLaw
from source_coherence import SourceCoherenceEngine, SourceClaim
from tolerance_skill import Decision


def test_dynamics_nan_inf_never_crash_or_pass():
    for value in (float('nan'),float('inf'),float('-inf')):
        r=CoherenceDynamics().evaluate([
            CoherencePoint(0,1,True,('f',),('p',)),
            CoherencePoint(1,value,True,('f',),('p',)),
        ])
        assert r.decision is Decision.RETRY


def test_interchat_nan_inf_never_crash_or_pass():
    for value in (float('nan'),float('inf'),float('-inf')):
        r=InterchatGuard().evaluate(7,value,previous_frames=('f',),current_frames=('f',),previous_proxies=('p',),current_proxies=('p',))
        assert r.decision is Decision.RETRY


def test_interchat_requires_real_frame_proxy_binding():
    r=InterchatGuard().evaluate(7,8,previous_frames=(),current_frames=(),previous_proxies=(),current_proxies=())
    assert r.decision is Decision.RETRY


def test_hard_law_nan_inf_never_passes():
    for value in (float('nan'),float('inf'),float('-inf')):
        for op in ('<=','>='):
            r=LawEngine().evaluate([HardLaw('L',value,op,10,'e')])
            assert r.decision is Decision.RETRY


def test_hard_law_invalid_limit_never_passes():
    r=LawEngine().evaluate([HardLaw('L',2,'<=',float('inf'),'e')])
    assert r.decision is Decision.RETRY


def test_source_invalid_asof_never_crashes():
    r=SourceCoherenceEngine().evaluate([SourceClaim('s','c','v',None,'o','2026-01-01T00:00:00Z')],as_of='bad')
    assert r.decision is Decision.RETRY


def test_source_empty_origin_never_counts_independent():
    r=SourceCoherenceEngine().evaluate([SourceClaim('s','c','v',None,'','2026-01-01T00:00:00Z')])
    assert r.decision is Decision.RETRY
