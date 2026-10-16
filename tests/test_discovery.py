"""Unit tests for :mod:`serialhub.discovery`, its config wiring, and serialport
resolve/re-resolve behaviour.

All enumeration is stubbed (``ports=`` / monkeypatched ``comports``); no real
hardware is opened. The serialport tests monkeypatch ``serial.serial_for_url``
so no COM port is touched.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from serialhub import discovery
from serialhub.config import Config, PortConfig
from serialhub.serialport import SerialPortWorker

# --------------------------------------------------------------------------- #
# Stub enumeration: mirrors the two real adapters on this machine.
# --------------------------------------------------------------------------- #
def _fake_ports() -> list[SimpleNamespace]:
    return [
        SimpleNamespace(
            device="COM11",
            description="USB-Enhanced-SERIAL CH343 (COM11)",
            hwid="USB VID:PID=1A86:55D3 SER=5A46004316 LOCATION=1-2.1.2",
            vid=0x1A86,
            pid=0x55D3,
            serial_number="5A46004316",
        ),
        SimpleNamespace(
            device="COM12",
            description="USB-SERIAL CH340 (COM12)",
            hwid="USB VID:PID=1A86:7523 SER= LOCATION=1-2.1.4",
            vid=0x1A86,
            pid=0x7523,
            serial_number="",
        ),
        SimpleNamespace(
            device="COM3",
            description="USB-SERIAL CH340 (COM3)",
            hwid="USB VID:PID=1A86:7523 SER= LOCATION=1-2.1.6",
            vid=0x1A86,
            pid=0x7523,
            serial_number="",
        ),
    ]


# --------------------------------------------------------------------------- #
# (a) resolver: scoring / selection
# --------------------------------------------------------------------------- #
def test_description_substring_is_case_insensitive() -> None:
    # Given two CH340 ports (COM12, COM3) and a lowercase needle,
    # When resolving by description,
    # Then the first candidate (sorted by device) is chosen.
    out = discovery.resolve({"description": "ch340"}, ports=_fake_ports())
    assert out["device"] == "COM12"
    assert out["score"] == 1
    assert out["matched"] == ["description"]
    assert [c["device"] for c in out["candidates"]] == ["COM12", "COM3"]


def test_vid_pid_exact_match() -> None:
    out = discovery.resolve({"vid": 0x1A86, "pid": 0x55D3}, ports=_fake_ports())
    assert out["device"] == "COM11"
    assert out["score"] == 2


def test_vid_pid_accepts_hex_strings() -> None:
    out = discovery.resolve({"vid": "0x1A86", "pid": "0x7523"}, ports=_fake_ports())
    assert out["device"] == "COM12"  # CH340; sorted first among the two CH340s


def test_hwid_substring_match() -> None:
    out = discovery.resolve({"hwid": "55D3"}, ports=_fake_ports())
    assert out["device"] == "COM11"


def test_serial_substring_match() -> None:
    out = discovery.resolve({"serial": "5a46"}, ports=_fake_ports())
    assert out["device"] == "COM11"


def test_index_disambiguates_ties() -> None:
    ports = _fake_ports()
    assert discovery.resolve({"description": "CH340"}, ports=ports)["device"] == "COM12"
    assert discovery.resolve({"description": "CH340", "index": 1}, ports=ports)["device"] == "COM3"


def test_no_match_returns_none_device() -> None:
    out = discovery.resolve({"description": "NOPE"}, ports=_fake_ports())
    assert out["device"] is None
    assert out["candidates"] == []
    assert out["matched"] == []
    assert out["score"] == 0


def test_index_out_of_range_returns_none() -> None:
    out = discovery.resolve({"description": "CH340", "index": 5}, ports=_fake_ports())
    assert out["device"] is None


def test_all_criteria_must_match() -> None:
    # vid matches COM11 but pid does not -> no candidate.
    out = discovery.resolve({"vid": 0x1A86, "pid": 0x0001}, ports=_fake_ports())
    assert out["device"] is None


def test_unknown_key_in_spec_raises() -> None:
    with pytest.raises(ValueError):
        discovery.resolve({"nope": "x"}, ports=_fake_ports())


def test_describe_renders_readable_summary() -> None:
    assert discovery.describe({"description": "CH340"}) == "description~'CH340'"
    assert "vid=0x1A86" in discovery.describe({"vid": 0x1A86})
    assert discovery.describe({}) == "any port"


# --------------------------------------------------------------------------- #
# (b) config validation
# --------------------------------------------------------------------------- #
def test_port_with_match_and_empty_device_loads() -> None:
    cfg = Config.from_dict({
        "ports": [{"name": "a", "device": "", "match": {"description": "CH340"}}],
    })
    pc = cfg.port("a")
    assert pc.device == ""
    assert pc.match == {"description": "CH340"}
    # match is serialized back out
    assert cfg.to_dict()["ports"][0]["match"] == {"description": "CH340"}


def test_port_with_match_omitting_device_loads() -> None:
    cfg = Config.from_dict({
        "ports": [{"name": "a", "match": {"vid": 0x1A86, "pid": 0x55D3}}],
    })
    assert cfg.port("a").device == ""
    assert cfg.port("a").match == {"vid": 0x1A86, "pid": 0x55D3}


def test_unknown_match_key_raises_value_error() -> None:
    with pytest.raises(ValueError) as excinfo:
        Config.from_dict({
            "ports": [{"name": "a", "match": {"bogus": "x"}}],
        })
    assert "match" in str(excinfo.value) and "bogus" in str(excinfo.value)


def test_port_without_device_or_match_raises() -> None:
    with pytest.raises(ValueError) as excinfo:
        Config.from_dict({"ports": [{"name": "a", "device": ""}]})
    msg = str(excinfo.value)
    assert "device" in msg and "match" in msg


def test_bad_vid_raises_value_error() -> None:
    with pytest.raises(ValueError) as excinfo:
        Config.from_dict({"ports": [{"name": "a", "match": {"vid": "not-a-number"}}]})
    assert "vid" in str(excinfo.value)


def test_fixed_device_still_required_when_no_match() -> None:
    # Regression: the fixed-device path is unchanged.
    cfg = Config.from_dict({
        "ports": [{"name": "a", "device": "loop://"}],
    })
    assert cfg.port("a").device == "loop://"
    assert cfg.port("a").match is None


# --------------------------------------------------------------------------- #
# (c) serialport-level resolve + re-resolve
# --------------------------------------------------------------------------- #
class _StubHub:
    """Minimal Hub stand-in: records status broadcasts, ignores ingest."""

    def __init__(self) -> None:
        self.events: list[dict] = []

    def _broadcast(self, event: dict) -> None:
        self.events.append(event)

    def ingest(self, *args, **kwargs) -> None:  # pragma: no cover - unused here
        pass


class _FakeSerial:
    """Just enough of a pyserial object for the connect path."""

    def __init__(self, *args, **kwargs) -> None:
        self.closed = False
        self.dtr = None
        self.rts = None

    def setDTR(self, value: bool) -> None:
        self.dtr = value

    def setRTS(self, value: bool) -> None:
        self.rts = value

    def close(self) -> None:
        self.closed = True

    def read(self, n: int) -> bytes:  # pragma: no cover - not driven here
        return b""


def _match_port(match: dict) -> PortConfig:
    return PortConfig(name="m", device="", match=match, autostart=False)


def test_match_port_resolves_to_stubbed_device(monkeypatch) -> None:
    pc = _match_port({"description": "CH340"})
    opened: list[str] = []

    def fake_resolve(spec, ports=None):
        assert spec == {"description": "CH340"}
        return {"device": "COM12", "score": 1, "candidates": [], "matched": ["description"]}

    def fake_for_url(device, **kwargs):
        opened.append(device)
        return _FakeSerial()

    monkeypatch.setattr(discovery, "resolve", fake_resolve)
    monkeypatch.setattr("serial.serial_for_url", fake_for_url)

    worker = SerialPortWorker(pc, _StubHub())
    assert worker._uses_match is True

    assert worker._try_connect() is True
    assert pc.device == "COM12"            # resolved device written back for hub status
    assert worker.resolved_device == "COM12"
    assert opened == ["COM12"]
    assert worker.last_error is None


def test_match_port_reresolves_on_reconnect(monkeypatch) -> None:
    pc = _match_port({"vid": 0x1A86, "pid": 0x7523})
    devices = iter(["COM12", "COM99"])

    def fake_resolve(spec, ports=None):
        return {"device": next(devices), "score": 2, "candidates": [], "matched": []}

    monkeypatch.setattr(discovery, "resolve", fake_resolve)
    monkeypatch.setattr("serial.serial_for_url", lambda device, **kw: _FakeSerial())

    worker = SerialPortWorker(pc, _StubHub())
    assert worker._try_connect() is True
    assert worker.resolved_device == "COM12"

    # Simulate a drop (device unplugged) then a replug on a different COM.
    worker._close_serial()
    assert worker.is_open is False

    assert worker._try_connect() is True
    assert worker.resolved_device == "COM99"   # re-resolved, not stale COM12


def test_match_port_no_match_sets_error_without_crashing(monkeypatch) -> None:
    pc = _match_port({"description": "CH340"})

    monkeypatch.setattr(
        discovery, "resolve",
        lambda spec, ports=None: {"device": None, "score": 0, "candidates": [], "matched": []},
    )
    monkeypatch.setattr(discovery, "describe", lambda spec: "description~'CH340'")
    monkeypatch.setattr("serial.serial_for_url", lambda device, **kw: _FakeSerial())

    worker = SerialPortWorker(pc, _StubHub())
    assert worker._try_connect() is False
    assert worker.is_open is False
    assert "no device matched" in (worker.last_error or "")
    assert "CH340" in (worker.last_error or "")


def test_fixed_device_does_not_re_resolve(monkeypatch) -> None:
    # Regression: a fixed-device port must never consult discovery.
    pc = PortConfig(name="f", device="loop://", autostart=False)
    opened: list[str] = []

    def boom(*args, **kwargs):
        raise AssertionError("discovery.resolve must not be called for fixed device")

    monkeypatch.setattr(discovery, "resolve", boom)
    monkeypatch.setattr("serial.serial_for_url", lambda device, **kw: (opened.append(device), _FakeSerial())[1])

    worker = SerialPortWorker(pc, _StubHub())
    assert worker._uses_match is False
    assert worker._try_connect() is True
    assert opened == ["loop://"]
    assert worker.resolved_device == "loop://"
