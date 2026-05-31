"""2-year backtest: does a 4h-trend directional filter rescue the setups?

Operator's hypothesis (2026-05-31, inspired by Jesse/Opus video): the reason
every setup bled over 2y is that we fought the trend. Gate it: in a 4h UPtrend
take ONLY longs; in a 4h DOWNtrend take ONLY shorts. Compare head-to-head:
  - NOFILTER : every signal fires (what Mac's _setup_2y_backtest.py measured)
  - TRENDGATE: signal fires only if its side agrees with the 4h trend

Runs the REAL detectors over frozen 2y 1m price. Fees + exits identical to Mac's
harness so the only difference is the gate. Truth, not paper.

Usage:  python tools/_setup_trend_filter_2y.py BTCUSDT [ETHUSDT ...]
"""
import sys
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.setup_detector.setup_types import (  # noqa: E402
    detect_long_pdl_bounce, detect_long_dump_reversal, DetectionContext,
    detect_short_rally_fade, detect_short_pdh_rejection, detect_short_overbought_fade,
)
try:
    from services.setup_detector.double_top_bottom import detect_double_top_setup  # noqa: E402
except Exception:
    detect_double_top_setup = None

# identical exit/fee model to Mac's reverted-to-prod harness
FEES, TP, SL, HOLD_MIN = 0.165, 1.5, 0.5, 120
STEP_MIN = 15
H1_WIN, M1_WIN = 60, 60
FROZEN = ROOT / "backtests" / "frozen"

# 4h trend gate threshold: pct change of price vs price 4h-ago (on 1h closes)
TREND_LOOKBACK_H = 16   # 16 1h-bars ~ recent 4h*4 swing window
TREND_THRESH = 0.5      # >|0.5%| over the window = a directional trend


def _load(pair):
    df = pd.read_csv(FROZEN / f"{pair}_1m_2y.csv")
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return df.set_index("ts")[["open", "high", "low", "close", "volume"]].sort_index()


def _regime(h1: pd.DataFrame, price: float) -> str:
    if len(h1) < 5:
        return "range_wide"
    p4 = float(h1["close"].iloc[-5])
    chg = (price / p4 - 1) * 100 if p4 else 0
    if chg > 1.0:
        return "trend_up"
    if chg < -1.0:
        return "trend_down"
    return "range_wide"


def _trend_4h(h1: pd.DataFrame, price: float) -> str:
    """Coarse 4h trend: price now vs price TREND_LOOKBACK_H 1h-bars ago."""
    if len(h1) < TREND_LOOKBACK_H + 1:
        return "flat"
    p0 = float(h1["close"].iloc[-TREND_LOOKBACK_H])
    if not p0:
        return "flat"
    chg = (price / p0 - 1) * 100
    if chg > TREND_THRESH:
        return "up"
    if chg < -TREND_THRESH:
        return "down"
    return "flat"


def _sim_exit(m1_all, hi, lo, ts_ns, t_entry, entry, side="long"):
    pos = int(np.searchsorted(ts_ns, t_entry.value, side="left"))
    end = pos + HOLD_MIN
    if pos >= len(hi) or end > len(hi):
        return None
    if side == "long":
        tp, sl = entry * (1 + TP / 100), entry * (1 - SL / 100)
        for i in range(pos, end):
            if lo[i] <= sl:
                return -SL - FEES
            if hi[i] >= tp:
                return TP - FEES
        return (float(m1_all[end - 1]) / entry - 1) * 100 - FEES
    else:
        tp, sl = entry * (1 - TP / 100), entry * (1 + SL / 100)
        for i in range(pos, end):
            if hi[i] >= sl:
                return -SL - FEES
            if lo[i] <= tp:
                return TP - FEES
        return (entry / float(m1_all[end - 1]) - 1) * 100 - FEES


