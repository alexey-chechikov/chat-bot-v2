"""Проверочные скрипты research/weex в тестах — только с поддельной биржей: сеть запрещена, настоящий WeexClient
не создаётся (на маке живые ключи), кэш режима движка сбрасывается."""
import socket

import pytest

import services.weex_api.client as wc
from research.weex import weex_monitor_common as mc
from services.weex_grid import engine as eg


def _no_network(*a, **k):
    raise RuntimeError("сеть в тестах research_weex запрещена")


class _NoRealClient:
    def __init__(self, *a, **k):
        raise AssertionError("настоящий WeexClient в тесте — подставь FakeClient")


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", _no_network)
    monkeypatch.setattr(socket, "create_connection", _no_network)
    monkeypatch.setattr(wc, "WeexClient", _NoRealClient)
    monkeypatch.setattr(eg, "_REGIME_CACHE", {})
    monkeypatch.setattr(eg, "_fetch_daily", _no_network)
    monkeypatch.setattr(mc, "PACE_SEC", 0.0)                # пауза между запросами — только для настоящей биржи
