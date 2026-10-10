"""导出格式（§8）。

职责：把 ``Line`` 列表格式化为 raw / noansi / json(JSONL) 文本，并写盘。
仅依赖 ``models``。
"""

from __future__ import annotations

import json

from .models import Line, strip_ansi

__all__ = ["export_text", "export_to_file", "VALID_FORMATS"]

VALID_FORMATS = ("raw", "noansi", "json")


def export_text(lines: list[Line], fmt: str = "raw") -> str:
    """raw：原样 text+``\\n``；noansi：去 ANSI text+``\\n``；json：每行一个 JSON 对象（JSONL）。"""
    if fmt not in VALID_FORMATS:
        raise ValueError(f"unknown export format {fmt!r}; expected one of {list(VALID_FORMATS)}")
    if fmt == "json":
        return "".join(
            json.dumps(line.to_dict(), ensure_ascii=False) + "\n" for line in lines
        )
    strip = fmt == "noansi"
    return "".join(
        (strip_ansi(line.text) if strip else line.text) + "\n" for line in lines
    )


def export_to_file(lines: list[Line], path: str, fmt: str = "raw") -> int:
    """把格式化内容以 UTF-8 写入 path，返回写入字节数。"""
    content = export_text(lines, fmt)
    data = content.encode("utf-8")
    with open(path, "wb") as fh:
        fh.write(data)
    return len(data)
