"""Tests for the MCP surface (§11) and the stdlib HTTP client (§11 / client.py)."""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp")

from serialhub import mcp_compat, mcp_server  # noqa: E402
from serialhub.client import Client  # noqa: E402

EXPECTED_TOOLS = {
    "list_ports", "open", "close", "status", "read", "search", "wait_for",
    "send", "snapshot", "export", "tcp_bridge", "mark", "clear", "reload",
}

ROOT = Path(__file__).resolve().parent.parent


def _tool_names() -> set[str]:
    """Discover registered MCP tool names across mcp 1.x / 2.x layouts."""
    server = mcp_server.mcp
    manager = getattr(server, "_tool_manager", None)
    tools = getattr(manager, "_tools", None)
    if isinstance(tools, dict) and tools:
        return set(tools.keys())
    listed = asyncio.run(server.list_tools())
    return {tool.name for tool in listed}


def test_mcp_compat_exports_shim_symbols() -> None:
    assert hasattr(mcp_compat, "MCPServer")
    assert hasattr(mcp_compat, "ToolAnnotations")


def test_mcp_exposes_exactly_the_14_tools() -> None:
    names = _tool_names()
    assert names == EXPECTED_TOOLS
    assert len(names) == 14


# ---- client error handling ------------------------------------------------- #
def test_client_list_ports_unreachable_is_ok_false() -> None:
    client = Client("http://127.0.0.1:1", timeout=1.0)
    result = client.list_ports()
    assert result["ok"] is False
    assert "error" in result


def test_client_call_unreachable_is_ok_false() -> None:
    client = Client("http://127.0.0.1:1", timeout=1.0)
    result = client.call("GET", "/api/ports")
    assert result["ok"] is False
    assert "error" in result


# ---- MCP stdio smoke (subprocess) ----------------------------------------- #
def test_mcp_smoke_subprocess() -> None:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "mcp_smoke.py")],
        cwd=str(ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=90,
    )
    assert proc.returncode == 0, f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
