# serialhub 架构与接口契约（v1，冻结）

> 本文件是**并行开发唯一事实来源**。所有模块必须严格按此处签名实现，不得改名/改返回结构。
> 语言 Python 3.10+（本机 3.12）。运行时依赖仅：`pyserial, fastapi, uvicorn, pyyaml, websockets`（+ 可选 `mcp`）。
> 禁止引入上述之外的新依赖（标准库随意）。类型注解齐全；Windows/Linux 均可运行。

---

## 1. 进程模型

```
┌─────────────────────────────── serialhub serve（常驻守护，单进程） ───────────────────────────────┐
│  Hub（serialhub/hub.py）                                                                           │
│   ├── SerialPortWorker × N  （每口一个线程：持久打开/读行/写/断线重连）                             │
│   ├── RingBuffer × N        （每口环形缓冲，含 seq/ts_ms）                                          │
│   ├── 全局单调序号 seq（线程安全）                                                                  │
│   ├── 订阅广播（WebSocket + wait_for 唤醒）                                                        │
│   └── TcpBridge × M         （tcp_bridge.py，把某口暴露为 TCP / 或作客户端透传）                    │
│  server.py（FastAPI + uvicorn，同进程）→ REST /api/* + WebSocket /ws + 静态 Web UI(/static)        │
└────────────────────────────────────────────────────────────────────────────────────────────────┘
              ▲ HTTP/WS（Bearer token 可选）
              │
      serialhub <cmd>（cli.py，轻量客户端）──► 打印单行 JSON envelope {ok, data|error}
              ▲
              │ 同 serialhub/client.py
      serialhub mcp --stdio（mcp_server.py）──► 暴露 MCP tools（结构化 JSON），供 agent 调用
```

- **MCP 是瘦客户端**：它（与 CLI）通过 HTTP 调用常驻守护；守护必须先 `serve`。这与本仓 ecosystem 既有做法一致（MCP 包一层客户端协议，保持单一事实来源）。
- CLI 与 MCP 共用 `serialhub/client.py`（stdlib `urllib.request`，无额外依赖）。

---

## 2. 文件归属（并行不重叠）

| 文件 | 归属 | 说明 |
|---|---|---|
| `serialhub/__init__.py` | A | 版本、导出关键符号 |
| `serialhub/__main__.py` | A | `from .cli import main; main()`（若 cli 未就绪则延迟导入） |
| `serialhub/models.py` | A | `Line`、ANSI 工具、EOL 工具、`now_ms()` |
| `serialhub/ringbuffer.py` | A | `RingBuffer` |
| `serialhub/config.py` | A | `Config`/`PortConfig`/...、加载/校验/热重载合并 |
| `serialhub/serialport.py` | A | `SerialPortWorker` |
| `serialhub/hub.py` | A | `Hub`（核心） |
| `serialhub/exporter.py` | A | 导出 raw/noansi/json |
| `serialhub/server.py` | B | `create_app(hub, config)`（FastAPI）+ mount static |
| `serialhub/static/index.html` `.js` `.css` | B | Web UI（xterm.js） |
| `serialhub/tcp_bridge.py` | D | `TcpBridge` |
| `serialhub/client.py` | C | HTTP 客户端（stdlib） |
| `serialhub/cli.py` | C | 命令行（含 serve 入口） |
| `serialhub/mcp_compat.py` | C | 兼容 mcp 1.x(FastMCP)/2.x(MCPServer) |
| `serialhub/mcp_server.py` | C | MCP tools |
| `tools/mcp_smoke.py` | C | MCP stdio 冒烟客户端 |
| `tests/*` | E | 单测 |
| `README.md` / `docs/*` / `examples/*` | F | 文档 |

> B/C/D 实现时**按本契约编码**，不要依赖 A 的中间状态；A 完成后统一联调。

---

## 3. 数据模型（models.py，A 实现，所有人依赖）

