#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from structural_reasoning_gate import ProofStatus, StructuralProofRequest, StructuralReasoningGate


CATEGORIES = (
    "financial_cell_faithful",
    "financial_cell_wrong_year",
    "financial_unit_faithful",
    "financial_unit_nearby_wrong",
    "arithmetic_sum_faithful",
    "arithmetic_sum_wrong",
    "explicit_count_faithful",
    "explicit_count_wrong",
    "percent_complement_faithful",
    "percent_complement_wrong",
    "yes_no_faithful",
    "yes_no_wrong",
    "comparison_faithful",
    "comparison_wrong",
    "multi_source_faithful",
    "multi_source_invented_claim",
)


def _case(index: int, category: str) -> tuple[StructuralProofRequest, str]:
    first = 10_000 + index
    second = 8_000 + index
    if category == "financial_cell_faithful":
        return StructuralProofRequest(f"December 31,\n2022\n2021\nTotal current assets\n{first:,}\n{second:,}", "What were total current assets at FY2022 in USD millions?", f"${first:,}"), "PASS"
    if category == "financial_cell_wrong_year":
        return StructuralProofRequest(f"December 31,\n2022\n2021\nTotal current assets\n{first:,}\n{second:,}", "What were total current assets at FY2022 in USD millions?", f"${second:,}"), "VETO"
    if category == "financial_unit_faithful":
        return StructuralProofRequest(f"Balance Sheets ($ in millions)\nDecember 31, 2022\nTotal assets\n{first:,}", "What were total assets at FY2022 in USD thousands?", f"${first * 1000}.00"), "PASS"
    if category == "financial_unit_nearby_wrong":
        return StructuralProofRequest(f"Balance Sheets ($ in millions)\nDecember 31, 2022\nTotal assets\n{first:,}", "What were total assets at FY2022 in USD thousands?", f"${first * 1000 + 1000}.00"), "VETO"
    if category == "arithmetic_sum_faithful":
        return StructuralProofRequest(f"The census recorded {first:,} households and {second:,} families.", "How many households and families were recorded in total?", f"{first + second:,}"), "PASS"
    if category == "arithmetic_sum_wrong":
        return StructuralProofRequest(f"The census recorded {first:,} households and {second:,} families.", "How many households and families were recorded in total?", f"{first + second + 1:,}"), "VETO"
    if category == "explicit_count_faithful":
        return StructuralProofRequest("Smith caught a 74-yard pass, then caught three touchdown passes.", "How many touchdown catches did Smith make?", "3"), "PASS"
    if category == "explicit_count_wrong":
        return StructuralProofRequest("Smith caught a 74-yard pass, then caught three touchdown passes.", "How many touchdown catches did Smith make?", "74"), "VETO"
    if category == "percent_complement_faithful":
        return StructuralProofRequest("Residents were 25% under 18, 20% from 18 to 24, 30% from 25 to 44, and 25% at least 45.", "How many in percent weren't 18 to 24?", "80%"), "PASS"
    if category == "percent_complement_wrong":
        return StructuralProofRequest("Residents were 25% under 18, 20% from 18 to 24, 30% from 25 to 44, and 25% at least 45.", "How many in percent weren't 18 to 24?", "81%"), "VETO"
    if category == "yes_no_faithful":
        return StructuralProofRequest("The treatment did not increase residual activity. No adverse outcome was observed.", "Does the treatment increase residual activity?", "No. It does not increase residual activity."), "PASS"
    if category == "yes_no_wrong":
        return StructuralProofRequest("The treatment did not increase residual activity.", "Does the treatment increase residual activity?", "Yes. It increases residual activity."), "VETO"
    if category == "comparison_faithful":
        return StructuralProofRequest(f"The census counted {first:,} residents from China and {second:,} from Australia.", "Were there more residents from China or Australia?", "China"), "PASS"
    if category == "comparison_wrong":
        return StructuralProofRequest(f"The census counted {first:,} residents from China and {second:,} from Australia.", "Were there more residents from China or Australia?", "Australia"), "VETO"
    context = "passage 1: Tighten the hinge screws first. Enlarge the strike plate hole only if the latch remains misaligned. Move the strike plate after checking alignment."
    if category == "multi_source_faithful":
        return StructuralProofRequest(context, "How should the latch be repaired?", "1. Tighten the hinge screws first. 2. Enlarge the strike plate hole only if the latch remains misaligned. 3. Move the strike plate after checking alignment."), "PASS"
    if category == "multi_source_invented_claim":
        return StructuralProofRequest(context, "How should the latch be repaired?", "1. Tighten the hinge screws first. 2. Enlarge the strike plate hole only if the latch remains misaligned. 3. Paint the lock blue before moving the strike plate."), "VETO"
    raise ValueError("UNKNOWN_CATEGORY")


def run(cases_per_category: int) -> dict[str, object]:
    if not 1 <= cases_per_category <= 100_000:
        raise ValueError("cases_per_category outside bounded campaign")
    gate = StructuralReasoningGate()
    counts = {category: {"cases": 0, "correct": 0} for category in CATEGORIES}
    false_pass = 0
    false_block = 0
    receipts: list[str] = []
    for category in CATEGORIES:
        for index in range(cases_per_category):
            request, expected = _case(index, category)
            proof = gate.evaluate(request)
            observed = "PASS" if proof.status is ProofStatus.PROVED else "VETO"
            counts[category]["cases"] += 1
            counts[category]["correct"] += observed == expected
            receipts.append(proof.receipt_sha256)
            if observed != expected and expected == "VETO":
                false_pass += 1
            elif observed != expected:
                false_block += 1
    total = cases_per_category * len(CATEGORIES)
    correct = sum(item["correct"] for item in counts.values())
    return {
        "schema": "zoran.v20-zmos-structural-campaign.v1",
        "cases_per_category": cases_per_category,
        "total_cases": total,
        "correct": correct,
        "false_pass": false_pass,
        "false_block": false_block,
        "receipt_replay_sha256": hashlib.sha256("".join(receipts).encode("ascii")).hexdigest(),
        "categories": counts,
        "verdict": "PASS" if correct == total and false_pass == false_block == 0 else "FAIL",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases-per-category", type=int, default=1000)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run(args.cases_per_category)
    rendered = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0 if result["verdict"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
