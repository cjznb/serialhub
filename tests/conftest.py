"""Shared pytest fixtures for the serialhub test suite.

Every fixture uses ``loop://`` virtual serial ports only — no real hardware,
no COM ports. Hubs, bridges and worker threads are always torn down via
finalizers so pytest exits cleanly and never hangs.
"""

from __future__ import annotations

import socket
import sys
from pathlib import Path
from typing import Any, Optional

import pytest

# Make ``serialhub`` importable regardless of how pytest is invoked.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from serialhub.config import Config  # noqa: E402
from serialhub.hub import Hub  # noqa: E402
from serialhub.server import create_app  # noqa: E402


def pytest_configure(config) -> None:
    """Silence a third-party Starlette/anyio deprecation so the run stays clean."""
    config.addinivalue_line(
        "filterwarnings",
        "ignore:.*anyio.abc.BlockingPortal alias is deprecated.*:DeprecationWarning",
    )


def _default_ports() -> list[dict[str, Any]]:
    """Two loopback ports: ``t`` autostarts, ``t2`` waits for an explicit open.

    ``buffer_lines`` is intentionally small so eviction can be exercised.
    """
    return [
        {"name": "t", "device": "loop://", "autostart": True,
         "buffer_lines": 64, "buffer_bytes": 1 << 20},
        {"name": "t2", "device": "loop://", "autostart": False,
         "buffer_lines": 64, "buffer_bytes": 1 << 20},
    ]


def build_config(token: Optional[str] = None,
                 ports: Optional[list[dict[str, Any]]] = None) -> Config:
    """Build a validated :class:`Config` backed by ``loop://`` ports only."""
    raw: dict[str, Any] = {
        "server": {"host": "127.0.0.1", "port": 8765, "token": token, "cors": True},
        "defaults": {
            "baud": 115200, "data_bits": 8, "parity": "N", "stop_bits": 1,
            "flow": "none", "eol": "\r\n", "encoding": "utf-8",
            "reconnect_ms": 200, "reconnect_max_ms": 500, "flush_ms": 20,
            "dtr": True, "rts": True,
        },
        "ports": _default_ports() if ports is None else ports,
    }
    return Config.from_dict(raw)


@pytest.fixture
def make_config():
    """Factory: ``make_config(token=..., ports=...)`` -> validated Config."""
    return build_config


@pytest.fixture
def cfg(make_config) -> Config:
    return make_config()


@pytest.fixture
def hub(cfg: Config):
    """A started Hub on ``loop://`` ports; stopped (idempotent) on teardown."""
    h = Hub(cfg)
    h.start()
    try:
        yield h
    finally:
        h.stop()


@pytest.fixture
def hub_factory():
    """Factory that owns extra Hubs; every one is stopped on teardown."""
    created: list[Hub] = []

    def _make(cfg: Config) -> Hub:
        h = Hub(cfg)
        h.start()
        created.append(h)
        return h

    yield _make
    for h in created:
        try:
            h.stop()
        except Exception:  # noqa: BLE001 - best-effort teardown
            pass


@pytest.fixture
def client(hub, cfg):
    """FastAPI TestClient built from ``create_app(hub, cfg)``."""
    from fastapi.testclient import TestClient  # imported after configure (filter active)

    with TestClient(create_app(hub, cfg)) as tc:
        yield tc


@pytest.fixture
def free_tcp_port():
    """Return a callable yielding a currently-free loopback TCP port."""
    def _get() -> int:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", 0))
            return int(s.getsockname()[1])
        finally:
            s.close()

    return _get
