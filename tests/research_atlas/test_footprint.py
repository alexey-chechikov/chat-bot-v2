"""Footprint ATLAS 14.10 (docs/ATLAS_FOOTPRINT_PROTOCOL_2026-10-14.md): свечи из сделок, фитили, правило F, пороги.

Синтетика без сети, без архивов биржи и без живого кода.
"""
from __future__ import annotations

import io
import zipfile

import numpy as np
import pandas as pd
import pytest

from tests.research_atlas import atlas_fx as fx  # noqa: F401  (пути research/gold и research/atlas_data)

import footprint_bars as fbars  # noqa: E402
import footprint_test as ft  # noqa: E402
import sweep_backtest as sb  # noqa: E402

HDR = "agg_trade_id,price,quantity,first_trade_id,last_trade_id,transact_time,is_buyer_maker\n"
T0 = 20_000 * sb.DAY                                     # начало UTC-дня = начало 15m-свечи


def _csv(rows, header: bool = True) -> bytes:
    """rows: (agg_id, price, qty, t_ms, is_buyer_maker)."""
    body = "".join(f"{a},{p},{q},{10 * a},{10 * a + 1},{t},{'true' if m else 'false'}\n" for a, p, q, t, m in rows)
    return ((HDR if header else "") + body).encode()


# open 100 (покупка), 99 продажа, 98 покупка, 100 продажа РОВНО на min(open, close), 101 покупка, close 102 (покупка)
EDGE_ROWS = [(1, 100.0, 1.0, T0 + 1, False), (2, 99.0, 2.0, T0 + 2, True), (3, 98.0, 0.5, T0 + 3, False),
             (4, 100.0, 3.0, T0 + 4, True), (5, 101.0, 1.0, T0 + 5, False), (6, 102.0, 0.25, T0 + 6, False)]


def test_header_detected_and_aggressor_sign():
    with_h = fbars.parse_trades(_csv(EDGE_ROWS, header=True))
    no_h = fbars.parse_trades(_csv(EDGE_ROWS, header=False))
    assert with_h["header"] and not no_h["header"]
    assert len(with_h["t"]) == len(no_h["t"]) == 6
    # is_buyer_maker = true → агрессор продавец (buy = False)
    assert with_h["buy"].tolist() == [True, False, True, False, True, True]
    assert np.array_equal(with_h["px"], no_h["px"])
    assert with_h["n_tr"].tolist() == [2] * 6


def test_bad_aggressor_flag_raises():
    raw = _csv(EDGE_ROWS).replace(b",true\n", b",maybe\n", 1)
    with pytest.raises(ValueError):
        fbars.parse_trades(raw)


def test_time_order_and_tie_break_by_agg_id(tmp_path):
    rows = [(5, 101.0, 1.0, T0 + 50, False), (3, 99.0, 1.0, T0 + 10, True), (4, 100.0, 1.0, T0 + 10, False)]
    p = tmp_path / "X-aggTrades-2024-10-04.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("X-aggTrades-2024-10-04.csv", _csv(rows))
    tr, sha = fbars.read_zip(p)
    assert len(sha) == 64
    assert tr["px"].tolist() == [99.0, 100.0, 101.0]            # время, затем agg_trade_id
    b = fbars.bar_agg(tr)
    assert (b.o.iloc[0], b.c.iloc[0], b.h.iloc[0], b.l.iloc[0]) == (99.0, 101.0, 101.0, 99.0)


def test_wick_assignment_includes_trades_at_body_edge():
    b = fbars.bar_agg(fbars.parse_trades(_csv(EDGE_ROWS))).iloc[0]
    assert (b.o, b.c, b.h, b.l) == (100.0, 102.0, 102.0, 98.0)
    assert b.volume == pytest.approx(7.75) and b.buy == pytest.approx(2.75) and b.sell == pytest.approx(5.0)
    # нижний фитиль: цена ≤ 100 — open (1 пок.), 99 (2 прод.), 98 (0.5 пок.), 100 (3 прод., ровно на краю)
    assert b.lw_buy == pytest.approx(1.5) and b.lw_sell == pytest.approx(5.0)
    assert (b.lw_n, b.lw_strict_n) == (4, 2)
    # верхний: цена ≥ 102 — только close; строго выше тела сделок нет → фитиль пустой
    assert b.uw_buy == pytest.approx(0.25) and b.uw_sell == 0.0
    assert (b.uw_n, b.uw_strict_n) == (1, 0)
    fb = ft.FootBars(pd.DataFrame([b]), n_days=1)
    assert fb.wl[0] == pytest.approx((1.5 - 5.0) / 7.75)
    assert np.isnan(fb.wu[0])                                    # пустой фитиль — нет wu


