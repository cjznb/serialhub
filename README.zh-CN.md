**简体中文** · [English](README.md)

# serialhub · 常驻串口中枢

[![CI](https://github.com/cjznb/serialhub/actions/workflows/ci.yml/badge.svg)](https://github.com/cjznb/serialhub/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

把一个或多个串口变成**常驻、可回看、可增量读取、对 AI agent 极友好**的服务：

- **守护进程**持久打开端口，逐行落进每口**环形缓冲**（全局单调 `seq` + epoch 毫秒 `ts_ms`）。
- **Web UI**（xterm.js）实时看多个口、过滤、搜索、导出、发送。
- **REST + WebSocket** 暴露全部能力；**CLI** 与 **MCP 服务器**共用同一份瘦客户端。
- **TCP 桥**把某个口透传成 TCP（server 监听 / client 连出）。
- **MCP 工具**让 agent 用 `wait_for` 阻塞等哨兵、用 `since_seq` 游标续读，**不重复消费**。

> 设计契约（数据模型 / Hub / REST / CLI / MCP，全部冻结）见 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)。
> MCP 专项说明见 [`docs/MCP.zh-CN.md`](docs/MCP.zh-CN.md)。
> DSH（DeepSeek Harness）接入全过程见 [`docs/DSH.zh-CN.md`](docs/DSH.zh-CN.md)。

---

## 0. 一句话

`python -m serialhub serve --config config.example.yaml` 起守护，浏览器开 `http://127.0.0.1:8765/`，
命令行 `python -m serialhub list` / MCP `wait_for` 立刻可用；**没有硬件也能用 `loop://` 空跑全链路**。

---

## 1. 特性一览

| 能力 | 说明 |
|---|---|
| 常驻多口 | 每口一个读线程，持久打开、断线按指数退避重连（**旧缓冲不丢**） |
| 自动发现 | 某口可用 `match` 规格替代固定 `device`；**打开时解析、每次重连前重新解析**，故拔插后换到别的 COM 仍能找回 |
| 环形缓冲 | 每口按**行数 + 字节**双阈值淘汰最老行；默认 20000 行 / 8 MiB |
| 全局序号 | `seq` 跨所有口单调递增、线程安全；`ts_ms` 为接收时刻 epoch 毫秒 |
| 逐行类型 | `kind ∈ {rx, tx, mark}`：收到 / 本进程发出（回显）/ 标记 |
| 无重复消费 | `read` 支持 `since_seq` / `since_ts` 游标，返回 `next_seq` 供续读 |
| 阻塞哨兵 | `wait_for` 阻塞等某行匹配正则；**超时不是错误**（`matched:false`，仍 `ok:true`） |
| 搜索 | `search` 正则搜全缓冲，可带上下文窗口 |
| 导出 | raw / noansi / json(JSONL) 落盘 |
| REST + WS | 每个 CLI 动作都有对应 REST 端点；`/ws` 推送实时行事件 |
| Web UI | 深/浅色、多标签、ANSI 彩色、时间戳/序号、过滤/搜索、暂停/清屏、导出、发送栏 |
| TCP 桥 | server（监听，客户端写=下发串口）/ client（连远端透传） |
| CLI | 每个子命令输出**单行 JSON** `{"ok":true,"data":{...}}`，退出码 0/1 |
| MCP | 16 个工具（stdio），让 agent 直接以工具调用操作串口 |
| 热重载 | 改配置后 `serialhub reload`，增删口 / 改参数 / 重建缓冲即时生效 |
| 无硬件演示 | `device: loop://` 直接空跑 open→send→read→wait_for |

---

## 2. 目录结构

```
serialhub/
├── README.md                 # 本文件（用户手册）
├── docs/
│   ├── ARCHITECTURE.md        # 冻结契约（唯一事实来源）
│   ├── MCP.md                 # MCP 使用说明（16 工具参考 + agent 手册）
│   └── DSH.md                 # DSH（DeepSeek Harness）接入全过程
├── examples/
│   ├── config.yaml            # loop:// 演示 + 带注释的真实口
│   ├── mcp_client.py          # 可运行的编程式客户端示例
│   └── agent_wait_for.md      # agent 用 wait_for 等哨兵的 walkthrough
├── config.example.yaml        # 配置样例
├── requirements.txt           # 运行时依赖
├── requirements-dev.txt       # 开发/测试依赖（pytest/httpx/mcp）
├── pyproject.toml             # 打包元数据（serialhub 入口 / pytest 配置）
├── pytest.ini                 # pytest 入口
├── serialhub/
│   ├── __main__.py            # python -m serialhub 入口
│   ├── cli.py                 # 命令行（serve/list/open/read/wait/send/bridge/mcp/...）
│   ├── client.py              # HTTP 瘦客户端（stdlib，CLI/MCP 共用）
│   ├── mcp_server.py          # MCP 16 工具（stdio）
│   ├── mcp_compat.py          # mcp 1.x/2.x 兼容垫片
│   ├── server.py              # FastAPI + REST + WS + 静态 UI
│   ├── hub.py                 # 中枢（端口/缓冲/广播/桥/等待）
│   ├── serialport.py          # 每口读线程 + 断线重连
│   ├── ringbuffer.py          # 每口环形缓冲（read/search）
│   ├── tcp_bridge.py          # TCP 桥
│   ├── exporter.py            # 导出格式化
│   ├── config.py              # 配置模型/加载/校验
│   ├── discovery.py           # 端口自动发现（match 规格 -> 真实设备名）
│   ├── models.py              # Line / ANSI / EOL / now_ms
│   └── static/                # Web UI（index.html + app.js + style.css）
├── tests/                     # 单元/集成测试
└── tools/
    └── mcp_smoke.py           # 自写 MCP stdio 冒烟客户端
```

---

## 3. 环境要求与安装

| 依赖 | 版本 | 说明 |
|---|---|---|
| Python | 3.10+（本机实测 3.12） | 运行时与 CLI |
| pyserial | >= 3.5 | 串口 |
| fastapi / uvicorn[standard] | >= 0.110 / >= 0.27 | HTTP + WS |
| pyyaml | >= 6.0 | 配置解析 |
| websockets | >= 12 | uvicorn WS |
| mcp | >= 1.9（可选） | 仅 MCP 服务器需要 |

```powershell
# 1) 运行时依赖（必装）
pip install -r requirements.txt

# 2) MCP 支持（可选，装完才有 serialhub mcp）
pip install "mcp>=1.9"
#   或直接： pip install -r requirements-dev.txt   # 含 pytest/httpx/mcp

# 3) 以源码包安装，获得 serialhub 控制台入口（可选但推荐）
pip install -e .
```

装完后两种等价入口：

```powershell
python -m serialhub list          # 始终可用（源码在 PYTHONPATH）
serialhub list                    # pip install -e . 之后可用
```

---

## 4. 快速开始

### 4.1 无硬件演示（`loop://`）

```powershell
# 用带 loop:// 演示口的配置起服务（examples/config.yaml 已备好 demo 口）
python -m serialhub serve --config examples/config.yaml
```

看到 uvicorn 起来后：

```powershell
# 列端口（会看到 demo 口 open=true，device=loop://）
python -m serialhub list

# 发一条，再读回来（loop:// 会把写出的字节原样送回）
python -m serialhub send demo "hello" --eol crlf
python -m serialhub read demo --limit 20

# 阻塞等一条回应（此处 loop 立即回显，立刻命中）
python -m serialhub wait demo "hello" --timeout-ms 3000
```

浏览器打开 <http://127.0.0.1:8765/> 即见 Web UI。

### 4.2 接真实串口

```powershell
python -m serialhub serve --config config.example.yaml
# 命令行覆盖监听地址/端口/日志级别：
python -m serialhub serve --config config.example.yaml --host 0.0.0.0 --port 8765 --log-level info
# 起来后不自动打开任何口，等显式 open：
python -m serialhub serve --config config.example.yaml --no-autostart
```

---

## 5. 配置文件详解

配置为 **YAML 或 JSON**（按扩展名 `.yaml/.yml` 用 YAML，其它用 JSON）。顶层结构如下。
逐项字段与默认值（`config.py` / `config.example.yaml` 一致）：

### 5.1 `server`（HTTP/WS 监听与鉴权）

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `host` | str | `127.0.0.1` | 监听地址；`0.0.0.0` 对外 |
| `port` | int | `8765` | 监听端口 |
| `token` | str\|null | `null` | 非空时 `/api/*` 与 `/ws` 需 `Authorization: Bearer <token>` |
| `cors` | bool | `true` | 是否允许跨域（开发方便） |

### 5.2 `defaults`（所有口的默认参数，可被每个 `ports[]` 逐项覆盖）

| 字段 | 类型 | 默认 | 取值 / 说明 |
|---|---|---|---|
| `baud` | int | `115200` | 波特率 |
| `data_bits` | int | `8` | `5\|6\|7\|8` |
| `parity` | str | `N` | `N\|E\|O\|M\|S`（大小写归一） |
| `stop_bits` | float | `1` | `1\|1.5\|2` |
| `flow` | str | `none` | `none\|rtscts\|xonxoff\|dsrdtr` |
| `dtr` | bool | `true` | 打开后是否置 DTR |
| `rts` | bool | `true` | 打开后是否置 RTS |
| `eol` | str | `"\r\n"` | `send` 默认结尾；也接受 `none` / `\n` / `\r` / 自定义字面量 |
| `encoding` | str | `utf-8` | 字节解码用（errors=replace） |
| `reconnect_ms` | int | `1000` | 断线重连初始间隔 |
| `reconnect_max_ms` | int | `10000` | 重连退避上限 |
| `flush_ms` | int | `50` | 无换行的残行，超过此毫秒数也作为一行吐出 |
| `buffer_lines` | int | `20000` | 每口环形缓冲最大行数 |
| `buffer_bytes` | int | `8388608` | 每口环形缓冲最大字节数（8 MiB） |
| `autostart` | bool | `true` | 守护启动时是否立即打开 |

另有一个可选的顶层 `buffer_defaults` 段（`{lines, bytes}`）：当某口**没有**显式给出
`buffer_lines` / `buffer_bytes` 时，用这里的值兜底。

### 5.3 `ports[]`（端口列表）

每项含 `name`（唯一非空），且**要么**含固定 `device`，**要么**含自动发现 `match`；其余键与 `defaults` 同名，逐项覆盖。另有：

| 字段 | 类型 | 说明 |
|---|---|---|
| `name` | str | 逻辑口名（`list`/`open`/`read` 都用它） |
| `device` | str | 固定设备：`COMx` / `/dev/ttyUSB0` / pyserial URL（`loop://`、`socket://host:port`、`rfc2217://...`）。`device` 与 `match` 同时给出时，固定值优先 |
| `match` | dict\|null | 自动发现规格（`device` 为空时使用）。见 §5.3.1 |
| `description` | str | 可选备注（自由文本）。透传到 `list_ports`/`status`/Web UI，便于辨识设备（如 `ESP32C6`） |
| `tcp_bridge` | dict\|null | 可选：`{mode: server\|client, port: <int>, host: <str\|null>}`，守护启动时自动起桥 |

#### 5.3.1 `match`（端口自动发现）

某口可不写固定 `device`，改给一份 `match` 规格。守护在**打开时**把它解析成当前真实设备名（如 `COM12`），
并在**每次重连前重新解析**，故设备拔插后换到别的 COM 仍能被找回；解析出的 COM 会写回，因此
`list` / `status` / Web UI 都能看到。某口一个都没匹配到时，会显示 `last_error: no device matched: ...`
并持续重试。

| `match` 键 | 类型 | 语义 |
|---|---|---|
| `description` | str | 对端口描述做不区分大小写的**子串**匹配 |
| `hwid` | str | 对 `hwid` 做不区分大小写**子串**匹配 |
| `device` | str | 对设备名做不区分大小写**子串**匹配（如 `"COM"`） |
| `serial` | str | 对序列号做不区分大小写**子串**匹配 |
| `vid` | int\|str | **精确**匹配 USB 厂商号；int 或十六进制串（`0x1A86` / `"0x1A86"` / `46230`） |
| `pid` | int\|str | **精确**匹配 USB 产品号（形式同 `vid`） |
| `index` | int | 多个候选同分时取（按设备名排序）第 N 个；默认 `0` |

所有键均可选、按“与”关系组合；未知键会被拒绝。[`examples/config.yaml`](examples/config.yaml) 中的真实写法：

```yaml
ports:
  - name: c6
    match: { description: "CH343" }   # ESP32C6（CH343）
  - name: stm32
    match: { description: "CH340" }   # STM32H750（CH340）
  # 等价写法： match: { vid: 0x1A86, pid: 0x7523 }
```

要在运行时把某口改指到别的设备而不改配置，用 `set-device`（§7.1、§9.3）或
`open NAME --device COMx`；该改写是**临时的**（见 §7.1）。

### 5.4 `logging` / `ui`

| 段 | 字段 | 默认 | 说明 |
|---|---|---|---|
| `logging` | `enabled` | `false` | 是否把每口数据滚动落盘 |
| | `dir` | `logs` | 落盘目录 |
| | `max_mb` | `16` | 单文件滚动阈值 |
| | `backups` | `3` | 保留的历史文件数 |
| `ui` | `theme` | `dark` | `dark\|light`（Web UI 默认主题） |
| | `timestamp` | `true` | 默认是否显示每行时间戳 |
| | `max_render_lines` | `5000` | 前端保留的最大渲染行（虚拟窗口） |

### 5.5 `loop://` 无硬件演示配置

完整可运行版本见 [`examples/config.yaml`](examples/config.yaml)。最小示例：

```yaml
server:
  host: 127.0.0.1
  port: 8765
  token: null
  cors: true

defaults:
  baud: 115200
  eol: "\r\n"

ports:
  - name: demo
    device: loop://      # pyserial 回环：写出的字节原样读回，无需硬件
    autostart: true

ui:
  theme: dark
  timestamp: true
```

校验规则（加载即校验，非法抛 `ValueError` 且消息含字段路径如 `ports[console].data_bits`）：
`name` 唯一非空、非空 `device` **或** `match` 规格、`data_bits∈{5,6,7,8}`、`parity∈{N,E,O,M,S}`、
`stop_bits∈{1,1.5,2}`、`flow∈{none,rtscts,xonxoff,dsrdtr}`、`buffer_lines>0`、`buffer_bytes>0`。`match` 规格
只接受 §5.3.1 的键；未知键、非字符串的 `description`/`hwid`/`device`/`serial`、非法的 `vid`/`pid`、
负的 `index` 均报错。

---

## 6. Web UI 用法

打开 `http://127.0.0.1:8765/`。深色为主，右上角可切浅色。

| 区域 | 功能 |
|---|---|
| 顶栏统计 | 端口数 / open 数 / uptime |
| 连接状态 | `live` / `connecting` / `reconnecting` / `unauthorized` 状态灯 |
| token 输入框 | 服务端设了 `token` 时，在此填 Bearer token（存 localStorage） |
| 标签页 | 多口标签，每标签带**状态点**与波特率 |
| 终端 | xterm.js 渲染 **ANSI 彩色**；CDN 不可用时**降级为纯文本**（去 ANSI）并给横幅提示 |
| 每行前缀 | 时间戳（可关）+ 序号 `seq`；`tx` 前缀 `▸`、`mark` 前缀 `⚑` |
| Pause | 暂停实时渲染（新行进缓冲，Resume 后补渲） |
| Autoscroll | 自动滚到最新行开关 |
| Time | 每行时间戳开关 |
| Clear | 清空本地视图 |
| filter | 客户端正则**实时过滤**（`error\|warn`），非法正则会标红 |
| search | 回车执行本地搜索并高亮，`↑`/`↓` 在命中间跳转，显示 `命中/总数` |
| hist | 调**服务端全历史**搜索，结果可点行跳转 |
| export | 导出该口缓冲：`raw` / `noansi` / `json`（服务端写文件） |
| 发送栏 | 选目标口 + 输入 + EOL(CRLF/LF/CR/none) + Send；`↑`/`↓` 翻发送历史 |
| 端口头 | 设备名 / 波特率 / 状态；右侧 lines/s、B/s、buffer 占用百分比与迷你速率图 |

> UI 通过 `/api/*` 与 `/ws` 工作；WS 首帧推 `hello`（端口概览），随后推 `line` / `status` / `mark` 事件。

> **Language / 语言**：Web UI 提供 `EN | 中文` 切换（选择会持久化）。后端消息依据 `SERIALHUB_LANG` 环境变量，否则依据 HTTP `Accept-Language` 头。新增语言的方法见 [`docs/I18N.md`](docs/I18N.md)。

---

## 7. CLI 用法

CLI 是**瘦客户端**：除 `serve` / `mcp` 外，每个子命令打印**恰好一行 JSON**：

```json
{"ok": true, "data": { ... }}
```
```json
{"ok": false, "error": "<可读消息>"}
```

退出码：`0`=成功，`1`=失败。全局参数：`--url`（默认 `http://127.0.0.1:8765`）、`--token`（或环境变量 `SERIALHUB_TOKEN`）。

### 7.1 子命令表

| 子命令 | 参数 | 对应 REST | 说明 |
|---|---|---|---|
| `serve` | `--config F` `[--host]` `[--port]` `[--no-autostart]` `[--log-level]` | (本地) | 运行守护（不打印 JSON） |
| `list`（别名 `ports`） | — | `GET /api/ports` | 列系统串口 + 已配置端口 |
| `discover` | — | `GET /api/devices` | 枚举系统串口设备（带序号，按设备名排序） |
| `status` | `[NAME]` | `GET /api/status` | 整体或单口状态 |
| `open` | `NAME` `[--baud]` `[--device]` | `POST /api/ports/{n}/open` | 打开（可覆盖波特率/设备；`--device` 同时是一次临时 remap） |
| `set-device` | `NAME` `[--device COMx]` `[--match SPEC]` `[--no-reopen]` | `POST /api/ports/{n}/device` | 运行时改写某口用哪个设备（**临时**，见下） |
| `close` | `NAME` | `POST /api/ports/{n}/close` | 关闭（保留缓冲） |
| `read` | `NAME` `[--since-seq]` `[--since-ts]` `[--filter]` `[--limit]` `[--strip-ansi]` `[--kinds]` | `GET .../read` | 增量读缓冲行 |
| `search` | `NAME REGEX` `[--context]` `[--since-seq]` `[--limit]` | `GET .../search` | 正则搜索（可带上下文） |
| `wait` | `NAME REGEX` `[--timeout-ms]` `[--since-seq]` | `GET .../wait` | 阻塞等一条匹配（超时非错） |
| `send` | `NAME DATA` `[--eol]` `[--wait-regex]` `[--timeout-ms]` | `POST .../send` | 发数据（追加 EOL），可选等回应 |
| `snapshot` | `NAME` `[--tail-lines]` | `GET .../snapshot` | 取缓冲末尾 N 行 |
| `export` | `NAME` `[--path]` `[--format raw\|noansi\|json]` `[--range]` | `POST .../export` | 导出缓冲到文件 |
| `mark` | `NAME LABEL` | `POST .../mark` | 插入标记行 |
| `clear` | `NAME` | `POST .../clear` | 清空该口缓冲 |
| `bridge` | `{start,stop,status}` `--port NAME` `[--mode server\|client]` `[--tcp-port]` `[--host]` | `POST /api/bridge` | 起停/查看 TCP 桥 |
| `reload` | — | `POST /api/reload` | 热重载配置 |
| `mcp` | `[--stdio]` `[--transport]` | (MCP) | 运行 MCP 服务器 |

参数细节：

- `read` 游标优先 `--since-seq`，其次 `--since-ts`；都没有则按 `--limit` 取末尾。`--kinds` 逗号分隔（`rx,tx,mark`）。
- `search` 的 `regex` 与 `read` 的 `--filter` 不同名（前者定位命中、支持上下文，后者只筛选）。
- `send` 的 `DATA` 传 `-` 时从 stdin 读（去掉一个尾随换行）；`--eol` 接受 `crlf|lf|cr|none` 或转义字面量，缺省取该口 `eol`。
- `wait` / `send` 的超时单位是**毫秒**（`--timeout-ms`）。
- `set-device` 必须且只能给出 `--device` / `--match` 之一；`--match` 接受 JSON 对象（`'{"vid":0x1A86,"pid":0x7523}'`）或紧凑 `k=v` 对（`description=CH340,vid=0x1A86`）。`--no-reopen` 只改内存映射（下次 open/重连生效）；默认立即重开该口（缓冲保留）。
- **运行时 remap 是临时的**：`set-device`（以及 `open --device`）只改内存映射，**不写入配置文件**。要持久化，请改配置后 `reload`。

### 7.2 常用示例

```powershell
# 列端口 / 看状态
python -m serialhub list
python -m serialhub status
python -m serialhub status console

# 打开（覆盖波特率）与关闭
python -m serialhub open console --baud 921600
python -m serialhub close console

# 增量读取：从 0 开始，最多 50 行，仅 rx
python -m serialhub read console --since-seq 0 --limit 50 --kinds rx
# 只看含 error/warn 的行、去 ANSI
python -m serialhub read console --filter "error|warn" --strip-ansi

# 搜索带上下文
python -m serialhub search console "Bootloader" --context 2

# 阻塞等哨兵（15s）
python -m serialhub wait console "Bootloader" --timeout-ms 15000

# 发命令并等回应
python -m serialhub send console "reboot" --eol crlf --wait-regex "Bootloader" --timeout-ms 15000

# 从 stdin 发
"ls -la" | python -m serialhub send console - --eol lf

# 快照 / 导出 / 标记 / 清空
python -m serialhub snapshot console --tail-lines 100
python -m serialhub export console --format json --path out/console.jsonl
python -m serialhub mark console "before-reset"
python -m serialhub clear console

# 热重载
python -m serialhub reload
```

### 7.3 返回 envelope 示例

`python -m serialhub wait demo "hello" --timeout-ms 3000`：

```json
{"ok": true, "data": {"port": "demo", "matched": true, "line": {"seq": 7, "port": "demo", "ts_ms": 1730000000123, "text": "hello", "ansi": false, "kind": "rx"}, "seq": 7, "ts_ms": 1730000000123, "from_seq": 5}}
```

失败（例如口不存在）：

```json
{"ok": false, "error": "unknown port: 'nope'"}
```

---

## 8. TCP 桥用法

把某个口透传成 TCP：客户端写进 TCP 的字节会下发串口（并以 `kind=tx` 入缓冲），
串口收到的行会（带该口 `eol`）回写给所有 TCP 客户端。

| 模式 | 行为 | 必填 |
|---|---|---|
| `server` | 监听 `<host>:<tcp_port>`（默认 `127.0.0.1`；传 `--host 0.0.0.0` 对外），多客户端 | `--tcp-port` |
| `client` | 连出到 `host:<tcp_port>`，断线指数退避重连 | `--tcp-port` + `--host` |

```powershell
# server 模式：把 console 暴露到本机 TCP 4001
python -m serialhub bridge start --port console --mode server --tcp-port 4001
python -m serialhub bridge status --port console
#   -> {"ok":true,"data":{"port":"console","mode":"server","tcp_port":4001,"host":null,"active":true}}
python -m serialhub bridge stop --port console

# server 模式对外（跨机 nc）：绑定 0.0.0.0
python -m serialhub bridge start --port console --mode server --tcp-port 4001 --host 0.0.0.0

# client 模式：连远端串口-over-TCP 服务并透传到本口
python -m serialhub bridge start --port console --mode client --host 192.168.1.50 --tcp-port 4001
```

用 `nc`（或 `ncat`）连上后即可当串口用：

```powershell
# 本机（PowerShell 若无 nc，可用 ncat 或 Test-NetConnection 佐证端口可达）
nc 127.0.0.1 4001
# 之后输入的内容会下发串口；串口回行会显示在这里
```

> 注意：**server 模式默认只绑定回环 `127.0.0.1`**；传 `--host 0.0.0.0`（或 REST/MCP 的 `host` 字段）即可对外监听（跨机 `nc`）。
> 跨机时记得在 Windows 防火墙放行该 TCP 端口。也可在配置里用 `tcp_bridge:{mode,port,host}` 让守护启动时自动起桥（见 §5.3）。

---

## 9. MCP 用法

MCP 服务器让 agent **以工具调用**（而非 shell）操作串口。它是**瘦客户端**：每个工具都通过 HTTP
调用常驻守护，所以**必须先 `serve`**。transport 为 **stdio**（opencode / Claude Desktop / Cursor 的通用本地方式）。

> 完整的 16 工具逐项参考、agent 操作手册、错误约定与序列图见 [`docs/MCP.zh-CN.md`](docs/MCP.zh-CN.md)。

### 9.1 启动

```powershell
# 方式一：模块入口（推荐）
python -m serialhub mcp --stdio

# 方式二：直接跑脚本（注册 config 里常用的写法）
python serialhub/mcp_server.py

# 方式三：CLI 子命令
python -m serialhub mcp --transport stdio
```

### 9.2 注册到客户端

**opencode**（合并进你的配置）：

```jsonc
"mcp": {
  "serialhub": {
    "type": "local",
    "command": ["python", "D:\\projects\\project\\h750\\keshe\\serialhub\\serialhub\\mcp_server.py"],
    "enabled": true,
    "environment": { "SERIALHUB_URL": "http://127.0.0.1:8765" }
  }
}
```

等价的模块写法：`"command": ["python", "-m", "serialhub", "mcp", "--stdio"]`。

**Claude Desktop**（`claude_desktop_config.json`）：

```json
{
  "mcpServers": {
    "serialhub": {
      "command": "python",
      "args": ["D:\\projects\\project\\h750\\keshe\\serialhub\\serialhub\\mcp_server.py"],
      "env": { "SERIALHUB_URL": "http://127.0.0.1:8765" }
    }
  }
}
```

**Cursor**（`.cursor/mcp.json`）：

```json
{
  "mcpServers": {
    "serialhub": {
      "command": "python",
      "args": ["D:\\projects\\project\\h750\\keshe\\serialhub\\serialhub\\mcp_server.py"],
      "env": { "SERIALHUB_URL": "http://127.0.0.1:8765" }
    }
  }
}
```

**DSH（DeepSeek Harness）** — `~/.dsh/profiles/<profile>/cordis.patch.yml`（用户 patch 层）：

```yaml
- insert:
    - id: serialhub-mcp
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: serialhub
        transport: stdio
        command: 'E:\Anaconda3\python.exe'
        args:
          - 'D:\projects\project\h750\keshe\serialhub\serialhub\mcp_server.py'
        env:
          SERIALHUB_URL: 'http://127.0.0.1:8765'
```

DSH 自带 `@deepseek-ai/dsh-mcp-client` 插件，所以**无需改任何源码**：保存 profile patch 即热重载，
16 个工具会以 `mcp__serialhub__*` 出现在运行中的会话里。完整接入过程（含踩坑与撤销）见
[`docs/DSH.zh-CN.md`](docs/DSH.zh-CN.md)。

环境变量：`SERIALHUB_URL`（守护基址，默认 `http://127.0.0.1:8765`）、`SERIALHUB_TOKEN`（守护设了 token 时）。

### 9.3 工具速查表（16 个）

所有工具成功返回 `{"ok": true, ...}`，失败返回 `{"ok": false, "error": "..."}`。

| 工具 | 参数 | 返回关键字段 |
|---|---|---|
| `list_ports` | — | `system[]`, `ports[]` |
| `open` | `port, baud=115200, device=None` | 端口 dict（`open:true`, `buffer`, ...） |
| `close` | `port` | 端口 dict（`open:false`） |
| `status` | `port=None` | `server`+`ports[]` 或单口 |
| `read` | `port, since_seq=None, since_ts=None, filter=None, limit=None, strip_ansi=False` | `lines[]`, `next_seq`, `count`, `dropped`, `has_more` |
| `search` | `port, regex, context=0, since_seq=None, limit=None` | `hits[]`, `count`, `next_seq` |
| `wait_for` | `port, regex, timeout_ms=10000, since_seq=None` | `matched`, `line`, `seq`, `ts_ms`, `from_seq` |
| `send` | `port, data, eol="\r\n", wait_regex=None, timeout_ms=None` | `sent_bytes`, `sent`, `waited`, `matched`, `line`, `seq` |
| `snapshot` | `port, tail_lines=200` | `lines[]`, `count` |
| `export` | `port, path=None, format="raw", range=None` | `path`, `bytes`, `format`, `count` |
| `tcp_bridge` | `action, port, tcp_port=None, mode="server", host=None` | `active`, `mode`, `tcp_port` |
| `mark` | `port, label` | `seq`, `ts_ms` |
| `clear` | `port` | `cleared` |
| `reload` | — | `added`/`removed`/`restarted`/`updated` |
| `set_device` | `port, device=None, match=None, reopen=True` | 端口 dict（改后的 `device` / `open`）；临时，不落盘 |
| `discover` | — | `devices[]`（`{index, device, description, hwid, vid, pid}`） |

回环演示：

```powershell
python -m serialhub serve --config examples/config.yaml   # demo 口 device=loop://
python tools/mcp_smoke.py                                  # initialize + tools/list（无需守护）
python tools/mcp_smoke.py --full --tool-timeout 30         # 再跑 list_ports（需守护）
```

### 9.4 示例对话：用 `wait_for` 等哨兵（核心价值）

`loop://` 演示口下，agent 与守护的真实 tool-call 往返：

**Agent → `open`**
```json
{ "port": "demo" }
```
返回（节选）：
```json
{"ok":true,"name":"demo","device":"loop://","open":true,"baud":115200,"buffer":{"count":0,"first_seq":null,"last_seq":null,"dropped_total":0},"tcp_bridge":null}
```

**Agent → `mark`**
```json
{ "port": "demo", "label": "reboot-cycle" }
```
```json
{"ok":true,"port":"demo","label":"reboot-cycle","seq":41,"ts_ms":1730000000000}
```

**Agent → `send`**
```json
{ "port": "demo", "data": "reboot", "eol": "\r\n" }
```
```json
{"ok":true,"port":"demo","sent_bytes":8,"sent":"reboot","waited":false,"matched":false,"line":null,"seq":null}
```

对 `loop://`，写出的 8 字节会立刻被读回（`reboot` + CRLF）。于是下面这一步会**立即命中**：

**Agent → `wait_for`**
```json
{ "port": "demo", "regex": "reboot", "timeout_ms": 15000 }
```
```json
{"ok":true,"port":"demo","matched":true,"line":{"seq":43,"port":"demo","ts_ms":1730000000042,"text":"reboot","ansi":false,"kind":"rx"},"seq":43,"ts_ms":1730000000042,"from_seq":42}
```

拿到命中行的 `seq`（此处 `43`）后，用**游标续读**后续行，**不重复**：

**Agent → `read`**
```json
{ "port": "demo", "since_seq": 43, "limit": 100 }
```
```json
{"ok":true,"port":"demo","lines":[],"count":0,"next_seq":43,"dropped":0,"has_more":false,"first_seq":41,"last_seq":43}
```

真实设备上，`wait_for("console","Bootloader",15000)` 会**阻塞**直到固件打印启动横幅，
返回命中行的 `seq`/`ts_ms`；随后 `read(since_seq=<该 seq>)` 按序消费后续启动日志，**零重复**。
**超时不是错误**：15s 内没等到就返回 `{"ok":true,"matched":false,...}`，agent 可据此走失败分支（如 `search` 查崩溃日志、`export` 落盘）。

完整 walkthrough 见 [`examples/agent_wait_for.md`](examples/agent_wait_for.md)；
可运行代码见 [`examples/mcp_client.py`](examples/mcp_client.py)。

---

## 10. 与 Agent 集成（推荐模式）

1. **用游标做增量，不重复消费**
   每次 `read` 返回 `next_seq`，下次把它作为 `since_seq` 传入即可接着读；`wait_for` 命中的 `seq`
   也是天然游标。`dropped > 0` 表示游标早于缓冲最老行（有永久丢失，需从 `first_seq` 续）。

2. **命令回显与设备输出分离**
   本进程发出的内容以 `kind="tx"` 入缓冲，设备返回以 `kind="rx"`。`read` 可用 `kinds:["rx"]`
   （REST/CLI 的 `--kinds`）只看设备输出，避免把回显当回应。

3. **阻塞哨兵替代 sleep 轮询**
   `wait_for(port, regex, timeout_ms)` 在服务端阻塞（MCP 侧跑在工作线程，不卡事件循环），
   命中即返回；比"固定 sleep + read"更快更稳。**超时是 `matched:false` 的正常结果**。

4. **批量 send + wait**
   一次 `send(data, wait_regex=..., timeout_ms=...)` 就完成"发命令 + 等回应"，返回里直接带
   `matched` / `line` / `seq`。多步流程按顺序调用即可（每步以返回的 `seq` 作为下一步 `since_seq`）。

5. **失败取证**
   超时后用 `search(port, "HardFault|ASSERT|panic", context=2)` 定位，
   再用 `export(port, path="out/xxx.jsonl", format="json")` 落盘整段缓冲。

6. **标记分段**
   在关键动作前 `mark(port, "before-reset")`，之后用 `search` 或 `read` 快速定位阶段边界。

---

## 11. 测试与自检

```powershell
# 单元/集成测试（入口见 pytest.ini 与 pyproject.toml，测试位于 tests/；当前 73 项全部通过）
pip install -r requirements-dev.txt
python -m pytest -q

# MCP 协议自检（自写 stdio JSON-RPC 客户端，不需要守护）
python tools/mcp_smoke.py

# 端到端冒烟（需要守护在跑）：initialize + tools/list(16) + list_ports
python -m serialhub serve --config examples/config.yaml   # 另一个终端
python tools/mcp_smoke.py --full --tool-timeout 30
```

---

## 12. 验收证据

本项目在 `loop://` 上完成了一次**端到端验收（29/29 全通过）**，覆盖以下方法论（可复现）：

| 用例 | 断言要点 |
|---|---|
| `open` → `send` → `read` | 回环收到所发字节；游标续读**无重复** |
| `wait_for` 立即命中 | `matched:true` 且返回命中行 `seq`/`ts_ms` |
| `wait_for` 超时 | `matched:false` 且 `ok:true`（**非错误**） |
| `search` | 命中集合正确、`next_seq` 正确 |
| `snapshot` | 返回末尾 N 行且计数一致 |
| `mark` | 标记行入缓冲，`seq`/`ts_ms` 有效 |
| `export` | 文件真实写出，`bytes`/`count` 一致 |
| TCP 桥往返 | 经 TCP 写→串口→回写 TCP 的线上往返成功 |
| CLI `list` / `read` | 单行 JSON envelope，退出码 0 |
| MCP `initialize` + `tools/list` | 返回 **16** 个工具 |
| MCP `send` + `wait_for` | 哨兵命中（`matched:true`） |

一键复跑：

```powershell
python -m serialhub serve --config examples/config.yaml
python -m pytest -q
python -m serialhub list
python -m serialhub send demo "hello" --eol crlf
python -m serialhub wait demo "hello" --timeout-ms 3000
python tools/mcp_smoke.py --full
```

---

## 13. 常见问题

| 现象 | 根因 | 处置 |
|---|---|---|
| CLI/MCP 报 `connection failed` | 守护没起 / 换了端口 | 先 `serve`；确认 `--url` 或 `SERIALHUB_URL` 指向正确基址 |
| Web UI 一直 `reconnecting` | 守护未起，或防火墙/代理 | 看 uvicorn 是否在监听；本机用 `127.0.0.1` 直连 |
| 浏览器/远端连不上 8765 | Windows 防火墙拦截入站 | 放行 TCP 8765：`New-NetFirewallRule -DisplayName "serialhub 8765" -Direction Inbound -Protocol TCP -LocalPort 8765 -Action Allow` |
| 所有 `/api/*` 返回 401 | 服务端设了 `token` | CLI/MCP 传 `--token` / `SERIALHUB_TOKEN`；UI 顶栏填 token |
| 串口断线后没数据 | 设备拔插，worker 在退避重连 | 看 `status` 的 `last_error` / `reconnect_count`；重连后**旧缓冲保留** |
| `serve` 报端口占用 | 8765 被占用 | 改 `--port` 或配置 `server.port`；同步改 `SERIALHUB_URL` |
| `open` 报打不开设备 | 设备名错 / 被占用 | 用 `list` 看 `system[]` 的真实 `device`；确认没被别的程序占用 |
| 想无硬件试全链路 | — | 用 `device: loop://`（见 `examples/config.yaml`） |
| `send` 中文乱码 | 编码不匹配 | 配置该口 `encoding`；解析端按同编码 |
| `wait_for` 一直等到超时 | 哨兵没出现 / 正则不对 | 先用 `snapshot`/`search` 看已有输出，再调正则；超时是正常返回，不是错误 |

---

## 14. 非目标（明确不做）

- **不做固件下载 / 烧录**：本工具只做"串口数据的中枢与观测"，不解析协议、不刷固件。
- **不做业务协议解析**：行 = 文本（可含 ANSI），不内置任何设备私有帧格式解析。
- 不做鉴权体系、多用户、持久化数据库；`token` 只是单令牌门禁。

> 需要固件 OTA / 协议级能力时，请配合同生态的独立服务（如 OTA 发布服务端）使用。

---

## 15. 许可证

本项目采用 **MIT License**，详见 [LICENSE](LICENSE)。

```
Copyright (c) 2026 cjznb
```

内置/依赖的第三方组件及其许可证见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
（内置的 xterm.js 为 MIT；字体为 SIL OFL，运行时由 CDN 加载、未随仓库分发）。
