from __future__ import annotations

import json
from pathlib import Path


FIXTURE = Path(__file__).with_name("fixtures") / "technical_microcorpus_v0" / "corpus.jsonl"


def build_listener_ontology() -> dict[str, list[str]]:
    records = [json.loads(line) for line in FIXTURE.read_text(encoding="utf-8").splitlines() if line.strip()]
    targets = [record["semantic_target"] for record in records]
    propositions = [item for target in targets for item in target["propositions"]]
    return {
        "intents": sorted({target["intent"] for target in targets}),
        "subjects": sorted({item["s"] for item in propositions}),
        "relations": sorted({item["r"] for item in propositions}),
        "objects": sorted({item["o"] for item in propositions}),
        "polarities": sorted({item["polarity"] for item in propositions if "polarity" in item}),
        "modalities": sorted({item["modality"] for item in propositions if "modality" in item}),
        "conditions": sorted({item["condition"] for item in propositions if "condition" in item}),
        "costs": sorted({item["cost"] for item in propositions if "cost" in item}),
        "restrictions": sorted({item["restriction"] for item in propositions if "restriction" in item}),
        "temporal_steps": sorted({step for target in targets for step in target.get("temporal_order", [])}),
        "reference_sources": sorted({key for target in targets for key in target.get("references", {})}),
        "reference_targets": sorted({value for target in targets for value in target.get("references", {}).values()}),
        "units": sorted({unit for target in targets for unit in target.get("units", [])}),
    }


if __name__ == "__main__":
    print(json.dumps(build_listener_ontology(), ensure_ascii=False, sort_keys=True))
