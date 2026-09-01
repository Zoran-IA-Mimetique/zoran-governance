#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import itertools
import json
from pathlib import Path

from phenomenal_coherence import (
    CANONICAL_FRAMES,
    SUPERIOR_FRAMES,
    CausalBenefit,
    FrameTransition,
    PhenomenalCoherenceEngine,
    PhenomenalCoherenceRequest,
    PhenomenalSnapshot,
    evidence_sha256,
)
from tolerance_skill import Decision


ROOT = Path(__file__).resolve().parent
MISSION = "a" * 64
BASELINE = "b" * 64
CANDIDATE = "c" * 64
CONTRACT = "d" * 64
RESOURCE_GATE_RECEIPT = "e" * 64
STATES = ("gain", "preserve", "regress", "missing")


def _request(states: tuple[str, ...]) -> PhenomenalCoherenceRequest:
    transitions = []
    causal = []
    for frame_id, state in zip(CANONICAL_FRAMES, states):
        if state == "missing":
            continue
        after = {"gain": 11, "preserve": 10, "regress": 9}[state]
        evidence = f"campaign-transition:{frame_id}:{state}"
        transitions.append(FrameTransition(frame_id, 10, after, evidence, evidence_sha256(evidence)))
        if frame_id in SUPERIOR_FRAMES:
            causal_evidence = f"campaign-causal:{frame_id}:{state}"
            causal.append(
                CausalBenefit(
                    frame_id,
                    f"campaign-intervention:{frame_id}",
                    after,
                    after - 1,
                    f"remove campaign intervention:{frame_id}",
                    causal_evidence,
                    evidence_sha256(causal_evidence),
                )
            )
    by_frame = {item.frame_id: item for item in transitions}
    trajectory = []
    if set(by_frame) == set(CANONICAL_FRAMES):
        for t in range(3):
            if t == 0:
                scores = {frame_id: 9 for frame_id in CANONICAL_FRAMES}
            elif t == 1:
                scores = {frame_id: 10 for frame_id in CANONICAL_FRAMES}
            else:
                scores = {frame_id: by_frame[frame_id].after_s for frame_id in CANONICAL_FRAMES}
            evidence = f"campaign-snapshot:{t}:{','.join(states)}"
            trajectory.append(PhenomenalSnapshot(t, scores, CONTRACT, evidence, evidence_sha256(evidence)))
    return PhenomenalCoherenceRequest(
        "campaign-object",
        MISSION,
        BASELINE,
        CANDIDATE,
        CONTRACT,
        tuple(transitions),
        tuple(causal),
        tuple(trajectory),
        resource_gate_receipt_sha256=RESOURCE_GATE_RECEIPT,
    )


def _expected(states: tuple[str, ...]) -> Decision:
    if "missing" in states:
        return Decision.RETRY
    if "regress" in states:
        return Decision.VETO
    by_frame = dict(zip(CANONICAL_FRAMES, states))
    if by_frame["local"] != "gain":
        return Decision.VETO
    if any(by_frame[frame_id] != "gain" for frame_id in SUPERIOR_FRAMES):
        return Decision.VETO
    return Decision.PASS


def main() -> None:
    engine = PhenomenalCoherenceEngine()
    false_pass = 0
    false_block = 0
    cases = 0
    decisions = {item.value: 0 for item in Decision}
    for states in itertools.product(STATES, repeat=len(CANONICAL_FRAMES)):
        observed = engine.evaluate(_request(states)).decision
        expected = _expected(states)
        cases += 1
        decisions[observed.value] += 1
        if observed is Decision.PASS and expected is not Decision.PASS:
            false_pass += 1
        if observed is not Decision.PASS and expected is Decision.PASS:
            false_block += 1

    base = _request(("gain", "preserve", "preserve", "gain", "gain", "gain"))
    baseline_receipt = engine.evaluate(base).receipt_sha256
    replay_divergences = sum(
        engine.evaluate(base).receipt_sha256 != baseline_receipt
        for _ in range(5_000)
    )
    payload = {
        "component": "ZORAN_PHENOMENAL_COHERENCE_CAMPAIGN",
        "version": "2.0.0",
        "cases": cases,
        "state_space": list(STATES),
        "decisions": decisions,
        "false_pass": false_pass,
        "false_block": false_block,
        "deterministic_replays": 5_000,
        "replay_divergences": replay_divergences,
        "baseline_receipt_sha256": baseline_receipt,
    }
    payload["campaign_sha256"] = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if false_pass or false_block or replay_divergences:
        raise SystemExit(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    output = ROOT / "PHENOMENAL_COHERENCE_CAMPAIGN_RESULTS.json"
    output.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