```python
from dataclasses import dataclass, field
from typing import Optional
import re, time

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[@-Z\\-_]")

def strip_ansi(text: str) -> str: ...      # 去除 ANSI 控制序列
def has_ansi(text: str) -> bool: ...
def now_ms() -> int: ...                   # int(time.time()*1000)

KIND_RX = "rx"; KIND_TX = "tx"; KIND_MARK = "mark"

@dataclass(frozen=True, slots=True)
class Line:
    seq: int          # 全局单调递增（跨所有口唯一）
    port: str         # 逻辑口名
    ts_ms: int        # 接收时刻（epoch 毫秒）
    text: str         # 一行文本，**不含行尾 EOL**；可能含 ANSI 转义
    ansi: bool = False# text 是否含 ANSI
    kind: str = "rx"  # rx=收到 | tx=本进程发出（回显） | mark=标记

    def to_dict(self, strip: bool = False) -> dict:
        """{'seq','port','ts_ms','text','ansi','kind'}；strip=True 时 text 去 ANSI。"""
```

EOL 工具：
```python
def resolve_eol(eol: Optional[str], default: str = "\r\n") -> bytes:
    """crlf|lf|cr|none|\r\n|\n|\r|Literal → bytes。'none'→b''。"""
```

---

## 4. RingBuffer（ringbuffer.py，A 实现）

```python
class RingBuffer:
    def __init__(self, max_lines: int = 20000, max_bytes: int = 8*1024*1024): ...

    def append(self, line: Line) -> None:        # 越界自动淘汰最老（行数/字节双阈值）
    def clear(self) -> None:
    def stats(self) -> dict:
        # {'count','bytes','first_seq','last_seq','dropped_total'}
    def snapshot(self, tail: Optional[int] = None) -> list[Line]:
        # tail=None→全部；否则最后 tail 行（新→旧排列? 一律旧→新升序）
    def oldest_seq(self) -> Optional[int]: ...
    def newest_seq(self) -> Optional[int]: ...
    def read(self, *, since_seq=None, since_ts=None, regex=None, limit=None,
             strip_ansi: bool=False, kinds: Optional[set[str]]=None) -> dict:
        # 见 §4.1 语义
    def search(self, regex: str, *, context: int=0, since_seq=None, limit=None) -> dict:
        # 见 §4.2
```

### 4.1 `read` 语义（**无重复消费**关键）
- 游标：优先 `since_seq`（返回 `seq > since_seq`）；否则 `since_ts`（返回 `ts_ms > since_ts`）；都没有→返回末尾 `limit`（默认按调用方给的 limit，None→全部保留行）。
- `regex` 非空→仅返回匹配行；`kinds` 非空→仅返回这些 kind；`strip_ansi=True`→text 去 ANSI。
- `limit` 截断后第一个未返回的行即下次 `next_seq`。
- 返回：
```python
{
  "lines": [Line.to_dict(strip_ansi) ...],   # 旧→新
  "count": int,          # 本次返回行数
  "next_seq": int,       # = 最后返回行的 seq；无返回则 = 传入游标（或最新 seq）
  "dropped": int,        # 因缓冲淘汰而永久丢失的行数（游标早于最老保留行时 >0）
  "has_more": bool,      # 缓冲中仍有 seq>next_seq 且满足条件的行未返回
  "first_seq": int|None, # 当前缓冲最老 seq
  "last_seq": int|None,  # 当前缓冲最新 seq
}
```
`dropped` 定义：若传入 `since_seq` 且 `since_seq < first_seq - 1`，则 `dropped = first_seq - 1 - since_seq`；否则 0。

### 4.2 `search` 语义
```python
{
  "hits": [
    {"seq","ts_ms","text","kind",
     "match": "<命中的子串>",
     "context_before": [{"seq","ts_ms","text"}...],   # context>0 时
     "context_after":  [{"seq","ts_ms","text"}...]}
  ],
  "count": int, "next_seq": int, "regex": str
}
```
`since_seq` 仅搜 `seq>since_seq`；`limit` 限制命中数。

---

