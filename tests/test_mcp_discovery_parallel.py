"""MCP discovery must run servers concurrently so one slow/bad server can't
stall daemon startup for its full 30s setup timeout (x N servers, serially)."""

import time
from unittest.mock import patch

import jarvis.tools.registry as registry


class _FakeClient:
    def __init__(self, cfg):
        self.cfg = cfg

    def list_tools(self, server):
        if server == "bad":
            raise RuntimeError("boom")
        time.sleep(0.3)  # simulate a slow per-server discovery round trip
        return [{"name": f"{server}_tool", "description": "d", "inputSchema": {}}]


def test_all_servers_discovered():
    with patch.object(registry, "MCPClient", _FakeClient):
        tools, errors = registry.discover_mcp_tools({"a": {}, "b": {}})
    assert "a__a_tool" in tools
    assert "b__b_tool" in tools
    assert errors == {}


def test_one_failing_server_does_not_block_others():
    with patch.object(registry, "MCPClient", _FakeClient):
        tools, errors = registry.discover_mcp_tools({"good": {}, "bad": {}})
    assert "good__good_tool" in tools
    assert "bad" in errors


def test_discovery_runs_concurrently():
    servers = {f"s{i}": {} for i in range(4)}  # 4 x 0.3s = 1.2s serial, ~0.3s parallel
    with patch.object(registry, "MCPClient", _FakeClient):
        t0 = time.perf_counter()
        tools, _ = registry.discover_mcp_tools(servers)
        elapsed = time.perf_counter() - t0
    assert len(tools) == 4
    assert elapsed < 0.8, f"discovery looks serial ({elapsed:.2f}s for 4x0.3s servers)"
