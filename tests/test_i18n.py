"""Tests for the pluggable backend i18n layer (``serialhub/i18n``)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from serialhub import i18n

CATALOG_DIR = Path(i18n.__file__).resolve().parent


@pytest.fixture(autouse=True)
def _reset_locale():
    """Keep the active locale from leaking between tests."""
    i18n.set_locale(None)
    yield
    i18n.set_locale(None)


# ---- (a) en/zh key parity ------------------------------------------------- #
def test_en_zh_key_parity() -> None:
    en = json.loads((CATALOG_DIR / "en.json").read_text(encoding="utf-8"))
    zh = json.loads((CATALOG_DIR / "zh.json").read_text(encoding="utf-8"))
    assert isinstance(en, dict) and isinstance(zh, dict)
    assert set(en) == set(zh)


# ---- (d) available -------------------------------------------------------- #
def test_available_contains_en_and_zh() -> None:
    codes = i18n.available()
    assert "en" in codes and "zh" in codes
    assert codes == sorted(codes)


def test_default_locale_is_en() -> None:
    assert i18n.DEFAULT_LANG == "en"
    assert i18n.get_locale() == "en"


# ---- (b) t() lookup / fallback ------------------------------------------- #
def test_t_returns_english_by_default() -> None:
    assert i18n.t("server.error.unauthorized") == "unauthorized"
    assert i18n.t("hub.error.port_exists", name="console") == "port 'console' already exists"


def test_t_formats_placeholders_and_repr() -> None:
    assert i18n.t("server.error.unknown_port", name="'nope'") == "unknown port: 'nope'"
    assert i18n.t("hub.error.unknown_format", fmt="xml", formats=["raw", "json"]) == (
        "unknown format 'xml'; expected one of ['raw', 'json']"
    )


def test_t_fallback_active_then_en_then_key(monkeypatch: pytest.MonkeyPatch) -> None:
    # A synthetic locale in `available` but with a deliberately partial catalog.
    monkeypatch.setattr(i18n, "available", lambda: ["en", "qaa"])
    monkeypatch.setitem(i18n._catalog_cache, "qaa", {"only.here": "LOCAL"})
    i18n.set_locale("qaa")

    assert i18n.t("only.here") == "LOCAL"                        # active catalog hit
    assert i18n.t("server.error.unauthorized") == "unauthorized"  # en fallback
    assert i18n.t("totally.absent.key") == "totally.absent.key"   # key fallback


def test_t_never_raises_on_missing_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(i18n, "available", lambda: ["en", "qaa"])
    monkeypatch.setitem(i18n._catalog_cache, "qaa", {"greet": "hi {missing}"})
    i18n.set_locale("qaa")

    assert i18n.t("greet") == "hi {missing}"             # no vars → returned as-is
    assert i18n.t("greet", other="x") == "hi {missing}"  # KeyError swallowed


# ---- (c) resolve_locale precedence --------------------------------------- #
def test_resolve_locale_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SERIALHUB_LANG", raising=False)

    assert i18n.resolve_locale() == "en"                                   # default
    assert i18n.resolve_locale(accept_language="zh-CN,zh;q=0.9,en") == "zh"  # accept-language
    assert i18n.resolve_locale(accept_language="fr-FR,fr") == "en"         # unsupported → default

    monkeypatch.setenv("SERIALHUB_LANG", "zh")
    assert i18n.resolve_locale() == "zh"                                   # env
    assert i18n.resolve_locale(accept_language="en") == "zh"              # env > accept-language
    assert i18n.resolve_locale(explicit="en") == "en"                     # explicit > env

    monkeypatch.setenv("SERIALHUB_LANG", "zz")                            # unsupported env ignored
    assert i18n.resolve_locale() == "en"


def test_set_locale_normalizes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SERIALHUB_LANG", raising=False)
    i18n.set_locale("zh")
    assert i18n.get_locale() == "zh"
    assert i18n.t("server.error.unauthorized") == "未授权"

    i18n.set_locale("zh-CN")  # region suffix → primary tag
    assert i18n.get_locale() == "zh"

    i18n.set_locale("zz")  # unsupported → unset → default
    assert i18n.get_locale() == "en"


# ---- server: per-request Accept-Language --------------------------------- #
def test_server_404_localized_by_accept_language(client) -> None:
    en = client.post("/api/ports/nope/close")  # no header → unchanged English
    assert en.status_code == 404
    assert en.json()["error"] == "unknown port: 'nope'"

    zh = client.post("/api/ports/nope/close", headers={"Accept-Language": "zh-CN"})
    assert zh.status_code == 404
    assert zh.json()["error"] == "未知端口：'nope'"


def test_server_unauthorized_localized(make_config, hub_factory) -> None:
    from fastapi.testclient import TestClient

    from serialhub.server import create_app

    cfg = make_config(token="sekret")
    hub = hub_factory(cfg)
    with TestClient(create_app(hub, cfg)) as tc:
        en = tc.get("/api/ports")
        assert en.status_code == 401
        assert en.json()["error"] == "unauthorized"

        zh = tc.get("/api/ports", headers={"Accept-Language": "zh"})
        assert zh.status_code == 401
        assert zh.json()["error"] == "未授权"
