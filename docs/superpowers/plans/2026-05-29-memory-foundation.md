# Memory Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **Test runner:** `C:\Users\aggel\Jarvis-src\.venv\Scripts\python.exe -m pytest tests/<file> -v` (run from `C:\Users\aggel\Jarvis-src`). Import as `from jarvis.x import ...` (conftest puts `src` on `sys.path`). Modules import cleanly in `.venv`.
> **Conventions:** British English, NO em dashes in user-facing strings, emojis OK in CLI prints, `from ..debug import debug_log`. Data privacy first. Do NOT touch the forced-English reply clamp.
> **Decision (locked):** ship the scrub LOGIC + endpoint first; the memory-viewer UI button is a later thin follow-up.
> **Pre-existing WIP:** the working tree has ~17 pre-existing failing tests unrelated to this work (enrichment/intent-judge/migration/UI). Only ensure YOUR new tests pass and you add no NEW failures.

**Goal:** Give Jarvis a clean, protected, recallable memory foundation: repair semantic recall, stop the extractor storing garbage, and add a reusable review-gated cleanup.

**Architecture:** Three independent phases. (1) Recall repair fixes the empty python faiss vector store + backfills. (2) Write-time hygiene gate hardens `extract_graph_memories` using a shared hallucination blocklist + plausibility rules. (3) A reusable `scrub_graph_facts` (mirroring the diary `rewrite_all_diary_summaries`) returns review-gated deletion proposals, exposed via an endpoint.

**Tech Stack:** Python 3.11, SQLite, Ollama (`gemma4:e2b` chat, `nomic-embed-text` 768-dim embeddings), faiss python vector store (`utils/vector_store.py`), pytest.

---

## File structure

| File | Responsibility | Action |
|------|----------------|--------|
| `src/jarvis/memory/db.py` | `upsert_summary_embedding`, vector search, `is_vss_enabled`, `_python_vector_store` | Modify (add `has_vector_store` helper + `summaries_missing_embeddings`) |
| `src/jarvis/memory/conversation.py` | summary write + embedding, diary scrub/optimise, graph extraction call | Modify (fix `can_reembed` gate; add `backfill_summary_embeddings`) |
| `src/jarvis/utils/vector_store.py` | python faiss store (`add_vector`, `search`, persistence) | Read + verify persistence (Phase 1 diagnosis) |
| `src/jarvis/listening/hallucinations.py` | shared hallucination blocklist | Create (moved from `listener.py`) |
| `src/jarvis/listening/listener.py` | STT path; currently owns the blocklist | Modify (import from new module) |
| `src/jarvis/memory/graph_ops.py` | `extract_graph_memories`, `update_graph_from_dialogue`, new `scrub_graph_facts` | Modify + add |
| `src/jarvis/api_server.py` | REST/WS endpoints | Modify (add `/api/graph/scrub-facts`) |
| `src/jarvis/memory/graph.spec.md`, `summariser.spec.md` | specs | Modify |

---

## PHASE 1 - Recall repair (empty vector store)

### Task 1: Characterise the recall gap with a test

**Files:**
- Test: `tests/test_recall_embeddings.py` (create)
- Read first: `src/jarvis/utils/vector_store.py` (how `add_vector`/`search` persist), `src/jarvis/memory/db.py:90-150,416-435`

- [ ] **Step 1: Write the failing/characterisation test**

```python
# tests/test_recall_embeddings.py
from jarvis.memory.db import Database

def test_python_vector_store_roundtrip(tmp_path):
    """When sqlite-vss is unavailable, an upserted summary embedding must be
    retrievable via vector search (this is the path the live Windows DB uses)."""
    db = Database(str(tmp_path / "t.db"), sqlite_vss_path=None)
    assert db.is_vss_enabled is False          # python faiss path is active
    summary_id = db.insert_or_update_summary(date_utc="2026-05-29", source_app="test",
                                              summary="Angelos lives in Ioannina", topics="user")
    emb = [0.01] * 768
    db.upsert_summary_embedding(summary_id, emb)
    hits = db.search_summaries_by_vector(emb, top_k=3)   # name per db.py; adjust to real API
    assert any(h["summary_id"] == summary_id for h in hits), "stored vector must be searchable"
    db.close()
```

