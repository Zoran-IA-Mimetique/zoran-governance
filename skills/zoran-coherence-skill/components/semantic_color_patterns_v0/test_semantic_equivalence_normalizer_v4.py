import inspect

import pytest

from components.semantic_color_patterns_v0.discourse_realizer_v1 import (
    SemanticDiscourse,
    SemanticProposition,
)
from components.semantic_color_patterns_v0.listener_ontology_v4 import build_listener_ontology
from components.semantic_color_patterns_v0.semantic_equivalence_normalizer_v4 import (
    SemanticEquivalenceNormalizerV4,
)


def _discourse(*propositions, intent="EXPLIQUER", temporal=(), references=(), units=()):
    return SemanticDiscourse(
        intent=intent,
        propositions=tuple(propositions),
        temporal_order=tuple(temporal),
        references=tuple(references),
        units=tuple(units),
    )


def _normalizer():
    return SemanticEquivalenceNormalizerV4(build_listener_ontology())


def test_identity_is_a_complete_non_compensatory_pass():
    target = _discourse(
        SemanticProposition("cache", "réduit", "latence"),
        temporal=("mise_en_cache", "lecture"),
        references=(("elle", "invalidation explicite"),),
        units=("seconde",),
    )
    receipt = _normalizer().compare(target, target)
    assert receipt.decision == "PASS"
    assert receipt.alignment == 1.0
    assert receipt.missing_atoms == receipt.extra_atoms == ()


def test_surface_separators_case_and_accents_do_not_change_identity():
    target = _discourse(SemanticProposition("coupe-circuit", "suspend_temporairement", "appels"))
    observed = _discourse(SemanticProposition("COUPE CIRCUIT", "suspend temporairement", "appels"))
    assert _normalizer().compare(target, observed).decision == "PASS"


def test_negation_and_possibility_may_live_in_relation_or_metadata():
    target = _discourse(
        SemanticProposition("envoi", "ne_prouve_pas", "réception", polarity="negative"),
        SemanticProposition("réessai", "peut_créer", "doublon", modality="possible"),
    )
    observed = _discourse(
        SemanticProposition("envoi", "ne prouve pas", "réception"),
        SemanticProposition("réessai", "peut créer", "doublon"),
    )
    assert _normalizer().compare(target, observed).decision == "PASS"


def test_intent_subtype_keeps_the_same_public_speech_act():
    target = _discourse(SemanticProposition("attente", "cause", "blocage"), intent="EXPLIQUER")
    observed = _discourse(
        SemanticProposition("attente", "cause", "blocage"),
        intent="EXPLIQUER_CAUSALITÉ",
    )
    assert _normalizer().compare(target, observed).decision == "PASS"


@pytest.mark.parametrize(
    "field",
    ("temporal", "references", "units"),
)
def test_missing_non_compensatory_context_requires_mission_restart(field):
    kwargs = {
        "temporal": ("départ", "arrivée"),
        "references": (("elle", "source"),),
        "units": ("seconde",),
    }
    target = _discourse(SemanticProposition("source", "alimente", "sortie"), **kwargs)
    kwargs[field] = ()
    receipt = _normalizer().compare(
        target,
        _discourse(SemanticProposition("source", "alimente", "sortie"), **kwargs),
    )
    assert receipt.decision == "RETRY"
    assert receipt.alignment < 1.0
    assert receipt.missing_atoms


def test_opposite_polarity_is_a_veto_not_a_repairable_average():
    target = _discourse(SemanticProposition("envoi", "prouve", "réception", polarity="negative"))
    observed = _discourse(SemanticProposition("envoi", "prouve", "réception", polarity="positive"))
    receipt = _normalizer().compare(target, observed)
    assert receipt.decision == "VETO"
    assert "POLARITY_CONTRADICTION" in receipt.vetoes


def test_extra_proposition_cannot_be_averaged_away():
    target = _discourse(SemanticProposition("capteur", "mesure", "température"))
    observed = _discourse(
        SemanticProposition("capteur", "mesure", "température"),
        SemanticProposition("capteur", "certifie", "sécurité"),
    )
    receipt = _normalizer().compare(target, observed)
    assert receipt.decision == "RETRY"
    assert receipt.extra_atoms


def test_normalizer_has_no_case_id_or_target_pair_lookup():
    source = inspect.getsource(SemanticEquivalenceNormalizerV4)
    assert "NET-01" not in source
    assert "corpus.jsonl" not in source
    assert "target_sha256" not in source


def test_ontology_order_does_not_change_the_receipt():
    ontology = build_listener_ontology()
    reversed_ontology = {key: list(reversed(values)) for key, values in ontology.items()}
    target = _discourse(SemanticProposition("cache", "réduit", "latence et charge source"))
    observed = _discourse(SemanticProposition("Cache", "réduit", "latence_et_charge_source"))
    assert SemanticEquivalenceNormalizerV4(ontology).compare(target, observed) == (
        SemanticEquivalenceNormalizerV4(reversed_ontology).compare(target, observed)
    )
