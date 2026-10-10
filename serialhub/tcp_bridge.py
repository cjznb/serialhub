"""TCP bridge for serialhub.

Exposes a Hub serial port as a TCP service (``server`` mode) or transparently
connects to a remote serial-over-TCP endpoint (``client`` mode).

Design (see ``docs/ARCHITECTURE.md`` §12):

* ``server`` mode binds ``bind:tcp_port`` and accepts multiple clients.  Bytes
  received from any client are forwarded to the serial port via
  ``Hub.write_bytes`` and echoed into the ring buffer via ``Hub.ingest``
  (``kind="tx"``) for observability.
* ``client`` mode connects to ``host:tcp_port`` and is symmetric, reconnecting
  with exponential backoff whenever the link drops.
* Both modes drain a single broadcast subscription (``Hub.subscribe``): every
  ``type == "line"`` event for the bridged port is re-encoded as
  ``line["text"] + configured EOL`` and written back out to all connected
  peers.  The EOL is resolved from ``hub.config.port(port).eol`` through
  :func:`serialhub.models.resolve_eol`.

Only the Hub surface documented in ARCHITECTURE.md §6 is used.  ``Hub`` and
``Line`` are imported strictly for typing (``TYPE_CHECKING``) to avoid import
cycles; the hub is reached by duck typing at runtime.
"""

from __future__ import annotations

import queue
import socket
import threading
import time
from typing import TYPE_CHECKING, Optional

from serialhub.models import resolve_eol

if TYPE_CHECKING:
    from serialhub.hub import Hub
    from serialhub.models import Line  # noqa: F401  (typing-only reference per §12)

__all__ = ["TcpBridge"]

_RECV_SIZE = 4096
_ACCEPT_TIMEOUT = 0.5
_CLIENT_TIMEOUT = 0.5
_JOIN_TIMEOUT = 2.0
_CONNECT_TIMEOUT = 5.0
_BACKOFF_START = 0.5
_BACKOFF_MAX = 5.0
_LISTEN_BACKLOG = 16
_LINE_EVENT = "line"


