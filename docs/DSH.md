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
> Applies to DSH builds that ship the `@deepseek-ai/dsh-mcp-client` plugin (desktop and CLI profiles alike).

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
serialhub serve (persistent daemon, default 127.0.0.1:8765, holds the ports + ring buffers)
  ▼
COMx / /dev/ttyUSB0 / loop:// / ...
```

Two preconditions (both pre-existing serialhub design, not introduced by the integration):

1. The MCP server does not open ports itself — **the daemon must be running** (`serialhub serve`);
2. The daemon base URL defaults to `http://127.0.0.1:8765` and can be overridden with `SERIALHUB_URL`.

---

## 2. Prerequisites

| Item | Requirement |
|---|---|
| Python | 3.10+ with `mcp>=1.9` (MCP server dependency) and `pyserial` installed; the integration config points at this interpreter |
| serialhub | this repository's source; `mcp_server.py` runs directly as a script (it fixes `sys.path`, so `pip install -e .` is not needed) |
| daemon | `serialhub serve` running; the MCP server reaches it through `SERIALHUB_URL` (default `http://127.0.0.1:8765`) |
| DSH | ships the `@deepseek-ai/dsh-mcp-client` plugin |

> Below, `<path-to-serialhub>` is the absolute path of this repository root, `<profile>` is the DSH
> profile to wire up, and `<python>` is the interpreter that has `mcp` installed (its absolute path is
> recommended).

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
- Edit the **user patch layer** `cordis.patch.yml`; the sibling `cordis.yml` is just an empty entry
  list — **do not edit it**;
- A wider-scoped alternative is the home-level `$DSH_HOME/cordis.patch.yml`. This guide uses the
  profile level;
- The profile name is visible in `$env:DSH_PROFILE`: the desktop build uses `desktop`, and a CLI
  `dsh <profile>` launch uses that same name.

### 3.3 Back up

```powershell
Copy-Item "$env:DSH_HOME\profiles\<profile>\cordis.patch.yml" `
          "$env:DSH_HOME\profiles\<profile>\cordis.patch.yml.bak-$(Get-Date -Format yyyyMMdd)"
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
        command: '<python>'                                   # interpreter that has mcp (absolute path is safer)
        args:
          - '<path-to-serialhub>/serialhub/mcp_server.py'     # replace with the real absolute path
        env:
          SERIALHUB_URL: 'http://127.0.0.1:8765'
```

Replace `<python>` / `<path-to-serialhub>` with real values. See
[§4](#4-config-fields-dsh-mcp-client) for the field meanings. Note: if the same file contains blocks
that another tool **owns and rewrites** (e.g. a managed block written by an adapter installer), put the
new entry **outside** such blocks, otherwise it can be overwritten.

### 3.5 Apply

- DSH's composed tree enables `dsh-hmr` by default; it watches the profile manifest, the profile patch
  and the home patch, so **saving hot-reloads — no restart**.
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
| `command` | `<python>` | child executable (the interpreter that has `mcp`) |
| `args` | `<path-to-serialhub>/serialhub/mcp_server.py` | script form (it fixes `sys.path` itself, so `pip install -e .` is not needed) |
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
3. **Business layer**: actually call a serial tool (`<port>` is a port name from your own config,
   `<N>` is the `next_seq` you last read):

```text
list_ports()                            → {"ok": true, "system": [...], "ports": [...]}
status()                                → {"ok": true, "server": {...}, "ports": [...]}
read(port="<port>", since_seq=<N>)      → {"ok": true, "lines": [...], "next_seq": ...}
wait_for(port="<port>", regex="<regex>", since_seq=<N>, timeout_ms=8000)
                                        → {"ok": true, "matched": true, "line": {...}, "seq": ...}
```

---

## 6. Pitfalls

### 6.1 `wait_for` without `since_seq` can match an **old** buffered line

`wait_for` is designed to “scan the ring buffer first”, so without `since_seq` it returns immediately
if a matching line is already buffered — possibly a stale one. **To wait for a *new* line, pass the
`next_seq` you last read**:

```text
wait_for(port="<port>", regex="<regex>", since_seq=<last next_seq>, timeout_ms=8000)
  → {"ok": true, "matched": true, "line": {...}, "seq": ...}   ← a new line
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

If `cordis.patch.yml` contains a managed block maintained by another tool, it will be rewritten; keep
the serialhub entry outside such blocks.

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

## 9. Integration checklist

- [ ] `python tools/mcp_smoke.py` passes; `tools/list` returns 16 tools
- [ ] the daemon is running and `SERIALHUB_URL` points at it
- [ ] the profile patch is saved; HMR took effect (or DSH was restarted)
- [ ] the session lists 16 `mcp__serialhub__*` tools
- [ ] `list_ports` returns `ok:true` and shows the configured ports
- [ ] `read(port, since_seq=...)` resumes at new lines without duplicate consumption
- [ ] `wait_for(port, regex, since_seq=...)` catches a **new** line
- [ ] rollback drill: removing the entry removes the tools; the daemon and serial service are unaffected

---

## 10. References

- [`MCP.md`](MCP.md): the 16-tool reference and agent playbook
- [`ARCHITECTURE.md`](ARCHITECTURE.md): the frozen contract (MCP / REST / CLI)
- The `@deepseek-ai/dsh-mcp-client` README: full config-field reference (shipped with DSH)
- The `@deepseek-ai/dsh` README: profile composition, patch-layer order and HMR behavior (shipped with DSH)
