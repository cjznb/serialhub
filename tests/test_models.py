"""Unit tests for :mod:`serialhub.models` (§3)."""

from __future__ import annotations

import pytest

from serialhub.models import Line, has_ansi, resolve_eol, strip_ansi

COLORED = "\x1b[31mred\x1b[0m"


def test_line_to_dict_keeps_ansi_bytes() -> None:
    line = Line(seq=1, port="t", ts_ms=1000, text=COLORED, ansi=True, kind="rx")
    assert line.to_dict() == {
        "seq": 1, "port": "t", "ts_ms": 1000, "text": COLORED,
        "ansi": True, "kind": "rx",
    }


def test_line_to_dict_strip_removes_ansi() -> None:
    line = Line(seq=2, port="t", ts_ms=2000, text=COLORED, ansi=True)
    stripped = line.to_dict(strip=True)
    assert stripped["text"] == "red"
    assert stripped["seq"] == 2 and stripped["kind"] == "rx"


def test_ansi_helpers() -> None:
    assert has_ansi(COLORED) is True
    assert has_ansi("plain") is False
    assert strip_ansi(COLORED) == "red"
    assert strip_ansi("plain") == "plain"


@pytest.mark.parametrize("value,expected", [
    ("crlf", b"\r\n"),
    ("lf", b"\n"),
    ("cr", b"\r"),
    ("none", b""),
    ("\r\n", b"\r\n"),
    ("LF", b"\n"),          # case-insensitive
    ("END", b"END"),        # literal custom terminator
])
def test_resolve_eol(value: str, expected: bytes) -> None:
    assert resolve_eol(value) == expected


def test_resolve_eol_default_when_none() -> None:
    assert resolve_eol(None) == b"\r\n"
    assert resolve_eol(None, default="\n") == b"\n"
