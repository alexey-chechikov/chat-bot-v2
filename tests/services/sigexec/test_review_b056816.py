"""Регрессии повторного разбора GPT b056816 (docs/WEEX_GPT_SIGEXEC_HEDGE_RECHECK_2026-11-14.md) — гонки на общей стороне
SHORT (WEEX COMBINED). Помощники — из test_review_ead2ca4. Каждый тест падает на 35f8b4f (см. ANSWERS)."""
from __future__ import annotations

import json

import pytest

from services.sigexec import hedge as hg
from services.sigexec import run as rn
from services.sigexec.exchange.base import SHORT, Incomplete
from services.sigexec.exchange.sim import SimExchange
from services.sigexec.exchange.weex import WeexExchange

from .test_review_ead2ca4 import HCFG, Expo, FakeWeex, d_blue, d_cs, mk, run, setup_shared

T0 = 1_800_000_000


# ---------------------------------------------------------------- P1: урезание + старый стоп
def test_trim_cancels_old_stop_before_cutting(tmp_path):
    e, ex, src = setup_shared(tmp_path)
    src.v = 4000.0
    ex.tick_clock(65)
    run(e, ex, {"system": d_cs()}, n=1)                  # урезание 0.0428
    ex.move(80000.0)                                     # до следующего прохода — рост за аварийный уровень
    assert ex.pos[SHORT] >= 0.05 - 1e-9                  # ручные 0.05 целы (на 35f8b4f — 0.0072)
    stops = [r for r in e.st["orders"].values() if r["role"] == "stop"]
    assert sum(r["filled"] for r in stops) <= 0.0572 + 1e-9   # старый стоп на 0.10 не исполнялся


