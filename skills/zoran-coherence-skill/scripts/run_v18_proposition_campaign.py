#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from proposition_coherence_gate import Proposition, PropositionCoherenceGate, PropositionCoherenceRequest
from question_reformulation_gate import (
    QuestionReformulationGate,
    QuestionReformulationRequest,
    ReformulationCandidate,
    SemanticVector,
)
from tolerance_skill import Decision


H = "a" * 64
WEB = "b" * 64
CATEGORIES = (
    "faithful",
    "entity_swap",
    "relation_swap",
    "number_date_swap",
    "negation_scope_swap",
)


def _question(index: int):
    person = f"Personne Publique {index}"
    vector = SemanticVector((person,), ("date de naissance",), ("date",), dates=(f"19{index % 90:02d}",))
    request = QuestionReformulationRequest(
        f"{person}, naissance ?",
        vector,
        (
            ReformulationCandidate(f"Quelle est la date de naissance de {person} ?", vector),
            ReformulationCandidate(f"À quelle date {person} est-elle née ?", vector),
        ),
        doubt=True,
        factual_intent=True,
        public_persons=(person,),
    )
    return person, QuestionReformulationGate().evaluate(request)


def _pair(index: int, category: str, question_receipt: str, person: str):
    date = f"19{index % 90:02d}-01-01"
    claim = Proposition(
        f"c-{index}", person, "date de naissance", date,
        date=date, evidence_id=f"e-{index}", public_person_fact=True,
    )
    evidence = Proposition(
        f"source-{index}", person, "date de naissance", date,
        date=date, evidence_id=f"e-{index}", exact_quote=f"{person} est née le {date}.",
        public_person_fact=True,
    )
    expected_relations = ("date de naissance",)
    expected = Decision.PASS
    if category == "entity_swap":
        claim = replace(claim, subject=f"Autre Personne {index}")
        expected = Decision.VETO
    elif category == "relation_swap":
        claim = replace(claim, relation="profession")
        expected = Decision.VETO
    elif category == "number_date_swap":
        claim = replace(claim, object="2000-01-01", date="2000-01-01")
        expected = Decision.VETO
    elif category == "negation_scope_swap":
        claim = replace(claim, polarity="NEGATIVE")
        expected = Decision.VETO
    request = PropositionCoherenceRequest(
        question_receipt,
        (person,),
        expected_relations,
        (claim,),
        (evidence,),
        ((person, WEB),),
    )
    return request, expected


def run(cases_per_category: int) -> dict[str, object]:
    if cases_per_category < 1 or cases_per_category > 100_000:
        raise ValueError("cases_per_category outside bounded campaign")
    gate = PropositionCoherenceGate()
    counts = {category: {"cases": 0, "correct": 0} for category in CATEGORIES}
    false_pass = 0
    false_block = 0
    question_failures = 0
    for category in CATEGORIES:
        for index in range(cases_per_category):
            person, question = _question(index)
            if question.decision is not Decision.PASS:
                question_failures += 1
                continue
            request, expected = _pair(index, category, question.receipt_sha256, person)
            observed = gate.evaluate(request).decision
            counts[category]["cases"] += 1
            if observed is expected:
                counts[category]["correct"] += 1
            elif expected is Decision.VETO:
                false_pass += 1
            else:
                false_block += 1
    total = cases_per_category * len(CATEGORIES)
    passed = sum(item["correct"] for item in counts.values())
    return {
        "schema": "zoran.v18-proposition-campaign.v1",
        "cases_per_category": cases_per_category,
        "total_cases": total,
        "correct": passed,
        "false_pass": false_pass,
        "false_block": false_block,
        "question_failures": question_failures,
        "categories": counts,
        "verdict": "PASS" if passed == total and false_pass == false_block == question_failures == 0 else "FAIL",
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
