**简体中文** · [English](DSH.md)

# 把 serialhub 接入 DeepSeek Harness（DSH）

> 面向：想在 DSH（DeepSeek Harness）里直接调用 serialhub 串口工具的工程师与 agent。
>
> **结论先行：不需要修改 serialhub 或 DSH 的任何源码。** DSH 自带 `@deepseek-ai/dsh-mcp-client`
> 插件，接入 = 在 DSH profile 的**用户 patch 层**加一条 stdio MCP 服务器记录；DSH 默认开启的配置热重载
> （HMR）会让 16 个工具在**保存后立即出现**，无需重启。
>
> 适用范围：自带 `@deepseek-ai/dsh-mcp-client` 插件的 DSH 版本（桌面版与 CLI profile 通用）。

---

## 1. 背景：为什么是“加配置”而不是“改代码”

DSH 的 MCP 客户端插件 `@deepseek-ai/dsh-mcp-client` 为每台服务器读取一条配置记录（`stdio` 或
`streamable-http`），并把服务器工具注册成 `mcp__<serverName>__<rawName>` 暴露给模型。而 serialhub 的
MCP server（[`../serialhub/mcp_server.py`](../serialhub/mcp_server.py)）本来就是 **stdio + 瘦客户端**，
两边可以直接对接，不需要改动任何一方的源码：

```
DSH 模型
  │ 工具调用 mcp__serialhub__list_ports(...)
  ▼
dsh-mcp-client（DSH 插件；按配置 spawn 子进程，JSON-RPC over stdio）
  ▼
serialhub/mcp_server.py（16 个工具；每个工具转成一次 HTTP 调用）
  ▼
serialhub serve（常驻 daemon，默认 127.0.0.1:8765，持有串口 + 环形缓冲）
  ▼
COMx / /dev/ttyUSB0 / loop:// / ...
```

两条使用前提（都是 serialhub 既有设计，不是接入引入的）：

1. MCP server 不自己开串口，**必须先启动 daemon**（`serialhub serve`）；
2. daemon 基址默认 `http://127.0.0.1:8765`，可用 `SERIALHUB_URL` 覆盖。

---

## 2. 前置条件

| 项 | 要求 |
|---|---|
| Python | 3.10+，已安装 `mcp>=1.9`（MCP server 依赖）与 `pyserial`；接入配置里要指定该解释器 |
| serialhub | 本仓库源码；`mcp_server.py` 可直接以脚本运行（自带 `sys.path` 修正，无需 `pip install -e .`） |
| daemon | `serialhub serve` 已运行；MCP server 通过 `SERIALHUB_URL`（默认 `http://127.0.0.1:8765`）访问它 |
| DSH | 自带 `@deepseek-ai/dsh-mcp-client` 插件 |

> 下文的 `<path-to-serialhub>` 指本仓库根目录的绝对路径，`<profile>` 指要接入的 DSH profile 名，
> `<python>` 指已安装 `mcp` 的解释器（建议用其绝对路径）。

---

## 3. 移植步骤（逐条可复现）

### 3.1 先自检 MCP server 本身

```powershell
python tools/mcp_smoke.py
```

预期：`initialize` 返回 `serverInfo.name = serialhub`，`tools/list` 列出 **16** 个工具，最后打印
`# RESULT: PASS`。这一步**不需要 daemon**。

### 3.2 找到 DSH 要改的配置文件

- DSH 的 home 默认是 `~/.dsh`（环境变量 `DSH_HOME`），profile 目录是 `$DSH_HOME/profiles/<profile>/`；
- 要改的是**用户 patch 层** `cordis.patch.yml`；同目录的 `cordis.yml` 只是空入口列表，**不要改它**；
- 作用域更大的替代位置是 home 级 `$DSH_HOME/cordis.patch.yml`。本指南选择 profile 级；
- profile 名可用 `$env:DSH_PROFILE` 确认：桌面版固定为 `desktop`，CLI 用 `dsh <profile>` 启动时即为该名字。

### 3.3 备份

```powershell
Copy-Item "$env:DSH_HOME\profiles\<profile>\cordis.patch.yml" `
          "$env:DSH_HOME\profiles\<profile>\cordis.patch.yml.bak-$(Get-Date -Format yyyyMMdd)"