## 5. Config（config.py，A 实现）

```python
@dataclass
class ServerConfig:
    host: str = "127.0.0.1"; port: int = 8765
    token: Optional[str] = None; cors: bool = True

@dataclass
class PortConfig:
    name: str; device: str
    baud: int = 115200
    data_bits: int = 8            # 5..8
    parity: str = "N"             # N|E|O|M|S
    stop_bits: float = 1          # 1|1.5|2
    flow: str = "none"            # none|rtscts|xonxoff|dsrdtr
    dtr: bool = True; rts: bool = True
    eol: str = "\r\n"
    encoding: str = "utf-8"
    reconnect_ms: int = 1000; reconnect_max_ms: int = 10000
    flush_ms: int = 50
    buffer_lines: int = 20000; buffer_bytes: int = 8*1024*1024
    autostart: bool = True
    tcp_bridge: Optional[dict] = None   # {mode:'server'|'client', port:int, host:str|None}

@dataclass
class LoggingConfig:
    enabled: bool = False; dir: str = "logs"; max_mb: int = 16; backups: int = 3

@dataclass
class UIConfig:
    theme: str = "dark"; timestamp: bool = True; max_render_lines: int = 5000

@dataclass
class Config:
    server: ServerConfig; ports: list[PortConfig]
    logging: LoggingConfig; ui: UIConfig
    path: Optional[str] = None           # 来源文件（热重载用）
    defaults: dict = field(default_factory=dict)

    @staticmethod
    def load(path: str) -> "Config":
        """按扩展名 .yaml/.yml→yaml, 否则 json；顶层 defaults 逐项合并进每个 port；校验后返回。"""
    def to_dict(self, *, redact: bool = True) -> dict:
        """redact=True 时把 server.token 置为 None 或以 '***' 替代。"""
    def port(self, name: str) -> PortConfig:      # 未知 name → KeyError
    def port_names(self) -> list[str]: ...
    def merge_overrides(self, **kw) -> "Config":  # 命令行覆盖 host/port/...
```

校验（`load` 内）：name 唯一非空；device 非空；`data_bits∈{5,6,7,8}`；`parity∈{N,E,O,M,S}`（大小写归一）；`stop_bits∈{1,1.5,2}`；`flow∈{none,rtscts,xonxoff,dsrdtr}`；`buffer_lines>0`；`buffer_bytes>0`。非法→`ValueError`（消息含字段路径）。

---

## 6. Hub（hub.py，A 实现）—— 全体后端依赖

```python
class Hub:
    def __init__(self, config: Config) -> None: ...

    # 生命周期
    def start(self) -> None:                      # 打开 autostart 口 + 起 config 里声明的 tcp_bridge
    def stop(self) -> None:                       # 关所有口+桥；幂等
    def reload(self, new_config: Config) -> dict: # 热重载（见 §6.3）

    # 端口
    def add_port(self, pc: PortConfig, *, autostart: bool = True) -> None
    def remove_port(self, name: str) -> None
    def open(self, name: str, *, baud: int|None = None, device: str|None = None) -> dict
    def close(self, name: str) -> dict
    def is_open(self, name: str) -> bool

    # 查询
    def list_ports(self) -> dict
    def status(self, name: str|None = None) -> dict

    # 数据
    def read(self, name, *, since_seq=None, since_ts=None, regex=None,
             limit=None, strip_ansi=False, kinds=None) -> dict
    def search(self, name, regex, *, context=0, since_seq=None, limit=None) -> dict
    def wait_for(self, name, regex, *, timeout_ms=10000, since_seq=None) -> dict
    def snapshot(self, name, *, tail_lines=200) -> dict
    def export(self, name, *, path=None, fmt="raw", rng=None) -> dict
    def clear(self, name) -> dict
    def mark(self, name, label) -> dict
    def send(self, name, data, *, eol=None, wait_regex=None, timeout_ms=None) -> dict

    # 供 SerialPortWorker / TcpBridge 使用
    def next_seq(self) -> int:                    # 线程安全自增
    def ingest(self, port, text, *, kind="rx", ts_ms=None) -> Line   # 建行→入环→广播
    def write_bytes(self, name, data: bytes) -> int   # 原始字节写串口（不追加 EOL）
    def subscribe(self) -> "queue.Queue[dict]": ...   # 广播队列（事件见下）
    def unsubscribe(self, q) -> None: ...

    # 桥
    def bridge_start(self, name, *, mode="server", tcp_port=None, host=None) -> dict
    def bridge_stop(self, name) -> dict
    def bridge_status(self, name=None) -> dict

    @property
    def config(self) -> Config: ...
```

