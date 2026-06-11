"""Direct LLM interaction utilities without extra features like temporal context."""

from __future__ import annotations
from typing import Optional, Any, Dict, List, Generator, Callable
import requests
import json

from .debug import debug_log
from .config import load_settings


class ToolsNotSupportedError(Exception):
    """Raised when the model returns HTTP 400 because native tool calling is not supported."""
    pass


def shared_num_ctx() -> int:
    """The ONE context size every call on the shared brain must request.

    Ollama fully reloads a model's runner whenever a request's num_ctx differs
    from the loaded one — measured ~8.5s per transition on qwen3.5:9b-4k, in
    BOTH directions. Mixed sizes (chat 8192 / fused 4096 / reminder parser
    1024) made every voice query pay up to two reloads and pushed sub-second
    calls past their timeouts. Config dial: ``llm_num_ctx`` (default 4096,
    matching the deliberately-built -4k model); changing it moves every call
    site together so the runner is never thrashed.
    """
    try:
        return int(getattr(load_settings(), "llm_num_ctx", 4096) or 4096)
    except Exception:
        return 4096


def call_llm_direct(base_url: str, chat_model: str, system_prompt: str, user_content: str, timeout_sec: float = 10.0, thinking: bool = False, num_ctx: Optional[int] = None, temperature: Optional[float] = None) -> Optional[str]:
    """Direct LLM call without temporal context, location, or other ask_coach features.

    ``num_ctx`` rides ``shared_num_ctx()`` when omitted — see its docstring;
    pass a value ONLY for a model that does not share the main brain's runner.

    ``temperature`` is forwarded to Ollama when set. Pass ``0.0`` for
    classification / extraction calls where determinism beats creativity —
    Ollama defaults to ~0.8 otherwise, which can flake small models on
    rule-following tasks (e.g. the knowledge extractor's banned-form list).
    """
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content}
    ]

    options: Dict[str, Any] = {"num_ctx": int(num_ctx) if num_ctx else shared_num_ctx()}
    if temperature is not None:
        options["temperature"] = temperature

    payload: Dict[str, Any] = {
        "model": chat_model,
        "messages": messages,
        "stream": False,
        "options": options,
        "think": thinking,
    }
    
    try:
        with requests.post(f"{base_url.rstrip('/')}/api/chat", json=payload, timeout=timeout_sec) as resp:
            resp.raise_for_status()
            data = resp.json()

        if isinstance(data, dict):
            content = extract_text_from_response(data)
            if isinstance(content, str) and content.strip():
                return content
            debug_log(f"call_llm_direct: empty content from response keys={list(data.keys())}", "llm")
    except requests.exceptions.Timeout:
        debug_log(f"call_llm_direct: timeout after {timeout_sec}s", "llm")
        return None
    except Exception as e:
        debug_log(f"call_llm_direct: request failed — {e}", "llm")
        return None

    return None


def call_llm_streaming(
    base_url: str,
    chat_model: str,
    system_prompt: str,
    user_content: str,
    on_token: Optional[Callable[[str], None]] = None,
    timeout_sec: float = 30.0,
    thinking: bool = False,
) -> Optional[str]:
    """
    Streaming LLM call that invokes on_token callback for each token received.

    Args:
        base_url: Ollama base URL
        chat_model: Model name
        system_prompt: System prompt
        user_content: User message
        on_token: Callback invoked with each token as it arrives
        timeout_sec: Request timeout
        thinking: Enable thinking/reasoning mode

    Returns:
        Complete response text, or None on error
    """
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content}
    ]

    payload: Dict[str, Any] = {
        "model": chat_model,
        "messages": messages,
        "stream": True,
        "options": {"num_ctx": shared_num_ctx()},
        "think": thinking,
    }

    # Use ``with`` so the streaming response (and the underlying TCP
    # connection) is released even if iter_lines exits early via an
    # exception or the caller stops consuming. Without this an aborted
    # stream pinned the connection until GC, which could happen many
    # turns later under sustained reply load.
    try:
        with requests.post(
            f"{base_url.rstrip('/')}/api/chat",
            json=payload,
            timeout=timeout_sec,
            stream=True,
        ) as resp:
            resp.raise_for_status()

            full_response = []
            for line in resp.iter_lines():
                if line:
                    try:
                        data = json.loads(line)
                        if "message" in data and isinstance(data["message"], dict):
                            content = data["message"].get("content", "")
                            if content:
                                full_response.append(content)
                                if on_token:
                                    on_token(content)
                    except json.JSONDecodeError:
                        continue

            result = "".join(full_response)
            return result if result.strip() else None

    except requests.exceptions.Timeout:
        return None
    except Exception:
        return None


def extract_text_from_response(data: Dict[str, Any]) -> Optional[str]:
    """Extract text from LLM response - supports multiple response formats."""
    # Preferred: Ollama chat non-stream format
    if "message" in data and isinstance(data["message"], dict):
        content = data["message"].get("content")
        if isinstance(content, str):
            return content
    
    # Fallback: OpenAI-style format
    if "choices" in data and isinstance(data["choices"], list) and len(data["choices"]) > 0:
        choice = data["choices"][0]
        if isinstance(choice, dict):
            if "message" in choice and isinstance(choice["message"], dict):
                content = choice["message"].get("content")
                if isinstance(content, str):
                    return content
            elif "text" in choice:
                content = choice["text"]
                if isinstance(content, str):
                    return content
    
    # Another fallback: direct "content" field
    if "content" in data:
        content = data["content"]
        if isinstance(content, str):
            return content
    
    return None


