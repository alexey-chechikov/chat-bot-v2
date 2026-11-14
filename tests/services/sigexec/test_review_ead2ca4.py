"""Регрессии разбора GPT ead2ca4 (docs/WEEX_GPT_SIGEXEC_HEDGE_REVIEW_2026-11-14.md) — страховка на общей стороне WEEX.
Имитатор биржи — SimExchange (WEEX COMBINED: reduceOnly режет общую сторону, сим так и делает); адаптер WEEX — на
подставном клиенте. Каждый тест падает на f1049c9 (проверено переносом в его worktree) — см. ANSWERS."""
from __future__ import annotations

import json

import pytest

from services.sigexec import hedge as hg
from services.sigexec import run as rn
from services.sigexec.exchange.base import SHORT, Incomplete, OrderReq, Unknown
from services.sigexec.exchange.sim import SimExchange
from services.sigexec.exchange.weex import WeexExchange
from services.sigexec.executor import Executor, Halt
from services.sigexec.strategy import Desired

T0 = 1_800_000_000
HCFG = {"enabled": True, "sizing": "hedge", "hedge_k": 1.0, "use_target": False, "allowed_sides": ["SHORT"], "slots": ["system"],
        "cap_usd": 15000.0, "prefix": "b7h", "entry": {"kind": "market"}, "exit": {"kind": "market"}, "add_resting": False,
        "shared_account": True}


class Expo:
    def __init__(self, v):
        self.v = v

    def __call__(self):
        if isinstance(self.v, Exception):
            raise self.v
        return self.v


def mk(tmp_path, expo=14000.0, ex=None, **cfg):
    ex = ex or SimExchange(price=70000.0)
    ex._t = T0 + 5
    c = dict(HCFG)
    c.update(cfg)
    src = expo if isinstance(expo, Expo) else Expo(expo)
    return Executor(ex, c, tmp_path / "st.json", tmp_path / "jr.jsonl", exposure=src), ex, src


def d_cs(**kw):
    x = dict(slot="system", entry_t=T0, side=-1, tag="под жёлтой", w=1.0, sig_px=70000.0, main_frac=1.0, add_lv=None, add_frac=0.0,
             add_done=False, target=68000.0, exit_by_t=None, exit_text="")
    x.update(kw)
    return Desired(**x)


def d_blue(**kw):
    x = dict(slot="system", entry_t=T0, side=-1, tag="под синей", w=1.0, sig_px=70000.0, main_frac=0.5, add_lv=68000.0, add_frac=0.5,
             add_done=False, target=None, exit_by_t=None, exit_text="")
    x.update(kw)
    return Desired(**x)


def run(e, ex, desired, n=1, dt=5.0, events=None):
    for _ in range(n):
        e.step(desired, events)
        ex.tick_clock(dt)


def setup_shared(tmp_path, **cfg):
    """Ручной шорт 0.05, страховка 0.10 и её стоп — как в воспроизведении GPT."""
    e, ex, src = mk(tmp_path, **cfg)
    ex.external_trade(SHORT, 0.05)
    run(e, ex, {"system": d_cs()}, n=2)
    assert ex.pos[SHORT] == pytest.approx(0.15)
    assert [r["qty"] for r in e.st["orders"].values() if r["role"] == "stop" and r["status"] == "UNTRIGGERED"] == [pytest.approx(0.10)]
    return e, ex, src


# ---------------------------------------------------------------- P1: общая сторона SHORT
@pytest.mark.parametrize("variant", ["выход системы", "аварийный стоп", "close_all"])
def test_external_reduction_never_closes_manual_short(tmp_path, variant):
    e, ex, _ = setup_shared(tmp_path)
    ex.external_trade(SHORT, -0.02)                      # кто-то сократил общую сторону: 0.15 → 0.13
    run(e, ex, {"system": d_cs()}, n=3)
    if variant == "выход системы":
        run(e, ex, {"system": None}, n=4)
    elif variant == "аварийный стоп":
        ex.move(80000.0)
        run(e, ex, {"system": d_cs()}, n=4)
    else:
        e.close_all()
        run(e, ex, {"system": d_cs()}, n=4)
    assert ex.pos[SHORT] == pytest.approx(0.05)          # ручные 0.05 целы (на f1049c9 — 0.03)
    assert e.st["slots"]["system"]["ep"] is None