# ---------------------------------------------------------------- P1: стоп исполнился во время замены
class SpikeOnCancel(SimExchange):
    """При снятии стопа цена успевает сходить к $80 000 и обратно — старый стоп исполняется до отмены."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.spike = False

    def cancel(self, symbol, cid, kind, oid="", placed_at=0.0):
        if kind == "STOP" and self.spike:
            self.spike = False
            p = self.px
            self.move(80000.0)
            self.move(p)
        return super().cancel(symbol, cid, kind, oid, placed_at)


def test_stop_filled_during_replacement_goes_to_exit(tmp_path):
    ex = SpikeOnCancel(price=70000.0)
    e, ex, _ = mk(tmp_path, ex=ex, expo=Expo(14000.0))
    ex.external_trade(SHORT, 0.05)
    run(e, ex, {"system": d_blue()}, n=2)                # 0.5 × $14 000 / 70 000 = 0.10 страховки, стоп 0.10
    ex.move(68000.0)
    run(e, ex, {"system": d_blue(add_done=True)}, n=1)   # рыночный добор 0.1029 — стоп 0.10 теперь меньше позиции
    assert ex.pos[SHORT] == pytest.approx(0.2529, abs=1e-4)
    ex.spike = True
    run(e, ex, {"system": d_blue(add_done=True)}, n=1)   # замена стопа: старый исполнился во время снятия
    big = [r for r in e.st["orders"].values() if r["role"] == "stop" and r["status"] == "UNTRIGGERED"
           and r["qty"] > ex.pos[SHORT] - 0.05 + 1e-9]
    assert not big                                       # на 35f8b4f — новый стоп 0.2029 при стороне 0.1529
    ex.move(80000.0)                                     # до следующего прохода
    assert ex.pos[SHORT] >= 0.05 - 1e-9                  # ручные 0.05 целы (на 35f8b4f — 0)


def test_stop_fill_during_replacement_starts_exit_same_pass(tmp_path):
    ex = SpikeOnCancel(price=70000.0)
    e, ex, _ = mk(tmp_path, ex=ex, expo=Expo(14000.0))
    ex.external_trade(SHORT, 0.05)
    run(e, ex, {"system": d_blue()}, n=2)
    ex.move(68000.0)
    run(e, ex, {"system": d_blue(add_done=True)}, n=1)
    ex.spike = True
    run(e, ex, {"system": d_blue(add_done=True)}, n=1)
    jr = [json.loads(x) for x in (tmp_path / "jr.jsonl").read_text().splitlines()]
    assert any(j["kind"] == "выход начат" and "при замене" in j["why"] for j in jr)
    assert ex.pos[SHORT] == pytest.approx(0.05)          # свой остаток закрыт рыночным в том же проходе


class CancelUnknown(SimExchange):
    """Снятие стопа не подтверждается (ответ потерян, стоп жив)."""

    def cancel(self, symbol, cid, kind, oid="", placed_at=0.0):
        if kind == "STOP":
            from services.sigexec.exchange.base import Unknown
            raise Unknown("sim: снятие стопа — ответ потерян")
        return super().cancel(symbol, cid, kind, oid, placed_at)


def test_trim_waits_until_stop_cancel_confirmed(tmp_path):
    ex = CancelUnknown(price=70000.0)
    e, ex, src = mk(tmp_path, ex=ex)
    ex.external_trade(SHORT, 0.05)
    run(e, ex, {"system": d_cs()}, n=2)
    src.v = 4000.0
    run(e, ex, {"system": d_cs()}, n=4, dt=40)
    assert not [r for r in e.st["orders"].values() if r["role"] == "trim"]   # урезания рядом с живым стопом нет
    assert ex.pos[SHORT] == pytest.approx(0.15)


# ---------------------------------------------------------------- P1: принадлежность стороны
@pytest.mark.parametrize("reopen", [0.08, 0.15])
def test_side_closed_and_reopened_manual_untouched(tmp_path, reopen):
    e, ex, _ = setup_shared(tmp_path)
    ex.external_trade(SHORT, -0.15)                      # сторона закрыта до нуля
    ex.external_trade(SHORT, reopen)                     # и открыта заново ручными
    run(e, ex, {"system": None}, n=5)                    # сигнал выхода
    assert ex.pos[SHORT] == pytest.approx(reopen)        # на 35f8b4f: 0.08 → 0.05, 0.15 → 0.05
    assert not [o for o in ex.orders.values() if o["req"]["kind"] == "STOP" and o["status"] == "UNTRIGGERED"]  # старый стоп снят


def test_require_empty_side_waits_while_manual_short(tmp_path):
    e, ex, _ = mk(tmp_path, require_empty_side=True)
    ex.external_trade(SHORT, 0.05)
    run(e, ex, {"system": d_cs()}, n=3)
    S = e.st["slots"]["system"]
    assert S["ep"] is None and T0 not in S["done"] and not e.st["orders"]
    ex.external_trade(SHORT, -0.05)                      # ручной закрыт — сторона пустая, сигнал ещё свежий
    run(e, ex, {"system": d_cs()}, n=4)
    assert S["ep"] is not None and ex.pos[SHORT] == pytest.approx(0.10)


# ---------------------------------------------------------------- P1: потерянное подтверждение → два стопа
class StaleStops(SimExchange):
    """Стоп встал, ответ потерян, а оба списка WEEX (корректные по форме) его не показывают — устаревший снимок."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.hide = False

    def order(self, symbol, cid, kind, oid="", placed_at=0.0):
        if kind == "STOP" and self.hide:
            return None
        return super().order(symbol, cid, kind, oid, placed_at)


def test_shared_account_never_auto_absent(tmp_path):
    ex = StaleStops(price=70000.0)
    e, ex, _ = mk(tmp_path, ex=ex)
    ex.external_trade(SHORT, 0.10)
    run(e, ex, {"system": d_cs()}, n=1)
    ex.hide = True
    ex.fail_next("place", "unknown_placed")
    run(e, ex, {"system": d_cs()}, n=1)
    run(e, ex, {"system": d_cs()}, n=8, dt=40)           # дольше unknown_grace_s
    stops = [r for r in e.st["orders"].values() if r["role"] == "stop"]
    assert len(stops) == 1 and stops[0]["status"] == "UNRESOLVED"   # на 35f8b4f — ABSENT и второй стоп
    ex.move(80000.0)
    assert ex.pos[SHORT] == pytest.approx(0.10)


