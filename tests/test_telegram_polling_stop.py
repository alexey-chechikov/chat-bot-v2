"""Собственный цикл опроса Telegram останавливается (разбор GPT к a25c763): раньше `while True` без сигнала — поток
опроса жил вечно, остановка процесса ждала его до SIGKILL launchd, а замок одного экземпляра держался всё это время.
Объект без __init__ (без токена и сети), бот — поддельный."""
from __future__ import annotations

import threading
import time

from services.telegram_runtime import POLL_TIMEOUT_SEC, TelegramBotApp


class _Bot:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = []

    def get_updates(self, offset, timeout, long_polling_timeout):
        self.calls.append((timeout, long_polling_timeout))
        time.sleep(0.02)
        if self.fail:
            raise RuntimeError("сеть")
        return []

    def process_new_updates(self, updates):
        pass

    def stop_polling(self):                          # библиотечная остановка — на собственный цикл не влияет
        pass


def _app(bot):
    app = TelegramBotApp.__new__(TelegramBotApp)
    app.allowed_chat_ids = []                        # без рабочих потоков оповещений
    app.bot = bot
    return app


def _run(app, method):
    th = threading.Thread(target=getattr(app, method), daemon=True)
    th.start()
    time.sleep(0.15)
    return th


def test_stop_polling_loop_ends_both_loops():
    for method in ("run_polling_blocking", "run"):
        app = _app(_Bot())
        th = _run(app, method)
        app.bot.stop_polling()                       # как раньше в app_runner — цикл продолжается
        time.sleep(0.1)
        assert th.is_alive(), method
        app.stop_polling_loop()
        th.join(2)
        assert not th.is_alive(), method


def test_stop_interrupts_error_backoff():
    app = _app(_Bot(fail=True))
    th = _run(app, "run_polling_blocking")           # после ошибки — пауза 2 с
    t0 = time.monotonic()
    app.stop_polling_loop()
    th.join(1.5)
    assert not th.is_alive() and time.monotonic() - t0 < 1.5


def test_long_poll_bounded_for_shutdown():
    app = _app(_Bot())
    th = _run(app, "run_polling_blocking")
    app.stop_polling_loop()
    th.join(2)
    assert POLL_TIMEOUT_SEC <= 10 and app.bot.calls and all(c == (POLL_TIMEOUT_SEC, POLL_TIMEOUT_SEC)
                                                            for c in app.bot.calls)
