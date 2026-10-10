#!/usr/bin/env python3
"""serialhub 编程式客户端示例（只用标准库 + serialhub.client）。

它演示一个最小、干净的客户端流程，**假设守护已在运行**：

    python -m serialhub serve --config examples/config.yaml   # 先在另一个终端起守护
    python examples/mcp_client.py                              # 再跑本脚本

流程：list_ports -> open -> snapshot -> read(游标) -> send(+等回应) -> wait_for -> search。
默认针对 examples/config.yaml 里的 `demo`（device=loop://）口，无需硬件即可跑通。

返回值约定：每个 client 方法都直接返回 REST 的 JSON envelope（已带 `ok`），
失败时 `{"ok": false, "error": "..."}`，绝不抛异常。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

# 让脚本能直接 `import serialhub`（examples/ 的上一级就是仓库根）。
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from serialhub.client import Client  # noqa: E402  (路径注入之后再导入)


def show(label: str, env: dict) -> dict:
    """打印一行标题 + 缩进 JSON，并把 envelope 传回便于串联。"""
    print(f"\n=== {label} ===")
    print(json.dumps(env, ensure_ascii=False, indent=2))
    return env


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="serialhub 编程式客户端示例")
    ap.add_argument("--url", default=os.environ.get("SERIALHUB_URL", "http://127.0.0.1:8765"),
                    help="守护基址（默认 http://127.0.0.1:8765）")
    ap.add_argument("--token", default=os.environ.get("SERIALHUB_TOKEN"),
                    help="Bearer token（守护设了才需要）")
    ap.add_argument("--port", default="demo",
                    help="逻辑口名（默认 demo，需 device=loop://）")
    args = ap.parse_args(argv)

    client = Client(args.url, args.token)

    # 0) 守护是否在跑？（连接失败时 call 返回 ok:false，不抛异常）
    health = client.call("GET", "/health")
    if not health.get("ok"):
        print(f"守护不可达：{args.url}")
        print("请先运行： python -m serialhub serve --config examples/config.yaml")
        return 1

    # 1) 列口：确认目标口存在，记下当前最新 seq 作为增量起点。
    listing = show("list_ports", client.list_ports())
    ports = {p.get("name"): p for p in listing.get("ports", [])}
    if args.port not in ports:
        print(f"端口 {args.port!r} 不在配置中；可选：{sorted(ports)}")
        return 1

    # 2) 打开（若已打开，open 是幂等的重开）。
    show(f"open({args.port})", client.open(args.port))

    # 3) 游标起点 + 现场快照。
    start_seq = (ports[args.port].get("buffer") or {}).get("last_seq") or 0
    show("snapshot(tail_lines=20)", client.snapshot(args.port, tail_lines=20))
    show(f"read(since_seq={start_seq}) 增量起点",
         client.read(args.port, since_seq=start_seq, limit=20))

    # 4) send + wait_regex：一步完成「发命令 + 等回应」。
    show("send('reboot', wait_regex='reboot')",
         client.send(args.port, "reboot", eol="\r\n", wait_regex="reboot", timeout_ms=5000))

    # 5) wait_for：阻塞等哨兵。loop:// 已回显，立即命中；真实设备会阻塞到超时。
    #    注意：超时是 matched:false（仍 ok:true），不是错误。
    wait = show("wait_for('reboot', timeout_ms=5000)",
                client.wait(args.port, "reboot", timeout_ms=5000, since_seq=start_seq))
    hit_seq = wait.get("seq")

    # 6) read(since_seq=命中seq)：按序消费后续，不重复。
    if hit_seq is not None:
        show(f"read(since_seq={hit_seq}) 续读（无重复）",
             client.read(args.port, since_seq=hit_seq, limit=50))

    # 7) search：全缓冲正则搜索，可带上下文。
    show("search('reboot', context=1)", client.search(args.port, "reboot", context=1))

    print("\n完成。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
