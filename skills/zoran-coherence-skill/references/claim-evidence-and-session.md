# Claims, evidence, abstention and opaque session

## Exact claim coverage

Segment the exact proposed output with `segment_output()`. Every segment appears exactly once, in order, with a zero-based index. A factual segment has one non-empty, globally unique `claim_id`; a non-factual segment cannot carry a claim identity or evidence. Omission, duplication, relabeling a factual statement as non-factual, or evaluating a different output is a veto or `RETRY`.

An asserted factual claim needs at least one verified supporting span. Each span binds `source_id`, full source text SHA-256, an exact non-empty quote and quote SHA-256, relation, evidence grade, provenance root, observation time, optional expiry, reliability state and host authority receipt. The exact quote must occur in the bound source text and semantically entail the claim while preserving negation and numbers. Evidence from the future, expired evidence, an invented/weak source and missing support cannot assert a fact; they raise a visible source gyrophare.

For a public or lexical fact, a caller-declared `wikimedia_checked_claim_ids` value has no trust effect. At least one support must include an evaluator-signed Wikipedia, Wiktionary, Wikiquote or Wikidata lookup envelope bound to the exact claim, source, quote, project, API endpoint, page, revision and retrieval time. This is a first plausibility/source pass, not the sole authority for high-stakes, current, private or scientific claims.

An unsupported, stale or contested factual unit may pass only as `ABSTAIN` when the unit visibly says that it is unverified, uncertain, contested, unsupported, theoretical or `RETRY`. Silent deletion is not abstention. Certainty language or a positive assertion after `mais`, `but` or an equivalent connector vetoes the abstention. If contradiction evidence exists, the wording must disclose the contradiction or contest.

`ZoranRuntime.evaluate()` binds the claim-evidence request to the exact semantic receipt and exact evaluated text. A syntactically valid receipt for another semantic evaluation or output is a veto.

## Host-owned display authority

The host session authority signs an Ed25519 envelope outside the candidate package. Its payload binds the mission SHA-256, prompt SHA-256, exact output SHA-256, issuance and expiry, terminal PASS and these exact ordered stages:

`activation → prompt_security → pre_chat → zmos_recall → retrieval → claim_evidence → semantic_non_conflation → frame_search → proxy → sources → phenomenal_resources → phenomenal_coherence → host_truth → laws → action → robot_handoff → k3_post → terminal`

Every event binds its index, stage identity, PASS status, exact receipt and previous event hash. The maximum certificate lifetime is 15 minutes. `host_session_guard.py` uses the pinned session public key. Missing certificates are `RETRY`; identity substitution, invalid time, reordered/omitted events, chain mutation, non-PASS stages, signature failure and caller-supplied session registries are vetoes. Display is authorized only in state `DISPLAY_AUTHORIZED`.

The signed session proves execution under the configured host key. It does not prove organizational third-party independence, open-world factual accuracy, scientific validity or uncompromised key custody.
