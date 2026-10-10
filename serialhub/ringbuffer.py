"""每口环形缓冲（§4）。

职责：按行数/字节双阈值淘汰最老行的线程安全环形缓冲，提供增量 ``read``
（保证无重复消费）与 ``search``（带上下文）。

本模块只依赖 ``models``。
"""

from __future__ import annotations

import re
from collections import deque
from threading import Lock
from typing import Optional, Union

from .models import Line

__all__ = ["RingBuffer"]

Pattern = Union[str, "re.Pattern[str]", None]


def _matches(text: str, pattern: Pattern) -> bool:
    """pattern 为 None/空串时不筛选；字符串按正则编译匹配；否则用已编译对象。"""
    if pattern is None:
        return True
    if isinstance(pattern, str):
        if pattern == "":
            return True
        return re.search(pattern, text) is not None
    return pattern.search(text) is not None


class RingBuffer:
    """线程安全、按行/字节双阈值淘汰的环形缓冲。"""

    def __init__(self, max_lines: int = 20000, max_bytes: int = 8 * 1024 * 1024) -> None:
        self._max_lines: int = max(1, int(max_lines))
        self._max_bytes: int = max(1, int(max_bytes))
        self._buf: deque[Line] = deque()
        self._bytes: int = 0
        self._dropped: int = 0
        self._lock = Lock()

    # ---- 写 ----
    def append(self, line: Line) -> None:
        """追加一行；越界自动淘汰最老行（行数/字节双阈值）。"""
        size = _line_bytes(line)
        with self._lock:
            self._buf.append(line)
            self._bytes += size
            while self._buf and (len(self._buf) > self._max_lines or self._bytes > self._max_bytes):
                old = self._buf.popleft()
                self._bytes -= _line_bytes(old)
                self._dropped += 1

    def clear(self) -> None:
        """清空缓冲（不改变 dropped_total）。"""
        with self._lock:
            self._buf.clear()
            self._bytes = 0

    # ---- 读 ----
    def stats(self) -> dict:
        """{'count','bytes','first_seq','last_seq','dropped_total'}。"""
        with self._lock:
            first = self._buf[0].seq if self._buf else None
            last = self._buf[-1].seq if self._buf else None
            return {
                "count": len(self._buf),
                "bytes": self._bytes,
                "first_seq": first,
                "last_seq": last,
                "dropped_total": self._dropped,
            }

    def snapshot(self, tail: Optional[int] = None) -> list[Line]:
        """tail=None→全部；否则最后 tail 行。一律旧→新升序。"""
        with self._lock:
            if tail is None:
                return list(self._buf)
            if tail <= 0:
                return []
            return list(self._buf)[-tail:]

    def oldest_seq(self) -> Optional[int]:
        with self._lock:
            return self._buf[0].seq if self._buf else None

    def newest_seq(self) -> Optional[int]:
        with self._lock:
            return self._buf[-1].seq if self._buf else None

    def read(
        self,
        *,
        since_seq: Optional[int] = None,
        since_ts: Optional[int] = None,
        regex: Pattern = None,
        limit: Optional[int] = None,
        strip_ansi: bool = False,
        kinds: Optional[set[str]] = None,
    ) -> dict:
        """增量读取（§4.1）。游标优先 ``since_seq`` → ``since_ts`` → 末尾 ``limit``。"""
        kinds_set = set(kinds) if kinds else None
        with self._lock:
            items = list(self._buf)
        first = items[0].seq if items else None
        last = items[-1].seq if items else None

        if since_seq is not None:
            cursor_mode = True
            base = [line for line in items if line.seq > since_seq]
        elif since_ts is not None:
            cursor_mode = True
            base = [line for line in items if line.ts_ms > since_ts]
        else:
            cursor_mode = False
            base = items

        filtered = [
            line for line in base
            if (kinds_set is None or line.kind in kinds_set) and _matches(line.text, regex)
        ]

        if limit is not None and limit >= 0:
            if cursor_mode:
                result = filtered[:limit]
                has_more = len(filtered) > len(result)
            else:
                result = filtered[-limit:] if limit > 0 else []
                has_more = False
        else:
            result = filtered
            has_more = False

        lines_out = [line.to_dict(strip_ansi) for line in result]
        if result:
            next_seq = result[-1].seq
        elif since_seq is not None:
            next_seq = since_seq
        else:
            next_seq = last if last is not None else 0

        if since_seq is not None and first is not None and since_seq < first - 1:
            dropped = first - 1 - since_seq
        else:
            dropped = 0

        return {
            "lines": lines_out,
            "count": len(lines_out),
            "next_seq": next_seq,
            "dropped": dropped,
            "has_more": has_more,
            "first_seq": first,
            "last_seq": last,
        }

    def search(
        self,
        regex: Pattern,
        *,
        context: int = 0,
        since_seq: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> dict:
        """正则搜索（§4.2）。since_seq 仅搜 seq>since_seq；limit 限制命中数。"""
        if regex is None:
            raise ValueError("search() requires a non-null regex")
        pat = regex if not isinstance(regex, str) else re.compile(regex)
        with self._lock:
            items = list(self._buf)
        newest = items[-1].seq if items else None

        hits: list[dict] = []
        for idx, line in enumerate(items):
            if since_seq is not None and line.seq <= since_seq:
                continue
            m = pat.search(line.text)
            if m is None:
                continue
            before = items[max(0, idx - context):idx] if context > 0 else []
            after = items[idx + 1:idx + 1 + context] if context > 0 else []
            hits.append({
                "seq": line.seq,
                "ts_ms": line.ts_ms,
                "text": line.text,
                "kind": line.kind,
                "match": m.group(0),
                "context_before": [{"seq": x.seq, "ts_ms": x.ts_ms, "text": x.text} for x in before],
                "context_after": [{"seq": x.seq, "ts_ms": x.ts_ms, "text": x.text} for x in after],
            })
            if limit is not None and len(hits) >= limit:
                break

        if hits:
            next_seq = hits[-1]["seq"]
        elif since_seq is not None:
            next_seq = since_seq
        else:
            next_seq = newest if newest is not None else 0
        return {"hits": hits, "count": len(hits), "next_seq": next_seq, "regex": pat.pattern}


def _line_bytes(line: Line) -> int:
    """一行的字节占用（文本 UTF-8 编码长度）。"""
    return len(line.text.encode("utf-8"))
