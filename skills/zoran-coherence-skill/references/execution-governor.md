# Persistent execution governor

`PASS`, `RETRY`, and `VETO` are evaluation decisions. They never authorize a
scheduler by themselves. Before every repair, tool call, external wait, or
promotion attempt, the host must separately obtain one execution state from
`execution_governor.py`:

- `CONTINUE`: exactly one new material action is authorized;
- `WAIT_EXTERNAL`: the current turn is terminal and must not poll or relaunch;
- `STOP`: the program budget or an invariant ended execution;
- `DONE`: the evaluation passed and no recovery action remains.

## Stable program identity

Choose one `program_id` when the mission is sealed and reuse it across chats,
processes, checkpoints, and host restarts. A `session_id` is evidence only. It
must never select a journal, reset a counter, or create a fresh recovery budget.

The host provides a persistent `state_root` to `ExecutionGovernor`. The governor
derives the journal filename from `SHA-256(program_id)`, writes it with mode
`0600`, serializes writers with a file lock, and verifies its sequence and hash
chain before every decision. Missing, corrupt, replaced, oversized, or symlinked
state fails closed.

## Global bounds

The default program budget is three authorized recovery cycles, two consecutive
cycles without a material delta, 1,200 elapsed seconds, and 60 tool calls. These
are non-compensatory caps. A new chat does not renew them. A state/action pair
that already received `CONTINUE` cannot receive it again.

The host reports tool calls as deltas. The governor accumulates them in the
journal. Wall time starts at the first journal event and is read from the host
clock; clock regression stops execution.

## Capability preflight and terminal wait

Declare the owner of every next action as `INTERNAL`, `USER`, `CONNECTOR`, or
`EXTERNAL`. If a non-internal capability is unavailable, return
`WAIT_EXTERNAL`, end the turn, surface the missing capability once, and do not
poll. Replaying the same request returns the same receipt without appending an
event or consuming a fresh cycle. Resumption requires new external evidence or a
distinct available internal build action.

## Build is not promotion

During `BUILD`, an absent promotion signature does not prevent source edits,
tests, candidate commits, deterministic ZIP construction, or checkpointing.
During `PROMOTION`, every declared external proof is mandatory; absence yields
terminal `WAIT_EXTERNAL`, never an internal retry loop and never a fabricated
certificate.

## Runtime use

Configure `ZoranRuntime(..., execution_state_root=HOST_PERSISTENT_PATH)`. Call
`govern_execution()` before a single action, or provide an
`execution_request_factory` to `recover_until_terminal()`. The runtime rejects
recovery without both a persistent governor and a request factory. The older
`BoundedRecoveryLoop` is only a local inner guard and cannot establish a global
bound by itself.

This mechanism is enforceable only for hosts that route every execution step
through the installed runtime. The skill must not claim platform-wide or
non-bypassable enforcement without an authenticated host integration receipt.
