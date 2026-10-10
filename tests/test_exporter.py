"""Unit tests for :mod:`serialhub.exporter` (§8)."""

from __future__ import annotations

import json

import pytest

from serialhub.exporter import export_text, export_to_file
from serialhub.models import Line


def _lines() -> list[Line]:
    return [
        Line(seq=1, port="t", ts_ms=1000, text="plain"),
        Line(seq=2, port="t", ts_ms=2000, text="\x1b[31mred\x1b[0m", ansi=True),
    ]


def test_export_text_raw_keeps_ansi() -> None:
    assert export_text(_lines(), "raw") == "plain\n\x1b[31mred\x1b[0m\n"


def test_export_text_noansi_strips_ansi() -> None:
    assert export_text(_lines(), "noansi") == "plain\nred\n"


def test_export_text_json_is_jsonl_with_expected_keys() -> None:
    out = export_text(_lines(), "json")
    rows = [json.loads(line) for line in out.splitlines()]
    assert len(rows) == 2
    assert set(rows[0].keys()) == {"seq", "port", "ts_ms", "text", "ansi", "kind"}
    assert rows[1]["text"] == "\x1b[31mred\x1b[0m"
    assert rows[1]["ansi"] is True
    assert rows[1]["seq"] == 2


def test_export_to_file_returns_byte_count(tmp_path) -> None:
    target = tmp_path / "out.txt"
    content = "plain\n\x1b[31mred\x1b[0m\n"
    written = export_to_file(_lines(), str(target), "raw")
    assert written == len(content.encode("utf-8"))
    assert target.read_text(encoding="utf-8") == content


def test_export_unknown_format_raises() -> None:
    with pytest.raises(ValueError):
        export_text(_lines(), "bogus")