- [ ] **Step 2: Run it; adjust method names to the real `db.py` API**

Run: `...python.exe -m pytest tests/test_recall_embeddings.py -v`
Expected: either FAIL (pins the persistence bug) or reveals the exact missing/renamed method. Read `db.py` search method names (around lines 130-160) and `insert_or_update_summary` signature; fix the test to call the real API. The test must end up asserting a true behaviour.

- [ ] **Step 3: If the store does not persist, fix `utils/vector_store.py` / `db.upsert_summary_embedding`**

Make `add_vector` persist to the `faiss_vector_store` table on write (or on a flush the daemon already calls). Keep the change minimal and within the existing store class.

- [ ] **Step 4: Run the test to PASS**

Run: `...python.exe -m pytest tests/test_recall_embeddings.py -v`  Expected: PASS.

- [ ] **Step 5: Commit**

```
git add tests/test_recall_embeddings.py src/jarvis/utils/vector_store.py src/jarvis/memory/db.py
git commit -m "fix(memory): persist summary embeddings via python vector store path"
```

### Task 2: Embed on summary write (python-store path)

**Files:**
- Modify: `src/jarvis/memory/conversation.py:1096-1340` (`generate_conversation_summary`)
- Test: `tests/test_recall_embeddings.py`

- [ ] **Step 1: Write the failing test**

```python
def test_summary_write_populates_vector_store(tmp_path, monkeypatch):
    """Writing a summary with an embed model configured must store a vector."""
    from jarvis.memory.db import Database
    import jarvis.memory.conversation as conv
    monkeypatch.setattr(conv, "get_embedding", lambda text, base, model, timeout_sec=15.0: [0.02] * 768)
    db = Database(str(tmp_path / "t.db"), sqlite_vss_path=None)
    conv.update_conversation_summary(  # use the real public write entrypoint; adjust name
        db, source_app="test",
        messages=[(0.0, "user", "I live in Ioannina"), (1.0, "assistant", "Noted.")],
        ollama_base_url="http://x", ollama_chat_model="gemma4:e2b", ollama_embed_model="nomic-embed-text",
    )
    rows = db.get_all_conversation_summaries()
    assert rows, "a summary row must exist"
    hits = db.search_summaries_by_vector([0.02] * 768, top_k=3)
    assert hits, "the written summary must be vector-searchable"
    db.close()
```

- [ ] **Step 2: Run it** (`...pytest tests/test_recall_embeddings.py::test_summary_write_populates_vector_store -v`). Read the real summary-write entrypoint name + signature (around `conversation.py:1096`, `1267`, `1597-1624`) and fix the call. Expected: FAIL if embeddings are skipped on the python path.

- [ ] **Step 3: Fix** so the write path always calls `get_embedding` + `db.upsert_summary_embedding` when an embed model is set, regardless of `is_vss_enabled` (the python store path must not be skipped). The existing lines `conversation.py:1336-1338` already do this for `generate_conversation_summary`; ensure no upstream guard skips it on the python path.

- [ ] **Step 4: Run to PASS.**

- [ ] **Step 5: Commit**

```
git commit -am "fix(memory): write summary embedding on the python vector-store path"
```

### Task 3: Backfill helper + fix the `is_vss_enabled` re-embed gate

**Files:**
- Modify: `src/jarvis/memory/db.py` (add `has_vector_store` property + `summary_ids_without_embedding()`)
- Modify: `src/jarvis/memory/conversation.py:171,466` (`can_reembed` gate)
- Add: `backfill_summary_embeddings(db, ollama_base_url, ollama_embed_model, ...)` in `conversation.py`
- Test: `tests/test_recall_embeddings.py`

- [ ] **Step 1: Write the failing test**

```python
def test_backfill_embeds_existing_summaries(tmp_path, monkeypatch):
    from jarvis.memory.db import Database
    import jarvis.memory.conversation as conv
    db = Database(str(tmp_path / "t.db"), sqlite_vss_path=None)
    sid = db.insert_or_update_summary(date_utc="2026-05-29", source_app="test",
                                      summary="Angelos lives in Ioannina", topics="user")
    # No embedding yet:
    assert db.summary_ids_without_embedding() == [sid]
    monkeypatch.setattr(conv, "get_embedding", lambda text, base, model, timeout_sec=15.0: [0.03] * 768)
    n = conv.backfill_summary_embeddings(db, "http://x", "nomic-embed-text")
    assert n == 1
    assert db.summary_ids_without_embedding() == []
    db.close()
```

