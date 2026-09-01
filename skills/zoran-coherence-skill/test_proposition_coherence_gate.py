from dataclasses import replace

from proposition_coherence_gate import (
    Proposition,
    PropositionCoherenceGate,
    PropositionCoherenceRequest,
)
from tolerance_skill import Decision


Q = "a" * 64
WEB = "b" * 64


def base_claim(**changes):
    value = Proposition(
        claim_id="c1",
        subject="David Guetta",
        relation="date de naissance",
        object="7 novembre 1967",
        date="1967-11-07",
        evidence_id="e1",
        public_person_fact=True,
    )
    return replace(value, **changes)


def evidence(**changes):
    value = Proposition(
        claim_id="source-c1",
        subject="David Guetta",
        relation="date de naissance",
        object="7 novembre 1967",
        date="1967-11-07",
        evidence_id="e1",
        exact_quote="David Guetta, né le 7 novembre 1967.",
        public_person_fact=True,
    )
    return replace(value, **changes)


def request(claim, source, receipts=(("David Guetta", WEB),)):
    return PropositionCoherenceRequest(
        Q,
        ("David Guetta",),
        ("date de naissance",),
        (claim,),
        (source,),
        receipts,
    )


def test_faithful_public_person_claim_passes_with_local_and_internet_proof():
    result = PropositionCoherenceGate().evaluate(request(base_claim(), evidence()))
    assert result.decision is Decision.PASS


def test_entity_recombination_is_blocked():
    result = PropositionCoherenceGate().evaluate(request(
        base_claim(subject="David Guetta"),
        evidence(subject="David de Gea"),
    ))
    assert result.decision is Decision.VETO
    assert result.reasons == ("SUBJECT_RELATION_OBJECT_BINDING_FAILURE:c1",)


def test_date_recombination_is_blocked():
    result = PropositionCoherenceGate().evaluate(request(
        base_claim(date="1966-11-07", object="7 novembre 1966"),
        evidence(),
    ))
    assert result.decision is Decision.VETO


def test_negation_scope_change_is_blocked():
    result = PropositionCoherenceGate().evaluate(request(
        base_claim(polarity="NEGATIVE"),
        evidence(polarity="POSITIVE"),
    ))
    assert result.decision is Decision.VETO


def test_public_person_claim_waits_for_internet_receipt():
    result = PropositionCoherenceGate().evaluate(request(base_claim(), evidence(), receipts=()))
    assert result.decision is Decision.RETRY
    assert result.reasons == ("PUBLIC_PERSON_INTERNET_VERIFICATION_REQUIRED:c1",)


def test_question_relation_mismatch_is_blocked_even_when_quote_is_authentic():
    result = PropositionCoherenceGate().evaluate(PropositionCoherenceRequest(
        Q,
        ("David Guetta",),
        ("profession",),
        (base_claim(),),
        (evidence(),),
        (("David Guetta", WEB),),
    ))
    assert result.decision is Decision.VETO
    assert result.reasons == ("QUESTION_RELATION_MISMATCH:c1",)
