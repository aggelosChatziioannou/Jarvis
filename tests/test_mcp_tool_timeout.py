"""MCP tool calls must use a short per-call timeout on the voice hot path.

MCPClient.invoke_tool delegated to runtime.invoke WITHOUT a timeout, so it fell
through to the 120s runtime default — a hung/slow MCP server could block a
reply-loop turn for two minutes. Use a config-driven default (~30s) with a
per-server override for explicitly long-running/stateful servers.
"""

from unittest.mock import patch, MagicMock

from jarvis.tools.external.mcp_client import MCPClient


def _invoke_capturing(timeout_box):
    def _invoke(server, cfg, tool, args, timeout=None):
        timeout_box["timeout"] = timeout
        return "RES"
    rt = MagicMock()
    rt.invoke.side_effect = _invoke
    return rt


def _run(client, server="srv"):
    box = {}
    rt = _invoke_capturing(box)
    with patch("jarvis.tools.external.mcp_runtime.get_runtime", return_value=rt), \
         patch("jarvis.tools.external.mcp_client._result_to_dict", lambda r: {"r": r}):
        client.invoke_tool(server_name=server, tool_name="doThing", arguments={"a": 1})
    return box["timeout"]


def test_default_tool_timeout_is_short_not_120():
    client = MCPClient({"srv": {"transport": "stdio", "command": "x"}})
    assert _run(client) == 30.0


def test_explicit_client_default_is_used():
    client = MCPClient({"srv": {"transport": "stdio", "command": "x"}}, tool_timeout_sec=15.0)
    assert _run(client) == 15.0


def test_per_server_override_wins():
    client = MCPClient(
        {"slow": {"transport": "stdio", "command": "x", "tool_timeout_sec": 120}},
        tool_timeout_sec=30.0,
    )
    assert _run(client, server="slow") == 120.0
