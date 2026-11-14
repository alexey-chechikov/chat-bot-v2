"""Страховка лонг-сеток шортом системы (executor sizing="hedge", services/sigexec/hedge.py, run.check_executor_cfg) —
14.11, research/grid_hedge_20261114. Имитатор биржи — тот же, что у test_executor (частичные, потерянные ответы)."""
from __future__ import annotations

import json
import math

import pytest

from services.sigexec import hedge as hg
from services.sigexec import run as rn
from services.sigexec.exchange.base import LONG, SHORT
from services.sigexec.exchange.sim import SimExchange
from services.sigexec.executor import Executor, Halt, validate_config
from services.sigexec.strategy import Desired

T0 = 1_800_000_000
HCFG = {"enabled": True, "sizing": "hedge", "hedge_k": 1.0, "use_target": False, "allowed_sides": ["SHORT"], "slots": ["system"],
        "cap_usd": 15000.0, "prefix": "b7h", "entry": {"kind": "market"}, "exit": {"kind": "market"}}


class Expo:
    """Источник позиции сеток для тестов: значение или исключение; считает вызовы."""

    def __init__(self, v):
        self.v, self.calls = v, 0

    def __call__(self):
        self.calls += 1
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


def d_short(**kw):
    x = dict(slot="system", entry_t=T0, side=-1, tag="под синей", w=1.7, sig_px=70000.0, main_frac=0.85, add_lv=68000.0, add_frac=0.85,
             add_done=False, target=None, exit_by_t=None, exit_text="")
    x.update(kw)
    return Desired(**x)


def d_cs(**kw):
    x = dict(slot="system", entry_t=T0, side=-1, tag="под жёлтой", w=1.3, sig_px=70000.0, main_frac=1.3, add_lv=None, add_frac=0.0,
             add_done=False, target=68000.0, exit_by_t=None, exit_text="")
    x.update(kw)
    return Desired(**x)


def d_long(**kw):
    x = dict(slot="system", entry_t=T0, side=1, tag="над синей", w=1.0, sig_px=70000.0, main_frac=0.5, add_lv=72000.0, add_frac=0.5,
             add_done=False, target=None, exit_by_t=None, exit_text="")
    x.update(kw)
    return Desired(**x)


def run(e, ex, desired, n=1, dt=5.0, events=None):
    for _ in range(n):
        e.step(desired, events)
        ex.tick_clock(dt)


def journal(tmp_path):
    return [json.loads(x) for x in (tmp_path / "jr.jsonl").read_text().splitlines()]


def live_roles(e):
    return sorted((r["role"], r["kind"]) for r in e.st["orders"].values() if r["status"] not in ("FILLED", "CANCELED", "REJECTED", "ABSENT"))


# ---------------------------------------------------------------- размер
def test_size_from_grid_exposure_not_engine_weight(tmp_path):
    e, ex, _ = mk(tmp_path)
    run(e, ex, {"system": d_short()}, n=2)
    ep = e.st["slots"]["system"]["ep"]
    assert ep["goal_main"] == pytest.approx(0.1)            # 1.0 × 0.5 × $14 000 / 70 000 — вес 1.7 не применён
    assert ep["goal_add"] == pytest.approx(0.1029)          # 0.5 × $14 000 / 68 000, вниз к шагу 0.0001
    assert ep["hedge"] == {"exposure_usd": 14000.0, "k": 1.0, "base_usd": 14000.0, "main_frac": 0.5, "add_frac": 0.5}
    assert ex.pos[SHORT] == pytest.approx(0.1) and ex.pos[LONG] == 0
    assert live_roles(e) == [("add", "STOP"), ("stop", "STOP")]
    stop = next(r for r in e.st["orders"].values() if r["role"] == "stop")
    assert stop["side"] == "BUY" and stop["trigger"] > 70000 * 1.11      # аварийный стоп шорта — выше входа


def test_k_scales_size(tmp_path):
    e, ex, _ = mk(tmp_path, hedge_k=0.5)
    run(e, ex, {"system": d_short()})
    assert e.st["slots"]["system"]["ep"]["goal_main"] == pytest.approx(0.05)


