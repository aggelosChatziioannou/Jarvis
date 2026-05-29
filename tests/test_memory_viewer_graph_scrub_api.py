"""Tests for the review-gated graph-fact scrub HTTP endpoint
(`/api/graph/scrub-facts`) on the FastAPI control server.

Mirrors ``tests/test_memory_viewer_diary_scrub_api.py``. The contract:
1. the ``propose`` path returns per-fact deletion proposals (raw fact text
   is allowed here — it is the response the LOCAL user reviews);
2. the ``apply`` path removes only the approved facts and STREAMS NDJSON
   counts only — the streaming progress channel must never echo raw fact
   text, exactly like the diary scrub, so it cannot become a
   data-exfiltration channel;
3. nothing is mutated by ``propose`` — the scrub is review-gated.

Tests stub ``scrub_graph_facts`` / ``apply_graph_scrub`` and the store/
settings resolution so they stay deterministic and offline.
"""

from __future__ import annotations

import json

import pytest

try:
    import fastapi  # noqa: F401
    from fastapi.testclient import TestClient  # noqa: F401

    _HAS_FASTAPI = True
except Exception:  # pragma: no cover - import guard
    _HAS_FASTAPI = False


# Sentinel raw fact text unique to the seeded graph — used to prove the
# apply stream never echoes memory content.
_SECRET_FACT = "The user speaks Welsh"
_SECRET_BRANCH = "user"


@pytest.mark.unit
@pytest.mark.skipif(not _HAS_FASTAPI, reason="FastAPI not available")
class TestGraphScrubEndpoint:
    @pytest.fixture(autouse=True)
    def setup_app(self, monkeypatch):
        from fastapi.testclient import TestClient

        from jarvis import api_server
        import jarvis.memory.graph_ops as go

        # A fake store the endpoint will resolve instead of opening the
        # live SQLite graph. The endpoint only needs get_node/update_node
        # for the real ops, but here we stub the ops themselves, so the
        # store is just a sentinel object.
        class _FakeStore:
            pass

        fake_store = _FakeStore()

        # Stub settings so the endpoint has a chat model + base url without
        # touching the user's real config.
        class _FakeSettings:
            ollama_base_url = "http://x"
            ollama_chat_model = "gemma4:e2b"
            db_path = ":memory:"

        monkeypatch.setattr(api_server, "_resolve_graph_store", lambda: fake_store)
        monkeypatch.setattr(api_server, "_load_settings_safe", lambda: _FakeSettings())

        # Deterministic propose: one keep, one drop — drop carries a reason.
        def fake_scrub(store, base_url, chat_model, timeout_sec=30.0):
            assert store is fake_store
            return {
                "proposals": [
                    {
                        "branch": _SECRET_BRANCH,
                        "fact": "The user lives in Ioannina",
                        "drop": False,
                        "reason": "",
                    },
                    {
                        "branch": _SECRET_BRANCH,
                        "fact": _SECRET_FACT,
                        "drop": True,
                        "reason": "transcription artefact",
                    },
                ],
                "applied": False,
            }

        # Deterministic apply: report the count only.
        def fake_apply(store, approved):
            assert store is fake_store
            return {"removed": len(approved)}

        monkeypatch.setattr(go, "scrub_graph_facts", fake_scrub)
        monkeypatch.setattr(go, "apply_graph_scrub", fake_apply)

        self.client = TestClient(api_server.app)
        yield

    # ── propose path ──────────────────────────────────────────────────

    def _propose(self) -> dict:
        resp = self.client.post("/api/graph/scrub-facts")
        assert resp.status_code == 200
        return resp.json()

    def test_propose_returns_proposals_with_reasons(self):
        body = self._propose()
        assert body["applied"] is False
        drops = [p for p in body["proposals"] if p["drop"]]
        assert any(p["fact"] == _SECRET_FACT for p in drops)
        assert all("reason" in p and "branch" in p for p in body["proposals"])

    def test_propose_does_not_apply(self):
        """The propose response must be explicitly un-applied — review-gated."""
        body = self._propose()
        assert body["applied"] is False

    # ── apply path ────────────────────────────────────────────────────

    def _apply_stream(self, approved: list[dict]) -> list[dict]:
        resp = self.client.post(
            "/api/graph/scrub-facts",
            params={"apply": "true"},
            json={"approved": approved},
        )
        assert resp.status_code == 200
        events = []
        for line in resp.text.splitlines():
            if not line.strip():
                continue
            events.append(json.loads(line))
        return events

    def test_apply_streams_start_then_complete(self):
        events = self._apply_stream(
            [{"branch": _SECRET_BRANCH, "fact": _SECRET_FACT}]
        )
        types = [e["type"] for e in events]
        assert types[0] == "start"
        assert types[-1] == "complete"

    def test_apply_complete_reports_removed_count(self):
        events = self._apply_stream(
            [{"branch": _SECRET_BRANCH, "fact": _SECRET_FACT}]
        )
        complete = events[-1]
        assert complete["type"] == "complete"
        assert complete["removed"] == 1

    def test_apply_stream_never_includes_raw_fact_text(self):
        """Privacy contract: the apply stream must not echo memory content
        into the browser. Only counts and booleans are allowed.
        """
        events = self._apply_stream(
            [{"branch": _SECRET_BRANCH, "fact": _SECRET_FACT}]
        )
        forbidden = ["welsh", "ioannina", "transcription artefact"]
        for ev in events:
            blob = json.dumps(ev).lower()
            for needle in forbidden:
                assert needle not in blob, (
                    f"graph content {needle!r} leaked into apply event {ev}"
                )

    def test_apply_event_keys_are_a_known_whitelist(self):
        """Defence-in-depth for the privacy contract: lock down the *shape*
        of streamed apply events. Any future field that could carry fact
        text must trip this test, forcing a deliberate review.
        """
        events = self._apply_stream(
            [{"branch": _SECRET_BRANCH, "fact": _SECRET_FACT}]
        )
        allowed = {
            "type",
            "total",
            "processed",
            "removed",
            "message",
        }
        for ev in events:
            unknown = set(ev.keys()) - allowed
            assert not unknown, (
                f"unexpected scrub-apply event keys leaked through the "
                f"privacy contract: {unknown}. Add to whitelist "
                f"deliberately, never by accident — any new field is a "
                f"potential data-exfiltration channel through the streaming UI."
            )

    def test_apply_empty_approved_list_removes_nothing(self):
        events = self._apply_stream([])
        complete = events[-1]
        assert complete["type"] == "complete"
        assert complete["removed"] == 0