@pytest.mark.parametrize("hist,opens", [({"hasMore": False, "orders": [{}]}, []), ({"hasMore": False, "orders": []}, [{}]),
                                        ({"hasMore": False, "orders": [{"clientAlgoId": "x"}]}, [])])
def test_weex_rows_without_id_are_incomplete(hist, opens):
    with pytest.raises(Incomplete):
        WeexExchange(FakeWeex(hist, open_algos=opens)).order("BTCUSDT", "b7hsk1", "STOP", "123", T0)


@pytest.mark.parametrize("child", [None, [], {"orderId": "456", "status": "FILLED", "executedQty": "abc"}])
def test_weex_bad_child_order_is_incomplete(child):
    algo = {"clientAlgoId": "b7hsk1", "algoId": "123", "algoStatus": "TRIGGERED", "actualOrderId": "456"}
    with pytest.raises(Incomplete):
        WeexExchange(FakeWeex({"hasMore": False, "orders": [algo]}, child=child)).order("BTCUSDT", "b7hsk1", "STOP", "123", T0)


# ---------------------------------------------------------------- добор при вооружённом стопе
class FillOnBook(SimExchange):
    """Стоп исполняется после сверки начала прохода, но до рыночного добора (на чтении стакана в этом проходе)."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.arm = False

    def book(self, symbol):
        if self.arm:
            self.arm = False
            p = self.px
            self.move(80000.0)
            self.move(p)
        return super().book(symbol)


def test_add_not_sent_after_stop_filled_in_same_pass(tmp_path):
    ex = FillOnBook(price=70000.0)
    e, ex, _ = mk(tmp_path, ex=ex, expo=Expo(14000.0), shared_account=False)
    run(e, ex, {"system": d_blue()}, n=2)
    ex.move(68000.0)
    ex.arm = True
    run(e, ex, {"system": d_blue(add_done=True)}, n=1)
    assert not [r for r in e.st["orders"].values() if r["role"] == "add" and r["filled"]]   # на 35f8b4f добор открыл 0.1029
    assert ex.pos[SHORT] == pytest.approx(0.0, abs=1e-9)


# ---------------------------------------------------------------- размер и SB
def test_live_grid_states_must_cover_all_symbols():
    with pytest.raises(ValueError):
        hg.make({"source": "weex", "symbols": ["BTCUSDT", "ETHUSDT"], "grid_states": {"ETHUSDT": ["e.json"]}}, live=True)


def test_sb_config_bad_shape_blocks_and_freezes_increases(tmp_path):
    sb = tmp_path / "sb.json"
    sb.write_text("[]")
    cfg = {"exchange": {"name": "weex", "symbol": "BTCUSDT", "paper": True, "testnet": False},
           "executor": {k: v for k, v in HCFG.items() if k != "shared_account"}, "feed": {"symbol": "BTCUSDT"},
           "hedge": {"source": 14000, "block_if_live": [str(sb)]}}

    class Feed:
        t = []

        def update(self, now):
            return 0

        def fresh(self, now):
            return False
    r = rn.Runner(cfg, tmp_path, exchange=SimExchange(), feed=Feed(), notify=lambda s: None)
    r.tick(T0)                                           # на 35f8b4f — AttributeError
    assert r.exe.cfg["enabled"] is False and r.exe.block_increase


def test_live_hedge_requires_block_if_live():
    cfg = {"exchange": {"name": "weex", "symbol": "BTCUSDT", "paper": False, "testnet": False, "share_short_with_operator": True},
           "executor": {k: v for k, v in HCFG.items() if k != "shared_account"}, "feed": {"symbol": "BTCUSDT"}, "hedge": {}}
    with pytest.raises(rn.Halt):
        rn.check_executor_cfg(cfg)


def test_block_increase_freezes_add_of_open_episode(tmp_path):
    e, ex, _ = mk(tmp_path, expo=Expo(14000.0), shared_account=False)
    run(e, ex, {"system": d_blue()}, n=2)
    e.block_increase = "SB живая"
    ex.move(68000.0)
    run(e, ex, {"system": d_blue(add_done=True)}, n=3)
    assert not [r for r in e.st["orders"].values() if r["role"] == "add" and r["filled"]]
    assert json.dumps(e.status())                         # статус читается
