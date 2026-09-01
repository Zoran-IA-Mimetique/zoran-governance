from blockage_watchdog import BlockageWatchdog, LoopSignal, STUCK, PASS, RETRY, RESTART_MESSAGE, WatchdogPolicy


def test_same_state_action_breaks_loop():
    w = BlockageWatchdog()
    first = LoopSignal(1, state_fingerprint='S', action_fingerprint='A', progress_fingerprint='P1', checkpoint='C1')
    second = LoopSignal(2, state_fingerprint='S', action_fingerprint='A', progress_fingerprint='P2', checkpoint='C1')
    assert w.evaluate((), first).status == PASS
    v = w.evaluate((first,), second)
    assert v.status == STUCK
    assert 'REPEATED_STATE_ACTION' in v.reasons
    assert v.restart_message == RESTART_MESSAGE
    assert v.resume_checkpoint == 'C1'


def test_repeated_error_breaks_even_when_actions_change():
    w = BlockageWatchdog()
    h = (
        LoopSignal(1, state_fingerprint='1', action_fingerprint='a', error_code='E', progress_fingerprint='p1'),
        LoopSignal(2, state_fingerprint='2', action_fingerprint='b', error_code='E', progress_fingerprint='p2'),
    )
    v = w.evaluate(h, LoopSignal(3, state_fingerprint='3', action_fingerprint='c', error_code='E', progress_fingerprint='p3'))
    assert v.status == STUCK and 'REPEATED_ERROR' in v.reasons


def test_no_progress_breaks_loop():
    w = BlockageWatchdog()
    h = (
        LoopSignal(1, state_fingerprint='1', action_fingerprint='a', progress_fingerprint='same'),
        LoopSignal(2, state_fingerprint='2', action_fingerprint='b', progress_fingerprint='same'),
    )
    v = w.evaluate(h, LoopSignal(3, state_fingerprint='3', action_fingerprint='c', progress_fingerprint='same'))
    assert v.status == STUCK and 'NO_NEW_PROGRESS' in v.reasons


def test_real_progress_does_not_trigger():
    w = BlockageWatchdog()
    h = (
        LoopSignal(1, state_fingerprint='1', action_fingerprint='a', progress_fingerprint='p1'),
        LoopSignal(2, state_fingerprint='2', action_fingerprint='b', progress_fingerprint='p2'),
    )
    assert w.evaluate(h, LoopSignal(3, state_fingerprint='3', action_fingerprint='c', progress_fingerprint='p3')).status == PASS


def test_missing_measurements_do_not_fake_stuck():
    w = BlockageWatchdog()
    h = (LoopSignal(1), LoopSignal(2))
    assert w.evaluate(h, LoopSignal(3)).status == RETRY


def test_hard_cycle_bound_breaks():
    w = BlockageWatchdog(WatchdogPolicy(max_cycles=4))
    v = w.evaluate((), LoopSignal(4))
    assert v.status == STUCK and 'MAX_CYCLE_BOUND_REACHED' in v.reasons


def test_receipt_is_deterministic():
    w = BlockageWatchdog()
    s = LoopSignal(2, 'S', 'A', 'P', 'E', 'C', 'a'*64)
    a = w.evaluate((LoopSignal(1, 'S', 'A', 'Q'),), s)
    b = w.evaluate((LoopSignal(1, 'S', 'A', 'Q'),), s)
    assert a.receipt_sha256 == b.receipt_sha256
