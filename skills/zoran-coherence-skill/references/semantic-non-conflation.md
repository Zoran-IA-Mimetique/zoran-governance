# Semantic non-conflation contract

## Law DER-NC-001

Two distinct concepts, actors, objects, actions, modalities, conditions or authorities must remain operationally distinct through interpretation, decision and execution. No obligation, prohibition, permission or status transfers from one to another without an explicit evidence-bound equivalence proof.

`DER-NC-001` is an engineering derivative introduced after a confirmed conflation. It is derived from the local active registry's phenomenal-coherence invariant (`LAW-000`), non-recurrence rule (`DER-004`), authority separation (`DER-008`) and plan/output equivalence (`DER-009`). Its exact wording has not been verified as a pre-existing canonical corpus law, so the runtime labels it `ENGINEERING_DERIVATIVE_NOT_CORPUS_VERIFIED`.

## Mandatory decomposition

Before deciding, enumerate every distinct:

- actor: who interprets, submits, validates, certifies, promotes or blocks;
- object: which mission, candidate, artifact, receipt or state is affected;
- action: the exact operational verb, not a loose synonym;
- modality: `MUST`, `MUST_NOT`, permission, applicability or condition;
- authority: who may issue which status;
- temporal state: missing, pending, blocked, executed, rejected or validated.

The complete source text carries a SHA-256 digest. Every concept has a verbatim source quote, definition, actor, object, modality, required actions, forbidden actions and evidence digest. Every concept pair has a discriminant and a falsifier. Every referenced action has one disposition and grounding concepts. A concept whose quote is absent from the bound source text is `RETRY`.

## Exact-action invariant

A prohibition can block only the exact action it names. It cannot suppress a different required action through analogy, proximity or an inferred implication.

Example:

- `self_certification_prohibition` forbids `self_certify` by the candidate;
- `external_validation_requirement` requires `submit_to_external_robot` by the host.

The first rule does not block the second action. Mapping the self-certification prohibition onto robot submission produces `VETO: REQUIRED_ACTION_BLOCKED_BY_NONMATCHING_PROHIBITION:submit_to_external_robot`.

## Fail-closed decisions

- `PASS`: all pairs are distinguished, all action identities and evidence are valid, every requirement is executed and every prohibition is enforced.
- `RETRY`: a correctly grounded required action or prohibition enforcement is pending.
- `VETO`: semantic identities are duplicated, a rule conflicts, a forbidden action ran, a required action was erased, or a nonmatching prohibition was substituted.
- `RETRY`: a definition, distinction, falsifier, disposition, grounding or evidence digest is absent or invalid.

The gate prevents a structured conflation from passing. It does not prove universal natural-language understanding, synonym completeness or corpus-wide semantic equivalence. The host must supply the explicit decomposition and must preserve the exact runtime-generated receipt.