def test_exit_right_after_reduction_is_clamped_to_floor(tmp_path):
    e, ex, _ = setup_shared(tmp_path)
    ex.external_trade(SHORT, -0.02)
    run(e, ex, {"system": None}, n=1)                    # выход в тот же проход — без двух проходов сверки
    assert ex.pos[SHORT] >= 0.05 - 1e-9
    run(e, ex, {"system": None}, n=4)
    assert ex.pos[SHORT] == pytest.approx(0.05)


def test_side_closed_and_new_manual_between_polls(tmp_path):
    e, ex, _ = setup_shared(tmp_path)
    ex.external_trade(SHORT, -0.15)                      # вся сторона закрыта кнопкой
    ex.external_trade(SHORT, 0.05)                       # и до следующего прохода — новый ручной шорт
    run(e, ex, {"system": None}, n=5)
    assert ex.pos[SHORT] == pytest.approx(0.05)          # новый ручной не закрыт (на f1049c9 — 0)


def test_side_closed_during_partial_entry_no_rebuy(tmp_path):
    e, ex, _ = mk(tmp_path)
    ex.external_trade(SHORT, 0.05)
    ex.partial_next(0.5)
    run(e, ex, {"system": d_cs()}, n=1)                  # вход налился наполовину: 0.05
    assert ex.pos[SHORT] == pytest.approx(0.10)
    ex.external_trade(SHORT, -0.10)                      # оператор закрыл всю сторону
    run(e, ex, {"system": d_cs()}, n=5)
    assert ex.pos[SHORT] == pytest.approx(0.0)           # прежний сигнал не добирает ещё 0.05 (на f1049c9 — 0.05)


def test_doubt_on_side_delays_new_episode(tmp_path):
    e, ex, _ = mk(tmp_path)
    ex.external_trade(SHORT, 0.05)
    run(e, ex, {"system": None}, n=1)                    # пол чужого объёма = 0.05
    ex.external_trade(SHORT, -0.02)                      # сторона изменилась, ещё не подтверждено
    run(e, ex, {"system": d_cs()}, n=1)
    assert e.st["slots"]["system"]["ep"] is None and not e.st["orders"]   # в сомнении эпизод не начинается
    run(e, ex, {"system": d_cs()}, n=3)                  # подтвердилось — ручной уменьшился, эпизод идёт
    assert e.st["slots"]["system"]["ep"] is not None and ex.pos[SHORT] == pytest.approx(0.13)


def test_stop_placed_during_doubt_not_above_closable(tmp_path):
    e, ex, _ = mk(tmp_path)
    ex.external_trade(SHORT, 0.05)
    run(e, ex, {"system": d_cs()}, n=1)                  # вход 0.10, стопа ещё нет
    ex.external_trade(SHORT, -0.12)                      # сторона 0.15 → 0.03 до следующего прохода
    run(e, ex, {"system": d_cs()}, n=1)
    stops = [r for r in e.st["orders"].values() if r["role"] == "stop" and r["status"] == "UNTRIGGERED"]
    assert all(r["qty"] <= 0.0 + 1e-9 for r in stops)    # закрыть можно 0.03 − пол 0.05 → 0: стопа на 0.10 нет
    ex.move(80000.0)
    assert ex.pos[SHORT] == pytest.approx(0.03)


