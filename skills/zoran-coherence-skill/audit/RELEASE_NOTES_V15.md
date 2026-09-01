# Zoran Coherence Skill 15.0.0 — phenomenal candidate

This release starts from the byte-verified v14.0.0 audited archive (`67a105298b8fde2634f3f8919042d72c001cac507140a942664d0dc500b57468`) and makes phenomenal coherence a mandatory runtime invariant. It is intentionally labelled `experimental-candidate`, not externally certified or robot-promoted.

## New central invariant

- exactly six frames: local, lower, peer, upper, temporal, and planetary;
- at least three validated, strictly ordered trajectory states under one measurement contract;
- strict local improvement and non-compensatory preservation of lower and peer frames;
- measured causal gain, intervention, counterfactual, falsifier, and evidence on upper, temporal, and planetary frames;
- critical-invariant veto and a conjunctive nine-condition bounded-regression exception;
- deterministic request-bound and evidence-integrity-bound receipt;
- terminal receipt binding generated inside `ZoranRuntime`, preventing caller substitution of the phenomenal receipt.

## Robot promotion boundary

The skill decides and emits the phenomenal receipt. An external robot owns promotion. The robot must authenticate its authorization and the remaining host trust roots, replay or bind the exact mission/candidate, verify the phenomenal receipt, and append the promotion outcome to ZMOS. This external execution is `RETRY` until replayed in the actual host.

## Deliberately trace_pending

- truth of caller-supplied real-world measurements and causal counterfactuals;
- real planetary effects or universal scientific validity;
- external robot identity, signature, and host trust-root authenticity;
- clean dependency installation in this build environment;
- signed provenance, Sigstore/SLSA, external vulnerability scan, multi-OS behavior, and independent third-party certification.
