from __future__ import annotations

import time
from datetime import datetime, timezone

from .bots import _assert_not_production
from .client import GinAreaClient
from .exceptions import GinAreaAPIError, GinAreaTestFailedError, GinAreaTestTimeoutError
from .models import BotStatus, Test

# 2026-08-19: досчитанный бэктест GinArea приходит со статусом STOPPED(12),
# а не FINISHED(14) — так помечены и готовые тесты в UI («Stopped»), и
# единственный тест на стенде 5276061629. Без STOPPED в списке
# wait_for_finished крутил опрос до таймаута на УЖЕ ГОТОВОМ тесте: один
# такой прогон впустую сжёг 25 минут.
TERMINAL_STATUSES = {
    BotStatus.FINISHED,
    BotStatus.FAILED,
    BotStatus.TP_STOPPED,
    BotStatus.SL_STOPPED,
    BotStatus.STOPPED,
}


def _to_iso(dt: datetime) -> str:
    """Return an ISO 8601 UTC string ending with Z."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class BacktestAPI:
    def __init__(self, client: GinAreaClient) -> None:
        self.client = client

    def create_test(self, bot_id: int, date_from: datetime, date_to: datetime) -> Test:
        _assert_not_production(bot_id)
        data = self.client.request(
            "POST",
            f"/bots/{bot_id}/tests",
            json={"dateFrom": _to_iso(date_from), "dateTo": _to_iso(date_to)},
        )
        return Test.from_dict(data)  # type: ignore[arg-type]

    def list_tests(
        self,
        bot_id: int,
        *,
        interval: str = "1h",
        max_count: int = 150,
    ) -> list[Test]:
        data = self.client.request(
            "GET",
            f"/bots/{bot_id}/tests",
            params={"interval": interval, "maxCount": str(max_count)},
        )
        return [Test.from_dict(item) for item in data]  # type: ignore[arg-type]

    def test_range(self, bot_id: int) -> object:
        """Доступный диапазон дат для бэктеста (вызов веб-приложения GinArea)."""
        return self.client.request("GET", f"/bots/{bot_id}/tests/range")

    def delete_test(self, bot_id: int, test_id: int) -> object:
        """Удалить тест. Путь — из веб-приложения GinArea (chunk с TestsService:
        delete(e) → DELETE /bots/tests/{id}), не подобран перебором.

        GinArea держит ОДИН тест на бота (01.10.2026: «limit on the number of
        tests for the bot»), поэтому серия бэктестов на клоне = прогон → запись
        результата → удаление. Проверяем, что тест принадлежит этому боту, и что
        бот не боевой.
        """
        _assert_not_production(bot_id)
        if not any(t.id == test_id for t in self.list_tests(bot_id)):
            raise GinAreaAPIError(f"тест {test_id} не принадлежит боту {bot_id}")
        return self.client.request("DELETE", f"/bots/tests/{test_id}")

    def get_test(self, bot_id: int, test_id: int) -> Test:
        for test in self.list_tests(bot_id):
            if test.id == test_id:
                return test
        raise GinAreaAPIError(f"Test {test_id} not found for bot {bot_id}")

    def wait_for_finished(
        self,
        bot_id: int,
        test_id: int,
        *,
        poll_interval: float = 5.0,
        timeout: float = 1800.0,
    ) -> Test:
        started = time.monotonic()
        while True:
            test = self.get_test(bot_id, test_id)
            if test.status == BotStatus.FINISHED:
                return test
            if test.status == BotStatus.FAILED:
                raise GinAreaTestFailedError(
                    test_id,
                    test.errorCode or -1,
                    f"Test {test_id} failed with errorCode={test.errorCode}",
                )
            if test.status in (BotStatus.TP_STOPPED, BotStatus.SL_STOPPED,
                               BotStatus.STOPPED):
                return test
            if (time.monotonic() - started) > timeout:
                raise GinAreaTestTimeoutError(
                    f"Test {test_id} did not finish within {timeout}s (last status={test.status.name})"
                )
            time.sleep(poll_interval)

    def run_test(
        self,
        bot_id: int,
        date_from: datetime,
        date_to: datetime,
        *,
        poll_interval: float = 5.0,
        timeout: float = 1800.0,
    ) -> Test:
        created = self.create_test(bot_id, date_from, date_to)
        return self.wait_for_finished(
            bot_id,
            created.id,
            poll_interval=poll_interval,
            timeout=timeout,
        )