def test_size_fixed_at_entry(tmp_path):
    src = Expo(14000.0)
    e, ex, _ = mk(tmp_path, expo=src)
    run(e, ex, {"system": d_short()})
    src.v = 28000.0                                          # сетки набрали ещё — эпизод не пересчитывается
    run(e, ex, {"system": d_short()}, n=3)
    ep = e.st["slots"]["system"]["ep"]
    assert ep["goal_main"] == pytest.approx(0.1) and ep["goal_add"] == pytest.approx(0.1029)
    assert src.calls == 1 and ex.pos[SHORT] == pytest.approx(0.1)


def test_cap_trims_hedge(tmp_path):
    e, ex, _ = mk(tmp_path, expo=40000.0, cap_usd=5000.0)
    run(e, ex, {"system": d_short()})
    ep = e.st["slots"]["system"]["ep"]
    assert ep["goal_add"] == 0.0 and ep["goal_main"] == pytest.approx(0.0714)   # сначала без добора, потом под потолок
    assert ex.pos[SHORT] * 70000 <= 5000 + 1


def test_under_yellow_hedge_half_no_target_on_shared_account(tmp_path):
    e, ex, _ = mk(tmp_path, shared_account=True)
    run(e, ex, {"system": d_cs()}, n=2)
    ep = e.st["slots"]["system"]["ep"]
    assert ep is not None and ep["goal_main"] == pytest.approx(0.1) and ep["goal_add"] == 0.0
    assert live_roles(e) == [("stop", "STOP")]               # цели лимиткой нет — одна reduceOnly на стороне
    assert not [r for r in e.st["orders"].values() if r["role"] == "target"]


def test_long_signal_not_executed(tmp_path):
    e, ex, src = mk(tmp_path)
    run(e, ex, {"system": d_long()})
    assert e.st["slots"]["system"]["ep"] is None and T0 in e.st["slots"]["system"]["done"]
    assert ex.pos[LONG] == 0 and src.calls == 0


# ---------------------------------------------------------------- неизвестная позиция сеток ≠ ноль
@pytest.mark.parametrize("bad", [OSError("сеть"), hg.ExposureError("кривой ответ"), float("nan"), -5.0, "14000", True, None])
def test_unknown_exposure_waits_not_done(tmp_path, bad):
    src = Expo(bad)
    e, ex, _ = mk(tmp_path, expo=src)
    run(e, ex, {"system": d_short()}, n=3)
    S = e.st["slots"]["system"]
    assert S["ep"] is None and T0 not in S["done"] and not e.st["orders"]
    msgs = [j for j in journal(tmp_path) if j["kind"] == "размер страховки неизвестен"]
    assert len(msgs) == 1                                   # сообщение раз в час, не на каждый проход
    src.v = 14000.0                                         # прочиталось — эпизод начинается, пока сигнал свежий
    run(e, ex, {"system": d_short()})
    assert S["ep"] is not None and ex.pos[SHORT] == pytest.approx(0.1)


def test_unknown_exposure_until_signal_too_old(tmp_path):
    src = Expo(OSError("сеть"))
    e, ex, _ = mk(tmp_path, expo=src, max_signal_age_s=1800)
    run(e, ex, {"system": d_short()})
    ex.tick_clock(2000)
    src.v = 14000.0
    run(e, ex, {"system": d_short()})
    S = e.st["slots"]["system"]
    assert S["ep"] is None and T0 in S["done"] and ex.pos[SHORT] == 0   # опоздавший вход не догоняется


def test_no_grid_longs_nothing_to_hedge(tmp_path):
    e, ex, _ = mk(tmp_path, expo=0.0)
    run(e, ex, {"system": d_short()})
    S = e.st["slots"]["system"]
    assert S["ep"] is None and T0 in S["done"] and not e.st["orders"]


