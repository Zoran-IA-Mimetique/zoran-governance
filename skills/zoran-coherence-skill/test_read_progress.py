import pytest

from read_progress import (
    IN_PROGRESS,
    RETRY,
    PASS,
    ReadProgressTracker,
    terminal_read_status,
)


def test_pdf_reports_exact_percent_and_go():
    r = ReadProgressTracker().evaluate(
        object_id="pdf-1", object_type="pdf", total_units=200, read_units=range(1, 127)
    )
    assert r.status == IN_PROGRESS
    assert r.percent == "63.00"
    assert r.read_count == 126
    assert r.remaining_count == 74
    assert r.cta == "GO"
    assert r.next_unread_unit == 127
    assert r.user_message() == "Lecture PDF : 63.00 % — 126/200 pages.\nGO"


def test_duplicate_reads_never_inflate_percent():
    r = ReadProgressTracker().evaluate(
        object_id="doc", object_type="document", total_units=4, read_units=(1, 1, 2, 2)
    )
    assert r.read_count == 2
    assert r.percent == "50.00"


def test_complete_object_is_100_and_has_no_go():
    r = ReadProgressTracker().evaluate(
        object_id="zip", object_type="archive", total_units=3, read_units=(3, 1, 2)
    )
    assert r.status == PASS
    assert r.complete is True
    assert r.percent == "100.00"
    assert r.cta is None
    assert terminal_read_status(r) == (PASS, "READING_COMPLETE_100_PERCENT")


def test_incomplete_read_blocks_terminal_completion():
    r = ReadProgressTracker().evaluate(
        object_id="x", object_type="corpus", total_units=10, read_units=(1, 2, 3)
    )
    status, detail = terminal_read_status(r)
    assert status == "FAIL"
    assert detail == "READING_INCOMPLETE:30.00%"


def test_unknown_total_never_fakes_percentage():
    r = ReadProgressTracker().evaluate(
        object_id="stream", object_type="object", total_units=None, read_units=(1, 2)
    )
    assert r.status == RETRY
    assert r.percent is None
    assert r.complete is False
    assert r.cta == "GO"
    assert "RETRY" in r.user_message()
    assert terminal_read_status(r) == (RETRY, "READING_TOTAL_UNKNOWN")


def test_next_window_resumes_on_unread_units_only():
    tracker = ReadProgressTracker()
    r = tracker.evaluate(
        object_id="pdf", object_type="pdf", total_units=8, read_units=(1, 2, 5)
    )
    assert tracker.next_window(r, max_units=3) == (3, 4, 6)


def test_out_of_range_unit_is_rejected():
    with pytest.raises(ValueError):
        ReadProgressTracker().evaluate(
            object_id="pdf", object_type="pdf", total_units=5, read_units=(1, 6)
        )


def test_receipt_is_deterministic_independent_of_read_order():
    tracker = ReadProgressTracker()
    a = tracker.evaluate(object_id="pdf", object_type="pdf", total_units=5, read_units=(1, 3, 2))
    b = tracker.evaluate(object_id="pdf", object_type="pdf", total_units=5, read_units=(3, 2, 1))
    assert a.receipt_sha256 == b.receipt_sha256


def test_terminal_controller_refuses_completion_below_100_percent():
    from terminal_controller import ControlEvidence, REQUIRED_CONTROL_IDS, TerminalController
    from zoran_runtime import ZoranRuntime
    from frame_search import FrameSearchEngine, FrameDefinition

    tracker = ReadProgressTracker()
    r = tracker.evaluate(object_id="pdf", object_type="pdf", total_units=100, read_units=range(1, 100))
    status, detail = terminal_read_status(r)
    controls = [
        ControlEvidence(cid, True, True, PASS, "a" * 64, "ok")
        for cid in REQUIRED_CONTROL_IDS
    ]
    controls.append(ControlEvidence("object_read_complete", True, True, status, r.receipt_sha256, detail))
    verdict = TerminalController().evaluate(controls,trusted_receipts={x.control_id:x.receipt_sha256 for x in controls})
    assert verdict.status == "FAIL"
    assert any("READING_INCOMPLETE:99.00%" in reason for reason in verdict.reasons)