class TcpBridge:
    """Bridge one serial port to/from a TCP socket.

    Args:
        hub: The owning :class:`~serialhub.hub.Hub` (duck-typed).
        port: Logical port name to bridge.
        mode: ``"server"`` (listen) or ``"client"`` (connect out).
        tcp_port: TCP port to bind (server) or connect to (client).
        host: Remote host for client mode; ``None`` in server mode.
        bind: Local interface to bind in server mode (default loopback).

    Raises:
        ValueError: if ``mode`` is invalid, or a required parameter for the
            chosen mode is missing (``tcp_port`` for server, ``host`` and
            ``tcp_port`` for client).
    """

    def __init__(
        self,
        hub: Hub,
        port: str,
        *,
        mode: str = "server",
        tcp_port: Optional[int] = None,
        host: Optional[str] = None,
        bind: str = "127.0.0.1",
    ) -> None:
        if mode not in ("server", "client"):
            raise ValueError(f"TcpBridge mode must be 'server' or 'client', got {mode!r}")
        if tcp_port is None:
            raise ValueError(f"TcpBridge {mode} mode requires tcp_port")
        if mode == "client" and host is None:
            raise ValueError("TcpBridge client mode requires host")

        self._hub = hub
        self._port = port
        self._mode = mode
        self._tcp_port: int = tcp_port
        self._host = host
        self._bind = bind

        self._lock = threading.Lock()
        self._clients: set[socket.socket] = set()
        self._threads: list[threading.Thread] = []
        self._stop_event = threading.Event()
        self._queue: Optional["queue.Queue[dict]"] = None
        self._listener: Optional[socket.socket] = None
        self._active = False
        self._last_error: Optional[str] = None

    # ------------------------------------------------------------------ API

    def start(self) -> dict:
        """Start the bridge and its worker threads.

        Returns:
            ``{"port", "mode", "tcp_port", "host", "active": True}``.

        Raises:
            OSError: if binding/connecting cannot be set up (e.g. port in use).
                Any partial state is torn down before the error propagates.
        """
        with self._lock:
            if self._active:
                return self._result(active=True)

        self._stop_event.clear()
        try:
            self._queue = self._hub.subscribe()
            if self._mode == "server":
                self._listener = self._make_listener()
                self._register_thread(
                    threading.Thread(
                        target=self._accept_loop,
                        name=f"tcpbridge-accept-{self._port}",
                        daemon=True,
                    )
                )
            else:
                self._register_thread(
                    threading.Thread(
                        target=self._client_connect_loop,
                        name=f"tcpbridge-connect-{self._port}",
                        daemon=True,
                    )
                )
            self._register_thread(
                threading.Thread(
                    target=self._dispatch_loop,
                    name=f"tcpbridge-dispatch-{self._port}",
                    daemon=True,
                )
            )
            for thread in list(self._threads):
                thread.start()
            self._active = True
            return self._result(active=True)
        except Exception:
            self.stop()
            raise

    def stop(self) -> dict:
        """Stop the bridge and release every resource.

        Closes the listener, closes all client sockets, unsubscribes, sets the
        stop event and joins all threads (with a timeout).  Idempotent: safe to
        call multiple times and before :meth:`start`.

        Returns:
            ``{"port", "mode", "tcp_port", "host", "active": False}``.
        """
        self._stop_event.set()

        listener, self._listener = self._listener, None
        if listener is not None:
            self._close_quietly(listener)

        with self._lock:
            clients = list(self._clients)
            self._clients.clear()
        for client in clients:
            self._close_quietly(client)

        subscription, self._queue = self._queue, None
        if subscription is not None:
            try:
                self._hub.unsubscribe(subscription)
            except Exception as exc:  # pragma: no cover - defensive
                self._record_error(exc)

        with self._lock:
            threads = list(self._threads)
            self._threads.clear()
        current = threading.current_thread()
        for thread in threads:
            if thread is current:
                continue
            thread.join(timeout=_JOIN_TIMEOUT)

        self._active = False
        return self._result(active=False)

    def status(self) -> dict:
        """Return the current bridge status.

        Returns:
            ``{"port", "mode", "tcp_port", "host", "active", "clients"}`` where
            ``clients`` is the number of currently registered sockets.
        """
        with self._lock:
            clients = len(self._clients)
        result = self._result(active=self._active)
        result["clients"] = clients
        return result

    # ------------------------------------------------------------- internals

    def _make_listener(self) -> socket.socket:
        """Create, bind and listen on the server socket."""
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind((self._bind, self._tcp_port))
            listener.listen(_LISTEN_BACKLOG)
            listener.settimeout(_ACCEPT_TIMEOUT)
        except Exception:
            self._close_quietly(listener)
            raise
        return listener

    def _accept_loop(self) -> None:
        """Accept client connections until stopped (server mode)."""
        listener = self._listener
        if listener is None:  # pragma: no cover - defensive
            return
        while not self._stop_event.is_set():
            try:
                conn, _addr = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                if self._stop_event.is_set():
                    return
                time.sleep(0.05)
                continue
            self._configure_socket(conn)
            with self._lock:
                self._clients.add(conn)
            reader = threading.Thread(
                target=self._client_reader,
                args=(conn,),
                name=f"tcpbridge-rx-{self._port}",
                daemon=True,
            )
            self._register_thread(reader)
            reader.start()

    def _client_connect_loop(self) -> None:
        """Connect to the remote endpoint, reconnecting with backoff."""
        backoff = _BACKOFF_START
        while not self._stop_event.is_set():
            try:
                sock = socket.create_connection(
                    (self._host, self._tcp_port), timeout=_CONNECT_TIMEOUT
                )
            except OSError as exc:
                self._record_error(exc)
                if self._stop_event.wait(backoff):
                    return
                backoff = min(backoff * 2.0, _BACKOFF_MAX)
                continue

            backoff = _BACKOFF_START
            self._record_error(None)
            self._configure_socket(sock)
            with self._lock:
                self._clients.add(sock)
            try:
                self._client_reader(sock)
            finally:
                self._remove_client(sock)
            if self._stop_event.wait(backoff):
                return

    def _client_reader(self, conn: socket.socket) -> None:
        """Read from a peer until EOF/stop; forward bytes to the serial port."""
        try:
            while not self._stop_event.is_set():
                try:
                    data = conn.recv(_RECV_SIZE)
                except socket.timeout:
                    continue
                except OSError:
                    break
                if not data:
                    break
                self._forward_to_serial(data)
        finally:
            self._remove_client(conn)

    def _dispatch_loop(self) -> None:
        """Drain the subscription queue and fan lines out to all peers."""
        subscription = self._queue
        if subscription is None:  # pragma: no cover - defensive
            return
        while not self._stop_event.is_set():
            try:
                event = subscription.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self._handle_event(event)
            except Exception as exc:  # pragma: no cover - must not kill loop
                self._record_error(exc)

    def _handle_event(self, event: object) -> None:
        """Broadcast a single serial line event to every connected peer."""
        if not isinstance(event, dict):
            return
        if event.get("type") != _LINE_EVENT or event.get("port") != self._port:
            return
        line = event.get("line")
        if not isinstance(line, dict):
            return
        text = line.get("text")
        if text is None:
            return
        payload = str(text).encode("utf-8", errors="replace") + self._eol_bytes()
        self._broadcast(payload)

    def _forward_to_serial(self, data: bytes) -> None:
        """Forward raw bytes from a peer to the serial port and ingest them."""
        try:
            self._hub.write_bytes(self._port, data)
        except Exception as exc:
            self._record_error(exc)
        try:
            self._hub.ingest(self._port, data.decode("utf-8", errors="replace"), kind="tx")
        except Exception as exc:
            self._record_error(exc)

    def _broadcast(self, payload: bytes) -> None:
        """Best-effort write of ``payload`` to every connected peer."""
        with self._lock:
            targets = list(self._clients)
        for sock in targets:
            try:
                sock.sendall(payload)
            except OSError:
                self._remove_client(sock)

    def _eol_bytes(self) -> bytes:
        """Resolve the configured EOL for the bridged port as raw bytes."""
        try:
            eol = self._hub.config.port(self._port).eol
        except Exception as exc:
            self._record_error(exc)
            eol = None
        return resolve_eol(eol, "\r\n")

    def _remove_client(self, sock: socket.socket) -> None:
        """Deregister and close a peer socket (idempotent, never fatal)."""
        with self._lock:
            self._clients.discard(sock)
        self._close_quietly(sock)

    def _register_thread(self, thread: threading.Thread) -> None:
        """Track a worker thread, pruning any that were started and finished."""
        with self._lock:
            self._threads = [
                t for t in self._threads if t.ident is None or t.is_alive()
            ]
            self._threads.append(thread)

    def _configure_socket(self, sock: socket.socket) -> None:
        """Apply low-latency blocking-with-timeout socket options."""
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass
        try:
            sock.settimeout(_CLIENT_TIMEOUT)
        except OSError:  # pragma: no cover - defensive
            pass

    def _result(self, *, active: bool) -> dict:
        """Build the standard result envelope shared by start/stop/status."""
        result = {
            "port": self._port,
            "mode": self._mode,
            "tcp_port": self._tcp_port,
            "host": self._host,
            "active": active,
        }
        return result

    def _record_error(self, exc: object) -> None:
        """Store the most recent non-fatal error (never raises)."""
        self._last_error = None if exc is None else f"{type(exc).__name__}: {exc}"

    @staticmethod
    def _close_quietly(sock: socket.socket) -> None:
        """Close a socket, ignoring shutdown races and errors."""
        try:
            sock.close()
        except OSError:
            pass