- [ ] **Step 2: Run it** (FAIL: `summary_ids_without_embedding` / `backfill_summary_embeddings` not defined).

- [ ] **Step 3: Implement**
- `db.has_vector_store` -> `self.is_vss_enabled or self._python_vector_store is not None`.
- `db.summary_ids_without_embedding()` -> summary ids with no vector in the active store.
- In `conversation.py:171` and `:466` change `can_reembed = bool(ollama_base_url and ollama_embed_model and db.is_vss_enabled)` to `... and db.has_vector_store`.
- `backfill_summary_embeddings(db, ollama_base_url, ollama_embed_model, timeout_sec=15.0)`: for each id from `summary_ids_without_embedding()`, embed `summary + " " + topics` via `get_embedding` and `db.upsert_summary_embedding`. Fail-open per row. Return count embedded.

- [ ] **Step 4: Run to PASS.**

- [ ] **Step 5: Commit**

```
git commit -am "feat(memory): backfill summary embeddings + fix re-embed gate for python store"
```

- [ ] **Step 6: Backfill the LIVE database (one-off, after restart-safe)**

Run a throwaway script in `.venv` that opens `~/.local/share/jarvis/jarvis.db`, calls `backfill_summary_embeddings` with the user's `ollama_base_url` + `nomic-embed-text`, and prints the count. Expected: 5 summaries embedded. (Daemon should be stopped or this is best-effort under WAL.)

---

## PHASE 2 - Write-time hygiene gate

### Task 4: Extract the hallucination blocklist into a shared module

**Files:**
- Create: `src/jarvis/listening/hallucinations.py`
- Modify: `src/jarvis/listening/listener.py` (replace the inline `_HALLUCINATION_EXACT` / `_HALLUCINATION_SUBSTRINGS` near lines 2685-2759 with imports)
- Test: `tests/test_hallucination_blacklist.py` (existing - must keep passing)

- [ ] **Step 1: Read** `listener.py:2685-2760` to copy the exact `_HALLUCINATION_EXACT`, `_HALLUCINATION_SUBSTRINGS`, and the `_is_youtube_hallucination` helper.

- [ ] **Step 2: Create `hallucinations.py`** with the moved constants + a pure function `looks_like_hallucination(text: str) -> bool` (exact-match set + substring set, lowercased). No behaviour change.

- [ ] **Step 3: Update `listener.py`** to `from .hallucinations import looks_like_hallucination, HALLUCINATION_EXACT, HALLUCINATION_SUBSTRINGS` and delete the inline copies; keep `_is_youtube_hallucination` delegating to `looks_like_hallucination`.

- [ ] **Step 4: Run** `...pytest tests/test_hallucination_blacklist.py tests/test_calm_whisper_blocklist.py -v`. Expected: PASS (no behaviour change).

- [ ] **Step 5: Commit**

```
git commit -am "refactor(memory): share hallucination blocklist between STT and extractor"
```

### Task 5: Gate `extract_graph_memories` against garbage

**Files:**
- Modify: `src/jarvis/memory/graph_ops.py:49-240` (`extract_graph_memories`)
- Test: `tests/test_graph_extractor_hygiene.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_graph_extractor_hygiene.py
from unittest.mock import patch
import jarvis.memory.graph_ops as go

def _run(facts):
    # mock the LLM extraction to return raw (branch, fact) tuples, then assert the gate filters
    with patch.object(go, "_call_extractor_llm", return_value=facts):  # adjust to real internal
        return go.extract_graph_memories("summary", "http://x", "gemma4:e2b")

def test_drops_known_hallucination_fact():
    out = _run([("user", "The user is interested in the subtitle service authorwave")])
    assert out == []

def test_drops_transient_data_as_fact():
    out = _run([("world", "Ioanna is experiencing partly cloudy weather 12.6C")])
    assert out == []

def test_keeps_legitimate_user_fact():
    out = _run([("user", "The user lives in Ioannina")])
    assert ("user", "The user lives in Ioannina") in out
```

