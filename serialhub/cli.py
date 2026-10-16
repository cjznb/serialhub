"""serialhub command-line interface.

``serialhub <cmd>`` is a lightweight client for a running ``serialhub serve``
daemon: every non-``serve`` subcommand prints exactly one line of JSON —
``{"ok": true, "data": <result>}`` or ``{"ok": false, "error": "<message>"}`` —
and exits 0 on success / 1 on failure. ``serve`` runs the daemon in-process.

``hub``/``server``/``tcp_bridge`` (and uvicorn) are imported lazily inside the
``serve`` handler only, so ``serialhub list`` and the MCP server start with
minimal dependencies.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Optional

from .client import DEFAULT_URL, Client
from .i18n import t

DEFAULT_EOL = "\r\n"
_EOL_TOKENS = {"crlf", "lf", "cr", "none"}
_EOL_ESCAPES = {"\\r\\n": "\r\n", "\\n": "\n", "\\r": "\r", "\\t": "\t"}


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #
def _resolve_eol(value: Optional[str]) -> str:
    """Normalize ``--eol``: named tokens pass through, escapes become literal."""
    if value is None:
        return DEFAULT_EOL
    if value in _EOL_TOKENS:
        return value
    return _EOL_ESCAPES.get(value, value)


def _read_send_data(data: str) -> str:
    """Resolve the ``DATA`` argument; ``-`` reads stdin minus one trailing newline."""
    if data != "-":
        return data
    text = sys.stdin.read()
    if text.endswith("\r\n"):
        return text[:-2]
    if text.endswith(("\n", "\r")):
        return text[:-1]
    return text


def _parse_match_arg(text: str) -> dict[str, Any]:
    """Parse ``--match``: a JSON object, or compact ``k=v`` pairs.

    Examples: ``'{"description": "CH340"}'`` or ``description=CH340,vid=0x1A86``.
    Raises ``ValueError`` on malformed input; the caller turns it into an error
    envelope.
    """
    text = text.strip()
    if text.startswith("{"):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(t("cli.error.match_json", text=text)) from exc
        if not isinstance(parsed, dict):
            raise ValueError(t("cli.error.match_not_object", text=text))
        return parsed
    spec: dict[str, Any] = {}
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        key, sep, value = part.partition("=")
        if not sep or not key.strip():
            raise ValueError(t("cli.error.match_pairs", text=text))
        spec[key.strip()] = value.strip()
    if not spec:
        raise ValueError(t("cli.error.match_pairs", text=text))
    return spec


def _global_options(args: argparse.Namespace) -> tuple[str, Optional[str]]:
    url = getattr(args, "url", None) or DEFAULT_URL
    token = getattr(args, "token", None) or os.environ.get("SERIALHUB_TOKEN") or None
    return url, token


def _print_env(env: dict[str, Any]) -> int:
    """Emit the single-line JSON envelope and return the process exit code."""
    if env.get("ok"):
        data = {k: v for k, v in env.items() if k != "ok"}
        print(json.dumps({"ok": True, "data": data}, ensure_ascii=False))
        return 0
    print(json.dumps({"ok": False, "error": str(env.get("error") or "unknown error")},
                     ensure_ascii=False))
    return 1


# --------------------------------------------------------------------------- #
# argument parser
# --------------------------------------------------------------------------- #
def _build_parser() -> argparse.ArgumentParser:
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument("--url", default=argparse.SUPPRESS,
                        help=t("cli.opt.url"))
    parent.add_argument("--token", default=argparse.SUPPRESS,
                        help=t("cli.opt.token"))

    parser = argparse.ArgumentParser(prog="serialhub", description=t("cli.description"),
                                     parents=[parent])
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True

    def add(name: str, **kw: Any) -> argparse.ArgumentParser:
        return sub.add_parser(name, parents=[parent], **kw)

    add("list", help=t("cli.cmd.list"))
    add("ports", help=t("cli.cmd.ports"))

    p = add("status", help=t("cli.cmd.status"))
    p.add_argument("name", nargs="?", default=None)

    p = add("open", help=t("cli.cmd.open"))
    p.add_argument("name")
    p.add_argument("--baud", type=int, default=None)
    p.add_argument("--device", default=None)

    p = add("close", help=t("cli.cmd.close"))
    p.add_argument("name")

    p = add("set-device", help=t("cli.cmd.set_device"))
    p.add_argument("name")
    p.add_argument("--device", default=None)
    p.add_argument("--match", default=None, help=t("cli.arg.match"))
    p.add_argument("--no-reopen", action="store_true", help=t("cli.arg.no_reopen"))

    add("discover", help=t("cli.cmd.discover"))

    p = add("read", help=t("cli.cmd.read"))
    p.add_argument("name")
    p.add_argument("--since-seq", type=int, default=None)
    p.add_argument("--since-ts", type=int, default=None)
    p.add_argument("--filter", default=None, help=t("cli.arg.filter"))
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--strip-ansi", action="store_true")
    p.add_argument("--kinds", default=None, help=t("cli.arg.kinds"))

    p = add("search", help=t("cli.cmd.search"))
    p.add_argument("name")
    p.add_argument("regex")
    p.add_argument("--context", type=int, default=0)
    p.add_argument("--since-seq", type=int, default=None)
    p.add_argument("--limit", type=int, default=None)

    p = add("wait", help=t("cli.cmd.wait"))
    p.add_argument("name")
    p.add_argument("regex")
    p.add_argument("--timeout-ms", type=int, default=10000)
    p.add_argument("--since-seq", type=int, default=None)

    p = add("send", help=t("cli.cmd.send"))
    p.add_argument("name")
    p.add_argument("data", help=t("cli.arg.send_data"))
    p.add_argument("--eol", default=None, help=t("cli.arg.eol"))
    p.add_argument("--wait-regex", default=None)
    p.add_argument("--timeout-ms", type=int, default=None)

    p = add("snapshot", help=t("cli.cmd.snapshot"))
    p.add_argument("name")
    p.add_argument("--tail-lines", type=int, default=200)

    p = add("export", help=t("cli.cmd.export"))
    p.add_argument("name")
    p.add_argument("--path", default=None)
    p.add_argument("--format", default="raw", choices=["raw", "noansi", "json"])
    p.add_argument("--range", default=None, help=t("cli.arg.range"))

    p = add("mark", help=t("cli.cmd.mark"))
    p.add_argument("name")
    p.add_argument("label")

    p = add("clear", help=t("cli.cmd.clear"))
    p.add_argument("name")

    p = add("bridge", help=t("cli.cmd.bridge"))
    p.add_argument("action", choices=["start", "stop", "status"])
    p.add_argument("--port", required=True)
    p.add_argument("--mode", default="server", choices=["server", "client"])
    p.add_argument("--tcp-port", type=int, default=None)
    p.add_argument("--host", default=None)

    add("reload", help=t("cli.cmd.reload"))

    p = add("serve", help=t("cli.cmd.serve"))
    p.add_argument("--config", required=True)
    p.add_argument("--host", default=None)
    p.add_argument("--port", type=int, default=None)
    p.add_argument("--no-autostart", action="store_true")
    p.add_argument("--log-level", default=None)

    p = add("mcp", help=t("cli.cmd.mcp"))
    p.add_argument("--stdio", action="store_true", help=t("cli.arg.stdio"))
    p.add_argument("--transport", default="stdio", help=t("cli.arg.transport"))

    return parser


# --------------------------------------------------------------------------- #
# handlers
# --------------------------------------------------------------------------- #
def _dispatch(command: str, args: argparse.Namespace) -> int:
    url, token = _global_options(args)
    client = Client(url, token)
    if command in ("list", "ports"):
        env = client.list_ports()
    elif command == "status":
        env = client.status(args.name)
    elif command == "open":
        env = client.open(args.name, baud=args.baud, device=args.device)
    elif command == "close":
        env = client.close(args.name)
    elif command == "set-device":
        if (args.device is None) == (args.match is None):
            env = {"ok": False, "error": t("cli.error.set_device_one")}
        else:
            try:
                match = _parse_match_arg(args.match) if args.match is not None else None
            except ValueError as exc:
                env = {"ok": False, "error": str(exc)}
            else:
                env = client.set_device(args.name, device=args.device, match=match,
                                        reopen=not args.no_reopen)
    elif command == "discover":
        env = client.discover()
    elif command == "read":
        env = client.read(args.name, since_seq=args.since_seq, since_ts=args.since_ts,
                          filter=args.filter, limit=args.limit,
                          strip_ansi=args.strip_ansi, kinds=args.kinds)
    elif command == "search":
        env = client.search(args.name, args.regex, context=args.context,
                            since_seq=args.since_seq, limit=args.limit)
    elif command == "wait":
        env = client.wait(args.name, args.regex, timeout_ms=args.timeout_ms,
                          since_seq=args.since_seq)
    elif command == "send":
        env = client.send(args.name, _read_send_data(args.data),
                          eol=_resolve_eol(args.eol), wait_regex=args.wait_regex,
                          timeout_ms=args.timeout_ms)
    elif command == "snapshot":
        env = client.snapshot(args.name, tail_lines=args.tail_lines)
    elif command == "export":
        env = client.export(args.name, path=args.path, fmt=args.format, rng=args.range)
    elif command == "mark":
        env = client.mark(args.name, args.label)
    elif command == "clear":
        env = client.clear(args.name)
    elif command == "bridge":
        env = client.bridge(args.action, args.port, mode=args.mode,
                            tcp_port=args.tcp_port, host=args.host)
    elif command == "reload":
        env = client.reload()
    else:
        env = {"ok": False, "error": f"unknown command: {command}"}
    return _print_env(env)


def _cmd_serve(args: argparse.Namespace) -> int:
    """Run the daemon in-process. Heavy imports stay here (lazy)."""
    import uvicorn  # noqa: PLC0415 - lazy by design

    from .config import Config
    from .hub import Hub
    from .server import create_app

    cfg = Config.load(args.config)
    overrides: dict[str, Any] = {}
    if args.host is not None:
        overrides["host"] = args.host
    if args.port is not None:
        overrides["port"] = args.port
    if overrides:
        cfg = cfg.merge_overrides(**overrides)
    if args.no_autostart:
        for port_cfg in cfg.ports:
            port_cfg.autostart = False

    hub = Hub(cfg)
    hub.start()
    app = create_app(hub, cfg)
    try:
        uvicorn.run(app, host=cfg.server.host, port=cfg.server.port,
                    log_level=args.log_level or "info")
    except KeyboardInterrupt:
        pass
    finally:
        hub.stop()
    return 0


def _cmd_mcp(args: argparse.Namespace) -> int:
    from . import mcp_server  # noqa: PLC0415 - lazy by design

    transport = "stdio" if args.stdio else args.transport
    mcp_server.main(transport=transport)
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entry point. Returns the process exit code."""
    args = _build_parser().parse_args(argv)
    if args.command == "serve":
        return _cmd_serve(args)
    if args.command == "mcp":
        return _cmd_mcp(args)
    try:
        return _dispatch(args.command, args)
    except BrokenPipeError:
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
