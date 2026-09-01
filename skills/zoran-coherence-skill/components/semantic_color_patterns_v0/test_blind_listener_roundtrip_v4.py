import json
from pathlib import Path

from components.semantic_color_patterns_v0.blind_listener_roundtrip_v4 import (
    evaluate_blind_listener_roundtrip_v4,
)


ROOT = Path(__file__).with_name("fixtures") / "technical_microcorpus_v0"
CORPUS = ROOT / "corpus.jsonl"
LISTENER = ROOT / "conversational_speech_v4_blind_listener.jsonl"
MANIFEST = ROOT / "conversational_speech_v4_blind_listener_manifest.json"
ATTEMPT2_LISTENER = ROOT / "conversational_speech_v4_attempt2_blind_listener.jsonl"
ATTEMPT2_LISTENER_MANIFEST = ROOT / "conversational_speech_v4_attempt2_blind_listener_manifest.json"
ATTEMPT2_REVIEW = ROOT / "conversational_speech_v4_attempt2_blind_review.json"
ATTEMPT3_LISTENER = ROOT / "conversational_speech_v4_attempt3_blind_listener.jsonl"
ATTEMPT3_LISTENER_MANIFEST = ROOT / "conversational_speech_v4_attempt3_blind_listener_manifest.json"
ATTEMPT3_REVIEW = ROOT / "conversational_speech_v4_attempt3_blind_review.json"


def test_all_thirty_blind_cases_are_present_once_and_in_frozen_order():
    corpus_ids = [json.loads(line)["id"] for line in CORPUS.read_text(encoding="utf-8").splitlines()]
    listener_ids = [json.loads(line)["id"] for line in LISTENER.read_text(encoding="utf-8").splitlines()]
    assert listener_ids == corpus_ids
    assert len(listener_ids) == len(set(listener_ids)) == 30


def test_blind_listener_manifest_records_no_target_or_score_access():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["source_usage"]["canonical_targets"] is False
    assert manifest["source_usage"]["target_sha"] is False
    assert manifest["source_usage"]["scores"] is False
    assert manifest["status"] == "experimental_structural_separation"
    assert manifest["independent_certification"] is False


def test_first_blind_round_exceeds_the_preregistered_eight_of_ten_alignment():
    receipt = evaluate_blind_listener_roundtrip_v4(corpus_path=CORPUS, listener_path=LISTENER)
    assert receipt.case_count == 30
    assert receipt.score_10 >= 8.0
    assert receipt.pass_count == 7
    assert receipt.retry_count == 23
    assert receipt.veto_count == 0
    assert receipt.promotion == "FORBIDDEN"


def test_first_blind_round_is_deterministic():
    first = evaluate_blind_listener_roundtrip_v4(corpus_path=CORPUS, listener_path=LISTENER)
    second = evaluate_blind_listener_roundtrip_v4(corpus_path=CORPUS, listener_path=LISTENER)
    assert first == second


def test_second_blind_round_improves_alignment_without_relaxing_pass():
    first = evaluate_blind_listener_roundtrip_v4(corpus_path=CORPUS, listener_path=LISTENER)
    second = evaluate_blind_listener_roundtrip_v4(corpus_path=CORPUS, listener_path=ATTEMPT2_LISTENER)
    assert second.score_10 > first.score_10
    assert second.score_10 == 9.668870861130923
    assert (second.pass_count, second.retry_count, second.veto_count) == (21, 9, 0)


def test_second_round_listener_stayed_blind_and_french_review_stayed_separate():
    listener_manifest = json.loads(ATTEMPT2_LISTENER_MANIFEST.read_text(encoding="utf-8"))
    manifest_text = json.dumps(listener_manifest, ensure_ascii=False).casefold()
    assert "corpus.jsonl" in manifest_text
    assert "interdit" in manifest_text or "false" in manifest_text

    review = json.loads(ATTEMPT2_REVIEW.read_text(encoding="utf-8"))
    assert review["semantic_fidelity_evaluated"] is False
    assert review["external_certification"] is False
    assert review["summary"]["accepted_count"] == 23
    assert review["summary"]["total_count"] == 30


def test_second_round_releases_only_the_intersection_of_both_gates():
    semantics = evaluate_blind_listener_roundtrip_v4(corpus_path=CORPUS, listener_path=ATTEMPT2_LISTENER)
    semantic_ids = {case.id for case in semantics.cases if case.decision == "PASS"}
    review = json.loads(ATTEMPT2_REVIEW.read_text(encoding="utf-8"))
    natural_ids = {item["id"] for item in review["reviews"] if item["accepted"]}
    assert len(semantic_ids & natural_ids) == 16


def test_third_blind_round_keeps_both_evaluations_separate():
    semantics = evaluate_blind_listener_roundtrip_v4(corpus_path=CORPUS, listener_path=ATTEMPT3_LISTENER)
    assert semantics.score_10 == 9.66155606155606
    assert (semantics.pass_count, semantics.retry_count, semantics.veto_count) == (17, 13, 0)

    manifest = json.loads(ATTEMPT3_LISTENER_MANIFEST.read_text(encoding="utf-8"))
    assert manifest["scores_computed"] is False
    assert manifest["comparisons_performed"] is False
    assert "canonical_targets" in manifest["sources_forbidden"]

    review = json.loads(ATTEMPT3_REVIEW.read_text(encoding="utf-8"))
    assert review["semantic_fidelity_evaluated"] is False
    assert review["summary"]["accepted_count"] == 28
    assert review["summary"]["round4_allowed"] is False


def test_third_round_releases_only_the_intersection_of_both_gates():
    semantics = evaluate_blind_listener_roundtrip_v4(corpus_path=CORPUS, listener_path=ATTEMPT3_LISTENER)
    semantic_ids = {case.id for case in semantics.cases if case.decision == "PASS"}
    review = json.loads(ATTEMPT3_REVIEW.read_text(encoding="utf-8"))
    natural_ids = {item["id"] for item in review["reviews"] if item["accepted"]}
    assert len(semantic_ids & natural_ids) == 15