def test_operator_adds_manual_short_then_hedge_exits_only_own(tmp_path):
    e, ex, _ = setup_shared(tmp_path)
    ex.external_trade(SHORT, 0.03)                       # оператор добавил ручной
    run(e, ex, {"system": d_cs()}, n=3)
    run(e, ex, {"system": None}, n=4)
    assert ex.pos[SHORT] == pytest.approx(0.08)          # ручные 0.05 + 0.03 целы


# ---------------------------------------------------------------- P1: потерянный ответ на стоп + «{}» истории
class HiddenStops(SimExchange):
    """Стоп встал, ответ потерян; поиск стопа — «неполный» (как {} из allAlgoOrders после исправления адаптера)."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.hide = False

    def order(self, symbol, cid, kind, oid="", placed_at=0.0):
        if kind == "STOP" and self.hide:
            raise Incomplete("allAlgoOrders: ответ не {hasMore, orders}")
        return super().order(symbol, cid, kind, oid, placed_at)


def test_lost_stop_reply_no_second_stop(tmp_path):
    ex = HiddenStops(price=70000.0)
    e, ex, _ = mk(tmp_path, ex=ex)
    ex.external_trade(SHORT, 0.10)
    run(e, ex, {"system": d_cs()}, n=1)                  # вход
    ex.hide = True
    ex.fail_next("place", "unknown_placed")              # стоп встал, ответ потерян
    run(e, ex, {"system": d_cs()}, n=1)
    run(e, ex, {"system": d_cs()}, n=8, dt=40)           # дольше unknown_grace_s
    stops = [r for r in e.st["orders"].values() if r["role"] == "stop"]
    assert len(stops) == 1 and stops[0]["status"] == "UNKNOWN"
    ex.move(80000.0)
    assert ex.pos[SHORT] == pytest.approx(0.10)          # сработал один стоп — ручные 0.10 целы (на f1049c9 — 0)


class FakeWeex:
    def __init__(self, algo_hist, open_algos=None, child=None):
        self.algo_hist, self.open_algos, self.child = algo_hist, open_algos or [], child
        self.cancelled, self.cancelled_algo = [], []

    def open_algo_orders(self, symbol):
        return self.open_algos

    def get(self, base, path, params):
        return self.algo_hist

    def order_info(self, oid):
        return self.child

    def user_trades(self, symbol, oid):
        return []

    def cancel(self, oid):
        self.cancelled.append(oid)
        return {"success": True}

    def cancel_algo(self, oid):
        self.cancelled_algo.append(oid)
        return {"success": False}


@pytest.mark.parametrize("hist", [{}, {"orders": []}, {"hasMore": False}, {"hasMore": "false", "orders": []}, {"hasMore": False, "orders": [1]},
                                  [], None])
def test_weex_algo_history_bad_envelope_is_incomplete(hist):
    w = WeexExchange(FakeWeex(hist))
    with pytest.raises(Incomplete):
        w.order("BTCUSDT", "b7hsk1", "STOP", "123", T0)  # на f1049c9 «{}» → None → ABSENT → второй стоп


def test_weex_algo_history_proper_empty_is_absent():
    assert WeexExchange(FakeWeex({"hasMore": False, "orders": []})).order("BTCUSDT", "b7hsk1", "STOP", "123", T0) is None


def test_weex_cancel_triggered_stop_cancels_child_order():
    algo = {"clientAlgoId": "b7hsk1", "algoId": "123", "algoStatus": "TRIGGERED", "actualOrderId": "456"}
    child = {"orderId": "456", "clientOrderId": "", "status": "NEW", "executedQty": "0", "symbol": "BTCUSDT"}
    c = FakeWeex({"hasMore": False, "orders": [algo]}, child=child)
    WeexExchange(c).cancel("BTCUSDT", "b7hsk1", "STOP", "123", placed_at=T0)
    assert c.cancelled == ["456"] and c.cancelled_algo == []   # на f1049c9 — DELETE родителя 123, ребёнок жив


def test_weex_place_success_false_is_unknown():
    class C:
        def post(self, base, path, body):
            return {"algoId": "123", "success": False}
    w = WeexExchange(C())
    req = OrderReq(cid="b7hsk2", symbol="BTCUSDT", side="BUY", pos_side="SHORT", kind="STOP", qty=0.1, price=None, trigger=78000.0,
                   post_only=False, reduce_only=True)
    with pytest.raises(Unknown):
        w.place(req)                                     # на f1049c9 — UNTRIGGERED


# ---------------------------------------------------------------- P1: гонка стопа и добора, размер добора
def test_hedge_has_no_resting_add_and_add_sized_at_add_hour(tmp_path):
    src = Expo(14000.0)
    e, ex, _ = mk(tmp_path, expo=src, shared_account=False)
    run(e, ex, {"system": d_blue()}, n=2)
    assert not [r for r in e.st["orders"].values() if r["role"] == "add"]   # стопа добора на бирже нет
    src.v = 7000.0                                       # лонги сеток закрылись тейками наполовину
    ex.move(68000.0)
    run(e, ex, {"system": d_blue(add_done=True)}, n=2)
    ep = e.st["slots"]["system"]["ep"]
    assert ep["goal_add"] == pytest.approx(0.0029, abs=1e-4)   # не больше предела: 1 × $7 000 / 68 000 − 0.10 (b056816; на f1049c9 — 0.1029)
    assert ex.pos[SHORT] == pytest.approx(0.1029, abs=1e-4)    # страховка = k × текущие лонги, не больше


def test_emergency_stop_then_no_reopen_by_add(tmp_path):
    e, ex, _ = mk(tmp_path, shared_account=False)
    run(e, ex, {"system": d_blue()}, n=2)
    ex.move(80000.0)
    ex.move(67900.0)                                     # между проходами: стоп закрыл шорт, цена ушла ниже уровня добора
    assert ex.pos[SHORT] == pytest.approx(0.0)           # на f1049c9 висящий стоп добора открыл 0.1029 до прохода
    run(e, ex, {"system": d_blue()}, n=3)
    assert ex.pos[SHORT] == pytest.approx(0.0)


def test_hedge_requires_market_exit_and_signal_add():
    from services.sigexec.executor import validate_config
    for bad in ({"exit": {"kind": "chase", "wait_s": 300, "reprice_s": 20, "max_orders": 20}}, {"add_resting": True},
                {"add_follow_signal": False}):
        with pytest.raises(Halt):
            validate_config({**HCFG, **bad})


def test_stop_resized_in_same_pass(tmp_path):
    e, ex, _ = setup_shared(tmp_path)
    ex.external_trade(SHORT, -0.02)
    run(e, ex, {"system": d_cs()}, n=3)                  # сверка подтвердила — эпизод в выходе; стоп снят, выход рыночный
    live = [r for r in e.st["orders"].values() if r["role"] == "stop" and r["status"] == "UNTRIGGERED"]
    assert not live or all(r["qty"] <= 0.08 + 1e-9 for r in live)


def test_persistent_incomplete_lookup_notifies_once_per_hour(tmp_path):
    ex = HiddenStops(price=70000.0)
    said = []
    ex._t = T0 + 5
    e = Executor(ex, dict(HCFG), tmp_path / "st.json", tmp_path / "jr.jsonl", notify=said.append, exposure=Expo(14000.0))
    run(e, ex, {"system": d_cs()}, n=1)
    ex.hide = True
    ex.fail_next("place", "unknown_placed")
    run(e, ex, {"system": d_cs()}, n=12, dt=40)
    assert sum("исход неизвестен, поиск неполный" in s for s in said) == 1


# ---------------------------------------------------------------- размер: правдоподобные, но кривые ответы
def _row(sym, side, size, mark):
    return {"symbol": sym, "side": side, "size": size, "openValue": str(float(size) * mark), "unrealizePnl": "0"}


BOOKS = {"BTCUSDT": (69999.0, 70001.0), "ETHUSDT": (1999.9, 2000.1)}


@pytest.mark.parametrize("rows,books,lots", [
    ([{"symbol": "BTCUSDT", "size": "0.1", "openValue": "7000", "unrealizePnl": "0"}], BOOKS, None),               # без side
    ([_row("BTCUSDT", "LONG", "0.1", 70000), _row("BTCUSDT", "LONG", "0.05", 70000)], BOOKS, None),               # дубль
    ([_row("BTCUSDT", "LONG", True, 70000)], BOOKS, None),                                                       # True
    ([_row("BTCUSDT", "LONG", "0.1", 70000)], {"BTCUSDT": (1999.0, 2001.0)}, None),                              # чужой стакан
    ([_row("BTCUSDT", "LONG", "0.1", 70000)], BOOKS, {"BTCUSDT": (0.1, 0.004), "ETHUSDT": (3.5, 0.06)}),          # ETH пропал
    ([_row("BTCUSDT", "LONG", "0.15", 70000), _row("ETHUSDT", "LONG", "3.5", 2000)], BOOKS,
     {"BTCUSDT": (0.1, 0.004), "ETHUSDT": (3.5, 0.06)}),                                                          # BTC ×1.5
    ([{"symbol": "BTCUSDT", "side": "LONG", "size": "0.1"}], BOOKS, None),                                       # нет openValue
])
def test_exposure_plausible_but_wrong_reads_raise(rows, books, lots):
    with pytest.raises(hg.ExposureError):
        hg.long_exposure_usd(rows, books, lots=lots)


def test_exposure_matches_grid_lots_within_tolerance(tmp_path):
    for name, sym, qtys in (("b.json", "BTCUSDT", [0.05, 0.05]), ("e.json", "ETHUSDT", [0.02] * 175)):
        (tmp_path / name).write_text(json.dumps({"LONG": {"lots": [{"qty": str(q)} for q in qtys]}}))
    lots = hg.grid_lots({"BTCUSDT": [str(tmp_path / "b.json")], "ETHUSDT": [str(tmp_path / "e.json")]})
    rows = [_row("BTCUSDT", "LONG", "0.1", 70000), _row("ETHUSDT", "LONG", "3.5", 2000)]
    assert hg.long_exposure_usd(rows, BOOKS, lots=lots) == pytest.approx(0.1 * 70000 + 3.5 * 2000)
    with pytest.raises(hg.ExposureError):
        hg.grid_lots({"BTCUSDT": [str(tmp_path / "нет.json")]})


@pytest.mark.parametrize("symbols", ["BTCUSDT", "ETHUSD", ["BTCUSDT", "BTCUSDT"], [], ["BTCUSDT", ""]])
def test_exposure_symbols_validated(symbols):
    with pytest.raises(hg.ExposureError):
        hg.long_exposure_usd([], {}, symbols=symbols)


def test_numeric_source_only_on_paper():
    with pytest.raises(ValueError):
        hg.make({"source": 14000}, live=True)
    with pytest.raises(ValueError):
        hg.make({"source": "weex"}, live=True)           # живой без сверки с учётом сеток
    assert hg.make({"source": 14000}, live=False)() == 14000.0


# ---------------------------------------------------------------- конфиг, потолок, бумажная книга
def _cfg(**xc):
    return {"exchange": {"name": "weex", "symbol": "BTCUSDT", "paper": True, "testnet": False, **xc},
            "executor": {k: v for k, v in HCFG.items() if k != "shared_account"}, "feed": {"symbol": "BTCUSDT"}}


@pytest.mark.parametrize("where", ["exchange", "feed"])
def test_hedge_only_btcusdt(where):
    cfg = _cfg()
    cfg[where]["symbol"] = "ETHUSDT"
    with pytest.raises(Halt):
        rn.check_executor_cfg(cfg)


def test_limit_cap_by_order_price(tmp_path):
    ex = SimExchange(price=70000.0)
    ex._t = T0 + 5
    e = Executor(ex, {"enabled": True, "base_usd": 100000.0, "cap_usd": 5000.0, "allowed_sides": ["SHORT"],
                      "entry": {"kind": "limit", "offset_bps": 1000, "wait_s": 300, "reprice_s": 20, "max_orders": 20}},
                 tmp_path / "st.json", tmp_path / "jr.jsonl")
    run(e, ex, {"system": d_cs(target=None)}, n=1)
    lim = [r for r in e.st["orders"].values() if r["role"] == "entry" and r["kind"] == "LIMIT"]
    assert lim and lim[0]["price"] == pytest.approx(77000.0)
    assert lim[0]["qty"] * lim[0]["price"] <= 5000.0 + 1e-6   # на f1049c9 — 0.0714 × 77 000 = $5 497.80


def test_paperbook_per_state_tag(tmp_path):
    cfg = _cfg()
    tag = rn.state_tag(cfg)
    ex = rn.make_exchange(cfg["exchange"], tmp_path, tag)
    assert ex.state_file.name == f"sigexec_paperbook_{tag}.json" and tag.endswith("-hedge")


def test_live_sb_grid_blocks_new_hedge_episodes(tmp_path):
    sb = tmp_path / "weex_grid_sb_config.json"
    sb.write_text(json.dumps({"enabled": True, "dry_run": False}))
    cfg = _cfg()
    cfg["hedge"] = {"source": 14000, "block_if_live": [str(sb)]}

    class Feed:
        t = []

        def update(self, now):
            return 0

        def fresh(self, now):
            return False
    said = []
    r = rn.Runner(cfg, tmp_path, exchange=SimExchange(), feed=Feed(), notify=said.append)
    r.tick(T0)
    assert r.exe.cfg["enabled"] is False and any("живая" in s for s in said)
    sb.write_text(json.dumps({"enabled": True, "dry_run": True}))
    r.tick(T0 + 10)
    assert r.exe.cfg["enabled"] is True


# ---------------------------------------------------------------- предел: страховка не больше текущих лонгов
def test_hedge_trimmed_when_grid_longs_shrink(tmp_path):
    src = Expo(14000.0)
    e, ex, _ = mk(tmp_path, expo=src)
    ex.external_trade(SHORT, 0.05)                       # ручной шорт — урезание его не трогает
    run(e, ex, {"system": d_cs()}, n=2)                  # «под жёлтой»: 0.5 × $14 000 / 70 000 = 0.10
    assert ex.pos[SHORT] == pytest.approx(0.15)
    src.v = 4000.0                                       # лонги сеток закрылись тейками: предел 1 × $4 000 / 70 000 ≈ 0.0571
    run(e, ex, {"system": d_cs()}, n=4, dt=40)
    ep = e.st["slots"]["system"]["ep"]
    assert e.qty(ep) == pytest.approx(0.0572, abs=2e-4)  # на f1049c9 — 0.10 до выхода системы
    assert ex.pos[SHORT] == pytest.approx(0.05 + e.qty(ep))   # ручные 0.05 целы
    stops = [r for r in e.st["orders"].values() if r["role"] == "stop" and r["status"] == "UNTRIGGERED"]
    assert stops and all(r["qty"] <= e.qty(ep) + 1e-9 for r in stops)


def test_hedge_not_trimmed_when_exposure_unknown(tmp_path):
    src = Expo(14000.0)
    e, ex, _ = mk(tmp_path, expo=src, shared_account=False)
    run(e, ex, {"system": d_cs()}, n=2)
    src.v = OSError("сеть")
    run(e, ex, {"system": d_cs()}, n=3, dt=70)
    assert ex.pos[SHORT] == pytest.approx(0.10)          # неизвестно ≠ 0: не урезает
