# Progress Guard — specification v2.0.0

## Objective
Prevent unproductive iterative work while preserving productive convergence.

## Invariants
1. Same material state + same action cannot be executed twice.
2. Regression toward the declared objective is forbidden.
3. Zero gain before objective completion is forbidden.
4. Positive but insignificant gain is forbidden.
5. Significance is target-aware and cost-aware, not a fixed universal number.
6. A repeated algorithm/action remains allowed after the material state changes if its next gain remains significant.
7. Missing progress evidence cannot become PASS.
8. Progress can never compensate a tolerance failure; tolerance quality can never compensate bad progression.

## Dynamic threshold
`required_gain = max(min_absolute_gain, min_fraction_of_remaining * remaining_gap, min_gain_per_cost * cost)`

Optional convergence constraint:
`remaining_after / gain <= max_projected_steps`

## State fingerprint requirement
`state_before_fingerprint` MUST include all materially relevant evidence/context. Cosmetic context changes do not make a new state. The loop key deliberately ignores the free context label and uses `state + action` only.

## Terminal decisions
- loop / regression / stagnation / low gain / too-slow convergence / already-completed objective: `VETO`
- missing measurement: `RETRY`
- productive convergence or objective completion: `PASS`