def test_doji_edge_trade_counts_in_both_wicks():
    rows = [(1, 100.0, 1.0, T0 + 1, True), (2, 99.0, 1.0, T0 + 2, True), (3, 101.0, 1.0, T0 + 3, False),
            (4, 100.0, 2.0, T0 + 4, False)]
    b = fbars.bar_agg(fbars.parse_trades(_csv(rows))).iloc[0]
    assert b.o == b.c == 100.0
    assert (b.lw_buy, b.lw_sell, b.lw_strict_n) == (2.0, 2.0, 1)
    assert (b.uw_buy, b.uw_sell, b.uw_strict_n) == (3.0, 1.0, 1)


def test_minute_agg_sums_buyer_aggressor():
    rows = [(1, 100.0, 1.0, T0 + 1, False), (2, 100.0, 2.0, T0 + 2, True), (3, 101.0, 4.0, T0 + sb.MIN + 1, False)]
    m = fbars.minute_agg(fbars.parse_trades(_csv(rows)))
    assert m.ts.tolist() == [T0, T0 + sb.MIN]
    assert m.volume.tolist() == [3.0, 4.0] and m.buy.tolist() == [1.0, 4.0]


def test_rel_err_and_integrity_gate():
    assert fbars.rel_err([1.0, 0.0, 1.0], [1.0, 0.0, 0.0]).tolist() == [0.0, 0.0, np.inf]
    ts = T0 + sb.MIN * np.arange(10)
    mins = pd.DataFrame({"ts": ts, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 10.0, "buy": 4.0,
                         "n_trades": 3})
    kl = mins.rename(columns={"buy": "taker_buy"}).copy()
    ok = fbars.integrity(mins, kl, T0, T0 + 10 * sb.MIN)
    assert ok["ok"] and ok["compared"] == 10 and ok["taker_buy"]["max"] == 0.0
    kl2 = kl.copy()
    kl2.loc[0, "taker_buy"] = 8.0                                 # агрессор перепутан в одной минуте из 10
    bad = fbars.integrity(mins, kl2, T0, T0 + 10 * sb.MIN)
    assert not bad["ok"] and bad["taker_buy"]["n_gt_1pct"] == 1


# ---------- пороги и правило F на синтетических свечах ----------

def _bars(n_days: int, seed: int = 0) -> pd.DataFrame:
    """n_days полных дней по 96 свечей; у всех свечей непустые фитили, wl/wu — случайные."""
    rng = np.random.default_rng(seed)
    n = n_days * 96
    bar_ts = T0 + sb.BAR * np.arange(n)
    up = rng.random(n) < 0.5
    o = np.where(up, 100.0, 100.5)
    c = np.where(up, 100.5, 100.0)
    vol = np.full(n, 10.0)
    lw_s = rng.uniform(0, 5, n)
    uw_b = rng.uniform(0, 5, n)
    return pd.DataFrame({"bar_ts": bar_ts, "o": o, "h": 101.0, "l": 99.0, "c": c, "volume": vol, "buy": 5.0,
                         "sell": 5.0, "lw_buy": 0.5, "lw_sell": lw_s, "uw_buy": uw_b, "uw_sell": 0.5, "lw_n": 2,
                         "lw_strict_n": 1, "uw_n": 2, "uw_strict_n": 1, "n_agg": 4, "n_trades": 4})


def _wl(df):
    return (df.lw_buy - df.lw_sell) / df.volume


