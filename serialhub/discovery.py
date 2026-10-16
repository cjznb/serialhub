"""串口自动发现/匹配（按描述符解析真实设备）。

让端口不再依赖固定 COM 号：``PortConfig.match`` 给出一份匹配规格（VID/PID、
描述子串、hwid 等），在**打开时**以及**每次重连前**解析为当前真实设备名
（如 ``COM12``），故设备拔插后换到别的 COM 仍能被找回。

匹配规格（``spec``）支持的键（全部可选，未给出的键忽略）：

- ``description``: str，对 ``p.description`` 做**不区分大小写的子串**匹配。
- ``hwid``:        str，对 ``p.hwid`` 做不区分大小写子串匹配。
- ``device``:      str，对 ``p.device`` 做不区分大小写子串匹配（如 ``"COM"``）。
- ``serial``:      str，对 ``p.serial_number`` 做不区分大小写子串匹配。
- ``vid`` / ``pid``: int 或十六进制串（``0x1A86`` / ``"0x1A86"`` / ``46230``），
  精确比较 ``p.vid`` / ``p.pid``。
- ``index``:       int，默认 0；多个候选同样满足时取按 device 名排序后的第 N 个。

纯 stdlib + pyserial；不做任何打开动作，只枚举。
"""

from __future__ import annotations

from typing import Any, Callable, Optional

import serial.tools.list_ports as _list_ports

__all__ = ["resolve", "describe", "parse_usb_id", "MATCH_KEYS"]

#: 允许出现在 match 规格里的全部键（含非匹配键 ``index``）。
MATCH_KEYS: tuple[str, ...] = (
    "description", "hwid", "device", "serial", "vid", "pid", "index",
)

#: 真正参与“是否匹配”判定的键（``index`` 只用于候选选择，不参与匹配）。
_CRITERIA_KEYS: tuple[str, ...] = (
    "description", "hwid", "device", "serial", "vid", "pid",
)

#: 以子串方式比较的字符串键 → 端口对象上的属性名。
_SUBSTRING_ATTRS: dict[str, str] = {
    "description": "description",
    "hwid": "hwid",
    "device": "device",
    "serial": "serial_number",
}

#: 以整数精确比较的 USB 标识键。
_USB_ID_KEYS: tuple[str, ...] = ("vid", "pid")


def parse_usb_id(value: Any) -> int:
    """把 ``0x1A86`` / ``"0x1A86"`` / ``46230`` 统一解析为 int。

    非法值（bool、非数字串、其它类型）→ ``ValueError``。
    """
    if isinstance(value, bool):  # bool 是 int 子类，显式拒绝以免 True→1 误配
        raise ValueError(f"invalid usb id: {value!r}")
    if isinstance(value, int):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value, 0)  # 支持 0x 前缀；纯十进制亦可
        except ValueError as exc:
            raise ValueError(f"invalid usb id: {value!r}") from exc
    raise ValueError(f"invalid usb id: {value!r}")


def _port_dict(p: Any) -> dict:
    """把一个 ``ListPortInfo`` 投影为稳定的 dict（仅保留对外暴露的字段）。"""
    return {
        "device": str(getattr(p, "device", "") or ""),
        "description": str(getattr(p, "description", "") or ""),
        "hwid": str(getattr(p, "hwid", "") or ""),
        "vid": getattr(p, "vid", None),
        "pid": getattr(p, "pid", None),
    }


def _criterion(key: str, value: Any) -> Callable[[Any], bool]:
    """为单个匹配键构造一个 ``predicate(port) -> bool``。"""
    if key in _SUBSTRING_ATTRS:
        attr = _SUBSTRING_ATTRS[key]
        needle = str(value).lower()

        def pred(p: Any) -> bool:
            hay = str(getattr(p, attr, "") or "").lower()
            return needle in hay

        return pred
    # vid / pid：精确整数比较（端口缺该字段时视为不匹配）
    target = parse_usb_id(value)

    def pred(p: Any) -> bool:
        cur = getattr(p, key, None)
        return cur is not None and int(cur) == target

    return pred


def resolve(spec: dict, ports: Optional[list] = None) -> dict:
    """按 ``spec`` 解析出当前真实设备名。

    Args:
        spec: 匹配规格（见模块文档）。空 dict/None 视为“任意端口”。
        ports: 端口枚举结果；缺省调用 ``serial.tools.list_ports.comports()``
            （测试可 monkeypatch 该对象或直接传入桩列表）。

    Returns:
        dict，字段：
        - ``device``: 命中的设备名（``str``），无命中为 ``None``。
        - ``score``: 命中设备满足的匹配键数量（无命中为 0）。
        - ``candidates``: 满足**全部**匹配键的候选端口列表（按 device 名排序），
          每项为 ``{"device","description","hwid","vid","pid"}``。
        - ``matched``: 命中设备实际满足的匹配键名列表（无命中为空）。
    """
    spec = spec or {}
    if not isinstance(spec, dict):
        raise ValueError("match spec must be a mapping")
    for key in spec:
        if key not in MATCH_KEYS:
            raise ValueError(f"unknown match key: {key!r}")

    raw_ports = list(_list_ports.comports() if ports is None else ports)
    criteria: list[tuple[str, Callable[[Any], bool]]] = [
        (key, _criterion(key, spec[key])) for key in _CRITERIA_KEYS if key in spec
    ]
    # 确定性排序：按 device 名（字符串）。
    pool = sorted(raw_ports, key=lambda p: str(getattr(p, "device", "") or ""))
    matched_ports = [p for p in pool if all(pred(p) for _, pred in criteria)]
    candidates = [_port_dict(p) for p in matched_ports]

    index = 0
    if "index" in spec:
        try:
            index = int(spec["index"])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"match index must be an integer: {spec['index']!r}") from exc
        if index < 0:
            raise ValueError(f"match index must be >= 0: {index}")

    if 0 <= index < len(matched_ports):
        return {
            "device": candidates[index]["device"],
            "score": len(criteria),
            "candidates": candidates,
            "matched": [key for key, _ in criteria],
        }
    return {"device": None, "score": 0, "candidates": candidates, "matched": []}


def describe(spec: dict) -> str:
    """把匹配规格渲染成人类可读摘要，用于错误消息。

    例：``{"description": "CH340"}`` → ``description~'CH340'``。
    """
    spec = spec or {}
    if not isinstance(spec, dict):
        return str(spec)
    parts: list[str] = []
    for key in ("description", "hwid", "device", "serial"):
        if key in spec and spec[key] is not None:
            parts.append(f"{key}~{spec[key]!r}")
    for key in _USB_ID_KEYS:
        if key in spec and spec[key] is not None:
            try:
                parts.append(f"{key}=0x{parse_usb_id(spec[key]):04X}")
            except ValueError:
                parts.append(f"{key}={spec[key]!r}")
    if spec.get("index"):
        parts.append(f"index={spec['index']}")
    return ", ".join(parts) if parts else "any port"
