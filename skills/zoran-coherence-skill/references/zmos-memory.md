# ZMOS memory contract

ZMOS is the sole Zoran project/chat trace-memory layer. It is not ground truth: factual assertions still require the applicable evidence gates.

GitHub remains the canonical repository authority. ZMOS is the coordination buffer between sessions; it never replaces the verified remote HEAD, a Git object, a signed source receipt, or the final GitHub SHA.

## Writer-unique coordination

One sealed `program_id` has exactly one `writer_id`. Helper sessions may enqueue candidate patches or commits, but they may not integrate, push, merge, promote, or declare the final GitHub state.

Every candidate envelope must bind:

- mission, state and lock identity;
- `canonical_github_head` and identical `base_head`;
- candidate Git SHA;
- distinct SHA-256 test/review receipts from the producing session;
- immutable queue position and ZMOS event-chain receipt.

Only the Writer may consume the integration queue, integrate a candidate, push a grouped change, and append the final GitHub SHA. The final synchronization event must bind the exact candidate SHA to the observed canonical GitHub SHA. A helper attempting a Writer-only action, a stale `BASE_HEAD`, missing tests, a duplicate receipt, or a final SHA that differs from the candidate is `VETO`.

Use `zmos_writer_coordination.py` before appending or consuming any coordination envelope. This gate grants workflow authority only; it does not prove the candidate true, tested, mergeable, or promoted. No percentage of GitHub-call reduction may be asserted without an observed before/after trace.

## Consent and capacity

Before first activation, ask:

> **Zoran🦋 peut garder une mémoire ZMOS locale pour mieux suivre tes chats et projets. Veux-tu l'activer sur cet appareil ? [Oui] [Non]**

If yes, ask how much space may be reserved. Do not claim installation until a persistent write/read probe succeeds. If storage is unavailable, say so and continue without local memory.

## Records

Every record binds its identity, chat/turn, content digest, frames, proxies, sources, S/ΔS, decision, provenance, timestamp, and modality in `record_sha256`. Allowed modalities are `PROUVE`, `SUPPORTE`, `DEDUIT`, `INCERTAIN`, `CONTRADICTOIRE`, `INCONNU`, and `RETRY`.

Scores must be finite and bounded: S in `[0,100]`, ΔS in `[-100,100]`. Timestamps are timezone-aware. Duplicate or blank frame/proxy/source identifiers are rejected.

Record states are `CANDIDATE`, `BLOCKED`, and `VALIDATED`. `VALIDATED` requires a PASS gate receipt. `BLOCKED` and `VALIDATED` are terminal; create a corrected record rather than rewriting history.

The local hash chain and record digests detect accidental or uncoordinated tampering. They are not a keyed signature or externally anchored transparency log; an attacker with database write access who can recompute every digest remains outside the guarantee.

## Recall

Relevance admits candidates. Measured coherence then orders them. Trace-pending S remains explicit. A relevant `CONTRADICTOIRE` object must be surfaced; if the context budget cannot fit one, recall returns `RETRY` instead of silently dropping it.

Object IDs are unique. Receipts bind selected content digests, provenance digests, labels, limits, and ordering. There is no fixed object-count ceiling; the user-approved storage and active context budget are the bounds.

The host enforces a logical/physical storage ceiling only when it constructs `ZmosMemory(..., max_storage_bytes=N)`. If no quota is supplied, quota enforcement is `RETRY` and the UI must not claim that a requested reserve is active. Database, WAL, and shared-memory files are restricted to mode `0600` on supported POSIX hosts.

`gate_receipt_sha256` is a reference to an upstream receipt. ZMOS validates its form and binds it into the event chain, but does not reconstruct arbitrary upstream component payloads. Authenticity of that receipt therefore depends on the host receipt registry and remains `RETRY` without it.

Legacy schema migrations preserve content but do not promote epistemic modality. After migration, re-run integrity verification before recall.
