# Three-state measurement law

The decision alphabet is closed: `PASS`, `RETRY`, `VETO`. No fourth state, synonym, compatibility alias, display placeholder, or hidden enum value is admissible.

## PASS

`PASS` means every required proposition has an observed trace, the trace is bound to the exact claim and mission, authenticity and integrity checks pass, and every applicable non-compensatory gate passes. A score cannot create `PASS` when a required receipt is absent.

## RETRY

`RETRY` is a temporary executable state. It is admissible only when the missing trace is expected to be recoverable and the receipt names:

- the exact missing trace;
- the responsible actor or connector;
- the next distinct resource or action;
- the remaining attempt budget;
- the condition that will yield `PASS` or `VETO`.

For phenomenal resources, the budget is exactly two distinct search rounds. Only the incomplete first round may yield `RETRY`.

## VETO

`VETO` is non-compensatory. It applies to contradiction, tampering, fabricated evidence, unsigned claimed measurement, forbidden execution, failed invariant, or exhausted recovery budget. If the second phenomenal-resource search remains incomplete, emit all of:

- `VETO`;
- `GYROPHARE_TRACE_ABSENTE_APRES_DEUX_RECHERCHES`;
- `HALLUCINATION_BLOQUANTE_OU_PHENOMENE_INEXISTANT`;
- `RETOUR_ENVOYEUR`.

Do not emit a numeric measurement or zero placeholder for an absent trace. Either the signed measurement exists and is computed, the first recovery round is running under `RETRY`, or the bounded search has failed and the result is `VETO`.
