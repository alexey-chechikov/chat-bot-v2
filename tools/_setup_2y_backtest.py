"""2-year out-of-time backtest of the dip-buy edge (pdl_bounce + dump_reversal)
with the optimized exits (tp 1.5% / sl 0.5% / 2h). Runs the REAL detectors over
2y of frozen 1m price (no signal in setups.jsonl that far back), then sims exits.

regime_label approximated (4h move: >+1% trend_up[excluded for pdl], <-1%
trend_down, else range_wide). dump_reversal has no regime gate (fully faithful).
"""
import sys
from datetime import timedelta
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path("/Users/alexeychechikov/code/bot7")
sys.path.insert(0, str(ROOT))
from services.setup_detector.setup_types import (  # noqa: E402
    detect_long_pdl_bounce, detect_long_dump_reversal, DetectionContext,
    detect_short_rally_fade, detect_short_pdh_rejection, detect_short_overbought_fade,
)
try:
    from services.setup_detector.double_top_bottom import detect_double_top_setup  # noqa: E402
except Exception:
    detect_double_top_setup = None

FEES, TP, SL, HOLD_MIN = 0.165, 1.5, 0.5, 120
STEP_MIN = 15            # evaluate every 15 minutes
H1_WIN, M1_WIN = 60, 60  # bars of context


def _load(pair):
    df = pd.read_csv(ROOT / "backtests" / "frozen" / f"{pair}_1m_2y.csv")
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
    else:  # short: tp below, sl above
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

    trades = []
    last_exit_ts = None
    # step every STEP_MIN minutes
    for pos in range(M1_WIN, len(m1) - HOLD_MIN, STEP_MIN):
        t = m1_idx[pos]
        if last_exit_ts is not None and t < last_exit_ts:
            continue
        m1_win = m1.iloc[pos - M1_WIN:pos + 1]
        hpos = int(np.searchsorted(h1_idx_ns, t.value, side="right"))
        if hpos < 16:
            continue
        h1_win = h1.iloc[max(0, hpos - H1_WIN):hpos]
        price = float(cl[pos])
        reg = _regime(h1_win, price)
        ctx = DetectionContext(pair=pair, current_price=price, regime_label=reg,
                               session_label="ANY", ohlcv_1m=m1_win, ohlcv_1h=h1_win)
        dets = [(detect_long_dump_reversal, "dump_reversal", "long"),
                (detect_long_pdl_bounce, "pdl_bounce", "long"),
                (detect_short_rally_fade, "rally_fade", "short"),
                (detect_short_pdh_rejection, "pdh_rejection", "short"),
                (detect_short_overbought_fade, "overbought_fade", "short")]
        if detect_double_top_setup is not None:
            dets.append((detect_double_top_setup, "double_top", "short"))
        for fn, name, side in dets:
            try:
                s = fn(ctx)
            except Exception:
                s = None
            if s is not None:
                r = _sim_exit(cl, hi, lo, ts_ns, t, price, side=side)
                if r is not None:
                    trades.append({"ts": t, "type": name, "side": side, "pnl": r})
                    last_exit_ts = t + timedelta(minutes=HOLD_MIN)
                break  # one entry per step
    return trades


def _stats(pnls):
    n = len(pnls)
    if not n:
        return None
    wins = sum(1 for p in pnls if p > 0)
    gw = sum(p for p in pnls if p > 0); gl = -sum(p for p in pnls if p < 0)
    return n, round(wins/n*100), round(sum(pnls)/n, 3), round(gw/gl if gl else 999, 2), round(sum(pnls), 1)


def main():
    pairs = sys.argv[1:] or ["BTCUSDT"]
    for pair in pairs:
        print(f"\n===== {pair} (2y, tp{TP}/sl{SL}/{HOLD_MIN}m) =====")
        tr = run_pair(pair)
        if not tr:
            print("  no trades"); continue
        df = pd.DataFrame(tr).sort_values("ts")
        print(f"  span {df.ts.min().date()} -> {df.ts.max().date()}, trades={len(df)}")
        # by year
        df["year"] = df.ts.dt.year
        print("  by year:   ", end="")
        for y, g in df.groupby("year"):
            s = _stats(list(g["pnl"]))
            print(f"{y}: n={s[0]} WR={s[1]}% EV={s[2]} PF={s[3]} sum={s[4]}%  ", end="")
        print()
        # by half
        half = len(df) // 2
        for name, seg in (("FULL", df), ("1st half", df.iloc[:half]), ("2nd half", df.iloc[half:])):
            s = _stats(list(seg["pnl"]))
            print(f"  {name:10s} n={s[0]} WR={s[1]}% EV={s[2]}% PF={s[3]} sum={s[4]}%")
        for sd in ("long", "short"):
            seg = df[df["side"] == sd]
            s = _stats(list(seg["pnl"]))
            if s:
                print(f"  -- {sd.upper():5s} n={s[0]} WR={s[1]}% EV={s[2]}% PF={s[3]} sum={s[4]}%")
        for t in sorted(df["type"].unique()):
            s = _stats(list(df[df["type"] == t]["pnl"]))
            if s and s[0] >= 10:
                print(f"    {t:16s} n={s[0]} WR={s[1]}% EV={s[2]}% PF={s[3]} sum={s[4]}%")


if __name__ == "__main__":
    main()