```

### 3.4 追加一条 `insert` 条目

在 `cordis.patch.yml` 末尾追加（`insert` 是 loader 的“插入列表”补丁语义）：

```yaml
# serialhub MCP —— 常驻串口中枢的 16 个工具，模型侧名称为 mcp__serialhub__*
# 前置：先启动 daemon（本 MCP server 只是 HTTP 瘦客户端）：
#   python -m serialhub serve --config config.yaml
- insert:
    - id: serialhub-mcp
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: serialhub
        transport: stdio
        command: '<python>'                                   # 装了 mcp 的解释器（绝对路径更稳妥）
        args:
          - '<path-to-serialhub>/serialhub/mcp_server.py'     # 换成实际绝对路径
        env:
          SERIALHUB_URL: 'http://127.0.0.1:8765'
```

把 `<python>` / `<path-to-serialhub>` 换成实际值即可。字段取值说明见
[§4](#4-配置字段dsh-mcp-client)。注意：如果同一文件里还有由其它工具**托管重写**的块（例如某个适配器
安装脚本维护的 managed 块），新条目要放在托管块**之外**，否则可能被覆盖。

### 3.5 生效

- DSH 的组合树默认开启 `dsh-hmr`，它监视 profile manifest、profile patch 与 home patch 文件：
  **保存即热重载，不需要重启**。
- 若部署里关闭了 HMR，改动在重启 DSH 后生效。
- 初次连接失败**不致命**：`failOnStartupError` 默认 `false`，DSH 照常启动，只是没有这批工具，并在日志里
  记录错误；修好 daemon/路径后保存一次配置即可触发重连。

---

## 4. 配置字段（dsh-mcp-client）

| 字段 | 本指南取值 | 含义 |
|---|---|---|
| `serverName` | `serialhub` | 工具命名空间；`[A-Za-z0-9_-]{1,32}`，同一注册作用域内唯一。决定公开工具名 `mcp__serialhub__<tool>` |
| `transport` | `stdio` | 本地 stdio 子进程 |
| `command` | `<python>` | 子进程可执行文件（装了 `mcp` 的解释器） |
| `args` | `<path-to-serialhub>/serialhub/mcp_server.py` | 以脚本方式启动（自带 `sys.path` 修正，无需 `pip install -e .`） |
| `env` | `SERIALHUB_URL` | 合并到**清洗后**的父环境之上；见 [§6.5](#65-dsh-会清洗子进程环境) |
| `cwd` | 不设 | 子进程工作目录；脚本方式无要求 |
| `toolCallTimeoutMs` | 默认 60000 | 单次 `tools/call` 超时；`wait_for`/`send(wait_regex)` 的 `timeout_ms` 要小于它 |
| `failOnStartupError` | 默认 false | 首次连接/工具同步失败时是否拒绝插件激活 |
| `reconnect.*` | 默认 | 断线自动重连（500ms 起指数退避，上限 30s，最多 10 次） |

等价写法：`command` 用 python、`args: ['-m', 'serialhub', 'mcp', '--stdio']`，但要求该解释器能
`import serialhub`（`pip install -e .` 或设置 `PYTHONPATH`/`cwd`）；脚本方式更省事。

---

## 5. 验证（三层）

1. **协议层**：`python tools/mcp_smoke.py` → 16 tools / `PASS`。
2. **DSH 加载层**：保存配置后，新会话（或热重载后的当前会话）工具列表出现 16 个
   `mcp__serialhub__*`；MCP 资源服务器列表也会出现 `serialhub`（本服务器不提供资源，
   `resources: []` 属正常）。
3. **业务层**：真的调一次串口工具（`<port>` 换成自己配置里的口名，`<N>` 用上次读到的 `next_seq`）：

```text
list_ports()                            → {"ok": true, "system": [...], "ports": [...]}
status()                                → {"ok": true, "server": {...}, "ports": [...]}
read(port="<port>", since_seq=<N>)      → {"ok": true, "lines": [...], "next_seq": ...}
wait_for(port="<port>", regex="<regex>", since_seq=<N>, timeout_ms=8000)
                                        → {"ok": true, "matched": true, "line": {...}, "seq": ...}
```

---

## 6. 踩坑与注意

### 6.1 `wait_for` 不带 `since_seq` 可能命中缓冲里的**旧行**

`wait_for` 的设计是“先在环形缓冲里找”，所以不传 `since_seq` 时，如果缓冲里已有匹配行，会**立刻返回
那条旧行**。**想等“新”日志必须传上次读到的 `next_seq`**：

```text
wait_for(port="<port>", regex="<regex>", since_seq=<上次的 next_seq>, timeout_ms=8000)
  → {"ok": true, "matched": true, "line": {...}, "seq": ...}   ← 新行
