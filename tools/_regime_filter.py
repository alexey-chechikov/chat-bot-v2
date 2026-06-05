"""Causal range/trend regime filter for BTC 4h — a gate for the DYNAMIC GRID.

Premise (proven by the operator's GinArea forward tests): the symmetric Auto-grid
HARVESTS in range and BLEEDS in trend. The lever is a regime gate: grid ON in range,
OFF in trend. The hard part is doing it WITHOUT lookahead — hand-drawn boxes use the
future; a real-time detector cannot.

Decision is strictly CAUSAL: the state at bar i uses only data up to bar i's close
(you act on bar i+1's open). Validation metrics may look forward, but ONLY to SCORE
the detector, never to make the on/off decision.

Core measure = Kaufman Efficiency Ratio (ER) on 4h:
    ER(N) = |close[i] - close[i-N]| / sum_k |close[i-k]-close[i-k-1]|   (k=0..N-1)
ER -> 1 = clean directional move (grid's enemy); ER -> 0 = chop (grid's friend).
This is the single axis we actually care about, with one window + one threshold
(plus hysteresis). We SWEEP thresholds and pick by a GENERAL criterion (sensible
range-time + max regime separation), NOT by whether any known window is dodged.
"""
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backtests" / "frozen" / "BTCUSDT_1h_2y.csv"
MIN_DWELL = 6        # debounce: a flip must hold this many bars (~1 day) to commit
MIN_RUN_DAYS = 10    # only range windows >= this are practical to run a grid on


def load_4h() -> pd.DataFrame:
    df = pd.read_csv(SRC)
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df = df.set_index("ts")
    return df.resample("4h").agg(
        {"open": "first", "high": "max", "low": "min",
         "close": "last", "volume": "sum"}).dropna()


def efficiency_ratio(close: pd.Series, n: int) -> pd.Series:
    direction = (close - close.shift(n)).abs()
    volatility = close.diff().abs().rolling(n).sum()
    return direction / volatility.replace(0, np.nan)


def range_state(er: np.ndarray, low: float, high: float) -> np.ndarray:
    """True = RANGE (grid ON). Enter range when ER<low, leave when ER>high."""
    out = np.zeros(len(er), dtype=bool)
    state = False
    for i, e in enumerate(er):
        if np.isnan(e):
            out[i] = False
            continue
        if not state and e < low:
            state = True
        elif state and e > high:
            state = False
        out[i] = state
    return out


def debounce(raw: np.ndarray, dwell: int) -> np.ndarray:
    out = np.zeros(len(raw), dtype=bool)
    committed = False
    run_val, run_len = None, 0
    for i, r in enumerate(raw):
        if r == run_val:
            run_len += 1
        else:
            run_val, run_len = r, 1
        if run_len >= dwell:
            committed = bool(r)
        out[i] = committed
    return out


