# Phenomenal coherence contract

## Role

Phenomenal coherence is the central admissibility invariant. A candidate is not validated merely because it is locally plausible, scores well in aggregate, or passes the historical 17-family gate. It must improve the sealed local object, preserve every affected lower and peer frame, and demonstrate a positive causal benefit on every affected superior frame through the terminal planetary frame.

The trajectory implementation is `PhenomenalCoherenceEngine` in `phenomenal_coherence.py`. Before it can run, `PhenomenalResourceGate` requires all six frame receipts and the calibrated `beta`, `dphi`, `T`, `sigma` proxies with finite values, units, source receipts and observation times. A complete round passes only with a pinned evaluator signature over the exact resource set. Caller-authored hashes are never measurement authenticity.

If the first resource search is incomplete, the only admissible result is `RETRY` with a gyrophare, the exact missing traces, and one search over new resources. If the second search remains incomplete, the result is `VETO`, `GYROPHARE_TRACE_ABSENTE_APRES_DEUX_RECHERCHES`, `HALLUCINATION_BLOQUANTE_OU_PHENOMENE_INEXISTANT`, and `RETOUR_ENVOYEUR`. A third round, identical second resource set, partial score or compensatory average is forbidden.

## Mandatory six-frame trajectory

The canonical frames are `local`, `lower`, `peer`, `upper`, `temporal`, and `planetary`. `planetary` is deliberately named rather than `global`: a software-wide result must not be relabelled as a demonstrated real-world planetary effect.

Every evaluation requires:

1. distinct baseline and candidate identities bound to the same mission and measurement contract;
2. exactly one transition for all six frames;
3. at least three validated, strictly time-ordered states under the same measurement contract;
4. matching before/after values between the trajectory and each transition;
5. non-empty evidence whose SHA-256 matches its declared digest;
6. strict local improvement;
7. preservation of lower and peer frames;
8. positive measured change plus intervention, counterfactual, falsifier, and evidence for upper, temporal, and planetary benefit;
9. preservation of every critical invariant.

Missing coverage or unavailable evidence is `RETRY` only while its exact recovery action remains inside the authorized search budget; after exhaustion it is the trace-absence `VETO`. A measured regression, duplicate identity, trajectory mismatch, non-positive claimed causal gain, or critical-invariant loss is a non-compensatory `VETO`.

## Exceptional bounded regression

A regression cannot be hidden by aggregate improvement. It is admissible only when one frame-bound exception proves, with integrity-bound evidence, that the regression is inevitable, strictly necessary, minimal, measured, bounded, traceable, has no less harmful alternative, destroys no uncompensable invariant, and yields a proven net coherence gain. All nine conditions are conjunctive.

## Robot promotion boundary

The skill produces a phenomenal-coherence decision and receipt. Promotion is an external robot action. A robot may promote only after it:

- replays or verifies the exact candidate and mission identities;
- receives the exact phenomenal receipt produced by the engine, not a caller-chosen substitute;
- verifies the other mandatory terminal controls;
- authenticates its promotion authorization from a host-owned trust root or signature;
- appends the outcome to ZMOS without rewriting the candidate evidence.

The runtime binds both resource and trajectory terminal controls to the receipts it just computed. The caller-supplied registry cannot replace either receipt. The v17 release robot checks the six software frames, signed resource envelope, build materials and exact artifact; the separate truth and session authorities sign the exact output controls and ordered runtime chain. Authenticity of real scientific measurements and effects remains separately measured beyond the signed observation scope.

## Claim boundary

Passing synthetic tests proves only deterministic behavior against the registered contract. It is not evidence of subjective consciousness, universal scientific law, external SOTA, or a real planetary benefit. Those claims require independent empirical measurement, falsification, and provenance outside the skill.
