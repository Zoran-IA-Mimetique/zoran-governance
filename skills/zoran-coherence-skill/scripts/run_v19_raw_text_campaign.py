#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from raw_text_coherence_gate import RawTextCoherenceGate, RawTextCoherenceRequest


CATEGORIES = ("faithful_local", "number_recombination", "scope_omission", "matter_opposition")
AS_OF = "2026-09-01T00:00:00Z"


def case(index: int, category: str):
    person = f"Alex Mercer {index}"
    other_person = f"Jordan Hale {index}"
    year = 1900 + index % 100
    other_year = 2000 + index % 20
    if category == "faithful_local":
        return RawTextCoherenceRequest(
            f"{person} was born in {year}.",
            f"When was {person} born?",
            f"{person} was born in {year}.",
            AS_OF,
        ), "PASS"
    if category == "number_recombination":
        return RawTextCoherenceRequest(
            f"{person} was born in {year}. {other_person} was born in {other_year}.",
            f"When was {person} born?",
            f"{person} was born in {other_year}.",
            AS_OF,
        ), "VETO"
    if category == "scope_omission":
        return RawTextCoherenceRequest(
            f"{person} is a keyboardist. {other_person} is a singer.",
            f"Are {person} and {other_person} both keyboardists?",
            f"{person} is a keyboardist.",
            AS_OF,
        ), "VETO"
    if category == "matter_opposition":
        return RawTextCoherenceRequest(
            "The Moon is a rocky natural satellite made of silicate minerals.",
            "What is the Moon made of?",
            "The Moon is made of cheese.",
            AS_OF,
        ), "VETO"
    raise ValueError("UNKNOWN_CATEGORY")


def run(cases_per_category: int) -> dict[str, object]:
    if cases_per_category < 1 or cases_per_category > 100_000:
        raise ValueError("cases_per_category outside bounded campaign")
    gate = RawTextCoherenceGate()
    counts = {category: {"cases": 0, "correct": 0} for category in CATEGORIES}
    false_pass = 0
    false_block = 0
    receipts: list[str] = []
    for category in CATEGORIES:
        for index in range(cases_per_category):
            request, expected = case(index, category)
            evaluation = gate.evaluate(request)
            observed = evaluation.decision.value
            counts[category]["cases"] += 1
            receipts.append(evaluation.receipt_sha256)
            if observed == expected:
                counts[category]["correct"] += 1
            elif expected == "VETO":
                false_pass += 1
            else:
                false_block += 1
    total = cases_per_category * len(CATEGORIES)
    correct = sum(item["correct"] for item in counts.values())
    return {
        "schema": "zoran.v19-raw-text-campaign.v1",
        "cases_per_category": cases_per_category,
        "total_cases": total,
        "correct": correct,
        "false_pass": false_pass,
        "false_block": false_block,
        "receipt_replay_sha256": __import__("hashlib").sha256("".join(receipts).encode("ascii")).hexdigest(),
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
