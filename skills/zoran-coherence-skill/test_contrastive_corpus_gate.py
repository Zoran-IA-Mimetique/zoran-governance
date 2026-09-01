from dataclasses import replace

from contrastive_corpus_gate import (
    CATEGORIES,
    ContrastiveCase,
    ContrastiveCorpusGate,
    ContrastiveCorpusRequest,
    corpus_sha256,
)
from tolerance_skill import Decision


H = "a" * 64
K = "b" * 64


def cases():
    categories = (
        [CATEGORIES[0]] * 8 + [CATEGORIES[1]] * 5 + [CATEGORIES[2]] * 3
        + [CATEGORIES[3]] * 2 + [CATEGORIES[4]] * 2
    )
    splits = ["train"] * 12 + ["validation"] * 4 + ["holdout"] * 4
    return tuple(
        ContrastiveCase(
            f"case-{index}", category, splits[index], f"root-{index}",
            f"https://example.test/{index}", H,
            "Quelle valeur est liée au sujet ?", "La preuve locale vaut 42.",
            "La preuve locale vaut 42.", "La valeur est 42.", "La valeur est 43.",
            H, H, K, splits[index] == "train",
        )
        for index, category in enumerate(categories)
    )


def request(items):
    return ContrastiveCorpusRequest(items, corpus_sha256(items), expected_total=20)


def test_contrastive_corpus_accepts_frozen_independent_three_way_split():
    result = ContrastiveCorpusGate().evaluate(request(cases()))
    assert result.decision is Decision.PASS
    assert result.case_count == 20


def test_contrastive_corpus_blocks_holdout_learning_leak():
    items = list(cases())
    items[-1] = replace(items[-1], used_for_learning=True)
    items = tuple(items)
    result = ContrastiveCorpusGate().evaluate(request(items))
    assert result.decision is Decision.VETO
    assert result.reasons[0].startswith("HOLDOUT_OR_VALIDATION_LEAK")


def test_contrastive_corpus_blocks_provenance_overlap_between_splits():
    items = list(cases())
    items[-1] = replace(items[-1], provenance_root=items[0].provenance_root)
    items = tuple(items)
    result = ContrastiveCorpusGate().evaluate(request(items))
    assert result.decision is Decision.VETO
    assert result.reasons == ("PROVENANCE_ROOT_LEAK_ACROSS_SPLITS",)


def test_contrastive_corpus_digest_detects_post_freeze_mutation():
    items = cases()
    frozen = corpus_sha256(items)
    changed = list(items)
    changed[0] = replace(changed[0], hallucinated_answer="La valeur est 99.")
    result = ContrastiveCorpusGate().evaluate(ContrastiveCorpusRequest(tuple(changed), frozen, expected_total=20))
    assert result.decision is Decision.VETO
    assert result.reasons == ("CONTRASTIVE_CORPUS_DIGEST_MISMATCH",)
