# 一个 AI Agent 如何用 serialhub：免烧录启动自检

本文是一份**面向 agent 的操作 walkthrough**：目标是在**不碰固件、不额外写脚本**的前提下，
用 serialhub 的 MCP 工具完成一次「重启并确认引导器起来」的检查（boot check）。

工具名与参数即 MCP 工具签名；每个 `tools/call` 的返回值是该工具的**结构化 JSON 结果**
（成功 `{"ok": true, ...}`，失败 `{"ok": false, "error": "..."}`）。下文 JSON 为代表性示例。

> 前置：守护已在跑（`python -m serialhub serve --config examples/config.yaml`），
> MCP 已注册（见 [`../docs/MCP.md`](../docs/MCP.md) §3）。
> 把示例里的 `console` / `COM11` 换成你的真实口名 / 设备。

---

## 场景

- 目标口：`console`（STM32 控制台，`device=COM11`，`baud=921600`）。
- 期望：发 `reboot` 后，固件打印含 `Bootloader` 的启动横幅。
- 策略：**用 `wait_for` 阻塞等哨兵**，而不是 sleep + 轮询；命中后**用命中行的 `seq` 做游标续读**。

---

## 步骤 1：`list_ports`（找口、记初始游标）

```json
{}
```
```json
{"ok":true,
 "system":[{"device":"COM11","description":"USB-SERIAL CH340","hwid":"USB VID:PID=1A86:7523"}],
 "ports":[{"name":"console","device":"COM11","open":false,"baud":921600,
           "buffer":{"count":0,"bytes":0,"first_seq":null,"last_seq":null,"dropped_total":0},
           "tcp_bridge":null}]}
```

记下：口名 `console`，当前缓冲为空（`last_seq=null`）。

---

## 步骤 2：`open`（打开口）

```json
{ "port": "console" }
```
```json
{"ok":true,"name":"console","device":"COM11","open":true,"baud":921600,
 "buffer":{"count":0,"bytes":0,"first_seq":null,"last_seq":null,"dropped_total":0},
 "tcp_bridge":null}
```

---

## 步骤 3：`mark`（给本轮打标记，便于后续定位）

```json
{ "port": "console", "label": "boot-check" }
```
```json
{"ok":true,"port":"console","label":"boot-check","seq":41,"ts_ms":1730000000000}
```

此刻标记行已入缓冲（`kind:"mark"`）。它既是时间锚点，也给了当前 `seq=41`。

---

## 步骤 4：`send`（下发重启命令，不等待）

```json
{ "port": "console", "data": "reboot", "eol": "\r\n" }
```
```json
{"ok":true,"port":"console","sent_bytes":8,"sent":"reboot","waited":false,
 "matched":false,"line":null,"seq":null}
```

发出的 `reboot` 会以 `kind:"tx"` 入缓冲（回显）；设备的真实输出随后陆续到达。

---

## 步骤 5：`wait_for`（**阻塞等哨兵**，核心）

```json
{ "port": "console", "regex": "Bootloader", "timeout_ms": 15000 }
```
命中（守护阻塞等待，直到固件打印横幅）：
```json
{"ok":true,"port":"console","matched":true,
 "line":{"seq":57,"port":"console","ts_ms":1730000001234,
         "text":"[BOOT] Bootloader v1.3.0 starting","ansi":false,"kind":"rx"},
 "seq":57,"ts_ms":1730000001234,"from_seq":42}
```

**关键**：拿到命中行的 `seq=57`。这就是下一步的**游标**。

若 15s 内没等到（设备没重启 / 正则不对），返回的是**正常结果，不是错误**：
```json
{"ok":true,"port":"console","matched":false,"line":null,"seq":null,"ts_ms":null,"from_seq":42}
```
agent 应据 `matched` 分流：`true` 进步骤 6，`false` 跳到步骤 7（失败取证）。

---

## 步骤 6：`read(since_seq=<命中 seq>)`（按序续读，**无重复**）

```json
{ "port": "console", "since_seq": 57, "limit": 100 }
```
```json
{"ok":true,"port":"console",
 "lines":[{"seq":58,"port":"console","ts_ms":1730000001400,"text":"init: clock 480MHz","ansi":false,"kind":"rx"},
          {"seq":59,"port":"console","ts_ms":1730000001500,"text":"init: sdram ok","ansi":false,"kind":"rx"},
          {"seq":60,"port":"console","ts_ms":1730000001600,"text":"init: lvgl ready","ansi":false,"kind":"rx"}],
 "count":3,"next_seq":60,"dropped":0,"has_more":false,
 "first_seq":41,"last_seq":60}
```

因为游标是命中行的 `seq`，**不会重复读到 `Bootloader` 那一行**，只消费它之后的新行；
`next_seq=60` 可留作下一轮续读。真实设备上这里会持续返回后续启动日志。

---

## 步骤 7（失败分支）：`search` 定位 + `export` 留证

超时后先全缓冲搜崩溃特征：

```json
{ "port": "console", "regex": "HardFault|ASSERT|panic", "context": 2 }
```
```json
{"ok":true,"port":"console",
 "hits":[{"seq":52,"ts_ms":1730000000300,"text":"[ERR] ASSERT failed: sdram.c:118",
          "kind":"rx","match":"ASSERT",
          "context_before":[{"seq":51,"ts_ms":1730000000280,"text":"sdram init begin"}],
          "context_after":[{"seq":53,"ts_ms":1730000000320,"text":"halt"}]}],
 "count":1,"next_seq":52,"regex":"HardFault|ASSERT|panic"}
```

再整段落盘，交给人工或别的工具：

```json
{ "port": "console", "path": "out/boot-check.jsonl", "format": "json" }
```
```json
{"ok":true,"port":"console",
 "path":"D:\\projects\\project\\h750\\keshe\\serialhub\\out\\boot-check.jsonl",
 "format":"json","bytes":5120,"count":20}
```

---

## 收尾：`close`

```json
{ "port": "console" }
```
```json
{"ok":true,"name":"console","device":"COM11","open":false,
 "buffer":{"count":20,"bytes":5120,"first_seq":41,"last_seq":60,"dropped_total":0},
 "tcp_bridge":null}
```

（缓冲保留，随时可再 `open` 或 `snapshot`。）

---

## 为什么这样用（要点）

1. **`wait_for` 替代 sleep 轮询**：命中即返回；每轮省下固定的等待开销，且更稳。
2. **`seq` 即游标**：`wait_for` 命中的 `seq` 直接喂给 `read(since_seq=...)`，**零重复消费**。
3. **`kind` 区分回显与设备输出**：`tx`=本机发出、`rx`=设备返回；避免把 `reboot` 回显当回应。
4. **超时不是错误**：`matched:false` 是 `ok:true` 的正常返回，agent 用它走失败分支。
5. **失败可取证**：`search`（正则+上下文）定位，`export`（json）落盘。

对应的可运行代码见 [`mcp_client.py`](mcp_client.py)；完整工具参考见 [`../docs/MCP.md`](../docs/MCP.md)。
