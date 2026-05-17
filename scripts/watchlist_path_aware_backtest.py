"""Path-aware backtest for watchlist taker-imbalance rules (XRP taker → BTC trade).

Validates the live edge claim for `taker_imbalance_short` (XRP taker_buy < 42% →
SHORT BTC) and `taker_imbalance_long` (> 58% → LONG BTC) by simulating ACTUAL
trade outcomes with stop / TP1 / TP2 / timeout, instead of just checking forward
4h direction (which the watchlist play card currently quotes).

Data sources:
  - state/deriv_live_history.jsonl  — per-symbol taker_buy_pct timeseries (~3-5 min)
  - market_live/market_1m.csv       — BTC 1m OHLC for stop/TP path simulation

Outcomes per fire:
  - TP2_hit     — TP2 touched before stop / timeout
  - TP1_hit     — TP1 touched, then stop or timeout (without TP2)
  - SL_hit      — stop touched before TP1
  - timeout     — neither TP nor stop hit within exit_after_h

PnL accounting per trade (in % of position notional):
  - tp2_only  — all-or-nothing exit at TP2 (no scale-out)
  - scale_out — 30% at TP1 + 70% at TP2 (or BE if TP1 hit but TP2 misses, with
                stop moved to BE after TP1)

Compared against:
  - Unconditional baseline: same simulator on random sampled timestamps in the
    same window (n=200 sampling).

Usage:
    python scripts/watchlist_path_aware_backtest.py
    python scripts/watchlist_path_aware_backtest.py --rule short
    python scripts/watchlist_path_aware_backtest.py --cooldown-min 60
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator, Optional

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DERIV_HISTORY = ROOT / "state" / "deriv_live_history.jsonl"
MARKET_1M = ROOT / "market_live" / "market_1m.csv"


@dataclass
class RuleSpec:
    name: str
    signal_symbol: str        # which symbol's data feeds the rule
    field: str                # "taker_buy_pct" | "funding_rate_8h" | "top_minus_global_long"
    op: str                   # "<" or ">"
    threshold: float
    direction: str            # "SHORT" or "LONG"
    tp1_pct: float            # signed % vs entry (e.g. -0.15 for SHORT)
    tp2_pct: float
    stop_pct: float           # signed % vs entry
    exit_after_h: int
    scale_out_pct: float = 0.30


RULES: dict[str, RuleSpec] = {
    "taker_short": RuleSpec(
        name="taker_imbalance_short",
        signal_symbol="XRPUSDT", field="taker_buy_pct", op="<", threshold=42.0,
        direction="SHORT",
        tp1_pct=-0.15, tp2_pct=-0.40, stop_pct=+0.30, exit_after_h=4,
        scale_out_pct=0.30,
    ),
    "taker_long": RuleSpec(
        name="taker_imbalance_long",
        signal_symbol="XRPUSDT", field="taker_buy_pct", op=">", threshold=58.0,
        direction="LONG",
        tp1_pct=+0.27, tp2_pct=+0.63, stop_pct=-0.40, exit_after_h=4,
        scale_out_pct=0.30,
    ),
    "funding_squeeze_long": RuleSpec(
        name="funding_squeeze_long",
        signal_symbol="BTCUSDT", field="funding_rate_8h", op="<", threshold=-0.0001,
        direction="LONG",
        tp1_pct=+0.46, tp2_pct=+0.68, stop_pct=-0.40, exit_after_h=4,
        scale_out_pct=0.30,
    ),
    "topshort_div_long": RuleSpec(
        name="topshort_divergence_long",
        signal_symbol="BTCUSDT", field="top_minus_global_long", op="<", threshold=-5.0,
        direction="LONG",
        tp1_pct=+0.40, tp2_pct=+0.87, stop_pct=-0.50, exit_after_h=24,
        scale_out_pct=0.30,
    ),
    # BTC/ETH same-asset versions of taker_imbalance (XRP version is cross-asset)
    "taker_short_btc": RuleSpec(
        name="taker_imbalance_short (BTC self-signal)",
        signal_symbol="BTCUSDT", field="taker_buy_pct", op="<", threshold=42.0,
        direction="SHORT",
        tp1_pct=-0.15, tp2_pct=-0.40, stop_pct=+0.30, exit_after_h=4,
        scale_out_pct=0.30,
    ),
    "taker_long_btc": RuleSpec(
        name="taker_imbalance_long (BTC self-signal)",
        signal_symbol="BTCUSDT", field="taker_buy_pct", op=">", threshold=58.0,
        direction="LONG",
        tp1_pct=+0.27, tp2_pct=+0.63, stop_pct=-0.40, exit_after_h=4,
        scale_out_pct=0.30,
    ),
    "taker_short_eth": RuleSpec(
        name="taker_imbalance_short (ETH cross-asset → BTC)",
        signal_symbol="ETHUSDT", field="taker_buy_pct", op="<", threshold=42.0,
        direction="SHORT",
        tp1_pct=-0.15, tp2_pct=-0.40, stop_pct=+0.30, exit_after_h=4,
        scale_out_pct=0.30,
    ),
    "taker_long_eth": RuleSpec(
        name="taker_imbalance_long (ETH cross-asset → BTC)",
        signal_symbol="ETHUSDT", field="taker_buy_pct", op=">", threshold=58.0,
        direction="LONG",
        tp1_pct=+0.27, tp2_pct=+0.63, stop_pct=-0.40, exit_after_h=4,
        scale_out_pct=0.30,
    ),
}


def load_btc_1m() -> pd.DataFrame:
    df = pd.read_csv(MARKET_1M, usecols=["ts_utc", "open", "high", "low", "close"])
    df["ts"] = pd.to_datetime(df["ts_utc"], utc=True)
    df = df.drop(columns=["ts_utc"]).sort_values("ts").reset_index(drop=True)
    return df


def iter_deriv_history() -> Iterator[dict]:
    if not DERIV_HISTORY.exists():
        return
    with DERIV_HISTORY.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _extract_field(sym: dict, field: str) -> Optional[float]:
    """Get rule.field value from per-symbol deriv row. Supports synthetic fields."""
    if field == "top_minus_global_long":
        tt = sym.get("top_trader_long_pct")
        gl = sym.get("global_long_account_pct")
        if tt is None or gl is None:
            return None
        return float(tt) - float(gl)
    v = sym.get(field)
    return None if v is None else float(v)


def find_fires(rule: RuleSpec, cooldown_min: int) -> list[dict]:
    """Walk deriv history; return list of {ts, value} when rule fires.
    Cooldown: don't refire within cooldown_min after a fire."""
    out = []
    cooldown_until: Optional[datetime] = None
    for row in iter_deriv_history():
        ts_iso = row.get("last_updated")
        sym = row.get(rule.signal_symbol, {}) or {}
        v = _extract_field(sym, rule.field)
        if v is None or ts_iso is None:
            continue
        try:
            ts = datetime.fromisoformat(ts_iso)
        except ValueError:
            continue
        if cooldown_until and ts < cooldown_until:
            continue
        hit = (v < rule.threshold) if rule.op == "<" else (v > rule.threshold)
        if not hit:
            continue
        out.append({"ts": ts, "value": v})
        cooldown_until = ts + timedelta(minutes=cooldown_min)
    return out


