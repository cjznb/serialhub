"""Tests for the runtime, transient port-remap feature.

Covered surface:
- ``Hub.set_device`` (device path, match path, ``reopen=False``, validation).
- ``Hub.list_devices`` (shape + sorting).
- REST ``POST /api/ports/{name}/device`` and ``GET /api/devices``.
- CLI ``--match`` parsing helper.

All enumeration is stubbed and only loopback (``loop://``) ports are used — no
real hardware, no COM ports. ``serial.serial_for_url`` is never faked here
because ``loop://`` is a genuine pyserial URL.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from serialhub import discovery

# --------------------------------------------------------------------------- #
# Stub enumeration (intentionally out of order to prove sorting).
# --------------------------------------------------------------------------- #
def _stub_ports() -> list[SimpleNamespace]:
    return [
        SimpleNamespace(device="COM3", description="CH340 (COM3)", hwid="HW3",
                        vid=0x1A86, pid=0x7523, serial_number=""),
        SimpleNamespace(device="COM11", description="CH343 (COM11)", hwid="HW11",
                        vid=0x1A86, pid=0x55D3, serial_number="5A46"),
    ]


def _resolve_to_loop(spec, ports=None):  # pragma: no cover - trivial stub
    return {"device": "loop://", "score": 1, "candidates": [], "matched": ["description"]}


# --------------------------------------------------------------------------- #
# set_device: device path
# --------------------------------------------------------------------------- #
def test_set_device_device_returns_status_and_preserves_buffer(hub) -> None:
    # Given a line already in the buffer,
    hub.ingest("t", "keep-me")
    # When remapping to a (same) fixed device,
    out = hub.set_device("t", device="loop://")
    # Then the returned dict is the port status and the buffer is intact.
    assert out["name"] == "t"
    assert out["device"] == "loop://"
    assert out["open"] is True
    assert "buffer" in out
    snap = hub.snapshot("t")
    assert any(line["text"] == "keep-me" for line in snap["lines"])


def test_set_device_device_clears_match(make_config, hub_factory, monkeypatch) -> None:
    monkeypatch.setattr(discovery, "resolve", _resolve_to_loop)
    cfg = make_config(ports=[{
        "name": "m", "match": {"description": "CH340"}, "autostart": False,
        "buffer_lines": 64, "buffer_bytes": 1 << 20,
    }])
    h = hub_factory(cfg)
    assert h.config.port("m").match == {"description": "CH340"}

    out = h.set_device("m", device="loop://")
    assert h.config.port("m").match is None
    assert h.config.port("m").device == "loop://"
    assert out["device"] == "loop://"


# --------------------------------------------------------------------------- #
# set_device: match path
# --------------------------------------------------------------------------- #
def test_set_device_match_resolves_and_writes_back(hub, monkeypatch) -> None:
    monkeypatch.setattr(discovery, "resolve", _resolve_to_loop)
    out = hub.set_device("t", match={"description": "CH340"})
    # The spec is stored, pc.device is blanked then re-resolved by the worker.
    assert hub.config.port("t").match == {"description": "CH340"}
    assert hub.config.port("t").device == "loop://"
    assert out["device"] == "loop://"
    assert out["open"] is True
    assert hub._workers["t"]._uses_match is True


# --------------------------------------------------------------------------- #
# set_device: reopen=False (mapping only)
# --------------------------------------------------------------------------- #
def test_set_device_reopen_false_keeps_running_worker(hub) -> None:
    worker_before = hub._workers["t"]
    out = hub.set_device("t", device="loop://", reopen=False)
    assert hub._workers["t"] is worker_before        # not restarted
    assert out["name"] == "t"
    assert hub._workers["t"].is_open                 # untouched, still open


def test_set_device_reopen_false_updates_mapping_only(hub) -> None:
    worker_before = hub._workers["t"]
    hub.set_device("t", match={"description": "CH340"}, reopen=False)
    pc = hub.config.port("t")
    assert pc.match == {"description": "CH340"}
    assert pc.device == ""
    assert hub._workers["t"] is worker_before


# --------------------------------------------------------------------------- #
# set_device: validation
# --------------------------------------------------------------------------- #
def test_set_device_requires_exactly_one_of_device_or_match(hub) -> None:
    with pytest.raises(ValueError):
        hub.set_device("t")                                        # neither
    with pytest.raises(ValueError):
        hub.set_device("t", device="loop://", match={"description": "X"})  # both


def test_set_device_empty_device_rejected(hub) -> None:
    with pytest.raises(ValueError):
        hub.set_device("t", device="")


def test_set_device_non_string_device_rejected(hub) -> None:
    with pytest.raises(ValueError):
        hub.set_device("t", device=123)  # type: ignore[arg-type]


def test_set_device_unknown_match_key_rejected(hub) -> None:
    with pytest.raises(ValueError) as excinfo:
        hub.set_device("t", match={"bogus": "x"})
    assert "bogus" in str(excinfo.value)


def test_set_device_bad_vid_rejected(hub) -> None:
    with pytest.raises(ValueError):
        hub.set_device("t", match={"vid": "not-a-number"})


def test_set_device_non_mapping_match_rejected(hub) -> None:
    with pytest.raises(ValueError):
        hub.set_device("t", match="CH340")  # type: ignore[arg-type]


def test_set_device_unknown_port_raises_keyerror(hub) -> None:
    with pytest.raises(KeyError):
        hub.set_device("nope", device="loop://")


# --------------------------------------------------------------------------- #
# list_devices
# --------------------------------------------------------------------------- #
def test_list_devices_shape_and_sorting(hub, monkeypatch) -> None:
    import serialhub.hub as hub_module

    monkeypatch.setattr(hub_module._list_ports, "comports", lambda: list(_stub_ports()))
    out = hub.list_devices()
    devices = out["devices"]
    # Sorted by device name → COM11 before COM3; index is the sorted position.
    assert [d["device"] for d in devices] == ["COM11", "COM3"]
    assert [d["index"] for d in devices] == [0, 1]
    assert devices[0] == {
        "index": 0, "device": "COM11", "description": "CH343 (COM11)",
        "hwid": "HW11", "vid": 0x1A86, "pid": 0x55D3,
    }


def test_list_devices_empty(hub, monkeypatch) -> None:
    import serialhub.hub as hub_module

    monkeypatch.setattr(hub_module._list_ports, "comports", lambda: [])
    assert hub.list_devices() == {"devices": []}


# --------------------------------------------------------------------------- #
# REST: /api/devices + /api/ports/{name}/device
# --------------------------------------------------------------------------- #
def test_rest_devices(client) -> None:
    body = client.get("/api/devices").json()
    assert body["ok"] is True
    assert isinstance(body["devices"], list)


def test_rest_set_device_device(client) -> None:
    resp = client.post("/api/ports/t/device", json={"device": "loop://"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["name"] == "t"
    assert body["device"] == "loop://"
    assert body["open"] is True


def test_rest_set_device_match(client, monkeypatch) -> None:
    monkeypatch.setattr(discovery, "resolve", _resolve_to_loop)
    body = client.post("/api/ports/t/device", json={"match": {"description": "CH340"}}).json()
    assert body["ok"] is True
    assert body["device"] == "loop://"


def test_rest_set_device_missing_options_is_400(client) -> None:
    resp = client.post("/api/ports/t/device", json={})
    assert resp.status_code == 400
    assert resp.json()["ok"] is False


def test_rest_set_device_unknown_port_is_404(client) -> None:
    resp = client.post("/api/ports/nope/device", json={"device": "loop://"})
    assert resp.status_code == 404
    assert resp.json()["ok"] is False


# --------------------------------------------------------------------------- #
# CLI: --match parsing helper
# --------------------------------------------------------------------------- #
def test_parse_match_arg_json_object() -> None:
    from serialhub.cli import _parse_match_arg

    assert _parse_match_arg('{"description": "CH340"}') == {"description": "CH340"}


def test_parse_match_arg_compact_pairs() -> None:
    from serialhub.cli import _parse_match_arg

    assert _parse_match_arg("description=CH340,vid=0x1A86") == {
        "description": "CH340", "vid": "0x1A86",
    }


def test_parse_match_arg_rejects_junk() -> None:
    from serialhub.cli import _parse_match_arg

    with pytest.raises(ValueError):
        _parse_match_arg("nonsense")
    with pytest.raises(ValueError):
        _parse_match_arg("{bad json}")
    with pytest.raises(ValueError):
        _parse_match_arg('["not", "an", "object"]')