def test_thresholds_past_only_rolling_20_days():
    df = _bars(22)
    fb = ft.FootBars(df)
    day = fb.bar_day - fb.bar_day[0]
    assert np.all(np.isnan(fb.p10[day < 20])) and np.all(np.isfinite(fb.p10[day >= 20]))
    exp21 = np.quantile(_wl(df)[day < 20], 0.10)
    assert np.allclose(fb.p10[day == 20], exp21)
    exp22 = np.quantile(_wl(df)[(day >= 1) & (day < 21)], 0.10)
    assert np.allclose(fb.p10[day == 21], exp22)
    # свой день и будущее не влияют на порог дня 20
    df2 = df.copy()
    df2.loc[day >= 20, "lw_sell"] = 0.0
    assert np.allclose(ft.FootBars(df2).p10[day == 20], fb.p10[day == 20])
    # день 0 — в окне дня 20 (порог меняется), но уже не в окне дня 21
    df3 = df.copy()
    df3.loc[day == 0, "lw_sell"] = 9.9
    fb3 = ft.FootBars(df3)
    assert not np.allclose(fb3.p10[day == 20], fb.p10[day == 20])
    assert np.allclose(fb3.p10[day == 21], fb.p10[day == 21])


def test_incomplete_day_skipped_in_threshold_window():
    df = _bars(22)
    day = (df.bar_ts.to_numpy() - T0) // sb.DAY
    df = df[~((day == 5) & (np.arange(len(df)) % 96 == 10))].reset_index(drop=True)   # день 5 без одной свечи
    fb = ft.FootBars(df)
    d = fb.bar_day - fb.bar_day[0]
    assert np.all(np.isnan(fb.p10[d == 20]))                     # полных дней до дня 20 — только 19
    full = np.isin(d, [x for x in range(21) if x != 5])
    assert np.allclose(fb.p10[d == 21], np.quantile(_wl(df)[full], 0.10))


def test_empty_wick_gives_no_signal_and_is_excluded_from_threshold():
    df = _bars(21)
    day = (df.bar_ts.to_numpy() - T0) // sb.DAY
    # в прошлых днях — свечи с пустым нижним фитилём и огромными продажами на краю тела: в порог не входят
    past_empty = (day < 20) & (np.arange(len(df)) % 7 == 0)
    df.loc[past_empty, "l"] = np.minimum(df.o, df.c)[past_empty]
    df.loc[past_empty, "lw_strict_n"] = 0
    df.loc[past_empty, "lw_sell"] = 1000.0
    # сигнальный день: свеча вверх, продажи на краю тела огромные, но фитиля нет
    k = int(np.flatnonzero((day == 20) & (df.c > df.o).to_numpy())[0])
    df.loc[k, ["l", "lw_strict_n", "lw_sell"]] = [100.0, 0, 1000.0]
    fb = ft.FootBars(df)
    side, _ = ft.f_signal(fb)
    assert np.isnan(fb.wl[k]) and side[k] == 0
    keep = (day < 20) & ~past_empty
    assert np.allclose(fb.p10[day == 20], np.quantile(_wl(df)[keep], 0.10))
    # контроль: та же свеча с непустым фитилём — LONG
    df.loc[k, ["l", "lw_strict_n"]] = [99.0, 1]
    side2, _ = ft.f_signal(ft.FootBars(df))
    assert side2[k] == 1


def test_f_rule_sides_and_doji():
    df = _bars(21)
    day = (df.bar_ts.to_numpy() - T0) // sb.DAY
    i_up, i_dn, i_dj = (int(x) for x in np.flatnonzero(day == 20)[:3])
    for i, (o, c) in ((i_up, (100.0, 100.5)), (i_dn, (100.5, 100.0)), (i_dj, (100.2, 100.2))):
        df.loc[i, ["o", "c", "lw_sell", "uw_buy"]] = [o, c, 50.0, 50.0]   # обе крайние: wl ≤ P10 и wu ≥ P90
    fb = ft.FootBars(df)
    side, both = ft.f_signal(fb)
    assert side[i_up] == 1                                       # wl ≤ P10, close ≥ open → LONG
    assert side[i_dn] == -1                                      # wu ≥ P90, close ≤ open → SHORT
    assert side[i_dj] == 0 and both[i_dj]                        # доджи в обоих условиях — без сигнала
    # без крайней дельты сигнала нет
    df.loc[i_up, "lw_sell"] = 0.0
    assert ft.f_signal(ft.FootBars(df))[0][i_up] == 0


