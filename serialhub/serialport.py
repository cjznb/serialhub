"""串口工作线程（§7）。

职责：每个逻辑口一个守护线程，负责持久打开、断线指数退避重连、读取字节并按
``\\n``/``\\r``/``\\r\\n`` 断行，残行超过 ``flush_ms`` 也吐出，逐行经 ``hub.ingest``
入环广播。任何串口错误都记入 ``last_error`` 并广播 status 事件，绝不崩溃进程。

仅被 ``Hub`` 使用；不直接改缓冲（一律经 ``hub.ingest``）。
"""

# allow: SIZE_OK - 契约 §7 要求单文件内实现完整 SerialPortWorker 读写/断行/重连循环。

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Optional

import serial

from . import discovery
from .models import now_ms

if TYPE_CHECKING:  # 仅类型标注，避免与 hub 形成运行期循环导入
    from .hub import Hub

__all__ = ["SerialPortWorker"]

_CR = 0x0D
_LF = 0x0A


def _find_eol(buf: bytearray) -> Optional[tuple[int, int]]:
    """定位最早的行结束符，返回 (行内容结束下标, 需删除到的下标)。

    ``\\r\\n`` 视为一个结束符；结尾孤立 ``\\r`` 暂缓（等待可能的 ``\\n``）。
    """
    n = len(buf)
    for i in range(n):
        b = buf[i]
        if b == _LF:
            return i, i + 1
        if b == _CR:
            if i + 1 < n:
                return i, (i + 2 if buf[i + 1] == _LF else i + 1)
            return None
    return None


