from dataclasses import replace
import json
from pathlib import Path

from phenomenal_coherence import CANONICAL_FRAMES
from phenomenal_resource_gate import (
    PhenomenalResourceGate,
    PhenomenalResourceRequest,
    PhenomenalResourceRound,
    ProxyResource,
)
from tolerance_skill import Decision


H = "a" * 64
ROOT = Path(__file__).resolve().parent
ROUND1_CERTIFICATE = json.loads((ROOT / "audit" / "PHENOMENAL_RESOURCE_CERTIFICATE_ROUND1_V17.json").read_text(encoding="utf-8"))
ROUND2_CERTIFICATE = json.loads((ROOT / "audit" / "PHENOMENAL_RESOURCE_CERTIFICATE_ROUND2_V17.json").read_text(encoding="utf-8"))


def round_(index, *, missing_frame=False, missing_proxy=False, resources=None):
    frames = {frame: H for frame in CANONICAL_FRAMES}
    if missing_frame:
        frames.pop("planetary")
    proxies = (
        ProxyResource("beta", 10.0, "score", H, "2026-09-01T00:00:00Z"),
        ProxyResource("dphi", 10.0, "score", H, "2026-09-01T00:00:00Z"),
        ProxyResource("T", 0.0, "score", H, "2026-09-01T00:00:00Z"),
        ProxyResource("sigma", 0.0, "score", H, "2026-09-01T00:00:00Z"),
    )
    if missing_proxy:
        proxies = proxies[:-1]
    resource_ids = tuple(resources or (f"resource-{index}",))
    certificate = None
    if not missing_frame and not missing_proxy:
        if index == 1 and resource_ids == ("resource-1",):
            certificate = ROUND1_CERTIFICATE
        elif index == 2 and resource_ids == ("alternative",):
            certificate = ROUND2_CERTIFICATE
    return PhenomenalResourceRound(index, resource_ids, frames, proxies, "2026-09-01T00:01:00Z", certificate)


def request(*rounds):
    return PhenomenalResourceRequest(H, ("beta", "dphi", "T", "sigma"), rounds)


def test_complete_first_round_passes():
    result = PhenomenalResourceGate().evaluate(request(round_(1)))
    assert result.decision is Decision.PASS and result.completed_round == 1


def test_self_authored_complete_round_without_host_attestation_is_veto():
    unsigned = replace(round_(1), authority_certificate=None)
    result = PhenomenalResourceGate().evaluate(request(unsigned))
    assert result.decision is Decision.VETO
    assert result.reasons == ("HALLUCINATION_BLOQUANTE_MESURE_SANS_ATTESTATION",)


def test_forged_host_resource_attestation_is_vetoed():
    forged = json.loads(json.dumps(ROUND1_CERTIFICATE))
    forged["payload"]["round_index"] = 2
    result = PhenomenalResourceGate().evaluate(request(replace(round_(1), authority_certificate=forged)))
    assert result.decision is Decision.VETO


def test_incomplete_first_round_requires_exactly_one_retry():
    result = PhenomenalResourceGate().evaluate(request(round_(1, missing_frame=True)))
    assert result.decision is Decision.RETRY
    assert result.reasons[0] == "GYROPHARE_MESURE_INCOMPLETE_RECHERCHE_TOUR_2_REQUISE"
    assert "OWNER:HOST_RETRIEVAL_CONNECTOR" in result.reasons
    assert "NEXT_ACTION:SEARCH_DISTINCT_RESOURCE_ROUND_2" in result.reasons
    assert "REMAINING_SEARCH_BUDGET:1" in result.reasons


def test_incomplete_second_round_returns_veto_with_beacon():
    result = PhenomenalResourceGate().evaluate(request(round_(1, missing_frame=True), round_(2, missing_proxy=True)))
    assert result.decision is Decision.VETO
    assert result.state == "GYROPHARE"
    assert result.reasons[:3] == ("GYROPHARE_TRACE_ABSENTE_APRES_DEUX_RECHERCHES", "HALLUCINATION_BLOQUANTE_OU_PHENOMENE_INEXISTANT", "RETOUR_ENVOYEUR")


def test_complete_second_round_passes_with_other_resources():
    result = PhenomenalResourceGate().evaluate(request(round_(1, missing_frame=True), round_(2, resources=("alternative",))))
    assert result.decision is Decision.PASS and result.completed_round == 2


def test_third_round_is_forbidden():
    assert PhenomenalResourceGate().evaluate(request(round_(1), round_(2), round_(3))).decision is Decision.VETO


def test_identical_second_round_resources_are_vetoed():
    result = PhenomenalResourceGate().evaluate(request(round_(1, missing_frame=True, resources=("same",)), round_(2, resources=("same",))))
    assert result.decision is Decision.VETO
    assert result.reasons == ("SECOND_ROUND_HAS_NO_NEW_RESOURCE",)


def test_complete_first_round_forbids_unnecessary_second_round():
    result = PhenomenalResourceGate().evaluate(request(round_(1), round_(2)))
    assert result.decision is Decision.VETO
    assert result.reasons == ("SECOND_ROUND_NOT_AUTHORIZED_AFTER_COMPLETE_FIRST_ROUND",)


def test_missing_request_is_retry_not_fabricated_measurement():
    result = PhenomenalResourceGate().evaluate(None)
    assert result.decision is Decision.RETRY
    assert "NEXT_ACTION:SEARCH_DISTINCT_RESOURCE_ROUND_1" in result.reasons
    assert "REMAINING_SEARCH_BUDGET:2" in result.reasons


def test_empty_round_list_starts_bounded_recovery_not_veto():
    result = PhenomenalResourceGate().evaluate(request())
    assert result.decision is Decision.RETRY
    assert "REMAINING_SEARCH_BUDGET:2" in result.reasons


def test_invalid_second_round_identity_exhausts_budget_and_vetoes():
    result = PhenomenalResourceGate().evaluate(request(
        round_(1, missing_frame=True),
        round_(2, missing_proxy=True, resources=("",)),
    ))
    assert result.decision is Decision.VETO
    assert result.reasons[:3] == (
        "GYROPHARE_TRACE_ABSENTE_APRES_DEUX_RECHERCHES",
        "HALLUCINATION_BLOQUANTE_OU_PHENOMENE_INEXISTANT",
        "RETOUR_ENVOYEUR",
    )
