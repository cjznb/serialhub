"""Unit tests for :class:`serialhub.ringbuffer.RingBuffer` (§4)."""

from __future__ import annotations

from serialhub.models import Line
from serialhub.ringbuffer import RingBuffer


def _line(seq: int, text: str, *, kind: str = "rx", ts: int | None = None) -> Line:
    return Line(seq=seq, port="p", ts_ms=1000 + seq if ts is None else ts,
                text=text, kind=kind)


def _fill(rb: RingBuffer, n: int, *, prefix: str = "l") -> None:
    for i in range(1, n + 1):
        rb.append(_line(i, f"{prefix}{i}"))


# ---- append / stats ------------------------------------------------------- #
def test_append_and_stats() -> None:
    rb = RingBuffer()
    rb.append(_line(1, "hi"))
    st = rb.stats()
    assert st == {"count": 1, "bytes": 2, "first_seq": 1, "last_seq": 1,
                  "dropped_total": 0}


# ---- eviction ------------------------------------------------------------- #
def test_max_lines_eviction() -> None:
    rb = RingBuffer(max_lines=3)
    _fill(rb, 5)
    assert [line.seq for line in rb.snapshot()] == [3, 4, 5]
    assert rb.stats()["dropped_total"] == 2
    assert rb.oldest_seq() == 3
    assert rb.newest_seq() == 5


def test_max_bytes_eviction() -> None:
    rb = RingBuffer(max_lines=1000, max_bytes=10)
    for i in range(1, 4):
        rb.append(_line(i, "aaaa"))  # 4 bytes per line -> 12 > 10
    st = rb.stats()
    assert st["count"] == 2
    assert st["first_seq"] == 2 and st["last_seq"] == 3
    assert st["bytes"] == 8
    assert st["dropped_total"] == 1


# ---- read cursor semantics ----------------------------------------------- #
def test_read_all_without_cursor() -> None:
    rb = RingBuffer()
    _fill(rb, 5)
    result = rb.read()
    assert [line["seq"] for line in result["lines"]] == [1, 2, 3, 4, 5]
    assert result["next_seq"] == 5
    assert result["has_more"] is False


def test_read_without_cursor_returns_tail_with_limit() -> None:
    rb = RingBuffer()
    _fill(rb, 5)
    result = rb.read(limit=2)
    assert [line["seq"] for line in result["lines"]] == [4, 5]
    assert result["next_seq"] == 5
    assert result["has_more"] is False


def test_read_since_seq_no_duplicates() -> None:
    rb = RingBuffer()
    _fill(rb, 5)
    first = rb.read(since_seq=2)
    assert [line["seq"] for line in first["lines"]] == [3, 4, 5]
    assert first["next_seq"] == 5
    second = rb.read(since_seq=first["next_seq"])
    assert second["count"] == 0
    assert second["next_seq"] == 5
    assert second["has_more"] is False


def test_read_since_seq_matches_strictly_greater() -> None:
    rb = RingBuffer()
    _fill(rb, 3)
    result = rb.read(since_seq=1)
    assert [line["seq"] for line in result["lines"]] == [2, 3]


def test_read_since_seq_empty_returns_cursor() -> None:
    rb = RingBuffer()
    rb.append(_line(1, "a"))
    result = rb.read(since_seq=1)
    assert result["count"] == 0
    assert result["next_seq"] == 1


def test_read_pagination_has_more() -> None:
    rb = RingBuffer()
    _fill(rb, 5)
    r1 = rb.read(since_seq=0, limit=2)
    assert [line["seq"] for line in r1["lines"]] == [1, 2]
    assert r1["has_more"] is True
    r2 = rb.read(since_seq=r1["next_seq"], limit=2)
    assert [line["seq"] for line in r2["lines"]] == [3, 4]
    assert r2["has_more"] is True
    r3 = rb.read(since_seq=r2["next_seq"], limit=2)
    assert [line["seq"] for line in r3["lines"]] == [5]
    assert r3["has_more"] is False


def test_read_since_ts() -> None:
    rb = RingBuffer()
    rb.append(_line(1, "a", ts=100))
    rb.append(_line(2, "b", ts=200))
    rb.append(_line(3, "c", ts=300))
    result = rb.read(since_ts=150)
    assert [line["seq"] for line in result["lines"]] == [2, 3]


def test_read_dropped_math_when_cursor_predates_oldest() -> None:
    rb = RingBuffer(max_lines=3)
    _fill(rb, 5)  # retains seq 3,4,5 ; first_seq = 3
    assert rb.read(since_seq=0)["dropped"] == 2       # 3 - 1 - 0
    assert rb.read(since_seq=1)["dropped"] == 1       # first-1 - since_seq
    assert rb.read(since_seq=2)["dropped"] == 0       # cursor within range


def test_read_regex_filter() -> None:
    rb = RingBuffer()
    for i, text in enumerate(["foo", "bar", "foobar"], start=1):
        rb.append(_line(i, text))
    result = rb.read(regex="^foo")
    assert [line["text"] for line in result["lines"]] == ["foo", "foobar"]


def test_read_kinds_filter() -> None:
    rb = RingBuffer()
    rb.append(_line(1, "a", kind="rx"))
    rb.append(_line(2, "b", kind="tx"))
    rb.append(_line(3, "c", kind="mark"))
    result = rb.read(kinds={"tx"})
    assert [line["kind"] for line in result["lines"]] == ["tx"]


def test_read_strip_ansi() -> None:
    rb = RingBuffer()
    rb.append(_line(1, "\x1b[31mred\x1b[0m"))
    result = rb.read(strip_ansi=True)
    assert result["lines"][0]["text"] == "red"


# ---- search --------------------------------------------------------------- #
def test_search_with_context_and_since_seq() -> None:
    rb = RingBuffer()
    rb.append(_line(1, "start"))
    rb.append(_line(2, "hello world"))
    rb.append(_line(3, "end"))
    result = rb.search("hello", context=1)
    assert result["count"] == 1
    assert result["regex"] == "hello"
    hit = result["hits"][0]
    assert hit["seq"] == 2 and hit["match"] == "hello"
    assert [b["seq"] for b in hit["context_before"]] == [1]
    assert [a["seq"] for a in hit["context_after"]] == [3]

    scoped = rb.search("start", since_seq=2)
    assert scoped["count"] == 0
    assert scoped["next_seq"] == 2


def test_search_limit() -> None:
    rb = RingBuffer()
    _fill(rb, 5, prefix="hit")
    result = rb.search("hit", limit=2)
    assert result["count"] == 2
    assert result["next_seq"] == result["hits"][-1]["seq"]


# ---- snapshot ------------------------------------------------------------- #
def test_snapshot_tail() -> None:
    rb = RingBuffer()
    _fill(rb, 5)
    assert [line.seq for line in rb.snapshot(2)] == [4, 5]
    assert [line.seq for line in rb.snapshot(None)] == [1, 2, 3, 4, 5]
