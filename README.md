**English** · [简体中文](README.zh-CN.md)

# serialhub · Persistent Serial Hub

[![CI](https://github.com/cjznb/serialhub/actions/workflows/ci.yml/badge.svg)](https://github.com/cjznb/serialhub/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Turn one or more serial ports into a **persistent, reviewable, incrementally readable** service that's **very agent-friendly**:

- **The daemon** holds ports open and appends every line into a per-port **ring buffer** (global monotonic `seq` + epoch-ms `ts_ms`).
- **Web UI** (xterm.js) watches several ports live and lets you filter, search, export, and send.
- **REST + WebSocket** expose the whole feature set; the **CLI** and the **MCP server** share the same thin client.
- **The TCP bridge** relays a port over TCP (server listen / client dial-out).
- **MCP tools** let an agent block on a sentinel with `wait_for` and resume with a `since_seq` cursor, **without re-consuming**.

> The design contract (data model / Hub / REST / CLI / MCP, all frozen) is in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).
> The MCP-specific guide is in [`docs/MCP.md`](docs/MCP.md) (Chinese: [`docs/MCP.zh-CN.md`](docs/MCP.zh-CN.md)).

---

## 0. In one line

`python -m serialhub serve --config config.example.yaml` starts the daemon, then open `http://127.0.0.1:8765/`
in a browser; both `python -m serialhub list` on the command line and MCP `wait_for` work right away.
**You can run the entire pipeline without hardware by using `loop://`.**

---

## 1. Features at a glance

| Capability | Description |
|---|---|
| Persistent multi-port | One reader thread per port; held open and reconnected with exponential backoff on disconnect (**old buffer is kept**) |
| Auto-discovery | A port may use a `match` spec instead of a fixed `device`; resolved at **open** and **re-resolved on every reconnect**, so a replugged adapter on a new COM is still found |
| Ring buffer | Per port, evicts the oldest lines on a dual threshold of **line count + bytes**; default 20000 lines / 8 MiB |
| Global sequence | `seq` is monotonic across all ports and thread-safe; `ts_ms` is the epoch-ms receive time |
| Line kind | `kind ∈ {rx, tx, mark}`: received / sent by this process (echo) / marker |
| No double consumption | `read` supports `since_seq` / `since_ts` cursors and returns `next_seq` for resuming |
| Blocking sentinel | `wait_for` blocks until a line matches a regex; **a timeout is not an error** (`matched:false`, still `ok:true`) |
| Search | `search` runs a regex over the whole buffer, optionally with a context window |
| Export | raw / noansi / json (JSONL) to disk |
| REST + WS | Every CLI action has a matching REST endpoint; `/ws` pushes live line events |
| Web UI | Dark/light, multi-tab, ANSI color, timestamps/seq, filter/search, pause/clear, export, send bar |
| TCP bridge | server (listen; client writes go down to the serial port) / client (dial a remote and relay) |
| CLI | Every subcommand prints a **single line of JSON** `{"ok":true,"data":{...}}`, exit code 0/1 |
| MCP | 16 tools (stdio) that let an agent drive the serial port through tool calls |
| Hot reload | After editing config, `serialhub reload` applies added/removed ports, changed params, and rebuilt buffers immediately |
| No-hardware demo | `device: loop://` runs the full open→send→read→wait_for loop with no hardware |

---

## 2. Directory layout

```
serialhub/
├── README.md                 # this file (user manual)
├── docs/
│   ├── ARCHITECTURE.md        # the frozen contract (single source of truth)
│   └── MCP.md                 # MCP guide (16-tool reference + agent manual)
├── examples/
│   ├── config.yaml            # loop:// demo + a commented real port
│   ├── mcp_client.py          # a runnable programmatic client example
│   └── agent_wait_for.md      # walkthrough: an agent using wait_for on a sentinel
├── config.example.yaml        # sample config
├── requirements.txt           # runtime dependencies
├── requirements-dev.txt       # dev/test dependencies (pytest/httpx/mcp)
├── pyproject.toml             # packaging metadata (serialhub entry point / pytest config)
├── pytest.ini                 # pytest entry
├── serialhub/
│   ├── __main__.py            # python -m serialhub entry
│   ├── cli.py                 # command line (serve/list/open/read/wait/send/bridge/mcp/...)
│   ├── client.py              # HTTP thin client (stdlib, shared by CLI/MCP)
│   ├── mcp_server.py          # the 16 MCP tools (stdio)
│   ├── mcp_compat.py          # mcp 1.x/2.x compatibility shim
│   ├── server.py              # FastAPI + REST + WS + static UI
│   ├── hub.py                 # the hub (ports/buffers/broadcast/bridges/waiting)
│   ├── serialport.py          # per-port reader thread + reconnect
│   ├── ringbuffer.py          # per-port ring buffer (read/search)
│   ├── tcp_bridge.py          # TCP bridge
│   ├── exporter.py            # export formatting
│   ├── config.py              # config model / loading / validation
│   ├── discovery.py           # port auto-discovery (match spec -> real device name)
│   ├── models.py              # Line / ANSI / EOL / now_ms
│   └── static/                # Web UI (index.html + app.js + style.css)
├── tests/                     # unit/integration tests
└── tools/
    └── mcp_smoke.py           # hand-written MCP stdio smoke client
```

---

## 3. Requirements and install

| Dependency | Version | Notes |
|---|---|---|
| Python | 3.10+ (3.12 verified locally) | runtime and CLI |
| pyserial | >= 3.5 | serial ports |
| fastapi / uvicorn[standard] | >= 0.110 / >= 0.27 | HTTP + WS |
| pyyaml | >= 6.0 | config parsing |
| websockets | >= 12 | uvicorn WS |
| mcp | >= 1.9 (optional) | needed only by the MCP server |

```powershell
# 1) Runtime dependencies (required)
pip install -r requirements.txt

# 2) MCP support (optional; installs the `serialhub mcp` subcommand)
pip install "mcp>=1.9"
#   or simply: pip install -r requirements-dev.txt   # includes pytest/httpx/mcp

# 3) Install as a source package to get the `serialhub` console entry (optional but recommended)
pip install -e .
```

After installing, two equivalent entry points:

```powershell
python -m serialhub list          # always available (source on PYTHONPATH)
serialhub list                    # available after pip install -e .
```

---

## 4. Quick start

### 4.1 No-hardware demo (`loop://`)

```powershell
# Start the service with a config that has a loop:// demo port (examples/config.yaml ships one)
python -m serialhub serve --config examples/config.yaml
```

Once you see uvicorn come up:

```powershell
# List ports (you'll see the demo port open=true, device=loop://)
python -m serialhub list

# Send one line, then read it back (loop:// sends written bytes straight back)
python -m serialhub send demo "hello" --eol crlf
python -m serialhub read demo --limit 20

# Block until a reply arrives (here the loop echoes immediately, so it hits at once)
python -m serialhub wait demo "hello" --timeout-ms 3000
```

Open <http://127.0.0.1:8765/> in a browser to see the Web UI.

### 4.2 A real serial port

```powershell
python -m serialhub serve --config config.example.yaml
# Override host/port/log level on the command line:
python -m serialhub serve --config config.example.yaml --host 0.0.0.0 --port 8765 --log-level info
# Start without auto-opening any port; wait for an explicit open:
python -m serialhub serve --config config.example.yaml --no-autostart
```

---

## 5. Configuration reference

Config is **YAML or JSON** (`.yaml/.yml` uses YAML by extension, anything else uses JSON). The top-level structure follows.
Field-by-field names and defaults (consistent with `config.py` / `config.example.yaml`):

### 5.1 `server` (HTTP/WS listener and auth)

| Field | Type | Default | Notes |
|---|---|---|---|
| `host` | str | `127.0.0.1` | Listen address; `0.0.0.0` to expose |
| `port` | int | `8765` | Listen port |
| `token` | str\|null | `null` | When non-empty, `/api/*` and `/ws` require `Authorization: Bearer <token>` |
| `cors` | bool | `true` | Whether cross-origin is allowed (handy during development) |

### 5.2 `defaults` (default params for every port; each `ports[]` entry can override them)

| Field | Type | Default | Values / notes |
|---|---|---|---|
| `baud` | int | `115200` | Baud rate |
| `data_bits` | int | `8` | `5\|6\|7\|8` |
| `parity` | str | `N` | `N\|E\|O\|M\|S` (case-normalized) |
| `stop_bits` | float | `1` | `1\|1.5\|2` |
| `flow` | str | `none` | `none\|rtscts\|xonxoff\|dsrdtr` |
| `dtr` | bool | `true` | Whether to raise DTR after opening |
| `rts` | bool | `true` | Whether to raise RTS after opening |
| `eol` | str | `"\r\n"` | Default `send` terminator; also accepts `none` / `\n` / `\r` / a custom literal |
| `encoding` | str | `utf-8` | Used for byte decoding (errors=replace) |
| `reconnect_ms` | int | `1000` | Initial reconnect interval on disconnect |
| `reconnect_max_ms` | int | `10000` | Reconnect backoff ceiling |
| `flush_ms` | int | `50` | A partial line with no newline is flushed as a line after this many ms |
| `buffer_lines` | int | `20000` | Max lines per port ring buffer |
| `buffer_bytes` | int | `8388608` | Max bytes per port ring buffer (8 MiB) |
| `autostart` | bool | `true` | Whether to open immediately when the daemon starts |

There is also an optional top-level `buffer_defaults` section (`{lines, bytes}`): when a port does
**not** explicitly set `buffer_lines` / `buffer_bytes`, these values are used as the fallback.

### 5.3 `ports[]` (the port list)

Each entry has `name` (unique, non-empty) plus **either** `device` (fixed) **or** `match` (auto-discovery);
the remaining keys share names with `defaults` and override them per entry. Additional keys:

| Field | Type | Notes |
|---|---|---|
| `name` | str | Logical port name (used by `list`/`open`/`read`) |
| `device` | str | Fixed device: `COMx` / `/dev/ttyUSB0` / pyserial URL (`loop://`, `socket://host:port`, `rfc2217://...`). If both `device` and `match` are given, `device` wins |
| `match` | dict\|null | Auto-discovery spec (used when `device` is empty). See §5.3.1 |
| `description` | str | Optional free-text note. Passed through to `list_ports`/`status`/Web UI to identify the device (e.g. `ESP32C6`) |
| `tcp_bridge` | dict\|null | Optional: `{mode: server\|client, port: <int>, host: <str\|null>}`; the daemon starts the bridge automatically at boot |

#### 5.3.1 `match` (port auto-discovery)

Instead of a fixed `device`, a port can carry a `match` spec. The daemon resolves it to the current real
device name (e.g. `COM12`) at **open** and **re-resolves on every reconnect**, so a replugged adapter that
comes back on a different COM is still found; the resolved COM is written back, so `list` / `status` / Web UI
show it. A port that matches nothing shows `last_error: no device matched: ...` and keeps retrying.

| `match` key | Type | Semantics |
|---|---|---|
| `description` | str | Case-insensitive **substring** against the port description |
| `hwid` | str | Case-insensitive **substring** against `hwid` |
| `device` | str | Case-insensitive **substring** against the device name (e.g. `"COM"`) |
| `serial` | str | Case-insensitive **substring** against the serial number |
| `vid` | int\|str | **Exact** USB vendor id; accepts int or hex string (`0x1A86` / `"0x1A86"` / `46230`) |
| `pid` | int\|str | **Exact** USB product id (same forms as `vid`) |
| `index` | int | When several ports match equally, pick the Nth (after sorting by device name); default `0` |

All keys are optional and combined with AND; unknown keys are rejected. The real pattern from
[`examples/config.yaml`](examples/config.yaml):

```yaml
ports:
  - name: c6
    match: { description: "CH343" }   # ESP32C6 (CH343)
  - name: stm32
    match: { description: "CH340" }   # STM32H750 (CH340)
  # equivalent: match: { vid: 0x1A86, pid: 0x7523 }
```

To repoint a port at runtime without editing the config, use `set-device` (§7.1, §9.3) or
`open NAME --device COMx`; that remap is **transient** (see §7.1).

### 5.4 `logging` / `ui`

| Section | Field | Default | Notes |
|---|---|---|---|
| `logging` | `enabled` | `false` | Whether to roll per-port data to disk |
| | `dir` | `logs` | Output directory |
| | `max_mb` | `16` | Single-file rotation threshold |
| | `backups` | `3` | Number of historical files to keep |
| `ui` | `theme` | `dark` | `dark\|light` (Web UI default theme) |
| | `timestamp` | `true` | Whether to show a per-line timestamp by default |
| | `max_render_lines` | `5000` | Max rendered lines kept in the front end (virtual window) |

### 5.5 `loop://` no-hardware demo config

The full runnable version is in [`examples/config.yaml`](examples/config.yaml). Minimal example:

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
    device: loop://      # pyserial loopback: written bytes are read straight back, no hardware
    autostart: true

ui:
  theme: dark
  timestamp: true
```

Validation rules (validated on load; an invalid config raises `ValueError` with a message that includes
the field path, such as `ports[console].data_bits`):
`name` unique and non-empty, a non-empty `device` **or** a `match` spec, `data_bits∈{5,6,7,8}`, `parity∈{N,E,O,M,S}`,
`stop_bits∈{1,1.5,2}`, `flow∈{none,rtscts,xonxoff,dsrdtr}`, `buffer_lines>0`, `buffer_bytes>0`. A `match` spec
accepts only the keys in §5.3.1; unknown keys, a non-string `description`/`hwid`/`device`/`serial`, an invalid
`vid`/`pid`, and a negative `index` all raise.

---

## 6. Web UI

Open `http://127.0.0.1:8765/`. Dark by default, with a light toggle in the top-right corner.

| Area | Function |
|---|---|
| Top-bar stats | Port count / open count / uptime |
| Connection status | `live` / `connecting` / `reconnecting` / `unauthorized` status light |
| token field | When the server sets a `token`, enter the Bearer token here (stored in localStorage) |
| Tabs | One tab per port, each with a **status dot** and baud rate |
| Terminal | xterm.js renders **ANSI color**; when the CDN is unavailable it **degrades to plain text** (ANSI stripped) with a banner notice |
| Per-line prefix | Timestamp (toggleable) + sequence `seq`; `tx` prefix `▸`, `mark` prefix `⚑` |
| Pause | Pause live rendering (new lines still buffer; Resume catches up) |
| Autoscroll | Toggle auto-scroll to the newest line |
| Time | Toggle the per-line timestamp |
| Clear | Clear the local view |
| filter | Client-side regex **live filter** (`error\|warn`); an invalid regex is highlighted red |
| search | Press Enter to run a local search and highlight hits; `↑`/`↓` jump between hits; shows `hits/total` |
| hist | Search the **full server history**; results are clickable to jump to the line |
| export | Export this port's buffer: `raw` / `noansi` / `json` (the server writes the file) |
| Send bar | Pick target port + input + EOL (CRLF/LF/CR/none) + Send; `↑`/`↓` cycle send history |
| Port header | Device name / baud / status; on the right, lines/s, B/s, buffer-fill percentage, and a mini rate chart |

> The UI works over `/api/*` and `/ws`; the first WS frame pushes `hello` (port overview), then it pushes `line` / `status` / `mark` events.

> **Language / 语言**: the Web UI has an `EN | 中文` switcher (your choice is persisted). Backend messages follow the `SERIALHUB_LANG` environment variable, else the HTTP `Accept-Language` header. To add a language, see [`docs/I18N.md`](docs/I18N.md).

---

## 7. CLI usage

The CLI is a **thin client**: except for `serve` / `mcp`, every subcommand prints **exactly one line of JSON**:

```json
{"ok": true, "data": { ... }}
```
```json
{"ok": false, "error": "<readable message>"}
```

Exit codes: `0`=success, `1`=failure. Global options: `--url` (default `http://127.0.0.1:8765`), `--token` (or the `SERIALHUB_TOKEN` environment variable).

### 7.1 Subcommand table

| Subcommand | Args | Matching REST | Notes |
|---|---|---|---|
| `serve` | `--config F` `[--host]` `[--port]` `[--no-autostart]` `[--log-level]` | (local) | Run the daemon (prints no JSON) |
| `list` (alias `ports`) | - | `GET /api/ports` | List system serial ports + configured ports |
| `discover` | - | `GET /api/devices` | Enumerate system serial devices (indexed, sorted by device name) |
| `status` | `[NAME]` | `GET /api/status` | Overall or single-port status |
| `open` | `NAME` `[--baud]` `[--device]` | `POST /api/ports/{n}/open` | Open (optionally override baud/device; `--device` also performs a transient remap) |
| `set-device` | `NAME` `[--device COMx]` `[--match SPEC]` `[--no-reopen]` | `POST /api/ports/{n}/device` | Remap which device a port uses at runtime (**transient**, see below) |
| `close` | `NAME` | `POST /api/ports/{n}/close` | Close (buffer kept) |
| `read` | `NAME` `[--since-seq]` `[--since-ts]` `[--filter]` `[--limit]` `[--strip-ansi]` `[--kinds]` | `GET .../read` | Incrementally read buffered lines |
| `search` | `NAME REGEX` `[--context]` `[--since-seq]` `[--limit]` | `GET .../search` | Regex search (optionally with context) |
| `wait` | `NAME REGEX` `[--timeout-ms]` `[--since-seq]` | `GET .../wait` | Block until one line matches (timeout is not an error) |
| `send` | `NAME DATA` `[--eol]` `[--wait-regex]` `[--timeout-ms]` | `POST .../send` | Send data (EOL appended), optionally wait for a reply |
| `snapshot` | `NAME` `[--tail-lines]` | `GET .../snapshot` | Fetch the last N buffered lines |
| `export` | `NAME` `[--path]` `[--format raw\|noansi\|json]` `[--range]` | `POST .../export` | Export the buffer to a file |
| `mark` | `NAME LABEL` | `POST .../mark` | Insert a marker line |
| `clear` | `NAME` | `POST .../clear` | Clear that port's buffer |
| `bridge` | `{start,stop,status}` `--port NAME` `[--mode server\|client]` `[--tcp-port]` `[--host]` | `POST /api/bridge` | Start/stop/inspect the TCP bridge |
| `reload` | - | `POST /api/reload` | Hot-reload the config |
| `mcp` | `[--stdio]` `[--transport]` | (MCP) | Run the MCP server |

Argument details:

- `read` prefers the `--since-seq` cursor, then `--since-ts`; if neither is given it takes the tail by `--limit`. `--kinds` is comma-separated (`rx,tx,mark`).
- `search`'s `regex` and `read`'s `--filter` are different names (the former locates hits and supports context; the latter only filters).
- `send`'s `DATA` reads from stdin when passed `-` (one trailing newline is stripped); `--eol` accepts `crlf|lf|cr|none` or an escaped literal, defaulting to that port's `eol`.
- The timeout unit for `wait` / `send` is **milliseconds** (`--timeout-ms`).
- `set-device` requires **exactly one** of `--device` / `--match`; `--match` takes a JSON object (`'{"vid":0x1A86,"pid":0x7523}'`) or compact pairs (`description=CH340,vid=0x1A86`). `--no-reopen` changes only the in-memory mapping (applied on the next open/reconnect); the default reopens the port now (buffer kept).
- **Runtime remap is transient**: `set-device` (and `open --device`) only change the in-memory mapping; nothing is written to the config file. To persist, edit the config and run `reload`.

### 7.2 Common examples

```powershell
# List ports / check status
python -m serialhub list
python -m serialhub status
python -m serialhub status console

# Open (override baud) and close
python -m serialhub open console --baud 921600
python -m serialhub close console

# Incremental read: from 0, at most 50 lines, rx only
python -m serialhub read console --since-seq 0 --limit 50 --kinds rx
# Only lines containing error/warn, ANSI stripped
python -m serialhub read console --filter "error|warn" --strip-ansi

# Search with context
python -m serialhub search console "Bootloader" --context 2

# Block on a sentinel (15s)
python -m serialhub wait console "Bootloader" --timeout-ms 15000

# Send a command and wait for the reply
python -m serialhub send console "reboot" --eol crlf --wait-regex "Bootloader" --timeout-ms 15000

# Send from stdin
"ls -la" | python -m serialhub send console - --eol lf

# Snapshot / export / mark / clear
python -m serialhub snapshot console --tail-lines 100
python -m serialhub export console --format json --path out/console.jsonl
python -m serialhub mark console "before-reset"
python -m serialhub clear console

# Hot reload
python -m serialhub reload
```

### 7.3 Return envelope example

`python -m serialhub wait demo "hello" --timeout-ms 3000`:

```json
{"ok": true, "data": {"port": "demo", "matched": true, "line": {"seq": 7, "port": "demo", "ts_ms": 1730000000123, "text": "hello", "ansi": false, "kind": "rx"}, "seq": 7, "ts_ms": 1730000000123, "from_seq": 5}}
```

On failure (for example, a port that doesn't exist):

```json
{"ok": false, "error": "unknown port: 'nope'"}
```

---

## 8. TCP bridge usage

Relay a port over TCP: bytes a client writes to TCP are sent down to the serial port (and buffered with
`kind=tx`), while lines the serial port receives are written back to every TCP client (with that port's `eol`).

| Mode | Behavior | Required |
|---|---|---|
| `server` | Listen on `<host>:<tcp_port>` (default `127.0.0.1`; pass `--host 0.0.0.0` to expose), multi-client | `--tcp-port` |
| `client` | Dial out to `host:<tcp_port>`, reconnecting with exponential backoff on disconnect | `--tcp-port` + `--host` |

```powershell
# server mode: expose console on local TCP 4001
python -m serialhub bridge start --port console --mode server --tcp-port 4001
python -m serialhub bridge status --port console
#   -> {"ok":true,"data":{"port":"console","mode":"server","tcp_port":4001,"host":null,"active":true}}
python -m serialhub bridge stop --port console

# server mode, exposed (cross-machine nc): bind 0.0.0.0
python -m serialhub bridge start --port console --mode server --tcp-port 4001 --host 0.0.0.0

# client mode: connect a remote serial-over-TCP service and relay it to this port
python -m serialhub bridge start --port console --mode client --host 192.168.1.50 --tcp-port 4001
```

Connect with `nc` (or `ncat`) and use it like a serial port:

```powershell
# Local (if PowerShell has no nc, use ncat or Test-NetConnection to confirm reachability)
nc 127.0.0.1 4001
# Anything you type now goes down to the serial port; lines coming back show up here
```

> Note: **server mode binds only to loopback `127.0.0.1` by default**; pass `--host 0.0.0.0` (or the REST/MCP `host` field)
> to listen externally (cross-machine `nc`).
> For cross-machine access, remember to allow that TCP port in the Windows firewall. You can also use `tcp_bridge:{mode,port,host}`
> in the config to have the daemon start the bridge at boot (see §5.3).

---

## 9. MCP usage

The MCP server lets an agent drive serial ports **through tool calls** (rather than a shell). It is a **thin client**:
every tool calls the persistent daemon over HTTP, so you **must `serve` first**. The transport is **stdio**
(the common local approach for opencode / Claude Desktop / Cursor).

> The complete 16-tool reference, agent playbook, error conventions, and sequence diagram are in [`docs/MCP.md`](docs/MCP.md).

### 9.1 Launch

```powershell
# Option 1: module entry (recommended)
python -m serialhub mcp --stdio

# Option 2: run the script directly (the form commonly used in registered configs)
python serialhub/mcp_server.py

# Option 3: CLI subcommand
python -m serialhub mcp --transport stdio
```

### 9.2 Register with a client

**opencode** (merge into your config):

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

The equivalent module form: `"command": ["python", "-m", "serialhub", "mcp", "--stdio"]`.

**Claude Desktop** (`claude_desktop_config.json`):

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

**Cursor** (`.cursor/mcp.json`):

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

Environment variables: `SERIALHUB_URL` (daemon base, default `http://127.0.0.1:8765`), `SERIALHUB_TOKEN` (when the daemon sets a token).

### 9.3 Tool cheat sheet (16)

Every tool returns `{"ok": true, ...}` on success and `{"ok": false, "error": "..."}` on failure.

| Tool | Args | Key return fields |
|---|---|---|
| `list_ports` | - | `system[]`, `ports[]` |
| `open` | `port, baud=115200, device=None` | port dict (`open:true`, `buffer`, ...) |
| `close` | `port` | port dict (`open:false`) |
| `status` | `port=None` | `server`+`ports[]` or a single port |
| `read` | `port, since_seq=None, since_ts=None, filter=None, limit=None, strip_ansi=False` | `lines[]`, `next_seq`, `count`, `dropped`, `has_more` |
| `search` | `port, regex, context=0, since_seq=None, limit=None` | `hits[]`, `count`, `next_seq` |
| `wait_for` | `port, regex, timeout_ms=10000, since_seq=None` | `matched`, `line`, `seq`, `ts_ms`, `from_seq` |
| `send` | `port, data, eol="\r\n", wait_regex=None, timeout_ms=None` | `sent_bytes`, `sent`, `waited`, `matched`, `line`, `seq` |
| `snapshot` | `port, tail_lines=200` | `lines[]`, `count` |
| `export` | `port, path=None, format="raw", range=None` | `path`, `bytes`, `format`, `count` |
| `tcp_bridge` | `action, port, tcp_port=None, mode="server", host=None` | `active`, `mode`, `tcp_port` |
| `mark` | `port, label` | `seq`, `ts_ms` |
| `clear` | `port` | `cleared` |
| `reload` | - | `added`/`removed`/`restarted`/`updated` |
| `set_device` | `port, device=None, match=None, reopen=True` | port dict (remapped `device` / `open`); transient, not persisted |
| `discover` | - | `devices[]` (`{index, device, description, hwid, vid, pid}`) |

Loopback demo:

```powershell
python -m serialhub serve --config examples/config.yaml   # demo port device=loop://
python tools/mcp_smoke.py                                  # initialize + tools/list (no daemon needed)
python tools/mcp_smoke.py --full --tool-timeout 30         # then run list_ports (needs the daemon)
```

### 9.4 Example dialogue: waiting on a sentinel with `wait_for` (the core value)

With the `loop://` demo port, a real tool-call round trip between an agent and the daemon:

**Agent → `open`**
```json
{ "port": "demo" }
```
Returns (excerpt):
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

For `loop://`, the 8 written bytes are read straight back (`reboot` + CRLF). So the next step **hits immediately**:

**Agent → `wait_for`**
```json
{ "port": "demo", "regex": "reboot", "timeout_ms": 15000 }
```
```json
{"ok":true,"port":"demo","matched":true,"line":{"seq":43,"port":"demo","ts_ms":1730000000042,"text":"reboot","ansi":false,"kind":"rx"},"seq":43,"ts_ms":1730000000042,"from_seq":42}
```

Once you have the hit line's `seq` (here `43`), use the **cursor to resume** subsequent lines **without duplicates**:

**Agent → `read`**
```json
{ "port": "demo", "since_seq": 43, "limit": 100 }
```
```json
{"ok":true,"port":"demo","lines":[],"count":0,"next_seq":43,"dropped":0,"has_more":false,"first_seq":41,"last_seq":43}
```

On a real device, `wait_for("console","Bootloader",15000)` **blocks** until the firmware prints the boot
banner, returning the hit line's `seq`/`ts_ms`; then `read(since_seq=<that seq>)` consumes subsequent boot
logs in order, with **zero duplicates**.
**A timeout is not an error**: if nothing arrives within 15s it returns `{"ok":true,"matched":false,...}`, and
the agent can branch on that (e.g. `search` for a crash log, `export` to disk).

See [`examples/agent_wait_for.md`](examples/agent_wait_for.md) for the full walkthrough;
see [`examples/mcp_client.py`](examples/mcp_client.py) for runnable code.

---

## 10. Integrating with an agent (recommended patterns)

1. **Use a cursor to read incrementally, without re-consuming**
   Every `read` returns `next_seq`; pass it back as `since_seq` next time to continue; the `seq` a `wait_for`
   hit returns is a natural cursor too. `dropped > 0` means the cursor predates the oldest buffered line (there is
   permanent loss; resume from `first_seq`).

2. **Separate command echo from device output**
   Content this process sends is buffered with `kind="tx"`, device replies with `kind="rx"`. `read` can use
   `kinds:["rx"]` (the REST/CLI `--kinds`) to see only device output, avoiding mistaking an echo for a reply.

3. **Block on a sentinel instead of sleep-polling**
   `wait_for(port, regex, timeout_ms)` blocks server-side (on the MCP side it runs on a worker thread and doesn't
   stall the event loop) and returns as soon as it hits; it's faster and more stable than "fixed sleep + read".
   **A timeout is a normal result, `matched:false`.**

4. **Batch send + wait**
   A single `send(data, wait_regex=..., timeout_ms=...)` does "send command + wait for reply" and returns
   `matched` / `line` / `seq` directly. Chain multi-step flows in order (each step uses the returned `seq` as the
   next step's `since_seq`).

5. **Post-failure forensics**
   After a timeout, locate with `search(port, "HardFault|ASSERT|panic", context=2)`, then dump the whole buffer
   with `export(port, path="out/xxx.jsonl", format="json")`.

6. **Segment with markers**
   Before a key action, `mark(port, "before-reset")`; afterward use `search` or `read` to quickly find phase boundaries.

---

## 11. Tests and self-checks

```powershell
# Unit/integration tests (entries in pytest.ini and pyproject.toml; tests live in tests/; currently 73 pass)
pip install -r requirements-dev.txt
python -m pytest -q

# MCP protocol self-check (hand-written stdio JSON-RPC client, no daemon needed)
python tools/mcp_smoke.py

# End-to-end smoke (needs the daemon running): initialize + tools/list(16) + list_ports
python -m serialhub serve --config examples/config.yaml   # in another terminal
python tools/mcp_smoke.py --full --tool-timeout 30
```

---

## 12. Acceptance evidence

This project completed an **end-to-end acceptance run (29/29 passing)** over `loop://`, covering the
following methodology (reproducible):

| Case | Assertion |
|---|---|
| `open` → `send` → `read` | The loopback receives the sent bytes; cursor resume has **no duplicates** |
| `wait_for` immediate hit | `matched:true` and returns the hit line's `seq`/`ts_ms` |
| `wait_for` timeout | `matched:false` and `ok:true` (**not an error**) |
| `search` | Hit set correct, `next_seq` correct |
| `snapshot` | Returns the last N lines with a matching count |
| `mark` | Marker line buffered, `seq`/`ts_ms` valid |
| `export` | File truly written, `bytes`/`count` match |
| TCP bridge round trip | A wire round trip TCP write → serial → TCP write-back succeeds |
| CLI `list` / `read` | Single-line JSON envelope, exit code 0 |
| MCP `initialize` + `tools/list` | Returns **16** tools |
| MCP `send` + `wait_for` | Sentinel hit (`matched:true`) |

Rerun with one command:

```powershell
python -m serialhub serve --config examples/config.yaml
python -m pytest -q
python -m serialhub list
python -m serialhub send demo "hello" --eol crlf
python -m serialhub wait demo "hello" --timeout-ms 3000
python tools/mcp_smoke.py --full
```

---

## 13. FAQ

| Symptom | Root cause | Fix |
|---|---|---|
| CLI/MCP reports `connection failed` | Daemon not started / wrong port | `serve` first; confirm `--url` or `SERIALHUB_URL` points at the right base |
| Web UI stuck on `reconnecting` | Daemon not running, or firewall/proxy | Check whether uvicorn is listening; on the local machine, connect via `127.0.0.1` directly |
| Browser/remote can't reach 8765 | Windows firewall blocking inbound | Allow TCP 8765: `New-NetFirewallRule -DisplayName "serialhub 8765" -Direction Inbound -Protocol TCP -LocalPort 8765 -Action Allow` |
| All `/api/*` return 401 | The server sets a `token` | Pass `--token` / `SERIALHUB_TOKEN` to CLI/MCP; enter the token in the UI top bar |
| No data after a serial disconnect | Device unplugged/replugged, worker is backoff-reconnecting | Check `status`'s `last_error` / `reconnect_count`; after reconnect the **old buffer is kept** |
| `serve` reports the port is in use | 8765 is occupied | Change `--port` or `server.port` in the config; update `SERIALHUB_URL` to match |
| `open` reports the device can't be opened | Wrong device name / already in use | Use `list` to see the real `device` in `system[]`; confirm no other program holds it |
| Want to try the full pipeline without hardware | - | Use `device: loop://` (see `examples/config.yaml`) |
| `send` shows garbled CJK | Encoding mismatch | Set that port's `encoding`; have the parsing side use the same encoding |
| `wait_for` keeps waiting until timeout | The sentinel never appeared / wrong regex | Use `snapshot`/`search` first to see existing output, then adjust the regex; a timeout is a normal return, not an error |

---

## 14. Non-goals (explicitly out of scope)

- **No firmware download / flashing**: this tool is only "a hub and observer for serial data"; it does not parse protocols or flash firmware.
- **No business-protocol parsing**: a line = text (may contain ANSI); no device-private frame format parsing is built in.
- No auth system, multi-user, or persistent database; `token` is only a single-token gate.

> When you need firmware OTA / protocol-level capabilities, pair it with a companion independent service (such as an OTA release server).

---

## 15. License

This project is under the **MIT License**; see [LICENSE](LICENSE).

```
Copyright (c) 2026 cjznb
```

See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for bundled/dependency third-party components and their
licenses (the bundled xterm.js is MIT; fonts are SIL OFL, loaded from a CDN at runtime and not distributed with the repo).