def run_pair(pair):
    m1 = _load(pair)
    h1 = m1.resample("1h").agg({"open": "first", "high": "max", "low": "min",
                                "close": "last", "volume": "sum"}).dropna()
    ts_ns = m1.index.astype("int64").to_numpy()
    hi = m1["high"].to_numpy(float); lo = m1["low"].to_numpy(float)
    cl = m1["close"].to_numpy(float)
    h1_idx_ns = h1.index.astype("int64").to_numpy()
    m1_idx = m1.index

    # two independent trade books — same signals, different gate
    books = {"NOFILTER": [], "TRENDGATE": []}
    last_exit = {"NOFILTER": None, "TRENDGATE": None}

    for pos in range(M1_WIN, len(m1) - HOLD_MIN, STEP_MIN):
        t = m1_idx[pos]
        m1_win = m1.iloc[pos - M1_WIN:pos + 1]
        hpos = int(np.searchsorted(h1_idx_ns, t.value, side="right"))
        if hpos < TREND_LOOKBACK_H + 2:
            continue
        h1_win = h1.iloc[max(0, hpos - H1_WIN):hpos]
        price = float(cl[pos])
        reg = _regime(h1_win, price)
        trend = _trend_4h(h1_win, price)
        ctx = DetectionContext(pair=pair, current_price=price, regime_label=reg,
                               session_label="ANY", ohlcv_1m=m1_win, ohlcv_1h=h1_win)
        dets = [(detect_long_dump_reversal, "dump_reversal", "long"),
                (detect_long_pdl_bounce, "pdl_bounce", "long"),
                (detect_short_rally_fade, "rally_fade", "short"),
                (detect_short_pdh_rejection, "pdh_rejection", "short"),
                (detect_short_overbought_fade, "overbought_fade", "short")]
        if detect_double_top_setup is not None:
            dets.append((detect_double_top_setup, "double_top", "short"))

        fired = None
        for fn, name, side in dets:
            try:
                s = fn(ctx)
            except Exception:
                s = None
            if s is not None:
                fired = (name, side)
                break  # one entry per step (same rule as Mac)
        if fired is None:
            continue
        name, side = fired
        r = _sim_exit(cl, hi, lo, ts_ns, t, price, side=side)
        if r is None:
            continue

        # NOFILTER book: take it always (respecting its own cooldown)
        if last_exit["NOFILTER"] is None or t >= last_exit["NOFILTER"]:
            books["NOFILTER"].append({"ts": t, "type": name, "side": side, "pnl": r})
            last_exit["NOFILTER"] = t + timedelta(minutes=HOLD_MIN)

        # TRENDGATE book: take only if side agrees with 4h trend
        agree = (side == "long" and trend == "up") or (side == "short" and trend == "down")
        if agree and (last_exit["TRENDGATE"] is None or t >= last_exit["TRENDGATE"]):
            books["TRENDGATE"].append({"ts": t, "type": name, "side": side, "pnl": r})
            last_exit["TRENDGATE"] = t + timedelta(minutes=HOLD_MIN)

    return books


def _stats(pnls):
    n = len(pnls)
    if not n:
        return None
    wins = sum(1 for p in pnls if p > 0)
    gw = sum(p for p in pnls if p > 0); gl = -sum(p for p in pnls if p < 0)
    return n, round(wins / n * 100), round(sum(pnls) / n, 3), round(gw / gl if gl else 999, 2), round(sum(pnls), 1)


def _report(label, trades):
    if not trades:
        print(f"  [{label}] no trades"); return
    df = pd.DataFrame(trades).sort_values("ts")
    df["year"] = df.ts.dt.year
    s = _stats(list(df["pnl"]))
    print(f"  [{label}] FULL  n={s[0]} WR={s[1]}% EV={s[2]}% PF={s[3]} sum={s[4]}%")
    print(f"           by year: ", end="")
    for y, g in df.groupby("year"):
        sy = _stats(list(g["pnl"]))
        print(f"{y}: n={sy[0]} EV={sy[2]} sum={sy[4]}%  ", end="")
    print()
    for sd in ("long", "short"):
        seg = df[df["side"] == sd]
        ss = _stats(list(seg["pnl"]))
        if ss:
            print(f"           -- {sd.upper():5s} n={ss[0]} WR={ss[1]}% EV={ss[2]}% sum={ss[4]}%")


def main():
    pairs = sys.argv[1:] or ["BTCUSDT"]
    for pair in pairs:
        print(f"\n===== {pair} (2y, tp{TP}/sl{SL}/{HOLD_MIN}m, trend_lb={TREND_LOOKBACK_H}h thr={TREND_THRESH}%) =====")
        books = run_pair(pair)
        _report("NOFILTER ", books["NOFILTER"])
        print()
        _report("TRENDGATE", books["TRENDGATE"])


if __name__ == "__main__":
    main()
