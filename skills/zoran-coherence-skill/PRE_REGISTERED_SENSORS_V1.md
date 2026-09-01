# PRE-REGISTERED SENSOR LAYER V1

Frozen before implementation.

## Scope
Standalone Multicriteria Tolerance Skill only. No Zoran project dependency.

## Goal
Convert a bounded validation bundle (request, response, structured evidence, domain constraints and runtime telemetry) into measured observations for the 17-family tolerance engine.

## Non-negotiable rules
1. Sensor layer MUST NOT invent evidence.
2. Missing required external truth/source/telemetry => RETRY through an trace_pending Observation.
3. Critical mismatches in zero-tolerance families must yield non-zero delta and therefore VETO under the conservative policy.
4. No LLM, network, embedding model, probabilistic classifier or hidden epsilon.
5. Same bundle => byte-identical sensor receipt and engine receipt.
6. Sensors are bounded: unsupported linguistic form => RETRY, never guessed PASS.
7. All 17 tolerance families must be declared applicable or explicitly excluded.

## Sensors to implement
### Text / evidence sensors
- intentional: bounded intent class from request versus declared response role.
- ambiguity: multiple incompatible intent markers.
- source: cited source ids must exist in evidence registry.
- factual: structured claim key/value asserted by response must match governed evidence.
- numeric: quantities asserted for governed keys must respect declared numeric tolerances.
- temporal: governed before/after/date relation must be preserved.
- causal: governed cause->effect direction must be preserved.
- epistemic: output certainty must not exceed evidence certainty.
- semantic: governed polarity/negation must be preserved.
- coherence: contradictory governed assertions in one response are charged/blocked.

### Context / telemetry sensors
- metier: domain must be declared and match allowed domain set.
- measurement: required measurement uncertainty must be present and <= configured bound.
- safety: hard safety constraints must not be violated.
- regulatory: hard regulatory constraints must not be violated.
- resource: observed resource usage must be <= configured budget.
- repeatability: deterministic fingerprints supplied for repeated runs must agree.
- integration: required output fields/schema markers must be present.

## Acceptance campaign
A. Unit tests: at least 30 tests, including one clean and one corrupted case per family where semantically applicable.
B. 17-family clean end-to-end bundle => PASS.
C. Single-family mutation campaign: 17/17 mutations must be blocked (`VETO` or bounded `RETRY` as preregistered by failure class), while clean remains `PASS`.
D. All 2^17 binary mutation combinations on structured sensor inputs: only all-clean may PASS; zero false PASS.
E. Missing-evidence campaign: remove each required evidence/telemetry input in turn; each applicable missing item must produce RETRY, not PASS.
F. Replay: 10,000 identical evaluations => identical sensor receipt + engine receipt.
G. Unsupported text form explicitly marked applicable => RETRY.
H. Existing v1 engine regressions: all existing tests and campaigns remain unchanged/green.

## Status rule
Promotion label may be at most PASS_BOUNDED_SENSOR_V1. It MUST NOT claim open-world factuality, arbitrary-language semantic understanding, or SOTA anti-hallucination until public blind datasets are run.
