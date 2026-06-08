"""Causal directional WINDOW segmenter for the 2-contract grid book (operator's boxes).

The operator hand-draws green (LONG) / red (SHORT) boxes on the 4h chart and wants to
run a SHORT directional grid in red windows and a LONG one in green windows, with a real
EXIT rule for "the window changed". MA cross / MA slope do NOT reproduce the boxes causally
(they lag and whipsaw -> wrong-signed windows, measured). What DOES work causally is an
ATR-reversal swing: flip the window when price reverses K*ATR from the running extreme.
That reversal IS the exit rule.

HONESTY: the segment runs start..EXTREME, so "captured to the extreme" is optimistic — you
never enter/exit at the extreme, you flip K*ATR away from it. So we ALSO report the realistic
flip-to-flip net (an always-in book that switches side on each signal) which subtracts the
K*ATR giveback at both ends. For a GRID the directional bias is the point (stay on the right
side); the flip-to-flip number is the floor a single-position trend-follower would see.

Strictly causal: the flip at bar k uses only data <= close[k].
"""
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backtests" / "frozen" / "BTCUSDT_1h_2y.csv"


def load_4h():
    df = pd.read_csv(SRC)
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df = df.set_index("ts")
    return df.resample("4h").agg({"open": "first", "high": "max", "low": "min",
                                  "close": "last", "volume": "sum"}).dropna()


def atr(df, n=14):
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def swing_windows(close, atrv, idx, K):
    """Return list of windows (dir, start_ts, end_ts, start_px, extreme_px, flip_px).
    flip_px = price at the bar where the reversal confirmed (the real entry of the NEXT
    window / exit of this one)."""
    segs = []
    state = 1
    ext = close[0]; ext_i = 0; start_i = 0
    for k in range(1, len(close)):
        if state > 0:
            if close[k] > ext:
                ext, ext_i = close[k], k
            elif close[k] < ext - K * atrv[k]:
                segs.append((1, idx[start_i], idx[ext_i], close[start_i], ext, close[k]))
                state = -1; start_i = ext_i; ext, ext_i = close[k], k
        else:
            if close[k] < ext:
                ext, ext_i = close[k], k
            elif close[k] > ext + K * atrv[k]:
                segs.append((-1, idx[start_i], idx[ext_i], close[start_i], ext, close[k]))
                state = 1; start_i = ext_i; ext, ext_i = close[k], k
    segs.append((state, idx[start_i], idx[-1], close[start_i], ext, close[-1]))
    return segs


def report(df, a, b, K, show=True):
    m = (df.index >= pd.Timestamp(a, tz="UTC")) & (df.index <= pd.Timestamp(b, tz="UTC"))
    sub = df[m]
    segs = swing_windows(sub["close"].to_numpy(float), atr(df)[m].to_numpy(float),
                         sub.index, K)
    # extreme-to-extreme (optimistic) vs flip-to-flip (realistic always-in)
    capt_ext = sum((pe / ps - 1) * 100 * d for d, s, e, ps, pe, pf in segs)
    flip_pts = [pf for *_, pf in segs]
    # flip-to-flip: hold dir d of window i from its entry flip to its exit flip
    flip_net = 0.0
    for i, (d, s, e, ps, pe, pf) in enumerate(segs):
        entry = flip_pts[i - 1] if i > 0 else ps     # entered at previous flip
        exit_ = pf                                    # exit at this window's flip
        flip_net += (exit_ / entry - 1) * 100 * d
    durs = [(e - s).total_seconds() / 86400 for d, s, e, ps, pe, pf in segs]
    if show:
        print(f"\n===== K={K}xATR  |  {a} -> {b} =====")
        print(f"  окон {len(segs)}   медиана {np.median(durs):.0f}д   "
              f"до-экстремума(оптимизм) {capt_ext:+.0f}%   "
              f"flip-to-flip(реально) {flip_net:+.0f}%")
        for d, s, e, ps, pe, pf in segs:
            days = (e - s).total_seconds() / 86400
            nm = (pe / ps - 1) * 100
            print(f"   {('LONG ' if d > 0 else 'SHORT'):5} {s:%Y-%m-%d} -> {e:%Y-%m-%d} "
                  f"{days:4.0f}д  пик {ps:7.0f}->{pe:7.0f} ({nm:+5.1f}%)  flip@{pf:7.0f}")
    return dict(n=len(segs), capt_ext=capt_ext, flip_net=flip_net,
                med=float(np.median(durs)), segs=segs)


def main():
    df = load_4h()
    print(f"Data {df.index[0]:%Y-%m-%d} -> {df.index[-1]:%Y-%m-%d}")
    # sweep K on the operator's 2024 chart window
    print("\n### How the WINDOW changes with the exit threshold K (operator's 2024 chart) ###")
    for K in (2.5, 3.5, 5.0, 7.0):
        r = report(df, "2024-03-01", "2024-11-15", K, show=False)
        print(f"  K={K}: {r['n']:2d} окон, медиана {r['med']:.0f}д, "
              f"до-пика {r['capt_ext']:+.0f}%, flip-to-flip {r['flip_net']:+.0f}%")
    # detailed view at a practical K
    report(df, "2024-06-05", "2024-10-13", 5.0)   # exactly the operator's autogrid backtest span


if __name__ == "__main__":
    main()
