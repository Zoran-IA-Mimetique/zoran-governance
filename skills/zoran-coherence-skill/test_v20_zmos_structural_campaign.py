from __future__ import annotations

from dataclasses import fields

from scripts.run_v20_zmos_structural_campaign import CATEGORIES, run
from structural_reasoning_gate import StructuralProofRequest


def test_zmos_request_namespace_excludes_external_benchmark_routes():
    assert tuple(field.name for field in fields(StructuralProofRequest)) == ("context", "question", "answer")


def test_small_v20_zmos_structural_campaign_has_no_false_decision():
    result = run(2)
    assert result["total_cases"] == 2 * len(CATEGORIES)
    assert result["false_pass"] == 0
    assert result["false_block"] == 0
    assert result["verdict"] == "PASS"
