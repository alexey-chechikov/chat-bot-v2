"""Находки GPT по коду 3b33428 (docs/WEEX_GPT_STATE_ANSWERS_2026-10-11.md): размер тренда до настоящего стопа,
частичный выход тренда (свой и внешний), общий потолок (стоящие входы, битый учёт, одно место — один раз)."""
import json

import pytest

from services.weex_grid import engine as eg
from services.weex_grid import portfolio
from services.weex_trend import engine as te
from services.weex_trend import loop as tl
from tests.services.weex_grid.test_weex_grid_engine import Px, bot_open, make
from tests.services.weex_trend.test_weex_trend import setup, tick


# ---------- №8: риск $50 — до аварийного стопа на бирже с комиссией, а не до Chandelier
def test_trend_risk_is_to_exchange_stop(tmp_path):
    clock, px, ex, make_t, signal = setup(tmp_path, risk_usd=50.0, max_notional_usd=100_000.0)
    signal("SHORT", stop=2600.0)
    tick(make_t, clock, 2)
    ep = json.loads((tmp_path / "st.json").read_text())["episode"]
    q, entry = float(ep["qty"]), ep["entry_px"]
    hard = float(ep["stop"]["trigger"])
    assert hard == pytest.approx(2600 * 1.015, abs=0.02)
    loss = q * (hard - entry) + q * (entry + hard) * 0.00048     # стоп сработал: цена + тейкер обеих ног
    assert loss <= 50.0 + 1e-6                                   # было 0.5 ETH → $69.5 + комиссии


# ---------- №9: свой выход исполнен частично — остаток в учёте и под стопом
def test_trend_partial_exit_keeps_rest_protected(tmp_path):
    clock, px, ex, make_t, signal = setup(tmp_path)
    signal("SHORT", stop=2600.0)
    tick(make_t, clock, 2)
    q = float(json.loads((tmp_path / "st.json").read_text())["episode"]["qty"])
    real = ex.place_market

    def partial(symbol, side, position_side, qty, cid, reduce_only=False):
        if reduce_only:
            qty = f"{float(qty) * 0.4:.3f}"                      # биржа закрыла только 40%
        return real(symbol, side, position_side, qty, cid, reduce_only=reduce_only)
    ex.place_market = partial
    signal(None)                                                 # служба сняла тренд → основной выход
    tick(make_t, clock, 2)                                       # отправка выхода, затем разбор исполнения
    st = json.loads((tmp_path / "st.json").read_text())
    ep = st["episode"]
    left = round(q - round(q * 0.4, 3), 3)
    assert ep is not None and float(ep["qty"]) == pytest.approx(left)      # эпизод не закрыт целиком
    assert ex.pos["SHORT"] == pytest.approx(left)
    stops = ex.open_algo_orders("ETHUSDT")
    assert len(stops) == 1 and float(stops[0]["quantity"]) == pytest.approx(left)   # остаток под стопом
    assert st["n_trades"] == 0
    ex.place_market = real
    tick(make_t, clock, 2)                                       # следующий проход закрывает остаток
    st = json.loads((tmp_path / "st.json").read_text())
    assert st["episode"] is None and ex.pos["SHORT"] == pytest.approx(0.0) and st["n_trades"] == 1
    assert not ex.open_algo_orders("ETHUSDT")


# ---------- №9: позицию уменьшили не ботом (вручную) — эпизод живёт остатком
def test_trend_partial_outside_reduction_keeps_episode(tmp_path):
    clock, px, ex, make_t, signal = setup(tmp_path)
    signal("LONG", stop=2400.0)
    tick(make_t, clock, 2)
    q = float(json.loads((tmp_path / "st.json").read_text())["episode"]["qty"])
    ex.pos["LONG"] = round(q * 0.6, 3)                           # 40% закрыто руками
    tick(make_t, clock, 1)
    ep = json.loads((tmp_path / "st.json").read_text())["episode"]
    assert ep is not None and float(ep["qty"]) == pytest.approx(round(q * 0.6, 3))
    stops = ex.open_algo_orders("ETHUSDT")
    assert len(stops) == 1 and float(stops[0]["quantity"]) == pytest.approx(round(q * 0.6, 3))


# ---------- №20: занято — и стоящие входы, неясные постановки, сироты-входы
def test_used_counts_entries_pending_strays(tmp_path):
    gs = tmp_path / "g.json"
    gs.write_text(json.dumps({
        "LONG": {"lots": [{"qty": "0.01", "entry": 80000.0}],
                 "entry": {"id": "1", "price": 79000.0, "qty": "0.01", "filled": 0.004},
                 "pending": None, "strays": [{"kind": "e", "price": 78000.0, "origQty": "0.01", "executedQty": "0"},
                                             {"kind": "t", "price": 81000.0, "origQty": "0.01"}]},
        "SHORT": {"lots": [], "entry": None,
                  "pending": {"kind": "e", "price": 82000.0, "qty": "0.01"}, "strays": []}}))
    assert portfolio.used_usd([gs], []) == pytest.approx(800 + 0.006 * 79000 + 780 + 820)


def test_unreadable_state_blocks_not_zero(tmp_path):
    gs = tmp_path / "g.json"
    gs.write_text("{битый")
    with pytest.raises(ValueError):
        portfolio.used_usd([gs], [])


# ---------- №20: в одном проходе сетки одно свободное место не раздаётся двум сторонам
def test_grid_room_not_reused_within_tick(tmp_path):
    g, ex = make(tmp_path, Px(), sides=["LONG", "SHORT"], portfolio_free_usd=15.0)   # ордер ~$10 на сторону
    g.tick()
    assert len([o for o in bot_open(ex) if not o["reduceOnly"]]) == 1                # было 2 → $20 при $15


def test_grid_standing_entry_kept_with_tight_room(tmp_path):
    """Свой стоящий вход уже входит в «занято» — на следующем проходе он не снимается из-за самого себя."""
    g, ex = make(tmp_path, Px(), sides=["LONG"], portfolio_free_usd=50.0)
    g.tick()
    oid = g.st["LONG"]["entry"]["id"]
    g.cfg["portfolio_free_usd"] = 0.0                            # свободное посчитано уже с этим входом
    g.tick()
    assert g.st["LONG"]["entry"]["id"] == oid and ex.orders[oid]["status"] == "NEW"


# ---------- №20: тренд получает свободное место заново перед каждой монетой
def test_trend_runner_recomputes_room_per_symbol(monkeypatch):
    cfg = {**te.DEFAULT, "enabled": True, "dry_run": False, "symbols": ["ETHUSDT", "XRPUSDT"],
           "per_symbol": {"XRPUSDT": {"qty_step": 10, "price_tick": 0.0001}}}
    monkeypatch.setattr(te, "load_config", lambda: cfg)
    seen, room = [], {"free": 250.0}

    def fake_tick(self, c):
        seen.append(c.get("portfolio_free_usd"))
        room["free"] -= 200.0                                    # первая монета заняла место
    monkeypatch.setattr(tl.TrendRunner, "_tick_symbol", fake_tick)
    tl.TrendRunner(lambda: None).tick(portfolio_free=lambda: room["free"])
    assert seen == [250.0, 50.0]                                 # было 250 обеим
