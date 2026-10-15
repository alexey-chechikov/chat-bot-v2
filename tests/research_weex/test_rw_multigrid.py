"""Проверочные скрипты research/weex при нескольких сетках на одном символе (15.10: живая BTC + B34/B49/B89 на
BTCUSDT). Своя сетка — b7g + её знак: ордера и сделки соседок не сироты, не «чужие ручные» и не идут в сверку денег;
ордер бота со знаком ни одной сетки — сирота без хозяина; сетка бота на переданной оператору стороне — ПРОБЛЕМА."""
import json
import time

from services.weex_grid import engine as eg
from tests.research_weex.harness import FakeClient, daily_rows, iso, run_script, side_state, trade

NOW = time.time()
T0 = NOW - 3 * 86400


def make_grids(tmp_path, monkeypatch, grids: dict) -> dict:
    """grids: {имя: (конфиг, учёт|None, журнал|None)} — у каждой сетки свои файлы; GRIDS — эти имена."""
    paths = {}
    for name, (cfg, st, journal) in grids.items():
        cp, sp, jp = (tmp_path / f"{name}_cfg.json", tmp_path / f"{name}_state.json",
                      tmp_path / f"{name}_journal.jsonl")
        cp.write_text(json.dumps({"symbol": "BTCUSDT", "dry_run": False, "enabled": True, "sides": ["LONG"], **cfg},
                                 ensure_ascii=False), encoding="utf-8")
        if st is not None:
            sp.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
        if journal is not None:
            jp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in journal), encoding="utf-8")
        paths[name] = (cp, sp, jp)
    monkeypatch.setattr(eg, "GRIDS", tuple(grids))
    monkeypatch.setattr(eg, "grid_files", lambda name: paths[name])
    return paths


def order(oid, cid, side="BUY", pos="LONG", price="100", qty="1", reduce=False):
    return {"orderId": oid, "clientOrderId": cid, "side": side, "positionSide": pos, "price": price, "origQty": qty,
            "executedQty": "0", "reduceOnly": reduce}


def grid_state(entry=None, tp=None, **top):
    lots = []
    if tp:
        lots = [{"entry": 100.0, "qty": "1", "tp": float(tp[2]), "t": 1.0,
                 "tp_order": {"id": tp[0], "cid": tp[1], "price": float(tp[2]), "qty": "1"}}]
    long = side_state(lots=lots, entry={"id": entry[0], "cid": entry[1], "price": 99.0, "qty": "1"} if entry else None)
    return {"symbol": "BTCUSDT", "LONG": long, "SHORT": side_state(), "halted": False,
            "last_tick_ok_ts": time.time() - 5, **top}


FOUR = {
    "BTC": ({"release_sides": ["SHORT"]}, grid_state(("be", "b7gBLe1"), ("bt", "b7gBLt1", "101")), []),
    "B34": ({"cid_tag": "3"}, grid_state(("e34", "b7g3Le1"), ("t34", "b7g3Lt1", "101")), []),
    "B49": ({"cid_tag": "4"}, grid_state(("e49", "b7g4Le1")), []),
    "B89": ({"cid_tag": "8", "dry_run": True, "enabled": False}, None, None),
}
OPENS = [order("be", "b7gBLe1", price="99"), order("bt", "b7gBLt1", "SELL", price="101", reduce=True),
         order("e34", "b7g3Le1", price="99"), order("t34", "b7g3Lt1", "SELL", price="101", reduce=True),
         order("e49", "b7g4Le1", price="99"), order("m1", "6b1f0c9e-web", price="90")]


def test_orphan_check_four_grids_neighbours_are_not_orphans(tmp_path, monkeypatch):
    make_grids(tmp_path, monkeypatch, FOUR)
    code, out = run_script("orphan_check.py", FakeClient(opens=OPENS), monkeypatch)
    assert code == 0, out
    assert "BTC BTCUSDT: своих ордеров 2 — сопоставлено с учётом 2" in out
    assert "B34 BTCUSDT: своих ордеров 2 — сопоставлено с учётом 2" in out
    assert "B49 BTCUSDT: своих ордеров 1 — сопоставлено с учётом 1" in out
    assert "B89 BTCUSDT: живого учёта нет; своих ордеров на бирже 0" in out
    assert "сирота:" not in out and "ИТОГ: сирот 0, лотов без тейка 0" in out


