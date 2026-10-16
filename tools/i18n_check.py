#!/usr/bin/env python3
"""i18n parity checker for serialhub.

Two independent checks, both must pass for a clean exit:

1. **Backend catalogs** (``serialhub/i18n/*.json``) — every language must expose
   the exact same key set as ``en.json``. Add-a-language = drop ``<lang>.json``,
   so a drifted key set is a real defect (it silently degrades to the ``en``
   fallback at runtime).

2. **UI catalogs** (``serialhub/static/i18n/*.js``) — *best-effort*: if the Web
   UI locale files exist, extract the keys of each ``register('<lang>', { … })``
   dictionary and check parity against the ``en`` UI locale. Underscore-prefixed
   files (e.g. ``_template.js``) are skipped — they are not locales.

Exit 0 when every catalog matches its ``en`` baseline, 1 otherwise. Prints a
human-readable report either way.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT / "serialhub" / "i18n"
UI_DIR = ROOT / "serialhub" / "static" / "i18n"

_QUOTES = "'\"`"
_REGISTER_RE = re.compile(r"register\s*\(\s*(['\"])(?P<lang>[\w-]+)\1\s*,\s*")


# --------------------------------------------------------------------------- #
# backend (.json) catalogs
# --------------------------------------------------------------------------- #
def load_backend() -> tuple[dict[str, set[str]], list[str]]:
    """Return ``{lang: key_set}`` plus a list of problem strings."""
    catalogs: dict[str, set[str]] = {}
    problems: list[str] = []
    if not BACKEND_DIR.is_dir():
        return catalogs, [f"backend catalog dir not found: {BACKEND_DIR}"]
    for path in sorted(BACKEND_DIR.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            problems.append(f"{path.name}: invalid JSON ({exc})")
            continue
        if not isinstance(raw, dict):
            problems.append(f"{path.name}: top level must be an object")
            continue
        catalogs[path.stem] = {str(k) for k in raw}
    if "en" not in catalogs:
        problems.append("backend baseline serialhub/i18n/en.json is missing")
    return catalogs, problems


# --------------------------------------------------------------------------- #
# UI (.js) catalogs — quote-aware object-literal key extraction
# --------------------------------------------------------------------------- #
def _read_brace_block(text: str, start: int) -> tuple[str, int]:
    """Return the ``{...}`` substring beginning at ``start`` and the end index."""
    depth = 0
    i = start
    n = len(text)
    in_str: Optional[str] = None
    while i < n:
        ch = text[i]
        if in_str is not None:
            if ch == "\\":
                i += 2
                continue
            if ch == in_str:
                in_str = None
            i += 1
            continue
        if ch in _QUOTES:
            in_str = ch
            i += 1
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1], i + 1
        i += 1
    return text[start:], n


def _read_js_string(text: str, i: int) -> tuple[str, int]:
    """``text[i]`` is a quote; return its raw content and the index after the close."""
    quote = text[i]
    i += 1
    n = len(text)
    out: list[str] = []
    while i < n:
        ch = text[i]
        if ch == "\\":
            out.append(text[i : i + 2])
            i += 2
            continue
        if ch == quote:
            return "".join(out), i + 1
        out.append(ch)
        i += 1
    return "".join(out), n


def _top_level_keys(body: str) -> list[str]:
    """Keys of an object literal at brace depth 1, quoted or bare, followed by ``:``."""
    keys: list[str] = []
    i = 0
    n = len(body)
    depth = 0
    while i < n:
        ch = body[i]
        if ch == "{":
            depth += 1
            i += 1
            continue
        if ch == "}":
            depth -= 1
            i += 1
            continue
        if ch in _QUOTES:
            # A quoted string is either a key ("a.b":) or a value ("text"); skip
            # its body (so braces/commas inside strings don't corrupt the scan)
            # and record it as a key only when a ':' follows at depth 1.
            key, j = _read_js_string(body, i)
            if depth == 1:
                k = j
                while k < n and body[k].isspace():
                    k += 1
                if k < n and body[k] == ":":
                    keys.append(key)
            i = j
            continue
        if depth == 1 and (ch.isalpha() or ch in "_$"):
            j = i
            while j < n and (body[j].isalnum() or body[j] in "_$"):
                j += 1
            k = j
            while k < n and body[k].isspace():
                k += 1
            if k < n and body[k] == ":":
                keys.append(body[i:j])
            i = j
            continue
        i += 1
    return keys


def extract_ui_keys(text: str) -> dict[str, set[str]]:
    """Map each ``register('<lang>', {...})`` call to its dictionary key set."""
    found: dict[str, set[str]] = {}
    for match in _REGISTER_RE.finditer(text):
        lang = match.group("lang")
        start = match.end()
        if start >= len(text) or text[start] != "{":
            continue
        body, _ = _read_brace_block(text, start)
        found.setdefault(lang, set()).update(_top_level_keys(body))
    return found


def load_ui() -> tuple[dict[str, set[str]], list[str]]:
    catalogs: dict[str, set[str]] = {}
    problems: list[str] = []
    if not UI_DIR.is_dir():
        return catalogs, problems  # optional: UI locale files may not exist
    for path in sorted(UI_DIR.glob("*.js")):
        if path.name.startswith("_"):
            continue  # template / partial, not a locale
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            problems.append(f"{path.name}: cannot read ({exc})")
            continue
        for lang, keys in extract_ui_keys(text).items():
            catalogs.setdefault(lang, set()).update(keys)
    return catalogs, problems


# --------------------------------------------------------------------------- #
# parity + report
# --------------------------------------------------------------------------- #
def _diff(catalogs: dict[str, set[str]], baseline: str) -> list[str]:
    """Compare every non-baseline catalog's key set to ``baseline``."""
    problems: list[str] = []
    base_keys = catalogs.get(baseline)
    if base_keys is None:
        return problems  # reported elsewhere
    for lang in sorted(catalogs):
        if lang == baseline:
            continue
        missing = sorted(base_keys - catalogs[lang])
        extra = sorted(catalogs[lang] - base_keys)
        if missing:
            problems.append(f"[{lang}] missing {len(missing)} key(s): {', '.join(missing)}")
        if extra:
            problems.append(f"[{lang}] extra {len(extra)} key(s): {', '.join(extra)}")
    return problems


def _report(title: str, catalogs: dict[str, set[str]], baseline: str) -> None:
    print(title)
    if not catalogs:
        print("  (none found)")
        return
    for lang in sorted(catalogs):
        marker = " (baseline)" if lang == baseline else ""
        print(f"  {lang}: {len(catalogs[lang])} keys{marker}")


def main() -> int:
    backend, backend_problems = load_backend()
    ui, ui_problems = load_ui()

    backend_problems += _diff(backend, "en")
    if ui:
        ui_problems += _diff(ui, "en")

    print("serialhub i18n check")
    print("=" * 20)
    _report("backend catalogs (serialhub/i18n/*.json):", backend, "en")
    _report("UI catalogs (serialhub/static/i18n/*.js, best-effort):", ui, "en")
    print()

    problems = backend_problems + ui_problems
    if problems:
        print(f"FAIL — {len(problems)} problem(s):")
        for item in problems:
            print(f"  - {item}")
        return 1
    print("OK — all catalogs match their 'en' baseline.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
