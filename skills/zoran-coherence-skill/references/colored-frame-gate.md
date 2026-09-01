# Colored frame Boolean gate

`colored_frame_gate.py` runs before lexical overlap and statistical
classification.  It recognises a closed family of question frames and remains
`NOT_APPLICABLE` outside that family.

## Frame identity

Each brick binds seven independent fields:

- its role;
- its fixed hue;
- its exact canonical value, retained for identity and audit;
- a closed visual motif representing a semantic family;
- an intention;
- a bounded intention intensity;
- an optional direction arrow displayed immediately before the brick.

The role colors are:

- `SUBJECT` → `BLUE`;
- `RELATION` → `ORANGE`;
- `OBJECT` → `WHITE`;
- `QUALIFIER` → `YELLOW`.

A hue is not a semantic proof by itself. Swapping subject and object fails
even when the words or motifs are similar.

## Direction law

Direction stays outside the patterned brick so it cannot be confused with the
semantic family inside it:

- `↑ increase` for an upward intention;
- `↓ reduce` for a downward intention;
- no arrow for a non-directional intention.

The arrow is derived from the same closed registry as the intention. A caller
cannot attach `↓` to `increase` or `↑` to `reduce`. The arrow is a reading aid
and a consistency check; it does not replace the exact word, motif, role,
polarity or frame comparison.

## Motif law

The motif makes a meaning-level comparison visible without erasing the exact
words. For example, `reduce`, `lower`, `diminuer` and `faire baisser` carry the
same sparse-white-dot motif and the same `REDUCE` intention. `increase` has a
different motif and opposite intention. Unknown surfaces remain `SOLID` and
require exact value identity.

Two bricks may say the same thing only when all these conditions hold:

- same role and therefore same fixed hue;
- same non-`EXACT` semantic family;
- same intention;
- same direction arrow;
- compatible intensity band;
- same frame polarity.

The exact values may differ in that case. The motif only opens a candidate
semantic match: it never authorises a frame by itself. Actor, object, number,
date, qualifier, negation and scope remain separately bound. A caller cannot
attach a preferred motif or force to an unrelated word; the closed registry
derives them from the role and canonical surface, otherwise construction
fails closed.

## Boolean law

The comparison is directional:

`answer frame ⊆ source frame or deterministic derived frame`

The source may carry additional qualifiers.  Every answer brick must be
present either with exact identity or with the compatible motif law above.
Every recognised answer frame must be contained; one contradiction vetoes the
composition.

The three outcomes are:

- `PROVED`: all recognised frames are contained;
- `DISPROVED`: a role, value, number, order or polarity contradicts the source;
- `UNRESOLVED`: the family was recognised but a required binding is absent.

An unrecognised family is `NOT_APPLICABLE` and may continue through the older
structural and statistical gates.  A recognised but unresolved family never
receives a lexical pass.

## Deterministic derivations

The initial closed set includes absolute change, percentage increase, binary
complement, mean, remainder, profit margin, equity, current ratio, unit
conversion, chronological order, rank succession and scalar comparison.  The
receipt records the formula and operands.  No external teacher, model call or
word-overlap threshold authorises these proofs.

## Scope

This gate improves the covered families; it does not understand arbitrary
language and does not establish universal hallucination prevention. Extend a
motif only with paired paraphrase/antonym tests, intensity tests, role-swap
tests and clean release replay.
