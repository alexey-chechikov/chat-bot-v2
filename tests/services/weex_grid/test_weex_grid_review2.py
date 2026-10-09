"""Сценарии из разбора GPT по коду 65eae029 (10.10, вечер): целостность конфига/учёта, сироты-тейки,
частичное внешнее закрытие, полный поиск потерянного ордера, резерв частичного входа, частичный
тейк пока висит, поздняя комиссия, слоты по заявкам, потолок по окончательной цене."""
import json

import pytest

from services.weex_grid import engine as eg
from services.weex_grid import loop as lp
from tests.services.weex_grid.test_weex_grid_engine import Px, bot_open, make


# ---------- P1-1: битый конфиг не превращается в конфиг BTC
def test_broken_config_raises_instead_of_btc_default(tmp_path):
    p = tmp_path / "xau_cfg.json"
    p.write_text('{"symbol": "XAUUSDT", "enabled": tru', encoding="utf-8")
    with pytest.raises(eg.ConfigError):
        eg.load_config(p, eg.TEMPLATES["XAU"])


def test_config_symbol_must_match_template(tmp_path):
    p = tmp_path / "xau_cfg.json"
    p.write_text(json.dumps({"symbol": "BTCUSDT"}), encoding="utf-8")
    with pytest.raises(eg.ConfigError):
        eg.load_config(p, eg.TEMPLATES["XAU"])


def test_runner_halts_broken_grid_without_touching_others(tmp_path, monkeypatch):
    """Битый конфиг XAU + живой учёт XAU с лотом: ни одного ордера на BTC от имени золота."""
    px = Px()
    ex = eg.DryExchange(px)
    btc_cfg = tmp_path / "btc.json"
    btc_cfg.write_text(json.dumps({**eg.DEFAULT, "enabled": True, "dry_run": False, "sides": ["LONG"]}))
    monkeypatch.setattr(eg, "CONFIG", btc_cfg)
    monkeypatch.setattr(eg, "STATE", tmp_path / "btc_st.json")
    monkeypatch.setattr(eg, "JOURNAL", tmp_path / "btc_j.jsonl")
    monkeypatch.setattr(eg.load_config, "__defaults__", (btc_cfg, None))
    monkeypatch.setattr(eg.save_config, "__defaults__", (btc_cfg,))

    def gf(name="BTC"):
        if name == "BTC":
            return btc_cfg, tmp_path / "btc_st.json", tmp_path / "btc_j.jsonl"
        return tmp_path / f"{name}.json", tmp_path / f"{name}_st.json", tmp_path / f"{name}_j.jsonl"
    monkeypatch.setattr(eg, "grid_files", gf)
    (tmp_path / "XAU.json").write_text('{"symbol": "XAUUSDT", "enabled": tr', encoding="utf-8")
    (tmp_path / "XAU_st.json").write_text(json.dumps({"symbol": "XAUUSDT", "LONG": {**eg.new_side_state(), "lots": [
        {"entry": 4200.0, "qty": "0.023", "tp": 4212.6, "tp_order": None, "t": 1.0}]}}))
    monkeypatch.setattr(eg, "GRIDS", ("BTC", "XAU"))
    sent = []
    r = lp.Runner(send_fn=sent.append)
    monkeypatch.setattr(r, "_client", lambda: ex)
    r.tick()                                         # XAU встаёт, BTC работает
    assert not any(o["reduceOnly"] for o in ex.orders.values())   # никакого reduceOnly от «золотого» лота
    assert len(bot_open(ex)) == 1                    # только вход BTC
    assert sent and "XAU" in sent[0] and "остановлена" in sent[0]


# ---------- P1-3: битый учёт не запускает пустой бот
def test_corrupt_state_halts_and_keeps_takes(tmp_path):
    px = Px()
    g, ex = make(tmp_path, px, sides=["LONG"])
    g.tick()
    px.mid = 99_790.0
    g.tick()
    assert [o for o in bot_open(ex) if o["reduceOnly"]]
    (tmp_path / "st.json").write_text('{"LONG": {"lots": [', encoding="utf-8")     # оборванная запись
    with pytest.raises(eg.StateCorrupt):
        eg.Grid(ex, g.cfg, state_path=tmp_path / "st.json", journal_path=tmp_path / "j.jsonl", now_fn=g.now)
    assert [o for o in bot_open(ex) if o["reduceOnly"]]                               # тейк не снят


