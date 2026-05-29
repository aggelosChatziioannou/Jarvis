"""Live eval: when a screen tool is offered, the chat model CALLS it instead of
hallucinating screen contents.

Guards the anti-hallucination tool descriptions on seeScreen/readScreen. Field
failure it reproduces: with seeScreen available + planned, qwen3.5:9b answered
"your screen is mostly black…" from imagination without ever calling the tool.
Before the forceful descriptions this fails (no tool call); after, the model
calls the tool and grounds its reply in the result.

Run: EVAL_JUDGE_MODEL=qwen3.5:9b-8k ./scripts/run_evals.sh test_vision_tool
"""

from unittest.mock import patch

import pytest

from conftest import requires_judge_llm
from helpers import (
    JUDGE_MODEL,
    ToolCallCapture,
    _parse_judge_response,
    call_judge_llm,
    create_mock_tool_run,
)


def _is_small(model_name: str) -> bool:
    from jarvis.reply.prompts import detect_model_size, ModelSize
    return detect_model_size(model_name) == ModelSize.SMALL


class TestVisionToolInvocationLive:
    @pytest.mark.eval
    @requires_judge_llm
    @pytest.mark.parametrize("query,tool,fake_result", [
        pytest.param(
            "what do you see on my screen", "seeScreen",
            '{"description":"a dark VS Code editor with a terminal panel showing logs","monitor":"primary"}',
            id="seeScreen",
        ),
        pytest.param(
            "read the screen for me", "readScreen",
            '{"text":"Error: connection refused on port 8080","monitor":"primary"}',
            id="readScreen",
        ),
    ])
    def test_screen_query_invokes_vision_tool(
        self, query, tool, fake_result, mock_config, eval_db, eval_dialogue_memory
    ):
        from jarvis.reply.engine import run_reply_engine

        mock_config.ollama_base_url = "http://localhost:11434"
        mock_config.ollama_chat_model = JUDGE_MODEL
        mock_config.vision_enabled = True

        capture = ToolCallCapture()
        with patch(
            "jarvis.reply.engine.run_tool_with_retries",
            side_effect=create_mock_tool_run(capture, {tool: fake_result}),
        ):
            response = run_reply_engine(
                db=eval_db, cfg=mock_config, tts=None, text=query,
                dialogue_memory=eval_dialogue_memory, language="en",
                # Mirror the live Tier 2.4 fused path that offers the screen tool.
                fused_tools=[{"name": tool, "arguments": {}}],
                fused_plan=[tool, "Reply to the user."],
            )

        print(f"\n  Vision invocation ({JUDGE_MODEL}): {query!r}")
        print(f"  Tools called: {capture.tool_names() or 'none'}")
        print(f"  Response: {(response or '')[:160]}")

        if not capture.has_tool(tool):
            msg = (
                f"'{query}' MUST call {tool} (never describe the screen from imagination); "
                f"called {capture.tool_names() or 'none'}. Response: {(response or '')[:200]}"
            )
            if _is_small(JUDGE_MODEL):
                pytest.xfail(f"Small model {JUDGE_MODEL} hallucinated instead of calling {tool}: {msg}")
            pytest.fail(msg)

    @pytest.mark.eval
    @requires_judge_llm
    def test_unavailable_vision_is_reported_not_faked(
        self, mock_config, eval_db, eval_dialogue_memory
    ):
        """When seeScreen returns status 'unavailable' (vision model timed out),
        the reply must tell the user vision is unavailable/delayed and NOT
        fabricate a description of the screen."""
        from jarvis.reply.engine import run_reply_engine

        mock_config.ollama_base_url = "http://localhost:11434"
        mock_config.ollama_chat_model = JUDGE_MODEL
        mock_config.vision_enabled = True

        fake_result = (
            '{"status":"unavailable","reason":"no_response","description":null,'
            '"message":"The vision model did not respond in time (it may be slow to load '
            'or temporarily unavailable); the screen was NOT analysed.","monitor":"primary"}'
        )
        capture = ToolCallCapture()
        with patch(
            "jarvis.reply.engine.run_tool_with_retries",
            side_effect=create_mock_tool_run(capture, {"seeScreen": fake_result}),
        ):
            response = run_reply_engine(
                db=eval_db, cfg=mock_config, tts=None,
                text="what do you see on my screen",
                dialogue_memory=eval_dialogue_memory, language="en",
                fused_tools=[{"name": "seeScreen", "arguments": {}}],
                fused_plan=["seeScreen", "Reply to the user."],
            )

        print(f"\n  Unavailable handling ({JUDGE_MODEL}): {(response or '')[:200]!r}")
        # The persona is a witty butler, so phrasing varies wildly ("the vision
        # system took a coffee break"). Judge the MEANING, not keywords: did it
        # report vision unavailable/retry, WITHOUT fabricating screen contents?
        judge_system = (
            "You evaluate a butler-style voice assistant's reply. Context: the screen-vision "
            "tool FAILED and returned status 'unavailable' — nothing about the screen is known. "
            "A correct reply conveys that the vision/screen system is temporarily unavailable, "
            "down, or delayed, and/or asks the user to try again, using ANY phrasing (wit is "
            "fine), WITHOUT describing or guessing any actual screen contents. A reply that "
            "describes specific windows, apps, text, or UI as if it had seen the screen is WRONG.\n\n"
            "Output exactly:\nOVERALL: [PASS/FAIL]\nREASONING: [one sentence]"
        )
        verdict = _parse_judge_response(
            call_judge_llm(judge_system, f"Assistant reply: {response}") or "OVERALL: FAIL"
        )
        print(f"  Judge: passed={verdict.is_passed} — {verdict.reasoning}")
        if not verdict.is_passed:
            msg = (f"reply must report vision unavailable without fabricating a screen "
                   f"description; got: {(response or '')[:200]} | judge: {verdict.reasoning}")
            if _is_small(JUDGE_MODEL):
                pytest.xfail(f"Small model {JUDGE_MODEL} did not report unavailability: {msg}")
            pytest.fail(msg)
