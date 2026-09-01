from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from tolerance_skill import Decision

COMPONENT_ID = "ZORAN_K3_ADAPTER"
VERSION = "11.0.0"

K3_CONTINUE = "K3_CONTINUE"
K3_REPLAN = "K3_REPLAN_SAME_OBJECT"
K3_STOP = "K3_STOP_ACTION"
K3_MEASURE = "K3_REQUEST_MEASUREMENT"


@dataclass(frozen=True)
class K3Translation:
    skill_decision: Decision
    k3_instruction: str
    receipt_sha256: str


class K3Adapter:
    """Unambiguous translation of skill verdicts toward a K3-controlled workflow."""

    MAP = {
        Decision.PASS: K3_CONTINUE,
        Decision.RETRY: K3_REPLAN,
        Decision.VETO: K3_STOP,
    }

    def translate(self, decision: Decision, *, trace_required: bool = False) -> K3Translation:
        instruction = K3_MEASURE if decision is Decision.RETRY and trace_required else self.MAP[decision]
        payload = {"component": COMPONENT_ID, "version": VERSION, "skill_decision": decision.value, "k3_instruction": instruction}
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return K3Translation(decision, instruction, digest)
