"""/weex set: разбор параметров, пересчёт долларов в BTC, границы."""
import json

from services.weex_grid import engine as eg
from services.weex_grid import loop as lp


def setup(tmp_path, monkeypatch):
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({**eg.DEFAULT, "enabled": True, "dry_run": False}), encoding="utf-8")
    monkeypatch.setattr(eg, "CONFIG", cfg)
    monkeypatch.setattr(eg.load_config, "__defaults__", (cfg, None))
    monkeypatch.setattr(eg.save_config, "__defaults__", (cfg,))
    return cfg


def test_target_and_usd(tmp_path, monkeypatch):
    cfg = setup(tmp_path, monkeypatch)
    out = lp.set_params("цель 0,21 ордер 100", lambda: 83_000.0)
    c = json.loads(cfg.read_text())
    assert c["target_pct"] == 0.21 and c["order_qty"] == "0.0012"
    assert "до 10 ордеров" in out and c["dry_run"] is False and c["enabled"] is True


def test_stops_off_and_cap(tmp_path, monkeypatch):
    cfg = setup(tmp_path, monkeypatch)
    out = lp.set_params("стоп 0 стресс 0 потолок 4000 ордер 100", lambda: 83_000.0)
    c = json.loads(cfg.read_text())
    assert c["daily_loss_stop_usd"] == 0 and c["stress_budget_frac"] == 0 and c["max_notional_usd"] == 4000
    assert "стоп дня ВЫКЛ" in out and "стресс-бюджет ВЫКЛ" in out and "до 40 ордеров" in out


def test_engine_respects_disabled_stops(tmp_path):
    import pytest  # noqa: F401
    from tests.services.weex_grid.test_weex_grid_engine import Px, make
    px = Px()
    g, ex = make(tmp_path, px, sides=["LONG"], daily_loss_stop_usd=0, stress_budget_frac=0, order_qty="0.01",
                 max_notional_usd=1e6)
    ex.balance = 50.0
    g.tick()
    for m in (99_790, 99_590, 99_390, 95_000):
        px.mid = m
        g.tick()
    assert not g.st["halted"] and g.st["LONG"]["entry"] is not None     # стопов нет — работает лимитами ордеров


def test_limits_and_unknown(tmp_path, monkeypatch):
    cfg = setup(tmp_path, monkeypatch)
    assert "вне допустимого" in lp.set_params("ордер 5000", lambda: 83_000.0)     # 0.06 BTC > 0.01
    assert "Не знаю" in lp.set_params("плечо 50", lambda: 83_000.0)
    assert json.loads(cfg.read_text())["order_qty"] == eg.DEFAULT["order_qty"]
