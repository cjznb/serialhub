"""Pluggable backend i18n layer for serialhub (stdlib only, no new deps).

A *language is a file*: drop ``serialhub/i18n/<lang>.json`` (a flat
``{"dotted.key": "text with {var} placeholders"}`` map) and it becomes usable —
no code change. Catalogs are loaded lazily and cached.

Resolution precedence (see :func:`resolve_locale`):
``explicit`` → env ``SERIALHUB_LANG`` → ``Accept-Language`` → ``DEFAULT_LANG``.

Lookup precedence (see :func:`t`): active locale → ``en`` → the key itself.
:func:`t` never raises: a missing key or a bad format returns a degraded string.

The default locale is ``en`` and the ``en`` catalog reproduces the project's
existing strings verbatim, so behaviour is unchanged unless a caller opts into
another locale (via ``SERIALHUB_LANG`` or an ``Accept-Language`` header).
"""

from __future__ import annotations

import contextvars
import json
import os
from pathlib import Path
from typing import Any, Optional

DEFAULT_LANG = "en"

_CATALOG_DIR = Path(__file__).resolve().parent

# Active locale for the current context. ``None`` means "unset" → fall back to
# the env/default. A ContextVar keeps this isolated per-request / per-task.
_ACTIVE: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "serialhub_i18n_locale", default=None
)

_catalog_cache: dict[str, dict[str, str]] = {}
_available_cache: Optional[list[str]] = None


def available() -> list[str]:
    """Return the sorted codes of every ``*.json`` catalog in this package."""
    global _available_cache
    if _available_cache is None:
        _available_cache = sorted(path.stem for path in _CATALOG_DIR.glob("*.json"))
    return list(_available_cache)


def _load(lang: str) -> Optional[dict[str, str]]:
    """Lazily load + cache a catalog; ``None`` when the language is absent."""
    cached = _catalog_cache.get(lang)
    if cached is not None:
        return cached
    path = _CATALOG_DIR / f"{lang}.json"
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    catalog = (
        {str(k): str(v) for k, v in raw.items()} if isinstance(raw, dict) else {}
    )
    _catalog_cache[lang] = catalog
    return catalog


def _normalize(lang: Optional[str]) -> Optional[str]:
    """Map a tag like ``zh-CN`` / ``zh`` to a supported code, else ``None``."""
    if not lang:
        return None
    code = str(lang).strip().lower().replace("_", "-")
    if not code:
        return None
    supported = available()
    if code in supported:
        return code
    primary = code.split("-", 1)[0]
    return primary if primary in supported else None


def _env_default() -> str:
    """The env-selected locale if valid, else :data:`DEFAULT_LANG`."""
    return _normalize(os.environ.get("SERIALHUB_LANG")) or DEFAULT_LANG


def get_locale() -> str:
    """The active locale: explicit override → env → default."""
    return _ACTIVE.get() or _env_default()


def set_locale(lang: Optional[str]) -> None:
    """Set the active locale for the current context; invalid → unset."""
    _ACTIVE.set(_normalize(lang))


def _parse_accept_language(header: Optional[str]) -> Optional[str]:
    """First supported language in an ``Accept-Language`` header, else ``None``."""
    if not header:
        return None
    for part in str(header).split(","):
        token = part.split(";", 1)[0].strip()
        if not token or token == "*":
            continue
        code = _normalize(token)
        if code:
            return code
    return None


def resolve_locale(
    explicit: Optional[str] = None,
    accept_language: Optional[str] = None,
) -> str:
    """Resolve a locale by precedence; only ever returns codes in :func:`available`."""
    return (
        _normalize(explicit)
        or _normalize(os.environ.get("SERIALHUB_LANG"))
        or _parse_accept_language(accept_language)
        or DEFAULT_LANG
    )


def _lookup(lang: str, key: str) -> Optional[str]:
    catalog = _load(lang)
    if catalog is None:
        return None
    return catalog.get(key)


def t(key: str, **vars: Any) -> str:
    """Translate ``key`` for the active locale; never raises.

    Falls back active → ``en`` → the raw key. ``{var}`` placeholders are filled
    from ``**vars``; a formatting error yields the (unformatted) text.
    """
    try:
        text = _lookup(get_locale(), key)
        if text is None:
            text = _lookup(DEFAULT_LANG, key)
        if text is None:
            return str(key)
        if not vars:
            return text
        try:
            return text.format(**vars)
        except (KeyError, IndexError, ValueError):
            return text
    except Exception:  # noqa: BLE001 - the contract is "never raise"
        return str(key)


__all__ = [
    "DEFAULT_LANG",
    "available",
    "get_locale",
    "set_locale",
    "resolve_locale",
    "t",
]