- [ ] **Step 2: Run it** (FAIL). Read `extract_graph_memories` to find the real internal that yields facts (around lines 220-240, the `facts` list before return) and adjust the patch target.

- [ ] **Step 3: Implement the gate** - after the LLM yields candidate facts and before returning, drop any fact where `looks_like_hallucination(fact_text)` is True, or that matches a transient-data shape (contains weather/temperature/forecast/current-time wording the gate treats as transient). Also extend the extractor `system_prompt` (lines 70+) with: do not store transient tool data (weather, time) as enduring facts; do not assert low-confidence identities or languages; prefer attribution for third-party claims. Keep the deterministic drop (blocklist + transient) as the belt; the prompt is the braces. No hardcoded human-language lists.

- [ ] **Step 4: Run to PASS.**

- [ ] **Step 5: Commit**

```
git commit -am "feat(memory): hygiene gate in graph extractor (blocklist + transient + prompt)"
```

### Task 6: Eval - extractor rejects implausible facts

**Files:**
- Create: `evals/test_graph_hygiene.py` (mirror `evals/test_diary_summariser_hygiene.py`)

- [ ] **Step 1: Write the eval** (live `gemma4:e2b`, soft-xfail on weaker models): given a summary that mentions a mis-detected language or a person-as-place confusion, assert `extract_graph_memories` does not emit a `("user", "...speaks Welsh...")` or a `("world", "<person> is located in ...")` fact. Use `@pytest.mark.eval`.

- [ ] **Step 2: Run** `...pytest evals/test_graph_hygiene.py -v` (needs Ollama). Record pass/xfail.

- [ ] **Step 3: Commit**

```
git commit -am "test(memory): graph extractor hygiene eval"
```

---

## PHASE 3 - Reusable graph-fact scrub (review-gated)

### Task 7: `scrub_graph_facts` proposal generator

**Files:**
- Read first: `src/jarvis/memory/conversation.py:133-300` (`rewrite_all_diary_summaries` - the pattern to mirror, incl. the untrusted-input fence + counts-only events)
- Add: `scrub_graph_facts(store, ollama_base_url, ollama_chat_model, timeout_sec=30.0)` in `src/jarvis/memory/graph_ops.py`
- Test: `tests/test_graph_scrub.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_graph_scrub.py
from unittest.mock import patch
import jarvis.memory.graph_ops as go

class FakeStore:
    def __init__(self, branches): self._b = branches
    def get_node(self, nid):
        class N: pass
        n = N(); n.data = self._b.get(nid, ""); return n

def test_scrub_proposes_drops_with_reasons():
    store = FakeStore({"user": "The user lives in Ioannina\nThe user speaks Welsh"})
    # mock the per-branch LLM verdict: keep line 0, drop line 1
    with patch.object(go, "_judge_facts",
                      return_value=[{"fact": "The user speaks Welsh", "drop": True, "reason": "transcription artefact"}]):
        result = go.scrub_graph_facts(store, "http://x", "gemma4:e2b")
    drops = [d for d in result["proposals"] if d["drop"]]
    assert any("Welsh" in d["fact"] for d in drops)
    assert all("reason" in d for d in drops)
    # PROPOSAL ONLY - nothing deleted yet:
    assert "applied" not in result or result["applied"] is False
```

- [ ] **Step 2: Run it** (FAIL: `scrub_graph_facts` / `_judge_facts` not defined).

- [ ] **Step 3: Implement** - walk the `user`/`directives`/`world` branch nodes, split `data` into facts (one per line), pass each branch's facts to the chat model wrapped in the same `<<<BEGIN UNTRUSTED ...>>>` fence used by the diary scrub, asking for a per-fact `{fact, drop: bool, reason}` JSON verdict (flag transcription artefacts, hallucinations, entity-confusion, transient-as-fact, generic trivia). Return `{"proposals": [...], "applied": False}`. Do NOT mutate the graph. Fail-open: LLM/JSON failure -> empty proposals.

- [ ] **Step 4: Run to PASS.**

- [ ] **Step 5: Commit**

```
git commit -am "feat(memory): scrub_graph_facts proposal generator (review-gated)"
```

### Task 8: Apply-on-confirm + privacy-safe progress events

