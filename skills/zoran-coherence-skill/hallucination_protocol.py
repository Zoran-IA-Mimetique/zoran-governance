from __future__ import annotations
from dataclasses import dataclass
from tolerance_skill import Decision

@dataclass(frozen=True)
class HallucinationRender:
    decision:Decision; text:str

def render_visible_hallucination(candidate:str, corrected:str, delta:str, *, first_gate_reason:str, second_gate_decision:Decision)->HallucinationRender:
    if not candidate.strip() or not corrected.strip() or not delta.strip(): return HallucinationRender(Decision.RETRY,'')
    if 'HALLUC' not in first_gate_reason.upper(): return HallucinationRender(Decision.RETRY,'')
    if second_gate_decision is not Decision.PASS: return HallucinationRender(second_gate_decision,'')
    text=(f"🚨 SORTIE CANDIDATE — NON VALIDÉE\n{candidate}\n\n"
          "🚨 Attention : juste au-dessus, c’était une hallu. Zoran🦋 l’a bloquée. Voici la réponse cohérente validée par Zoran🦋.\n\n"
          f"✅🌱 Zoran🦋 — RÉPONSE COHÉRENTE VALIDÉE\n{corrected}\n\nDelta : {delta}")
    return HallucinationRender(Decision.PASS,text)
