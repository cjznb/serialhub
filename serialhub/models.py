"""数据模型与通用工具（§3）。

职责：
- ``Line``：一行串口数据（全局 seq + epoch 毫秒时间戳 + 文本 + ANSI 标记 + kind）。
- ANSI 工具：``strip_ansi`` / ``has_ansi``。
- 时间工具：``now_ms``。
- EOL 工具：``resolve_eol``（把 crlf/lf/cr/none/字面量解析为 bytes）。

本模块不依赖 serialhub 内其它模块，供全体后端复用。
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Optional, Union

__all__ = [
    "ANSI_RE",
    "KIND_RX",
    "KIND_TX",
    "KIND_MARK",
    "Line",
    "strip_ansi",
    "has_ansi",
    "now_ms",
    "resolve_eol",
]

# 覆盖 CSI 序列（ESC [ ... 终止符）与两字符 ESC 序列。
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[@-Z\\-_]")

KIND_RX = "rx"
KIND_TX = "tx"
KIND_MARK = "mark"

# EOL 名称/字面量到字节序列的映射（键统一小写）。
_EOL_MAP: dict[str, bytes] = {
    "crlf": b"\r\n",
    "\r\n": b"\r\n",
    "lf": b"\n",
    "\n": b"\n",
    "cr": b"\r",
    "\r": b"\r",
    "none": b"",
    "": b"",
}


def strip_ansi(text: str) -> str:
    """去除文本中的 ANSI 控制序列。"""
    return ANSI_RE.sub("", text)


def has_ansi(text: str) -> bool:
    """文本是否含 ANSI 控制序列。"""
    return ANSI_RE.search(text) is not None


def now_ms() -> int:
    """当前 epoch 毫秒（int）。"""
    return int(time.time() * 1000)


@dataclass(frozen=True, slots=True)
class Line:
    """一行串口/标记数据。

    seq 全局单调递增（跨所有口唯一）；ts_ms 为接收时刻 epoch 毫秒；
    text 不含行尾 EOL，可能含 ANSI 转义；kind ∈ {rx, tx, mark}。
    """

    seq: int
    port: str
    ts_ms: int
    text: str
    ansi: bool = False
    kind: str = KIND_RX

    def to_dict(self, strip: bool = False) -> dict:
        """返回 {'seq','port','ts_ms','text','ansi','kind'}；strip=True 时去 ANSI。"""
        text = strip_ansi(self.text) if strip else self.text
        return {
            "seq": self.seq,
            "port": self.port,
            "ts_ms": self.ts_ms,
            "text": text,
            "ansi": self.ansi,
            "kind": self.kind,
        }


def resolve_eol(eol: Optional[str], default: str = "\r\n") -> bytes:
    """把 EOL 说明解析为字节序列。

    ``crlf|lf|cr|none``（大小写不敏感）与字面量 ``\\r\\n|\\n|\\r`` 映射到对应
    字节；``none`` 解析为 ``b""``；其它字符串按 UTF-8 原样编码（自定义结尾）。
    ``eol`` 为 None 时使用 ``default``。
    """
    value: Union[str, bytes] = default if eol is None else eol
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    key = value.lower()
    if key in _EOL_MAP:
        return _EOL_MAP[key]
    return value.encode("utf-8")
