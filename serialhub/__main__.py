"""``python -m serialhub`` 入口。

本文件归属 A；``cli.py``（含 ``main``）由另一 agent 提供，可能尚未就绪，故延迟导入
并给出清晰提示，而不是在包导入期崩溃。
"""

from __future__ import annotations

import sys


def _run() -> int:
    try:
        from .cli import main
    except Exception as exc:
        print(
            f"serialhub CLI unavailable ({type(exc).__name__}: {exc}). "
            "The 'serialhub.cli' module is required to run 'python -m serialhub'.",
            file=sys.stderr,
        )
        return 1
    return main()


if __name__ == "__main__":
    raise SystemExit(_run())
