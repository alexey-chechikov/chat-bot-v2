"""Audit pause-rule effectiveness — did the pause save real DD?

For each pause proposal in state/bot_brain_proposals.jsonl, compare BTC price
at pause time to price 30 minutes later:
  - SHORT bot pause (R1, R1.5, R1.6, R5): "saved" if price went UP after pause
    (SHORT bot would have lost money in upward move while paused)
  - LONG bot pause (R2, R2.5, R2.6): "saved" if price went DOWN
  - Otherwise: "missed" — would have been better to keep grid running

Per-rule: counts saves vs misses, mean Δprice for saves vs misses, "edge over
random" (vs unconditional 30-min direction rate).

Usage:
    python scripts/bot_brain_pause_audit.py
    python scripts/bot_brain_pause_audit.py --window-min 60
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
PROPOSALS = ROOT / "state" / "bot_brain_proposals.jsonl"
MARKET_1M = ROOT / "market_live" / "market_1m.csv"

# How much price must move to consider pause "saved" vs noise
PRICE_MOVE_THRESHOLD_PCT = 0.2


def _parse_ts(s: str) -> datetime:
    if s is None:
        raise ValueError("None ts")
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _read_proposals() -> list[dict]:
    out = []
    if not PROPOSALS.exists():
        return out
    with PROPOSALS.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return out


def _build_price_index() -> list[tuple[datetime, float]]:
    """Load market_1m as (ts, close) sorted list for binary search."""
    out = []
    if not MARKET_1M.exists():
        return out
    with MARKET_1M.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                ts = _parse_ts(row["ts_utc"])
                close = float(row["close"])
                out.append((ts, close))
            except (ValueError, KeyError):
                continue
    return out


def _price_at(prices: list[tuple[datetime, float]], target: datetime) -> Optional[float]:
    """Binary search nearest price at-or-before target."""
    if not prices:
        return None
    lo, hi = 0, len(prices) - 1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if prices[mid][0] <= target:
            lo = mid
        else:
            hi = mid - 1
    if prices[lo][0] <= target:
        return prices[lo][1]
    return None


def audit(window_min: int = 30) -> dict:
    proposals = _read_proposals()
    prices = _build_price_index()
    if not proposals or not prices:
        return {"error": "no data"}

    # Only count pause proposals (skip resize/etc)
    pauses = [p for p in proposals if p.get("action") == "pause"]
    last_price_ts = prices[-1][0]

    # Per-rule aggregation
    by_rule: dict[str, dict] = {}
    for p in pauses:
        rid = p.get("rule_id", "?")
        tier = p.get("tier", "?")
        try:
            pause_ts = _parse_ts(p.get("ts"))
        except ValueError:
            continue
        future_ts = pause_ts + timedelta(minutes=window_min)
        # Skip if window not yet closed
        if future_ts > last_price_ts:
            continue
        p_at = _price_at(prices, pause_ts)
        p_future = _price_at(prices, future_ts)
        if p_at is None or p_future is None or p_at <= 0:
            continue
        move_pct = (p_future - p_at) / p_at * 100.0

        # Determine "direction this bot would lose to" — SHORT bots lose on UP move, LONG lose on DOWN
        bot_side = "short" if tier in ("T1", "T2", "T3", "TB") else "long" if tier.startswith("LONG") else "?"
        if bot_side == "short":
            saved = move_pct > PRICE_MOVE_THRESHOLD_PCT
            missed_grind = move_pct < -PRICE_MOVE_THRESHOLD_PCT
        elif bot_side == "long":
            saved = move_pct < -PRICE_MOVE_THRESHOLD_PCT
            missed_grind = move_pct > PRICE_MOVE_THRESHOLD_PCT
        else:
            continue

        slot = by_rule.setdefault(rid, {
            "n_closed": 0, "saved": 0, "missed": 0, "neutral": 0,
            "moves_saved": [], "moves_missed": [], "moves_neutral": [],
        })
        slot["n_closed"] += 1
        if saved:
            slot["saved"] += 1
            slot["moves_saved"].append(move_pct)
        elif missed_grind:
            slot["missed"] += 1
            slot["moves_missed"].append(move_pct)
        else:
            slot["neutral"] += 1
            slot["moves_neutral"].append(move_pct)

    # Random baseline: how often unconditional 30-min window had move > threshold either way
    baseline_up = baseline_down = baseline_n = 0
    step = max(1, len(prices) // 1000)  # sample
    for i in range(0, len(prices) - window_min, step):
        p_at = prices[i][1]
        target_ts = prices[i][0] + timedelta(minutes=window_min)
        p_future = _price_at(prices, target_ts)
        if p_future is None:
            continue
        move = (p_future - p_at) / p_at * 100.0
        baseline_n += 1
        if move > PRICE_MOVE_THRESHOLD_PCT:
            baseline_up += 1
        elif move < -PRICE_MOVE_THRESHOLD_PCT:
            baseline_down += 1
    baseline_up_rate = baseline_up / max(baseline_n, 1)
    baseline_down_rate = baseline_down / max(baseline_n, 1)

    return {
        "window_min": window_min,
        "threshold_pct": PRICE_MOVE_THRESHOLD_PCT,
        "by_rule": by_rule,
        "baseline_up_rate": round(baseline_up_rate, 3),
        "baseline_down_rate": round(baseline_down_rate, 3),
        "baseline_n": baseline_n,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--window-min", type=int, default=30)
    args = ap.parse_args()
    r = audit(args.window_min)
    if r.get("error"):
        print(r["error"])
        return
    print(f"=== Bot-Brain pause audit (window={r['window_min']}min, threshold ±{r['threshold_pct']}%) ===")
    print(f"Baseline (unconditional): up rate {r['baseline_up_rate']*100:.1f}% / "
          f"down rate {r['baseline_down_rate']*100:.1f}% (n={r['baseline_n']})")
    print()
    print(f"{'rule':32}  {'closed':>6}  {'saved':>5}  {'missed':>6}  {'neutral':>7}  "
          f"{'save%':>6}  {'mean_saved%':>11}  {'mean_missed%':>12}")
    for rid, s in sorted(r["by_rule"].items()):
        n = s["n_closed"]
        if n == 0:
            continue
        save_pct = 100 * s["saved"] / n
        ms = sum(s["moves_saved"]) / max(len(s["moves_saved"]), 1)
        mm = sum(s["moves_missed"]) / max(len(s["moves_missed"]), 1)
        print(f"{rid:32}  {n:>6}  {s['saved']:>5}  {s['missed']:>6}  {s['neutral']:>7}  "
              f"{save_pct:>5.1f}%  {ms:>+10.3f}%  {mm:>+11.3f}%")
    print()
    print("Note: 'saved' = price moved against bot direction by ≥ threshold after pause.")
    print("      'missed' = price moved with bot direction (would have ground PnL while paused).")
    print("      'neutral' = small price move within ±threshold.")


if __name__ == "__main__":
    main()