class SerialPortWorker(threading.Thread):
    """单口串口读写线程。基类为 ``Thread``，实际读循环由内部线程承载以支持开/关复用。"""

    def __init__(self, pc, hub: "Hub") -> None:
        super().__init__(name=f"serialhub-{getattr(pc, 'name', 'port')}", daemon=True)
        self._pc = pc
        self._hub = hub
        self._serial: Optional[serial.SerialBase] = None
        self._open: bool = False
        self._want_open: bool = False
        self._last_error: Optional[str] = None
        self._reconnect_count: int = 0
        self._rx_lines: int = 0
        self._tx_lines: int = 0
        self._encoding: str = getattr(pc, "encoding", None) or "utf-8"
        self._flush_ms: int = max(0, int(getattr(pc, "flush_ms", 50)))
        # 是否用 match 自动发现设备：为真时每次连接/重连前重新解析真实设备名。
        self._uses_match: bool = bool(getattr(pc, "match", None))
        self._state_lock = threading.RLock()
        self._io_lock = threading.Lock()
        self._counters_lock = threading.Lock()
        self._stop = threading.Event()
        self._loop_thread: Optional[threading.Thread] = None

    # ---- 属性 ----
    @property
    def is_open(self) -> bool:
        with self._state_lock:
            return self._open

    @property
    def last_error(self) -> Optional[str]:
        with self._state_lock:
            return self._last_error

    @property
    def reconnect_count(self) -> int:
        with self._state_lock:
            return self._reconnect_count

    @property
    def rx_lines(self) -> int:
        with self._counters_lock:
            return self._rx_lines

    @property
    def tx_lines(self) -> int:
        with self._counters_lock:
            return self._tx_lines

    @property
    def resolved_device(self) -> str:
        """当前解析到的真实设备名（match 端口为发现的 COM，固定端口即配置值）。"""
        with self._state_lock:
            return self._pc.device

    # ---- 生命周期 ----
    def open(self) -> None:
        """立即尝试打开（失败置 last_error，不抛），并确保读循环在运行。"""
        with self._state_lock:
            self._want_open = True
            self._stop.clear()
            self._try_connect()
            if self._loop_thread is None or not self._loop_thread.is_alive():
                self._loop_thread = threading.Thread(
                    target=self._run_loop,
                    name=f"serialhub-{self._pc.name}-io",
                    daemon=True,
                )
                self._loop_thread.start()

    def close(self) -> None:
        """停止读循环并释放端口（幂等）。"""
        with self._state_lock:
            self._want_open = False
        self._stop.set()
        thread = self._loop_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=3.0)
        self._close_serial()
        self._broadcast_status()

    def update_config(self, pc) -> None:
        """热重载时替换端口配置（线程安全，供 Hub 调用）。"""
        with self._state_lock:
            self._pc = pc
            self._encoding = getattr(pc, "encoding", None) or "utf-8"
            self._flush_ms = max(0, int(getattr(pc, "flush_ms", 50)))
            self._uses_match = bool(getattr(pc, "match", None))

    def write(self, data: bytes) -> int:
        """线程安全写串口（原始字节，不追加 EOL）；未打开 → RuntimeError。"""
        with self._state_lock:
            ser = self._serial
            if ser is None or not self._open:
                raise RuntimeError(f"port '{self._pc.name}' is not open")
        try:
            with self._io_lock:
                written = ser.write(data)
                try:
                    ser.flush()
                except Exception as exc:  # flush 失败记录但不致命
                    with self._state_lock:
                        self._last_error = f"flush: {type(exc).__name__}: {exc}"
        except Exception as exc:
            with self._state_lock:
                self._last_error = f"write: {type(exc).__name__}: {exc}"
            self._broadcast_status()
            raise
        count = int(written) if written is not None else len(data)
        with self._counters_lock:
            self._tx_lines += 1
        return count

    def status(self) -> dict:
        with self._state_lock:
            return {
                "open": self._open,
                "last_error": self._last_error,
                "reconnect_count": self._reconnect_count,
                "rx_lines": self.rx_lines,
                "tx_lines": self.tx_lines,
            }

    # ---- 连接 ----
    def _resolve_device(self) -> Optional[str]:
        """match 端口：重新解析真实设备名并写回 ``pc.device``。

        每次连接/重连前调用（先把 ``pc.device`` 清空以强制重解析），这样设备拔插
        后换到别的 COM 仍能找回。无命中或解析异常 → 置 ``last_error``、返回 None，
        不抛异常、不崩溃，交由外层退避重试。
        """
        pc = self._pc
        pc.device = ""
        try:
            found = discovery.resolve(pc.match or {})
        except Exception as exc:
            self._last_error = f"discovery: {type(exc).__name__}: {exc}"
            self._open = False
            self._serial = None
            self._broadcast_status()
            return None
        device = found.get("device")
        if not device:
            self._last_error = f"no device matched: {discovery.describe(pc.match or {})}"
            self._open = False
            self._serial = None
            self._broadcast_status()
            return None
        pc.device = device
        return device

    def _try_connect(self) -> bool:
        """在 _state_lock 下尝试建立连接；成功 True，失败 False（置 last_error）。"""
        if self._open and self._serial is not None:
            return True
        pc = self._pc
        if self._uses_match:
            device = self._resolve_device()
            if device is None:
                return False
        else:
            device = pc.device
        try:
            ser = serial.serial_for_url(
                device,
                baudrate=pc.baud,
                bytesize=pc.data_bits,
                parity=pc.parity,
                stopbits=pc.stop_bits,
                rtscts=pc.flow == "rtscts",
                xonxoff=pc.flow == "xonxoff",
                dsrdtr=pc.flow == "dsrdtr",
                timeout=0.1,
                write_timeout=1,
            )
        except Exception as exc:
            self._last_error = f"{type(exc).__name__}: {exc}"
            self._open = False
            self._serial = None
            self._broadcast_status()
            return False
        try:
            ser.setDTR(bool(pc.dtr))
            ser.setRTS(bool(pc.rts))
        except Exception as exc:  # 某些 URL（loop:// 等）不支持 DTR/RTS
            self._last_error = f"dtr/rts: {type(exc).__name__}: {exc}"
        self._serial = ser
        self._open = True
        if self._uses_match:
            self._last_error = None  # 连接成功即清掉“未发现/重连”错误
        self._broadcast_status()
        return True

    def _close_serial(self) -> None:
        with self._io_lock:
            with self._state_lock:
                ser = self._serial
                self._serial = None
                self._open = False
            if ser is not None:
                try:
                    ser.close()
                except Exception as exc:
                    with self._state_lock:
                        self._last_error = f"close: {type(exc).__name__}: {exc}"

    def _broadcast_status(self) -> None:
        with self._state_lock:
            event = {
                "type": "status",
                "port": self._pc.name,
                "open": self._open,
                "last_error": self._last_error,
                "reconnect_count": self._reconnect_count,
            }
        self._hub._broadcast(event)

    # ---- 读循环 ----
    def _run_loop(self) -> None:
        pc = self._pc
        backoff = max(1, int(pc.reconnect_ms))
        backoff_max = max(backoff, int(pc.reconnect_max_ms))
        buf = bytearray()
        residual_since: Optional[int] = None

        while not self._stop.is_set():
            with self._state_lock:
                want = self._want_open
            if not want:
                self._stop.wait(0.05)
                continue

            if not self.is_open:
                if self._try_connect():
                    backoff = max(1, int(self._pc.reconnect_ms))
                    buf.clear()
                    residual_since = None
                else:
                    with self._state_lock:
                        self._reconnect_count += 1
                    self._stop.wait(backoff / 1000.0)
                    backoff = min(backoff * 2, backoff_max)
                    continue

            data = self._read_once()
            if data is None:
                buf.clear()
                residual_since = None
                with self._state_lock:
                    self._reconnect_count += 1
                self._stop.wait(backoff / 1000.0)
                backoff = min(backoff * 2, backoff_max)
                continue

            now = now_ms()
            if data:
                if not buf:
                    residual_since = now
                buf.extend(data)
                self._emit_complete_lines(buf)
                if not buf:
                    residual_since = None
                elif residual_since is None:
                    residual_since = now

            if buf and residual_since is not None and (now_ms() - residual_since) >= self._flush_ms:
                raw = bytes(buf)
                if raw.endswith(b"\r"):
                    raw = raw[:-1]
                buf.clear()
                residual_since = None
                self._emit(raw)

    def _read_once(self) -> Optional[bytes]:
        """读一次；返回 None 表示连接已断开（错误已记录/广播）。"""
        with self._state_lock:
            ser = self._serial
            opened = self._open
        if ser is None or not opened:
            return None
        try:
            with self._io_lock:
                return ser.read(4096)  # type: ignore[no-any-return]
        except Exception as exc:
            with self._state_lock:
                self._last_error = f"read: {type(exc).__name__}: {exc}"
            self._close_serial()
            self._broadcast_status()
            return None

    def _emit_complete_lines(self, buf: bytearray) -> None:
        while True:
            idx = _find_eol(buf)
            if idx is None:
                break
            end, drop = idx
            raw = bytes(buf[:end])
            del buf[:drop]
            self._emit(raw)

    def _emit(self, raw: bytes) -> None:
        text = raw.decode(self._encoding, errors="replace")
        self._hub.ingest(self._pc.name, text, kind="rx")
        with self._counters_lock:
            self._rx_lines += 1

    # Thread.run 覆盖为读循环体（内部线程以 target=self._run_loop 启动）。
    def run(self) -> None:  # pragma: no cover - 仅当以 Thread 方式启动时使用
        self._run_loop()
