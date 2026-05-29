"""Periodic memory-maintenance jobs, scheduled on the daemon poll loop.

No APScheduler: cadences are tracked via persisted last-run timestamps in the
``job_state`` table, so they survive restarts and never double-run within an
interval. Every job is fail-open — a failure is logged, last-run is NOT advanced
(so it retries next tick), and it never propagates to crash the voice pipeline.

The scheduler logic lives here (not in ``daemon.py``) so it is unit-testable
without importing the daemon. ``daemon.main()`` just calls
``run_periodic_memory_jobs`` on an hourly throttle.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable, List, Optional, Tuple

from ..debug import debug_log


def run_due_jobs(db, cfg, jobs: List[Tuple[str, timedelta, Callable]], now: Optional[datetime] = None) -> List[str]:
    """Run each due job and persist its last-run. Returns the names that ran.

    ``jobs`` is a list of ``(name, interval, fn)`` where ``fn(db, cfg)`` does the
    work. A job is due when it has never run or its interval has elapsed. Each
    job is independently fail-open.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    ran: List[str] = []
    for name, interval, fn in jobs:
        try:
            last = db.get_job_last_run(name)
            if last is not None:
                if (now - datetime.fromisoformat(last)) < interval:
                    continue
            debug_log(f"memory job '{name}': running", "memory")
            fn(db, cfg)
            db.set_job_last_run(name, now.isoformat())
            ran.append(name)
            debug_log(f"memory job '{name}': done", "memory")
        except Exception as exc:
            # Fail-open: do NOT advance last_run, so the job retries next tick.
            debug_log(f"memory job '{name}' failed (non-fatal): {type(exc).__name__}: {exc}", "memory")
    return ran


def run_periodic_memory_jobs(db, cfg, now: Optional[datetime] = None) -> List[str]:
    """Assemble the enabled lifecycle jobs and run any that are due."""
    jobs: List[Tuple[str, timedelta, Callable]] = []
    if getattr(cfg, "memory_ttl_enabled", False):
        jobs.append(("ttl_daily", timedelta(days=1), _job_ttl_purge))
    if getattr(cfg, "memory_weekly_prune_enabled", True):
        jobs.append(("prune_weekly", timedelta(days=7), _job_prune))
    if getattr(cfg, "memory_monthly_consolidation_enabled", True):
        jobs.append(("consolidate_monthly", timedelta(days=28), _job_consolidate))
    return run_due_jobs(db, cfg, jobs, now=now)


def _open_store(db):
    from .graph import GraphMemoryStore

    store = GraphMemoryStore(db.db_path)
    store.history_sink = db.append_memory_history
    return store


def _job_ttl_purge(db, cfg) -> None:
    store = _open_store(db)
    try:
        store.purge_expired_nodes()
    finally:
        store.close()


def _job_prune(db, cfg) -> None:
    store = _open_store(db)
    try:
        store.prune_low_importance(
            min_age_days=int(getattr(cfg, "memory_weekly_prune_min_age_days", 30))
        )
    finally:
        store.close()


def _job_consolidate(db, cfg) -> None:
    from .conversation import consolidate_previous_month

    store = _open_store(db)
    try:
        consolidate_previous_month(
            db,
            store,
            getattr(cfg, "ollama_base_url", ""),
            getattr(cfg, "ollama_chat_model", ""),
            picker_model=_resolve_picker(cfg),
            delete_raw=bool(getattr(cfg, "memory_archive_delete_raw", True)),
        )
    finally:
        store.close()


def _resolve_picker(cfg) -> Optional[str]:
    # Warm small-model chain, inlined to avoid importing the reply engine here.
    for attr in ("tool_router_model", "intent_judge_model", "ollama_chat_model"):
        value = (getattr(cfg, attr, "") or "").strip()
        if value:
            return value
    return None
