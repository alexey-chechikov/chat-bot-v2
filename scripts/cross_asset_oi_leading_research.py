"""Cross-asset OI delta — does alt OI lead BTC price?

Hypothesis: when ETH/XRP open-interest changes rapidly, BTC price follows
within 15-30 minutes. If true, alt-OI-delta is a leading indicator for
BTC moves — useful for bot_brain confidence (e.g. boost R1.5 conviction
when alt-OI corroborates).

Data:
  state/deriv_live_history.jsonl  — per-symbol oi_native + oi_change_1h_pct,
    ~10 days × 3-5min cadence (limited window — findings preliminary)
  market_live/market_1m.csv       — BTC 1m close (for forward move)

Method:
  For each deriv snapshot at time T:
    - Read btc_oi_1h_pct, eth_oi_1h_pct, xrp_oi_1h_pct
    - Compute synthetic "alt_oi_delta_5m" via diff vs previous snapshot
    - Look up BTC close at T+5min, T+15min, T+30min from market_1m.csv
    - Compute forward BTC moves

  Bucket by alt-OI signal direction, compare BTC forward move distributions.

Caveats:
  - Sample is small (10 days, ~2880 snapshots, ~200 strong-signal events)
  - OI delta is noisy at sub-hour resolution
  - 2026 conditions only — different regimes may flip the lead direction

Usage:
    python scripts/cross_asset_oi_leading_research.py
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DERIV_HISTORY = ROOT / "state" / "deriv_live_history.jsonl"
MARKET_1M = ROOT / "market_live" / "market_1m.csv"


def _parse_ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _load_deriv() -> list[dict]:
    out = []
    if not DERIV_HISTORY.exists():
        return out
    with DERIV_HISTORY.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                ts_iso = rec.get("last_updated")
                if not ts_iso:
                    continue
                rec["_ts"] = _parse_ts(ts_iso)
                out.append(rec)
            except (json.JSONDecodeError, ValueError):
                continue
    out.sort(key=lambda r: r["_ts"])
    return out


def _load_btc_prices() -> list[tuple[datetime, float]]:
    out = []
    if not MARKET_1M.exists():
        return out
    with MARKET_1M.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                out.append((_parse_ts(row["ts_utc"]), float(row["close"])))
            except (ValueError, KeyError):
                continue
    out.sort()
    return out


def _price_at(prices: list[tuple[datetime, float]], target: datetime) -> Optional[float]:
    lo, hi = 0, len(prices) - 1
    if not prices:
        return None
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if prices[mid][0] <= target:
            lo = mid
        else:
            hi = mid - 1
    if prices[lo][0] <= target and (target - prices[lo][0]).total_seconds() < 600:
        return prices[lo][1]
    return None


def build_dataset(deriv: list[dict], prices: list[tuple[datetime, float]]) -> list[dict]:
    """For each deriv snapshot, attach forward BTC moves."""
    out = []
    for row in deriv:
        ts = row["_ts"]
        btc = row.get("BTCUSDT", {}) or {}
        eth = row.get("ETHUSDT", {}) or {}
        xrp = row.get("XRPUSDT", {}) or {}

        btc_oi = btc.get("oi_change_1h_pct")
        eth_oi = eth.get("oi_change_1h_pct")
        xrp_oi = xrp.get("oi_change_1h_pct")
        if btc_oi is None or eth_oi is None or xrp_oi is None:
            continue

        p_now = _price_at(prices, ts)
        p_5m = _price_at(prices, ts + timedelta(minutes=5))
        p_15m = _price_at(prices, ts + timedelta(minutes=15))
        p_30m = _price_at(prices, ts + timedelta(minutes=30))
        if not (p_now and p_5m and p_15m and p_30m):
            continue

        out.append({
            "ts": ts,
            "btc_oi_1h": float(btc_oi),
            "eth_oi_1h": float(eth_oi),
            "xrp_oi_1h": float(xrp_oi),
            "alt_oi_avg": (float(eth_oi) + float(xrp_oi)) / 2.0,
            "btc_move_5m_pct": (p_5m - p_now) / p_now * 100.0,
            "btc_move_15m_pct": (p_15m - p_now) / p_now * 100.0,
            "btc_move_30m_pct": (p_30m - p_now) / p_now * 100.0,
        })
    return out


def bucket_analysis(dataset: list[dict], signal_key: str, label: str) -> None:
    """Bucket dataset by `signal_key` quintiles, report mean BTC moves."""
    if not dataset:
        print(f"\n{label}: no data")
        return
    vals = np.array([r[signal_key] for r in dataset])
    quintiles = np.percentile(vals, [20, 40, 60, 80])
    print(f"\n--- {label} — n={len(dataset)} ---")
    print(f"  quintile thresholds: {quintiles.round(3).tolist()}")
    print(f"  {'bucket':12} {'n':>5} {'mean_oi':>9} {'5m':>9} {'15m':>9} {'30m':>9} {'up_30m%':>9}")
    bucket_defs = [
        ("Q1 lowest",  lambda v: v <= quintiles[0]),
        ("Q2",         lambda v: quintiles[0] < v <= quintiles[1]),
        ("Q3 middle",  lambda v: quintiles[1] < v <= quintiles[2]),
        ("Q4",         lambda v: quintiles[2] < v <= quintiles[3]),
        ("Q5 highest", lambda v: v > quintiles[3]),
    ]
    for name, pred in bucket_defs:
        sub = [r for r in dataset if pred(r[signal_key])]
        if not sub:
            continue
        n = len(sub)
        mean_oi = np.mean([r[signal_key] for r in sub])
        mean_5m = np.mean([r["btc_move_5m_pct"] for r in sub])
        mean_15m = np.mean([r["btc_move_15m_pct"] for r in sub])
        mean_30m = np.mean([r["btc_move_30m_pct"] for r in sub])
        up_30m = 100 * sum(1 for r in sub if r["btc_move_30m_pct"] > 0) / n
        print(f"  {name:12} {n:>5} {mean_oi:>+9.3f} {mean_5m:>+9.3f} "
              f"{mean_15m:>+9.3f} {mean_30m:>+9.3f} {up_30m:>8.1f}%")


def correlation_analysis(dataset: list[dict]) -> None:
    """Pairwise correlation: OI features vs BTC forward moves."""
    print(f"\n--- Pearson correlations (n={len(dataset)}) ---")
    print(f"  {'feature':18} {'vs 5m':>8} {'vs 15m':>8} {'vs 30m':>8}")
    features = ["btc_oi_1h", "eth_oi_1h", "xrp_oi_1h", "alt_oi_avg"]
    targets = ["btc_move_5m_pct", "btc_move_15m_pct", "btc_move_30m_pct"]
    for f in features:
        xs = np.array([r[f] for r in dataset])
        row = [f]
        for t in targets:
            ys = np.array([r[t] for r in dataset])
            if xs.std() > 0 and ys.std() > 0:
                corr = float(np.corrcoef(xs, ys)[0, 1])
                row.append(f"{corr:>+8.3f}")
            else:
                row.append("    nan")
        print(f"  {row[0]:18} {row[1]} {row[2]} {row[3]}")


def confluence_analysis(dataset: list[dict]) -> None:
    """When BTC + ETH + XRP all rise OR all fall together — does forward BTC
    move become more predictable?"""
    print(f"\n--- Triple-confluence (all 3 OIs same sign) ---")
    all_up = [r for r in dataset if r["btc_oi_1h"] > 0.3 and r["eth_oi_1h"] > 0.3 and r["xrp_oi_1h"] > 0.3]
    all_dn = [r for r in dataset if r["btc_oi_1h"] < -0.3 and r["eth_oi_1h"] < -0.3 and r["xrp_oi_1h"] < -0.3]
    baseline = dataset
    print(f"  {'bucket':30} {'n':>5} {'mean_30m':>10} {'up_30m%':>8}")
    for name, sub in [
        ("ALL UP (each OI > +0.3%)", all_up),
        ("ALL DOWN (each OI < -0.3%)", all_dn),
        ("baseline (all snapshots)", baseline),
    ]:
        if not sub:
            print(f"  {name:30} {0:>5}     —")
            continue
        n = len(sub)
        mean_30m = np.mean([r["btc_move_30m_pct"] for r in sub])
        up_30m = 100 * sum(1 for r in sub if r["btc_move_30m_pct"] > 0) / n
        print(f"  {name:30} {n:>5} {mean_30m:>+9.3f}% {up_30m:>7.1f}%")


def main():
    print("Loading data...")
    deriv = _load_deriv()
    prices = _load_btc_prices()
    print(f"  deriv snapshots: {len(deriv):,}")
    print(f"  btc 1m bars: {len(prices):,}")
    if not deriv or not prices:
        print("insufficient data")
        return

    dataset = build_dataset(deriv, prices)
    print(f"  joined dataset: {len(dataset):,} usable rows")
    if not dataset:
        return

    correlation_analysis(dataset)
    bucket_analysis(dataset, "btc_oi_1h", "BTC OI 1h delta (baseline)")
    bucket_analysis(dataset, "eth_oi_1h", "ETH OI 1h delta (cross-asset)")
    bucket_analysis(dataset, "xrp_oi_1h", "XRP OI 1h delta (cross-asset)")
    bucket_analysis(dataset, "alt_oi_avg", "ALT OI avg (ETH+XRP)/2")
    confluence_analysis(dataset)

    print("\n--- Interpretation guide ---")
    print("  Correlations: positive = OI delta predicts UP move; negative = predicts DOWN.")
    print("  |corr| < 0.05 = no signal. 0.05-0.10 = weak. >0.15 = meaningful (rare in OI/price).")
    print("  Q5 vs Q1 mean_30m gap shows monotonic-ish predictive power.")
    print(f"  Sample size {len(dataset)} is limited (~10d) — findings are preliminary,")
    print("  retune after 30+ days of deriv_live_history accumulated.")


if __name__ == "__main__":
    main()
