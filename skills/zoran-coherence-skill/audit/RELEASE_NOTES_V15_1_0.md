# v15.1.0 — dual deterministic robot candidate

This release replaces the caller-supplied robot trust registry with two separated deterministic host robots and pinned Ed25519 public anchors.

- Robot A evaluates the exact ZIP over six non-compensatory software frames and signs its receipt.
- Robot B verifies Robot A, safely extracts and recompiles the ZIP, reruns every test, rebuilds twice byte-identically, checks trust anchors and private-key absence, then signs the release certificate.
- The candidate rejects caller-supplied robot registries, mutated signatures, candidate substitution, receipt substitution and handoff substitution.
- Promotion still requires semantic non-conflation PASS, phenomenal-coherence PASS and robot state exactly VALIDATED.

The signed certificate covers the deterministic software artifact only. Third-party organizational independence, scientific universality and real planetary benefit are explicitly excluded.