def test_orphan_check_flags_own_orphan_and_order_of_no_grid(tmp_path, monkeypatch):
    opens = OPENS + [order("x3", "b7g3Le9", price="98"), order("z1", "b7gZLe1", price="97")]
    make_grids(tmp_path, monkeypatch, FOUR)
    code, out = run_script("orphan_check.py", FakeClient(opens=opens), monkeypatch)
    assert code == 1, out
    assert "B34 BTCUSDT: своих ордеров 3 — сопоставлено с учётом 2" in out and "сирот 1" in out
    assert "BTC BTCUSDT: своих ордеров 2 — сопоставлено с учётом 2, по cid неясной постановки 0, сирот 0" in out
    assert "без сетки" in out and "b7gZLe1" in out


def test_duplicate_tag_is_problem_not_ok_in_all_checks(tmp_path, monkeypatch):
    """Две сетки с одним знаком (B49 получила «3», как у B34): движок их останавливает — проверки не выдают «ок» и не
    приписывают ордера одной сетке за другую."""
    grids = {**FOUR, "B49": ({"cid_tag": "3"}, FOUR["B49"][1], [])}
    make_grids(tmp_path, monkeypatch, grids)
    code, out = run_script("orphan_check.py", FakeClient(opens=OPENS), monkeypatch)
    assert code == 1 and "совпадает со знаком сетки B49" in out and "ИТОГ: сирот 0" not in out, out
    make_grids(tmp_path, monkeypatch, {**recon_grids(), "B49": ({"cid_tag": "3"}, recon_grids()["B49"][1], [])})
    code, out = run_script("pnl_reconcile.py", FakeClient(trades=TRADES, infos=INFOS), monkeypatch, argv=["B34"])
    assert code == 2 and "совпадает" in out and "ИТОГ: совпадает" not in out, out


# ---------- сверка денег одной сетки на общем символе
INFOS = {"e34": {"orderId": "e34", "clientOrderId": "b7g3Le1"}, "t34": {"orderId": "t34", "clientOrderId": "b7g3Lt1"},
         "eb": {"orderId": "eb", "clientOrderId": "b7gBLe1"}, "mb": {"orderId": "mb", "clientOrderId": "web-manual"},
         "e49": {"orderId": "e49", "clientOrderId": "b7g4Le1"}}
TRADES = [trade("1", "e34", pos="LONG", side="BUY", price=100.0, at=T0 + 60, commission="0.01"),
          trade("2", "t34", pos="LONG", side="SELL", price=101.0, at=T0 + 120, commission="0.01"),
          trade("3", "eb", pos="LONG", side="BUY", price=99.0, at=T0 + 180, commission="0.01"),
          trade("4", "mb", pos="LONG", side="BUY", price=98.0, qty=2.0, at=T0 + 240),
          trade("5", "e49", pos="LONG", side="BUY", price=100.5, at=T0 + 300, commission="0.01")]


def recon_grids():
    st34 = grid_state()
    st34["LONG"].update(realized=1.0, fees=0.02, n_entries=1, n_tps=1)
    stb = grid_state()
    stb["LONG"].update(lots=[{"entry": 99.0, "qty": "1", "tp": 100.4, "t": 1.0, "tp_order": None}], fees=0.01,
                       n_entries=1)
    st49 = grid_state()
    st49["LONG"].update(lots=[{"entry": 100.5, "qty": "1", "tp": 101.0, "t": 1.0, "tp_order": None}], fees=0.01)
    return {"BTC": ({"release_sides": ["SHORT"]}, stb,
                    [{"ts": iso(T0), "side": "LONG", "kind": "вход", "order_id": "eb"}]),
            "B34": ({"cid_tag": "3"}, st34, [{"ts": iso(T0), "side": "LONG", "kind": "вход", "order_id": "e34"},
                                             {"ts": iso(T0 + 120), "side": "LONG", "kind": "тейк", "order_id": "t34"}]),
            "B49": ({"cid_tag": "4"}, st49, [{"ts": iso(T0), "side": "LONG", "kind": "вход", "order_id": "e49"}])}


def test_pnl_reconcile_new_grid_counts_only_its_own_trades(tmp_path, monkeypatch):
    make_grids(tmp_path, monkeypatch, recon_grids())
    c = FakeClient(trades=TRADES, infos=INFOS)
    code, out = run_script("pnl_reconcile.py", c, monkeypatch, argv=["B34"])
    assert code == 0, out
    assert "сетки 2, ручных 1, других сеток 2" in out and "ИТОГ: совпадает" in out
    assert "e49" not in c.info_calls                       # номер из журнала B49 — соседка без запроса детали


def test_pnl_reconcile_live_btc_excludes_new_grids(tmp_path, monkeypatch):
    make_grids(tmp_path, monkeypatch, recon_grids())
    code, out = run_script("pnl_reconcile.py", FakeClient(trades=TRADES, infos=INFOS), monkeypatch, argv=["BTC"])
    assert code == 0, out
    assert "сетки 1, ручных 1, других сеток 3" in out and "ИТОГ: совпадает" in out


