"""中枢核心（§6）。

职责：把 ``Config`` + 每口 ``RingBuffer`` + 每口 ``SerialPortWorker`` + 订阅广播 +
全局单调 seq 缝合起来，对外提供端口生命周期、查询、数据读写、等待、导出、标记、
发送与 TCP 桥委托等能力，并保证全部返回结构严格符合契约 §6.1。

线程安全：``_lock`` 守护端口登记表 / 缓冲表 / 桥表 / 订阅者集合；``_seq_lock``
守护全局序号。worker 不直接改缓冲，一律经 ``ingest``。
"""

# allow: SIZE_OK - 契约 §6 要求单一 Hub 类承载全部端口/缓冲/广播/桥/等待逻辑，
# 且文件所有权（agent A）限定文件清单，禁止拆分为额外模块。

from __future__ import annotations

import os
import queue
import re
import threading
from typing import TYPE_CHECKING, Any, Iterable, Optional

from serial.tools import list_ports as _list_ports

from .config import Config, PortConfig
from .exporter import VALID_FORMATS, export_to_file
from .models import Line, has_ansi, now_ms, resolve_eol
from .ringbuffer import RingBuffer
from .serialport import SerialPortWorker

if TYPE_CHECKING:
    from .tcp_bridge import TcpBridge

__all__ = ["Hub"]

_SUBSCRIBER_QUEUE_SIZE = 10000
_IO_FIELDS = (
    "device", "baud", "data_bits", "parity", "stop_bits", "flow",
    "dtr", "rts", "encoding", "reconnect_ms", "reconnect_max_ms", "flush_ms",
)


def _compile(pattern: Any) -> "re.Pattern[str]":
    if isinstance(pattern, str):
        return re.compile(pattern)
    return pattern


def _parse_range(rng: Any) -> tuple[Optional[int], Optional[int]]:
    """解析 seq 范围：``"A-B"`` 或 ``[a, b]``；空端为 None。"""
    if rng is None:
        return None, None
    if isinstance(rng, (list, tuple)):
        if len(rng) >= 2:
            return int(rng[0]), int(rng[1])
        if len(rng) == 1:
            return int(rng[0]), None
        return None, None
    if isinstance(rng, str):
        text = rng.strip()
        if "-" in text:
            lo_s, hi_s = text.split("-", 1)
            lo = int(lo_s) if lo_s.strip() else None
            hi = int(hi_s) if hi_s.strip() else None
            return lo, hi
        if text:
            v = int(text)
            return v, v
    return None, None


