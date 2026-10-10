#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mcp_smoke.py -- minimal MCP **stdio** client used to verify serialhub's MCP server.

It speaks raw newline-delimited JSON-RPC 2.0 (no SDK client), which doubles as
proof that ``serialhub/mcp_server.py`` implements the protocol correctly.

Usage::

    python tools/mcp_smoke.py           # initialize + tools/list (needs no daemon)
    python tools/mcp_smoke.py --full    # also run list_ports (needs `serialhub serve`)

Exit code 0 = all calls returned well-formed JSON; 1 = failure.
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import subprocess
import sys
import threading
import time
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SERVER = os.path.join(ROOT, "serialhub", "mcp_server.py")
PROTOCOL_VERSION = "2025-06-18"


class StdioClient:
    """Threaded newline-JSON-RPC client over a child process's stdio."""

    def __init__(self) -> None:
        env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
        self.proc = subprocess.Popen(
            [sys.executable, SERVER],
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env,
        )
        self._id = 0
        self._queue: "queue.Queue[str]" = queue.Queue()
        self._stderr_lines: list[str] = []
        threading.Thread(target=self._pump, args=(self.proc.stdout, self._queue),
                         daemon=True).start()
        threading.Thread(target=self._drain_stderr, daemon=True).start()

    def _pump(self, stream, out: "queue.Queue[str]") -> None:
        for line in stream:
            out.put(line)
        out.put("")  # sentinel: stdout closed

    def _drain_stderr(self) -> None:
        stderr = self.proc.stderr
        if stderr is None:
            return
        for line in stderr:
            self._stderr_lines.append(line.rstrip("\n"))

    def stderr(self) -> str:
        return "\n".join(self._stderr_lines[-40:])

    def _send(self, method: str, params=None, notify: bool = False):
        msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        if not notify:
            self._id += 1
            msg["id"] = self._id
        stdin = self.proc.stdin
        if stdin is None:
            raise RuntimeError("server stdin is not available")
        stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
        stdin.flush()
        return msg.get("id")

    def notify(self, method: str, params=None) -> None:
        self._send(method, params, notify=True)

    def request(self, method: str, params=None, timeout: float = 120.0) -> dict:
        rid = self._send(method, params)
        deadline = time.time() + timeout
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                raise TimeoutError(f"{method} (id={rid}) timed out after {timeout:.0f}s")
            try:
                line = self._queue.get(timeout=remaining)
            except queue.Empty:
                raise TimeoutError(f"{method} (id={rid}) timed out after {timeout:.0f}s")
            if line == "":
                raise RuntimeError(f"server closed stdout during {method}; stderr:\n{self.stderr()}")
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(msg, dict) and msg.get("id") == rid:
                if "error" in msg:
                    raise RuntimeError(f"{method} returned JSON-RPC error: {msg['error']}")
                return msg

    def close(self) -> None:
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def tool_result_payload(resp: dict):
    """Extract the tool's structured payload from a tools/call response."""
    result = resp.get("result", {})
    for item in result.get("content", []):
        if item.get("type") == "text":
            try:
                return json.loads(item["text"])
            except json.JSONDecodeError:
                return item["text"]
    return result.get("structuredContent", result)


def call(client: StdioClient, name: str, arguments: dict, timeout: float) -> dict:
    resp = client.request("tools/call", {"name": name, "arguments": arguments}, timeout=timeout)
    payload = tool_result_payload(resp)
    print(f"\n# tools/call -> {name}({json.dumps(arguments, ensure_ascii=False)})")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return payload


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="MCP stdio smoke test for serialhub/mcp_server.py")
    ap.add_argument("--full", action="store_true",
                    help="also run list_ports (needs a running `serialhub serve`)")
    ap.add_argument("--tool-timeout", type=float, default=30.0,
                    help="per tools/call timeout in seconds (default 30)")
    args = ap.parse_args(argv)

    client = StdioClient()
    try:
        init = client.request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "mcp-smoke", "version": "1.0"},
        }, timeout=30)
        server_info = init.get("result", {}).get("serverInfo", {})
        print("# initialize ->")
        print(json.dumps({"serverInfo": server_info,
                          "protocolVersion": init.get("result", {}).get("protocolVersion")},
                         ensure_ascii=False, indent=2))
        client.notify("notifications/initialized")

        listing = client.request("tools/list", {}, timeout=30)
        tools = listing.get("result", {}).get("tools", [])
        print(f"\n# tools/list -> {len(tools)} tools")
        print(json.dumps([{"name": t["name"], "description": t.get("description", "").splitlines()[0]}
                          for t in tools], ensure_ascii=False, indent=2))

        failed = False
        if args.full:
            failed |= not call(client, "list_ports", {}, args.tool_timeout).get("ok")

        print("\n# RESULT:", "FAIL" if failed else "PASS")
        return 1 if failed else 0
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
