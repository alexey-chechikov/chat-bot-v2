"""Трендовый бот ETH на WEEX (services/weex_trend) на имитаторе: вход по свежему сигналу с размером по риску,
пропуск старого эпизода, основной выход по снятию сигнала, аварийный стоп на бирже (и без повторного входа в
тот же эпизод), подтяжка стопа, потерянный ответ биржи, битый конфиг/учёт, холостой режим."""
import json
from datetime import datetime, timezone

import pytest

from services.weex_trend import engine as te


class Px:
    def __init__(self, mid=2500.0):
        self.mid = mid

    def __call__(self):
        return round(self.mid - 0.01, 2), round(self.mid + 0.01, 2)


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="seconds")


def setup(tmp_path, **cfg):
    clock = {"t": 1_800_000_000.0}
    px = Px()
    ex = te.DryTrendExchange(px, now_fn=lambda: clock["t"])
    conf = {**te.DEFAULT, "enabled": True, "dry_run": True, "poll_sec": 0, **cfg}
    sig_path = tmp_path / "sig.json"

    def make():
        return te.Trend(ex, conf, state_path=tmp_path / "st.json", journal_path=tmp_path / "j.jsonl",
                        signals_path=sig_path, now_fn=lambda: clock["t"])

    def signal(side=None, stop=None, entry_ts=None):
        data = {} if side is None else {"ETHUSDT": {"side": side, "entry_px": px.mid, "stop": stop,
                                                    "entry_ts": entry_ts or iso(clock["t"]), "exh_sent": False}}
        sig_path.write_text(json.dumps(data))
    return clock, px, ex, make, signal


def tick(make, clock, n=1):
    for _ in range(n):
        clock["t"] += 60
        make().tick()


def test_fresh_short_signal_opens_with_risk_sizing(tmp_path):
    clock, px, ex, make, signal = setup(tmp_path, risk_usd=33.0, max_notional_usd=1500.0)
    signal("SHORT", stop=2600.0)                     # стоп в 4% над ценой
    tick(make, clock, 2)
    st = json.loads((tmp_path / "st.json").read_text())
    ep = st["episode"]
    assert ep["status"] == "open" and ep["side"] == "SHORT"
    assert float(ep["qty"]) == pytest.approx(0.33, abs=0.001)          # $33 / $100 до стопа
    assert ex.pos["SHORT"] == pytest.approx(0.33, abs=0.001)
    stops = ex.open_algo_orders("ETHUSDT")
    assert len(stops) == 1 and float(stops[0]["triggerPrice"]) == pytest.approx(2600 * 1.015, abs=0.02)
    assert stops[0]["side"] == "BUY" and float(stops[0]["quantity"]) == pytest.approx(0.33)


def test_notional_cap_limits_size(tmp_path):
    clock, px, ex, make, signal = setup(tmp_path, risk_usd=33.0, max_notional_usd=500.0)
    signal("LONG", stop=2490.0)                      # стоп близко → по риску 3.3 ETH, но потолок $500
    tick(make, clock, 2)
    assert ex.pos["LONG"] == pytest.approx(0.2, abs=0.001)


def test_old_signal_is_skipped(tmp_path):
    clock, px, ex, make, signal = setup(tmp_path)
    signal("SHORT", stop=2600.0, entry_ts=iso(clock["t"] - 3 * 86400))  # эпизод трёхдневной давности
    tick(make, clock, 3)
    assert ex.pos["SHORT"] == 0 and not ex.orders
    assert "старый" in (tmp_path / "j.jsonl").read_text()


def test_signal_exit_closes_and_cancels_stop(tmp_path):
    clock, px, ex, make, signal = setup(tmp_path)
    signal("SHORT", stop=2600.0)
    tick(make, clock, 2)
    px.mid = 2400.0
    signal(None)                                     # служба сигналов сняла эпизод (закрытие 4ч за стопом)
    tick(make, clock, 2)
    st = json.loads((tmp_path / "st.json").read_text())
    assert st["episode"] is None and ex.pos["SHORT"] == pytest.approx(0)
    assert not ex.open_algo_orders("ETHUSDT")
    assert st["realized"] == pytest.approx(0.33 * (2499.99 - 2400.01), rel=1e-3) and st["n_trades"] == 1


def test_emergency_stop_closes_and_no_reentry_same_episode(tmp_path):
    clock, px, ex, make, signal = setup(tmp_path)
    signal("SHORT", stop=2600.0)
    ts0 = json.loads((tmp_path / "sig.json").read_text())["ETHUSDT"]["entry_ts"]
    tick(make, clock, 2)
    px.mid = 2700.0                                  # проскок за аварийный стоп 2639
    tick(make, clock, 2)
    st = json.loads((tmp_path / "st.json").read_text())
    assert st["episode"] is None and ex.pos["SHORT"] == pytest.approx(0)
    assert "аварийный стоп" in (tmp_path / "j.jsonl").read_text()
    signal("SHORT", stop=2800.0, entry_ts=ts0)       # тот же эпизод в службе сигналов ещё жив
    tick(make, clock, 3)
    assert ex.pos["SHORT"] == pytest.approx(0)       # повторно в тот же эпизод не входим