class Hub:
    """串口中枢。全体后端（REST/WS/MCP/桥）依赖其返回结构。"""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._lock = threading.RLock()
        self._seq_lock = threading.Lock()
        self._seq = 0
        self._start_ms = now_ms()
        self._buffers: dict[str, RingBuffer] = {}
        self._workers: dict[str, SerialPortWorker] = {}
        self._subscribers: set[queue.Queue] = set()
        self._bridges: dict[str, "TcpBridge"] = {}
        for pc in config.ports:
            self._buffers[pc.name] = RingBuffer(pc.buffer_lines, pc.buffer_bytes)
            self._workers[pc.name] = SerialPortWorker(pc, self)

    # ---- 生命周期 ----
    def start(self) -> None:
        """打开 autostart 口，并启动 config 里声明的 tcp_bridge。"""
        with self._lock:
            ports = list(self._config.ports)
        for pc in ports:
            if pc.autostart:
                try:
                    self.open(pc.name)
                except Exception as exc:
                    self._publish_error(pc.name, exc)
            if pc.tcp_bridge:
                try:
                    self.bridge_start(
                        pc.name,
                        mode=pc.tcp_bridge.get("mode", "server"),
                        tcp_port=pc.tcp_bridge.get("port"),
                        host=pc.tcp_bridge.get("host"),
                    )
                except Exception as exc:
                    self._publish_error(pc.name, exc)

    def stop(self) -> None:
        """关闭所有桥与端口；幂等。"""
        with self._lock:
            bridge_names = list(self._bridges)
            worker_names = list(self._workers)
        for name in bridge_names:
            try:
                self.bridge_stop(name)
            except Exception as exc:
                self._publish_error(name, exc)
        for name in worker_names:
            try:
                self.close(name)
            except Exception as exc:
                self._publish_error(name, exc)

    def reload(self, new_config: Config) -> dict:
        """热重载（§6.3）：返回 {"added","removed","restarted","updated"}。"""
        added: list[str] = []
        removed: list[str] = []
        restarted: list[str] = []
        updated: list[str] = []
        old_ports = {pc.name: pc for pc in self._config.ports}
        new_ports = {pc.name: pc for pc in new_config.ports}

        for name in list(old_ports):
            if name not in new_ports:
                self.remove_port(name)
                removed.append(name)

        for name in new_ports:
            if name not in old_ports:
                self.add_port(new_ports[name])
                added.append(name)

        for name in new_ports:
            if name not in old_ports:
                continue
            old_pc, new_pc = old_ports[name], new_ports[name]
            if (old_pc.buffer_lines, old_pc.buffer_bytes) != (new_pc.buffer_lines, new_pc.buffer_bytes):
                self._rebuild_buffer(name, new_pc.buffer_lines, new_pc.buffer_bytes)
                updated.append(name)
            if any(getattr(old_pc, f) != getattr(new_pc, f) for f in _IO_FIELDS):
                worker = self._require_worker(name)
                if worker.is_open:
                    worker.close()
                    self._replace_worker(name, new_pc)
                    self.open(name)
                    restarted.append(name)
                else:
                    worker.update_config(new_pc)
            else:
                self._require_worker(name).update_config(new_pc)
            self._replace_port_config(name, new_pc)

        self._config = new_config
        return {"added": added, "removed": removed, "restarted": restarted, "updated": updated}

    # ---- 端口管理 ----
    def add_port(self, pc: PortConfig, *, autostart: bool = True) -> None:
        """新增端口（已存在则 ValueError）。"""
        with self._lock:
            if pc.name in self._workers:
                raise ValueError(f"port '{pc.name}' already exists")
            self._buffers[pc.name] = RingBuffer(pc.buffer_lines, pc.buffer_bytes)
            self._workers[pc.name] = SerialPortWorker(pc, self)
            self._config.ports.append(pc)
        if autostart:
            self.open(pc.name)

    def remove_port(self, name: str) -> None:
        """关闭并移除端口；未知 name → KeyError。"""
        with self._lock:
            worker = self._workers.get(name)
        if worker is None:
            raise KeyError(name)
        try:
            self.bridge_stop(name)
        except Exception as exc:
            self._publish_error(name, exc)
        worker.close()
        with self._lock:
            self._workers.pop(name, None)
            self._buffers.pop(name, None)
            self._config.ports = [p for p in self._config.ports if p.name != name]

    def open(self, name: str, *, baud: Optional[int] = None, device: Optional[str] = None) -> dict:
        """打开端口（可选改 baud/device），返回端口 dict。"""
        pc = self._port_config(name)
        worker = self._require_worker(name)
        changed = False
        if baud is not None and int(baud) != pc.baud:
            pc.baud = int(baud)
            changed = True
        if device is not None and str(device) != pc.device:
            pc.device = str(device)
            changed = True
        if changed:
            if worker.is_open:
                worker.close()
            self._replace_worker(name, pc)
            worker = self._workers[name]
        worker.open()
        return self._port_status(name)

    def close(self, name: str) -> dict:
        """关闭端口，返回端口 dict。"""
        worker = self._require_worker(name)
        worker.close()
        return self._port_status(name)

    def is_open(self, name: str) -> bool:
        return self._require_worker(name).is_open

    # ---- 查询 ----
    def list_ports(self) -> dict:
        with self._lock:
            names = list(self._workers)
        return {"system": self._system_ports(), "ports": [self._port_status(n) for n in names]}

    def status(self, name: Optional[str] = None) -> dict:
        if name is not None:
            data = self._port_status(name)
            data["server"] = self._server_info()
            return data
        with self._lock:
            names = list(self._workers)
        return {"server": self._server_info(), "ports": [self._port_status(n) for n in names]}

    # ---- 数据 ----
    def read(
        self,
        name: str,
        *,
        since_seq: Optional[int] = None,
        since_ts: Optional[int] = None,
        regex: Any = None,
        limit: Optional[int] = None,
        strip_ansi: bool = False,
        kinds: Optional[Iterable[str]] = None,
    ) -> dict:
        result = self._require_buffer(name).read(
            since_seq=since_seq,
            since_ts=since_ts,
            regex=regex,
            limit=limit,
            strip_ansi=strip_ansi,
            kinds=set(kinds) if kinds else None,
        )
        result["port"] = name
        return result

    def search(
        self,
        name: str,
        regex: str,
        *,
        context: int = 0,
        since_seq: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> dict:
        result = self._require_buffer(name).search(
            regex, context=context, since_seq=since_seq, limit=limit
        )
        result["port"] = name
        return result

    def wait_for(
        self,
        name: str,
        regex: str,
        *,
        timeout_ms: int = 10000,
        since_seq: Optional[int] = None,
    ) -> dict:
        """先扫环（已到哨兵立即返回），否则订阅广播阻塞等待。超时非错误。

        扫描下界：给定 ``since_seq`` 时用其值；否则用 0（即扫全环，已存在的匹配行立即返回）。
        """
        buf = self._require_buffer(name)
        pat = _compile(regex)
        cursor = since_seq if since_seq is not None else 0

        q = self.subscribe()
        try:
            existing = buf.read(since_seq=cursor, regex=pat, limit=1)
            if existing["lines"]:
                return self._wait_hit(name, existing["lines"][0], cursor)
            deadline = now_ms() + max(0, int(timeout_ms))
            while True:
                remaining = deadline - now_ms()
                if remaining <= 0:
                    break
                try:
                    event = q.get(timeout=remaining / 1000.0)
                except queue.Empty:
                    break
                if event.get("type") != "line" or event.get("port") != name:
                    continue
                line = event["line"]
                if line["seq"] <= cursor:
                    continue
                if pat.search(line["text"]) is not None:
                    return self._wait_hit(name, line, cursor)
        finally:
            self.unsubscribe(q)
        return {"port": name, "matched": False, "line": None, "seq": None, "ts_ms": None, "from_seq": cursor}

    def snapshot(self, name: str, *, tail_lines: int = 200) -> dict:
        lines = self._require_buffer(name).snapshot(tail_lines)
        dicts = [line.to_dict() for line in lines]
        return {"port": name, "tail_lines": tail_lines, "lines": dicts, "count": len(dicts)}

    def export(self, name: str, *, path: Optional[str] = None, fmt: str = "raw", rng: Any = None) -> dict:
        """导出环内行；path 缺省写到 ``<cwd>/exports/<port>-<ts>.<ext>``。"""
        if fmt not in VALID_FORMATS:
            raise ValueError(f"unknown format {fmt!r}; expected one of {list(VALID_FORMATS)}")
        lines = self._require_buffer(name).snapshot()
        lo, hi = _parse_range(rng)
        if lo is not None or hi is not None:
            lines = [
                line for line in lines
                if (lo is None or line.seq >= lo) and (hi is None or line.seq <= hi)
            ]
        if path is None:
            ext = "jsonl" if fmt == "json" else "txt"
            path = os.path.join(os.getcwd(), "exports", f"{name}-{now_ms()}.{ext}")
        target = os.path.abspath(path)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        written = export_to_file(lines, target, fmt)
        return {"port": name, "path": target, "format": fmt, "bytes": written, "count": len(lines)}

    def clear(self, name: str) -> dict:
        buf = self._require_buffer(name)
        cleared = buf.stats()["count"]
        buf.clear()
        return {"port": name, "cleared": cleared}

    def mark(self, name: str, label: str) -> dict:
        line = self.ingest(name, label, kind="mark")
        return {"port": name, "label": label, "seq": line.seq, "ts_ms": line.ts_ms}

    def send(
        self,
        name: str,
        data: Any,
        *,
        eol: Optional[str] = None,
        wait_regex: Optional[str] = None,
        timeout_ms: Optional[int] = None,
    ) -> dict:
        """写串口（按口 eol 追加结尾）+ 以 kind=tx 入环；可选等待回应。"""
        worker = self._require_worker(name)
        pc = self._port_config(name)
        eol_bytes = resolve_eol(eol, pc.eol)
        if isinstance(data, str):
            payload = data.encode(pc.encoding, errors="replace")
            sent_text = data
        else:
            payload = bytes(data)
            sent_text = payload.decode(pc.encoding, errors="replace")

        from_seq: Optional[int] = None
        if wait_regex is not None:
            newest = self._require_buffer(name).newest_seq()
            from_seq = newest if newest is not None else 0

        sent_bytes = worker.write(payload + eol_bytes)
        self.ingest(name, sent_text, kind="tx")

        result: dict = {
            "port": name,
            "sent_bytes": sent_bytes,
            "sent": sent_text,
            "waited": wait_regex is not None,
            "matched": False,
            "line": None,
            "seq": None,
        }
        if wait_regex is not None:
            waited = self.wait_for(
                name, wait_regex,
                timeout_ms=timeout_ms if timeout_ms is not None else 10000,
                since_seq=from_seq,
            )
            result["matched"] = waited["matched"]
            result["line"] = waited["line"]
            result["seq"] = waited["seq"]
        return result

    # ---- 供 worker / 桥使用 ----
    def next_seq(self) -> int:
        with self._seq_lock:
            self._seq += 1
            return self._seq

    def ingest(self, port: str, text: str, *, kind: str = "rx", ts_ms: Optional[int] = None) -> Line:
        """建行→入环→广播（§6.2）。"""
        seq = self.next_seq()
        line = Line(
            seq=seq,
            port=port,
            ts_ms=ts_ms if ts_ms is not None else now_ms(),
            text=text,
            ansi=has_ansi(text),
            kind=kind,
        )
        with self._lock:
            buf = self._buffers.get(port)
        if buf is not None:
            buf.append(line)
        self._broadcast({"type": "line", "port": port, "line": line.to_dict()})
        return line

    def write_bytes(self, name: str, data: bytes) -> int:
        """原始字节写串口（不追加 EOL）。"""
        return self._require_worker(name).write(bytes(data))

    def subscribe(self) -> "queue.Queue[dict]":
        q: "queue.Queue[dict]" = queue.Queue(maxsize=_SUBSCRIBER_QUEUE_SIZE)
        with self._lock:
            self._subscribers.add(q)
        return q

    def unsubscribe(self, q: "queue.Queue[dict]") -> None:
        with self._lock:
            self._subscribers.discard(q)

    # ---- 桥 ----
    def bridge_start(
        self,
        name: str,
        *,
        mode: str = "server",
        tcp_port: Optional[int] = None,
        host: Optional[str] = None,
    ) -> dict:
        self._require_worker(name)
        with self._lock:
            existing = self._bridges.get(name)
        if existing is not None:
            existing.stop()
        from .tcp_bridge import TcpBridge  # 延迟导入：该文件由其它 agent 提供
        # server 模式下 `host` 即监听绑定地址（默认回环；传 "0.0.0.0" 可跨机访问）；
        # client 模式下 `host` 是远端地址，本地绑定固定回环。
        bind = (host or "127.0.0.1") if mode == "server" else "127.0.0.1"
        bridge = TcpBridge(self, name, mode=mode, tcp_port=tcp_port, host=host, bind=bind)
        info = bridge.start()
        with self._lock:
            self._bridges[name] = bridge
        return info

    def bridge_stop(self, name: str) -> dict:
        with self._lock:
            bridge = self._bridges.pop(name, None)
        if bridge is None:
            return {"port": name, "mode": None, "tcp_port": None, "host": None, "active": False}
        return bridge.stop()

    def bridge_status(self, name: Optional[str] = None) -> dict:
        if name is not None:
            with self._lock:
                bridge = self._bridges.get(name)
            if bridge is None:
                return {"port": name, "mode": None, "tcp_port": None, "host": None, "active": False}
            return bridge.status()
        with self._lock:
            items = [b.status() for b in self._bridges.values()]
        return {
            "port": None,
            "mode": None,
            "tcp_port": None,
            "host": None,
            "active": any(bool(i.get("active")) for i in items),
            "bridges": items,
        }

    @property
    def config(self) -> Config:
        return self._config

    # ---- 内部工具 ----
    def _broadcast(self, event: dict) -> None:
        with self._lock:
            subs = list(self._subscribers)
        for q in subs:
            try:
                q.put_nowait(event)
            except queue.Full:
                pass  # 订阅者消费过慢，按契约丢弃

    def _publish_error(self, name: str, exc: Exception) -> None:
        with self._lock:
            worker = self._workers.get(name)
        self._broadcast({
            "type": "status",
            "port": name,
            "open": worker.is_open if worker is not None else False,
            "error": f"{type(exc).__name__}: {exc}",
        })

    def _require_worker(self, name: str) -> SerialPortWorker:
        with self._lock:
            worker = self._workers.get(name)
        if worker is None:
            raise KeyError(name)
        return worker

    def _require_buffer(self, name: str) -> RingBuffer:
        with self._lock:
            buf = self._buffers.get(name)
        if buf is None:
            raise KeyError(name)
        return buf

    def _port_config(self, name: str) -> PortConfig:
        for pc in self._config.ports:
            if pc.name == name:
                return pc
        raise KeyError(name)

    def _replace_worker(self, name: str, pc: PortConfig) -> None:
        with self._lock:
            self._workers[name] = SerialPortWorker(pc, self)

    def _replace_port_config(self, name: str, pc: PortConfig) -> None:
        with self._lock:
            self._config.ports = [pc if p.name == name else p for p in self._config.ports]

    def _rebuild_buffer(self, name: str, max_lines: int, max_bytes: int) -> None:
        with self._lock:
            old = self._buffers.get(name)
        new = RingBuffer(max_lines, max_bytes)
        if old is not None:
            for line in old.snapshot():
                new.append(line)
        with self._lock:
            self._buffers[name] = new

    def _wait_hit(self, name: str, line: dict, cursor: int) -> dict:
        return {
            "port": name,
            "matched": True,
            "line": line,
            "seq": line["seq"],
            "ts_ms": line["ts_ms"],
            "from_seq": cursor,
        }

    def _server_info(self) -> dict:
        return {
            "host": self._config.server.host,
            "port": self._config.server.port,
            "version": self._version(),
            "uptime_ms": now_ms() - self._start_ms,
        }

    def _bridge_view(self, name: str, pc: PortConfig) -> Optional[dict]:
        with self._lock:
            bridge = self._bridges.get(name)
        if bridge is not None:
            s = bridge.status()
            return {
                "mode": s.get("mode"),
                "port": s.get("tcp_port"),
                "host": s.get("host"),
                "active": bool(s.get("active")),
            }
        if pc.tcp_bridge:
            return {
                "mode": pc.tcp_bridge.get("mode"),
                "port": pc.tcp_bridge.get("port"),
                "host": pc.tcp_bridge.get("host"),
                "active": False,
            }
        return None

    def _port_status(self, name: str) -> dict:
        worker = self._require_worker(name)
        pc = self._port_config(name)
        buf = self._require_buffer(name)
        st = worker.status()
        return {
            "name": name,
            "device": pc.device,
            "description": pc.description,
            "open": st["open"],
            "baud": pc.baud,
            "data_bits": pc.data_bits,
            "parity": pc.parity,
            "stop_bits": pc.stop_bits,
            "flow": pc.flow,
            "rx_lines": st["rx_lines"],
            "tx_lines": st["tx_lines"],
            "last_error": st["last_error"],
            "reconnect_count": st["reconnect_count"],
            "buffer": buf.stats(),
            "tcp_bridge": self._bridge_view(name, pc),
        }

    @staticmethod
    def _version() -> str:
        try:
            from . import __version__
            return __version__
        except Exception:
            return "0.1.0"

    @staticmethod
    def _system_ports() -> list[dict]:
        result: list[dict] = []
        try:
            for info in _list_ports.comports():
                result.append({
                    "device": info.device,
                    "description": info.description,
                    "hwid": info.hwid,
                })
        except Exception:
            return []
        return result
