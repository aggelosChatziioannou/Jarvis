# forgetMemory tool — spec

Lets the user delete or correct something Jarvis has remembered, by voice, in
any language ("forget that I live in London", "I never said that", "ξέχνα ότι
μένω στην Αθήνα"). Deletion is irreversible and the input is speech, so the
tool is built around an **unbypassable propose → confirm** safety pattern,
mirroring the vision engine.

## Public schema

A single object with two optional properties:

| Property  | Type    | Meaning |
|-----------|---------|---------|
| `subject` | string  | What to forget, e.g. `"lives in London"`. |
| `confirm` | boolean | Honoured only when a fresh proposal is already pending. |

Both are optional because the live router emits unreliable argument names
(`memory`, `memory_to_delete`, `fact`, …) and sometimes a hallucinated value.
The tool therefore does **not** trust the arguments alone (see Subject
resolution).

## Two-turn safety: propose → confirm (unbypassable)

1. **Propose.** The first call finds the stored fact lines matching the
   subject, stashes them in a process-wide single-slot pending buffer
   (TTL `_PENDING_TTL_SEC` = 120 s) and **deletes nothing**. It returns a
   `requires_confirmation:` raw result listing what would be removed.
2. **Confirm.** Deletion happens only against a *fresh* pending proposal. A
   premature `confirm: true` on the very first call (no fresh pending) falls
   through to a propose, so a single misheard "forget …" can never wipe
   memory on its own.

The pending buffer is the only path to deletion; widening recall (below) only
widens what is *proposed*, never what is deleted without consent.

## Subject resolution (router-argument-tolerant)

`subject` is resolved in this order:
1. an explicit `subject` argument, if present;
2. otherwise the user's own utterance (`ToolContext.redacted_text`) — the
   reliable source, since the fused router's argument names/values are not;
3. otherwise any other string argument as a last resort.

## Recall: strict first, then fail-open semantic

`_match_lines` runs two passes:
1. **Strict** (always, free, language-agnostic): the normalised subject is a
   substring of a fact line, or every significant subject token (`\w{3,}`,
   Unicode) appears in the line.
2. **Semantic fallback** (only when strict finds nothing, and only when an
   embed model + positive threshold are configured): include any line whose
   embedding cosine-similarity to the subject is `>= memory_forget_semantic_threshold`
   (default **0.82**). This catches paraphrases strict matching misses
   ("resides in London" vs the stored "the user lives in London").

The threshold is deliberately **looser** than the memory-write dedup
threshold (`memory_semantic_dedup_threshold`, 0.93): write-dedup must never
drop a distinct fact, whereas forget recall only *proposes* — the user vetoes
a wrong candidate at the confirm step, so surfacing a near-paraphrase is safe.
Fail-open: if embeddings are unavailable, recall degrades to the strict
matcher (never raises, never over-matches).

## Reliable execution + confirmation routing (engine integration)

On the live fused path the 9B chat model is unreliable here — it often narrates
a confabulated "deleted that for you" without ever emitting the tool call, and
the fused router sometimes routes the confirmation turn to a different tool
(a diet-related "yes, remove that" can route to `deleteMeal`). Two engine-side
mechanisms make the flow reliable without any prompt change:

- **Force-execution.** `forgetMemory` is force-executed via the plan
  direct-exec path on *any* model size (like the vision perception tools, see
  `planner.spec.md`). The bare `forgetMemory` plan step fast-parses to
  `(forgetMemory, {})` and the tool derives the subject from the utterance, so
  unreliable router arguments do not matter.
- **Pending-aware allow-list + consent.** While a fresh proposal is pending
  (`has_fresh_pending()`), the engine keeps `forgetMemory` in the turn's
  allow-list so the user's assent is honoured even if the router classified the
  confirmation turn as another tool. Reaching the tool again while a proposal
  is pending is treated as **consent** — safe because the upstream router does
  not route refusals ("no, keep it") to a deletion tool (verified EN + EL). If
  the user instead names a *different* stored fact, the tool re-proposes that
  one rather than confirming the first.

## Raw-result contract (anti-confabulation)

Results carry protocol discriminators (mirroring `requires_confirmation:`) so
the persona model phrases them faithfully and cannot narrate a non-event as a
deletion:

| Discriminator            | Meaning |
|--------------------------|---------|
| `requires_confirmation:` | facts found and stashed; ask the user to confirm. |
| `removed:`               | a confirmed deletion actually happened. |
| `no_match:`              | nothing matched; report "found nothing", never claim a deletion. |

`forgetMemory` is in `_DIGEST_SKIP_TOOLS` so the small-model digest pass cannot
strip these discriminators before the persona model reads them.

## Memory hygiene

Because the tool now executes for real (rather than the model confabulating a
deletion that never happened), the diary/graph pipeline no longer ingests a
false "deleted X" claim that would otherwise be re-extracted as a contradictory
user fact. Verified: after a successful forget the graph contains neither the
removed fact nor a "user does not …" negation.

## Principles

- Tools return raw data; the unified system prompt phrases the confirmation
  question and the acknowledgement.
- No hardcoded language patterns: recall is embeddings + a Unicode token
  matcher; assent/refusal is judged by the router/model in-language, never by a
  yes/no word list.
- propose → confirm stays unbypassable; looser recall widens only the proposal,
  never the deletion.

## Config

| Key | Default | Purpose |
|-----|---------|---------|
| `memory_forget_semantic_threshold` | `0.82` | cosine cutoff for the fail-open paraphrase recall pass. |