def test_trailing_moves_emergency_stop_only_favourably(tmp_path):
    clock, px, ex, make, signal = setup(tmp_path)
    signal("SHORT", stop=2600.0)
    ts0 = json.loads((tmp_path / "sig.json").read_text())["ETHUSDT"]["entry_ts"]
    tick(make, clock, 2)
    px.mid = 2450.0
    signal("SHORT", stop=2550.0, entry_ts=ts0)       # Chandelier опустился
    tick(make, clock, 2)
    live = ex.open_algo_orders("ETHUSDT")
    assert len(live) == 1 and float(live[0]["triggerPrice"]) == pytest.approx(2550 * 1.015, abs=0.02)
    signal("SHORT", stop=2560.0, entry_ts=ts0)       # «вверх» для шорта — не двигаем
    tick(make, clock, 2)
    assert float(ex.open_algo_orders("ETHUSDT")[0]["triggerPrice"]) == pytest.approx(2550 * 1.015, abs=0.02)


def test_lost_entry_response_no_double_entry(tmp_path):
    clock, px, ex, make, signal = setup(tmp_path)
    signal("SHORT", stop=2600.0)
    real = ex.place_market

    def lose(*a, **k):
        real(*a, **k)
        ex.place_market = real
        raise TimeoutError("read timeout")
    ex.place_market = lose
    tick(make, clock, 4)
    assert ex.pos["SHORT"] == pytest.approx(0.33, abs=0.001)          # одна позиция, не две
    assert json.loads((tmp_path / "st.json").read_text())["episode"]["status"] == "open"


def test_disabled_keeps_managing_open_position(tmp_path):
    clock, px, ex, make, signal = setup(tmp_path)
    signal("SHORT", stop=2600.0)
    tick(make, clock, 2)
    conf_off = {**make().cfg}
    st_path = tmp_path / "st.json"
    t = te.Trend(ex, {**conf_off, "enabled": False}, state_path=st_path, journal_path=tmp_path / "j.jsonl",
                 signals_path=tmp_path / "sig.json", now_fn=lambda: clock["t"])
    signal(None)
    clock["t"] += 60
    t.tick()
    clock["t"] += 60
    te.Trend(ex, {**conf_off, "enabled": False}, state_path=st_path, journal_path=tmp_path / "j.jsonl",
             signals_path=tmp_path / "sig.json", now_fn=lambda: clock["t"]).tick()
    assert ex.pos["SHORT"] == pytest.approx(0)       # выключенный бот всё равно закрыл по сигналу выхода


def test_xrp_lot_step_ten(tmp_path):
    """XRP на WEEX — лоты по 10 монет: размер по риску округляется вниз до десятков."""
    clock = {"t": 1_800_000_000.0}
    px = Px(1.40)
    ex = te.DryTrendExchange(lambda: (1.3999, 1.4001), symbol="XRPUSDT", now_fn=lambda: clock["t"])
    conf = {**te.DEFAULT, "enabled": True, "dry_run": True, "poll_sec": 0, "symbol": "XRPUSDT",
            "qty_step": 10, "price_tick": 0.0001, "risk_usd": 33.0, "max_notional_usd": 1500.0}
    sig = tmp_path / "sig.json"
    sig.write_text(json.dumps({"XRPUSDT": {"side": "SHORT", "entry_px": 1.40, "stop": 1.47,
                                           "entry_ts": iso(clock["t"]), "exh_sent": False}}))
    for _ in range(2):
        clock["t"] += 60
        te.Trend(ex, conf, state_path=tmp_path / "x.json", journal_path=tmp_path / "xj.jsonl",
                 signals_path=sig, now_fn=lambda: clock["t"]).tick()
    assert ex.pos["SHORT"] == 470                    # $33 / 0.0701 = 470.7 → 470 XRP (шаг 10)
    assert px.mid == 1.40


def test_runner_files_per_symbol():
    from services.weex_trend import loop as tl
    assert tl.files(False, "ETHUSDT")[0].name == "weex_trend_state.json"
    assert tl.files(True, "XRPUSDT")[0].name == "weex_trend_xrp_state_dry.json"
    cfg = {**te.DEFAULT, "symbols": ["ETHUSDT", "XRPUSDT"], "per_symbol": {"XRPUSDT": {"qty_step": 10}}}
    assert tl.symbol_cfg(cfg, "XRPUSDT")["qty_step"] == 10 and tl.symbol_cfg(cfg, "ETHUSDT")["qty_step"] == 0.001


def test_broken_state_halts(tmp_path):
    clock, px, ex, make, signal = setup(tmp_path)
    (tmp_path / "st.json").write_text('{"episode": {', encoding="utf-8")
    with pytest.raises(te.StateCorrupt):
        make()


def test_unreadable_signals_file_does_nothing(tmp_path):
    clock, px, ex, make, signal = setup(tmp_path)
    signal("SHORT", stop=2600.0)
    tick(make, clock, 2)
    (tmp_path / "sig.json").write_text('{"ETHUSDT": {', encoding="utf-8")   # служба сигналов пишет файл
    tick(make, clock, 2)
    assert ex.pos["SHORT"] == pytest.approx(0.33, abs=0.001)          # не закрыли по «пустому» сигналу
