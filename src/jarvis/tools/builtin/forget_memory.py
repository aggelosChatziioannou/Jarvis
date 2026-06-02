"""forgetMemory tool: let the user delete/correct a stored memory by voice.

Safety model mirrors the vision engine (propose -> confirm): calling
``forgetMemory`` with a subject PROPOSES a deletion (lists the matching facts,
deletes nothing) and stashes them as a pending proposal. Only a follow-up call
with ``confirm: true`` actually removes them. This means a single misheard
"forget ..." can never wipe memory on its own — the user must agree first.

Tools return raw data; the unified system prompt phrases the confirmation
question and the final acknowledgement.
"""
from __future__ import annotations

import threading
import time
import re
from typing import Any, Dict, List, Optional, Tuple

from ...debug import debug_log
from ..base import Tool, ToolContext
from ..types import ToolExecutionResult


# Process-wide pending proposal (single local user, like the vision engine's
# pending-action buffer). Guarded by a lock for thread safety.
_pending_lock = threading.Lock()
_pending: Dict[str, Any] = {"subject": "", "matches": [], "at": 0.0}

# A pending proposal older than this is considered stale and won't be confirmed
# (the user moved on). Keeps a forgotten "yes" from acting much later.
_PENDING_TTL_SEC = 120.0

_TOKEN_RE = re.compile(r"\w{3,}", re.UNICODE)


def _reset_pending() -> None:
    """Test/utility helper: clear the pending proposal."""
    with _pending_lock:
        _pending["subject"] = ""
        _pending["matches"] = []
        _pending["at"] = 0.0


def has_fresh_pending() -> bool:
    """True if a forgetMemory proposal is awaiting confirmation (not expired).

    The reply engine uses this to keep ``forgetMemory`` in the allow-list on
    the turn AFTER a proposal, so the user's assent ("yes, delete it") is
    honoured even when the upstream router misclassifies the confirmation turn
    as a different tool (e.g. a diet-related "yes, remove that" can route to
    ``deleteMeal``). Safe: the tool only ever deletes a fresh pending proposal,
    and refusals are not routed to a deletion tool, so merely keeping the tool
    available cannot cause an unwanted delete."""
    with _pending_lock:
        matches = _pending.get("matches") or []
        at = float(_pending.get("at") or 0.0)
    return bool(matches) and (time.monotonic() - at) <= _PENDING_TTL_SEC


def _tokens(text: str) -> set:
    return set(_TOKEN_RE.findall(text))


def _embed_text(text: str, base_url: str, model: str, timeout_sec: float = 10.0):
    """Embed ``text`` for semantic recall. Fail-open: returns None on any
    error or missing config, so a transient embed failure can never raise and
    can never widen the deletion set. Module-level so tests can stub it."""
    if not base_url or not model:
        return None
    try:
        from ...memory.embeddings import get_embedding
        return get_embedding(text, base_url, model, timeout_sec=timeout_sec)
    except Exception:  # pragma: no cover - defensive
        return None


def _match_lines(
    store,
    subject: str,
    *,
    base_url: str = "",
    embed_model: str = "",
    threshold: float = 0.0,
) -> List[Tuple[str, str]]:
    """Find ``(node_id, line)`` pairs whose fact line matches ``subject``.

    Two-stage, language-agnostic, over-deletion-safe:

    1. STRICT (always, free): the normalised subject is a substring of the
       normalised line, OR every significant subject token (Unicode word,
       len>=3) appears in the line.
    2. SEMANTIC fallback (only when strict finds NOTHING, and only when an
       embed model + positive threshold are configured): include any line
       whose embedding cosine-similarity to the subject is >= ``threshold``.
       This catches paraphrases the strict pass misses ("resides in London"
       vs the stored "the user lives in London"). Fail-open: any embedding
       that can't be computed contributes no match.

    The semantic pass only widens the PROPOSE candidate set — it never
    deletes. propose->confirm (the user vetoes a wrong candidate before
    anything is removed) stays the only path to deletion, so looser recall
    cannot cause over-deletion.
    """
    from ...memory.graph import normalise_fact

    subj_norm = normalise_fact(subject)
    if not subj_norm:
        return []
    subj_tokens = _tokens(subj_norm)

    # Gather candidate lines once; reused by both passes.
    candidates: List[Tuple[str, str, str]] = []  # (node_id, raw_line, norm_line)
    for node in store.get_all_nodes():
        if not node.data:
            continue
        for line in node.data.split("\n"):
            ln = line.strip()
            if not ln:
                continue
            candidates.append((node.id, ln, normalise_fact(ln)))

    # 1) Strict pass.
    out: List[Tuple[str, str]] = []
    for node_id, ln, ln_norm in candidates:
        ln_tokens = _tokens(ln_norm)
        if (subj_norm in ln_norm) or (subj_tokens and subj_tokens.issubset(ln_tokens)):
            out.append((node_id, ln))
    if out:
        return out

    # 2) Semantic fallback — only when strict matched nothing.
    if not (base_url and embed_model and threshold and threshold > 0.0):
        return out
    from ...memory.embeddings import cosine_similarity

    subj_vec = _embed_text(subject, base_url, embed_model)
    if not subj_vec:
        return out
    for node_id, ln, _ln_norm in candidates:
        line_vec = _embed_text(ln, base_url, embed_model)
        if not line_vec:
            continue
        if cosine_similarity(subj_vec, line_vec) >= threshold:
            out.append((node_id, ln))
    return out


