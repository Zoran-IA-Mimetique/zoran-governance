# SOTA LoopGain replay preregistration v1

Frozen before full per-trial trajectory replay.

Comparator: loopgain-ai/loopgain-bench, commit 6640702031bdefe341907d7e2dc3cf103003b4a2.
Benchmark: public B20 trajectories (max_iter=20), all available benchmark cells.
Scope: runtime anti-loop / progress stopping only. This is not an anti-hallucination benchmark.

## Fixed mapping to ProgressGuard v2

For each B20 trajectory, use the workload target_error published by the benchmark:
- W1 codegen: 0.00
- W2 debate: 0.10
- W3 planner: 0.05
- W4 external retrieval workload (upstream benchmark label): 0.30
- W5 adversarial: 0.05

Direction: minimize error.
Horizon reference: 20 iterations.
Policy:
- min_absolute_gain = 0
- min_fraction_of_remaining = 0.05 (= 1/20)
- min_gain_per_cost = 0
- completion_tolerance = 0
- max_projected_steps = 20

Replay semantics:
1. Iteration 1 is always admitted as the initial observed state.
2. Before each subsequent iteration i, compare error[i-1] -> error[i].
3. Regression, stagnation before target, insufficient gain (<5% of remaining gap), or projected convergence >20 steps triggers stop.
4. On stop, select the best-so-far error among admitted/observed iterations; no later B20 information is used by the online rule.
5. If target is already met, stop successfully at that point.
6. Missing/non-finite error -> RETRY, counted separately (not silently PASS).

Primary metrics (same public trajectories):
- best-preservation rate: selected_error == minimum error on full B20 trajectory
- false-stop rate: selected_error > minimum error on full B20 trajectory
- mean iterations used
- iteration reduction vs B20 (20 iterations)

Comparator published LoopGain v0.4.0 metrics will be reported separately. No threshold tuning after seeing replay outcomes.
