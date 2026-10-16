"""serialhub HTTP client (standard library only).

CLI 与 MCP 共用的瘦客户端：它把 REST 端点的 JSON envelope（本身已带 ``ok``）
原样返回；任何网络层失败都被转换成 ``{"ok": False, "error": "..."}``，绝不
向上抛异常。仅依赖标准库 ``urllib.request``，无第三方客户端依赖。
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

DEFAULT_URL = "http://127.0.0.1:8765"
DEFAULT_TIMEOUT = 30.0


def _query_value(value: Any) -> str:
    """Encode a query value; booleans become ``true``/``false``."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _parse_json(raw: bytes) -> dict[str, Any]:
    """Decode a response body into a dict, degrading gracefully on junk."""
    text = raw.decode("utf-8", "replace").strip()
    if not text:
        return {"ok": False, "error": "empty response from server"}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {"ok": False, "error": f"invalid JSON response: {text[:300]}"}
    if not isinstance(parsed, dict):
        return {"ok": False, "error": f"unexpected JSON response: {text[:300]}"}
    return parsed


class Client:
    """Thin REST client for a running serialhub daemon."""

    def __init__(self, base_url: str = DEFAULT_URL, token: Optional[str] = None,
                 timeout: float = DEFAULT_TIMEOUT) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token or None
        self.default_timeout = float(timeout)

    # ------------------------------------------------------------------ #
    # low level
    # ------------------------------------------------------------------ #
    def call(self, method: str, path: str, *, params: Optional[dict[str, Any]] = None,
             body: Optional[dict[str, Any]] = None,
             timeout: Optional[float] = None) -> dict[str, Any]:
        """Perform one REST call and return the server's JSON envelope.

        ``params`` becomes the query string (``None`` values dropped, booleans
        rendered as ``true``/``false``); ``body`` is sent as JSON. Connection
        and protocol errors never raise — they yield ``{"ok": False, ...}``.
        """
        url = f"{self.base_url}{path}"
        if params:
            clean = {k: _query_value(v) for k, v in params.items() if v is not None}
            if clean:
                url = f"{url}?{urllib.parse.urlencode(clean)}"

        headers = {"Accept": "application/json"}
        payload: Optional[bytes] = None
        if body is not None:
            payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        request = urllib.request.Request(url, data=payload, headers=headers,
                                         method=method.upper())
        wait = self.default_timeout if timeout is None else float(timeout)
        try:
            with urllib.request.urlopen(request, timeout=wait) as response:
                return _parse_json(response.read())
        except urllib.error.HTTPError as exc:
            detail = _read_error_body(exc)
            if "error" not in detail:
                detail["error"] = f"HTTP {exc.code}: {exc.reason}"
            detail["ok"] = False
            return detail
        except (urllib.error.URLError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            return {"ok": False, "error": f"connection failed: {reason}"}

    # ------------------------------------------------------------------ #
    # convenience wrappers (each returns the envelope dict)
    # ------------------------------------------------------------------ #
    @staticmethod
    def _port_path(name: str, suffix: str = "") -> str:
        base = f"/api/ports/{urllib.parse.quote(name, safe='')}"
        return f"{base}/{suffix}" if suffix else base

    def list_ports(self) -> dict[str, Any]:
        return self.call("GET", "/api/ports")

    def status(self, name: Optional[str] = None) -> dict[str, Any]:
        return self.call("GET", "/api/status", params={"name": name})

    def open(self, name: str, baud: Optional[int] = None,
             device: Optional[str] = None) -> dict[str, Any]:
        return self.call("POST", self._port_path(name, "open"),
                         body={"baud": baud, "device": device})

    def close(self, name: str) -> dict[str, Any]:
        return self.call("POST", self._port_path(name, "close"))

    def set_device(self, name: str, device: Optional[str] = None,
                   match: Optional[dict[str, Any]] = None,
                   reopen: bool = True) -> dict[str, Any]:
        """Remap a port's device/match at runtime (transient; no config write)."""
        return self.call("POST", self._port_path(name, "device"), body={
            "device": device, "match": match, "reopen": reopen,
        })

    def discover(self) -> dict[str, Any]:
        """Enumerate system serial devices (indexed, sorted by device name)."""
        return self.call("GET", "/api/devices")

    def read(self, name: str, *, since_seq: Optional[int] = None,
             since_ts: Optional[int] = None, filter: Optional[str] = None,
             limit: Optional[int] = None, strip_ansi: bool = False,
             kinds: Optional[str] = None) -> dict[str, Any]:
        return self.call("GET", self._port_path(name, "read"), params={
            "since_seq": since_seq, "since_ts": since_ts, "filter": filter,
            "limit": limit, "strip_ansi": strip_ansi, "kinds": kinds,
        })

    def search(self, name: str, regex: str, *, context: int = 0,
               since_seq: Optional[int] = None,
               limit: Optional[int] = None) -> dict[str, Any]:
        return self.call("GET", self._port_path(name, "search"), params={
            "regex": regex, "context": context, "since_seq": since_seq, "limit": limit,
        })

    def wait(self, name: str, regex: str, *, timeout_ms: int = 10000,
             since_seq: Optional[int] = None) -> dict[str, Any]:
        wait = (timeout_ms / 1000.0 + 15.0) if timeout_ms else None
        return self.call("GET", self._port_path(name, "wait"), params={
            "regex": regex, "timeout_ms": timeout_ms, "since_seq": since_seq,
        }, timeout=wait)

    def send(self, name: str, data: str, *, eol: Optional[str] = None,
             wait_regex: Optional[str] = None,
             timeout_ms: Optional[int] = None) -> dict[str, Any]:
        wait = (timeout_ms / 1000.0 + 15.0) if timeout_ms else None
        return self.call("POST", self._port_path(name, "send"), body={
            "data": data, "eol": eol, "wait_regex": wait_regex, "timeout_ms": timeout_ms,
        }, timeout=wait)

    def snapshot(self, name: str, *, tail_lines: int = 200) -> dict[str, Any]:
        return self.call("GET", self._port_path(name, "snapshot"),
                         params={"tail_lines": tail_lines})

    def export(self, name: str, *, path: Optional[str] = None, fmt: str = "raw",
               rng: Optional[str] = None) -> dict[str, Any]:
        return self.call("POST", self._port_path(name, "export"),
                         body={"path": path, "format": fmt, "range": rng})

    def mark(self, name: str, label: str) -> dict[str, Any]:
        return self.call("POST", self._port_path(name, "mark"), body={"label": label})

    def clear(self, name: str) -> dict[str, Any]:
        return self.call("POST", self._port_path(name, "clear"))

    def bridge(self, action: str, port: str, *, mode: str = "server",
               tcp_port: Optional[int] = None,
               host: Optional[str] = None) -> dict[str, Any]:
        return self.call("POST", "/api/bridge", body={
            "action": action, "port": port, "mode": mode,
            "tcp_port": tcp_port, "host": host,
        })

    def reload(self) -> dict[str, Any]:
        return self.call("POST", "/api/reload")


def _read_error_body(exc: urllib.error.HTTPError) -> dict[str, Any]:
    """Best-effort parse of a non-2xx body; never raises."""
    try:
        return _parse_json(exc.read())
    except OSError:
        return {}
