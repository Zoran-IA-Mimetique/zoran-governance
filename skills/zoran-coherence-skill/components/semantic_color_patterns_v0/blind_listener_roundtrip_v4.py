from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path

from components.semantic_color_patterns_v0.discourse_realizer_v1 import SemanticDiscourse
from components.semantic_color_patterns_v0.listener_ontology_v4 import build_listener_ontology
from components.semantic_color_patterns_v0.semantic_equivalence_normalizer_v4 import (
    SemanticEquivalenceNormalizerV4,
)


@dataclass(frozen=True)
class BlindListenerCaseV4:
    id: str
    decision: str
    alignment: float
    missing_atoms: tuple[str, ...]
    extra_atoms: tuple[str, ...]
    vetoes: tuple[str, ...]


@dataclass(frozen=True)
class BlindListenerRoundtripReceiptV4:
    case_count: int
    pass_count: int
    retry_count: int
    veto_count: int
    mean_alignment: float
    score_10: float
    promotion: str
    cases: tuple[BlindListenerCaseV4, ...]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _rows(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def evaluate_blind_listener_roundtrip_v4(
    *,
    corpus_path: Path,
    listener_path: Path,
) -> BlindListenerRoundtripReceiptV4:
    targets = _rows(corpus_path)
    reconstructions = _rows(listener_path)
    target_ids = [item.get("id") for item in targets]
    observed_ids = [item.get("id") for item in reconstructions]
    if target_ids != observed_ids or len(target_ids) != len(set(target_ids)):
        raise ValueError("blind listener case identities or order changed")

    normalizer = SemanticEquivalenceNormalizerV4(build_listener_ontology())
    cases: list[BlindListenerCaseV4] = []
    for target_row, observed_row in zip(targets, reconstructions):
        target = SemanticDiscourse.from_target(target_row["semantic_target"])
        observed_payload = {key: value for key, value in observed_row.items() if key != "id"}
        observed = SemanticDiscourse.from_target(observed_payload)
        receipt = normalizer.compare(target, observed)
        cases.append(BlindListenerCaseV4(
            id=str(target_row["id"]),
            decision=receipt.decision,
            alignment=receipt.alignment,
            missing_atoms=receipt.missing_atoms,
            extra_atoms=receipt.extra_atoms,
            vetoes=receipt.vetoes,
        ))

    mean = sum(case.alignment for case in cases) / len(cases)
    return BlindListenerRoundtripReceiptV4(
        case_count=len(cases),
        pass_count=sum(case.decision == "PASS" for case in cases),
        retry_count=sum(case.decision == "RETRY" for case in cases),
        veto_count=sum(case.decision == "VETO" for case in cases),
        mean_alignment=mean,
        score_10=10.0 * mean,
        promotion="FORBIDDEN",
        cases=tuple(cases),
    )
