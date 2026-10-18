**English** · [简体中文](DSH.zh-CN.md)

# Wiring serialhub into DeepSeek Harness (DSH)

> Audience: engineers and agents who want to use serialhub's serial-port tools from inside DSH
> (DeepSeek Harness).
>
> **Bottom line: no source changes to serialhub or DSH are needed.** DSH ships the
> `@deepseek-ai/dsh-mcp-client` plugin, so wiring up = adding one stdio MCP server record to the DSH
> profile's **user patch layer**. DSH enables config hot-reload (HMR) by default, so the 16 tools
> appear **immediately after saving** — no restart required.
>
> Verified on: 2026-10-18, Windows 11, DSH Desktop 0.2.0-rc.2, Python 3.12.3 (Anaconda), official
> mcp SDK 1.30.0.

---

## 1. Why this is “add config”, not “change code”

DSH's MCP client plugin `@deepseek-ai/dsh-mcp-client` reads one config record per server (`stdio` or
`streamable-http`) and registers the server's tools for the model as
`mcp__<serverName>__<rawName>`. serialhub's MCP server
([`../serialhub/mcp_server.py`](../serialhub/mcp_server.py)) is already a **stdio thin client**, so
the two fit together directly with no changes on either side:

```
DSH model
  │ tool call mcp__serialhub__list_ports(...)
  ▼
dsh-mcp-client (DSH plugin; spawns the child from config, JSON-RPC over stdio)
  ▼
serialhub/mcp_server.py (16 tools; each forwards to one HTTP call)
  ▼
serialhub serve (persistent daemon, 127.0.0.1:8765, holds the COM ports + ring buffers)
  ▼
COMx / loop://
```

Two preconditions (both pre-existing serialhub design, not introduced by the integration):

1. The MCP server does not open ports itself — **the daemon must be running** (`serialhub serve`);
2. The daemon base URL defaults to `http://127.0.0.1:8765` and can be overridden with `SERIALHUB_URL`.

---

## 2. Prerequisites

| Item | Requirement | Verified locally |
|---|---|---|
| Python | 3.10+ with `mcp>=1.9` and `pyserial` installed | `E:\Anaconda3\python.exe`, 3.12.3, mcp 1.30.0, pyserial 3.5 |
| serialhub | this repository's source (the script fixes `sys.path`, no install needed) | `D:\projects\project\h750\keshe\serialhub` |
| daemon | `serialhub serve` running | `127.0.0.1:8765` (had been up ~1.75 days) |
| DSH | ships `@deepseek-ai/dsh-mcp-client` | DSH Desktop 0.2.0-rc.2 (bundled) |

---

## 3. Porting steps (reproducible)

### 3.1 Self-check the MCP server first

```powershell
python tools/mcp_smoke.py
```

Expect: `initialize` returns `serverInfo.name = serialhub`, `tools/list` lists **16** tools, and the
run ends with `# RESULT: PASS`. This step does **not** need the daemon.

### 3.2 Locate the DSH config file to edit

- DSH home defaults to `~/.dsh` (`DSH_HOME`); the profile directory is `$DSH_HOME/profiles/<profile>/`;
- The desktop build uses the profile named `desktop` (the process env shows `DSH_PROFILE=desktop` and
  `DSH_PROFILE_DIR=...\profiles\desktop`);
- Edit the **user patch layer** `cordis.patch.yml`; the sibling `cordis.yml` is just an empty entry
  list — **do not edit it**;
- A wider-scoped alternative is the home-level `$DSH_HOME/cordis.patch.yml`. This guide uses the
  profile level.

### 3.3 Back up

```powershell
Copy-Item "$env:DSH_HOME\profiles\desktop\cordis.patch.yml" `
          "$env:DSH_HOME\profiles\desktop\cordis.patch.yml.bak-$(Get-Date -Format yyyyMMdd)"
```

### 3.4 Append one `insert` entry

Append to `cordis.patch.yml` (`insert` is the loader's “insert list” patch semantics):

```yaml
# serialhub MCP — the 16 tools of the persistent serial hub; model-facing names are mcp__serialhub__*
# Prerequisite: start the daemon first (this MCP server is only an HTTP thin client):
#   python -m serialhub serve --config config.yaml
- insert:
    - id: serialhub-mcp
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: serialhub
        transport: stdio
        command: 'E:\Anaconda3\python.exe'          # absolute path of the interpreter that has mcp
        args:
          - 'D:\projects\project\h750\keshe\serialhub\serialhub\mcp_server.py'
        env:
          SERIALHUB_URL: 'http://127.0.0.1:8765'
