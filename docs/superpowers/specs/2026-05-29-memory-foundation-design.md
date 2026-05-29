# Memory Foundation Design

**Date:** 2026-05-29
**Status:** Draft (awaiting user review)
**Goal:** Make Jarvis's memory smarter and more useful by giving it a *clean, protected, recallable* foundation, before adding any new personalisation features.

## Plain-language summary

Jarvis's memory is like a notebook about the user. We found three problems:
1. It had **wrong notes** (e.g. "speaks Welsh", "Ioanna is a Russian island" - actually the city Ioannina mis-heard) that it read on every reply.
2. It **wrote anything it heard, unchecked**, so garbage piled up.
3. Its **deep search was broken** (the semantic index was empty), so it could not find relevant past info.

This design fixes all three: a **review-gated cleanup**, a **write-time guard**, and a **search repair**. It is deliberately scoped to the *foundation* - new personalisation (preference learning, proactivity) is a later phase that builds on this.

A one-off manual clean-slate has already been applied to the live graph (user = Angelos + Ioannina, directives = address as Boss, world = empty) at the user's request; this design automates and protects that going forward.

## Background (what we found)

- The knowledge graph (`memory_nodes`) stores facts under fixed branches `user` / `directives` / `world`. The **warm profile** (user + directives) is injected into every reply unconditionally.
- The live graph contained transcription artefacts ("speaks Welsh/German"), known hallucinations ("authorwave", already in the STT blocklist), and entity-confusion (the city *Ioannina* stored as a person *Ioanna* and as a Russian island, with weather attached as a world fact).
- Root cause: the summariser hygiene rules (deflection / attribution / topic-separation) do not cover transcription-artefact / hallucination / entity-confusion facts, and the graph extractor (`extract_graph_memories`) has no plausibility gate before `append_to_node`.
- `faiss_vector_store` had **0 rows** while FTS and summaries were populated, so semantic recall returned nothing (consistent with the eval's "did not reference stored knowledge"). Embeddings are not being written at summary-write time.

## Components

### 1. Graph-fact cleanup (reusable, LLM-driven, review-gated)

A new `scrub_graph_facts(store, ollama_base_url, ollama_chat_model, ...)` in `memory/graph_ops.py`, mirroring the existing `rewrite_all_diary_summaries` diary scrub.

- Splits each branch node's `data` into individual facts and asks the chat model to flag facts that read as: transcription artefacts, hallucinations, entity-confusion (person treated as place), transient data (weather / time) stored as an enduring fact, or generic trivia not about the user's world.
- **Human-in-the-loop:** returns proposed deletions with a per-fact reason. Nothing is deleted automatically - the user reviews and confirms (a false deletion loses real memory).
- **Privacy / fail-open / audit:** same guarantees as the diary scrub - progress events stream counts/booleans only (no raw fact text), LLM failure leaves data untouched, node timestamps preserved.
- **UI (optional, can defer):** a memory-viewer button "Clean up implausible facts" + endpoint mirroring `/api/diary/scrub-deflections`. The scrub function works headlessly even without the button.

### 2. Write-time hygiene guard (stop new poisoning)

Harden `extract_graph_memories` so garbage never reaches `append_to_node`:

- **Shared hallucination blocklist:** extract the existing blocklist from `listening/listener.py` into a shared `listening/hallucinations.py` so both the STT path and the graph extractor reject known noise ("authorwave", etc.). Already covered by `tests/test_hallucination_blacklist.py`.
- **Extractor prompt hardening (LLM judgement, not hardcoded language patterns):** do not store facts that read as transcription artefacts; do not assert low-confidence identities or languages; do not turn transient tool data (weather, time) into enduring facts; do not create a `world` fact about an entity that is already a known contact in the `user` branch (cross-branch consistency).
- Respects the project rule "no hardcoded language patterns" - all language-sensitive judgement is delegated to the LLM plus the already-tested blocklist.

### 3. Recall repair (empty vector store)

- Diagnose why `upsert_summary_embedding` is not populating `faiss_vector_store` (confirm whether it is called at summary-write time and whether the embed model is passed).
- Fix the write path so every summary write generates and stores its embedding (768-dim, `nomic-embed-text`).
- **Backfill** embeddings for the existing summaries (reuse the re-embed path already present in the diary rewrite sweep).
- Add a guard/test that summary writes produce embeddings; verify semantic recall returns results after backfill.

## Files touched

- `memory/graph_ops.py` - `scrub_graph_facts` + extractor hygiene gate
- `listening/hallucinations.py` (new) - shared blocklist; update `listening/listener.py` to import it
- `memory/conversation.py` + `memory/db.py` - embedding write at summary-time + backfill
- `api_server.py` + memory viewer - scrub endpoint + button (optional/deferrable)
- specs: `memory/graph.spec.md`, `memory/summariser.spec.md`
- new tests + evals

## Testing and evals

- **Unit:** scrub keep/drop + review-gate + fail-open; extractor rejects blocklist/implausible facts; recall writes embeddings + backfill + semantic search returns results.
- **Eval** (mirroring the diary hygiene evals, target `gemma4:e2b`, soft-xfail on weaker models): the extractor rejects "user speaks Welsh"-style implausible facts; the scrub flags entity-confusion (person/place). A fact like the real city-as-person confusion is a concrete regression case.

## Out of scope (later phases)

- New personalisation features (preference/habit learning, proactive use of facts).
- Reply language: stays permanently English (forced-English clamp untouched), per user choice.
- Weather/location defaulting is config (geoIP), not memory; tracked separately.

## Open decisions

- Ship the scrub UI button now, or land the headless scrub + endpoint first and add the button later? (Leaning: function + endpoint first, button as a thin follow-up.)
- Exact root cause of the empty vector store is to be confirmed during implementation; the fix direction (write at summary-time + backfill) holds regardless.