def chat_with_messages(
    base_url: str,
    chat_model: str,
    messages: List[Dict[str, str]],
    timeout_sec: float = 30.0,
    extra_options: Optional[Dict[str, Any]] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    thinking: bool = False,
    num_predict: Optional[int] = None,
    temperature: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    """
    Send an arbitrary messages array to the LLM and return the raw response JSON.
    Caller is responsible for interpreting assistant content (including JSON/tool calls).

    Args:
        base_url: Ollama base URL
        chat_model: Model name
        messages: Conversation messages
        timeout_sec: Request timeout
        extra_options: Additional model options
        tools: Optional list of tools in OpenAI-compatible JSON schema format for native tool calling
        thinking: Enable thinking/reasoning mode
        num_predict: Optional cap on generated tokens. Only sent when > 0; a
            value of None or <= 0 means "no cap" and leaves the model default
            (unbounded) untouched.
        temperature: Optional sampling temperature. Sent verbatim when not None
            (0.0 is a valid value meaning greedy decoding); None leaves the
            model default untouched.

    Returns the parsed JSON response dict on success, or None on error/timeout.
    """
    # Rides shared_num_ctx() like every other shared-brain call: the old
    # hardcoded 8192 here (vs 4096 elsewhere) forced an ~8.5s Ollama runner
    # reload TWICE per voice query. If a richer prompt needs more context,
    # raise `llm_num_ctx` in config — every call site moves together.
    payload: Dict[str, Any] = {
        "model": chat_model,
        "messages": messages,
        "stream": False,
        "options": {"num_ctx": shared_num_ctx()},
        "think": thinking,
    }
    if extra_options and isinstance(extra_options, dict):
        # Merge shallowly into options
        payload["options"].update(extra_options)

    # Optional generation bounds/tuning. Only set when the caller passes a
    # meaningful value so default behaviour stays byte-for-byte identical:
    # an absent num_predict leaves generation length unbounded, an absent
    # temperature leaves the model's own default in place.
    if num_predict is not None and num_predict > 0:
        payload["options"]["num_predict"] = int(num_predict)
    if temperature is not None:
        payload["options"]["temperature"] = float(temperature)

    # Add tools for native tool calling support (Ollama 0.4+)
    if tools and isinstance(tools, list) and len(tools) > 0:
        payload["tools"] = tools

    try:
        with requests.post(f"{base_url.rstrip('/')}/api/chat", json=payload, timeout=timeout_sec) as resp:
            resp.raise_for_status()
            data = resp.json()
        if isinstance(data, dict):
            return data
    except requests.exceptions.Timeout:
        print("  ⏱️ LLM request timed out", flush=True)
        return None
    except requests.exceptions.ConnectionError as e:
        print(f"  ❌ LLM connection error: {e}", flush=True)
        return None
    except requests.exceptions.HTTPError as e:
        # Raise a specific error when the model rejects the tools parameter (HTTP 400).
        # This lets the caller fall back to text-based tool calling automatically.
        if e.response is not None and e.response.status_code == 400 and tools:
            raise ToolsNotSupportedError(
                f"Model {chat_model!r} returned HTTP 400 — native tools API not supported"
            )
        print(f"  ❌ LLM HTTP error: {e}", flush=True)
        return None
    except Exception as e:
        print(f"  ❌ LLM error: {e}", flush=True)
        return None

    return None


def call_vision_model(
    base_url: str,
    model: str,
    prompt: str,
    images: List[str],
    timeout_sec: float = 30.0,
    keep_alive: Optional[str] = None,
    num_ctx: int = 4096,
    temperature: Optional[float] = None,
) -> Optional[str]:
    """Multimodal call to an Ollama vision model (e.g. moondream).

    Sends a single user message carrying ``images`` (base64-encoded PNG/JPEG
    strings, per Ollama's ``/api/chat`` multimodal format) and returns the
    model's text response, or None on error/timeout. This is deliberately
    separate from ``chat_with_messages``/``call_llm_direct`` so the text chat
    path is untouched — the vision domain owns its own request shape.

    ``keep_alive`` is forwarded verbatim when set (e.g. "5m" so a bursty
    vision model self-evicts and returns VRAM to the resident chat model;
    "0" to evict immediately). When None, Ollama's server default applies.
    """
    if not images:
        debug_log("call_vision_model: no images supplied", "vision")
        return None

    options: Dict[str, Any] = {"num_ctx": num_ctx}
    if temperature is not None:
        options["temperature"] = float(temperature)

    payload: Dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "user", "content": prompt, "images": list(images)},
        ],
        "stream": False,
        "options": options,
    }
    if keep_alive is not None:
        payload["keep_alive"] = keep_alive

    try:
        with requests.post(f"{base_url.rstrip('/')}/api/chat", json=payload, timeout=timeout_sec) as resp:
            resp.raise_for_status()
            data = resp.json()
        if isinstance(data, dict):
            content = extract_text_from_response(data)
            if isinstance(content, str) and content.strip():
                return content
            debug_log(
                f"call_vision_model: empty content from response keys={list(data.keys())}",
                "vision",
            )
    except requests.exceptions.Timeout:
        debug_log(f"call_vision_model: timeout after {timeout_sec}s", "vision")
        return None
    except Exception as e:
        debug_log(f"call_vision_model: request failed — {e}", "vision")
        return None

    return None