def simulate_trade(btc: pd.DataFrame, fire_ts: datetime, rule: RuleSpec) -> Optional[dict]:
    """Simulate a single trade starting at fire_ts using BTC 1m bars.

    Direction-aware:
      SHORT: stop = entry * (1 + stop_pct/100), TPs below entry
      LONG:  stop = entry * (1 + stop_pct/100), TPs above entry
    Returns dict {outcome, tp1_first, tp2_first, sl_first, pnl_tp2_only, pnl_scale}
    or None if insufficient forward bars.
    """
    # Find first bar at or after fire_ts
    idx = btc["ts"].searchsorted(fire_ts, side="left")
    if idx >= len(btc):
        return None
    entry = float(btc["close"].iloc[idx])
    end_ts = fire_ts + timedelta(hours=rule.exit_after_h)
    end_idx = btc["ts"].searchsorted(end_ts, side="right")
    if end_idx <= idx + 1:
        return None
    end_idx = min(end_idx, len(btc))

    tp1 = entry * (1 + rule.tp1_pct / 100.0)
    tp2 = entry * (1 + rule.tp2_pct / 100.0)
    stop = entry * (1 + rule.stop_pct / 100.0)

    tp1_first = tp2_first = sl_first = None
    for i in range(idx + 1, end_idx):
        hi = float(btc["high"].iloc[i])
        lo = float(btc["low"].iloc[i])
        if rule.direction == "SHORT":
            # Stop is ABOVE entry, TPs below. Conservative tie-break: if both
            # touched in same bar, assume stop hit first (worse case).
            sl_touch = hi >= stop
            tp1_touch = lo <= tp1
            tp2_touch = lo <= tp2
        else:  # LONG
            sl_touch = lo <= stop
            tp1_touch = hi >= tp1
            tp2_touch = hi >= tp2

        if sl_touch and tp1_first is None and sl_first is None:
            # Stop hit before TP1 → SL only outcome
            sl_first = i
            break
        if tp1_touch and tp1_first is None:
            tp1_first = i
        if tp2_touch and tp2_first is None:
            tp2_first = i
        # After TP1: stop moves to BE (entry). If price reverses to BE, exit BE.
        if tp1_first is not None and sl_first is None and tp2_first is None:
            if rule.direction == "SHORT" and hi >= entry:
                sl_first = i  # BE exit (we mark as SL slot but pnl uses entry)
                break
            if rule.direction == "LONG" and lo <= entry:
                sl_first = i
                break
        if tp2_first is not None:
            break

    # Determine outcome label
    if tp2_first is not None:
        outcome = "TP2"
    elif tp1_first is not None and sl_first is not None:
        outcome = "TP1_then_BE"
    elif tp1_first is not None:
        outcome = "TP1_timeout"
    elif sl_first is not None:
        outcome = "SL"
    else:
        outcome = "timeout"

    # PnL accounting (in % of notional). SHORT: profit when price down.
    sign = -1.0 if rule.direction == "SHORT" else +1.0

    def signed_pct(target: float) -> float:
        return sign * (target - entry) / entry * 100.0

    # all-or-nothing TP2 strategy: hit TP2 → +tp2_pct, else SL → -stop_pct,
    # else timeout → close at last_close
    last_close = float(btc["close"].iloc[end_idx - 1])
    timeout_pct = sign * (last_close - entry) / entry * 100.0
    if outcome == "TP2":
        pnl_tp2_only = abs(rule.tp2_pct)
    elif outcome == "SL":
        pnl_tp2_only = -abs(rule.stop_pct)
    elif outcome in ("TP1_then_BE", "TP1_timeout"):
        # TP1 hit but TP2 not reached. For tp2_only strategy:
        # - if BE exit after TP1: exit at entry = 0 PnL
        # - if timeout after TP1: timeout PnL
        if outcome == "TP1_then_BE":
            pnl_tp2_only = 0.0
        else:
            pnl_tp2_only = timeout_pct
    else:  # timeout, no TP1 hit
        pnl_tp2_only = timeout_pct

    # Scale-out 30% at TP1 + 70% to TP2 (with BE stop after TP1)
    s = rule.scale_out_pct
    if outcome == "TP2":
        pnl_scale = s * abs(rule.tp1_pct) + (1 - s) * abs(rule.tp2_pct)
    elif outcome == "SL":
        pnl_scale = -abs(rule.stop_pct)  # никогда не дошли до TP1
    elif outcome == "TP1_then_BE":
        # Locked s% at TP1, (1-s)% exits at BE = 0
        pnl_scale = s * abs(rule.tp1_pct) + (1 - s) * 0.0
    elif outcome == "TP1_timeout":
        pnl_scale = s * abs(rule.tp1_pct) + (1 - s) * timeout_pct
    else:  # timeout, no TP1 hit
        pnl_scale = timeout_pct

    return {
        "outcome": outcome,
        "tp1_first": tp1_first,
        "tp2_first": tp2_first,
        "sl_first": sl_first,
        "pnl_tp2_only_pct": round(pnl_tp2_only, 4),
        "pnl_scale_pct": round(pnl_scale, 4),
        "entry": entry,
        "timeout_pct": round(timeout_pct, 4),
        "fwd_4h_up": timeout_pct > 0 if rule.direction == "LONG" else timeout_pct > 0,
    }


