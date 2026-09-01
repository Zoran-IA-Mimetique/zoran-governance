import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

from claim_evidence_gate import (
    ClaimEvidenceGate, ClaimEvidenceRequest, ClaimUnit, Disposition, EvidenceGrade,
    EvidenceRelation, EvidenceSpan, SourceReliability, UnitKind, segment_output,
)
from tolerance_skill import Decision


H = "a" * 64
NOW = "2026-08-31T22:00:00Z"
WIKIMEDIA_CERTIFICATE = json.loads((Path(__file__).parent / "audit" / "WIKIMEDIA_TEST_CERTIFICATE_V17.json").read_text(encoding="utf-8"))


def span(*, relation=EvidenceRelation.SUPPORTS, grade=EvidenceGrade.OFFICIAL_PRIMARY, source_id="s1", root="root-1", valid_until=None):
    source = "La capitale de la France est Paris."
    quote = "La capitale de la France est Paris."
    return EvidenceSpan(
        source_id, source, hashlib.sha256(source.encode()).hexdigest(), quote,
        hashlib.sha256(quote.encode()).hexdigest(), relation, grade, root,
        "2026-08-31T20:00:00Z", valid_until, SourceReliability.DEMONSTRATED, "b" * 64,
        WIKIMEDIA_CERTIFICATE if relation is EvidenceRelation.SUPPORTS else None,
    )


def request(text, units):
    claims = tuple(item.claim_id for item in units if item.kind is UnitKind.FACTUAL and item.claim_id)
    return ClaimEvidenceRequest(text, tuple(units), NOW, H, claims)


def factual(index, text, disposition, claim_id, evidence=(), *, intrinsic="PASS", public=True, time_sensitive=False):
    return ClaimUnit(index, text, UnitKind.FACTUAL, disposition, claim_id, tuple(evidence), intrinsic, public, time_sensitive)


def test_segment_output_is_deterministic():
    assert segment_output("Paris est en France.\nD'accord !") == ("Paris est en France.", "D'accord !")


def test_non_factual_output_passes_when_fully_covered():
    text = "Plan :"
    unit = ClaimUnit(0, text, UnitKind.NON_FACTUAL, Disposition.NON_FACTUAL)
    result = ClaimEvidenceGate().evaluate(request(text, (unit,)))
    assert result.decision is Decision.PASS and result.factual_units == 0


def test_supported_factual_claim_passes():
    text = "Paris est la capitale de la France."
    unit = factual(0, text, Disposition.ASSERT, "c1", (span(),))
    result = ClaimEvidenceGate().evaluate(request(text, (unit,)))
    assert result.decision is Decision.PASS and result.asserted_units == 1


def test_public_person_fact_cannot_disable_wikimedia_first_pass():
    text = "David Guetta est une personne publique."
    source = text
    no_wiki = EvidenceSpan(
        "public-source", source, hashlib.sha256(source.encode()).hexdigest(), source,
        hashlib.sha256(source.encode()).hexdigest(), EvidenceRelation.SUPPORTS,
        EvidenceGrade.REPUTABLE_SECONDARY, "public-root", "2026-08-31T20:00:00Z",
        None, SourceReliability.REPUTABLE_SECONDARY, "b" * 64, None,
    )
    unit = ClaimUnit(
        0, text, UnitKind.FACTUAL, Disposition.ASSERT, "person-1", (no_wiki,),
        "PASS", False, False, True,
    )
    result = ClaimEvidenceGate().evaluate(request(text, (unit,)))
    assert result.decision is Decision.RETRY
    assert result.reasons == ("GYROPHARE_WIKIMEDIA_FIRST_PASS_MISSING:person-1",)


def test_public_claim_requires_signed_wikimedia_first_pass():
    text = "Paris est la capitale de la France."
    unsupported_lookup = replace(span(), wikimedia_certificate=None)
    unit = factual(0, text, Disposition.ASSERT, "c1", (unsupported_lookup,))
    result = ClaimEvidenceGate().evaluate(request(text, (unit,)))
    assert result.decision is Decision.RETRY
    assert "GYROPHARE_WIKIMEDIA_FIRST_PASS_MISSING:c1" in result.reasons


def test_caller_cannot_forge_wikimedia_certificate():
    text = "Paris est la capitale de la France."
    forged = deepcopy(WIKIMEDIA_CERTIFICATE)
    forged["payload"]["page_title"] = "Page inventée"
    unit = factual(0, text, Disposition.ASSERT, "c1", (replace(span(), wikimedia_certificate=forged),))
    result = ClaimEvidenceGate().evaluate(request(text, (unit,)))
    assert result.decision is Decision.RETRY
    assert any("WIKIMEDIA_ENVELOPE_SHA_INVALID" in reason for reason in result.reasons)


def test_assertion_without_support_is_retry():
    text = "Paris est la capitale de la France."
    unit = factual(0, text, Disposition.ASSERT, "c1")
    result = ClaimEvidenceGate().evaluate(request(text, (unit,)))
    assert result.decision is Decision.RETRY
    assert result.reasons == ("ASSERTED_CLAIM_WITHOUT_VERIFIED_SUPPORT:c1",)


def test_output_unit_omission_is_veto():
    text = "Premier fait. Second fait."
    unit = factual(0, "Premier fait.", Disposition.ASSERT, "c1", (span(),))
    assert ClaimEvidenceGate().evaluate(request(text, (unit,))).decision is Decision.VETO


