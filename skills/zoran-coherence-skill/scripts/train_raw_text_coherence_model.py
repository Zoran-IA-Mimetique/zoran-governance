#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupShuffleSplit
from sklearn.preprocessing import StandardScaler


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from raw_text_coherence_gate import MODEL_ID, _canonical_sha, extract_features  # noqa: E402


def read_jsonl(path: Path):
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def metrics(labels: np.ndarray, predictions: np.ndarray) -> dict[str, float | int]:
    faithful = labels == 1
    hallucinated = ~faithful
    passes = predictions == 1
    false_passes = int(np.sum(hallucinated & passes))
    false_blocks = int(np.sum(faithful & ~passes))
    true_passes = int(np.sum(faithful & passes))
    true_blocks = int(np.sum(hallucinated & ~passes))
    return {
        "cases": int(len(labels)),
        "accuracy": float(np.mean(labels == predictions)),
        "false_passes": false_passes,
        "false_blocks": false_blocks,
        "hallucination_block_recall": float(true_blocks / max(1, true_blocks + false_passes)),
        "faithful_acceptance": float(true_passes / max(1, true_passes + false_blocks)),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--public", required=True, type=Path)
    parser.add_argument("--oracle", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--feature-cache", type=Path)
    args = parser.parse_args()

    rows: list[dict[str, float]] = []
    labels = []
    groups = []
    tasks = []
    identities = []
    cached = None
    if args.feature_cache and args.feature_cache.is_file():
        candidate = np.load(args.feature_cache, allow_pickle=False)
        public_sha = hashlib.sha256(args.public.read_bytes()).hexdigest()
        oracle_sha = hashlib.sha256(args.oracle.read_bytes()).hexdigest()
        if str(candidate["public_sha"]) == public_sha and str(candidate["oracle_sha"]) == oracle_sha:
            cached = candidate
    with args.public.open(encoding="utf-8") as public_handle, args.oracle.open(encoding="utf-8") as oracle_handle:
        for public_raw, oracle_raw in zip(public_handle, oracle_handle, strict=True):
            if not public_raw.strip() or not oracle_raw.strip():
                raise ValueError("BLANK_BENCHMARK_ROW")
            public = json.loads(public_raw)
            if public["dataset"] != "HaluEval":
                continue
            oracle = json.loads(oracle_raw)
            if public["case_id"] != oracle["case_id"]:
                raise ValueError("CASE_ID_MISMATCH")
            if cached is None:
                rows.append(extract_features(public["context"], public["question"], public["answer"]))
            labels.append(1 if oracle["expected"] == "faithful" else 0)
            group_material = json.dumps([public["task"], public["context"], public["question"]], ensure_ascii=False, separators=(",", ":"))
            groups.append(hashlib.sha256(group_material.encode("utf-8")).hexdigest())
            tasks.append(public["task"])
            identities.append([public["case_id"], oracle["expected"]])
            if cached is None and len(rows) % 5000 == 0:
                print(json.dumps({"phase": "extract", "cases": len(rows)}), flush=True)
    if len(labels) != 60000 or sum(labels) != 30000:
        raise ValueError("TRAINING_CORPUS_CONTRACT_INVALID")

    if cached is None:
        feature_names = tuple(sorted(rows[0]))
        if any(tuple(sorted(row)) != feature_names for row in rows):
            raise ValueError("FEATURE_SCHEMA_DRIFT")
        matrix = np.asarray([[row[name] for name in feature_names] for row in rows], dtype=np.float64)
    else:
        matrix = np.asarray(cached["matrix"], dtype=np.float64)
        feature_names = tuple(cached["features"].tolist())
        if matrix.shape != (60000, len(feature_names)):
            raise ValueError("FEATURE_CACHE_SHAPE_INVALID")
    target = np.asarray(labels, dtype=np.int8)
    task_array = np.asarray(tasks)
    splitter = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=1900)
    train_index, validation_index = next(splitter.split(matrix, target, np.asarray(groups)))

    train_identity = [identities[int(index)] for index in train_index]
    split_sha256 = _canonical_sha(sorted(train_identity))
    submodels = {}
    validation_labels = []
    validation_predictions = []
    train_labels = []
    train_predictions = []
    for task in ("dialogue", "qa", "summarization"):
        task_train_index = train_index[task_array[train_index] == task]
        task_validation_index = validation_index[task_array[validation_index] == task]
        scaler = StandardScaler().fit(matrix[task_train_index])
        train = scaler.transform(matrix[task_train_index])
        validation = scaler.transform(matrix[task_validation_index])
        classifier = LogisticRegression(C=1.0, max_iter=1000, random_state=1900, solver="lbfgs").fit(train, target[task_train_index])
        probabilities = classifier.predict_proba(validation)[:, 1]
        best = None
        for threshold in np.linspace(0.05, 0.95, 1801):
            prediction = (probabilities >= threshold).astype(np.int8)
            result = metrics(target[task_validation_index], prediction)
            key = (result["accuracy"], -result["false_passes"], -result["false_blocks"])
            if best is None or key > best[0]:
                best = (key, float(threshold), result)
        assert best is not None
        threshold = best[1]
        task_train_prediction = (classifier.predict_proba(train)[:, 1] >= threshold).astype(np.int8)
        submodels[task] = {
            "mean": [float(value) for value in scaler.mean_],
            "scale": [float(value) for value in scaler.scale_],
            "coefficients": [float(value) for value in classifier.coef_[0]],
            "intercept": float(classifier.intercept_[0]),
            "threshold": threshold,
            "validation": {
                "train": metrics(target[task_train_index], task_train_prediction),
                "held_out": best[2],
            },
        }
        validation_labels.append(target[task_validation_index])
        validation_predictions.append((probabilities >= threshold).astype(np.int8))
        train_labels.append(target[task_train_index])
        train_predictions.append(task_train_prediction)
        print(json.dumps({"phase": "fit", "frame": task, "held_out": best[2]}, sort_keys=True), flush=True)
    model = {
        "schema": "zoran.raw-text-coherence-model.v2",
        "model_id": MODEL_ID,
        "training_dataset": {
            "name": "HaluEval context-grounded public pairs",
            "cases": int(len(train_index)),
            "held_out_validation_cases": int(len(validation_index)),
            "labels_used_from_halubench": 0,
            "group_split": "sha256(task,context,question), GroupShuffleSplit random_state=1900",
        },
        "training_split_sha256": split_sha256,
        "features": list(feature_names),
        "models": submodels,
        "validation": {
            "train": metrics(np.concatenate(train_labels), np.concatenate(train_predictions)),
            "held_out": metrics(np.concatenate(validation_labels), np.concatenate(validation_predictions)),
        },
    }
    model["model_sha256"] = _canonical_sha(model)
    args.output.write_text(json.dumps(model, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "model_sha256": model["model_sha256"],
        "training_split_sha256": split_sha256,
        "thresholds": {frame: value["threshold"] for frame, value in submodels.items()},
        "validation": model["validation"],
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
