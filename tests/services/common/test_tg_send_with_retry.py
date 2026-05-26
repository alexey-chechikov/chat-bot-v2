"""Tests for the shared TG retry helper."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from services.common.tg_send_with_retry import (
    DEFAULT_BACKOFF_SEC,
    make_send_fn,
    send_with_retry,
)


class _FlakyBot:
    """Mock bot that fails the first N times then succeeds."""

    def __init__(self, fail_n: int = 0, exc_cls: type = ConnectionError):
        self.fail_n = fail_n
        self.exc_cls = exc_cls
        self.calls: list[tuple] = []

    def send_message(self, chat_id, text, reply_markup=None):
        self.calls.append((chat_id, text, reply_markup))
        if len(self.calls) <= self.fail_n:
            raise self.exc_cls("boom")
        return {"ok": True}


def test_send_with_retry_success_first_attempt() -> None:
    bot = _FlakyBot(fail_n=0)
    result = send_with_retry(bot, [123], "hello", backoff_sec=0)
    assert result == {123: True}
    assert len(bot.calls) == 1


def test_send_with_retry_succeeds_on_second_attempt() -> None:
    bot = _FlakyBot(fail_n=1)
    result = send_with_retry(bot, [123], "hello", backoff_sec=0)
    assert result == {123: True}
    assert len(bot.calls) == 2


def test_send_with_retry_gives_up_after_max_retries() -> None:
    bot = _FlakyBot(fail_n=10)
    result = send_with_retry(bot, [123], "hello", retries=3, backoff_sec=0)
    assert result == {123: False}
    assert len(bot.calls) == 3  # 3 attempts, all failed


def test_send_with_retry_handles_multiple_chats_independently() -> None:
    bot = MagicMock()
    calls = []

    def send(cid, text, reply_markup=None):
        calls.append(cid)
        # chat 999 always fails, others succeed
        if cid == 999:
            raise ConnectionError("nope")

    bot.send_message = send
    result = send_with_retry(bot, [111, 999, 222], "x", retries=2, backoff_sec=0)
    assert result[111] is True
    assert result[222] is True
    assert result[999] is False
    assert calls.count(111) == 1
    assert calls.count(222) == 1
    assert calls.count(999) == 2  # retried


def test_send_with_retry_never_raises_even_on_attribute_error() -> None:
    """If bot doesn't have send_message, we log and return False — no crash."""
    class BrokenBot:
        pass

    result = send_with_retry(BrokenBot(), [42], "x", retries=2, backoff_sec=0)
    assert result == {42: False}


def test_send_with_retry_no_chats_returns_empty() -> None:
    bot = _FlakyBot()
    result = send_with_retry(bot, [], "x", backoff_sec=0)
    assert result == {}
    assert bot.calls == []


def test_send_with_retry_none_bot_no_op() -> None:
    # If bot is None (e.g. telegram disabled), the helper is a no-op.
    result = send_with_retry(None, [1, 2], "x", backoff_sec=0)
    assert all(v is False for v in result.values())


def test_send_with_retry_forwards_reply_markup() -> None:
    bot = _FlakyBot(fail_n=0)
    rm = {"inline_keyboard": [[{"text": "ok", "callback_data": "yes"}]]}
    send_with_retry(bot, [1], "x", reply_markup=rm, backoff_sec=0)
    assert bot.calls[0][2] == rm


def test_make_send_fn_routes_to_all_chats() -> None:
    bot = _FlakyBot(fail_n=0)
    send = make_send_fn(bot, [10, 20], backoff_sec=0)
    send("hi")
    assert {c[0] for c in bot.calls} == {10, 20}


def test_make_send_fn_accepts_meta_kwarg() -> None:
    """channel_router signatures pass meta=… — helper must ignore it."""
    bot = _FlakyBot(fail_n=0)
    send = make_send_fn(bot, [10], backoff_sec=0)
    send("hi", meta={"severity": "critical"})  # must not raise
    assert len(bot.calls) == 1