def test_duplicate_claim_identity_is_veto():
    text = "Premier fait. Second fait."
    units = (
        factual(0, "Premier fait.", Disposition.ASSERT, "c1", (span(),)),
        factual(1, "Second fait.", Disposition.ASSERT, "c1", (span(source_id="s2"),)),
    )
    assert ClaimEvidenceGate().evaluate(request(text, units)).decision is Decision.VETO


def test_exact_quote_must_exist_in_bound_source():
    good = span()
    bad = EvidenceSpan(good.source_id, good.source_text, good.source_sha256, "Lyon", hashlib.sha256(b"Lyon").hexdigest(), good.relation, good.grade, good.provenance_root, good.observed_at, reliability=SourceReliability.DEMONSTRATED, authority_receipt_sha256="b" * 64)
    text = "Paris est la capitale de la France."
    unit = factual(0, text, Disposition.ASSERT, "c1", (bad,))
    assert ClaimEvidenceGate().evaluate(request(text, (unit,))).decision is Decision.RETRY


def test_expired_evidence_cannot_support_assertion():
    text = "Paris est la capitale de la France."
    unit = factual(0, text, Disposition.ASSERT, "c1", (span(valid_until="2026-08-31T21:00:00Z"),), time_sensitive=True)
    result = ClaimEvidenceGate().evaluate(request(text, (unit,)))
    assert result.decision is Decision.RETRY
    assert any("EVIDENCE_EXPIRED" in reason for reason in result.reasons)


def test_equal_grade_contradiction_vetoes_assertion():
    text = "Paris est la capitale de la France."
    support = span()
    contradiction = span(relation=EvidenceRelation.CONTRADICTS, source_id="s2", root="root-2")
    unit = factual(0, text, Disposition.ASSERT, "c1", (support, contradiction))
    result = ClaimEvidenceGate().evaluate(request(text, (unit,)))
    assert result.decision is Decision.VETO
    assert "STRONG_CONTRADICTION_BLOCKS_ASSERTION:c1" in result.reasons


def test_explicit_abstention_is_a_controlled_pass():
    text = "Je ne peux pas établir ce fait : preuve insuffisante."
    unit = factual(0, text, Disposition.ABSTAIN, "c1", intrinsic="RETRY")
    result = ClaimEvidenceGate().evaluate(request(text, (unit,)))
    assert result.decision is Decision.PASS and result.abstained_units == 1


def test_hidden_abstention_is_veto():
    text = "Ce fait est probablement vrai."
    unit = factual(0, text, Disposition.ABSTAIN, "c1", intrinsic="RETRY")
    assert ClaimEvidenceGate().evaluate(request(text, (unit,))).decision is Decision.VETO


def test_contradiction_must_be_visible_when_abstaining():
    text = "Je ne peux pas établir ce fait : preuve insuffisante."
    unit = factual(0, text, Disposition.ABSTAIN, "c1", (span(relation=EvidenceRelation.CONTRADICTS),), intrinsic="RETRY")
    assert ClaimEvidenceGate().evaluate(request(text, (unit,))).decision is Decision.VETO


def test_missing_request_is_retry():
    assert ClaimEvidenceGate().evaluate(None).decision is Decision.RETRY


def test_false_fact_cannot_be_relabelled_non_factual():
    text = "La Lune est fabriquée en fromage."
    unit = ClaimUnit(0, text, UnitKind.NON_FACTUAL, Disposition.NON_FACTUAL)
    result = ClaimEvidenceGate().evaluate(request(text, (unit,)))
    assert result.decision is Decision.VETO
    assert result.reasons == ("INTRINSIC_MATERIAL_COHERENCE_CONFLICT:0",)


def test_undemonstrated_source_raises_beacon_and_retry():
    text = "Paris est la capitale de la France."
    weak = span()
    weak = EvidenceSpan(weak.source_id, weak.source_text, weak.source_sha256, weak.exact_quote, weak.quote_sha256, weak.relation, weak.grade, weak.provenance_root, weak.observed_at)
    result = ClaimEvidenceGate().evaluate(request(text, (factual(0, text, Disposition.ASSERT, "c1", (weak,)),)))
    assert result.decision is Decision.RETRY
    assert any("GYROPHARE_SOURCE_NON_DEMONTREE" in reason for reason in result.reasons)


def test_exact_but_irrelevant_quote_cannot_support_claim():
    source = "Paris est la capitale de la France. La Lune est un satellite naturel."
    quote = "Paris est la capitale de la France."
    irrelevant = EvidenceSpan("s1", source, hashlib.sha256(source.encode()).hexdigest(), quote, hashlib.sha256(quote.encode()).hexdigest(), EvidenceRelation.SUPPORTS, EvidenceGrade.OFFICIAL_PRIMARY, "root", "2026-08-31T20:00:00Z", reliability=SourceReliability.DEMONSTRATED, authority_receipt_sha256="b" * 64)
    text = "La Lune est un satellite naturel."
    result = ClaimEvidenceGate().evaluate(request(text, (factual(0, text, Disposition.ASSERT, "c1", (irrelevant,)),)))
    assert result.decision is Decision.RETRY
    assert any("CITATION_CLAIM_COHERENCE_FAILURE" in reason for reason in result.reasons)


def test_abstention_cannot_smuggle_certain_assertion():
    text = "Preuve insuffisante, mais la Lune est certainement fabriquée en fromage."
    units = (
        factual(0, "Preuve insuffisante,", Disposition.ABSTAIN, "c1", intrinsic="RETRY"),
        factual(1, "mais la Lune est certainement fabriquée en fromage.", Disposition.ABSTAIN, "c2", intrinsic="RETRY"),
    )
    assert ClaimEvidenceGate().evaluate(request(text, units)).decision is Decision.VETO
