import json

from components.semantic_color_patterns_v0.batch_learning_runtime import (
    BatchLearningRuntime,
    FrozenCorpus,
    oracle_key,
    route_signature_for_text,
    run_two_pass_experiment,
)
from components.semantic_color_patterns_v0.gma4_teacher_adapter import GMA4TeacherAdapter
from components.semantic_color_patterns_v0.wiktionary_cache import WiktionaryDiskCache
from components.semantic_color_patterns_v0.wiktionary_parser import WiktionaryEntry, WiktionarySense


def _teacher(prompt: str) -> str:
    request = json.loads(prompt)["request"]
    return json.dumps({
        "schema": "zoran.gma4-teacher-proposal.v1",
        "surface": request["surface"],
        "language": "fr",
        "lemma_candidates": ["se garder"],
        "pos_candidates": ["verb"],
        "definition": "S'abstenir de faire quelque chose par prudence.",
        "semantic_frame_candidates": ["AVOIDANCE"],
        "discourse_intention_candidates": ["COMMAND"],
        "components": ["garde", "toi"],
        "ambiguities": ["garder peut aussi signifier conserver"],
        "examples": [request["context"]],
        "needs_external_evidence": False,
    }, ensure_ascii=False)


def _wiki(surface: str) -> WiktionaryEntry:
    return WiktionaryEntry(
        surface, "fr", 987654,
        (WiktionarySense("VERB", "Forme de verbe", "S'abstenir consciemment d'une action par prudence."),),
        "https://fr.wiktionary.org/wiki/garde-toi",
    )


def _corpus(name: str, verb: str) -> FrozenCorpus:
    paragraphs = tuple(f"Garde-toi de {verb} ici." for _ in range(100))
    route = route_signature_for_text("garde-toi", paragraphs[0])
    return FrozenCorpus(
        name, f"https://example.test/{name}.txt", ("1" if verb == "ouvrir" else "2") * 64,
        paragraphs, {oracle_key("garde-toi", route): "AVOIDANCE"},
    )


def test_lexical_route_is_learned_then_reused_without_provider_calls():
    calls = {"teacher": 0, "wiki": 0}

    def teacher(prompt):
        calls["teacher"] += 1
        return _teacher(prompt)

    def wiki(surface):
        calls["wiki"] += 1
        return _wiki(surface)

    runtime = BatchLearningRuntime(
        adapter=GMA4TeacherAdapter(teacher),
        wiktionary_fetcher=wiki,
        known_surfaces={"de", "ouvrir", "courir", "ici"},
        max_workers=2,
    )
    result = run_two_pass_experiment(runtime, _corpus("p1", "ouvrir"), _corpus("p2", "courir"))
    assert result["verdict"] == "PASS"
    assert result["passage_1"]["metrics"]["experimentally_acquired"] == 1
    assert result["passage_2"]["metrics"]["gma4_calls"] == 0
    assert result["passage_2"]["metrics"]["wiktionary_calls"] == 0
    assert calls == {"teacher": 1, "wiki": 1}


def test_wiktionary_success_cache_prevents_duplicate_network_fetch(tmp_path):
    calls = []

    def fetch(surface):
        calls.append(surface)
        return _wiki(surface)

    cache = WiktionaryDiskCache(tmp_path / "cache", fetch)
    first = cache("garde-toi")
    second = cache("GARDE-TOI")
    assert first == second
    assert calls == ["garde-toi"]
    assert cache.cache_hits == 1
    assert cache.cache_misses == 1


def test_teacher_contract_retries_once_then_records_real_calls():
    attempts = []

    def teacher(prompt):
        attempts.append(prompt)
        payload = json.loads(_teacher(prompt))
        if len(attempts) == 1:
            payload["surface"] = "mauvaise-surface"
        return json.dumps(payload, ensure_ascii=False)

    runtime = BatchLearningRuntime(
        adapter=GMA4TeacherAdapter(teacher, max_contract_attempts=2),
        wiktionary_fetcher=_wiki,
        known_surfaces={"de", "ouvrir", "ici"},
    )
    result = runtime.process(_corpus("retry", "ouvrir"))
    assert result.metrics.gma4_requests == 1
    assert result.metrics.gma4_calls == 2
    assert result.metrics.gma4_contract_retries == 1
    assert result.metrics.gma4_failures == 0
