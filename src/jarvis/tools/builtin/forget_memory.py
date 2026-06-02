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


def _tokens(text: str) -> set:
    return set(_TOKEN_RE.findall(text))


def _match_lines(store, subject: str) -> List[Tuple[str, str]]:
    """Find ``(node_id, line)`` pairs whose fact line matches ``subject``.

    Strict, language-agnostic matching to avoid over-deletion: a line matches
    only if the normalised subject is a substring of the normalised line, OR
    every significant subject token (Unicode word, len>=3) appears in the line.
    """
    from ...memory.graph import normalise_fact

    subj_norm = normalise_fact(subject)
    if not subj_norm:
        return []
    subj_tokens = _tokens(subj_norm)
    out: List[Tuple[str, str]] = []
    for node in store.get_all_nodes():
        if not node.data:
            continue
        for line in node.data.split("\n"):
            ln = line.strip()
            if not ln:
                continue
            ln_norm = normalise_fact(ln)
            ln_tokens = _tokens(ln_norm)
            if (subj_norm in ln_norm) or (subj_tokens and subj_tokens.issubset(ln_tokens)):
                out.append((node.id, ln))
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

    def run(self, args: Optional[Dict[str, Any]], context: ToolContext) -> ToolExecutionResult:
        args = args if isinstance(args, dict) else {}
        confirm = bool(args.get("confirm"))
        subject = str(args.get("subject") or "").strip()

        from ...memory.graph import GraphMemoryStore
        store = GraphMemoryStore(context.cfg.db_path)
        try:
            # ---- CONFIRM: act only on a fresh pending proposal ----
            if confirm:
                with _pending_lock:
                    pending_subject = _pending.get("subject") or ""
                    pending_matches = list(_pending.get("matches") or [])
                    pending_at = float(_pending.get("at") or 0.0)
                fresh = pending_matches and (time.monotonic() - pending_at) <= _PENDING_TTL_SEC
                if not fresh:
                    # No agreed-upon proposal to act on — fail safe by proposing
                    # instead of deleting (forces the confirm-first flow).
                    debug_log("forgetMemory: confirm with no fresh pending — proposing instead", "memory")
                    return self._propose(store, subject or pending_subject, context)
                removed = _delete_lines(store, pending_matches)
                _reset_pending()
                debug_log(f"forgetMemory: confirmed deletion of {removed} fact line(s)", "memory")
                if removed:
                    context.user_print("🗑️ Forgotten.")
                    forgotten = "; ".join(line for _id, line in pending_matches)
                    return ToolExecutionResult(
                        success=True,
                        reply_text=f"Removed from memory: {forgotten}",
                    )
                return ToolExecutionResult(
                    success=True,
                    reply_text="Those facts were already gone from memory.",
                )

            # ---- PROPOSE: find candidates, stash, delete nothing ----
            return self._propose(store, subject, context)
        finally:
            store.close()

    def _propose(self, store, subject: str, context: ToolContext) -> ToolExecutionResult:
        if not subject:
            return ToolExecutionResult(
                success=False,
                reply_text="Tell me what you'd like me to forget.",
            )
        matches = _match_lines(store, subject)
        if not matches:
            _reset_pending()
            return ToolExecutionResult(
                success=True,
                reply_text=f"I don't have anything stored about '{subject}'.",
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