### 6.1 返回结构（REST/MCP 直接透传其 `data`）
**`list_ports()`**
```python
{"system":[{"device","description","hwid"}...],       # serial.tools.list_ports
 "ports":[{"name","device","open":bool,"baud","data_bits","parity","stop_bits",
           "flow","rx_lines","tx_lines","last_error","reconnect_count",
           "buffer":{"count","bytes","first_seq","last_seq","dropped_total"},
           "tcp_bridge":{"mode","port","host","active"}|None}...]}
```
**`status(name=None)`**：`name` 给定→单个 port dict（同 ports[] 元素）加 `"server"` 字段；否则
```python
{"server":{"host","port","version","uptime_ms"},"ports":[<port dict>...]}
```
**`read(...)`**：同 §4.1，另加 `"port": name`。
**`search(...)`**：同 §4.2，另加 `"port": name`。
**`wait_for(...)`**
```python
{"port":name,"matched":bool,"line":{Line dict}|None,"seq":int|None,"ts_ms":int|None,"from_seq":int}
```
（`from_seq` = 本次等待起点游标）
**`send(...)`**
```python
{"port":name,"sent_bytes":int,"sent":str,"waited":bool,"matched":bool,
 "line":{Line dict}|None,"seq":int|None}
```
**`snapshot(...)`**：`{"port":name,"tail_lines":n,"lines":[...],"count":n}`
**`export(...)`**：`{"port":name,"path":str,"format":"raw|noansi|json","bytes":int,"count":int}`
**`mark(...)`**：`{"port":name,"label":str,"seq":int,"ts_ms":int}`
**`clear(...)`**：`{"port":name,"cleared":int}`
**`bridge_start/stop/status`**：`{"port":name,"mode","tcp_port","host","active":bool}`

### 6.2 广播事件（subscribe 队列元素）
- `{"type":"line","port":name,"line":{Line dict}}`（每次 ingest 都发；含 rx/tx/mark）
- `{"type":"status","port":name,"open":bool,...}`（开/关/重连变化时）
- `{"type":"mark","port":name,"label":...,"seq":...}`（可选，line 已足够）

### 6.3 `reload(new_config)`
- 更新 `self._config`；对每个口：若缓冲区上限变化→用新上限重建 RingBuffer 并**保留现有行**；若设备/参数变化且已打开→重启该 worker；新增口→add_port；移除的口→close+remove；桥按需重建。
- 返回 `{"added":[...],"removed":[...],"restarted":[...],"updated":[...]}`。

---

## 7. SerialPortWorker（serialport.py，A 实现，仅 Hub 使用）

```python
class SerialPortWorker(threading.Thread):
    def __init__(self, pc: PortConfig, hub: Hub) -> None: ...
    @property
    def is_open(self) -> bool: ...
    @property
    def last_error(self) -> Optional[str]: ...
    @property
    def reconnect_count(self) -> int: ...
    @property
    def rx_lines(self) -> int: ...
    @property
    def tx_lines(self) -> int: ...
    def open(self) -> None:       # 立即尝试打开（失败置 last_error，不抛）
    def close(self) -> None:      # 停止线程并释放端口
    def write(self, data: bytes) -> int:   # 线程安全；未开→抛 RuntimeError
    def status(self) -> dict: ...
```
要点：
- 用 `serial.serial_for_url(pc.device, baudrate=pc.baud, bytesize=pc.data_bits, parity=pc.parity,
  stopbits=pc.stop_bits, rtscts=pc.flow=="rtscts", xonxoff=pc.flow=="xonxoff",
  dsrdtr=pc.flow=="dsrdtr", timeout=0.1, write_timeout=1)`；随后按需 `setDTR/setRTS`。
