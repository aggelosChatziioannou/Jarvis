"""Dashboard endpoints: /api/system/metrics and /api/services/status.

Weather is monkeypatched out (no network); reminders point at a tmp store.
Each metric is best-effort, so we assert structure, not specific hardware values.
"""

import pytest

from src.jarvis import api_server
from src.jarvis.reminders.store import ReminderStore


@pytest.fixture
def no_weather(monkeypatch):
    monkeypatch.setattr(api_server, "_read_weather", lambda: None)


@pytest.fixture
def no_external(monkeypatch):
    """Stub out all network/IMAP calls so service status is deterministic."""
    monkeypatch.setattr(api_server, "_read_weather", lambda: None)
    monkeypatch.setattr(api_server, "_spotify_status", lambda: {
        "id": "spotify", "name": "Spotify", "enabled": True, "connected": False, "active": False, "detail": "not authorised",
    })
    monkeypatch.setattr(api_server, "_gmail_status", lambda: {
        "id": "gmail", "name": "Gmail", "enabled": True, "connected": False, "active": False, "count": 0, "detail": "not configured",
    })


def test_system_metrics_has_expected_shape(no_weather):
    out = api_server.system_metrics()
    assert isinstance(out["uptime_sec"], float)
    assert out["uptime_sec"] >= 0
    for key in ("cpu_percent", "ram", "gpu", "models", "weather"):
        assert key in out
    assert isinstance(out["models"], list)
    assert out["weather"] is None  # monkeypatched


def test_services_status_lists_core_services(tmp_path, monkeypatch, no_external):
    db = str(tmp_path / "r.db")
    monkeypatch.setattr(api_server, "_resolve_reminder_store", lambda: ReminderStore(db))
    out = api_server.services_status()
    by_id = {s["id"]: s for s in out}
    assert {"reminders", "weather", "spotify", "gmail", "calendar"} <= set(by_id)
    assert by_id["reminders"]["count"] == 0  # empty tmp store
    assert by_id["weather"]["connected"] is False  # weather monkeypatched to None


def test_services_status_reminder_count_reflects_store(tmp_path, monkeypatch, no_external):
    from datetime import datetime, timedelta, timezone

    db = str(tmp_path / "r.db")
    store = ReminderStore(db)
    store.create("ping", datetime.now(timezone.utc) + timedelta(hours=1))
    monkeypatch.setattr(api_server, "_resolve_reminder_store", lambda: ReminderStore(db))
    out = api_server.services_status()
    rem = next(s for s in out if s["id"] == "reminders")
    assert rem["count"] == 1