def test_pnl_reconcile_unknown_tag_is_not_ok(tmp_path, monkeypatch):
    make_grids(tmp_path, monkeypatch, recon_grids())
    infos = {**INFOS, "e49": {"orderId": "e49", "clientOrderId": "b7gZLe1"}}   # знак ни одной сетки
    (tmp_path / "B49_journal.jsonl").write_text("", encoding="utf-8")
    code, out = run_script("pnl_reconcile.py", FakeClient(trades=TRADES, infos=infos), monkeypatch, argv=["B34"])
    assert code == 2, out
    assert "совпадает" not in out


# ---------- счёт: режим один раз, сетка бота на стороне оператора — проблема
def acct_grids(extra_short=False):
    journal = [{"ts": iso(NOW - 5 * 86400), "side": "SHORT", "kind": "вход", "order_id": "s0"},
               {"ts": iso(NOW - 2 * 86400), "side": "SHORT", "kind": "передано оператору", "qty": "1", "avg": 100.0,
                "mark": 100.0, "bag": 0.0, "lots": 1}]
    g = {"BTC": ({"release_sides": ["SHORT"], "regime_sma": 100}, grid_state(), journal)}
    for n, t in (("B34", "3"), ("B49", "4"), ("B89", "8")):
        g[n] = ({"cid_tag": t, "regime_sma": 100}, grid_state(), [])
    opens = [order("e34", "b7g3Le1", price="99"), order("e49", "b7g4Le1", price="99")]
    if extra_short:
        opens.append(order("s34", "b7g3Se1", side="SELL", pos="SHORT", price="105"))
    return g, opens


def test_account_now_four_btc_grids_ok_and_regime_printed_once(tmp_path, monkeypatch):
    g, opens = acct_grids()
    make_grids(tmp_path, monkeypatch, g)
    monkeypatch.setattr(eg, "_fetch_daily", lambda sym, n: daily_rows())
    code, out = run_script("account_now.py", FakeClient(opens=opens), monkeypatch)
    assert code == 0, out
    assert out.count("SMA100") == 1 and out.count("цикл жив") == 4
    assert "ДРУГИЕ СЕТКИ" not in out and "бот сторону не трогал" in out


def test_account_now_shared_position_against_all_grids_lots(tmp_path, monkeypatch):
    """Общая позиция LONG BTCUSDT сверяется с суммой лотов всех живых сеток символа: меньше — «перепроверить» (код 2),
    равна — ок."""
    g, opens = acct_grids()
    lot = {"entry": 100.0, "tp": 101.0, "t": 1.0, "tp_order": None}
    g["BTC"][1]["LONG"]["lots"] = [{**lot, "qty": "0.0036"}]
    g["B34"][1]["LONG"]["lots"] = [{**lot, "qty": "0.0012"}]
    make_grids(tmp_path, monkeypatch, g)
    monkeypatch.setattr(eg, "_fetch_daily", lambda sym, n: daily_rows())
    for size, want_code, want in (("0.0036", 2, "МЕНЬШЕ суммы лотов сеток 0.0048 (BTC 0.0036, B34 0.0012)"),
                                  ("0.0048", 0, "позиция на бирже 0.0048, лотов сеток 0.0048")):
        pos = [{"symbol": "BTCUSDT", "side": "LONG", "size": size, "openValue": str(float(size) * 100)}]
        code, out = run_script("account_now.py", FakeClient(opens=opens, positions=pos), monkeypatch)
        assert code == want_code and want in out, out


def test_account_now_duplicate_tag_is_problem(tmp_path, monkeypatch):
    g, opens = acct_grids()
    g["B49"] = ({"cid_tag": "3", "regime_sma": 100}, grid_state(), [])
    make_grids(tmp_path, monkeypatch, g)
    monkeypatch.setattr(eg, "_fetch_daily", lambda sym, n: daily_rows())
    code, out = run_script("account_now.py", FakeClient(opens=opens), monkeypatch)
    assert code == 1 and "совпадает со знаком сетки" in out and "ИТОГ: ЕСТЬ ПРОБЛЕМА" in out, out


def test_account_now_other_grid_on_operator_side_is_problem(tmp_path, monkeypatch):
    g, opens = acct_grids(extra_short=True)
    make_grids(tmp_path, monkeypatch, g)
    monkeypatch.setattr(eg, "_fetch_daily", lambda sym, n: daily_rows())
    code, out = run_script("account_now.py", FakeClient(opens=opens), monkeypatch)
    assert code == 1, out
    assert "ДРУГИЕ СЕТКИ БОТА на стороне: ордеров 1" in out and "ПРОБЛЕМА" in out