def simulate_random_baseline(btc: pd.DataFrame, rule: RuleSpec, n: int = 200,
                              seed: int = 42) -> dict:
    """Random-sampled baseline outcomes (same simulator) for edge-over-baseline."""
    rng = random.Random(seed)
    valid_start = max(60, rule.exit_after_h * 60)
    valid_end = len(btc) - rule.exit_after_h * 60 - 1
    if valid_end <= valid_start:
        return {"n": 0}
    results = []
    while len(results) < n:
        idx = rng.randint(valid_start, valid_end)
        ts = btc["ts"].iloc[idx].to_pydatetime()
        r = simulate_trade(btc, ts, rule)
        if r:
            results.append(r)
    return _aggregate(results, rule)


def _aggregate(results: list[dict], rule: RuleSpec) -> dict:
    if not results:
        return {"n": 0}
    n = len(results)
    by_outcome: dict[str, int] = {}
    for r in results:
        by_outcome[r["outcome"]] = by_outcome.get(r["outcome"], 0) + 1
    pnl_tp2 = [r["pnl_tp2_only_pct"] for r in results]
    pnl_scale = [r["pnl_scale_pct"] for r in results]
    fwd_direction_correct = sum(
        1 for r in results
        if (r["timeout_pct"] > 0 and rule.direction == "LONG")
        or (r["timeout_pct"] < 0 and rule.direction == "SHORT")
    )
    return {
        "n": n,
        "outcomes": by_outcome,
        "wr_tp2_only_pct": round(100 * sum(1 for p in pnl_tp2 if p > 0) / n, 1),
        "wr_scale_pct": round(100 * sum(1 for p in pnl_scale if p > 0) / n, 1),
        "wr_fwd_direction_pct": round(100 * fwd_direction_correct / n, 1),
        "mean_pnl_tp2_only_pct": round(sum(pnl_tp2) / n, 4),
        "mean_pnl_scale_pct": round(sum(pnl_scale) / n, 4),
        "total_pnl_tp2_only_pct": round(sum(pnl_tp2), 3),
        "total_pnl_scale_pct": round(sum(pnl_scale), 3),
        "tp2_hit_pct": round(100 * by_outcome.get("TP2", 0) / n, 1),
        "sl_hit_pct": round(100 * by_outcome.get("SL", 0) / n, 1),
    }


