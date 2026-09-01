from question_reformulation_gate import (
    QuestionReformulationGate,
    QuestionReformulationRequest,
    ReformulationCandidate,
    SemanticVector,
)
from tolerance_skill import Decision


VECTOR = SemanticVector(
    actors=("David Guetta",),
    relations=("date de naissance",),
    objects=("date",),
    modality="QUESTION",
)


def candidate(text: str, vector: SemanticVector = VECTOR) -> ReformulationCandidate:
    return ReformulationCandidate(text, vector)


def test_doubt_requires_two_reformulations_before_internet():
    result = QuestionReformulationGate().evaluate(QuestionReformulationRequest(
        "David Guetta est né quand ?", VECTOR,
        (candidate("Quelle est la date de naissance de David Guetta ?"),),
        doubt=True, factual_intent=True, public_persons=("David Guetta",),
    ))
    assert result.decision is Decision.RETRY
    assert result.reasons == ("TWO_REFORMULATIONS_REQUIRED_BEFORE_RETRIEVAL",)


def test_two_equivalent_reformulations_converge_and_require_internet():
    result = QuestionReformulationGate().evaluate(QuestionReformulationRequest(
        "David Guetta est né quand ?", VECTOR,
        (
            candidate("Quelle est la date de naissance de David Guetta ?"),
            candidate("À quelle date David Guetta est-il né ?"),
        ),
        multiframe_incoherence=True,
        factual_intent=True,
        public_persons=("David Guetta",),
    ))
    assert result.decision is Decision.PASS
    assert result.internet_verification_required is True
    assert result.selected_text == "Quelle est la date de naissance de David Guetta ?"


def test_reformulation_cannot_change_actor_relation_number_or_negation():
    drift = SemanticVector(
        actors=("David de Gea",), relations=("date de naissance",), objects=("date",),
    )
    result = QuestionReformulationGate().evaluate(QuestionReformulationRequest(
        "David Guetta est né quand ?", VECTOR,
        (
            candidate("Quelle est la date de naissance de David Guetta ?"),
            candidate("Quelle est la date de naissance de David de Gea ?", drift),
        ),
        doubt=True, public_persons=("David Guetta",),
    ))
    assert result.decision is Decision.VETO
    assert result.reasons == ("SEMANTIC_ROUND_TRIP_DRIFT:1",)


def test_public_person_cannot_disappear_from_surface():
    result = QuestionReformulationGate().evaluate(QuestionReformulationRequest(
        "David Guetta est né quand ?", VECTOR,
        (
            candidate("Quelle est sa date de naissance ?"),
            candidate("À quelle date cette personne est-elle née ?"),
        ),
        doubt=True, public_persons=("David Guetta",),
    ))
    assert result.decision is Decision.VETO
    assert result.reasons == ("PUBLIC_PERSON_DROPPED:David Guetta",)