```

See [§4](#4-config-fields-dsh-mcp-client) for the field meanings. Note: if the same file contains
blocks that another tool **owns and rewrites** (e.g. an agentchat adapter's managed block written by
`install.mjs`), put the new entry **outside** such blocks, otherwise it can be overwritten.

### 3.5 Apply

- DSH's composed tree enables `dsh-hmr` by default; it watches the profile manifest, the profile patch
  and the home patch, so **saving hot-reloads — no restart**. In the measured run the current session's
  tool list went from 0 to 16 `mcp__serialhub__*` tools right after the save.
- If HMR is disabled in a deployment, the change applies after restarting DSH.
- A failed first connection is **not fatal**: `failOnStartupError` defaults to `false`, so DSH still
  starts — just without these tools — and logs the error. Fix the daemon/path and save the config once
  more to trigger a reconnect.

---

## 4. Config fields (dsh-mcp-client)

| Field | Value used here | Meaning |
|---|---|---|
| `serverName` | `serialhub` | Tool namespace; `[A-Za-z0-9_-]{1,32}`, unique in a registration scope. Determines the public tool names `mcp__serialhub__<tool>` |
| `transport` | `stdio` | local stdio child process |
| `command` | absolute python interpreter path | child executable |
| `args` | absolute `mcp_server.py` path | script form (it fixes `sys.path` itself, so `pip install -e .` is not needed) |
| `env` | `SERIALHUB_URL` | merged over the **scrubbed** parent env; see [§6.5](#65-dsh-scrubs-the-child-environment) |
| `cwd` | unset | child working directory; not needed for the script form |
| `toolCallTimeoutMs` | default 60000 | per `tools/call` timeout; keep `wait_for`/`send(wait_regex)` `timeout_ms` below it |
| `failOnStartupError` | default false | whether a failed initial connect/tool sync refuses plugin activation |
| `reconnect.*` | default | auto-reconnect (500 ms exponential backoff, 30 s cap, 10 attempts) |

Equivalent form: `command` = python, `args: ['-m', 'serialhub', 'mcp', '--stdio']`, but that requires
the interpreter to `import serialhub` (`pip install -e .` or `PYTHONPATH`/`cwd`); the script form is
simpler.

---

## 5. Verification (three layers)

1. **Protocol layer**: `python tools/mcp_smoke.py` → 16 tools / `PASS`.
2. **DSH loading layer**: after saving, a new session (or the hot-reloaded current session) lists 16
   `mcp__serialhub__*` tools; the MCP resource server list also shows `serialhub` (this server exposes
   no resources — `resources: []` is normal).
3. **Business layer**: actually call a serial tool. Excerpts from the measured run:

```text
mcp__serialhub__list_ports()
  → ok: true
    system: COM11 (CH343) / COM15 (CH340) / several Bluetooth serial ports
    ports:  c6   → COM11  open:true  rx_lines:415   buffer 415 lines
            stm32→ COM15  open:true  rx_lines:4581  buffer 7549 lines

mcp__serialhub__status()
  → server: {host: 127.0.0.1, port: 8765, version: 0.1.0, uptime_ms: 151210141}

mcp__serialhub__read(port="stm32", since_seq=8213)
  → immediately returns four new lines 8214..8217 (no double consumption)

mcp__serialhub__wait_for(port="stm32", regex="I/SENS", since_seq=8217)
  → matched:true, line.seq=8242
```

---

## 6. Pitfalls (all observed in practice)

### 6.1 `wait_for` without `since_seq` can match an **old** buffered line

`wait_for` is designed to “scan the ring buffer first”, so without `since_seq` it may return a stale
line from boot immediately (the measured run matched `seq=2`). **To wait for a *new* line, pass the
`next_seq` you last read**:

```text
wait_for(port="stm32", regex="I/SENS", since_seq=8217, timeout_ms=8000)
  → matched:true, line.seq=8242   ← a new line
