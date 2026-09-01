# Evaluation and release contract

## Evidence hierarchy

Prefer clean-install replay, adversarial regression tests, deterministic repeated runs, mutation/fuzz/property tests, static/dependency review, self-authored closed-world campaigns, then prose claims. High test counts do not compensate for missing scenario families or a false PASS. Self-issued certification files are evidence records, not independent certification.

## Mandatory scenario families

Test clean extraction/install, manifest integrity, normal decisions, missing evidence, contradictory frames, non-finite values, prompt injection, path/import poisoning, memory tamper/staleness, writer concurrency, repeated state/action, low gain, terminal progress, receipt relabeling, deterministic replay, source-only portability, and the complete phenomenal state space. Test semantic non-conflation, complete output-unit coverage, exact quote/source binding, contradiction/freshness, visible abstention, forged semantic/claim/phenomenal/robot receipts, opaque-session identity/order/time/signature mutations, robot channel discovery, submission, pending/rejected verdicts, trust-root absence, and promotion refusal without `VALIDATED`.

The blind-eval harness must pin a preregistration digest, public dataset digest and hidden-oracle commitment before predictions. Public cases have no label fields. Oracle and prediction case identities must match the public split exactly and in order; post-hoc deletion, duplication, leakage or replacement is a veto. Every prediction binds output and trace SHA-256 values. A self-authored hidden split measures harness integrity and registered behavior only, never public open-world performance.

## Benchmark meaning

“Percent versus SOTA” is a capability-coverage score against a frozen public-practice reference, not a market percentile, proof of scientific validity, or measured superiority over every competitor. Freeze criteria and weights before scoring. Apply non-compensatory caps for unsafe installation, critical false PASS, forgeable integrity claims, text-only tests, and missing clean-environment replay.

Separate local software conformance, robustness on the registered adversarial suite, host integration evidence, open-world factual performance, and independent external validation. Never merge a missing-trace category into a flattering scalar; apply the bounded `RETRY` then `VETO` law instead.

## Release requirements

- valid `SKILL.md` frontmatter and discovery description;
- deterministic ZIP with one normalized root directory;
- no caches, compiled bytecode, coverage database, secrets, or absolute paths;
- dependency declaration and CycloneDX SBOM;
- SHA-256 manifest and build provenance with honest limitations;
- signed in-toto/SLSA v1-compatible predicate binding ZIP, manifest, SBOM, source commit/tree and builder identity;
- two byte-identical consecutive builds;
- full tests plus adversarial suite from a clean extracted copy;
- original release retained as rollback;
- new semantic version and filename;
- git commit for every skill modification.

The v17 ZIP is a dual-robot candidate until the separate host evaluator and certifier emit the signed certificate for its exact SHA-256 and source commit/tree. A certificate `PASS` covers deterministic software-artifact conformance, the frozen internal rubric and the signed provenance statement. Network-isolated fresh dependency installation, organizational third-party independence, public open-world performance, Sigstore/Rekor inclusion, scientific universality and real-world planetary benefit are separate missions; they cannot be folded into that certificate or represented by placeholders.
