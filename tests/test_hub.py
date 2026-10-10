"""Integration tests for :class:`serialhub.hub.Hub` (§6) on ``loop://`` ports."""

from __future__ import annotations

import os
import time

SETTLE = 0.3  # seconds for the worker read loop to ingest the loopback echo


# ---- lifecycle ------------------------------------------------------------ #
def test_open_close_is_open(hub) -> None:
    assert hub.is_open("t") is True
    assert hub.is_open("t2") is False       # autostart false

    closed = hub.close("t")
    assert closed["open"] is False
    assert hub.is_open("t") is False

    opened = hub.open("t")
    assert opened["open"] is True
    assert hub.is_open("t") is True

    opened2 = hub.open("t2")                 # open the non-autostart port
    assert opened2["open"] is True


# ---- send / read ---------------------------------------------------------- #
def test_send_writes_and_ingests_tx_and_echoes_rx(hub) -> None:
    result = hub.send("t", "ping")
    assert result["port"] == "t"
    assert result["sent"] == "ping"
    assert result["sent_bytes"] == len("ping\r\n".encode("utf-8"))

    time.sleep(SETTLE)
    tx = hub.read("t", kinds={"tx"})
    rx = hub.read("t", kinds={"rx"})
    assert any(line["text"] == "ping" for line in tx["lines"])
    assert any(line["text"] == "ping" for line in rx["lines"])


def test_read_cursor_twice_yields_no_duplicates(hub) -> None:
    hub.ingest("t", "a")
    hub.ingest("t", "b")
    first = hub.read("t", since_seq=0)
    second = hub.read("t", since_seq=first["next_seq"])
    first_seqs = {line["seq"] for line in first["lines"]}
    second_seqs = {line["seq"] for line in second["lines"]}
    assert first_seqs.isdisjoint(second_seqs)
    assert first["next_seq"] == max(first_seqs)


# ---- wait_for ------------------------------------------------------------- #
def test_wait_for_returns_immediately_for_existing_match(hub) -> None:
    hub.ingest("t", "SENTINEL-7")
    result = hub.wait_for("t", "SENTINEL", timeout_ms=500)
    assert result["matched"] is True
    assert result["line"]["text"] == "SENTINEL-7"
    assert result["seq"] == result["line"]["seq"]
    assert result["port"] == "t"


def test_wait_for_timeout_is_not_an_error(hub) -> None:
    result = hub.wait_for("t", "NEVER-MATCHES", timeout_ms=200)
    assert result["matched"] is False
    assert result["line"] is None
    assert result["seq"] is None
    assert result["port"] == "t"


# ---- mark / snapshot / export -------------------------------------------- #
def test_mark_inserts_kind_mark_line(hub) -> None:
    result = hub.mark("t", "BOOKMARK")
    assert result["port"] == "t"
    assert result["label"] == "BOOKMARK"
    assert isinstance(result["seq"], int)
    assert isinstance(result["ts_ms"], int)
    marks = hub.read("t", kinds={"mark"})
    assert any(line["text"] == "BOOKMARK" for line in marks["lines"])


def test_snapshot_tail_lines(hub) -> None:
    for i in range(5):
        hub.ingest("t", f"line{i}")
    snap = hub.snapshot("t", tail_lines=2)
    assert snap["port"] == "t"
    assert snap["count"] == 2
    assert [line["text"] for line in snap["lines"]] == ["line3", "line4"]


def test_export_to_path(hub, tmp_path) -> None:
    hub.ingest("t", "x")
    hub.ingest("t", "y")
    target = tmp_path / "out.txt"
    result = hub.export("t", path=str(target), fmt="raw")
    assert result["path"] == os.path.abspath(str(target))
    assert result["format"] == "raw"
    assert result["count"] == 2
    assert target.read_text(encoding="utf-8") == "x\ny\n"
    assert result["bytes"] == len("x\ny\n".encode("utf-8"))


# ---- status shapes (§6.1) ------------------------------------------------- #
def test_list_ports_key_shapes(hub) -> None:
    data = hub.list_ports()
    assert set(data.keys()) == {"system", "ports"}
    assert {p["name"] for p in data["ports"]} == {"t", "t2"}
    expected_port_keys = {
        "name", "device", "open", "baud", "data_bits", "parity", "stop_bits",
        "flow", "rx_lines", "tx_lines", "last_error", "reconnect_count",
        "buffer", "tcp_bridge",
    }
    for port in data["ports"]:
        assert expected_port_keys.issubset(port.keys())
        assert set(port["buffer"].keys()) == {
            "count", "bytes", "first_seq", "last_seq", "dropped_total",
        }


def test_status_shapes(hub) -> None:
    single = hub.status("t")
    assert single["name"] == "t"
    assert "server" in single
    assert set(single["server"].keys()) == {"host", "port", "version", "uptime_ms"}

    whole = hub.status()
    assert set(whole.keys()) == {"server", "ports"}


# ---- reload --------------------------------------------------------------- #
def test_reload_returns_summary_and_applies_changes(hub, make_config) -> None:
    new_cfg = make_config(ports=[
        {"name": "t", "device": "loop://", "autostart": True,
         "buffer_lines": 64, "buffer_bytes": 1 << 20},
        {"name": "t3", "device": "loop://", "autostart": True,
         "buffer_lines": 64, "buffer_bytes": 1 << 20},
    ])
    result = hub.reload(new_cfg)
    assert set(result.keys()) == {"added", "removed", "restarted", "updated"}
    assert "t3" in result["added"]
    assert "t2" in result["removed"]
    assert {p["name"] for p in hub.list_ports()["ports"]} == {"t", "t3"}
