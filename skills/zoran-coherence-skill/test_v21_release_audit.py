from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent


def test_public_diagnostic_is_explicitly_non_sota_and_non_holdout():
    report = json.loads((ROOT / "audit" / "V21_PUBLIC_DIAGNOSTIC.json").read_text(encoding="utf-8"))
    assert report["verdict"] == "DIAGNOSTIC_ONLY"
    assert report["public_sota_claim"] is False
    assert report["fresh_holdout"] is False
    assert report["candidate_label_channel"] == "ABSENT"


def test_public_diagnostic_crosses_99_percent_without_hiding_faithful_acceptance():
    report = json.loads((ROOT / "audit" / "V21_PUBLIC_DIAGNOSTIC.json").read_text(encoding="utf-8"))
    candidate = report["candidate_v21"]
    assert candidate["hallucination_block_recall"] > 0.99
    assert candidate["false_pass"] == 12
    assert candidate["faithful_acceptance"] == 0.3156934306569343
    assert candidate["false_block"] == 1875


def test_dataset_label_disputes_are_preserved_without_score_adjustment():
    ledger = json.loads((ROOT / "audit" / "V21_PUBLIC_LABEL_DISPUTES.json").read_text(encoding="utf-8"))
    assert ledger["status"] == "PRESERVED_NOT_SCORE_ADJUSTED"
    assert len(ledger["cases"]) == 13


def test_zmos_contract_keeps_github_canonical_and_writer_unique():
    contract = (ROOT / "references" / "zmos-memory.md").read_text(encoding="utf-8")
    assert "GitHub remains the canonical repository authority" in contract
    assert "exactly one `writer_id`" in contract
    assert "Only the Writer" in contract


def test_source_only_runner_does_not_replace_real_pytest_on_import():
    real_pytest = sys.modules["pytest"]
    from scripts import test_runner

    assert sys.modules["pytest"] is real_pytest
    assert test_runner.pytest_stub is not real_pytest
