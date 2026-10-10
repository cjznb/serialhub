"""Compatibility shim for the official ``mcp`` SDK.

mcp 1.x exposes ``mcp.server.fastmcp.FastMCP``; mcp 2.x renamed the high-level
server to ``mcp.server.mcpserver.MCPServer``. Feature code imports the symbols
from here so it works on either major version without conditionals. If the
``mcp`` package is entirely absent we print a clear hint to stderr and exit 2.
"""
from __future__ import annotations

import sys

try:
    try:
        from mcp.server.fastmcp import FastMCP as MCPServer  # type: ignore[attr-defined]  # mcp 1.x only
    except Exception:  # noqa: BLE001 - older/newer layout fallback
        from mcp.server.mcpserver import MCPServer  # mcp 2.x
    from mcp.types import ToolAnnotations
except ModuleNotFoundError as exc:  # pragma: no cover - operator-facing
    sys.stderr.write(
        "serialhub.mcp_compat: the official MCP SDK is not installed.\n"
        "  Install it with:  pip install \"mcp>=1.9\"   (or requirements-dev.txt)\n"
        f"  Import error: {exc}\n"
    )
    raise SystemExit(2) from exc

__all__ = ["MCPServer", "ToolAnnotations"]
