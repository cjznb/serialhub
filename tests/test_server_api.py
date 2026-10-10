"""REST + WebSocket integration tests for :mod:`serialhub.server` (§9)."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from serialhub.server import create_app


# ---- health / ports / status --------------------------------------------- #
def test_health(client) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["status"] == "ok"
    assert "version" in body and "uptime_ms" in body


def test_api_ports(client) -> None:
    response = client.get("/api/ports")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert "system" in body and "ports" in body
    assert {port["name"] for port in body["ports"]} == {"t", "t2"}


def test_api_status(client) -> None:
    whole = client.get("/api/status").json()
    assert whole["ok"] is True
    assert "server" in whole and "ports" in whole

    single = client.get("/api/status", params={"name": "t"}).json()
    assert single["ok"] is True
    assert single["name"] == "t"
    assert "server" in single


# ---- open / close --------------------------------------------------------- #
def test_open_close(client) -> None:
    closed = client.post("/api/ports/t2/close")
    assert closed.status_code == 200 and closed.json()["ok"] is True

    opened = client.post("/api/ports/t2/open")
    assert opened.status_code == 200
    body = opened.json()
    assert body["ok"] is True and body["open"] is True


# ---- send / read ---------------------------------------------------------- #
def test_send_then_read(client) -> None:
    sent = client.post("/api/ports/t/send", json={"data": "hello"})
    assert sent.status_code == 200
    assert sent.json()["ok"] is True and sent.json()["sent"] == "hello"

    time.sleep(0.3)
    data = client.get("/api/ports/t/read", params={"kinds": "rx"}).json()
    assert data["ok"] is True
    assert any(line["text"] == "hello" for line in data["lines"])


# ---- wait / search -------------------------------------------------------- #
def test_wait_match_and_timeout(client, hub) -> None:
    hub.ingest("t", "PONG-123")
    matched = client.get(
        "/api/ports/t/wait", params={"regex": "PONG", "timeout_ms": 500}
    ).json()
    assert matched["ok"] is True and matched["matched"] is True
    assert matched["line"]["text"] == "PONG-123"

    timed_out = client.get(
        "/api/ports/t/wait", params={"regex": "ABSENT", "timeout_ms": 200}
    ).json()
    assert timed_out["ok"] is True and timed_out["matched"] is False


def test_search(client, hub) -> None:
    hub.ingest("t", "abc 42 def")
    body = client.get("/api/ports/t/search", params={"regex": r"\d+"}).json()
    assert body["ok"] is True
    assert body["count"] >= 1
    assert body["hits"][0]["match"] == "42"


# ---- snapshot / mark / export -------------------------------------------- #
def test_snapshot(client, hub) -> None:
    hub.ingest("t", "s1")
    hub.ingest("t", "s2")
    body = client.get("/api/ports/t/snapshot", params={"tail_lines": 1}).json()
    assert body["ok"] is True and body["count"] == 1
    assert body["lines"][0]["text"] == "s2"


def test_mark(client) -> None:
    body = client.post("/api/ports/t/mark", json={"label": "HERE"}).json()
    assert body["ok"] is True
    assert body["label"] == "HERE"
    assert isinstance(body["seq"], int)


def test_export(client, hub, tmp_path) -> None:
    hub.ingest("t", "row")
    target = tmp_path / "exp.txt"
    body = client.post(
        "/api/ports/t/export", json={"format": "raw", "path": str(target)}
    ).json()
    assert body["ok"] is True and body["format"] == "raw"
    assert target.exists()
    assert body["bytes"] == target.stat().st_size


# ---- bridge --------------------------------------------------------------- #
def test_bridge_start_stop(client, free_tcp_port) -> None:
    port = free_tcp_port()
    started = client.post("/api/bridge", json={
        "action": "start", "port": "t", "mode": "server", "tcp_port": port,
    }).json()
    assert started["ok"] is True
    assert started["active"] is True and started["tcp_port"] == port

    stopped = client.post("/api/bridge", json={"action": "stop", "port": "t"}).json()
    assert stopped["ok"] is True and stopped["active"] is False


# ---- error paths ---------------------------------------------------------- #
def test_unknown_port_returns_404(client) -> None:
    response = client.post("/api/ports/nope/close")
    assert response.status_code == 404
    body = response.json()
    assert body["ok"] is False and "error" in body

    response2 = client.get("/api/ports/nope/read")
    assert response2.status_code == 404
    assert response2.json()["ok"] is False


# ---- websocket ------------------------------------------------------------ #
def test_websocket_hello(client) -> None:
    with client.websocket_connect("/ws") as websocket:
        message = websocket.receive_json()
        assert message["type"] == "hello"
        assert "ports" in message


# ---- token auth ----------------------------------------------------------- #
def test_token_auth(make_config, hub_factory) -> None:
    cfg = make_config(token="sekret")
    hub = hub_factory(cfg)
    with TestClient(create_app(hub, cfg)) as tc:
        unauth = tc.get("/api/ports")
        assert unauth.status_code == 401
        assert unauth.json() == {"ok": False, "error": "unauthorized"}

        ok = tc.get("/api/ports", headers={"Authorization": "Bearer sekret"})
        assert ok.status_code == 200
        assert ok.json()["ok"] is True

        # /health is not under /api/* and stays open
        assert tc.get("/health").status_code == 200
