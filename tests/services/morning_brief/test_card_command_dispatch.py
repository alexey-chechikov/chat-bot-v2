"""Регрессия 2026-06-10: «/card — 0 реакции».

Две причины, обе закрыты:
1. Роутинг: настоящий JSON-апдейт Bot API должен доводить «/card» до handle_card
   (ack + карточка) через bot.process_new_updates.
2. threaded=False: при threaded=True исключение в хэндлере навсегда блокировало
   WorkerThread telebot (continue_event.wait() никто не снимал в нашем кастомном
   полл-цикле) → после 2 исключений бот молча ел команды. Inline-режим обязателен.
"""
from __future__ import annotations

import time

import pytest


def _make_app(monkeypatch):
    import config
    if ":" not in str(getattr(config, "BOT_TOKEN", "") or ""):
        pytest.skip("BOT_TOKEN не настроен на этой машине (не прод)")
    from services.morning_brief import card as card_mod
    monkeypatch.setattr(card_mod, "build_morning_card",
                        lambda include_scan=True: f"FAKE_CARD scan={include_scan}")
    from services.telegram_runtime import TelegramBotApp
    app = TelegramBotApp()
    sent: list[tuple[int, str]] = []
    monkeypatch.setattr(app.bot, "send_message",
                        lambda chat_id, text, **kw: sent.append((int(chat_id), str(text))))
    return app, sent


def _update(chat_id: int, text: str):
    import telebot.types as tt
    return tt.Update.de_json({
        "update_id": 999999001,
        "message": {
            "message_id": 12500,
            "from": {"id": chat_id, "is_bot": False, "first_name": "Kemper"},
            "chat": {"id": chat_id, "first_name": "Kemper", "type": "private"},
            "date": int(time.time()),
            "text": text,
            "entities": [{"offset": 0, "length": len(text.split()[0]), "type": "bot_command"}],
        },
    })


def test_bot_is_not_threaded():
    """threaded=True + кастомный полл-цикл = молчаливая смерть воркеров telebot."""
    import config
    if ":" not in str(getattr(config, "BOT_TOKEN", "") or ""):
        pytest.skip("BOT_TOKEN не настроен на этой машине (не прод)")
    from services.telegram_runtime import TelegramBotApp
    app = TelegramBotApp()
    assert app.bot.threaded is False


def test_card_update_routes_to_handler(monkeypatch):
    app, sent = _make_app(monkeypatch)
    chat = app.allowed_chat_ids[0]
    app.bot.process_new_updates([_update(chat, "/card")])
    # ack уходит синхронно (threaded=False), карточка — из фонового потока
    deadline = time.time() + 5
    while len(sent) < 2 and time.time() < deadline:
        time.sleep(0.05)
    assert any("Собираю карточку" in t for _, t in sent), sent
    assert any("FAKE_CARD scan=True" in t for _, t in sent), sent


def test_card_fast_skips_scan(monkeypatch):
    app, sent = _make_app(monkeypatch)
    chat = app.allowed_chat_ids[0]
    app.bot.process_new_updates([_update(chat, "/card fast")])
    deadline = time.time() + 5
    while len(sent) < 2 and time.time() < deadline:
        time.sleep(0.05)
    assert any("FAKE_CARD scan=False" in t for _, t in sent), sent