- 读循环：`read(4096)`；累积字节→按 `\n`/`\r` 断行（`\r\n` 视为一个）；无换行残行超过 `flush_ms` 也吐出。
- 每个完整行→`hub.ingest(name, text, kind="rx")`（解码 `pc.encoding`, errors="replace"）。
- 断线：捕获串口异常→关闭→`hub` 广播 status→按 `reconnect_ms` 指数退避至 `reconnect_max_ms` 重试；**旧缓冲不丢**。
- `close()` 唤醒读循环并 join（带超时）。

---

## 8. Exporter（exporter.py，A 实现）

```python
def export_text(lines: list[Line], fmt: str = "raw") -> str:
    """raw: 原样 text+\\n；noansi: 去 ANSI text+\\n；json: 每行一个 JSON 对象(JSONL)。"""
def export_to_file(lines, path, fmt="raw") -> int:   # 返回写入字节数
```

---

## 9. REST / WebSocket 契约（server.py，B 实现）

- 基址 `http://{server.host}:{server.port}`；若 `server.token` 非空→`/api/*` 与 `/ws` 需
  `Authorization: Bearer <token>`（WS 亦可用 `?token=`）。失败→HTTP 401 `{"ok":false,"error":"unauthorized"}`。
- 所有 JSON 响应：成功 `{"ok":true, ...}`，失败 `{"ok":false,"error":"..."}`（4xx/5xx）。
- `create_app(hub: Hub, config: Config) -> fastapi.FastAPI` 供 `cli serve` 调用。
- 端点（`{}` 中为路径参数）：
  | 方法 | 路径 | 参数/体 | 返回 |
  |---|---|---|---|
  | GET | `/health` | — | `{"ok":true,"status":"ok","version","uptime_ms"}` |
  | GET | `/api/ports` | — | `{"ok":true,**hub.list_ports()}` |
  | GET | `/api/status` | `name?` | `{"ok":true,**hub.status(name)}` |
  | POST | `/api/ports/{name}/open` | `{baud?,device?}` | `{"ok":true,**hub.open(...)}` |
  | POST | `/api/ports/{name}/close` | — | `{"ok":true,**hub.close(...)}` |
  | GET | `/api/ports/{name}/read` | `since_seq?,since_ts?,filter?,limit?,strip_ansi?,kinds?` | `{"ok":true,**hub.read(...)}` |
  | GET | `/api/ports/{name}/search` | `regex,context?,since_seq?,limit?` | `{"ok":true,**hub.search(...)}` |
  | GET | `/api/ports/{name}/wait` | `regex,timeout_ms?,since_seq?` | `{"ok":true,**hub.wait_for(...)}` |
  | POST | `/api/ports/{name}/send` | `{data,eol?,wait_regex?,timeout_ms?}` | `{"ok":true,**hub.send(...)}` |
  | GET | `/api/ports/{name}/snapshot` | `tail_lines?` | `{"ok":true,**hub.snapshot(...)}` |
  | POST | `/api/ports/{name}/export` | `{path?,format?,range?}` | `{"ok":true,**hub.export(...)}` |
  | POST | `/api/ports/{name}/clear` | — | `{"ok":true,**hub.clear(...)}` |
  | POST | `/api/ports/{name}/mark` | `{label}` | `{"ok":true,**hub.mark(...)}` |
  | POST | `/api/bridge` | `{action,port,mode?,tcp_port?,host?}` | `{"ok":true,**bridge_*}` |
  | POST | `/api/reload` | — | `{"ok":true,**hub.reload(Config.load(config.path))}` |
  | GET | `/api/config` | — | `{"ok":true,"config":config.to_dict(redact=True)}` |
  | WS  | `/ws` | — | 服务端推送 `hub.subscribe()` 事件原样（`type`∈line/status/mark/hello） |
