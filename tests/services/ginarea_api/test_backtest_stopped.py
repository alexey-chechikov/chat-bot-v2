"""Досчитанный бэктест GinArea приходит со статусом STOPPED, не FINISHED.

2026-08-19: wait_for_finished ждал только FINISHED и крутил опрос до
таймаута на уже готовом тесте — 25 минут впустую. В UI такие тесты
помечены «Stopped», и единственный тест на стенде 5276061629 тоже STOPPED.
"""
from __future__ import annotations

import pytest

from services.ginarea_api.backtest import TERMINAL_STATUSES, BacktestAPI
from services.ginarea_api.exceptions import GinAreaTestFailedError
from services.ginarea_api.models import BotStatus


class _FakeAPI(BacktestAPI):
    def __init__(self, statuses):
        self._statuses = list(statuses)
        self.polls = 0

    def list_tests(self, bot_id, *, interval="1h", max_count=150):
        raise AssertionError("должен вызываться get_test, а не list_tests")

    def get_test(self, bot_id, test_id):
        self.polls += 1
        st = (self._statuses.pop(0) if len(self._statuses) > 1
              else self._statuses[0])

        class T:
            id = test_id
            status = st
            errorCode = None
        return T()


def test_stopped_is_terminal():
    assert BotStatus.STOPPED in TERMINAL_STATUSES


def test_wait_returns_on_stopped_without_spinning():
    api = _FakeAPI([BotStatus.ACTIVE, BotStatus.STOPPED])
    t = api.wait_for_finished(1, 42, poll_interval=0, timeout=5)
    assert t.status == BotStatus.STOPPED
    assert api.polls == 2, "не должен опрашивать дальше готового теста"


def test_finished_still_works():
    api = _FakeAPI([BotStatus.FINISHED])
    assert api.wait_for_finished(1, 42, poll_interval=0,
                                 timeout=5).status == BotStatus.FINISHED


def test_failed_still_raises():
    api = _FakeAPI([BotStatus.FAILED])
    with pytest.raises(GinAreaTestFailedError):
        api.wait_for_finished(1, 42, poll_interval=0, timeout=5)
