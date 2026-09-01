#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path
import sys
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from raw_text_coherence_gate import RawTextCoherenceGate, RawTextCoherenceRequest
from tolerance_skill import Decision


REQUIRED_COLUMNS = ("id", "passage", "question", "answer", "label", "source_ds")
ALLOWED_LABELS = frozenset({"PASS", "FAIL"})


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _metrics(rows: Iterable[dict[str, object]]) -> dict[str, object]:
    rows = tuple(rows)
    true_pass = sum(row["expected"] == "PASS" and row["observed"] == "PASS" for row in rows)
    false_block = sum(row["expected"] == "PASS" and row["observed"] != "PASS" for row in rows)
    true_block = sum(row["expected"] == "FAIL" and row["observed"] != "PASS" for row in rows)
    false_pass = sum(row["expected"] == "FAIL" and row["observed"] == "PASS" for row in rows)
    total = len(rows)
    faithful_acceptance = _ratio(true_pass, true_pass + false_block)
    hallucination_block_recall = _ratio(true_block, true_block + false_pass)
    block_precision = _ratio(true_block, true_block + false_block)
    return {
        "cases": total,
        "correct": true_pass + true_block,
        "accuracy": _ratio(true_pass + true_block, total),
        "balanced_accuracy": (faithful_acceptance + hallucination_block_recall) / 2,
        "hallucination_block_recall": hallucination_block_recall,
        "faithful_acceptance": faithful_acceptance,
        "block_precision": block_precision,
        "block_f1": _ratio(2 * block_precision * hallucination_block_recall, block_precision + hallucination_block_recall),
        "true_pass": true_pass,
        "true_block": true_block,
        "false_pass": false_pass,
        "false_block": false_block,
    }


def evaluate_rows(
    rows: Iterable[dict[str, str]],
    gate: RawTextCoherenceGate,
    *,
    as_of: str,
    excluded_sources: frozenset[str],
) -> tuple[dict[str, object], list[dict[str, object]]]:
    evaluated: list[dict[str, object]] = []
    predictions_digest = hashlib.sha256()
    for row in rows:
        if row["source_ds"] in excluded_sources:
            continue
        expected = row["label"].strip().upper()
        if expected not in ALLOWED_LABELS:
            raise ValueError(f"LABEL_INVALID:{row['id']}")
        request = RawTextCoherenceRequest(
            context=row["passage"], question=row["question"], answer=row["answer"], as_of=as_of,
        )
        result = gate.evaluate(request)
        observed = "PASS" if result.decision is Decision.PASS else "FAIL"
        item = {
            "id": row["id"],
            "source_ds": row["source_ds"],
            "expected": expected,
            "observed": observed,
            "decision": result.decision.value,
            "reasons": list(result.reasons),
            "faithful_probability": result.faithful_probability,
            "threshold": result.threshold,
            "structural_status": result.structural_status,
            "structural_family": result.structural_family,
            "structural_trace": list(result.structural_trace),
            "receipt_sha256": result.receipt_sha256,
            "question": row["question"],
            "answer": row["answer"],
            "passage": row["passage"],
        }
        evaluated.append(item)
        predictions_digest.update(row["id"].encode("utf-8"))
        predictions_digest.update(result.receipt_sha256.encode("ascii"))

    by_source: dict[str, list[dict[str, object]]] = defaultdict(list)
    for item in evaluated:
        by_source[str(item["source_ds"])].append(item)
    misclassified = [item for item in evaluated if item["expected"] != item["observed"]]
    reason_counts = Counter(
        str(reason)
        for item in misclassified
        for reason in item["reasons"]
    )
    report = {
        "schema": "zoran.public-halubench-diagnostic.v1",
        "candidate_label_channel": "ABSENT",
        "evaluated_case_set_sha256": hashlib.sha256("".join(str(item["id"]) for item in evaluated).encode("utf-8")).hexdigest(),
        "prediction_receipts_sha256": predictions_digest.hexdigest(),
        "excluded_sources": sorted(excluded_sources),
        "metrics": _metrics(evaluated),
        "external_source_slices": {name: _metrics(items) for name, items in sorted(by_source.items())},
        "misclassification_reasons": dict(sorted(reason_counts.items(), key=lambda item: (-item[1], item[0]))),
        "misclassified_cases": len(misclassified),
    }
    return report, misclassified


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--expected-dataset-sha256", required=True)
    parser.add_argument("--dataset-commit", required=True)
    parser.add_argument("--exclude-source", action="append", default=[])
    parser.add_argument("--as-of", default="2026-09-01T00:00:00Z")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--failures-output", type=Path, required=True)
    args = parser.parse_args()

    observed_sha = _sha256(args.dataset)
    if observed_sha != args.expected_dataset_sha256:
        raise ValueError(f"DATASET_SHA256_MISMATCH:{observed_sha}")
    with args.dataset.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != REQUIRED_COLUMNS:
            raise ValueError("DATASET_SCHEMA_MISMATCH")
        rows = list(reader)

    report, failures = evaluate_rows(
        rows, RawTextCoherenceGate(), as_of=args.as_of, excluded_sources=frozenset(args.exclude_source),
    )
    report.update({
        "dataset_sha256": observed_sha,
        "dataset_commit": args.dataset_commit,
        "dataset_rows": len(rows),
        "verdict": "DIAGNOSTIC_ONLY",
        "public_sota_claim": False,
    })
    args.output.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    with args.failures_output.open("w", encoding="utf-8") as handle:
        for item in failures:
            handle.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