- 参数命名：`filter`（read 的正则）与 `regex`（search/wait/send 的正则）不同名，勿混。
- 布尔参数接受 `true/false/1/0`。`kinds` 逗号分隔。
- 静态 UI：`GET /` 返回 `serialhub/static/index.html`；`/static/*` 挂载静态目录。UI 通过 `/ws` 与 `/api/*` 工作。

**Web UI（B）必须满足**：深色为主可切浅色；xterm.js（CDN 或本地，需能离线降级）；多口标签页；ANSI 彩色渲染；每行时间戳开关 + 序号；实时过滤（regex）+ 搜索高亮/跳转；暂停/继续、自动滚屏、清屏；导出 raw/noansi/json；发送栏（选口/输入/结尾选项/历史）；顶部统计（行速率/字节速率/缓冲占用）；连接状态与波特率显示。

---

## 10. CLI 契约（cli.py，C 实现）

- 入口：`main(argv=None) -> int`。`serialhub serve` 运行守护（不打印 JSON）；其余子命令打印**单行 JSON**：
  `{"ok":true,"data":<...>}` 或 `{"ok":false,"error":"<msg>"}`；退出码 0=ok，1=失败。
- 全局参数（`--url` 默认 `http://127.0.0.1:8765`；`--token` 或环境变量 `SERIALHUB_TOKEN`）。
- 子命令 → REST 映射：
  | CLI | REST |
  |---|---|
  | `serve --config F [--host][--port][--no-autostart][--log-level]` | 启 uvicorn + Hub |
  | `list` | GET /api/ports |
  | `status [NAME]` | GET /api/status |
  | `open NAME [--baud][--device]` | POST /api/ports/{n}/open |
  | `close NAME` | POST /api/ports/{n}/close |
  | `read NAME [--since-seq][--since-ts][--filter][--limit][--strip-ansi][--kinds]` | GET .../read |
  | `search NAME REGEX [--context][--since-seq][--limit]` | GET .../search |
  | `wait NAME REGEX [--timeout-ms][--since-seq]` | GET .../wait |
  | `send NAME DATA [--eol][--wait-regex][--timeout-ms]` | POST .../send |
  | `snapshot NAME [--tail-lines]` | GET .../snapshot |
  | `export NAME [--path][--format][--range]` | POST .../export |
  | `mark NAME LABEL` | POST .../mark |
  | `clear NAME` | POST .../clear |
  | `bridge {start,stop,status} --port NAME [--mode][--tcp-port][--host]` | POST /api/bridge |
  | `reload` | POST /api/reload |
  | `ports` | `list` 别名 |
  | `mcp [--stdio]` | 运行 MCP（见 §11） |
- `send` 的 `DATA` 为 `-` 时读 stdin（去尾随换行）。`--eol` 接受 `crlf|lf|cr|none`；默认取该口 `Config` 的 `eol`（客户端不知道时用 `\r\n`）。
- `--kinds` 逗号分隔（rx,tx,mark）。

---

## 11. MCP 契约（mcp_server.py + client.py，C 实现）

- 传输：stdio（默认）。`serialhub mcp --stdio` 启动。
- 兼容垫片 `mcp_compat.py`：
  ```python
  try:
      from mcp.server.fastmcp import FastMCP as MCPServer      # mcp 1.x
  except Exception:
      from mcp.server.mcpserver import MCPServer                # mcp 2.x
  from mcp.types import ToolAnnotations
  ```
- `client.py`（stdlib `urllib.request`）：
  ```python
  class Client:
      def __init__(self, base_url: str, token: str|None = None, timeout: float = 30.0): ...
      def call(self, method: str, path: str, *, params: dict|None=None,
               body: dict|None=None, timeout: float|None=None) -> dict:
          """返回 REST 的 JSON（已含 ok）。连接失败→{'ok':False,'error':'...'}。
          按需把 params 转 query（None 值省略；bool→'true'/'false'）。"""
  ```