def run_for_rule(rule_key: str, cooldown_min: int = 60) -> dict:
    rule = RULES[rule_key]
    print(f"\n=== {rule.name} ({rule.signal_symbol} taker_buy {rule.op} {rule.threshold}) ===")
    fires = find_fires(rule, cooldown_min)
    if not fires:
        print("no fires found in deriv history")
        return {}
    print(f"Fires after {cooldown_min}-min cooldown: {len(fires)}")
    print(f"  first: {fires[0]['ts']}  last: {fires[-1]['ts']}")
    btc = load_btc_1m()
    print(f"BTC 1m bars: {len(btc)}  {btc.ts.iloc[0]} → {btc.ts.iloc[-1]}")

    results = []
    skipped_oob = 0
    for f in fires:
        r = simulate_trade(btc, f["ts"], rule)
        if r is None:
            skipped_oob += 1
            continue
        results.append(r)
    print(f"Simulated: {len(results)}  out-of-bounds: {skipped_oob}")
    agg = _aggregate(results, rule)
    baseline = simulate_random_baseline(btc, rule)
    edge_dir = agg["wr_fwd_direction_pct"] - baseline.get("wr_fwd_direction_pct", 50)
    edge_pnl_tp2 = agg["mean_pnl_tp2_only_pct"] - baseline.get("mean_pnl_tp2_only_pct", 0)
    edge_pnl_scale = agg["mean_pnl_scale_pct"] - baseline.get("mean_pnl_scale_pct", 0)

    print(f"\n— CONDITIONAL (rule fires) n={agg['n']}")
    print(f"  outcomes:  {agg['outcomes']}")
    print(f"  TP2 hit rate:    {agg['tp2_hit_pct']:.1f}%   SL hit rate: {agg['sl_hit_pct']:.1f}%")
    print(f"  WR fwd-direction (paper-style): {agg['wr_fwd_direction_pct']:.1f}%")
    print(f"  WR tp2_only strategy:           {agg['wr_tp2_only_pct']:.1f}%   mean PnL: {agg['mean_pnl_tp2_only_pct']:+.4f}%   sum: {agg['total_pnl_tp2_only_pct']:+.2f}%")
    print(f"  WR scale-out (30%@TP1+BE):      {agg['wr_scale_pct']:.1f}%   mean PnL: {agg['mean_pnl_scale_pct']:+.4f}%   sum: {agg['total_pnl_scale_pct']:+.2f}%")

    print(f"\n— BASELINE (random {baseline.get('n', 0)} timestamps, same simulator)")
    if baseline.get("n", 0):
        print(f"  WR fwd-direction:               {baseline['wr_fwd_direction_pct']:.1f}%")
        print(f"  WR tp2_only:                    {baseline['wr_tp2_only_pct']:.1f}%   mean PnL: {baseline['mean_pnl_tp2_only_pct']:+.4f}%")
        print(f"  WR scale-out:                   {baseline['wr_scale_pct']:.1f}%   mean PnL: {baseline['mean_pnl_scale_pct']:+.4f}%")

    print(f"\n— EDGE OVER BASELINE")
    print(f"  WR-direction:  {edge_dir:+.1f} п.п.")
    print(f"  PnL tp2_only:  {edge_pnl_tp2:+.4f}% per trade")
    print(f"  PnL scale-out: {edge_pnl_scale:+.4f}% per trade")

    verdict = []
    if agg["wr_scale_pct"] < 45:
        verdict.append("scale-out WR<45% — невыгодно")
    if edge_pnl_scale < 0.02:
        verdict.append("edge per-trade < 0.02% — внутри fees + шума")
    if agg["sl_hit_pct"] > 35:
        verdict.append(f"SL hit {agg['sl_hit_pct']:.0f}% — стоп слишком близко")
    if not verdict:
        verdict.append("✅ edge есть и устойчив на текущих данных")
    print(f"\n— VERDICT: {' | '.join(verdict)}")
    return {"rule": rule.name, "agg": agg, "baseline": baseline}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rule", choices=list(RULES.keys()) + ["all"], default="all")
    ap.add_argument("--cooldown-min", type=int, default=60,
                    help="min minutes between rule fires (default 60)")
    args = ap.parse_args()

    keys = list(RULES.keys()) if args.rule == "all" else [args.rule]
    for k in keys:
        run_for_rule(k, cooldown_min=args.cooldown_min)


if __name__ == "__main__":
    main()
