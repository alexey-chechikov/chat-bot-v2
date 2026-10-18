"""Тесты research/trend_recheck (протокол docs/TREND_4H_RECHECK_PROTOCOL_2026-10-15.md): сеть запрещена, данные —
только синтетические минуты."""
from __future__ import annotations

import socket

import pytest


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def deny(*args, **kwargs):
        raise RuntimeError("research_trend tests: сеть запрещена")

    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