def test_open_at_entry_exit_and_one_position():
    b_id = np.array([0, 1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 12, 13], dtype=np.int64)   # свечи 8 нет
    b_o = 100.0 + b_id
    px_in, px_out = ft.open_at(b_id, b_o, 1), ft.open_at(b_id, b_o, 1 + ft.HOLD)
    assert px_in[0] == 101.0 and px_out[0] == 105.0
    assert np.isnan(px_out[b_id == 3][0])                         # свеча 3 + 5 = 8 — её нет
    assert np.isnan(px_in[b_id == 7][0])                          # свеча 7 + 1 = 8 — её нет
    side = np.zeros(len(b_id), dtype=np.int8)
    side[[3, 4, 6]] = 1                    # 3 — без свечи выхода; 4 — сделка (выход 9); 6 — внутри позиции
    vol = np.full(len(b_id), 0.01)
    r = ft.evaluate(b_id, side, px_in, px_out, vol, np.ones(len(b_id), bool), np.ones(len(b_id), bool),
                    split_ts=int(10 * sb.BAR), n_ctl=9)
    assert r["signals"]["busy"] == 1 and r["signals"]["no_fill"] == 1
    assert [t["sig_ts"] // sb.BAR for t in r["trades"]] == [4]
    t = r["trades"][0]
    assert (t["entry"], t["exit"]) == (105.0, 109.0) and t["gross"] == pytest.approx(4.0 / 105.0)
    assert t["net"] == pytest.approx(float(ft.d1.trade_return(105.0, 109.0, 1.0, ft.SLIP, ft.TAKER)))


def test_window_masks_signals_outside():
    b_id = np.arange(30, dtype=np.int64)
    b_o = np.full(30, 100.0)
    side = np.zeros(30, dtype=np.int8)
    side[[2, 20]] = -1
    win = b_id >= 10
    r = ft.evaluate(b_id, side, ft.open_at(b_id, b_o, 1), ft.open_at(b_id, b_o, 5), np.full(30, 0.01), win,
                    np.ones(30, bool), split_ts=int(25 * sb.BAR), n_ctl=9)
    assert r["signals"]["all"] == 1 and [t["sig_ts"] // sb.BAR for t in r["trades"]] == [20]


def test_overlap_counts_same_bar_same_side():
    f = np.array([1, 1, -1, 0, -1])
    t = np.array([1, 0, -1, 1, 1])
    up = np.array([True, True, False, True, True])
    ov = ft.overlap(f, t, up, ~up)
    assert ov["LONG"]["both"] == 1 and ov["LONG"]["F"] == 2 and ov["SHORT"]["both"] == 1
    assert ov["all"]["share_of_F"] == pytest.approx(2 / 4)


def test_window_split_is_70pct_of_signal_window():
    s = ft.window_split("2026-09-08", "2026-10-13")
    t0 = ft.day_of("2026-09-08") * sb.DAY
    t1 = (ft.day_of("2026-10-13") + 1) * sb.DAY - sb.MIN
    assert s == int(t0 + 0.7 * (t1 - t0))
    assert pd.Timestamp(s, unit="ms").strftime("%Y-%m-%d") == "2026-10-03"


def test_zip_with_two_members_rejected(tmp_path):
    p = tmp_path / "bad.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("a.csv", _csv(EDGE_ROWS))
        z.writestr("b.csv", _csv(EDGE_ROWS))
    with pytest.raises(ValueError):
        fbars.read_zip(p)


def test_parse_microsecond_timestamps():
    rows = [(1, 100.0, 1.0, (T0 + 5) * 1000, False)]
    tr = fbars.parse_trades(_csv(rows))
    assert tr["unit"] == "us" and tr["t"][0] == T0 + 5


def test_bytesio_roundtrip_of_bar_csv():
    b = fbars.bar_agg(fbars.parse_trades(_csv(EDGE_ROWS)))
    buf = io.StringIO()
    b[fbars.BAR_COLS].to_csv(buf, index=False)
    back = pd.read_csv(io.StringIO(buf.getvalue()))
    fb = ft.FootBars(back, n_days=1)
    assert fb.lw_ok[0] and not fb.uw_ok[0]
