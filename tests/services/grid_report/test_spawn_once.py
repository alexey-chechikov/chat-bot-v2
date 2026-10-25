"""25.10 (аудит GPT 481385e G4): повторная тяжёлая команда (/map, /tv, /card, /levels, /rynok), пока прежняя сборка
идёт, не плодит потоки — отвечает «уже собираю». Настоящий бот не поднимается: метод вызывается на заглушке."""
from __future__ import annotations

import threading

from services.telegram_runtime import TelegramBotApp


class Fake:
    def __init__(self):
        self._builders, self._builders_lock = {}, threading.Lock()
        self.sent = []
        self.bot = self

    def send_message(self, chat_id, text, **kw):
        self.sent.append(text)


def test_second_command_while_building_does_not_spawn():
    app, gate, runs = Fake(), threading.Event(), []

    def job():
        runs.append(1)
        gate.wait(5)

    assert TelegramBotApp._spawn_once(app, "map-builder", job, 1, ack="🗺 Собираю") is True
    assert TelegramBotApp._spawn_once(app, "map-builder", job, 1, ack="🗺 Собираю") is False
    assert app.sent == ["🗺 Собираю", "⏳ Уже собираю по прошлой команде — ответ придёт, повторять не нужно."]
    assert TelegramBotApp._spawn_once(app, "tv-levels", lambda: None, 1) is True      # другой вид — свой поток
    gate.set()
    app._builders["map-builder"].join(5)
    assert TelegramBotApp._spawn_once(app, "map-builder", lambda: None, 1) is True    # прежняя кончилась — можно
    assert runs == [1]
