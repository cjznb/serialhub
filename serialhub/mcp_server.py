"""serialhub MCP server (stdio).

Exposes the serialhub daemon as Model Context Protocol tools so agents can
list/open/read/search/block-wait/send on serial ports without shelling out.
This is a thin client: every tool calls the daemon over HTTP via
``serialhub.client.Client`` — the daemon must already be running
(``serialhub serve``). Blocking HTTP calls run on a worker thread
(``asyncio.to_thread``) so the MCP event loop never stalls.

Every tool returns ``{"ok": true, ...fields}`` or ``{"ok": false, "error": "..."}``.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any, Optional, Union

if __package__ in (None, ""):  # executed as a script (e.g. MCP `command: [python, mcp_server.py]`)
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from serialhub.client import Client
    from serialhub.mcp_compat import MCPServer, ToolAnnotations
else:
    from .client import Client
    from .mcp_compat import MCPServer, ToolAnnotations

DEFAULT_URL = "http://127.0.0.1:8765"

_BASE_URL: str = os.environ.get("SERIALHUB_URL", DEFAULT_URL)
_TOKEN: Optional[str] = os.environ.get("SERIALHUB_TOKEN") or None


def configure(base_url: Optional[str] = None, token: Optional[str] = None) -> None:
    """Override the daemon URL/token at runtime (used by tests only)."""
    global _BASE_URL, _TOKEN
    if base_url is not None:
        _BASE_URL = base_url
    _TOKEN = token


def _client() -> Client:
    return Client(_BASE_URL, _TOKEN)


mcp = MCPServer(
    "serialhub",
    instructions=(
        "Control a persistent serial-port daemon (serialhub).\n"
        "Typical workflow: list_ports -> open(port) -> read/search/wait_for -> "
        "send -> snapshot/export.\n"
        "read/search/wait_for return buffered lines with global seq + epoch-ms ts, "
        "so you can resume with since_seq without re-reading.\n"
        "wait_for blocks until a regex matches (non-match is {ok:true,matched:false}; "
        "not an error).\n"
        "Every tool returns {'ok': true, ...fields} or {'ok': false, 'error': '<message>'}."
    ),
)

def _annotations(**kwargs: Any) -> ToolAnnotations:
    """Build ToolAnnotations using the SDK's camelCase wire aliases.

    The installed ``mcp`` stubs declare snake_case fields, but the models accept
    the camelCase aliases at runtime (both mcp 1.x and 2.x), matching the
    reference implementation and the frozen contract.
    """
    return ToolAnnotations(**kwargs)


_READ_ONLY = _annotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True,
                         openWorldHint=False)
_MUTATING = _annotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False,
                         openWorldHint=False)
_DESTRUCTIVE = _annotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False,
                            openWorldHint=False)


# --------------------------------------------------------------------------- #
# tools (order + names mirror the frozen MCP contract)
# --------------------------------------------------------------------------- #
@mcp.tool(name="list_ports", annotations=_READ_ONLY)
async def list_ports() -> dict[str, Any]:
    """List system serial devices and configured ports./
    列出系统串口与已配置端口（含 open/缓冲统计/桥接状态）。

    Returns:
        dict: ``{"ok": true, "system": [...], "ports": [...]}`` where each port
        carries name/device/open/baud/buffer/rx_lines/tx_lines/last_error/tcp_bridge.
        On failure ``{"ok": false, "error": "<message>"}``.
    """
    return await asyncio.to_thread(_client().list_ports)


@mcp.tool(name="open", annotations=_MUTATING)
async def open(port: str, baud: int = 115200, device: Optional[str] = None) -> dict[str, Any]:
    """Open (or reopen) a serial port with an optional baud/device override./
    打开（或重开）某口，可覆盖波特率/设备路径。

    Args:
        port: Logical port name from the config (e.g. ``console``).
        baud: Baud rate override (default 115200).
        device: Device path override (e.g. ``COM11``, ``/dev/ttyUSB0``).

    Returns:
        dict: ``{"ok": true, <port dict>}`` with ``open: true``. On failure
        ``{"ok": false, "error": "<message>"}``.
    """
    return await asyncio.to_thread(_client().open, port, baud, device)


@mcp.tool(name="close", annotations=_MUTATING)
async def close(port: str) -> dict[str, Any]:
    """Close a serial port (buffer is preserved)./ 关闭某口（保留缓冲）。

    Args:
        port: Logical port name.

    Returns:
        dict: ``{"ok": true, <port dict>}`` with ``open: false``. On failure
        ``{"ok": false, "error": "<message>"}``.
    """
    return await asyncio.to_thread(_client().close, port)


@mcp.tool(name="status", annotations=_READ_ONLY)
async def status(port: Optional[str] = None) -> dict[str, Any]:
    """Daemon + per-port status. Omit ``port`` for the whole daemon./
    守护进程与端口状态；省略 port 返回整体状态。

    Args:
        port: Optional logical port name; omit for daemon-wide status.

    Returns:
        dict: daemon-wide ``{"ok": true, "server": {...}, "ports": [...]}`` or a
        single port dict (plus server). On failure ``{"ok": false, "error": ...}``.
    """
    return await asyncio.to_thread(_client().status, port)


@mcp.tool(name="read", annotations=_READ_ONLY)
async def read(port: str, since_seq: Optional[int] = None, since_ts: Optional[int] = None,
               filter: Optional[str] = None, limit: Optional[int] = None,
               strip_ansi: bool = False) -> dict[str, Any]:
    """Read buffered lines without double-consuming (cursor by seq or ts)./
    读取缓冲行（按 seq/ts 游标，不重复消费），返回 next_seq 供续读。

    Args:
        port: Logical port name.
        since_seq: Return lines with ``seq > since_seq`` (preferred cursor).
        since_ts: Return lines with ``ts_ms > since_ts`` when no since_seq.
        filter: Optional regex; only matching lines are returned.
        limit: Max lines to return.
        strip_ansi: Strip ANSI escape sequences from ``text``.

    Returns:
        dict: ``{"ok": true, "lines": [{seq, ts_ms, text, ...}], "count",
        "next_seq", "dropped", "has_more", "first_seq", "last_seq", "port"}``.
    """
    return await asyncio.to_thread(
        _client().read, port, since_seq=since_seq, since_ts=since_ts,
        filter=filter, limit=limit, strip_ansi=strip_ansi,
    )


@mcp.tool(name="search", annotations=_READ_ONLY)
async def search(port: str, regex: str, context: int = 0,
                 since_seq: Optional[int] = None, limit: Optional[int] = None) -> dict[str, Any]:
    """Search buffered lines by regex, with optional context windows./
    按正则搜索缓冲行，可带上下文。

    Args:
        port: Logical port name.
        regex: Regular expression to match.
        context: Number of surrounding lines before/after each hit.
        since_seq: Only search lines with ``seq > since_seq``.
        limit: Max hits to return.

    Returns:
        dict: ``{"ok": true, "hits": [{seq, ts_ms, text, kind, match,
        context_before, context_after}], "count", "next_seq", "regex", "port"}``.
    """
    return await asyncio.to_thread(_client().search, port, regex, context=context,
                                   since_seq=since_seq, limit=limit)


@mcp.tool(name="wait_for", annotations=_READ_ONLY)
async def wait_for(port: str, regex: str, timeout_ms: int = 10000,
                   since_seq: Optional[int] = None) -> dict[str, Any]:
    """Block until a regex matches a new line (or timeout)./
    阻塞等待新行匹配正则（或超时）。未匹配不是错误：matched=false。

    Args:
        port: Logical port name.
        regex: Regular expression to wait for.
        timeout_ms: Max wait in milliseconds (default 10000).
        since_seq: Only consider lines with ``seq > since_seq``.

    Returns:
        dict: ``{"ok": true, "matched": bool, "line": {...}|None, "seq", "ts_ms",
        "from_seq", "port"}`` — a timeout yields ``matched: false`` (still ok).
    """
    return await asyncio.to_thread(_client().wait, port, regex, timeout_ms=timeout_ms,
                                   since_seq=since_seq)


@mcp.tool(name="send", annotations=_MUTATING)
async def send(port: str, data: str, eol: str = "\r\n",
               wait_regex: Optional[str] = None,
               timeout_ms: Optional[int] = None) -> dict[str, Any]:
    """Write data to a port (EOL appended), optionally waiting for a reply./
    向串口写入数据（追加 EOL），可选等待回复。

    Args:
        port: Logical port name.
        data: Payload text without the trailing EOL.
        eol: Line ending: ``crlf``/``lf``/``cr``/``none`` or a literal string.
        wait_regex: If set, block until a new line matches this regex.
        timeout_ms: Wait timeout for wait_regex, in milliseconds.

    Returns:
        dict: ``{"ok": true, "sent_bytes", "sent", "waited", "matched",
        "line": {...}|None, "seq", "port"}``. On failure ``{"ok": false, "error"}``.
    """
    return await asyncio.to_thread(_client().send, port, data, eol=eol,
                                   wait_regex=wait_regex, timeout_ms=timeout_ms)


@mcp.tool(name="snapshot", annotations=_READ_ONLY)
async def snapshot(port: str, tail_lines: int = 200) -> dict[str, Any]:
    """Return the last N buffered lines for a port./ 返回该口缓冲的末尾 N 行。

    Args:
        port: Logical port name.
        tail_lines: Number of trailing lines to return (default 200).

    Returns:
        dict: ``{"ok": true, "lines": [...], "count", "tail_lines", "port"}``.
    """
    return await asyncio.to_thread(_client().snapshot, port, tail_lines=tail_lines)


@mcp.tool(name="export", annotations=_MUTATING)
async def export(port: str, path: Optional[str] = None, format: str = "raw",
                 range: Optional[str] = None) -> dict[str, Any]:
    """Export the port buffer to a file (raw/noansi/json)./
    把该口缓冲导出到文件（raw/noansi/json）。注意：会写文件。

    Args:
        port: Logical port name.
        path: Target file path (daemon default when omitted).
        format: ``raw`` | ``noansi`` | ``json`` (JSONL).
        range: Optional range selector understood by the daemon.

    Returns:
        dict: ``{"ok": true, "path", "format", "bytes", "count", "port"}``.
    """
    return await asyncio.to_thread(_client().export, port, path=path, fmt=format, rng=range)


@mcp.tool(name="tcp_bridge", annotations=_MUTATING)
async def tcp_bridge(action: str, port: str, tcp_port: Optional[int] = None,
                     mode: str = "server", host: Optional[str] = None) -> dict[str, Any]:
    """Start/stop/inspect a TCP bridge for a port./
    启动/停止/查看某口的 TCP 桥。

    Args:
        action: ``start`` | ``stop`` | ``status``.
        port: Logical port name.
        tcp_port: TCP port (required for ``start`` in server mode).
        mode: ``server`` (listen) or ``client`` (connect out).
        host: Remote host (required for ``start`` in client mode).

    Returns:
        dict: ``{"ok": true, "active": bool, "mode", "tcp_port", "host", "port"}``.
    """
    return await asyncio.to_thread(_client().bridge, action, port, mode=mode,
                                   tcp_port=tcp_port, host=host)


@mcp.tool(name="mark", annotations=_MUTATING)
async def mark(port: str, label: str) -> dict[str, Any]:
    """Insert a labelled marker line into a port buffer./ 在缓冲中插入带标签的标记行。

    Args:
        port: Logical port name.
        label: Marker text (visible in read/search output).

    Returns:
        dict: ``{"ok": true, "label", "seq", "ts_ms", "port"}``.
    """
    return await asyncio.to_thread(_client().mark, port, label)


@mcp.tool(name="clear", annotations=_DESTRUCTIVE)
async def clear(port: str) -> dict[str, Any]:
    """Clear a port's ring buffer (destructive)./ 清空该口环形缓冲（破坏性）。

    Args:
        port: Logical port name.

    Returns:
        dict: ``{"ok": true, "cleared": int, "port"}``.
    """
    return await asyncio.to_thread(_client().clear, port)


@mcp.tool(name="reload", annotations=_MUTATING)
async def reload() -> dict[str, Any]:
    """Hot-reload the daemon config from disk./ 从磁盘热重载守护进程配置。

    Returns:
        dict: ``{"ok": true, "added", "removed", "restarted", "updated"}``.
    """
    return await asyncio.to_thread(_client().reload)


@mcp.tool(name="set_device", annotations=_MUTATING)
async def set_device(port: str, device: Optional[str] = None,
                     match: Optional[Union[str, dict]] = None,
                     reopen: bool = True) -> dict[str, Any]:
    """Remap which COM/device a configured port uses at runtime (transient).

    Provide exactly ONE of ``device`` or ``match`` — changing a port's target
    without editing the config file or restarting the daemon. Nothing is
    persisted; the mapping lives in memory until the daemon restarts.

    Args:
        port: Logical port name from the config (e.g. ``console``).
        device: Fixed device path (e.g. ``COM11``, ``/dev/ttyUSB0``).
        match: Auto-discovery spec — a JSON object string (e.g.
            ``'{"vid": "0x1A86", "pid": "0x7523"}'``) or a dict. Keys:
            description/hwid/device/serial (substring) + vid/pid (int or hex)
            + index.
        reopen: Restart the worker now (default true, buffer preserved). When
            false, only the in-memory mapping changes; it applies on the next
            open/reconnect.

    Returns:
        dict: ``{"ok": true, <port dict>}`` (name/device/open/...). On failure
        ``{"ok": false, "error": "<message>"}``.
    """
    spec: Optional[dict] = None
    if match is not None:
        if isinstance(match, str):
            try:
                spec = json.loads(match)
            except json.JSONDecodeError:
                return {"ok": False, "error": f"match must be a JSON object: {match!r}"}
            if not isinstance(spec, dict):
                return {"ok": False, "error": f"match must be a JSON object: {match!r}"}
        else:
            spec = match
    return await asyncio.to_thread(_client().set_device, port,
                                   device=device, match=spec, reopen=reopen)


@mcp.tool(name="discover", annotations=_READ_ONLY)
async def discover() -> dict[str, Any]:
    """Enumerate system serial devices (indexed, sorted by device name)./
    枚举系统串口设备（带序号，按设备名排序）。

    Returns:
        dict: ``{"ok": true, "devices": [{"index", "device", "description",
        "hwid", "vid", "pid"}...]}``. On failure ``{"ok": false, "error": ...}``.
    """
    return await asyncio.to_thread(_client().discover)


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #
def main(transport: str = "stdio") -> None:
    """Run the MCP server. ``transport`` defaults to ``stdio``."""
    for stream in (sys.stdin, sys.stdout):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8")
        except ValueError:
            pass
    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
