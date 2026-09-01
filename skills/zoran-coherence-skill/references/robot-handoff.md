# Robot handoff contract

External authority and external handoff are separate concepts. The LLM's inability to self-certify never means that it should omit submission to an external certifier.

## State machine

- `NOT_REQUIRED_PROVEN`: non-applicability is explicit and evidence-bound; local evaluation may continue, but this state cannot promote a candidate.
- `DISCOVERY_REQUIRED`: robot validation applies and channel discovery has not run (`RETRY`).
- `CHANNEL_UNRESOLVED`: discovery ran but no callable authorized channel was found (`RETRY`).
- `HANDOFF_REQUIRED`: a channel exists but the artifact was not submitted (`RETRY`).
- `VALIDATION_PENDING`: a bound submission exists but no terminal verdict exists (`RETRY`).
- `REJECTED`: the robot returned failure (`VETO`).
- `VALIDATED`: the pinned deterministic certifier returned an Ed25519-signed `PASS` for the exact mission, candidate, channel and submission (`PASS`).

Candidate, artifact, mission, channel and submission identities must be bound. Any substitution is a veto. A claimed robot `PASS` without the exact signed envelope is `RETRY`. A caller-supplied trust registry is itself vetoed; the public trust anchors are pinned in `references/robot-trust-anchors.json`, while both private keys remain outside the candidate package.

## Promotion rule

`ZoranRuntime.finalize_candidate()` requires four gates: semantic non-conflation `PASS`, claim evidence `PASS`, phenomenal coherence `PASS`, and robot state exactly `VALIDATED`. `NOT_REQUIRED_PROVEN` cannot promote. The terminal controller separately requires the exact runtime-generated receipts for `semantic_non_conflation_gate`, `claim_evidence_gate`, `phenomenal_coherence_gate` and `robot_handoff_gate`.

The two host robots are separate processes. The evaluator signs the six-frame evaluation and all registered campaigns. The certifier verifies that signature, safely re-extracts the exact ZIP, recompiles it, reruns every test without requiring pytest, rebuilds it twice, rebuilds it from a clean Git worktree, binds the source commit/tree, manifest and SBOM into a SLSA v1-compatible provenance statement, signs the release certificate and appends the promotion event. `scripts/verify_robot_certificate.py` rechecks it offline.

This establishes deterministic software-artifact certification by the configured host robots. It does not establish organizational third-party independence, scientific universality or a measured real planetary benefit; those claims remain outside the certificate scope.
