# LLM Contexts Map

Every distinct LLM call in Jarvis, what feeds it, what consumes it, and how it is gated. This is the reference for optimising the app's main bottleneck (LLM latency). Keep it in sync with the code — see the note at the bottom.

---

## 1. Main Reply Loop (agentic messages loop)

- **File**: [src/jarvis/reply/engine.py](src/jarvis/reply/engine.py) — `reply()` and the loop at ~lines 1370-1650; native tool-call path in `chat_with_messages()` (~1424, 1455).
- **Trigger**: every user message. Runs up to `agentic_max_turns` (default 8) iterations per reply.
- **Model / gating**: `cfg.ollama_chat_model` (the big model). Not optional. No size branching on the loop itself — size branching affects the digests/evaluator around it.
- **Inputs**:
  - Redacted user query
  - Recent dialogue (last 5 minutes), including in-loop tool-call + tool-role messages from prior replies within the active conversation (tool carryover, `DialogueMemory.record_tool_turn` / `get_recent_turns_with_tools` in [src/jarvis/memory/conversation.py](src/jarvis/memory/conversation.py); per-prompt cap via `cfg.tool_carryover_max_turns` / `tool_carryover_per_entry_chars`; storage cap `_tool_turns_max_storage = 16`; cleared on `stop` signal AND on new-conversation entry; UNTRUSTED WEB EXTRACT fence markers preserved on truncation; both `content` and `tool_calls[*].function.arguments` scrubbed on write)
  - Unified system prompt from [src/jarvis/system_prompt.py](src/jarvis/system_prompt.py) + ASR note + tool-protocol guidance
  - **Warm profile block** (query-agnostic User + Directives excerpt from the knowledge graph, composed by `build_warm_profile()` / `format_warm_profile_block()` in [src/jarvis/memory/graph_ops.py](src/jarvis/memory/graph_ops.py) at Step 3.5 of `reply()`; no LLM call, pure SQLite read; injected unconditionally so personalisation is the default; result cached in `DialogueMemory._hot_cache` under `DialogueMemory.WARM_PROFILE_CACHE_KEY` for the lifetime of the active conversation. Invalidated on `stop`, on new-conversation entry, AND on User/Directives graph mutations via the listener registered in [src/jarvis/daemon.py](src/jarvis/daemon.py) against `register_graph_mutation_listener` in [src/jarvis/memory/graph.py](src/jarvis/memory/graph.py); World-branch writes are ignored)
  - Digested memory enrichment (optional, see #4)
  - Time + location context (re-injected each turn)
  - Tool schema: native via `generate_tools_json_schema()` ([src/jarvis/tools/registry.py](src/jarvis/tools/registry.py)) or text fallback via `_text_tool_call_guidance()` ([engine.py:68](src/jarvis/reply/engine.py:68))
  - Tool results from prior turns (raw or digested — see #5)
- **Output**: OpenAI-style `{content, tool_calls, thinking}`. Consumed by the tool orchestrator and TTS pipeline. Natural-language content is delivered immediately; no post-turn evaluator runs.
- **Limits**: `num_ctx: 8192` (explicit). Timeout `llm_chat_timeout_sec` (180s). Output cap `num_predict` from `llm_chat_max_tokens` (default 512, omitted when ≤ 0) and optional decode `temperature` from `llm_chat_temperature` (default `-1.0` = unset/model default). Auto-fallback from native to text tool-calls on HTTP 400 (`ToolsNotSupportedError`), sticky for the session. Risk: `fetch_web_page` truncates at 50,000 chars (~37k tokens) — mitigated for SMALL models by tool-result digest (#5) which compresses the payload before it enters the messages history. LARGE models receive the raw payload and may silently see a truncated context.

## 2. Intent Judge

- **File**: [src/jarvis/listening/intent_judge.py](src/jarvis/listening/intent_judge.py) — `IntentJudge.evaluate()`.
- **Trigger**: on a speech segment *only if* there is an engagement signal (wake word detected, hot-window active, or TTS playing). Pure ambient speech skips it.
- **Model / gating**: `cfg.intent_judge_model` (default `gemma4:e2b`, ~2B). Falls back to text-based wake detection if Ollama is unavailable.
- **Inputs**:
  - Rolling transcript buffer (last 120s, with timestamps)
  - Wake-word timestamp (if any), normalised aliases
  - Last TTS text + finish time (echo rejection)
  - State flags (wake_word_mode, hot_window_mode, during_tts)
- **System prompt**: `SYSTEM_PROMPT_TEMPLATE` at [intent_judge.py:135](src/jarvis/listening/intent_judge.py:135). Teaches query extraction, echo detection, stop commands, pronoun/topic disambiguation, imperative re-addressing, declaratives to the wake word.
- **Output**: strict JSON `IntentJudgment{directed, query, stop, confidence, reasoning}` ([intent_judge.py:94](src/jarvis/listening/intent_judge.py:94)). Consumed by the listening state machine which dispatches to the reply engine.
- **Limits**: `intent_judge_timeout_sec` (15s). `num_ctx: 8192` (explicit — system prompt is ~2k tokens after PR #362, and the rolling transcript buffer at default `transcript_buffer_duration_sec=120` can reach ~1.5k tokens in chatty multi-speaker scenes; 4096 left ~10% headroom and risked silent ollama truncation of the system prompt's tail, where the few-shot examples and TRANSCRIPT NOISE block live).

## 2b. Fused Intent Engine (LIVE DEFAULT — supersedes #2/#7/#12 on the voice path)

- **File**: [src/jarvis/listening/fused_intent.py](src/jarvis/listening/fused_intent.py) — `FusedIntentEngine.classify_route_plan()`.
- **Trigger**: voice path, Tier 2 of the listener cascade (after the heuristic Tier-1 classifier escalates). With `use_fused_intent` (default True) this is the **live default**: it collapses intent judge (#2) + tool router (#7) + planner (#12) into **one** structured call (~5-7s vs ~15-21s).
- **Model / gating**: `cfg.intent_judge_model` (same model as the judge). `use_fused_intent` gates the engine; `use_fused_tools_in_engine` (default True) gates whether the reply engine consumes the fused `tools`/`plan` and thus **skips its internal #7 router and #12 planner** ([engine.py:1054](src/jarvis/reply/engine.py:1054)). Falls back to the legacy 3-call pipeline when fused is disabled, the fused JSON fails to parse, or the entry isn't the voice path.
- **Inputs**: transcript, `in_hot_window`, `language`, `last_tts_text`.
- **System prompt**: `_build_system_prompt()` advertises a tool catalogue built **dynamically from the live registry** — real `BUILTIN_TOOLS` names + cached MCP tools via `build_tool_catalogue()` — and is rebuilt when the tool/MCP set changes. (Earlier versions used a hardcoded catalogue of fake dotted names that resolved to no real tool; fixed so the model's returned names match the engine allow-list.)
- **Output**: schema-forced JSON `FusedJudgment{intent, confidence, tools[], plan[], fast_path_match, explanation}` (Ollama `format=<schema>`). `tools` → router allow-list shape; `plan` → planner shape; both fed to the reply engine's fast path.
- **Limits**: timeout `min(intent_judge_timeout_sec, 8.0)`; `num_ctx 4096`, `num_predict 300`; 2 attempts (temp 0.1 then greedy 0.0); on total failure a safe default `intent=query` keeps the pipeline alive.

## 3. Memory Enrichment Extractor

- **File**: [src/jarvis/reply/enrichment.py](src/jarvis/reply/enrichment.py) — `extract_search_params_for_memory()` (~line 71).
- **Trigger**: once per reply, **only when the pre-flight planner (#12) emitted a `searchMemory` directive or returned an empty plan (fail-open)**. Pure reply-only plans skip this entirely — saves one LLM call per greeting / small-talk turn.
- **Model / gating**: resolved via `resolve_tool_router_model(cfg)` — `tool_router_model → intent_judge_model → ollama_chat_model`. Small classification task; rides the same small/warm model as the router. Silent empty-dict on failure.
- **Inputs**: user query (with the planner's `topic` hint appended when present), optional context hint (live-context compact summary), UTC now.
- **System prompt**: inline at [enrichment.py:35-63](src/jarvis/reply/enrichment.py:35).
- **Output**: `{keywords, from?, to?, questions?}`. Consumed by memory search in the reply engine.
- **Limits**: up to 2 retries; timeout from `llm_tools_timeout_sec`.
- **Caching**: result cached in `DialogueMemory._hot_cache` under key `enrichment:{redacted_query[+topic_hint]}` for the lifetime of the active conversation. Identical follow-ups within the same conversation reuse the dict and skip the LLM hop. Cleared by `clear_hot_cache()` on the `stop` signal and on new-conversation entry.

## 3b. Recall Gate (pre-enrichment short-circuit)

- **File**: [src/jarvis/memory/recall_gate.py](src/jarvis/memory/recall_gate.py) — `should_recall()`.
- **Trigger**: once per reply, before diary/graph/digest enrichment runs (after the planner has decided memory is potentially needed).
- **Model / gating**: NO LLM — deterministic keyword-coverage heuristic. Cheap.
- **Inputs**: query, recent dialogue (incl. tool carryover rows).
- **Output**: `False` only if hot-window contains a fresh tool result AND ≥50% of the query's content words appear in the hot-window transcript → skips diary, graph, and memory digest for this reply. Else `True`. Fail-open on any exception. Content-word extraction uses `\w{3,}` with `re.UNICODE`, so the gate works for Latin, Cyrillic, CJK, Arabic, Hebrew, etc. (per CLAUDE.md "no hardcoded language patterns"). Overlap words are run through `redact()` before being written to debug logs.
- **Planner precedence**: when the planner explicitly emitted a `searchMemory` step, the gate is bypassed — the planner has more signal than coverage and overriding it would silently drop intent. The gate only short-circuits the fail-open empty-plan path.
- **Rationale**: prevents re-running diary/graph lookups when the hot window already grounds the follow-up (e.g. "his most famous song" after a Bieber webSearch).

## 4. Memory Digest (optional, SMALL models)

- **File**: [src/jarvis/reply/enrichment.py](src/jarvis/reply/enrichment.py) — `digest_memory_for_query()` + `_distil_batch()`.
- **Trigger**: once per reply when enrichment returns hits AND `memory_digest_enabled` (default OFF; `null` = auto-ON for SMALL ≤7B / OFF for LARGE). Skipped if raw < `_DIGEST_MIN_CHARS` (400). Batched if raw > `_DIGEST_BATCH_MAX_CHARS` (2000).
- **Model / gating**: `ollama_chat_model`. Gated by `memory_digest_enabled`.
- **Inputs**: user query, raw diary entries, raw graph nodes.
- **System prompt**: `_DIGEST_SYSTEM_PROMPT` at [enrichment.py:122](src/jarvis/reply/enrichment.py:122). Teaches relevance filtering, preference-signal detection, attribution preservation, `NONE` sentinel, identity queries.
- **Output**: ≤400 chars text per batch (`_DIGEST_MAX_CHARS`) injected as reference-only memory context into the main loop's system message. Empty on failure.
- **Limits**: `llm_digest_timeout_sec` (8s, shared).

## 5. Tool-Result Digest (optional, opt-in)

- **File**: [src/jarvis/reply/enrichment.py](src/jarvis/reply/enrichment.py) — `digest_tool_result_for_query()` + `_distil_tool_batch()`.
- **Trigger**: after each tool result in the loop, if `tool_result_digest_enabled` (default `null` = auto-ON for SMALL ≤7B, OFF for LARGE). Primary motivation on small models: prevents `fetch_web_page`'s 50k-char payloads from filling the 8192 num_ctx window. Skipped if raw < 400 chars (`_TOOL_DIGEST_MIN_CHARS`); batched if > 2500 (`_TOOL_DIGEST_BATCH_MAX_CHARS`).
- **Model / gating**: `ollama_chat_model`. Gated by `tool_result_digest_enabled`.
- **Inputs**: user query, tool name, raw tool result (e.g. webSearch payload inside UNTRUSTED WEB EXTRACT fence).
- **System prompt**: `_TOOL_DIGEST_SYSTEM_PROMPT`. Teaches attributed fact extraction, `NONE` sentinel, no inference.
- **Output**: ≤600 chars per batch (`_TOOL_DIGEST_MAX_CHARS`) replacing the raw payload in the messages stream. Falls back to raw on `NONE`.
- **Limits**: `llm_digest_timeout_sec` (8s, shared).

## 6. Max-Turn Loop Digest

- **File**: [src/jarvis/reply/enrichment.py](src/jarvis/reply/enrichment.py) — `digest_loop_for_max_turns()` (~line 847).
- **Trigger**: when the loop exhausts `agentic_max_turns` without producing a natural-language reply (e.g. pure tool-call loop). The evaluator no longer drives this — termination on content is immediate.
- **Model / gating**: `_resolve_loop_digest_model(cfg)` — prefers `intent_judge_model`, falls back to `ollama_chat_model`.
- **Inputs**: user query + loop activity (tool calls, results summaries, any prose).
- **System prompt**: `_LOOP_DIGEST_SYSTEM_PROMPT` — caveat-prefixed, user-language, concise.
- **Output**: caveat-prefixed final reply. Fails open to the last raw candidate or generic error.
- **Limits**: `llm_digest_timeout_sec` (8s, shared).

## 7. Tool Router (pre-loop tool selection)

- **File**: [src/jarvis/tools/selection.py](src/jarvis/tools/selection.py) — `select_tools_with_llm()` (~line 331).
- **Trigger**: once per reply, **at the very front of the flow before the planner (#12)**. Always runs — the router is the authoritative tool picker, and its narrowed catalogue is what the planner sees. When the planner later references tools, those names are unioned into the router's allow-list but never replace it; small models tend to default to `webSearch` where a dedicated tool like `getWeather` should win, and the router is tuned for that classification. `tool_selection_strategy == "llm"` is the default; other strategies (`all`, `keyword`, `embedding`) also run here.
- **Model / gating**: `resolve_tool_router_model(cfg)` chain — `tool_router_model → intent_judge_model → ollama_chat_model`.
- **Inputs**: user query, tool catalogue (builtin + MCP with descriptions), optional narrow-down hint.
- **System prompt**: inline (~lines 260-315). Teaches pick up-to-5 tools or `none`.
- **Output**: comma-separated tool names or `none`. Capped at `_LLM_MAX_SELECTED` (5). Always-included tools (`stop`, `toolSearchTool`) are unioned in regardless.
- **Limits**: `llm_timeout_sec`. On failure → all tools.
- **Caching**: `routed_tools` cached in `DialogueMemory._hot_cache` under key `router:{redacted_query}|{strategy}|{builtin-names}|{mcp-names}` for the lifetime of the active conversation. The catalogue signature lets a mid-conversation MCP refresh invalidate the cache; `context_hint` is intentionally excluded so time/location drift inside one conversation doesn't bust it. Cleared by `clear_hot_cache()` on the `stop` signal and on new-conversation entry.
- **Carry-over guard (engine-side overlay)**: after the cache lookup/write, the engine inspects the previous assistant turn's tool calls. When a previous tool reported `success=False` on its `ToolExecutionResult` (read via the `tool_failed` flag stamped onto each recorded tool result), that tool name is unioned back into the local `routed_tools` for this turn only. Compensates for small routers that misroute follow-ups where the user is supplying missing info (e.g. "I'm in London" routing to `webSearch` after a stalled `getWeather` chain). Successful chains do not carry over — a genuine new short ask after a completed chain keeps the router pick clean. The augmentation never touches the cache; replays of the same query in future turns get the raw router output. See `src/jarvis/reply/reply.spec.md` §6 (Tool allow-list per turn) for the full contract.

## 8. Tool Searcher (mid-loop escape hatch)

- **File**: [src/jarvis/tools/builtin/tool_search.py](src/jarvis/tools/builtin/tool_search.py) — `toolSearchTool`.
- **Trigger**: when the model explicitly invokes `toolSearchTool` during the loop. Capped at `tool_search_max_calls` (3) per reply.
- **Model**: reuses the tool router (#7) — no separate LLM call here.
- **Inputs**: self-contained query from the model.
- **Output**: newline-separated tool names + one-liners, merged into the allow-list for the next turn.

## 9. Conversation Summariser

- **File**: [src/jarvis/memory/conversation.py](src/jarvis/memory/conversation.py) — `generate_conversation_summary()` (~lines 350/355).
- **Trigger**: background, periodic — when unsaved dialogue reaches `dialogue_memory_timeout`. One per day per `source_app`.
- **Model / gating**: `ollama_chat_model`. Respects `llm_thinking_enabled`. Uses streaming when a token callback is provided, else direct.
- **Inputs**: recent conversation chunks + prior same-day summary (for incremental update).
- **System prompt**: inline (~lines 310-320). Hygiene rules per [src/jarvis/memory/summariser.spec.md](src/jarvis/memory/summariser.spec.md): no deflection narration, attribution preservation, topic separation. The deflection rule (rule 6) is enumerated with concrete BAD/GOOD pairs in English plus parallel pairs in Turkish and Spanish so small models don't assume the rule is keyed to English phrasing. ≤200 words + 3-5 topic keywords.
- **Output**: `(summary_text, topics_text)` → `conversation_summaries` table, embedded for vector search, feeds enrichment (#3) and graph extraction (#10). No post-process scrub — the prompt is single-source-of-truth, language-agnostic, and improves automatically as the chat model upgrades.
- **Deflection rewrite (separate bulk op)**: `rewrite_all_diary_summaries()` (`POST /api/diary/scrub-deflections`) — for cleaning historical rows written before the prompt was tightened. One `ollama_chat_model` call per row with `_REWRITE_DEFLECTION_SYSTEM_PROMPT`, asking the model to drop sentences that narrate the assistant's own failures while keeping everything else verbatim. Diary text is fenced as untrusted data (same fence used by the web tool). Preserves `ts_utc`; re-embeds updated rows best-effort. Empty-rewrite guard keeps the original if the model would have emptied the row. Fail-open at every layer (LLM call, write-back, embed). User-triggered from the Maintenance section in the diary sidebar.
- **Topic optimisation (separate bulk op)**: `optimise_diary_topics()` (`POST /api/diary/optimise-topics`) — collects all unique tags from `conversation_summaries`, makes one `ollama_chat_model` call with `_TOPIC_OPTIMISE_SYSTEM_PROMPT` to propose a normalised taxonomy (merge synonyms, split compound tags), then applies the mapping to every row that needs updating. Preserves `ts_utc`; re-embeds updated rows best-effort. User-triggered from the Maintenance section in the diary sidebar.
- **Limits**: `timeout_sec` (30s default).

## 10. Knowledge Graph Fact Extraction + Branch Classification

- **File**: [src/jarvis/memory/graph_ops.py](src/jarvis/memory/graph_ops.py) — `extract_graph_memories()`.
- **Trigger**: after each daily summary (#9). Background.
- **Model**: `ollama_chat_model`.
- **Inputs**: summary text + optional date.
- **System prompt**: inline — asks for JSON array of `{"branch": "USER|DIRECTIVES|WORLD", "fact": "..."}` objects, with a heuristic ("user telling the assistant how to behave → DIRECTIVES; user telling the assistant about themselves → USER; external facts → WORLD"). Unknown branches default to USER. The DO-NOT-EXTRACT block hardens four recurring traps: (1) assistant-generated recommendations (would-a-different-assistant-give-the-same-answer? heuristic separates these from external lookups, which DO count as facts); (2) transient snapshots like the current weather / time of day (described as "moments not facts" so the model stops conflating ephemera with persistent climate / location knowledge); (3) **low-confidence identity or language claims** — never assert who the user is, where a named person is located, or which language the user speaks unless the user stated it plainly (a mistranscribed token is not evidence; a name must not become a place); (4) **transcription artefacts** — STT residue on silence (subtitle credits, channel-subscribe outros, stray filler) is never a fact. A separate **attribution rule** keeps third-party claims sourced ("According to <source>, ...") rather than asserted as bare fact.
- **Write-time hygiene gate (deterministic belt to the prompt's braces)**: after the LLM returns candidate facts and before routing, each fact is dropped if `looks_like_hallucination()` (the shared STT blocklist in [src/jarvis/listening/hallucinations.py](src/jarvis/listening/hallucinations.py)) matches, or if `_looks_like_transient_fact()` detects a live-reading SHAPE (numeric temperature, clock time, or a weather/time word adjacent to a "currently/right now"-style marker). The shapes are data formats, not human-language word lists, so the language-agnostic rule holds (a number + degree sign is a reading in any language). Per-fact, so a mixed batch keeps its legitimate facts — never an all-or-nothing wipe. The drop count is logged.
- **Output**: list of `(branch_id, fact_text)` tuples (surviving the gate) → routed into the tagged branch via branch-pinned descent (no cross-branch contamination).
- **Limits**: `timeout_sec`. Failures → empty list. Temperature 0 — rule-following classification, not creative generation.

## 11. Knowledge Graph Best-Child Picker

- **File**: [src/jarvis/memory/graph_ops.py](src/jarvis/memory/graph_ops.py) — `_llm_pick_best_child()` (~line 167).
- **Trigger**: during graph insertion, per fact, to place it under the best existing category. Background.
- **Model**: uses `picker_model` when passed through from `update_graph_from_dialogue` (daemon resolves it via `resolve_tool_router_model(cfg)` → small model when available). Falls back to `ollama_chat_model` when no small model is configured.
- **Inputs**: fact text + numbered list of candidate child nodes (name + description).
- **System prompt**: inline (~lines 156-161) — answer with number or `NONE`.
- **Output**: child node id or `None` (fact still inserted, just not under an optimal parent).

## 11b. Knowledge Graph Node Merge (rewrite-on-write consolidation)

- **File**: [src/jarvis/memory/graph_ops.py](src/jarvis/memory/graph_ops.py) — `merge_node_data()` (system prompt at `_MERGE_SYSTEM_PROMPT`).
- **Trigger**: **once per (node, flush)** during `update_graph_from_dialogue`. The orchestrator first applies the exact-match dedupe fast-path, then groups the remaining facts by their resolved `node_id` so a 5-fact flush hitting the User node fires one rewrite, not five. Cold-start writes (empty target node) skip straight to plain append. Also invoked with `new_facts=[]` by the `consolidate_all_populated_nodes` maintenance op (powering the memory viewer's 🧹 button) to re-apply current rules to historical data.
- **Model**: same `picker_model` chain as #11 (small router model when configured, falls back to `ollama_chat_model`). Temperature 0 — the task is rule-following classification.
- **Inputs**: existing node `data` + the batch of new facts (zero or more) routed to that node in this flush.
- **System prompt**: defines an ordered rule set — contradiction/reversal drops the old version, near-duplicate phrasings collapse to one, repeated daily activities consolidate into patterns, independent attributes coexist (visible contradictions are NOT silently dropped), common-knowledge facts are pruned. Demands a bare `{"facts": [...]}` JSON object. Parser tries direct `json.loads` first, then a scoped regex (no greedy `\{.*\}`) before giving up.
- **Output**: `MergeResult(success: bool, incorporated_indices: list[int])`. The revised fact list is written back as the node's full `data`; `incorporated_indices` tells the orchestrator which inputs survived as new lines (under NFKC + casefold matching) so consolidated-out facts aren't reported as "newly stored". Subsumes per-flush supersession, near-duplicate dedupe, and ongoing consolidation in a single call. Because the latest prompt rewrites the whole node, updated conventions propagate to old data without a separate migration step. A superseding rewrite also records a change-history row and bumps the node `version` — an additive side-write that does not alter the merge's `data` output (see graph.spec.md "Versioning & Change History").
- **Limits**: 20s timeout. **Hallucination guard**: rewrites with more than `len(existing) + len(new) + 2` lines are rejected as runaway output. Fail-open on any error, parse failure, oversized rewrite, or empty rewrite → caller falls back to plain `append_to_node` for each new fact so they still land (a contradiction is recoverable; a silent wipe or hallucinated bloat is not).

## 11c. Knowledge Graph Fact Scrub (review-gated cleanup)

- **File**: [src/jarvis/memory/graph_ops.py](src/jarvis/memory/graph_ops.py) — `_judge_facts()` (called by `scrub_graph_facts()`; system prompt at `_SCRUB_JUDGE_SYSTEM_PROMPT`).
- **Trigger**: **user-triggered only**, never on the write path. `POST /api/graph/scrub-facts` (propose) on the FastAPI control server runs one verdict call per non-empty branch node (User / Directives / World). The mirror op `apply_graph_scrub()` (`?apply=true`) does NOT call the LLM — it just removes the user-confirmed lines.
- **Model**: `ollama_chat_model`. Temperature 0 — rule-following audit.
- **Inputs**: one branch node's `data` split one-fact-per-line, numbered, wrapped in the `<<<BEGIN/END UNTRUSTED WEB EXTRACT>>>` fence so stored facts (prior LLM output) are treated as data, not instructions.
- **System prompt**: `_SCRUB_JUDGE_SYSTEM_PROMPT` — asks for a per-fact `{"fact", "drop": bool, "reason"}` JSON array flagging the same garbage classes the write-time gate guards plus the ones a regex can't catch: transcription artefacts, hallucinations, entity-confusion, low-confidence identity/language, transient-as-fact, generic trivia. "When unsure, KEEP" — a wrongly-dropped fact is lost, a wrongly-kept one is removable next time.
- **Output**: `{"proposals": [{branch, fact, drop, reason}], "applied": False}`. **Proposal only — the graph is never mutated by this call.** Verdicts are matched back to real stored lines via NFKC + casefold folding, so the model cannot propose deleting a fact that was never stored. The local user reviews the proposals; only confirmed deletions reach `apply_graph_scrub()`.
- **Privacy**: the propose response carries raw fact text (it is the local user's review surface). The apply path streams NDJSON **counts only** (`{type, total, processed, removed}` / class-name-only `error`), locked behind a whitelist test, so the streaming UI cannot exfiltrate memory content. Mirrors the diary scrub (#9 sweep) contract.
- **Limits**: `timeout_sec` (30s default). **Fail-open per branch**: a branch whose verdict fails (LLM down, unparseable JSON) contributes no proposals and the walk continues; a scrub that can't get a verdict proposes nothing, never guesses a deletion.

## 12. Task-list Planner (pre-flight decomposition, gates the whole turn)

- **File**: [src/jarvis/reply/planner.py](src/jarvis/reply/planner.py) — `plan_query()`.
- **Trigger**: once per reply, **after the tool router and before memory search**. Skipped when `cfg.planner_enabled = False`, when the query is shorter than `MIN_QUERY_CHARS` (4), or when no model / base URL is available.
- **Model / gating**: resolution chain `planner_model (override) → ollama_chat_model`. The planner tracks the chat model so upgrading the chat model (via setup wizard or config) automatically upgrades plan quality.
- **Inputs**: user query, dialogue context, **router-narrowed** tool catalogue (names + one-line descriptions) — not the full 30+ list. When the carry-over guard from #7 fires, the previous turn's failed tool name is unioned into this catalogue before the planner sees it, so the planner can plan a re-call without `toolSearchTool` round-tripping. **No** memory context — the planner decides *whether* memory is needed.
- **System prompt**: `_PROMPT_TEMPLATE` in `planner.py`. Teaches the `searchMemory topic='...'` directive for prior-conversation lookups, short imperative tool steps, angle-bracket entity placeholders, final synthesis step, same-language output, no numbering.
- **Output**: list of plan steps (max `MAX_STEPS` = 5). Gates memory enrichment (#3 / #4) and augments the tool router (#7 — planner's picks are unioned in, not replacing). Single-step `["Reply to the user."]` plans are the planner's positive "no memory, no tools" signal. An empty list is fail-open — the engine reverts to running #3 unconditionally. Consumed further by the engine to build the `ACTION PLAN:` system-message block and drive the direct-exec loop (#13) for small models.
- **Limits**: `planner_timeout_sec` (6s). Fail-open → `[]`.

## 13. Plan Step Resolver (per direct-exec turn, small models + screen tools)

- **File**: [src/jarvis/reply/planner.py](src/jarvis/reply/planner.py) — `resolve_next_tool_call()`.
- **Trigger**: top of each agentic-loop iteration when the plan from #12 still has unexecuted tool steps AND either (a) `use_text_tools` is True (SMALL models, every step), or (b) the next plan step names a screen-perception tool (`seeScreen`/`readScreen`/`locateOnScreen`, via `step_names_vision_tool`) — forced on **any** model size because a large model trusted to call these natively hallucinates the screen instead of looking. Runs instead of the chat model for that turn. **Fast path skips the LLM entirely** when the step is fully concrete (tool name + `key='value'` args, no `<placeholder>`); the LLM call only fires when entity substitution or key remapping is needed.
- **Model**: same chain as #12.
- **Inputs**: next planned step text, prior tool calls (name + args + result excerpt), per-turn tool schema.
- **System prompt**: `_STEP_RESOLVER_SYSTEM` at [planner.py:300](src/jarvis/reply/planner.py:300). Teaches one-JSON-object output, placeholder substitution from prior results, `null` for synthesis steps.
- **Output**: `(tool_name, arguments)` tuple or `None`. Unknown tool names are rejected via the allow-list guard.
- **Limits**: `planner_timeout_sec`. Fail-open → `None` (engine falls back to the chat-model turn).

## 14. Tool-specific LLM calls

- **Weather** ([src/jarvis/tools/builtin/weather.py](src/jarvis/tools/builtin/weather.py), ~line 60) — `ollama_chat_model`, parses location/time/unit from the query.
- **Nutrition log_meal** ([src/jarvis/tools/builtin/nutrition/log_meal.py](src/jarvis/tools/builtin/nutrition/log_meal.py)) — `ollama_chat_model`. **Extraction** uses its own short `nutrition_extract_timeout_sec` (default 30s), not the 180s chat timeout. **Follow-up coaching** is a SECOND chat call gated by `nutrition_followups_enabled` (default **off**), so a meal log is normally a single fast call.

## 15. Vision Model (describe + grounding fallback)

- **File**: [src/jarvis/llm.py](src/jarvis/llm.py) `call_vision_model()`; called from [src/jarvis/vision/model_client.py](src/jarvis/vision/model_client.py) (`describe` / `locate`), via the vision tools (`seeScreen`, `clickScreen` fallback, etc.).
- **Trigger**: only when `cfg.vision_enabled` and a vision tool runs — `seeScreen`/`observe` always; `locateOnScreen`/`clickScreen` **only as a fallback** when Tesseract word-box locate finds no text label. Read/OCR (`readScreen`) is pure Tesseract, **no LLM call**.
- **Model / gating**: `cfg.vision_model` (default `qwen2.5vl:3b`). Multimodal: a single user message carrying a base64 PNG on `images`, POSTed to `/api/chat`. moondream was rejected in Phase-1 (empty grounding output).
- **Inputs**: one in-memory screenshot (PIL → base64 PNG, never on disk), **downscaled so its longest side ≤ `cfg.vision_max_width` (default 1280)** before encoding — a 2560-wide screen (~2616 prompt tokens) drops to ~700, cutting eval time and VRAM; grounding coordinates are scaled back to the original. OCR/`readScreen` keeps full resolution (Tesseract, no LLM). Plus a fixed English instruction (DESCRIBE_PROMPT or the `bbox_2d` LOCATE prompt). Not user-language matching.
- **Output**: free text — a scene description (consumed by the reply loop to answer "what do you see") or a grounding reply (`{"bbox_2d":[...]}` / `{"x":,"y":}` / prose) parsed to a centre point by `parse_point_or_box`, then converted to absolute desktop coords. On no response (`None`), `observe` returns an explicit `{"status":"unavailable", …}` so the reply LLM says vision is temporarily unavailable instead of confabulating a blank screen.
- **Limits**: `timeout_sec` = `cfg.vision_timeout_sec` (default **20s** — headroom for the cold first call: model load + image eval under VRAM contention, the cause of first-`seeScreen`-returns-blank), `num_ctx` 4096, `keep_alive` = `cfg.vision_keep_alive` (default "5m" so the bursty vision model self-evicts and returns VRAM to the resident chat model). Loaded on-demand. Chat path (`chat_with_messages`/`call_llm_direct`) is untouched.
## 16. Reminder Time-Parser Fallback

- **File**: [src/jarvis/reminders/parser.py](src/jarvis/reminders/parser.py) — `parse_when()` LLM branch (`_llm_fallback`).
- **Trigger**: once per `createReminder` / `snoozeReminder` time parse, **only when the deterministic paths fail**. Recurrence (`every`/`κάθε` → cron) and `dateparser` (EL/EN relative, EN absolute) resolve the common cases with no LLM call; EL absolute times and long-tail phrasings fall through to this.
- **Model / gating**: warm router chain inlined as `tool_router_model → intent_judge_model → ollama_chat_model` (inlined rather than importing `resolve_tool_router_model` to avoid a circular import into the hot-path parser). No model configured → returns None (fails closed).
- **Inputs**: the time phrase fenced as untrusted data; current local time as `RELATIVE_BASE`.
- **System prompt**: inline in `parser.py` — strict single-line output contract.
- **Output**: one line — an ISO-8601 local datetime, a 5-field cron string, or `NONE`. Validated (`datetime.fromisoformat` / `croniter.is_valid`); anything else → None. Consumed by `ReminderStore.create`.
- **Limits**: `reminder_parse_timeout_sec` (8s), `num_ctx: 1024`, `temperature: 0.0`, no thinking. Fails closed — an unresolved time creates no reminder rather than guessing.

## 17. Monthly Diary Consolidation (reuses extractor + merge)

- **File**: [src/jarvis/memory/conversation.py](src/jarvis/memory/conversation.py) — `consolidate_previous_month`, scheduled via `memory/maintenance.py` on the daemon poll loop.
- **Trigger**: monthly (28-day guard, last-run persisted in `job_state`), gated by `memory_monthly_consolidation_enabled` (default on). Targets the previous calendar month.
- **Model / gating**: **no new LLM call** — folds the month's summaries through `update_graph_from_dialogue`, reusing the diary→graph extractor + best-child picker + node merge (contexts #10 / #11 / #11b) with the warm picker chain. Fail-open: a fold error archives a truncated fallback narrative instead.
- **Inputs / Output**: the month's `conversation_summaries` → durable graph facts + one `episodic_archive` row; raw rows then removed (or kept when `memory_archive_delete_raw=False`).
- **Limits**: bounded by the reused extractor/merge timeouts; ≤ once/month, on its own poll-loop tick so it never blocks voice.

---

## Frequency / Size Summary

| # | Context | Per reply | Optional? | Model tier |
|---|---------|-----------|-----------|------------|
| 1 | Main chat loop | 1-8 | No | LARGE |
| 2 | Intent judge | 1 (voice only) | fallback available | SMALL |
| 3 | Memory enrichment extract | 0-1 | gated by planner | SMALL (via router chain) |
| 4 | Memory digest | 0-N | auto by size | SMALL (uses chat model) |
| 5 | Tool-result digest | 0-N | auto by size | SMALL (uses chat model) |
| 6 | Max-turn digest | 0-1 | No | SMALL |
| 7 | Tool router | 1 | always runs; planner picks unioned in | SMALL |
| 8 | Tool searcher | 0-3 | model-initiated | SMALL (reuses #7) |
| 9 | Summariser | ~1/session | No (background) | LARGE |
| 10 | Graph extraction | ~1/session | No (background) | LARGE |
| 11 | Graph best-child | 0-N | No (background) | SMALL (via router chain) |
| 11b | Graph node merge | 0-N (per node, batched) | No (background) | SMALL (via router chain) |
| 11c | Graph fact scrub (propose) | 0-3 (per branch) | user-triggered only | LARGE |
| 12 | Planner (plan_query) | 1 | yes (planner_enabled) | LARGE/SMALL (tracks chat model) |
| 13 | Plan step resolver | 0-N (SMALL only) | auto by size + plan | SMALL (via router chain) |
| 14 | Tool-specific | per-tool | n/a | LARGE |
| 15 | Vision model (describe + grounding) | 0-N (vision tools only) | tool-initiated | LARGE (vision model, on-demand) |
| 16 | Reminder time-parse fallback | 0 (only on ambiguous parse, tool-time) | gated; deterministic-first | SMALL (via router chain) |
| 17 | Monthly consolidation | 0 (reuses #10/#11b, ~once/month) | gated; background | SMALL/LARGE (reuses extractor chain) |

## Size-aware auto switches

Driven by `detect_model_size(model_name) → SMALL (≤7B) | LARGE (8B+)`:

| Feature | SMALL | LARGE |
|---------|-------|-------|
| Memory digest | ON | OFF |
| Tool-result digest | ON | OFF |
| Text-based tool calling | ON | OFF (native) |
| Planner direct-exec | ON | OFF |

## Config keys

- Models: `ollama_chat_model`, `intent_judge_model`, `tool_router_model`
- Flags: `memory_digest_enabled`, `tool_result_digest_enabled`, `llm_thinking_enabled`, `intent_judge_thinking_enabled`, `tool_selection_strategy`
- Timeouts: `llm_chat_timeout_sec` (180s), `llm_digest_timeout_sec` (8s, shared across #4/#5/#6), `llm_tools_timeout_sec`, `intent_judge_timeout_sec` (15s)
- Caps: `agentic_max_turns` (8), `tool_search_max_calls` (3), `_LLM_MAX_SELECTED` (5), `_DIGEST_MAX_CHARS` (400), `_TOOL_DIGEST_MAX_CHARS` (600), `llm_chat_max_tokens` (512), `memory_injection_max_turns` (4)

## Flow

```
user input
  └─▶ [2b] Fused Intent Engine    (LIVE DEFAULT, voice only, SMALL — one call)
  │     └─▶ replaces [2]+[7]+[12]; reply engine consumes fused tools/plan
  │           └─▶ AGENTIC LOOP (skips the legacy router+planner below)
  └─▶ (fused disabled / parse fail / non-voice) legacy 3-call path:
      [2] Intent Judge            (voice only, SMALL)
        └─▶ [7] Tool router (narrows catalogue for the planner)
              └─▶ [12] Planner (gates memory; advisory for the router allow-list)
                    ├─ plan requests searchMemory  → [3] Enrichment extract → [4] Memory digest (optional)
                    ├─ plan empty (fail-open)      → [3] Enrichment extract → [4] Memory digest
                    └─ plan reply-only             → skip #3 and #4 entirely
                    └─▶ AGENTIC LOOP  (≤ agentic_max_turns)
                                      ├─ [13] Plan step resolver (SMALL, direct-exec)
                                      ├─ [1] Main chat turn
                                      ├─ tool execution
                                      │    └─ [5] Tool-result digest (optional)
                                      │    └─ [8] Tool searcher (model-initiated)
                                      └─ content → deliver immediately
                                      └─ if max turns → [6] Max-turn digest
                          └─▶ TTS / output
                          └─▶ background: [9] summariser → [10] graph extract → [11] best-child
```

## Optimisation ideas (seed list)

1. Batch multi-chunk memory digests (#4) into a single call with explicit markers.
2. Parallelise multiple tool-result digests (#5) when several results land at once.
3. Pre-warm the intent-judge model before TTS finishes.
4. Cache tool-router (#7) output by query hash.
5. Give each digest its own timeout budget rather than sharing `llm_digest_timeout_sec` (today a slow memory digest can starve the max-turn digest).
6. Consider single-model deployments: router+planner prefer `intent_judge_model`; loading a second model hurts cold-start latency on small hardware.
7. Narrow `llm_thinking_enabled` to router/planner only, not every context.
8. Reduce `intent_judge_timeout_sec` (15s) or race it against text-based wake detection to avoid blocking the audio loop.

---

## Measuring

`tests/performance/test_pipeline_timings.py` times each context in this graph against a live Ollama. Run:

```
pytest tests/performance/ -v -m performance -s
```

It records per-context p50/p95 latencies using a monkey-patch recorder that infers the context from the caller's `__qualname__` (see `_CALLER_TO_CONTEXT` in `tests/performance/timing_recorder.py`). Dumps a JSON report to `tests/performance/reports/`. A micro-benchmark with a tiny fixed prompt runs alongside to give a per-call floor — if that floor moves, every context's total moves with it, so hardware/model drift is visible immediately.

Baseline on a local gemma4:e2b (as of 2026-04-22, 3 queries × 3 runs): main chat turn p50 ~4.5s, enrichment extract p50 ~0.9s (small-model chain), micro-prompt floor ~0.15s. Sample sizes: main 25 calls, enrichment 9. Use these as rough reference points — the assertions in the test are relative-shape (router ≤ 1.5× main chat turn), not absolute.

When you add or change a context, update `_CALLER_TO_CONTEXT` so it shows up in the report instead of landing in the `other:` bucket.

## Keep this doc in sync

This graph is the reference for LLM-latency optimisation. Treat it as authoritative: whenever code changes affect an LLM call — a new context, a removed one, a changed model/timeout/cap/gating/prompt source, or a new data-flow edge — update this file in the same PR. If the update would be more than a one-line tweak, reflect it in the relevant `*.spec.md` too.