def test_state_of_other_symbol_rejected(tmp_path):
    (tmp_path / "s.json").write_text(json.dumps({"symbol": "XAUUSDT"}))
    cfg = {**eg.DEFAULT, "enabled": True}
    with pytest.raises(eg.StateCorrupt):
        eg.Grid(eg.DryExchange(Px()), cfg, state_path=tmp_path / "s.json", journal_path=tmp_path / "j.jsonl")


def test_save_is_atomic_and_complete(tmp_path):
    g, ex = make(tmp_path, Px(), sides=["LONG"])
    g.tick()
    json.loads((tmp_path / "st.json").read_text())                                  # читается целиком
    assert not list(tmp_path.glob(".st.json.*.tmp"))


# ---------- P1-4: частичное внешнее закрытие снимает только дефицит
def test_partial_external_close_keeps_remainder(tmp_path):
    px = Px()
    g, ex = make(tmp_path, px, sides=["LONG"], order_qty="0.0012")
    g.tick()
    px.mid = 99_790.0
    g.tick()
    g.cfg["enabled"] = False
    g.tick()
    lot = g.st["LONG"]["lots"][0]
    ex.orders[lot["tp_order"]["id"]]["status"] = "CANCELED"
    for o in ex.orders.values():                      # вручную закрыли 0.0004 из 0.0012
        if not o["reduceOnly"] and o["status"] == "FILLED":
            o["executedQty"] = "0.0008"
    real = ex.place_limit
    calls = {"n": 0}

    def place(symbol, side, ps, qty, price, cid, reduce_only=False, post_only=True):
        if reduce_only and calls["n"] == 0:           # первая постановка тейка отклонена
            calls["n"] += 1
            return {"success": False, "orderId": None}
        return real(symbol, side, ps, qty, price, cid, reduce_only, post_only)
    ex.place_limit = place
    g.tick()
    lots = g.st["LONG"]["lots"]
    assert len(lots) == 1 and lots[0]["qty"] == "0.0008"
    g.tick()                                          # остаток получает тейк
    takes = [o for o in bot_open(ex) if o["reduceOnly"]]
    assert takes and takes[0]["origQty"] == "0.0008"


# ---------- P1-5: потерянный ордер ищется во всей истории, а не в первых 100
def test_pending_found_beyond_first_history_page(tmp_path):
    px = Px()
    g, ex = make(tmp_path, px, sides=["LONG"])
    real = ex.place_limit

    def place(*a, **k):
        r = real(*a, **k)
        o = ex.orders[r["orderId"]]
        o.update(status="FILLED", executedQty=o["origQty"], avgPrice=o["price"])
        for i in range(150):                          # 150 более новых ордеров символа
            ex.orders[f"m{i}"] = {"clientOrderId": f"manual{i}", "side": "BUY", "positionSide": "LONG",
                                  "price": "1", "origQty": "0.001", "status": "CANCELED", "executedQty": "0",
                                  "avgPrice": "0", "reduceOnly": False}
        ex.place_limit = real
        raise TimeoutError("read timeout")
    ex.place_limit = place
    g.tick()
    g.tick()
    lots = g.st["LONG"]["lots"]
    assert len(lots) == 1 and not g.st["LONG"]["pending"]
    entries = [o for o in ex.orders.values() if o["clientOrderId"].startswith("b7g") and not o["reduceOnly"]
               and o["status"] in ("NEW", "FILLED")]
    assert len(entries) == 2                           # найденный (исполнен) + следующий уровень, не дубль


