import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from frame_search import FrameDefinition, FrameSearchEngine
from host_session_guard import HostSessionGuard, HostSessionRequest, canonical_bytes
from tolerance_skill import Decision
from zoran_runtime import ZoranRuntime


ROOT = Path(__file__).resolve().parent
FIXTURE = json.loads((ROOT / "audit" / "HOST_SESSION_TEST_CERTIFICATE.json").read_text(encoding="utf-8"))
MISSION = hashlib.sha256(b"mission-v16-test").hexdigest()
PROMPT = hashlib.sha256(b"prompt-v16-test").hexdigest()
OUTPUT = "Réponse validée."
OBSERVED = "2026-08-31T22:05:00Z"


def request(*, certificate=FIXTURE, mission=MISSION, prompt=PROMPT, output=OUTPUT, observed=OBSERVED):
    return HostSessionRequest(mission, prompt, output, certificate, observed)


def test_valid_opaque_session_authorizes_display():
    result = HostSessionGuard().evaluate(request())
    assert result.decision is Decision.PASS
    assert result.state == "DISPLAY_AUTHORIZED"
    assert result.certificate_sha256 == FIXTURE["envelope_sha256"]


def test_runtime_refuses_display_before_semantic_speech_gate():
    runtime = ZoranRuntime(frame_engine=FrameSearchEngine((
        FrameDefinition("general", "General", ("coherence",), priority=1),
    )))
    result = runtime.finalize_output(request())
    assert result.decision is Decision.RETRY
    assert result.state == "SPEECH_WITHHELD"


def test_missing_certificate_is_retrye():
    result = HostSessionGuard().evaluate(request(certificate=None))
    assert result.decision is Decision.RETRY
    assert result.state == "CERTIFICATE_REQUIRED"


def test_caller_supplied_session_registry_is_vetoed():
    result = HostSessionGuard().evaluate(request(), trust_registry={"forged": "trust"})
    assert result.decision is Decision.VETO
    assert result.reasons == ("CALLER_SESSION_TRUST_REGISTRY_FORBIDDEN",)


def test_output_substitution_is_vetoed():
    result = HostSessionGuard().evaluate(request(output=OUTPUT + " Altérée."))
    assert result.decision is Decision.VETO
    assert result.reasons == ("SESSION_CERTIFICATE_IDENTITY_MISMATCH",)


def test_mission_or_prompt_substitution_is_vetoed():
    assert HostSessionGuard().evaluate(request(mission="a" * 64)).decision is Decision.VETO
    assert HostSessionGuard().evaluate(request(prompt="b" * 64)).decision is Decision.VETO


def test_expired_or_early_certificate_is_vetoed():
    assert HostSessionGuard().evaluate(request(observed="2026-08-31T21:59:59Z")).decision is Decision.VETO
    assert HostSessionGuard().evaluate(request(observed="2026-08-31T22:10:01Z")).decision is Decision.VETO


def test_signature_mutation_is_vetoed():
    mutated = deepcopy(FIXTURE)
    raw = bytearray(base64.b64decode(mutated["signature_base64"]))
    raw[0] ^= 1
    mutated["signature_base64"] = base64.b64encode(raw).decode("ascii")
    body = {key: mutated[key] for key in sorted(set(mutated) - {"envelope_sha256"})}
    mutated["envelope_sha256"] = hashlib.sha256(canonical_bytes(body)).hexdigest()
    result = HostSessionGuard().evaluate(request(certificate=mutated))
    assert result.decision is Decision.VETO
    assert result.reasons == ("SESSION_CERTIFICATE_SIGNATURE_INVALID",)


def test_stage_or_chain_mutation_is_vetoed():
    mutated = deepcopy(FIXTURE)
    mutated["payload"]["stages"][0]["stage_id"] = "terminal"
    body = {key: mutated[key] for key in sorted(set(mutated) - {"envelope_sha256"})}
    mutated["envelope_sha256"] = hashlib.sha256(canonical_bytes(body)).hexdigest()
    assert HostSessionGuard().evaluate(request(certificate=mutated)).decision is Decision.VETO


def test_non_pass_terminal_cannot_authorize_display():
    mutated = deepcopy(FIXTURE)
    mutated["payload"]["terminal_status"] = "RETRY"
    body = {key: mutated[key] for key in sorted(set(mutated) - {"envelope_sha256"})}
    mutated["envelope_sha256"] = hashlib.sha256(canonical_bytes(body)).hexdigest()
    assert HostSessionGuard().evaluate(request(certificate=mutated)).decision is Decision.VETO
