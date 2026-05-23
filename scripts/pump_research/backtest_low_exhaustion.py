"""Backtest «низ истощается» (grid_coordinator down-exhaustion signal).

Two complementary studies on BTCUSDT master CSV:
  1) LIVE-FIRES baseline — replay every grid_coordinator down-fire from
     state/grid_coordinator_fires.jsonl, look up forward returns at +4h
     and +12h, split by score and by RSI bucket. Small sample (~2 weeks)
     but ground-truth: every event the live emitter would have signalled.
  2) 2-YEAR PROXY — compute Wilder RSI 14 on 15m bars from the master,
     mark every bar with RSI<20 as a candidate "oversold" event (light
     proxy for the live 6-component score), measure forward WR. Big sample
     but coarse — no MFI / cross-asset components, so it's a UPPER bound
     on noise / LOWER bound on the targeted setup's quality.

Goal: decide whether «6/6 + RSI<20» deserves promotion to a standalone
GO-setup (target ≥65% WR @4h).

Run:
    .venv/bin/python3 scripts/pump_research/backtest_low_exhaustion.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("/Users/alexeychechikov/code/bot7")
FIRES = ROOT / "state" / "grid_coordinator_fires.jsonl"
MASTER = ROOT / "data" / "pump_research" / "BTCUSDT_pump_features_1m.csv"


def _load_fires() -> pd.DataFrame:
    rows = []
    with FIRES.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                d = rec.get("details") or {}
                rows.append({
                    "ts": pd.to_datetime(rec["ts"], utc=True),
                    "direction": rec.get("direction"),
                    "score": int(rec.get("score", 0)),
                    "rsi_btc": float(d.get("rsi_btc_now", float("nan"))),
                    "mfi_btc": float(d.get("mfi_btc_now", float("nan"))),
                    "btc_close": float(d.get("btc_close", float("nan"))),
                })
            except (KeyError, ValueError, json.JSONDecodeError):
                continue
    return pd.DataFrame(rows)


def _master_1m() -> pd.DataFrame:
    df = pd.read_csv(MASTER, usecols=["ts", "close"], dtype={"ts": "int64"})
    df["dt"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return df.set_index("dt")[["close"]].sort_index()


def _fwd_return(idx: pd.DatetimeIndex, base_dt: pd.Timestamp,
                horizon_min: int, df: pd.DataFrame) -> float:
    target = base_dt + pd.Timedelta(minutes=horizon_min)
    pos = idx.searchsorted(target)
    if pos >= len(idx):
        return float("nan")
    base_pos = idx.searchsorted(base_dt)
    if base_pos >= len(idx):
        return float("nan")
    p0 = df["close"].iloc[base_pos]
    p1 = df["close"].iloc[pos]
    return (p1 - p0) / p0 * 100.0


def _wilder_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    diff = close.diff()
    up = diff.clip(lower=0)
    down = (-diff).clip(lower=0)
    # Wilder smoothing == EMA with alpha=1/period
    roll_up = up.ewm(alpha=1 / period, adjust=False).mean()
    roll_dn = down.ewm(alpha=1 / period, adjust=False).mean()
    rs = roll_up / (roll_dn + 1e-12)
    return 100 - 100 / (1 + rs)


def study_live_fires(fires: pd.DataFrame, master: pd.DataFrame) -> None:
    down = fires[fires["direction"] == "down"].copy()
    print(f"LIVE FIRES study  (down-direction only): n={len(down)}  "
          f"range {down['ts'].min()} .. {down['ts'].max()}")
    if down.empty:
        return
    down["r4h"] = down["ts"].apply(lambda t: _fwd_return(master.index, t, 240, master))
    down["r12h"] = down["ts"].apply(lambda t: _fwd_return(master.index, t, 720, master))

    print("\n=== by score (down fires) — 'up' WR = price went UP after ===")
    print(f"{'score':>6} {'n':>5} {'WR_4h':>8} {'meanΔ_4h':>10} {'WR_12h':>8} {'meanΔ_12h':>10}")
    for s in sorted(down["score"].unique()):
        sub = down[down["score"] == s].dropna(subset=["r4h"])
        if len(sub) == 0:
            continue
        wr4 = 100 * (sub["r4h"] > 0).mean()
        m4 = sub["r4h"].mean()
        sub12 = down[down["score"] == s].dropna(subset=["r12h"])
        wr12 = 100 * (sub12["r12h"] > 0).mean() if len(sub12) else float("nan")
        m12 = sub12["r12h"].mean() if len(sub12) else float("nan")
        print(f"{s:>6} {len(sub):>5} {wr4:>7.1f}% {m4:>+9.3f}% {wr12:>7.1f}% {m12:>+9.3f}%")

    print("\n=== score>=4 × RSI bucket ===")
    high = down[down["score"] >= 4].dropna(subset=["r4h", "rsi_btc"]).copy()
    bins = [(-1, 20, "RSI<20"), (20, 25, "20-25"), (25, 30, "25-30"), (30, 100, "30+")]
    for lo, hi, lbl in bins:
        sub = high[(high["rsi_btc"] > lo) & (high["rsi_btc"] <= hi)]
        if len(sub) == 0:
            continue
        wr = 100 * (sub["r4h"] > 0).mean()
        m = sub["r4h"].mean()
        print(f"  {lbl:>7}  n={len(sub):>3}  WR_4h={wr:>5.1f}%  meanΔ={m:+.3f}%")


def study_2y_proxy(master: pd.DataFrame) -> None:
    print("\n2y PROXY study  (RSI<20 on 15m bars across full master)")
    # resample to 15m
    df15 = master["close"].resample("15min").last().to_frame()
    df15["rsi"] = _wilder_rsi(df15["close"], 14)
    df15 = df15.dropna()
    # candidate events: RSI<20, dedup so consecutive low-RSI bars are one event
    df15["is_low"] = df15["rsi"] < 20
    # event = first bar of a contiguous low run
    df15["event"] = df15["is_low"] & ~df15["is_low"].shift(1).fillna(False)
    events = df15[df15["event"]].copy()
    print(f"  events: {len(events)}  range {events.index.min()} .. {events.index.max()}")
    # forward returns @4h, @12h from the event bar
    idx = master.index
    events["r4h"] = events.index.to_series().apply(
        lambda t: _fwd_return(idx, t, 240, master))
    events["r12h"] = events.index.to_series().apply(
        lambda t: _fwd_return(idx, t, 720, master))
    ev4 = events.dropna(subset=["r4h"])
    ev12 = events.dropna(subset=["r12h"])
    wr4 = 100 * (ev4["r4h"] > 0).mean()
    wr12 = 100 * (ev12["r12h"] > 0).mean()
    print(f"  WR_4h:  {wr4:.1f}%  n={len(ev4)}  meanΔ={ev4['r4h'].mean():+.3f}%")
    print(f"  WR_12h: {wr12:.1f}%  n={len(ev12)}  meanΔ={ev12['r12h'].mean():+.3f}%")
    # split by RSI depth
    print("  by RSI depth at event:")
    for lo, hi, lbl in [(0, 15, "RSI<15"), (15, 18, "15-18"), (18, 20, "18-20")]:
        sub = ev4[(ev4["rsi"] > lo) & (ev4["rsi"] <= hi)]
        if len(sub) == 0:
            continue
        wr = 100 * (sub["r4h"] > 0).mean()
        m = sub["r4h"].mean()
        print(f"    {lbl:>7}  n={len(sub):>4}  WR_4h={wr:>5.1f}%  meanΔ={m:+.3f}%")


def main() -> int:
    print(f"Loading {MASTER.name} ...")
    master = _master_1m()
    print(f"  master: {len(master):,} 1m bars  {master.index[0]} .. {master.index[-1]}")
    print(f"Loading {FIRES.name} ...")
    fires = _load_fires()
    study_live_fires(fires, master)
    study_2y_proxy(master)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