**Files:**
- Modify: `src/jarvis/memory/graph_ops.py` (`apply_graph_scrub(store, approved_facts: list[dict]) -> dict`)
- Test: `tests/test_graph_scrub.py`

- [ ] **Step 1: Write the failing test**

```python
def test_apply_removes_only_approved_facts():
    import jarvis.memory.graph_ops as go
    class Store:
        def __init__(self): self.data = {"user": "The user lives in Ioannina\nThe user speaks Welsh"}
        def get_node(self, nid):
            class N: pass
            n = N(); n.data = self.data.get(nid, ""); return n
        def update_node(self, nid, *, data): self.data[nid] = data
    s = Store()
    res = go.apply_graph_scrub(s, [{"branch": "user", "fact": "The user speaks Welsh"}])
    assert "Welsh" not in s.data["user"]
    assert "Ioannina" in s.data["user"]      # untouched fact preserved
    assert res["removed"] == 1               # counts-only
```

- [ ] **Step 2: Run** (FAIL). **Step 3: Implement** `apply_graph_scrub` - for each approved `{branch, fact}`, remove that exact line from the branch node `data` via `store.update_node`, preserve all other lines, return `{"removed": n}` (counts only, no raw text in the return for the streaming layer). **Step 4: PASS.**

- [ ] **Step 5: Commit**

```
git commit -am "feat(memory): apply_graph_scrub removes only user-approved facts"
```

### Task 9: Endpoint `/api/graph/scrub-facts`

**Files:**
- Read first: the diary scrub endpoint in `src/jarvis/api_server.py` (search `scrub-deflections`) - mirror its NDJSON-streaming + counts-only contract
- Modify: `src/jarvis/api_server.py`
- Test: `tests/test_memory_viewer_graph_scrub_api.py` (create, mirror `tests/test_memory_viewer_diary_scrub_api.py`)

- [ ] **Step 1: Write the failing test** asserting: `GET`-then-`POST` (or two endpoints) `propose` returns proposals; `apply` with approved facts returns counts; the streamed/JSON event key set is a known whitelist (no raw fact text leaks). Mirror `test_progress_event_keys_are_a_known_whitelist`.

- [ ] **Step 2: Run** (FAIL). **Step 3: Implement** two endpoints (or one with `?apply=`): `propose` -> `scrub_graph_facts`, `apply` -> `apply_graph_scrub`. Privacy: stream counts/booleans; raw fact text only in the propose response the local user reviews. **Step 4: PASS.**

- [ ] **Step 5: Commit**

```
git commit -am "feat(memory): /api/graph/scrub-facts propose+apply endpoints"
```

### Task 10: Update specs

**Files:**
- Modify: `src/jarvis/memory/graph.spec.md` (document the write-time hygiene gate + `scrub_graph_facts`/`apply_graph_scrub` + endpoint, review-gated, privacy contract)
- Modify: `src/jarvis/memory/summariser.spec.md` (note the graph extractor now has its own write-time gate in addition to summariser hygiene)

- [ ] **Step 1:** Add the sections. **Step 2: Commit**

```
git commit -am "docs(memory): spec the hygiene gate + graph-fact scrub"
```

---

## Self-review (against the spec)

- Spec component 1 (cleanup) -> Tasks 7-9 (scrub propose/apply + endpoint), review-gated, privacy-safe. UI button deferred per locked decision. ✅
- Spec component 2 (write-time guard) -> Tasks 4-6 (shared blocklist + extractor gate + eval). ✅
- Spec component 3 (recall repair) -> Tasks 1-3 (persistence + write-time embed + backfill + live backfill). ✅
- Privacy/fail-open/audit -> asserted in Tasks 8-9 (counts-only, whitelist key test), fail-open in 3/5/7. ✅
- No hardcoded human-language patterns -> Task 5 uses blocklist + transient-shape + LLM prompt only. ✅
- Out of scope (new personalisation, reply language) -> not in any task. ✅
- Gap noted: several steps say "adjust to the real API / read X first" because exact internal names (`db` search method, `generate_conversation_summary` public entrypoint, the extractor's internal facts variable, the python store persistence) must be read at execution time. Tests are behaviour-concrete; the executor reads the real code and adapts the call sites. This is intentional for a brownfield plan.
