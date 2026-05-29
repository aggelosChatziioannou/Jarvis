"""Behavioural tests for turn/tool-boundary cancellation in the reply engine.

The STOP button and the Wispr barge-in both call the listener's
``reset_everything()`` which sets a ``threading.Event``. Until this wiring,
nothing read that event, so an in-flight reply ran to completion and could
speak after the user had already cancelled.

These tests pin the cancellation CONTRACT at safe boundaries:

  X1a — ``run_reply_engine`` accepts an optional ``cancel_event`` keyword and
        threads it into the agentic loop.
  X1b — when the event is set, the loop stops at a safe boundary and returns
        the no-speak sentinel (the empty string ``""``, which the listener's
        ``if reply and ...`` guard already treats as "do NOT speak").

Two boundaries are covered:
  (a) pre-set BEFORE the engine starts → the chat LLM must never be called;
  (b) set AFTER the first turn → the loop must stop before the second chat
      LLM call.

Omitting ``cancel_event`` must leave behaviour byte-for-byte identical to the
current engine (covered by the existing test suite and by
``test_no_cancel_event_runs_to_completion`` here).
"""

import threading
from unittest.mock import patch


def _assistant_tool_call(name: str, args: dict, call_id: str = "call_1"):
    return {
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": name, "arguments": args},
                }
            ],
        }
    }


def _assistant_content(text: str):
    return {"message": {"role": "assistant", "content": text}}


# ── X1b(a): pre-set event short-circuits before the first chat call ──────────


def test_preset_cancel_event_returns_sentinel_without_calling_chat(
    mock_config, db, dialogue_memory
):
    """When ``cancel_event`` is already set at the top of the first loop turn,
    the engine returns the no-speak sentinel and never invokes the chat LLM."""
    from jarvis.reply import engine as engine_mod

    mock_config.ollama_chat_model = "gpt-oss:20b"  # LARGE → native tools

    chat_calls = {"count": 0}

    def fake_chat(*args, **kwargs):
        chat_calls["count"] += 1
        return _assistant_content("This should never be produced.")

    ev = threading.Event()
    ev.set()  # cancelled before the engine even starts

    with patch.object(engine_mod, "chat_with_messages", side_effect=fake_chat), \
         patch.object(engine_mod, "select_tools", return_value=["stop"]), \
         patch.object(
             engine_mod,
             "extract_search_params_for_memory",
             return_value={"keywords": []},
         ):
        reply = engine_mod.run_reply_engine(
            db=db,
            cfg=mock_config,
            tts=None,
            text="what's the weather?",
            dialogue_memory=dialogue_memory,
            cancel_event=ev,
        )

    assert chat_calls["count"] == 0, (
        "Chat LLM must not be called when cancellation is set before the "
        f"first turn; got {chat_calls['count']} call(s)"
    )
    # No-speak sentinel: an empty string, which the listener's truthiness
    # guard (``if reply and self.tts...``) treats as "do NOT speak".
    assert reply == "", f"Expected the no-speak sentinel ''; got {reply!r}"


# ── X1b(b): event set after first turn stops before the second chat call ─────


def test_cancel_after_first_turn_stops_before_second_chat_call(
    mock_config, db, dialogue_memory
):
    """A tool call on turn 1 sets the event via the tool runner. The loop must
    stop on the next safe boundary and NOT make a second chat LLM call."""
    from jarvis.reply import engine as engine_mod
    from jarvis.tools.types import ToolExecutionResult

    mock_config.ollama_chat_model = "gpt-oss:20b"  # LARGE → native tools

    ev = threading.Event()
    chat_calls = {"count": 0}

    def fake_chat(*args, **kwargs):
        chat_calls["count"] += 1
        # Turn 1: ask for a tool. Any later call would be the second turn,
        # which cancellation must prevent.
        return _assistant_tool_call("getWeather", {"location": "London"})

    def fake_tool_runner(db, cfg, tool_name, tool_args, **kwargs):
        # Simulate a STOP / barge-in arriving while the tool runs.
        ev.set()
        return ToolExecutionResult(
            success=True,
            reply_text="London: 12C partly cloudy.",
            error_message=None,
        )

    with patch.object(engine_mod, "run_tool_with_retries", side_effect=fake_tool_runner), \
         patch.object(engine_mod, "chat_with_messages", side_effect=fake_chat), \
         patch.object(engine_mod, "select_tools", return_value=["getWeather", "stop"]), \
         patch.object(
             engine_mod,
             "extract_search_params_for_memory",
             return_value={"keywords": []},
         ):
        reply = engine_mod.run_reply_engine(
            db=db,
            cfg=mock_config,
            tts=None,
            text="how's the weather in london?",
            dialogue_memory=dialogue_memory,
            cancel_event=ev,
        )

    assert chat_calls["count"] == 1, (
        "Cancellation set during the turn-1 tool call must stop the loop "
        "before the second chat LLM call; expected exactly 1 chat call, got "
        f"{chat_calls['count']}"
    )
    assert reply == "", f"Expected the no-speak sentinel ''; got {reply!r}"


# ── Regression: cancel_event=None preserves existing behaviour ───────────────


def test_no_cancel_event_runs_to_completion(mock_config, db, dialogue_memory):
    """Omitting ``cancel_event`` (or passing None) must not change behaviour:
    the engine produces its normal natural-language reply."""
    from jarvis.reply import engine as engine_mod

    mock_config.ollama_chat_model = "gpt-oss:20b"

    def fake_chat(*args, **kwargs):
        return _assistant_content("It's 12C and partly cloudy in London.")

    with patch.object(engine_mod, "chat_with_messages", side_effect=fake_chat), \
         patch.object(engine_mod, "select_tools", return_value=["stop"]), \
         patch.object(
             engine_mod,
             "extract_search_params_for_memory",
             return_value={"keywords": []},
         ):
        reply = engine_mod.run_reply_engine(
            db=db,
            cfg=mock_config,
            tts=None,
            text="how's the weather in london?",
            dialogue_memory=dialogue_memory,
            cancel_event=None,
        )

    assert reply and "London" in reply, (
        f"With no cancel_event the engine must reply normally; got {reply!r}"
    )


def test_preset_cancel_does_not_speak_via_engine_tts(
    mock_config, db, dialogue_memory
):
    """When cancelled before the first turn, the engine must not speak the
    reply through its own in-engine TTS path either (it returns the sentinel
    before reaching Step 10's tts.speak)."""
    from unittest.mock import MagicMock
    from jarvis.reply import engine as engine_mod

    mock_config.ollama_chat_model = "gpt-oss:20b"

    fake_tts = MagicMock()
    fake_tts.enabled = True

    def fake_chat(*args, **kwargs):
        return _assistant_content("Should never be spoken.")

    ev = threading.Event()
    ev.set()

    with patch.object(engine_mod, "chat_with_messages", side_effect=fake_chat), \
         patch.object(engine_mod, "select_tools", return_value=["stop"]), \
         patch.object(
             engine_mod,
             "extract_search_params_for_memory",
             return_value={"keywords": []},
         ):
        reply = engine_mod.run_reply_engine(
            db=db,
            cfg=mock_config,
            tts=fake_tts,
            text="hello",
            dialogue_memory=dialogue_memory,
            cancel_event=ev,
        )

    assert reply == ""
    fake_tts.speak.assert_not_called()