- 工具（名字即 MCP 工具名；返回 `{"ok":true,...}` / `{"ok":false,"error"}`）：
  | 工具 | 参数 | 返回关键字段 |
  |---|---|---|
  | `list_ports` | — | `system[]`,`ports[]` |
  | `open` | `port, baud=115200, device=None` | `port` dict |
  | `close` | `port` | `port` dict |
  | `status` | `port=None` | `server`,`ports[]` 或单口 |
  | `read` | `port, since_seq=None, since_ts=None, filter=None, limit=None, strip_ansi=False` | `lines[{seq,ts_ms,text}]`,`next_seq`,`count`,`dropped`,`has_more` |
  | `search` | `port, regex, context=0, since_seq=None, limit=None` | `hits[]`,`count`,`next_seq` |
  | `wait_for` | `port, regex, timeout_ms=10000, since_seq=None` | `matched`,`line`,`seq`,`ts_ms`,`from_seq` |
  | `send` | `port, data, eol="\r\n", wait_regex=None, timeout_ms=None` | `sent_bytes`,`waited`,`matched`,`line`,`seq` |
  | `snapshot` | `port, tail_lines=200` | `lines[]`,`count` |
  | `export` | `port, path=None, format="raw", range=None` | `path`,`bytes`,`format`,`count` |
  | `tcp_bridge` | `action, port, tcp_port=None, mode="server", host=None` | `active`,`mode`,`tcp_port` |
  | `mark` | `port, label` | `seq`,`ts_ms` |
  | `clear` | `port` | `cleared` |
  | `reload` | — | `added/removed/restarted/updated` |
- `wait_for` 用长超时（`timeout_ms/1000 + 10`s）。工具在 worker 线程调用 `Client`（`asyncio.to_thread`），事件循环不阻塞。
- `tools/mcp_smoke.py`：自写 stdio JSON-RPC 客户端，`initialize`+`tools/list`（默认）；`--full` 再跑 `list_ports`。

---

## 12. TcpBridge（tcp_bridge.py，D 实现）

```python
class TcpBridge:
    def __init__(self, hub: "Hub", port: str, *, mode: str = "server",
                 tcp_port: int | None = None, host: str | None = None,
                 bind: str = "127.0.0.1") -> None: ...
    def start(self) -> dict:   # {"port","mode","tcp_port","host","active":True}
    def stop(self) -> dict:    # active:False
    def status(self) -> dict:  # 含 active/clients 计数
```
- **server**：`bind:tcp_port` 监听（默认 bind=127.0.0.1，可由 Hub 参数放宽到 0.0.0.0）；多客户端。
  客户端写入的字节→`hub.write_bytes(port, data)`，并 `hub.ingest(port, text, kind="tx")` 供观测；
  `hub.subscribe()` 收到该口 `type=="line"` 事件→把 `line.text`+该口 `eol` 编码后写回客户端。
- **client**：连接 `host:tcp_port`；远端→串口（write_bytes+ingest tx），串口→远端（同订阅）。
- 线程实现（threading + socket），`stop()` 需唤醒并 join 所有线程（带超时），幂等。
- 缺 `tcp_port`（server）或 `host`（client）→ raise ValueError。

---

## 13. 统一约定
- 所有时间：epoch 毫秒（`now_ms()`）。所有 seq：全局 int。
- 所有对外 JSON 一律 `{"ok": bool, ...}`；错误必须带 `"error": "<可读消息>"`。
- 禁止吞异常（空 `except`）；错误转成 `ok:false` 或记录到 `last_error`。
- 线程安全：Hub 的 seq/缓冲/队列用锁；worker 不直接改缓冲，一律经 `hub.ingest`。
- 类型注解齐全；`from __future__ import annotations`；文件头 docstring 说明职责。
- `__init__.py` 暴露 `__version__ = "0.1.0"`。