# ---------------------------------------------------------------- выход и общий счёт
def test_exit_by_signal_closes_only_own_short(tmp_path):
    e, ex, _ = mk(tmp_path, shared_account=True)
    ex.external_trade(SHORT, 0.05)                          # ручной шорт оператора на той же стороне
    run(e, ex, {"system": d_short()}, n=2)
    assert ex.pos[SHORT] == pytest.approx(0.15)
    ex.move(69000.0)
    ev = [{"slot": "system", "kind": "выход", "t": T0 + 3600, "entry_t": T0, "px": 69000.0, "why": "2 закрытия над зелёной", "res": 1.0}]
    run(e, ex, {"system": None}, events=ev, n=3)
    assert ex.pos[SHORT] == pytest.approx(0.05)             # закрыт только свой объём
    assert e.st["slots"]["system"]["ep"] is None
    orders = sorted(e.st["orders"].values(), key=lambda r: r["t_sent"])
    stop = next(r for r in orders if r["role"] == "stop")
    exit_ = next(r for r in orders if r["role"] == "exit")
    assert stop["status"] == "CANCELED" and stop["t_done"] <= exit_["t_sent"]   # стоп снят до рыночного выхода
    tr = [j for j in journal(tmp_path) if j["kind"] == "сделка"][0]
    assert tr["engine_usd"] is None and tr["hedge"]["exposure_usd"] == 14000.0
    assert tr["pnl_usd"] == pytest.approx(0.1 * (70000 - 69000), abs=12)        # минус комиссии и проскальзывание


def test_emergency_stop_closes_hedge_keeps_operator_short(tmp_path):
    e, ex, _ = mk(tmp_path, shared_account=True)
    ex.external_trade(SHORT, 0.05)
    run(e, ex, {"system": d_short()}, n=2)
    ex.bar(70000.0, 78500.0, 69900.0, 78400.0)              # +12% против шорта
    run(e, ex, {"system": d_short()}, n=3)
    assert ex.pos[SHORT] == pytest.approx(0.05)
    assert e.st["slots"]["system"]["ep"] is None


# ---------------------------------------------------------------- конфиг
@pytest.mark.parametrize("bad", [{"allowed_sides": ["LONG", "SHORT"]}, {"allowed_sides": ["LONG"]}, {"slots": ["system", "432"]},
                                 {"use_target": True}, {"hedge_k": 0}, {"hedge_k": 2.5}, {"hedge_k": True}, {"hedge_k": float("nan")},
                                 {"sizing": "kelly"}, {"use_target": "no"}])
def test_hedge_config_rejected(bad):
    with pytest.raises(Halt):
        validate_config({**HCFG, **bad})


def test_base_sizing_unchanged_by_default():
    c = validate_config({"enabled": True})
    assert c["sizing"] == "base" and c["use_target"] is True and c["allowed_sides"] == ["LONG", "SHORT"]


def test_hedge_without_exposure_source_halts(tmp_path):
    with pytest.raises(Halt):
        Executor(SimExchange(), HCFG, tmp_path / "st.json", tmp_path / "jr.jsonl")


def _rcfg(**xc):
    return {"exchange": {"name": "weex", "symbol": "BTCUSDT", "paper": False, "testnet": False, **xc},
            "executor": dict(HCFG), "feed": {"symbol": "BTCUSDT"}}


def test_weex_live_hedge_needs_operator_permission():
    with pytest.raises(Halt):
        rn.check_executor_cfg(_rcfg())
    with pytest.raises(Halt):
        rn.check_executor_cfg(_rcfg(share_short_with_operator="yes"))
    ecfg = rn.check_executor_cfg(_rcfg(share_short_with_operator=True))
    assert ecfg["shared_account"] is True and ecfg["allowed_sides"] == ["SHORT"]


def test_weex_live_rules_for_long_executor_unchanged():
    cfg = _rcfg(share_short_with_operator=True)
    cfg["executor"] = {"enabled": True, "allowed_sides": ["LONG", "SHORT"]}
    with pytest.raises(Halt):
        rn.check_executor_cfg(cfg)                          # без страховки SHORT на WEEX по-прежнему нельзя
    cfg["executor"] = {"enabled": True, "allowed_sides": ["LONG"]}
    assert rn.check_executor_cfg(cfg)["shared_account"] is True


