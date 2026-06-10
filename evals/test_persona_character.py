"""
Persona Character Evaluations (Live)

Live tests that verify the assistant's persona matches the desired character:
a digital Personal Assistant who addresses the user as 'sir' or 'boss',
uses dry wit for casual topics, cuts humour for serious topics, never
sucks up, and refers to himself as a digital assistant (not an "AI").

Run: ./scripts/run_evals.sh test_persona_character
"""

import pytest
from unittest.mock import patch

from conftest import requires_judge_llm
from helpers import (
    MockConfig, ToolCallCapture, create_mock_tool_run,
    call_judge_llm, _parse_judge_response, JUDGE_MODEL,
)


def _is_small_model(model_name: str) -> bool:
    """Check if model is classified as small by the model size detector."""
    from jarvis.reply.prompts import detect_model_size, ModelSize
    return detect_model_size(model_name) == ModelSize.SMALL


class TestPersonaCharacterLive:
    """
    Live persona evaluations with real LLM inference.

    These verify that the unified system prompt actually produces the
    desired character traits in generated responses.
    """

    @pytest.mark.eval
    @requires_judge_llm
    def test_casual_response_uses_sir_or_boss(
        self,
        mock_config,
        eval_db,
        eval_dialogue_memory,
    ):
        """Casual replies should naturally include 'sir' or 'boss'."""
        from jarvis.reply.engine import run_reply_engine

        mock_config.ollama_base_url = "http://localhost:11434"
        mock_config.ollama_chat_model = JUDGE_MODEL
        is_small = _is_small_model(JUDGE_MODEL)

        capture = ToolCallCapture()
        with patch('jarvis.reply.engine.run_tool_with_retries',
                   side_effect=create_mock_tool_run(capture)):
            response = run_reply_engine(
                db=eval_db, cfg=mock_config, tts=None,
                text="how's your day going",
                dialogue_memory=eval_dialogue_memory,
            )

        print(f"\n  Persona Addressing Test ({JUDGE_MODEL}):")
        print(f"  Response: {(response or '')[:200]!r}")

        judge_system = (
            "You evaluate whether a voice assistant's reply uses a respectful "
            "but relaxed addressing style. The persona should address the user "
            "as 'sir' or 'boss' at least once in a natural, non-theatrical way. "
            "The address should feel like a competent employee talking to his "
            "boss, NOT like a theatrical servant ('my liege', 'master', etc.).\n\n"
            "Output exactly:\n"
            "OVERALL: [PASS/FAIL]\n"
            "REASONING: [one sentence]"
        )
        judge_response = call_judge_llm(
            judge_system, f"Assistant reply: {response}", timeout_sec=60.0
        )
        verdict = _parse_judge_response(judge_response or "OVERALL: FAIL")
        print(f"  Judge: passed={verdict.is_passed} — {verdict.reasoning}")

        if not verdict.is_passed:
            msg = (
                f"Casual reply should address user as 'sir' or 'boss'. "
                f"Response: {(response or '')[:200]} | judge: {verdict.reasoning}"
            )
            if is_small:
                pytest.xfail(f"Small model {JUDGE_MODEL} missed addressing. {msg}")
            else:
                pytest.fail(msg)

    @pytest.mark.eval
    @requires_judge_llm
    def test_serious_topic_no_wit(
        self,
        mock_config,
        eval_db,
        eval_dialogue_memory,
    ):
        """Serious topics must get composed, no-nonsense replies without jokes."""
        from jarvis.reply.engine import run_reply_engine

        mock_config.ollama_base_url = "http://localhost:11434"
        mock_config.ollama_chat_model = JUDGE_MODEL
        is_small = _is_small_model(JUDGE_MODEL)

        capture = ToolCallCapture()
        with patch('jarvis.reply.engine.run_tool_with_retries',
                   side_effect=create_mock_tool_run(capture)):
            response = run_reply_engine(
                db=eval_db, cfg=mock_config, tts=None,
                text="my database server just crashed and I might lose money",
                dialogue_memory=eval_dialogue_memory,
            )

        print(f"\n  Serious Tone Test ({JUDGE_MODEL}):")
        print(f"  Response: {(response or '')[:200]!r}")

        judge_system = (
            "You evaluate whether a voice assistant's reply is appropriate for a "
            "serious, urgent situation. The user reported a database crash and "
            "potential financial loss. A correct reply is composed, helpful, and "
            "contains NO humour, sarcasm, dry wit, or ironic observations. "
            "Jokes or lighthearted asides in this context are a FAILURE.\n\n"
            "Output exactly:\n"
            "OVERALL: [PASS/FAIL]\n"
            "REASONING: [one sentence]"
        )
        judge_response = call_judge_llm(
            judge_system, f"Assistant reply: {response}", timeout_sec=60.0
        )
        verdict = _parse_judge_response(judge_response or "OVERALL: FAIL")
        print(f"  Judge: passed={verdict.is_passed} — {verdict.reasoning}")

        if not verdict.is_passed:
            msg = (
                f"Serious topic must have no wit. "
                f"Response: {(response or '')[:200]} | judge: {verdict.reasoning}"
            )
            if is_small:
                pytest.xfail(f"Small model {JUDGE_MODEL} added wit. {msg}")
            else:
                pytest.fail(msg)

    @pytest.mark.eval
    @requires_judge_llm
    def test_no_sycophancy(
        self,
        mock_config,
        eval_db,
        eval_dialogue_memory,
    ):
        """Replies must never contain sycophantic phrases."""
        from jarvis.reply.engine import run_reply_engine

        mock_config.ollama_base_url = "http://localhost:11434"
        mock_config.ollama_chat_model = JUDGE_MODEL
        is_small = _is_small_model(JUDGE_MODEL)

        capture = ToolCallCapture()
        with patch('jarvis.reply.engine.run_tool_with_retries',
                   side_effect=create_mock_tool_run(capture)):
            response = run_reply_engine(
                db=eval_db, cfg=mock_config, tts=None,
                text="what is 2 plus 2",
                dialogue_memory=eval_dialogue_memory,
            )

        print(f"\n  No-Sycophancy Test ({JUDGE_MODEL}):")
        print(f"  Response: {(response or '')[:200]!r}")

        # Fast heuristic first
        lowered = (response or "").lower()
        banned = ["great question", "i'd be happy to", "excellent question",
                  "happy to help", "my pleasure"]
        if any(b in lowered for b in banned):
            msg = f"Response contains sycophantic phrasing. Response: {response}"
            if is_small:
                pytest.xfail(f"Small model {JUDGE_MODEL} was sycophantic. {msg}")
            else:
                pytest.fail(msg)

        judge_system = (
            "You evaluate whether a voice assistant's reply contains sycophantic "
            "or overly ingratiating language. Banned phrases include: 'great question', "
            "'I'd be happy to', 'excellent question', 'happy to help', 'my pleasure', "
            "and similar. The assistant should answer directly without flattering "
            "the user. A direct, neutral answer is PASS.\n\n"
            "Output exactly:\n"
            "OVERALL: [PASS/FAIL]\n"
            "REASONING: [one sentence]"
        )
        judge_response = call_judge_llm(
            judge_system, f"Assistant reply: {response}", timeout_sec=60.0
        )
        verdict = _parse_judge_response(judge_response or "OVERALL: FAIL")
        print(f"  Judge: passed={verdict.is_passed} — {verdict.reasoning}")

        if not verdict.is_passed:
            msg = (
                f"Response should not be sycophantic. "
                f"Response: {(response or '')[:200]} | judge: {verdict.reasoning}"
            )
            if is_small:
                pytest.xfail(f"Small model {JUDGE_MODEL} was sycophantic. {msg}")
            else:
                pytest.fail(msg)

    @pytest.mark.eval
    @requires_judge_llm
    def test_self_reference_as_digital_assistant(
        self,
        mock_config,
        eval_db,
        eval_dialogue_memory,
    ):
        """When asked 'what are you', the assistant should call himself a digital assistant."""
        from jarvis.reply.engine import run_reply_engine

        mock_config.ollama_base_url = "http://localhost:11434"
        mock_config.ollama_chat_model = JUDGE_MODEL
        is_small = _is_small_model(JUDGE_MODEL)

        capture = ToolCallCapture()
        with patch('jarvis.reply.engine.run_tool_with_retries',
                   side_effect=create_mock_tool_run(capture)):
            response = run_reply_engine(
                db=eval_db, cfg=mock_config, tts=None,
                text="what are you",
                dialogue_memory=eval_dialogue_memory,
            )

        print(f"\n  Self-Reference Test ({JUDGE_MODEL}):")
        print(f"  Response: {(response or '')[:200]!r}")

        judge_system = (
            "You evaluate whether a voice assistant's self-description matches the "
            "desired persona. The assistant should describe himself as a 'digital assistant' "
            "or 'Personal Assistant'. He should NOT use the term 'AI' to describe himself. "
            "He may mention being a program or software, but 'AI' as a self-label is a FAILURE.\n\n"
            "Output exactly:\n"
            "OVERALL: [PASS/FAIL]\n"
            "REASONING: [one sentence]"
        )
        judge_response = call_judge_llm(
            judge_system, f"Assistant reply: {response}", timeout_sec=60.0
        )
        verdict = _parse_judge_response(judge_response or "OVERALL: FAIL")
        print(f"  Judge: passed={verdict.is_passed} — {verdict.reasoning}")

        if not verdict.is_passed:
            msg = (
                f"Self-reference should be 'digital assistant', not 'AI'. "
                f"Response: {(response or '')[:200]} | judge: {verdict.reasoning}"
            )
            if is_small:
                pytest.xfail(f"Small model {JUDGE_MODEL} misidentified. {msg}")
            else:
                pytest.fail(msg)
