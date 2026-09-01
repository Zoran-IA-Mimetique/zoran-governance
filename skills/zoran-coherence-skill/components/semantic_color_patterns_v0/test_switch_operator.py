from components.semantic_color_patterns_v0.switch_operator import (
    SemanticState,
    SemanticSwitch,
    apply_switch,
    switch_interaction_signature,
)


def state():
    return SemanticState(
        frame_id="P1",
        propositions={"COME_TOMORROW": 1.0, "COME_MORNING": 0.8, "BRING_KEYS": 0.9},
        intention_vector={"INFORMER": 0.7},
    )


def test_negation_is_scoped_not_global():
    result = apply_switch(state(), SemanticSwitch("NEGATION", ("COME_MORNING",)))
    assert result.requires_rebuild is False
    assert result.propositions["COME_TOMORROW"] == 1.0
    assert result.propositions["COME_MORNING"] == -0.8
    assert result.propositions["BRING_KEYS"] == 0.9


def test_contrast_requires_frame_rebuild():
    result = apply_switch(state(), SemanticSwitch("CONTRAST", ("COME_MORNING", "BRING_KEYS")))
    assert result.requires_rebuild is True
    assert result.reason == "relation_topology_changed"


def test_unresolved_scope_fails_closed():
    result = apply_switch(state(), SemanticSwitch("NEGATION", ("UNKNOWN_PROP",)))
    assert result.requires_rebuild is True
    assert result.changed_ids == ()
    assert result.reason == "scope_unresolved"


def test_interaction_signature_uses_scope_not_adjacency():
    switch = SemanticSwitch("NEGATION", ("COME_MORNING",))
    signature = switch_interaction_signature(switch, ["COME_TOMORROW", "COME_MORNING"])
    assert signature == ("NEGATION", ("COME_MORNING",), ("COME_MORNING",))
