"""Тесты исследовательских инструментов (ревью GPT 13.10): сеть запрещена — Binance/GinArea только поддельные."""
from __future__ import annotations

import socket

import pytest


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def deny(*args, **kwargs):
        raise RuntimeError("research_tools tests: сеть запрещена")

    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
