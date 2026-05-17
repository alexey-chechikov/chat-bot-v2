"""CVD divergence as pre-cascade co-trigger — Phase 3.4 research.

Hypothesis: when liq_cluster fires AND CVD shows divergence from price direction,
precision rises beyond 44%/67% (baseline / +taker filter).

CVD construction (approximate, from available data):
  per deriv_live snapshot at ts: taker_imbalance = (taker_buy_pct - 50) × 2 / 100
                                  ranges [-1, +1], + = buyers dominant
  CVD(ts) = cumulative sum of taker_imbalance × bar_volume (Bybit WS) up to ts.
  Divergence: price made new high but CVD didn't (bearish), or
              price made new low but CVD didn't (bullish).

Method:
  1. Build CVD per minute from market_1m.csv (BTC) + nearest-deriv-snapshot taker_buy_pct.
  2. For each liq_cluster fire, compute CVD-divergence flag at fire time:
     - Look at price/CVD over last 60min: did price make extrema while CVD didn't?
  3. Compare hit-rate (cascade within 30min) WITH vs WITHOUT divergence flag.

Output: precision lift, recommended thresholds, decision on R1.7/R2.7.

Usage:
    python scripts/cvd_pre_cascade_research.py
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
MARKET_1M = ROOT / "market_live" / "market_1m.csv"
DERIV_HISTORY = ROOT / "state" / "deriv_live_history.jsonl"
LIQ_FIRES = ROOT / "state" / "liq_pre_cascade_fires.jsonl"
CASCADES = ROOT / "state" / "cascade_accuracy.jsonl"

WINDOW_MIN = 30
CVD_LOOKBACK_MIN = 60  # window to detect divergence


def _parse_ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _read_jsonl(path: Path) -> list[dict]:
    out = []
    if not path.exists():
        return out
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return out


def _read_market() -> list[tuple[datetime, float, float, float]]:
    """Return (ts, close, volume, high, low) sorted by ts. Just close/volume here."""
    out = []
    if not MARKET_1M.exists():
        return out
    with MARKET_1M.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                ts = _parse_ts(row["ts_utc"])
                close = float(row["close"])
                volume = float(row["volume"])
                out.append((ts, close, volume))
            except (ValueError, KeyError):
                continue
    return out


def _build_cvd_index(market: list[tuple[datetime, float, float]],
                     deriv: list[dict]) -> list[tuple[datetime, float, float]]:
    """For each market bar, attach nearest-deriv taker_buy_pct → compute CVD step.
    Returns sorted list of (ts, close, cvd_cumulative)."""
    # Index deriv snapshots by ts for binary search
    deriv_sorted = []
    for d in deriv:
        ts_iso = d.get("last_updated")
        btc = d.get("BTCUSDT", {}) or {}
        taker = btc.get("taker_buy_pct")
        if ts_iso and taker is not None:
            try:
                deriv_sorted.append((_parse_ts(ts_iso), float(taker)))
            except ValueError:
                continue
    deriv_sorted.sort()
    deriv_times = [d[0] for d in deriv_sorted]

    cvd_cum = 0.0
    out = []
    for ts, close, vol in market:
        # Find nearest deriv snapshot at or before ts (use numpy bisect-like)
        if not deriv_times:
            taker_pct = 50.0
        else:
            # linear search backwards from previous index (could optimize, but n is small)
            lo, hi = 0, len(deriv_times) - 1
            best = 0
            while lo <= hi:
                mid = (lo + hi) // 2
                if deriv_times[mid] <= ts:
                    best = mid
                    lo = mid + 1
                else:
                    hi = mid - 1
            taker_pct = deriv_sorted[best][1] if deriv_sorted[best][0] <= ts else 50.0
        imbalance = (taker_pct - 50.0) * 2 / 100.0  # range [-1, +1]
        cvd_cum += imbalance * vol
        out.append((ts, close, cvd_cum))
    return out


def _detect_divergence(cvd_index: list[tuple[datetime, float, float]],
                       fire_ts: datetime, lookback_min: int = CVD_LOOKBACK_MIN
                       ) -> tuple[Optional[str], dict]:
    """At fire_ts, check if last `lookback_min` shows price/CVD divergence.

    Returns (direction, info):
      - "bearish_div": price made new high in window but CVD did NOT (sellers
                       dominant despite higher prices) → SHORT continuation
      - "bullish_div": price made new low but CVD did NOT (buyers absorbing
                       sell pressure) → LONG continuation
      - None: no divergence
    """
    # Slice window
    window_start = fire_ts - timedelta(minutes=lookback_min)
    sub = [(ts, p, c) for ts, p, c in cvd_index if window_start <= ts <= fire_ts]
    if len(sub) < 10:
        return None, {}

    prices = [s[1] for s in sub]
    cvds = [s[2] for s in sub]
    price_max_idx = int(np.argmax(prices))
    price_min_idx = int(np.argmin(prices))
    cvd_max_idx = int(np.argmax(cvds))
    cvd_min_idx = int(np.argmin(cvds))

    # Bearish divergence: price max came AFTER cvd max
    # (price kept rising but cvd already topped)
    bearish = price_max_idx > cvd_max_idx and price_max_idx > len(sub) * 0.6
    # Bullish divergence: price min came AFTER cvd min
    bullish = price_min_idx > cvd_min_idx and price_min_idx > len(sub) * 0.6

    info = {
        "price_max_t": sub[price_max_idx][0].isoformat(),
        "price_min_t": sub[price_min_idx][0].isoformat(),
        "cvd_max_t": sub[cvd_max_idx][0].isoformat(),
        "cvd_min_t": sub[cvd_min_idx][0].isoformat(),
        "price_range_pct": (prices[price_max_idx] - prices[price_min_idx]) / prices[0] * 100,
    }
    if bearish and not bullish:
        return "bearish_div", info
    if bullish and not bearish:
        return "bullish_div", info
    return None, info


def _label_fire(fire: dict, cascades: list[dict], window_min: int = WINDOW_MIN) -> bool:
    try:
        f_ts = _parse_ts(fire["ts"])
    except (ValueError, KeyError):
        return False
    f_side = fire.get("side")
    end = f_ts + timedelta(minutes=window_min)
    for c in cascades:
        try:
            c_ts = _parse_ts(c["ts"])
        except (ValueError, KeyError):
            continue
        if f_ts <= c_ts <= end and c.get("direction") == f_side:
            return True
    return False


def main():
    print("Loading data...")
    market = _read_market()
    deriv = _read_jsonl(DERIV_HISTORY)
    fires = _read_jsonl(LIQ_FIRES)
    cascades = _read_jsonl(CASCADES)
    print(f"  market 1m bars: {len(market):,}")
    print(f"  deriv snapshots: {len(deriv):,}")
    print(f"  liq fires: {len(fires)}")
    print(f"  cascades: {len(cascades)}")

    print("Building CVD index...")
    cvd_index = _build_cvd_index(market, deriv)
    print(f"  cvd points: {len(cvd_index):,}")

    print("\n=== CVD-divergence × liq_cluster analysis ===")
    rows = []
    for f in fires:
        try:
            f_ts = _parse_ts(f["ts"])
        except (ValueError, KeyError):
            continue
        div, info = _detect_divergence(cvd_index, f_ts)
        hit = _label_fire(f, cascades)
        rows.append({
            "ts": f["ts"], "side": f.get("side"),
            "divergence": div, "hit": hit,
            "price_range_pct": info.get("price_range_pct", 0),
        })

    # Baseline (no filter)
    baseline_n = len(rows)
    baseline_hits = sum(1 for r in rows if r["hit"])
    baseline_precision = baseline_hits / max(baseline_n, 1)
    print(f"\nBaseline (no CVD filter): n={baseline_n} hits={baseline_hits} "
          f"precision={baseline_precision:.3f}")

    # Per-side conditional with divergence direction match
    print()
    for side, expected_div in [("short", "bearish_div"), ("long", "bullish_div")]:
        sub = [r for r in rows if r["side"] == side]
        if not sub:
            continue
        side_baseline = sum(1 for r in sub if r["hit"]) / len(sub)
        with_div = [r for r in sub if r["divergence"] == expected_div]
        n_div = len(with_div)
        hits_div = sum(1 for r in with_div if r["hit"])
        prec_div = hits_div / max(n_div, 1) if n_div else 0
        lift = (prec_div - side_baseline) if n_div else 0
        print(f"--- {side} cluster (expected div: {expected_div}) ---")
        print(f"  Baseline {side}-side: n={len(sub)}  hits={sum(1 for r in sub if r['hit'])}  "
              f"precision={side_baseline:.3f}")
        print(f"  With CVD div: n={n_div}  hits={hits_div}  precision={prec_div:.3f}  "
              f"lift={lift:+.3f}")
        # Opposite (anti-pattern check)
        opp_div = "bullish_div" if expected_div == "bearish_div" else "bearish_div"
        opp = [r for r in sub if r["divergence"] == opp_div]
        n_opp = len(opp)
        hits_opp = sum(1 for r in opp if r["hit"])
        prec_opp = hits_opp / max(n_opp, 1) if n_opp else 0
        print(f"  With OPPOSITE div ({opp_div}): n={n_opp}  hits={hits_opp}  "
              f"precision={prec_opp:.3f}  lift={prec_opp - side_baseline:+.3f}")
        # No divergence
        none_div = [r for r in sub if r["divergence"] is None]
        if none_div:
            hits_none = sum(1 for r in none_div if r["hit"])
            prec_none = hits_none / len(none_div)
            print(f"  No divergence detected: n={len(none_div)}  hits={hits_none}  "
                  f"precision={prec_none:.3f}")
        print()


if __name__ == "__main__":
    main()
