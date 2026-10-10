# 第三方组件声明（Third-Party Notices）

`serialhub` 本项目采用 **MIT License**（见 [LICENSE](LICENSE)）。
以下为随本项目**内置分发**或**依赖**的第三方组件及其许可证。谨向原作者致谢。

## 一、随仓库内置分发的代码（vendored）

以下文件直接内置于 [`serialhub/static/vendor/`](serialhub/static/vendor/)，随本仓库一起分发：

| 组件 | 版本 | 许可证 | 上游 | 内置文件 |
|---|---|---|---|---|
| `@xterm/xterm` | 5.5.0 | MIT | <https://github.com/xtermjs/xterm.js> | `xterm.min.js`、`xterm.min.css` |
| `@xterm/addon-fit` | 0.10.0 | MIT | <https://github.com/xtermjs/xterm.js> | `addon-fit.min.js` |

两者均为 **MIT License**，版权归 xterm.js 作者所有
（`Copyright (c) 2017-2024 The xterm.js authors`）。
MIT 允许再分发，条件是保留版权与许可声明——本文件即为此声明。

## 二、运行时依赖（经包管理器安装，未内置分发）

| 组件 | 许可证 |
|---|---|
| `pyserial` | BSD-3-Clause |
| `fastapi` | MIT |
| `uvicorn` | BSD-3-Clause |
| `websockets` | BSD-3-Clause |
| `PyYAML` | MIT |
| `mcp`（官方 Python SDK） | MIT |

## 三、开发 / 测试依赖

| 组件 | 许可证 |
|---|---|
| `pytest` | MIT |
| `httpx` | BSD-3-Clause |

## 四、外部字体（运行时由 CDN 加载，未随仓库分发）

Web UI 通过 Google Fonts CDN 加载 **IBM Plex Sans / IBM Plex Mono**
（**SIL Open Font License 1.1**）。这些字体**不包含**在本仓库中；
CDN 不可达时界面自动回退到系统字体。

---

> **许可证兼容性**：以上全部为宽松许可证（MIT / BSD / OFL），与本项目的 MIT 许可证兼容。
