"""Несколько сеток (BTC + ETH): отдельные файлы, команды по имени, ETH-шорт на имитаторе."""
import json

import pytest

from services.weex_grid import engine as eg
from services.weex_grid import loop as lp


@pytest.fixture
def files(tmp_path, monkeypatch):
    btc = tmp_path / "btc_cfg.json"
    btc.write_text(json.dumps({**eg.DEFAULT, "enabled": True, "dry_run": False, "order_qty": "0.0012"}),
                   encoding="utf-8")
    monkeypatch.setattr(eg, "CONFIG", btc)
    monkeypatch.setattr(eg, "STATE", tmp_path / "btc_state.json")
    monkeypatch.setattr(eg, "JOURNAL", tmp_path / "btc_journal.jsonl")
    monkeypatch.setattr(eg.load_config, "__defaults__", (btc, None))
    monkeypatch.setattr(eg.save_config, "__defaults__", (btc,))

    def gf(name="BTC"):
        if name == "BTC":
            return btc, tmp_path / "btc_state.json", tmp_path / "btc_journal.jsonl"
        return (tmp_path / f"{name}_cfg.json", tmp_path / f"{name}_state.json", tmp_path / f"{name}_journal.jsonl")
    monkeypatch.setattr(eg, "grid_files", gf)
    return tmp_path


def test_eth_created_off_and_dry(files):
    cfg = lp.grid_config("ETH")
    assert cfg["enabled"] is False and cfg["dry_run"] is True
    assert cfg["symbol"] == "ETHUSDT" and cfg["sides"] == ["SHORT"] and cfg["qty_step"] == 0.001
    assert (files / "ETH_cfg.json").exists()


def test_eth_set_does_not_touch_btc(files):
    out = lp.set_params("ордер 10 шаг 0.4", lambda: 2_600.0, "ETH")
    eth = json.loads((files / "ETH_cfg.json").read_text())
    btc = json.loads((files / "btc_cfg.json").read_text())
    assert eth["order_qty"] == "0.003" and eth["step_pct"] == 0.4      # 10/2600 = 0.00385 → вниз до 0.003
    assert btc["order_qty"] == "0.0012" and btc["step_pct"] == eg.DEFAULT["step_pct"]
    assert "ETHUSDT" in out and "ETH" in out


def test_command_routes_by_name(files):
    assert "ETHUSDT" in lp.command("eth live") and json.loads((files / "ETH_cfg.json").read_text())["dry_run"] is False
    assert json.loads((files / "btc_cfg.json").read_text())["dry_run"] is False      # BTC не тронут
    lp.command("эфир stop")
    assert json.loads((files / "ETH_cfg.json").read_text())["enabled"] is False
    lp.command("stop")                                                             # без имени — BTC, как раньше
    assert json.loads((files / "btc_cfg.json").read_text())["enabled"] is False


def test_gold_grid_off_with_sweep_params(files):
    cfg = lp.grid_config("XAU")
    assert cfg["symbol"] == "XAUUSDT" and cfg["enabled"] is False and cfg["dry_run"] is True
    assert cfg["sides"] == ["LONG", "SHORT"] and cfg["step_pct"] == 0.75 and cfg["target_pct"] == 0.3
    assert "XAUUSDT" in lp.command("золото dry")


def test_eth_qty_limit(files):
    assert "вне допустимого" in lp.set_params("ордер 5000", lambda: 2_600.0, "ETH")   # 1.92 ETH > 0.5


def test_disabled_dry_grid_makes_no_requests(files, monkeypatch):
    r = lp.Runner()
    monkeypatch.setattr(r, "_client", lambda: (_ for _ in ()).throw(AssertionError("запрос к бирже")))
    r.tick_one("ETH")                         # выключена и холостая → ничего не делает


class EthPx:
    def __init__(self, mid=2_600.0):
        self.mid = mid

    def __call__(self):
        return round(self.mid - 0.01, 2), round(self.mid + 0.01, 2)


def test_eth_short_grid_cycle(tmp_path):
    px = EthPx()
    cfg = {**eg.DEFAULT, **eg.TEMPLATES["ETH"], "enabled": True, "dry_run": True, "step_pct": 0.3,
           "target_pct": 0.6, "order_qty": "0.01"}
    ex = eg.DryExchange(px, symbol="ETHUSDT")
    t = {"v": 1_800_000_000.0}

    def now():
        t["v"] += 10
        return t["v"]
    g = eg.Grid(ex, cfg, state_path=tmp_path / "s.json", journal_path=tmp_path / "j.jsonl", now_fn=now)
    g.tick()
    e = g.st["SHORT"]["entry"]
    assert e and e["price"] == pytest.approx(2_607.8, abs=0.02) and g.st["LONG"]["entry"] is None
    px.mid = 2_610.0                          # шорт исполнен
    g.tick()
    lot = g.st["SHORT"]["lots"][0]
    assert lot["tp"] == pytest.approx(2_607.8 * 0.994, abs=0.02)
    assert g.st["SHORT"]["entry"]["price"] == pytest.approx(2_607.8 * 1.003, abs=0.02)
    px.mid = 2_590.0                          # тейк
    g.tick()
    g.tick()
    assert g.st["SHORT"]["n_tps"] == 1 and not g.st["SHORT"]["lots"] and g.st["SHORT"]["realized"] > 0.15
    pos = {p["side"]: p for p in ex.futures_positions()}
    assert pos["SHORT"]["symbol"] == "ETHUSDT"
