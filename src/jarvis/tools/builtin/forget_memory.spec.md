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

1. **Propose.** A call that is not a confirmation finds the stored fact lines
   matching the subject, stashes them in a process-wide single-slot pending
   buffer (TTL `_PENDING_TTL_SEC` = 120 s) and **deletes nothing**. It returns
   a `requires_confirmation:` raw result listing what would be removed.
2. **Confirm.** When a fresh proposal is pending, deletion happens **only** on a
   genuine assent signal: an explicit `confirm: true`, OR a provided subject
   that *positively matches* the pending fact lines (see Recall). Anything else
   while pending — an empty/odd call, or a subject that matches a *different*
   stored fact — is treated as a new propose, not a confirmation.

**The unbypassable guard:** deletion requires a fresh prior proposal AND a
genuine assent signal. A single "forget X" only ever proposes (force-exec runs
it with no confirmation signal yet). A misheard/odd call, or a stray/stale call
that names nothing matching the pending, never deletes. Combined with the
router behaviour below, a refusal cannot delete either.

**Why subject-match is the assent signal.** When a deletion is pending the
listener passes `pending_confirmation="forgetMemory"` to the fused router,
which then, in any language: routes an ASSENT to forgetMemory (echoing the
pending fact as the argument, e.g. "go ahead" → `{memory: "you live in
Berlin"}`), routes a REFUSAL to NO tool (so it never reaches the tool — hence
can never delete), and routes a DIFFERENT new "forget Y" to forgetMemory with
Y's subject. So while pending: a routed call whose subject matches the pending
== assent (delete); a routed call whose subject matches something else == a
pivot (re-propose); a refusal never arrives. This is verified by
`evals/test_fused_forget_confirmation_routing.py` (EN + EL), which also shows
that WITHOUT the pending-confirmation rule a refusal non-deterministically
routes to forgetMemory — the rule is the safety-critical change.

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
a confabulated "deleted that for you" without ever emitting the tool call.
Three mechanisms make the flow reliable AND safe:

- **Force-execution (any model size).** A `forgetMemory` plan step is
  force-executed via the plan direct-exec path on *any* model size (like the
  vision perception tools, see `planner.spec.md`), so the operation actually
  runs instead of being confabulated. The engine executes it with the fused
  router's own arguments (the confirm flag and/or the subject it echoed); when
  the router gives nothing usable the tool falls back to the user's utterance.
  Safe regardless: a forced call deletes only on the genuine assent signal
  (explicit confirm, or a subject matching the pending — see above).
- **Pending-aware router (`pending_confirmation`).** When a deletion is pending,
  the listener passes `pending_confirmation="forgetMemory"` to the fused router
  (gated on `has_fresh_pending()`). A system-prompt rule then makes the router
  classify the turn in-language: assent → forgetMemory, refusal → NO tool,
  different request → routed normally. This is what keeps a refusal from ever
  reaching the tool, and is verified before/after by the eval.
- **Pending-aware allow-list.** While a proposal is pending the engine also
  keeps `forgetMemory` in the turn's allow-list, so the chat model can still
  reach it even if the router classified the turn as another tool. Safe for the
  same reason: deletion needs the assent signal, which a refusal lacks.

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
