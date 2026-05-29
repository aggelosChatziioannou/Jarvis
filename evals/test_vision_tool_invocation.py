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
from helpers import JUDGE_MODEL, ToolCallCapture, create_mock_tool_run


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
