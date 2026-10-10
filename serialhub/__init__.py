"""serialhub —— 常驻串口中枢（多口守护 + 每口环形缓冲 + Web UI + TCP 桥 + MCP）。

本包对外暴露版本号与关键符号。子模块（models/ringbuffer/config/serialport/hub）
互不导入本 ``__init__``，因此下列普通导入不产生循环。
"""

from __future__ import annotations

__version__ = "0.1.0"

from .config import Config, PortConfig
from .hub import Hub
from .models import Line
from .ringbuffer import RingBuffer

__all__ = ["__version__", "Line", "RingBuffer", "Config", "PortConfig", "Hub"]