def test_message_head_says_paper_and_hedge():
    cfg = _rcfg()
    cfg["exchange"]["paper"] = True
    assert rn.head_of(cfg) == "🛡 страховка сеток (sigexec) · БУМАГА — заявки на биржу не уходят"
    cfg["exchange"]["paper"] = False
    assert rn.head_of(cfg) == "🛡 страховка сеток (sigexec)"
    assert rn.head_of(dict(cfg, executor={"enabled": True})) == "🤖 sigexec"


def test_hedge_state_file_separate_from_long_executor():
    cfg = _rcfg(share_short_with_operator=True)
    long_cfg = dict(cfg, executor={"enabled": True, "allowed_sides": ["LONG"]})
    assert rn.state_tag(cfg) == "weex-live-main-BTCUSDT-hedge"
    assert rn.state_tag(long_cfg) == "weex-live-main-BTCUSDT"


# ---------------------------------------------------------------- источник позиции сеток
ROWS = [{"symbol": "BTCUSDT", "side": "LONG", "size": "0.18"}, {"symbol": "BTCUSDT", "side": "SHORT", "size": "0.05"},
        {"symbol": "ETHUSDT", "side": "LONG", "size": "1.2"}, {"symbol": "XRPUSDT", "side": "LONG", "size": "100"}]
BOOKS = {"BTCUSDT": (68000.0, 68001.0), "ETHUSDT": (1930.0, 1930.2)}


def test_long_exposure_btc_plus_eth_ignores_short_and_others():
    v = hg.long_exposure_usd(ROWS, BOOKS)
    assert v == pytest.approx(0.18 * 68000.5 + 1.2 * 1930.1)


@pytest.mark.parametrize("rows,books", [
    ({"code": 500}, BOOKS),
    ([{"symbol": "BTCUSDT", "side": "LONG", "size": "abc"}], BOOKS),
    ([{"symbol": "BTCUSDT", "side": "LONG", "size": "-0.1"}], BOOKS),
    ([{"symbol": "BTCUSDT", "side": "LONG", "size": "nan"}], BOOKS),
    ([{"symbol": "BTCUSDT", "side": "LONG", "size": None}], BOOKS),
    (["строка"], BOOKS),
    ([{"symbol": "ETHUSDT", "side": "LONG", "size": "1"}], {"BTCUSDT": (1.0, 2.0)}),
    ([{"symbol": "BTCUSDT", "side": "LONG", "size": "0.1"}], {"BTCUSDT": (68001.0, 68000.0)}),
    ([{"symbol": "BTCUSDT", "side": "LONG", "size": "0.1"}], {"BTCUSDT": (0.0, 68000.0)}),
    ([{"symbol": "BTCUSDT", "side": "LONG", "size": "1.0"}], BOOKS),       # $68k > предела $30k
])
def test_long_exposure_unclear_raises(rows, books):
    with pytest.raises(hg.ExposureError):
        hg.long_exposure_usd(rows, books)


def test_long_exposure_zero_when_no_longs():
    assert hg.long_exposure_usd([{"symbol": "BTCUSDT", "side": "SHORT", "size": "0.3"}], {}) == 0.0


def test_weex_exposure_reads_book_only_for_held_symbols():
    class C:
        def __init__(self):
            self.books = []

        def futures_positions(self):
            return [{"symbol": "BTCUSDT", "side": "LONG", "size": "0.1"}]

        def book(self, s):
            self.books.append(s)
            return BOOKS[s]
    c = C()
    v = hg.WeexExposure(c)()
    assert v == pytest.approx(0.1 * 68000.5) and c.books == ["BTCUSDT"]


def test_make_source():
    assert hg.make({"source": 1234.5})() == 1234.5
    for bad in ({"source": -1}, {"source": "binance"}, {"source": float("inf")}, {"source": True}):
        with pytest.raises(ValueError):
            hg.make(bad)
    assert math.isfinite(hg.DEFAULT_MAX_USD)
