"""serialhub HTTP / WebSocket server (server.py — 归属 B).

职责：把常驻 :class:`~serialhub.hub.Hub` 暴露为
    * REST ``/api/*``（契约 §9）
    * WebSocket ``/ws``（转发 ``hub.subscribe()`` 事件原样）
    * 静态 Web UI（``GET /`` + ``/static/*``）
并提供一个 ``create_app(hub, config)`` 工厂，交给 ``cli serve`` 用 uvicorn 运行。

设计约束：
    * **不**绑定监听地址、**不**调用 ``uvicorn.run``（那是 CLI 的职责）。
    * ``Hub`` / ``Config`` 仅用于类型注解（``TYPE_CHECKING``），运行时按 duck typing
      访问，因此即便 ``hub.py`` / ``config.py`` 尚未就绪，本模块也能被安全导入。
    * 所有 JSON 响应统一 ``{"ok": true, ...}`` / ``{"ok": false, "error": "..."}``。
"""

from __future__ import annotations

import asyncio
import json
import queue
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, Set

from fastapi import FastAPI, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

if TYPE_CHECKING:  # 仅供类型检查；运行时不需要 hub.py / config.py 存在
    from .config import Config
    from .hub import Hub

try:  # __init__.py 可能尚未落地，导入失败时兜底
    from . import __version__ as VERSION
except Exception:  # noqa: BLE001 - 包初始化期间允许缺失
    VERSION = "0.1.0"

STATIC_DIR = Path(__file__).resolve().parent / "static"


# --------------------------------------------------------------------------- #
# 请求体模型
# --------------------------------------------------------------------------- #
class OpenBody(BaseModel):
    baud: Optional[int] = None
    device: Optional[str] = None


class SendBody(BaseModel):
    data: str
    eol: Optional[str] = None
    wait_regex: Optional[str] = None
    timeout_ms: Optional[int] = None


class ExportBody(BaseModel):
    path: Optional[str] = None
    format: str = "raw"
    range: Optional[str] = None  # noqa: A003 - 与 REST 契约字段名保持一致


class MarkBody(BaseModel):
    label: str


class BridgeBody(BaseModel):
    action: str
    port: str
    mode: Optional[str] = None
    tcp_port: Optional[int] = None
    host: Optional[str] = None


# --------------------------------------------------------------------------- #
# 小工具
# --------------------------------------------------------------------------- #
def uptime_ms(app: FastAPI) -> int:
    """自 ``app.state.started_at`` 起始的毫秒数（helper，供 /health 等使用）。"""
    started = getattr(app.state, "started_at", None)
    if started is None:
        return 0
    return int((time.time() - started) * 1000)


def _parse_kinds(kinds: Optional[str]) -> Optional[Set[str]]:
    """``"rx,tx,mark"`` → ``{"rx","tx","mark"}``；空 → None。"""
    if not kinds:
        return None
    items = {part.strip() for part in kinds.split(",") if part.strip()}
    return items or None


def _http_token(request: Request) -> Optional[str]:
    auth = request.headers.get("authorization", "")
    if auth and auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.query_params.get("token")


def _ws_token(websocket: WebSocket) -> Optional[str]:
    auth = websocket.headers.get("authorization", "")
    if auth and auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return websocket.query_params.get("token")


