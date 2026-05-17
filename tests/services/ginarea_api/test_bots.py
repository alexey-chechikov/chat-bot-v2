from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.ginarea_api.bots import (
    _assert_not_production,
    _load_production_bot_ids,
)
from services.ginarea_api.client import GinAreaClient
from services.ginarea_api.exceptions import GinAreaProductionBotGuardError
from services.ginarea_api.models import DefaultGridParams
from services.ginarea_api.bots import BotsAPI


def test_list_bots_parses_array_correctly(httpx_mock, load_fixture, mock_client):
    httpx_mock.add_response(json=load_fixture("bots_response.json"))
    bots = BotsAPI(mock_client).list_bots()
    assert len(bots) == 2
    assert bots[0].name == "Template Short"


def test_get_bot_parses_with_nested_params_and_stat(httpx_mock, load_fixture, mock_client):
    httpx_mock.add_response(json=load_fixture("bot_response.json"))
    bot = BotsAPI(mock_client).get_bot(6161205316)
    assert bot.params.hedge is False
    assert bot.stat is not None
    assert bot.stat.extension.avgPS == pytest.approx(-12.1)


def test_get_params_parses_full_default_grid_params(httpx_mock, load_fixture, mock_client):
    httpx_mock.add_response(json=load_fixture("params_response.json"))
    params = BotsAPI(mock_client).get_params(6161205316)
    assert params.gs == pytest.approx(0.5)
    assert params.hedge is False
    assert params.leverage == 3
    assert params.gap.maxS == pytest.approx(1.5)


def test_resume_bot_calls_start_endpoint_with_empty_body(httpx_mock, mock_client):
    """2026-05-17: captured from DevTools — PUT /api/bots/{id}/start with {}."""
    httpx_mock.add_response(method="PUT", json={"ok": True})
    result = BotsAPI(mock_client).resume_bot(4525648417)
    assert result == {"ok": True}
    sent = httpx_mock.get_request()
    assert sent.method == "PUT"
    assert str(sent.url).endswith("/bots/4525648417/start")
    assert sent.read() == b"{}"


def test_pause_bot_calls_stop_endpoint_with_empty_body(httpx_mock, mock_client):
    """2026-05-17: captured from DevTools — PUT /api/bots/{id}/stop with {}."""
    httpx_mock.add_response(method="PUT", json={"ok": True})
    result = BotsAPI(mock_client).pause_bot(4525648417)
    assert result == {"ok": True}
    sent = httpx_mock.get_request()
    assert sent.method == "PUT"
    assert str(sent.url).endswith("/bots/4525648417/stop")
    assert sent.read() == b"{}"


def test_get_stat_parses_with_extension(httpx_mock, load_fixture, mock_client):
    httpx_mock.add_response(json=load_fixture("stat_response.json"))
    stat = BotsAPI(mock_client).get_stat(6161205316)
    assert stat.extension.posS == pytest.approx(-0.23)
    assert stat.extension.from_ == pytest.approx(72000.0)


def test_get_stat_history_returns_list(httpx_mock, load_fixture, mock_client):
    httpx_mock.add_response(json=load_fixture("stat_history_response.json"))
    history = BotsAPI(mock_client).get_stat_history(6161205316)
    assert len(history) == 3


def test_get_stat_history_with_custom_interval_and_count(httpx_mock, load_fixture, mock_client):
    httpx_mock.add_response(json=load_fixture("stat_history_response.json"))
    BotsAPI(mock_client).get_stat_history(6161205316, interval="15m", max_count=5)
    request = httpx_mock.get_requests()[0]
    assert request.url.params["interval"] == "15m"
    assert request.url.params["maxCount"] == "5"


def test_set_params_blocks_on_production_bot_id_raises(monkeypatch, mock_client, sample_default_grid_params):
    monkeypatch.setattr("services.ginarea_api.bots._load_production_bot_ids", lambda: frozenset({6161205316}))
    with pytest.raises(GinAreaProductionBotGuardError):
        _assert_not_production(6161205316)


def test_set_params_succeeds_on_template_bot_id(httpx_mock, monkeypatch, load_fixture, mock_client):
    monkeypatch.setattr("services.ginarea_api.bots._load_production_bot_ids", lambda: frozenset())
    httpx_mock.add_response(json=load_fixture("params_response.json"))
    params = DefaultGridParams.from_dict(load_fixture("params_response.json"))
    result = BotsAPI(mock_client).set_params(6161205316, params)
    assert result == params


def test_set_params_round_trip_preserves_dataclass(httpx_mock, monkeypatch, load_fixture, mock_client):
    monkeypatch.setattr("services.ginarea_api.bots._load_production_bot_ids", lambda: frozenset())
    payload = load_fixture("params_response.json")
    params = DefaultGridParams.from_dict(payload)
    httpx_mock.add_response(json=payload)
    result = BotsAPI(mock_client).set_params(6161205316, params)
    assert DefaultGridParams.from_dict(result.to_dict()) == result


def test_load_production_bot_ids_returns_frozenset_when_file_exists(tmp_path, monkeypatch):
    path = tmp_path / "portfolio.json"
    path.write_text(json.dumps({"bots": [{"id": 1, "active": True}, {"id": 2, "active": False}]}), encoding="utf-8")
    monkeypatch.setattr("services.ginarea_api.bots._PORTFOLIO_PATH", path)
    monkeypatch.setattr("services.ginarea_api.bots._PRODUCTION_LOADED", False)
    monkeypatch.setattr("services.ginarea_api.bots.PRODUCTION_BOT_IDS", frozenset())
    assert _load_production_bot_ids() == frozenset({1})


def test_load_production_bot_ids_returns_empty_when_file_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("services.ginarea_api.bots._PORTFOLIO_PATH", tmp_path / "missing.json")
    monkeypatch.setattr("services.ginarea_api.bots._PRODUCTION_LOADED", False)
    monkeypatch.setattr("services.ginarea_api.bots.PRODUCTION_BOT_IDS", frozenset())
    assert _load_production_bot_ids() == frozenset()
