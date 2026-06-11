"""Behavioural tests for the window-manager and stock-price tools (pure logic)."""

import pytest

from jarvis.tools.builtin.window_manager import (
    compute_target_rect, pick_monitor, pick_window, score_window_match,
)
from jarvis.tools.builtin.stock_prices import classify_symbol


class TestWindowMatching:
    WINDOWS = [
        {"title": "Inbox — Gmail", "process": "chrome.exe"},
        {"title": "Spotify Premium", "process": "Spotify.exe"},
        {"title": "main.py - Jarvis-src - Visual Studio Code", "process": "Code.exe"},
    ]

    def test_process_name_beats_title(self):
        # "chrome" matches the browser even though no title says chrome.
        assert pick_window(self.WINDOWS, "chrome")["process"] == "chrome.exe"

    def test_app_name_case_insensitive(self):
        assert pick_window(self.WINDOWS, "SPOTIFY")["process"] == "Spotify.exe"

    def test_title_words_match_any_order(self):
        assert pick_window(self.WINDOWS, "visual code")["process"] == "Code.exe"

    def test_no_match_returns_none(self):
        assert pick_window(self.WINDOWS, "blender") is None
        assert pick_window(self.WINDOWS, "") is None

    def test_exact_process_outranks_substring_title(self):
        windows = [
            {"title": "How to install Spotify - Chrome", "process": "chrome.exe"},
            {"title": "", "process": "spotify.exe"},
        ]
        assert score_window_match("spotify", windows[1]["title"], windows[1]["process"]) > \
            score_window_match("spotify", windows[0]["title"], windows[0]["process"])


class TestSnapGeometry:
    WORK = {"x": 100, "y": 50, "width": 1000, "height": 800}

    def test_halves_tile_the_work_area_exactly(self):
        left = compute_target_rect(self.WORK, "left-half")
        right = compute_target_rect(self.WORK, "right-half")
        assert left["x"] == 100 and left["width"] == 500
        assert right["x"] == 600 and right["width"] == 500
        assert left["width"] + right["width"] == self.WORK["width"]

    def test_full_covers_work_area(self):
        assert compute_target_rect(self.WORK, "full") == {"x": 100, "y": 50, "width": 1000, "height": 800}

    def test_odd_widths_do_not_lose_a_pixel(self):
        work = {"x": 0, "y": 0, "width": 1001, "height": 9}
        left = compute_target_rect(work, "left-half")
        right = compute_target_rect(work, "right-half")
        assert left["width"] + right["width"] == 1001


class TestMonitorPick:
    MONITORS = [
        {"index": 0, "x": 1920, "y": 0, "width": 1920, "height": 1040, "primary": True},
        {"index": 1, "x": 0, "y": 0, "width": 1920, "height": 1040, "primary": False},
    ]

    def test_left_right_follow_virtual_x_not_index(self):
        assert pick_monitor(self.MONITORS, "left")["x"] == 0
        assert pick_monitor(self.MONITORS, "right")["x"] == 1920

    def test_primary_and_current(self):
        assert pick_monitor(self.MONITORS, "primary")["primary"] is True
        assert pick_monitor(self.MONITORS, "current", current_index=1)["index"] == 1

    def test_numeric_choice_is_one_based_left_to_right(self):
        assert pick_monitor(self.MONITORS, "1")["x"] == 0
        assert pick_monitor(self.MONITORS, "2")["x"] == 1920


class TestSymbolClassification:
    @pytest.mark.parametrize("spoken,kind,ticker", [
        ("NVDA", "stock", "NVDA"),
        ("aapl", "stock", "AAPL"),
        ("bitcoin", "crypto", "btcusd"),
        ("BTC", "crypto", "btcusd"),
        ("gold", "fx", "xauusd"),
        ("XAUUSD", "fx", "xauusd"),
        ("eurusd", "fx", "eurusd"),
        ("solusd", "crypto", "solusd"),
    ])
    def test_known_assets_route_to_the_right_endpoint(self, spoken, kind, ticker):
        assert classify_symbol(spoken) == (kind, ticker)

    def test_unknown_defaults_to_stock_ticker(self):
        assert classify_symbol("plt r") == ("stock", "PLT R")
        assert classify_symbol("") == ("stock", "")


class TestRegistryWiring:
    def test_new_tools_are_registered_with_real_names(self):
        from jarvis.tools.registry import BUILTIN_TOOLS
        for name in ("listOpenWindows", "manageWindow", "getStockPrice"):
            assert name in BUILTIN_TOOLS
            tool = BUILTIN_TOOLS[name]
            assert tool.name == name
            assert tool.description
            assert tool.inputSchema["type"] == "object"


class TestTransientWindowPenalty:
    def test_real_window_beats_installer_splash(self):
        windows = [
            {"title": "Spotify Installer", "process": "Spotify.exe"},
            {"title": "Spotify Premium", "process": "Spotify.exe"},
        ]
        assert pick_window(windows, "spotify")["title"] == "Spotify Premium"

    def test_installer_still_matches_when_alone(self):
        windows = [{"title": "Spotify Installer", "process": "Spotify.exe"}]
        assert pick_window(windows, "spotify") is not None


class TestLastManagedFallback:
    """Pronoun follow-ups name no app. Live failure: «βάλε ΤΟ στην αριστερή
    οθόνη full screen» right after Jarvis moved Spotify — the router emitted
    action/monitor/position but no `window`, and the tool failed the call
    over a field the conversation had already established."""

    def test_missing_window_uses_last_managed(self):
        from jarvis.tools.builtin.window_manager import effective_window_query
        assert effective_window_query({"action": "move"}, "spotify") == "spotify"

    def test_explicit_window_wins_over_history(self):
        from jarvis.tools.builtin.window_manager import effective_window_query
        assert effective_window_query({"window": "chrome"}, "spotify") == "chrome"

    def test_second_window_beats_history(self):
        from jarvis.tools.builtin.window_manager import effective_window_query
        assert effective_window_query({"second_window": "chrome"}, "spotify") == "chrome"

    def test_no_window_no_history_is_empty(self):
        from jarvis.tools.builtin.window_manager import effective_window_query
        assert effective_window_query({"action": "move"}, None) == ""

    def test_error_names_only_the_missing_fields(self, monkeypatch):
        from jarvis.tools.builtin import window_manager as wm
        monkeypatch.setattr(wm, "_LAST_MANAGED_QUERY", None)
        res = wm.ManageWindowTool().run({"action": "move"}, None)
        assert res.success is False
        assert "window" in res.error_message
        assert "action" not in res.error_message