```

### 6.2 Daemon not running → tools return `ok:false`

`connection failed: ...` means the thin client cannot reach the daemon — start `serialhub serve`; if
you change the address/port, update `SERIALHUB_URL` too.

### 6.3 Multiple Python environments

`command` must be the absolute path of the interpreter **that has `mcp` installed**; a bare `python`
is resolved through the child env's PATH and may land on a different interpreter.

### 6.4 Script form vs module form

Running `mcp_server.py` directly makes the script prepend the repo root to `sys.path` (no install
needed); `-m serialhub ...` requires `import serialhub` to work.

### 6.5 DSH scrubs the child environment

The stdio child env is based on the scrubbed parent env: names matching `KEY|PASSWORD|SECRET|TOKEN`
and all `DSH_*` names are dropped, then the configured `env` is merged on top (explicit overrides
survive). Therefore:

- `SERIALHUB_URL` is unaffected and safe to use;
- if the daemon sets `server.token`, pass `SERIALHUB_TOKEN` explicitly (also in the config's `env`).

### 6.6 Do not hand-edit managed blocks

If `cordis.patch.yml` contains a managed block maintained by another tool (e.g. an agentchat adapter's
`install.mjs`), it will be rewritten; keep the serialhub entry outside such blocks.

### 6.7 Tool names are stable

The public name is fixed as `mcp__serialhub__<rawName>` across restart/HMR, so session history and
permission rules stay valid. Changing `serverName` means a new set of tool names — update permission
rules accordingly.

---

## 7. Rollback

Delete the `insert` entry from [§3.4](#34-append-one-insert-entry) (or restore the 3.3 backup) and
save: hot-reload removes the tools; the daemon and serial service are unaffected. Stop
`serialhub serve` separately if you also want the daemon down.

---

## 8. Registration cheat sheet across clients

| Client | Where | Server key | Key fields |
|---|---|---|---|
| opencode | config `mcp` | `mcp.serialhub` | `type: local`, `command: [...]`, `environment` |
| Claude Desktop | `claude_desktop_config.json` | `mcpServers.serialhub` | `command`, `args`, `env` |
| Cursor | `.cursor/mcp.json` | `mcpServers.serialhub` | same as above |
| **DSH** | `~/.dsh/profiles/<profile>/cordis.patch.yml` | `insert[].id: serialhub-mcp` | `@deepseek-ai/dsh-mcp-client`'s `serverName` / `transport: stdio` / `command` / `args` / `env` |

The difference from the first three: DSH takes a **patch layer of a plugin config tree**, not a
standalone `mcpServers` file; the server name comes from `serverName` (not the config key), and tool
naming is uniformly `mcp__<serverName>__<tool>`.

---

## 9. Porting log (this machine)

Date: 2026-10-18 (Windows 11, DSH Desktop 0.2.0-rc.2, Anaconda Python 3.12.3).

1. Read `serialhub/mcp_server.py` and `serialhub/mcp_compat.py`; confirmed stdio and mcp 1.x/2.x
   compatibility; confirmed the local Anaconda has `mcp 1.30.0`, `pyserial 3.5`, `fastapi`, `uvicorn`,
   `pyyaml`, `websockets`.
2. `python tools/mcp_smoke.py` → 16 tools / `PASS`.
3. Located DSH: `DSH_HOME=~/.dsh`, `DSH_PROFILE=desktop` → edited
   `~/.dsh/profiles/desktop/cordis.patch.yml`; backed it up first.
4. Appended the `insert` entry ([§3.4](#34-append-one-insert-entry), `command` =
   `E:\Anaconda3\python.exe`, `env.SERIALHUB_URL=http://127.0.0.1:8765`).
5. HMR reloaded immediately on save: the current session showed 16 `mcp__serialhub__*` tools with
   **no restart**.
6. Business verification: `list_ports` / `status` returned real daemon data; `read(since_seq=...)`
   resumed without duplicates; `wait_for(since_seq=...)` caught a new log line.
7. **No source file of serialhub or DSH was modified**; the only changes were one user config entry
   in the DSH profile plus a backup file.

---

## 10. References

- [`MCP.md`](MCP.md): the 16-tool reference and agent playbook
- [`ARCHITECTURE.md`](ARCHITECTURE.md): the frozen contract (MCP / REST / CLI)
- The `@deepseek-ai/dsh-mcp-client` README: full config-field reference (shipped with DSH)
- The `@deepseek-ai/dsh` README: profile composition, patch-layer order and HMR behavior (shipped with DSH)