# --------------------------------------------------------------------------- #
# 工厂
# --------------------------------------------------------------------------- #
def create_app(hub: "Hub", config: "Config") -> FastAPI:
    """构建并返回 FastAPI 应用（不启动服务器）。"""
    app = FastAPI(title="serialhub", version=VERSION, docs_url=None, redoc_url=None)
    app.state.started_at = time.time()

    server_cfg = getattr(config, "server", None)
    token: Optional[str] = getattr(server_cfg, "token", None) or None

    # ---- CORS -------------------------------------------------------------- #
    if getattr(server_cfg, "cors", False):
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
            allow_credentials=False,
        )

    # ---- 鉴权中间件（仅 /api/*，WS 在握手时单独校验） ----------------------- #
    if token:
        @app.middleware("http")
        async def _auth_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
            if request.url.path.startswith("/api/") and _http_token(request) != token:
                return JSONResponse(
                    status_code=401, content={"ok": False, "error": "unauthorized"}
                )
            return await call_next(request)

    # ---- 统一异常 → {"ok": false, "error": ...} ----------------------------- #
    @app.exception_handler(KeyError)
    async def _on_key_error(_req: Request, exc: KeyError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"ok": False, "error": f"unknown port: {exc}"})

    @app.exception_handler(ValueError)
    async def _on_value_error(_req: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(exc)})

    @app.exception_handler(RuntimeError)
    async def _on_runtime_error(_req: Request, exc: RuntimeError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"ok": False, "error": str(exc)})

    @app.exception_handler(RequestValidationError)
    async def _on_validation_error(_req: Request, _exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"ok": False, "error": "invalid request"})

    @app.exception_handler(Exception)
    async def _on_unhandled(_req: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500, content={"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        )

    # ---- 基础 / 健康检查 ---------------------------------------------------- #
    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "ok": True,
            "status": "ok",
            "version": VERSION,
            "uptime_ms": uptime_ms(app),
        }

    # ---- 端口列表 / 状态 ---------------------------------------------------- #
    @app.get("/api/ports")
    async def api_ports() -> dict[str, Any]:
        return {"ok": True, **hub.list_ports()}

    @app.get("/api/status")
    async def api_status(name: Optional[str] = None) -> dict[str, Any]:
        return {"ok": True, **hub.status(name)}

    @app.post("/api/ports/{name}/open")
    async def api_open(name: str, body: Optional[OpenBody] = None) -> dict[str, Any]:
        b = body or OpenBody()
        return {"ok": True, **hub.open(name, baud=b.baud, device=b.device)}

    @app.post("/api/ports/{name}/close")
    async def api_close(name: str) -> dict[str, Any]:
        return {"ok": True, **hub.close(name)}

    # ---- 数据：read / search / wait ---------------------------------------- #
    @app.get("/api/ports/{name}/read")
    async def api_read(
        name: str,
        since_seq: Optional[int] = None,
        since_ts: Optional[int] = None,
        filter_: Optional[str] = Query(None, alias="filter"),
        limit: Optional[int] = None,
        strip_ansi: bool = False,
        kinds: Optional[str] = None,
    ) -> dict[str, Any]:
        return {
            "ok": True,
            **hub.read(
                name,
                since_seq=since_seq,
                since_ts=since_ts,
                regex=filter_,
                limit=limit,
                strip_ansi=strip_ansi,
                kinds=_parse_kinds(kinds),
            ),
        }

    @app.get("/api/ports/{name}/search")
    async def api_search(
        name: str,
        regex: str,
        context: int = 0,
        since_seq: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> dict[str, Any]:
        return {
            "ok": True,
            **hub.search(name, regex, context=context, since_seq=since_seq, limit=limit),
        }

    @app.get("/api/ports/{name}/wait")
    async def api_wait(
        name: str,
        regex: str,
        timeout_ms: int = 10000,
        since_seq: Optional[int] = None,
    ) -> dict[str, Any]:
        return {
            "ok": True,
            **hub.wait_for(name, regex, timeout_ms=timeout_ms, since_seq=since_seq),
        }

    # ---- 数据：send / snapshot / export / clear / mark --------------------- #
    @app.post("/api/ports/{name}/send")
    async def api_send(name: str, body: SendBody) -> dict[str, Any]:
        return {
            "ok": True,
            **hub.send(
                name,
                body.data,
                eol=body.eol,
                wait_regex=body.wait_regex,
                timeout_ms=body.timeout_ms,
            ),
        }

    @app.get("/api/ports/{name}/snapshot")
    async def api_snapshot(name: str, tail_lines: int = 200) -> dict[str, Any]:
        return {"ok": True, **hub.snapshot(name, tail_lines=tail_lines)}

    @app.post("/api/ports/{name}/export")
    async def api_export(name: str, body: Optional[ExportBody] = None) -> dict[str, Any]:
        b = body or ExportBody()
        return {"ok": True, **hub.export(name, path=b.path, fmt=b.format, rng=b.range)}

    @app.post("/api/ports/{name}/clear")
    async def api_clear(name: str) -> dict[str, Any]:
        return {"ok": True, **hub.clear(name)}

    @app.post("/api/ports/{name}/mark")
    async def api_mark(name: str, body: MarkBody) -> dict[str, Any]:
        return {"ok": True, **hub.mark(name, body.label)}

    # ---- 桥 / 热重载 / 配置 ------------------------------------------------ #
    @app.post("/api/bridge")
    async def api_bridge(body: BridgeBody) -> dict[str, Any]:
        action = (body.action or "").lower()
        if action == "start":
            return {
                "ok": True,
                **hub.bridge_start(
                    body.port,
                    mode=body.mode or "server",
                    tcp_port=body.tcp_port,
                    host=body.host,
                ),
            }
        if action == "stop":
            return {"ok": True, **hub.bridge_stop(body.port)}
        if action == "status":
            return {"ok": True, **hub.bridge_status(body.port)}
        raise ValueError(f"unknown bridge action: {body.action!r}")

    @app.post("/api/reload")
    async def api_reload() -> dict[str, Any]:
        from .config import Config as RuntimeConfig  # 延迟导入：config.py 可能尚未落地

        path = getattr(config, "path", None)
        if not path:
            raise ValueError("no config source path to reload from")
        return {"ok": True, **hub.reload(RuntimeConfig.load(path))}

    @app.get("/api/config")
    async def api_config() -> dict[str, Any]:
        return {"ok": True, "config": config.to_dict(redact=True)}

    # ---- WebSocket --------------------------------------------------------- #
    @app.websocket("/ws")
    async def ws_endpoint(websocket: WebSocket) -> None:
        if token and _ws_token(websocket) != token:
            await websocket.accept()
            await websocket.send_json({"ok": False, "error": "unauthorized"})
            await websocket.close(code=1008)
            return

        await websocket.accept()

        # 1) 连接问候：推送当前端口概览
        try:
            listing = hub.list_ports()
            ports = listing.get("ports", []) if isinstance(listing, dict) else []
        except Exception:  # noqa: BLE001 - 问候失败不应中断连接
            ports = []
        await websocket.send_json({"type": "hello", "ports": ports})

        # 2) 订阅广播
        q = hub.subscribe()
        subscribed: Optional[Set[str]] = None  # None 表示全部端口

        async def _pump() -> None:
            """后台任务：把阻塞队列的事件喂给 WebSocket。"""
            while True:
                try:
                    event = await asyncio.to_thread(q.get, True, 1.0)
                except queue.Empty:
                    continue
                except Exception:  # noqa: BLE001
                    break
                if subscribed is not None and isinstance(event, dict):
                    ev_port = event.get("port")
                    if ev_port is not None and ev_port not in subscribed:
                        continue
                try:
                    await websocket.send_json(event)
                except Exception:  # noqa: BLE001 - 客户端已断开
                    break

        async def _handle_client_message(raw: str) -> None:
            nonlocal subscribed
            try:
                msg = json.loads(raw)
            except (ValueError, TypeError):
                return
            if not isinstance(msg, dict):
                return
            mtype = msg.get("type")
            if mtype == "ping":
                await websocket.send_json({"type": "pong"})
            elif mtype == "subscribe":
                names = msg.get("ports")
                if isinstance(names, list):
                    resolved = {str(n) for n in names}
                    subscribed = resolved or None
            elif mtype == "mark":
                port = msg.get("port")
                label = str(msg.get("label", ""))
                if port:
                    try:
                        hub.mark(port, label)
                    except Exception:  # noqa: BLE001 - best-effort
                        pass

        pump_task = asyncio.create_task(_pump())
        try:
            while True:
                raw = await websocket.receive_text()
                await _handle_client_message(raw)
        except WebSocketDisconnect:
            pass
        except Exception:  # noqa: BLE001
            pass
        finally:
            pump_task.cancel()
            try:
                hub.unsubscribe(q)
            except Exception:  # noqa: BLE001
                pass

    # ---- 静态 UI ----------------------------------------------------------- #
    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/")
    async def index() -> Any:
        index_file = STATIC_DIR / "index.html"
        if index_file.is_file():
            return FileResponse(str(index_file))
        return JSONResponse(status_code=404, content={"ok": False, "error": "ui not built"})

    return app


__all__ = ["create_app", "uptime_ms"]
