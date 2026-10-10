"""Unit tests for :mod:`serialhub.config` (§5)."""

from __future__ import annotations

import json
import os

import pytest
import yaml

from serialhub.config import Config


def _write_yaml(path, data) -> None:
    path.write_text(yaml.safe_dump(data), encoding="utf-8")


def _write_json(path, data) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


# ---- loading: YAML / JSON + defaults merge -------------------------------- #
def test_load_yaml_merges_top_level_defaults(tmp_path) -> None:
    path = tmp_path / "c.yaml"
    _write_yaml(path, {
        "defaults": {"baud": 9600, "parity": "N", "buffer_lines": 10},
        "ports": [{"name": "a", "device": "loop://"}],
    })
    cfg = Config.load(str(path))
    pc = cfg.port("a")
    assert pc.baud == 9600
    assert pc.parity == "N"
    assert pc.buffer_lines == 10
    assert cfg.path == os.path.abspath(str(path))


def test_load_json_merges_buffer_defaults(tmp_path) -> None:
    path = tmp_path / "c.json"
    _write_json(path, {
        "buffer_defaults": {"lines": 123, "bytes": 456},
        "ports": [
            {"name": "a", "device": "loop://"},
            {"name": "b", "device": "loop://", "buffer_lines": 7},
        ],
    })
    cfg = Config.load(str(path))
    assert cfg.port("a").buffer_lines == 123
    assert cfg.port("a").buffer_bytes == 456
    assert cfg.port("b").buffer_lines == 7        # per-port value wins
    assert cfg.port("b").buffer_bytes == 456      # buffer_default fills the gap


# ---- validation ----------------------------------------------------------- #
@pytest.mark.parametrize("ports,needle", [
    ([{"name": "a", "device": "loop://", "parity": "X"}], "parity"),
    ([{"name": "a", "device": "loop://"}, {"name": "a", "device": "loop://"}], "duplicate"),
    ([{"name": "a", "device": ""}], "device"),
    ([{"name": "a", "device": "loop://", "data_bits": 9}], "data_bits"),
])
def test_validation_errors_raise_value_error(tmp_path, ports, needle) -> None:
    path = tmp_path / "bad.json"
    _write_json(path, {"ports": ports})
    with pytest.raises(ValueError) as excinfo:
        Config.load(str(path))
    assert needle in str(excinfo.value)


# ---- serialization -------------------------------------------------------- #
def test_to_dict_redacts_token() -> None:
    cfg = Config.from_dict({
        "server": {"token": "secret"},
        "ports": [{"name": "a", "device": "loop://"}],
    })
    assert cfg.to_dict()["server"]["token"] == "***"
    assert cfg.to_dict(redact=False)["server"]["token"] == "secret"


def test_to_dict_without_token_stays_none() -> None:
    cfg = Config.from_dict({"ports": [{"name": "a", "device": "loop://"}]})
    assert cfg.to_dict()["server"]["token"] is None


# ---- lookup --------------------------------------------------------------- #
def test_port_and_port_names() -> None:
    cfg = Config.from_dict({
        "ports": [{"name": "a", "device": "loop://"},
                  {"name": "b", "device": "loop://"}],
    })
    assert cfg.port_names() == ["a", "b"]
    assert cfg.port("a").name == "a"
    with pytest.raises(KeyError):
        cfg.port("missing")


# ---- overrides ------------------------------------------------------------ #
def test_merge_overrides_returns_new_config() -> None:
    cfg = Config.from_dict({"ports": [{"name": "a", "device": "loop://"}]})
    out = cfg.merge_overrides(host="0.0.0.0", port=9000, token="tok", autostart=False)
    assert out.server.host == "0.0.0.0"
    assert out.server.port == 9000
    assert out.server.token == "tok"
    assert all(not pc.autostart for pc in out.ports)
    # original untouched
    assert cfg.server.host == "127.0.0.1"
    assert cfg.ports[0].autostart is True


# ---- numeric coercion / regression ---------------------------------------- #
def test_numeric_fields_coerced_from_strings(tmp_path) -> None:
    path = tmp_path / "c.yaml"
    path.write_text(
        "ports:\n"
        "  - name: a\n"
        "    device: loop://\n"
        "    reconnect_ms: '1000'\n"
        "    reconnect_max_ms: '10000'\n"
        "    flush_ms: '50'\n",
        encoding="utf-8",
    )
    pc = Config.load(str(path)).port("a")
    assert pc.reconnect_ms == 1000
    assert pc.reconnect_max_ms == 10000
    assert pc.flush_ms == 50


def test_glued_hashcomment_rejected_at_load(tmp_path) -> None:
    # Regression: `reconnect_max_ms: 10000# comment` (no space before '#') keeps the
    # whole token as a YAML string; it used to slip through validation and crash the
    # worker thread (port reported open but never read). Must fail at load, naming field.
    path = tmp_path / "c.yaml"
    path.write_text(
        "ports:\n  - name: a\n    device: loop://\n    reconnect_max_ms: 10000# 粘连\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError) as excinfo:
        Config.load(str(path))
    msg = str(excinfo.value)
    assert "reconnect_max_ms" in msg and "integer" in msg


def test_reconnect_max_below_reconnect_ms_rejected(tmp_path) -> None:
    path = tmp_path / "c.yaml"
    path.write_text(
        "ports:\n  - name: a\n    device: loop://\n    reconnect_ms: 5000\n    reconnect_max_ms: 1000\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError) as excinfo:
        Config.load(str(path))
    assert "reconnect_max_ms" in str(excinfo.value)
