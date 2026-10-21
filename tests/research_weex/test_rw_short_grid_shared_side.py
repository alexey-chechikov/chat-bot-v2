"""account_now: шорт-сетка SB сама ведёт BTCUSDT SHORT, переданный оператору основной сеткой BTC (21.10, решение
оператора). Ордера и сделки SB на этой стороне — не нарушение передачи; любая другая сетка там — по-прежнему ПРОБЛЕМА."""
import json
import time

from services.weex_grid import engine as eg
from tests.research_weex.harness import FakeClient, iso, run_script, side_state, trade

NOW = time.time()
HANDOVER = NOW - 2 * 86400
BTC_JOURNAL = [{"ts": iso(NOW - 5 * 86400), "side": "SHORT", "kind": "вход", "order_id": "e0"},
               {"ts": iso(HANDOVER), "side": "SHORT", "kind": "передано оператору", "qty": "1", "avg": 100.0,
                "mark": 100.0, "bag": 0.0, "lots": 1}]


def _st(**kw):
    return {"symbol": "BTCUSDT", "LONG": side_state(), "SHORT": side_state(**kw), "halted": False,
            "last_tick_ok_ts": time.time() - 5}


def setup(tmp_path, monkeypatch, sb_order="sb1"):
    files = {}
    cfgs = {"BTC": {"symbol": "BTCUSDT", "dry_run": False, "enabled": True, "sides": ["LONG"],
                    "release_sides": ["SHORT"]},
            "SB": {**eg.TEMPLATES["SB"], "dry_run": False, "enabled": True},
            "B34": {**eg.TEMPLATES["B34"], "dry_run": True, "enabled": False}}
    for name, cfg in cfgs.items():
        cp, sp, jp = (tmp_path / f"{name}_cfg.json", tmp_path / f"{name}_state.json", tmp_path / f"{name}_j.jsonl")
        cp.write_text(json.dumps(cfg), encoding="utf-8")
        st = _st() if name != "SB" else _st(lots=[{"entry": 100.0, "qty": "1", "tp": 98.6, "tp_order": None,
                                                     "t": 1.0, "parent": sb_order}])
        sp.write_text(json.dumps(st), encoding="utf-8")
        jr = BTC_JOURNAL if name == "BTC" else (
            [{"ts": iso(NOW - 3600), "side": "SHORT", "kind": "вход", "order_id": sb_order}] if name == "SB" else [])
        jp.write_text("".join(json.dumps(r) + "\n" for r in jr), encoding="utf-8")
        files[name] = (cp, sp, jp)
    monkeypatch.setattr(eg, "GRIDS", tuple(cfgs))
    monkeypatch.setattr(eg, "grid_files", lambda name: files[name])


def test_short_grid_orders_and_fills_on_released_side_are_legit(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    tp = {"orderId": "sbt", "clientOrderId": "b7g5St17000000002", "positionSide": "SHORT", "side": "BUY",
          "price": "98.6", "origQty": "1", "executedQty": "0", "reduceOnly": True}
    c = FakeClient(trades=[trade("t1", "sb1", side="SELL", at=NOW - 3600)], opens=[tp],
                   infos={"sb1": {"orderId": "sb1", "clientOrderId": "b7g5Se17000000001"}},
                   positions=[{"symbol": "BTCUSDT", "side": "SHORT", "size": "1"}])
    code, out = run_script("account_now.py", c, monkeypatch)
    assert "ДРУГИЕ СЕТКИ БОТА" not in out, out
    assert "в т.ч. лоты сеток" in out
    assert "BTC BTCUSDT SHORT передан оператору" in out and "бот сторону не трогал" in out


def test_other_grid_order_on_released_side_still_problem(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    o = {"orderId": "x3", "clientOrderId": "b7g3Se17000000009", "positionSide": "SHORT", "side": "SELL",
         "price": "101", "origQty": "1"}
    code, out = run_script("account_now.py", FakeClient(opens=[o]), monkeypatch)
    assert code == 1 and "ДРУГИЕ СЕТКИ БОТА" in out, out