```

### 6.2 daemon 没起 → 工具返回 `ok:false`

`connection failed: ...` 属于“瘦客户端连不上 daemon”，先 `serialhub serve`；地址/端口变了要同步改
`SERIALHUB_URL`。

### 6.3 多 Python 环境

`command` 要写**装了 `mcp` 的那个解释器**的绝对路径；写成裸 `python` 时 DSH 用子进程环境里的 PATH
解析，可能落到别的解释器。

### 6.4 脚本方式 vs 模块方式

直接跑 `mcp_server.py` 时脚本会自动把仓库根插到 `sys.path`，无需安装；用 `-m serialhub ...` 则需要
`import serialhub` 可用。

### 6.5 DSH 会清洗子进程环境

stdio 子进程的环境以“清洗过的父环境”为基座：删除名字匹配 `KEY|PASSWORD|SECRET|TOKEN` 的变量与所有
`DSH_*` 变量，再合并配置里的 `env`（显式覆盖保留）。因此：

- `SERIALHUB_URL` 不受影响，可放心用；
- 若 daemon 设了 `server.token`，用 `SERIALHUB_TOKEN` 显式传（同样写在配置的 `env` 里）。

### 6.6 托管块不要手改

若 `cordis.patch.yml` 中存在其它工具维护的 managed 块，它会被重写；serialhub 条目应放在托管块之外。

### 6.7 工具名是稳定的

公开名固定为 `mcp__serialhub__<rawName>`，与重启/HMR 无关；会话历史与权限规则因此可复用。改了
`serverName` 等于换一套工具名，需同步更新权限规则。

---

## 7. 撤销

删除 [§3.4](#34-追加一条-insert-条目) 的 `insert` 条目（或恢复 3.3 的备份），保存后热重载：工具消失，
daemon 与串口服务不受影响。若还想停 daemon，按原方式停掉 `serialhub serve` 即可。

---

## 8. 与其它客户端注册方式对照

| 客户端 | 配置位置 | 服务器键 | 关键字段 |
|---|---|---|---|
| opencode | 配置文件 `mcp` | `mcp.serialhub` | `type: local`、`command: [...]`、`environment` |
| Claude Desktop | `claude_desktop_config.json` | `mcpServers.serialhub` | `command`、`args`、`env` |
| Cursor | `.cursor/mcp.json` | `mcpServers.serialhub` | 同上 |
| **DSH** | `~/.dsh/profiles/<profile>/cordis.patch.yml` | `insert[].id: serialhub-mcp` | `@deepseek-ai/dsh-mcp-client` 的 `serverName` / `transport: stdio` / `command` / `args` / `env` |

DSH 与前三者的差异在于：它是**插件配置树的一层 patch**，而不是独立的 `mcpServers` 文件；服务器名由
`serverName` 决定（不是配置文件的键），工具命名规则统一为 `mcp__<serverName>__<tool>`。

---

## 9. 接入检查清单

- [ ] `python tools/mcp_smoke.py` 通过，`tools/list` 返回 16 个工具
- [ ] daemon 已运行，且 `SERIALHUB_URL` 指向它
- [ ] profile patch 已保存；HMR 生效（或已重启 DSH）
- [ ] 会话工具列表出现 16 个 `mcp__serialhub__*`
- [ ] `list_ports` 返回 `ok:true`，能看到已配置端口
- [ ] `read(port, since_seq=...)` 能续读到新行，且不重复消费
- [ ] `wait_for(port, regex, since_seq=...)` 能命中**新**行
- [ ] 撤销演练：删除条目后工具消失、daemon 与串口服务不受影响

---

## 10. 参考

- [`MCP.zh-CN.md`](MCP.zh-CN.md)：16 工具参考与 agent 操作手册
- [`ARCHITECTURE.md`](ARCHITECTURE.md)：冻结契约（含 MCP / REST / CLI）
- DSH 插件 `@deepseek-ai/dsh-mcp-client` 的 README：config 字段的完整说明（随 DSH 安装包分发）
- DSH `@deepseek-ai/dsh` 的 README：profile 组合、patch 层顺序与 HMR 行为（随 DSH 安装包分发）
