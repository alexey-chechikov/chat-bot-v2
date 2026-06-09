"""Регрессия 2026-06-10: tg_notify импортировал несуществующий core.config.load_config →
с 06.06 ВСЕ TV-сигналы молча не доходили в TG ('tv_notify.no_config — skipping TG send'
в launchd_app_runner.err). Теперь читает константы корневого config (как telegram_alert_client).
"""
from __future__ import annotations

import sys
import types


def _reset(mod):
    mod._config_loaded = False
    mod._bot_token = ""
    mod._chat_id = ""


def test_load_config_reads_root_config_constants(monkeypatch):
    fake = types.ModuleType("config")
    fake.BOT_TOKEN = "12345:FAKE"
    fake.CHAT_ID = "111, 222"  # список через запятую — берём первый
    monkeypatch.setitem(sys.modules, "config", fake)

    from services.tv_webhook import tg_notify
    _reset(tg_notify)
    tg_notify._load_config()
    assert tg_notify._bot_token == "12345:FAKE"
    assert tg_notify._chat_id == "111"
    _reset(tg_notify)  # не оставляем фейковые креды другим тестам


def test_load_config_real_module_has_credentials():
    """На прод-маке корневой config обязан давать рабочие креды (BOT_TOKEN формата id:hash)."""
    import config
    if not str(getattr(config, "BOT_TOKEN", "") or "").strip():
        import pytest
        pytest.skip("BOT_TOKEN не настроен на этой машине (не прод)")
    from services.tv_webhook import tg_notify
    _reset(tg_notify)
    tg_notify._load_config()
    assert ":" in tg_notify._bot_token
    assert tg_notify._chat_id
    _reset(tg_notify)
