"""Range Hunter × VPVR proximity backtest.

Hypothesis: signals where buy_level snaps to VAL (volume area low) AND
sell_level snaps to VAH (volume area high) have higher fill rate / WR /
PnL than fallback symmetric levels (±width% from mid).

Method:
1. Walk 2y 1m data, at each hour evaluate RH signal condition (BEST params).
2. If signal fires, compute rolling 24h VPVR (POC/VAH/VAL) from previous bars.
3. Compute proximity_score:
   - 0.0: VAL>=mid or VAH<=mid (no useful snap), use mid_symmetric
   - 0.5: only one side snaps (e.g. VAL within 2× width but VAH not)
   - 1.0: both VAL and VAH snap (within 2× width)
4. Simulate trade using snapped levels (or symmetric fallback).
5. Bucket outcomes by proximity_score, compare vs baseline.

Usage:
    python scripts/range_hunter_vpvr_proximity.py [--symbol BTCUSDT] [--days 730]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import range_hunter_backtest as rh  # type: ignore

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "backtests/frozen"

VPVR_WINDOW_BARS = 24 * 60  # 24h
VPVR_BINS = 50
VA_FRACTION = 0.70  # standard 70% value area

# Best RH params (matches walkforward.BEST)
BEST = dict(
    lookback_h=4, range_max_pct=0.70, atr_pct_max=0.10, cooldown_h=2,
    width_pct=0.10, hold_h=6, size_usd=10000.0, stop_loss_pct=0.20, contract="linear",
)


def load_price(symbol: str) -> pd.DataFrame:
    csv = DATA_DIR / f"{symbol}_1m_2y.csv"
    df = pd.read_csv(csv, usecols=["ts", "open", "high", "low", "close", "volume"])
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return df.sort_values("ts").reset_index(drop=True)


def compute_vpvr(window: pd.DataFrame, n_bins: int = VPVR_BINS) -> tuple[float, float, float]:
    """Return (POC, VAH, VAL) for OHLCV window using bin-based volume profile."""
    if len(window) < 60:
        return (np.nan, np.nan, np.nan)
    typical = (window["high"] + window["low"] + window["close"]) / 3.0
    vols = window["volume"].values
    lo, hi = float(typical.min()), float(typical.max())
    if hi <= lo:
        return (float(typical.iloc[-1]),) * 3
    edges = np.linspace(lo, hi, n_bins + 1)
    idx = np.clip(np.searchsorted(edges, typical.values, side="right") - 1, 0, n_bins - 1)
    bin_vol = np.zeros(n_bins)
    np.add.at(bin_vol, idx, vols)
    if bin_vol.sum() == 0:
        return (float(typical.iloc[-1]),) * 3
    poc_idx = int(np.argmax(bin_vol))
    total = bin_vol.sum()
    # Expand VA around POC until >= VA_FRACTION
    lo_i, hi_i = poc_idx, poc_idx
    acc = bin_vol[poc_idx]
    while acc / total < VA_FRACTION and (lo_i > 0 or hi_i < n_bins - 1):
        left_vol = bin_vol[lo_i - 1] if lo_i > 0 else -1
        right_vol = bin_vol[hi_i + 1] if hi_i < n_bins - 1 else -1
        if right_vol >= left_vol:
            hi_i += 1
            acc += bin_vol[hi_i]
        else:
            lo_i -= 1
            acc += bin_vol[lo_i]
    poc = (edges[poc_idx] + edges[poc_idx + 1]) / 2.0
    vah = edges[hi_i + 1]
    val = edges[lo_i]
    return (poc, vah, val)


def compute_levels(mid: float, width_pct: float, val: float, vah: float
                   ) -> tuple[float, float, str, float]:
    """Return (buy_level, sell_level, levels_source, proximity_score).
    Same logic as services/range_hunter/signal.py."""
    buy = mid * (1.0 - width_pct / 100.0)
    sell = mid * (1.0 + width_pct / 100.0)
    levels_source = "mid_symmetric"
    proximity_score = 0.0
    if np.isnan(val) or np.isnan(vah):
        return buy, sell, levels_source, proximity_score
    max_offset = mid * width_pct * 2 / 100.0
    snaps = 0
    new_buy, new_sell = buy, sell
    if not np.isnan(val) and abs(mid - val) <= max_offset and val < mid:
        new_buy = float(val)
        snaps += 1
    if not np.isnan(vah) and abs(vah - mid) <= max_offset and vah > mid:
        new_sell = float(vah)
        snaps += 1
    if new_buy != buy or new_sell != sell:
        return new_buy, new_sell, "vpvr_snap", snaps / 2.0
    return buy, sell, levels_source, proximity_score


def simulate_trade(df: pd.DataFrame, start_idx: int, p: rh.Params,
                   buy: float, sell: float) -> dict:
    """Simulate using EXPLICIT buy/sell levels (don't recompute from width_pct)."""
    end_idx = start_idx + p.hold_h * 60
    if end_idx >= len(df):
        return {"outcome": "incomplete", "pnl_usd": 0.0}
    mid0 = float(df.iloc[start_idx]["close"])
    buy_filled_at = sell_filled_at = None
    buy_fill_price = sell_fill_price = None
    for i in range(start_idx + 1, end_idx + 1):
        bar = df.iloc[i]
        if buy_filled_at is None and bar["low"] <= buy:
            buy_filled_at, buy_fill_price = i, buy
        if sell_filled_at is None and bar["high"] >= sell:
            sell_filled_at, sell_fill_price = i, sell
        if buy_filled_at and sell_filled_at:
            break
    size_btc = p.size_usd / mid0
    maker_pct = rh.MAKER_BP[p.contract] / 10000.0
    taker_pct = rh.TAKER_BP[p.contract] / 10000.0

    def pair_pnl(b, s):
        return size_btc * (s - b) + 2 * p.size_usd * (-maker_pct)

    def single_taker(side, fp, ep):
        base = size_btc * ((ep - fp) if side == "buy" else (fp - ep))
        return base + p.size_usd * (-maker_pct) - p.size_usd * taker_pct

    if buy_filled_at and sell_filled_at:
        return {"outcome": "pair_win", "pnl_usd": pair_pnl(buy_fill_price, sell_fill_price),
                "legs": 2}
    if buy_filled_at:
        sl = buy_fill_price * (1 - p.stop_loss_pct / 100)
        hit = None
        for j in range(buy_filled_at + 1, end_idx + 1):
            if df.iloc[j]["low"] <= sl:
                hit = j; break
        if hit:
            return {"outcome": "buy_stopped",
                    "pnl_usd": single_taker("buy", buy_fill_price, sl), "legs": 1}
        return {"outcome": "buy_timeout",
                "pnl_usd": single_taker("buy", buy_fill_price, float(df.iloc[end_idx]["close"])),
                "legs": 1}
    if sell_filled_at:
        sl = sell_fill_price * (1 + p.stop_loss_pct / 100)
        hit = None
        for j in range(sell_filled_at + 1, end_idx + 1):
            if df.iloc[j]["high"] >= sl:
                hit = j; break
        if hit:
            return {"outcome": "sell_stopped",
                    "pnl_usd": single_taker("sell", sell_fill_price, sl), "legs": 1}
        return {"outcome": "sell_timeout",
                "pnl_usd": single_taker("sell", sell_fill_price, float(df.iloc[end_idx]["close"])),
                "legs": 1}
    return {"outcome": "no_fills", "pnl_usd": 0.0, "legs": 0}


def run(symbol: str = "BTCUSDT", days: int | None = None) -> pd.DataFrame:
    df = load_price(symbol)
    if days is not None:
        cutoff = df["ts"].iloc[-1] - pd.Timedelta(days=days)
        df = df[df["ts"] >= cutoff].reset_index(drop=True)
    p = rh.Params(**BEST)
    trades = []
    skip_until_idx = -1
    print(f"[{symbol}] loaded {len(df):,} bars  {df.ts.iloc[0]} → {df.ts.iloc[-1]}")
    for hour_start in range(max(p.lookback_h * 60, VPVR_WINDOW_BARS),
                            len(df) - p.hold_h * 60, 60):
        if hour_start < skip_until_idx:
            continue
        sig_window = df.iloc[hour_start - p.lookback_h * 60: hour_start + 1]
        if not rh.compute_signal(sig_window, p):
            continue
        # VPVR на предыдущих 24h
        vpvr_window = df.iloc[hour_start - VPVR_WINDOW_BARS: hour_start + 1]
        poc, vah, val = compute_vpvr(vpvr_window)
        mid0 = float(df.iloc[hour_start]["close"])
        # Two parallel trades: symmetric (baseline) and VPVR-snapped
        sym_buy, sym_sell, _, _ = compute_levels(mid0, p.width_pct, np.nan, np.nan)
        snap_buy, snap_sell, snap_src, snap_score = compute_levels(mid0, p.width_pct, val, vah)
        sym_t = simulate_trade(df, hour_start, p, sym_buy, sym_sell)
        snap_t = simulate_trade(df, hour_start, p, snap_buy, snap_sell)
        trades.append({
            "ts": df.iloc[hour_start]["ts"],
            "mid": mid0,
            "poc": poc, "vah": vah, "val": val,
            "snap_src": snap_src, "snap_score": snap_score,
            "sym_outcome": sym_t["outcome"], "sym_pnl": sym_t["pnl_usd"],
            "snap_outcome": snap_t["outcome"], "snap_pnl": snap_t["pnl_usd"],
            "sym_legs": sym_t.get("legs", 0),
            "snap_legs": snap_t.get("legs", 0),
            "snap_buy": snap_buy, "snap_sell": snap_sell,
            "sym_buy": sym_buy, "sym_sell": sym_sell,
        })
        skip_until_idx = hour_start + p.cooldown_h * 60
    return pd.DataFrame(trades)


def summarize(t: pd.DataFrame, label: str, pnl_col: str, legs_col: str,
              outcome_col: str) -> str:
    if t.empty:
        return f"{label}: n=0"
    closed = t[t[outcome_col] != "no_fills"]
    pair_wins = (t[outcome_col] == "pair_win").sum()
    total = len(t)
    wr_overall = 100 * (t[pnl_col] > 0).sum() / total if total else 0
    total_pnl = t[pnl_col].sum()
    avg_pnl = t[pnl_col].mean()
    fill_rate = (t[legs_col].sum() / (2 * total)) if total else 0
    return (f"{label}: n={total}  pair_wins={pair_wins} ({100*pair_wins/total:.1f}%)  "
            f"WR={wr_overall:.1f}%  fill_rate={fill_rate:.2%}  "
            f"total=${total_pnl:,.0f}  avg=${avg_pnl:.2f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="BTCUSDT", choices=["BTCUSDT", "ETHUSDT", "XRPUSDT"])
    ap.add_argument("--days", type=int, default=None, help="last N days (default: all)")
    args = ap.parse_args()

    t = run(args.symbol, days=args.days)
    if t.empty:
        print("no signals")
        return

    print(f"\nTotal signals: {len(t)}")
    print(f"VPVR snap distribution:")
    for s in sorted(t["snap_score"].unique()):
        n = (t["snap_score"] == s).sum()
        print(f"  score={s:.1f}  n={n}  ({100*n/len(t):.1f}%)")

    print(f"\n─── Overall: symmetric vs vpvr-snap ─────────────────────")
    print(summarize(t, "SYM ", "sym_pnl", "sym_legs", "sym_outcome"))
    print(summarize(t, "SNAP", "snap_pnl", "snap_legs", "snap_outcome"))

    print(f"\n─── Bucketed by proximity_score (SNAP trades only) ──────")
    for s in [0.0, 0.5, 1.0]:
        sub = t[t["snap_score"] == s]
        if sub.empty:
            continue
        print(summarize(sub, f"score={s}", "snap_pnl", "snap_legs", "snap_outcome"))

    print(f"\n─── Same signals, SYM PnL bucketed by would-be score ────")
    for s in [0.0, 0.5, 1.0]:
        sub = t[t["snap_score"] == s]
        if sub.empty:
            continue
        print(summarize(sub, f"score={s}", "sym_pnl", "sym_legs", "sym_outcome"))

    delta = t["snap_pnl"].sum() - t["sym_pnl"].sum()
    print(f"\nNET DELTA (snap - sym): ${delta:,.0f}  over {len(t)} signals")


if __name__ == "__main__":
    main()