def _delete_lines(store, matches: List[Tuple[str, str]]) -> int:
    """Remove the given fact lines from their nodes. Returns lines removed."""
    from ...memory.graph import normalise_fact

    by_node: Dict[str, set] = {}
    for node_id, line in matches:
        by_node.setdefault(node_id, set()).add(normalise_fact(line))

    removed = 0
    for node_id, targets in by_node.items():
        node = store.get_node(node_id)
        if node is None or not node.data:
            continue
        kept: List[str] = []
        for line in node.data.split("\n"):
            if normalise_fact(line) in targets:
                removed += 1
                continue
            kept.append(line)
        store.update_node(node_id, data="\n".join(kept))
    return removed


class ForgetMemoryTool(Tool):
    @property
    def name(self) -> str:
        return "forgetMemory"

    @property
    def description(self) -> str:
        return (
            "Delete or correct something Jarvis has remembered about the user, when "
            "they ask to forget it (in ANY language), e.g. 'forget that I live in London' "
            "or 'I never said that'. SAFETY: call this FIRST with only `subject` (what to "
            "forget) — it returns the matching stored facts and deletes NOTHING. Tell the "
            "user what would be removed and, ONLY once they clearly agree, call it again "
            "with `confirm: true` to actually delete the pending facts. Never set "
            "confirm:true before the user has agreed."
        )

    @property
    def inputSchema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "subject": {
                    "type": "string",
                    "description": "What to forget, e.g. 'lives in London' or 'my phone number'.",
                },
                "confirm": {
                    "type": "boolean",
                    "description": "Set true ONLY after the user has agreed, to delete the pending facts.",
                },
            },
        }

    @staticmethod
    def _resolve_subject(args: Dict[str, Any], context: ToolContext) -> str:
        """Best-effort subject. The fused router emits unreliable argument
        names ('memory', 'memory_to_delete') and sometimes a hallucinated
        value, so the explicit ``subject`` arg is trusted only when present,
        then we fall back to the user's own utterance (the reliable source),
        then to any other string arg as a last resort."""
        subj = str(args.get("subject") or "").strip()
        if subj:
            return subj
        red = (getattr(context, "redacted_text", "") or "").strip()
        if red:
            return red
        for v in args.values():
            if isinstance(v, str) and v.strip():
                return v.strip()
        return ""

    @staticmethod
    def _fresh_pending() -> Tuple[str, List[Tuple[str, str]]]:
        """Return (subject, matches) of a non-expired pending proposal, else ('', [])."""
        with _pending_lock:
            pending_subject = _pending.get("subject") or ""
            pending_matches = list(_pending.get("matches") or [])
            pending_at = float(_pending.get("at") or 0.0)
        if pending_matches and (time.monotonic() - pending_at) <= _PENDING_TTL_SEC:
            return pending_subject, pending_matches
        return "", []

    def _confirm(self, store, pending_matches, context: ToolContext) -> ToolExecutionResult:
        removed = _delete_lines(store, pending_matches)
        _reset_pending()
        debug_log(f"forgetMemory: confirmed deletion of {removed} fact line(s)", "memory")
        if removed:
            context.user_print("🗑️ Forgotten.")
            forgotten = "; ".join(line for _id, line in pending_matches)
            return ToolExecutionResult(
                success=True,
                reply_text=f"removed: Deleted from memory: {forgotten}",
            )
        return ToolExecutionResult(
            success=True,
            reply_text="removed: Those facts were already gone from memory.",
        )

    def run(self, args: Optional[Dict[str, Any]], context: ToolContext) -> ToolExecutionResult:
        args = args if isinstance(args, dict) else {}
        confirm = bool(args.get("confirm"))
        subject = self._resolve_subject(args, context)

        from ...memory.graph import GraphMemoryStore, normalise_fact
        store = GraphMemoryStore(context.cfg.db_path)
        try:
            pending_subject, pending_matches = self._fresh_pending()

            # ---- A fresh proposal is awaiting the user's decision ----
            # The engine force-executes forgetMemory, so reaching it again while
            # a proposal is pending means the upstream router classified this
            # turn as forget-related. Refusals ("no, keep it") are NOT routed
            # here, so this is genuine assent — UNLESS the user named a
            # *different* stored fact, in which case we propose that instead.
            if pending_matches:
                if not confirm and subject:
                    base_url = str(getattr(context.cfg, "ollama_base_url", "") or "")
                    embed_model = str(getattr(context.cfg, "ollama_embed_model", "") or "")
                    try:
                        threshold = float(getattr(context.cfg, "memory_forget_semantic_threshold", 0.82) or 0.82)
                    except (TypeError, ValueError):
                        threshold = 0.82
                    new_matches = _match_lines(
                        store, subject,
                        base_url=base_url, embed_model=embed_model, threshold=threshold,
                    )
                    pending_norm = {normalise_fact(l) for _id, l in pending_matches}
                    new_norm = {normalise_fact(l) for _id, l in new_matches}
                    if new_matches and not new_norm.issubset(pending_norm):
                        # User pivoted to a different stored fact — propose it.
                        debug_log("forgetMemory: pending superseded by a new distinct subject", "memory")
                        return self._propose(store, subject, context)
                # Assent (or explicit confirm) — delete the pending proposal.
                return self._confirm(store, pending_matches, context)

            # ---- No pending proposal: PROPOSE (deletes nothing) ----
            # A premature confirm=true on the very first call has no fresh
            # pending to act on, so it safely falls through to a proposal.
            return self._propose(store, subject, context)
        finally:
            store.close()

    def _propose(self, store, subject: str, context: ToolContext) -> ToolExecutionResult:
        if not subject:
            return ToolExecutionResult(
                success=False,
                reply_text="Tell me what you'd like me to forget.",
            )
        cfg = getattr(context, "cfg", None)
        base_url = str(getattr(cfg, "ollama_base_url", "") or "")
        embed_model = str(getattr(cfg, "ollama_embed_model", "") or "")
        try:
            threshold = float(getattr(cfg, "memory_forget_semantic_threshold", 0.82) or 0.82)
        except (TypeError, ValueError):
            threshold = 0.82
        matches = _match_lines(
            store, subject,
            base_url=base_url, embed_model=embed_model, threshold=threshold,
        )
        if not matches:
            _reset_pending()
            # `no_match:` is a protocol discriminator (mirrors `requires_confirmation:`
            # below) so the persona model cannot narrate a zero-match search as a
            # successful deletion. Tools return raw data; the prompt phrases it.
            return ToolExecutionResult(
                success=True,
                reply_text=(
                    f"no_match: Nothing in memory matches '{subject}'. Tell the user you "
                    f"searched and found nothing to forget; do NOT say anything was "
                    f"deleted, removed, or forgotten."
                ),
            )
        with _pending_lock:
            _pending["subject"] = subject
            _pending["matches"] = matches
            _pending["at"] = time.monotonic()
        listing = "; ".join(line for _id, line in matches)
        context.user_print("🤔 Found matching memories — awaiting confirmation.")
        debug_log(f"forgetMemory: proposing deletion of {len(matches)} line(s)", "memory")
        return ToolExecutionResult(
            success=True,
            reply_text=(
                f"requires_confirmation: I have these stored — {listing}. "
                f"Ask the user to confirm before deleting; on agreement call forgetMemory with confirm:true."
            ),
        )