# ---------- P1-6: потерянная привязка тейка — исполненное восстанавливается
def test_orphan_take_adopted_and_partial_fill_recorded(tmp_path):
    px = Px()
    g, ex = make(tmp_path, px, sides=["LONG"], order_qty="0.0012")
    g.tick()
    px.mid = 99_790.0
    g.tick()
    lot = g.st["LONG"]["lots"][0]
    tp = ex.orders[lot["tp_order"]["id"]]
    tp.update(executedQty="0.0004", avgPrice=tp["price"])   # тейк исполнен на треть
    lot["tp_order"] = None                                   # учёт потерял привязку
    g.save()
    g.tick()
    lots = g.st["LONG"]["lots"]
    assert len(lots) == 1 and lots[0]["qty"] == "0.0008"
    assert g.st["LONG"]["realized"] == pytest.approx(0.0004 * (float(tp["price"]) - lot["entry"]), rel=1e-6)


# ---------- P1-7: частично исполненный вход резервирует свой реальный остаток
def test_partial_entry_reserve_uses_its_remaining(tmp_path):
    px = Px(80_000.0)
    g, ex = make(tmp_path, px, sides=["LONG"], order_qty="0.0012", max_notional_usd=200.0)
    g.tick()
    oid = g.st["LONG"]["entry"]["id"]
    ex.orders[oid].update(executedQty="0.0002", avgPrice=ex.orders[oid]["price"])
    g.tick()
    g.cfg.update(order_qty="0.0001", max_notional_usd=50.0)     # уменьшили размер и потолок
    g.tick()
    assert ex.orders[oid]["status"] == "CANCELED"               # остаток 0.001 × $79 840 > $50 — снят


# ---------- P2: частичное исполнение висящего тейка видно сразу
def test_live_partial_take_reflected(tmp_path):
    px = Px()
    g, ex = make(tmp_path, px, sides=["LONG"], order_qty="0.0012")
    g.tick()
    px.mid = 99_790.0
    g.tick()
    lot = g.st["LONG"]["lots"][0]
    tp = ex.orders[lot["tp_order"]["id"]]
    tp.update(executedQty="0.0004", avgPrice=tp["price"])       # висит, исполнен на треть
    g.tick()
    assert g.st["LONG"]["lots"][0]["qty"] == "0.0008"
    assert tp["status"] == "NEW"                                 # не снят как «не того объёма»
    g.tick()
    assert g.st["LONG"]["lots"][0]["qty"] == "0.0008"            # повтор снимка — без изменений


# ---------- P2: поздняя комиссия дописывается
def test_late_commission_settled(tmp_path):
    px = Px()
    g, ex = make(tmp_path, px, sides=["LONG"])
    g.tick()
    real_trades = ex.user_trades
    ex.user_trades = lambda symbol, order_id=None: []            # в момент исполнения сделок ещё нет
    px.mid = 99_790.0
    g.tick()
    assert g.st["LONG"]["fees"] == 0
    ex.user_trades = real_trades
    for _ in range(8):                                           # через минуту — досверка
        g.tick()
    assert g.st["LONG"]["fees"] == pytest.approx(0.0001 * 99_800 * 0.00016, rel=1e-6)


# ---------- идея GPT №1: слоты по заявкам, а не по кускам исполнения
def test_slots_count_parent_orders_not_fragments(tmp_path):
    g, ex = make(tmp_path, Px(), sides=["LONG"], max_lots_per_side=2, max_notional_usd=1e6)
    s = g.st["LONG"]
    s["lots"] = [{"entry": 100_000.0, "qty": "0.0001", "tp": 100_300.0, "tp_order": None, "t": float(i),
                  "parent": "A"} for i in range(5)]
    ok, _ = g.may_add("LONG", 99_800.0, 100_000.0)
    assert ok                                                     # 5 кусков одной заявки = 1 слот из 2


# ---------- P2: потолок по окончательной цене после сдвига к стакану
def test_cap_checked_at_final_price(tmp_path):
    px = Px(100_000.0)
    g, ex = make(tmp_path, px, sides=["SHORT"], order_qty="0.01", max_notional_usd=999.99)
    # уровень шорта 99 198 (ниже bid) → $991.98 проходит потолок, но продажа сдвигается к ask
    # 100 000.05 → $1 000.0005 > $999.99: по окончательной цене вход ставить нельзя
    g.st["SHORT"]["ref"] = 99_000.0
    g.tick()
    assert not [o for o in bot_open(ex) if not o["reduceOnly"]]
    assert "потолок" in g.st["SHORT"]["blocked"]