def windows(idx, mask, close):
    res, i, n = [], 0, len(mask)
    while i < n:
        if not mask[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and mask[j + 1]:
            j += 1
        net = (close[j] / close[i] - 1) * 100
        days = (idx[j] - idx[i]).total_seconds() / 86400
        res.append((idx[i], idx[j], days, net))
        i = j + 1
    return res


def build(df, n, low, high):
    er = efficiency_ratio(df["close"], n).to_numpy()
    bot_on = debounce(range_state(er, low, high), MIN_DWELL)
    bot_on[: n * 2] = False  # warmup
    return bot_on


def build_hybrid(df, don_n=20, er_n=24, er_low=0.30, reentry_dwell=12):
    """Asymmetric gate: FAST off on a sustained range break-out, SLOW back on only
    after ER stays low for `reentry_dwell` bars. Shape matches the asymmetric payoff
    (small win in range, big loss in trend) — accept the first leg, cut the rest."""
    h, l, c = df["high"], df["low"], df["close"]
    up = h.rolling(don_n).max().shift(1)
    dn = l.rolling(don_n).min().shift(1)
    brk = ((c > up) | (c < dn)).to_numpy()
    er = efficiency_ratio(c, er_n).to_numpy()
    on = np.zeros(len(df), dtype=bool)
    state = False           # start OFF during warmup
    low_streak = 0
    for i in range(len(df)):
        low_streak = low_streak + 1 if (er[i] < er_low) else 0
        if state and brk[i]:
            state = False           # break-out -> off immediately
        elif (not state) and low_streak >= reentry_dwell and not brk[i]:
            state = True            # calm restored -> back on
        on[i] = state
    on[: max(don_n, er_n) * 2] = False
    return on


def worst_on(on_w, k=5):
    return sorted(on_w, key=lambda w: -abs(w[3]))[:k]


def in_state(df, on_mask, day):
    i = df.index.get_indexer([pd.Timestamp(day, tz="UTC")], method="nearest")[0]
    return "ON" if on_mask[i] else "OFF"


def score(df, bot_on):
    close = df["close"].to_numpy(float)
    on_w = windows(df.index, bot_on, close)
    off_w = windows(df.index, ~bot_on, close)
    on_use = [w for w in on_w if w[2] >= MIN_RUN_DAYS]
    on_abs = np.mean([abs(w[3]) for w in on_w]) if on_w else 0
    off_abs = np.mean([abs(w[3]) for w in off_w]) if off_w else 0
    pct_on = 100 * bot_on.mean()
    ratio = off_abs / on_abs if on_abs else 0
    return dict(pct_on=pct_on, n_on=len(on_w), n_use=len(on_use),
                on_abs=on_abs, off_abs=off_abs, ratio=ratio,
                on_w=on_w, off_w=off_w, on_use=on_use)


def strong_moves(df, k_bars=18, thr=0.12, merge_gap_days=10):
    """Find 'bursts': |close[i]/close[i-k]-1| > thr (a ~3-day directional shock).
    Collapse consecutive burst bars into events; report event dates + the gap to
    the previous event. Answers: do strong moves arrive on a ~60-day clock?"""
    c = df["close"].to_numpy(float)
    idx = df.index
    burst = np.zeros(len(df), dtype=bool)
    for i in range(k_bars, len(df)):
        if abs(c[i] / c[i - k_bars] - 1) > thr:
            burst[i] = True
    events = []
    i = 0
    while i < len(df):
        if not burst[i]:
            i += 1
            continue
        j = i
        while j + 1 < len(df) and (idx[j + 1] - idx[j]).total_seconds() <= \
                merge_gap_days * 86400 and burst[j + 1: ].any():
            # extend while next burst bar within merge window
            nxt = np.where(burst[j + 1:])[0]
            if len(nxt) and (idx[j + 1 + nxt[0]] - idx[j]).total_seconds() <= \
                    merge_gap_days * 86400:
                j = j + 1 + nxt[0]
            else:
                break
        peak = c[i:j + 1]
        ret = (c[j] / c[i] - 1) * 100
        events.append((idx[i], idx[j], ret))
        i = j + 1
    return events


def main():
    df = load_4h()
    close = df["close"].to_numpy(float)
    print(f"Data: {df.index[0]:%Y-%m-%d} -> {df.index[-1]:%Y-%m-%d}  "
          f"({len(df)} 4h bars)\n")

    # ---- ER detector sweep + chosen ----
    grid = []
    for n in (24, 36, 48):
        for low, high in ((0.25, 0.35), (0.30, 0.40), (0.35, 0.45)):
            grid.append(((n, low, high), score(df, build(df, n, low, high))))
    elig = [(cfg, s) for cfg, s in grid if 25 <= s["pct_on"] <= 45]
    best_cfg, best = max(elig or grid, key=lambda t: t[1]["ratio"])
    n, low, high = best_cfg
    print(f">>> ER detector chosen: N={n} ER<{low}/>{high} "
          f"(range {best['pct_on']:.0f}%, separation {best['ratio']:.2f}x)\n")

    # ============ Q1: are RANGE durations ~60 days? ============
    durs = np.array([w[2] for w in best["on_w"]])
    print("=== Q1: RANGE-window DURATIONS (operator's '~60 day' hypothesis) ===")
    print(f"  windows: {len(durs)}   mean {durs.mean():.0f}d   median "
          f"{np.median(durs):.0f}d   min {durs.min():.0f}d   max {durs.max():.0f}d   "
          f"stdev {durs.std():.0f}d")
    print(f"  durations sorted: {sorted(round(x) for x in durs)}")
    near60 = ((durs >= 50) & (durs <= 70)).sum()
    print(f"  how many land in 50-70d band: {near60}/{len(durs)}  "
          f"-> {'regular ~60d' if near60 > len(durs) * 0.5 else 'NOT a 60d rhythm'}\n")

    # ============ Q2: do STRONG MOVES arrive every ~60 days? ============
    ev = strong_moves(df)
    print("=== Q2: STRONG MOVES (>12% in ~3d) and GAPS between them ===")
    print(f"{'burst start':16} {'burst end':16} {'move%':>7} {'gap since prev':>15}")
    prev_end = None
    gaps = []
    for s, e, ret in ev:
        gap = "" if prev_end is None else f"{(s - prev_end).total_seconds()/86400:.0f}d"
        if prev_end is not None:
            gaps.append((s - prev_end).total_seconds() / 86400)
        print(f"{s:%Y-%m-%d %H:%M} {e:%Y-%m-%d %H:%M} {ret:+7.1f} {gap:>15}")
        prev_end = e
    if gaps:
        g = np.array(gaps)
        print(f"\n  GAPS between bursts: mean {g.mean():.0f}d  median "
              f"{np.median(g):.0f}d  min {g.min():.0f}d  max {g.max():.0f}d  "
              f"stdev {g.std():.0f}d")
        cv = g.std() / g.mean() if g.mean() else 0
        print(f"  coefficient of variation: {cv:.2f}  "
              f"-> {'REGULAR clock (can time it)' if cv < 0.4 else 'IRREGULAR/random (cannot time it)'}\n")

    # ============ Q3: hybrid asymmetric gate — does it cut continuation? ============
    bot_on = build(df, n, low, high)
    hy = build_hybrid(df)
    hy_on_w = windows(df.index, hy, close)
    hy_pct = 100 * hy.mean()
    hy_on_abs = np.mean([abs(w[3]) for w in hy_on_w]) if hy_on_w else 0
    print("=== Q3: ASYMMETRIC HYBRID gate (fast-off on breakout, slow-on) ===")
    print(f"  range time {hy_pct:.0f}%   avg |net move| per ON window {hy_on_abs:.1f}%")
    print("  worst 5 ON windows (the gate's MISSES — big move while grid ON):")
    for s, e, days, net in worst_on(hy_on_w):
        print(f"    {s:%Y-%m-%d} -> {e:%Y-%m-%d}  {days:4.0f}d  {net:+6.1f}%")

    # ============ Q4 cliff zoom for both detectors ============
    print("\n=== ZOOM: Q4 2025 cliff (the -4824 window) ===")
    for label, mask in (("ER ", bot_on), ("HYB", hy)):
        zoom = df.loc["2025-11-10":"2025-12-25"]
        prev, line = None, []
        for ts in zoom.index:
            st = "ON" if mask[df.index.get_loc(ts)] else "OFF"
            if st != prev:
                line.append(f"{ts:%m-%d} {st}@{df.loc[ts,'close']:,.0f}")
                prev = st
        print(f"  [{label}] " + "  ".join(line))


if __name__ == "__main__":
    main()
