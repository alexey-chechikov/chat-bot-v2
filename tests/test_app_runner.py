from __future__ import annotations

import asyncio
import sys
import warnings
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import app_runner
import orchestrator_runner
import telegram_bot_runner
from services.telegram_runtime import TelegramBotApp


@pytest.fixture(autouse=True)
def _no_real_services(monkeypatch, tmp_path):
    """21.10: без подмены main() запускал настоящие сетки WEEX на живом учёте и ключах — вторая копия рядом с живым
    процессом (сироты холостого золота 12:08–12:10). Каждая задача _run_* — заглушка до stop_event, замок — во
    временной папке, аудит стартов не пишется."""
    async def idle(stop_event=None, *args, **kwargs):
        await (stop_event if isinstance(stop_event, asyncio.Event) else asyncio.Event()).wait()

    for name in dir(app_runner):
        if (name.startswith("_run_") and name != "_run_polling_in_executor"
                and asyncio.iscoroutinefunction(getattr(app_runner, name))):
            monkeypatch.setattr(app_runner, name, idle)
    monkeypatch.setattr(app_runner, "_log_startup_audit", lambda: None)
    real_main = app_runner.main
    monkeypatch.setattr(app_runner, "main",
                        lambda **kw: real_main(lock_path=str(tmp_path / "app_runner.lock"), **kw))


def test_main_starts_no_real_service():
    import inspect
    import re
    src = inspect.getsource(app_runner._main_locked)
    called = set(re.findall(r"create_task\(\s*([\w.]+)\(", src))
    assert "_run_weex_grid" in called
    for name in called - {"_run_polling_in_executor", "orchestrator.start", "stop_event.wait"}:
        assert getattr(app_runner, name).__name__ == "idle", name


def test_app_runner_starts_and_stops_cleanly(monkeypatch):
    stop_event = asyncio.Event()
    fake_app = MagicMock()
    fake_app.bot = MagicMock()
    fake_app.run_polling_blocking = MagicMock(side_effect=lambda: __import__("time").sleep(0.5))

    async def fake_start():
        await asyncio.sleep(60)

    fake_orchestrator = SimpleNamespace(start=AsyncMock(side_effect=fake_start), stop=MagicMock())

    monkeypatch.setattr("services.telegram_runtime.TelegramBotApp", lambda: fake_app)
    monkeypatch.setattr("app_runner.OrchestratorLoop", lambda cfg: fake_orchestrator)

    async def exercise():
        task = asyncio.create_task(
            app_runner.main(
                stop_event=stop_event,
                signal_handler_installer=lambda loop, event: None,
                shutdown_timeout=0.2,
            )
        )
        await asyncio.sleep(0.1)
        stop_event.set()
        return await asyncio.wait_for(task, timeout=2)

    rc = asyncio.run(exercise())
    assert rc == 0
    fake_orchestrator.stop.assert_called_once()
    fake_app.bot.stop_polling.assert_called_once()
    fake_app.stop_polling_loop.assert_called_once()     # 21.10: собственный цикл опроса тоже останавливается


def test_app_runner_orchestrator_crash_stops_polling(monkeypatch):
    fake_app = MagicMock()
    fake_app.bot = MagicMock()
    fake_app.run_polling_blocking = MagicMock(side_effect=lambda: None)

    async def fake_start():
        raise RuntimeError("boom")

    fake_orchestrator = SimpleNamespace(start=AsyncMock(side_effect=fake_start), stop=MagicMock())

    monkeypatch.setattr("services.telegram_runtime.TelegramBotApp", lambda: fake_app)
    monkeypatch.setattr("app_runner.OrchestratorLoop", lambda cfg: fake_orchestrator)

    rc = asyncio.run(app_runner.main(signal_handler_installer=lambda loop, event: None, shutdown_timeout=0.2))
    assert rc == 1
    fake_orchestrator.stop.assert_called_once()
    fake_app.bot.stop_polling.assert_called_once()


def test_app_runner_polling_crash_stops_orchestrator(monkeypatch):
    fake_app = MagicMock()
    fake_app.bot = MagicMock()
    fake_app.run_polling_blocking = MagicMock(side_effect=RuntimeError("boom"))

    async def fake_start():
        await asyncio.sleep(60)

    fake_orchestrator = SimpleNamespace(start=AsyncMock(side_effect=fake_start), stop=MagicMock())

    monkeypatch.setattr("services.telegram_runtime.TelegramBotApp", lambda: fake_app)
    monkeypatch.setattr("app_runner.OrchestratorLoop", lambda cfg: fake_orchestrator)

    rc = asyncio.run(app_runner.main(signal_handler_installer=lambda loop, event: None, shutdown_timeout=0.2))
    assert rc == 1
    fake_orchestrator.stop.assert_called_once()
    fake_app.bot.stop_polling.assert_called_once()


@pytest.mark.skipif(sys.platform == "win32", reason="loop.add_signal_handler SIGINT is not testable on Windows")
def test_app_runner_sigint_triggers_graceful_shutdown(monkeypatch):
    stop_event = asyncio.Event()
    fake_app = MagicMock()
    fake_app.bot = MagicMock()
    fake_app.run_polling_blocking = MagicMock(side_effect=lambda: __import__("time").sleep(0.5))

    async def fake_start():
        await asyncio.sleep(60)

    fake_orchestrator = SimpleNamespace(start=AsyncMock(side_effect=fake_start), stop=MagicMock())

    def install(loop, event):
        loop.call_later(0.1, event.set)

    monkeypatch.setattr("services.telegram_runtime.TelegramBotApp", lambda: fake_app)
    monkeypatch.setattr("app_runner.OrchestratorLoop", lambda cfg: fake_orchestrator)

    rc = asyncio.run(app_runner.main(stop_event=stop_event, signal_handler_installer=install, shutdown_timeout=0.2))
    assert rc == 0
    fake_orchestrator.stop.assert_called_once()
    fake_app.bot.stop_polling.assert_called_once()


def test_telegram_bot_app_run_polling_blocking_starts_alert_worker(monkeypatch):
    app = TelegramBotApp.__new__(TelegramBotApp)
    app.allowed_chat_ids = [123]
    app.alert_worker = MagicMock()
    app.alert_worker.is_alive.return_value = False
    app.bot = MagicMock()

    monkeypatch.setattr("services.telegram_runtime.config.AUTO_EDGE_ALERTS_ENABLED", True, raising=False)

    app.run_polling_blocking()

    app.alert_worker.start.assert_called_once()
    app.bot.infinity_polling.assert_called_once_with(skip_pending=True, timeout=25, long_polling_timeout=25)


def test_deprecated_runners_print_warning(monkeypatch):
    class _FakeApp:
        def run(self):
            return None

    monkeypatch.setattr("services.telegram_runtime.TelegramBotApp", lambda: _FakeApp())
    monkeypatch.setattr("orchestrator_runner.OrchestratorLoop", lambda cfg: SimpleNamespace(start=AsyncMock(), stop=MagicMock()))

    with warnings.catch_warnings(record=True) as bot_caught:
        warnings.simplefilter("always")
        assert telegram_bot_runner.main() == 0

    with warnings.catch_warnings(record=True) as orch_caught:
        warnings.simplefilter("always")
        asyncio.run(orchestrator_runner.main())

    assert any(item.category is DeprecationWarning for item in bot_caught)
    assert any(item.category is DeprecationWarning for item in orch_caught)
