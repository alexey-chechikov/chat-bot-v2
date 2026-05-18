"""Retro-test cascade-fade rule на УЖЕ накопленных каскадах.

Rule (из cascade_backtest_combined.json validated):
  long_liq cascade (price dropped) → SHORT continuation (2026 inverted edge)
  short_liq cascade (price rose)   → LONG fade (still works)

Method:
  1. Читаем все cascade_alert fires из state/cascade_alert_dedup.json
     + cascade events из state/liq_pre_cascade_fires.jsonl
  2. Для каждого: hypothetical entry в направлении rule, SL=-0.5%, TP=+0.75%, hold=4h
  3. Симулируем на 1m данных
  4. Per-week stats + verdict
"""
from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

LIQ_FIRES = ROOT / "state" / "liq_pre_cascade_fires.jsonl"
CASCADE_BACKTEST = ROOT / "state" / "cascade_backtest_combined.json"
MARKET_1M = ROOT / "market_live" / "market_1m.csv"
BTC_2Y = ROOT / "backtests" / "frozen" / "BTCUSDT_1m_2y.csv"

TAKER_FEE_PCT = 0.075


def _load_recent_cascades(days: int = 60) -> list[dict]:
    """Read pre-cascade fires (liq clusters) which act as proxy for actual cascades."""
    if not LIQ_FIRES.exists():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    out = []
    for line in LIQ_FIRES.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
            ts = datetime.fromisoformat(r["ts"])
            if ts < cutoff:
                continue
            out.append(r)
        except (json.JSONDecodeError, KeyError, ValueError):
            continue
    return out


def _load_btc_1m_window(start: datetime, end: datetime) -> list[tuple[datetime, float, float, float]]:
    """Load BTC 1m bars in window from BTC_2Y or market_1m fallback."""
    bars: list[tuple[datetime, float, float, float]] = []
    csv_path = MARKET_1M if MARKET_1M.exists() else BTC_2Y

    try:
        with csv_path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ts_str = row.get("ts_utc") or row.get("ts")
                if not ts_str:
                    continue
                try:
                    if ts_str.isdigit() or (ts_str.startswith("-") and ts_str[1:].isdigit()):
                        ts = datetime.fromtimestamp(int(ts_str)/1000, tz=timezone.utc)
                    else:
                        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    continue
                if ts < start - timedelta(minutes=10):
                    continue
                if ts > end + timedelta(hours=6):
                    break
                try:
                    hi = float(row["high"]); lo = float(row["low"]); cl = float(row["close"])
                    bars.append((ts, hi, lo, cl))
                except (KeyError, ValueError):
                    continue
    except OSError:
        pass
    return bars


def simulate_trade(side: str, entry: float, ts_signal: datetime,
                    bars: list[tuple[datetime, float, float, float]],
                    stop_pct: float = -0.5, tp_pct: float = 0.75,
                    hold_h: int = 4, size_usd: float = 1000.0) -> dict:
    sign = 1 if side == "LONG" else -1
    stop = entry * (1 + sign * stop_pct / 100)
    tp = entry * (1 + sign * tp_pct / 100)
    expiry = ts_signal + timedelta(hours=hold_h)

    for ts, hi, lo, cl in bars:
        if ts < ts_signal:
            continue
        if ts > expiry:
            break
        if side == "LONG":
            if lo <= stop:
                pnl = size_usd * (stop / entry - 1) - size_usd * (TAKER_FEE_PCT / 100) * 2
                return {"outcome": "sl_hit", "exit_price": stop, "pnl_usd": pnl}
            if hi >= tp:
                pnl = size_usd * (tp / entry - 1) - size_usd * (TAKER_FEE_PCT / 100) * 2
                return {"outcome": "tp_hit", "exit_price": tp, "pnl_usd": pnl}
        else:
            if hi >= stop:
                pnl = size_usd * (1 - stop / entry) - size_usd * (TAKER_FEE_PCT / 100) * 2
                return {"outcome": "sl_hit", "exit_price": stop, "pnl_usd": pnl}
            if lo <= tp:
                pnl = size_usd * (1 - tp / entry) - size_usd * (TAKER_FEE_PCT / 100) * 2
                return {"outcome": "tp_hit", "exit_price": tp, "pnl_usd": pnl}

    # timeout
    if bars:
        last_close = bars[-1][3]
        if side == "LONG":
            pnl = size_usd * (last_close / entry - 1) - size_usd * (TAKER_FEE_PCT / 100) * 2
        else:
            pnl = size_usd * (1 - last_close / entry) - size_usd * (TAKER_FEE_PCT / 100) * 2
        return {"outcome": "timeout", "exit_price": last_close, "pnl_usd": pnl}
    return {"outcome": "no_data", "exit_price": 0, "pnl_usd": 0}


def main():
    cascades = _load_recent_cascades(days=60)
    if not cascades:
        print("No recent cascade events found in state/liq_pre_cascade_fires.jsonl")
        print("Use scripts/cascade_fade_retro_test_2y.py for 2y history retro-test instead.")
        return

    print(f"Loaded {len(cascades)} cascade fires из liq_pre_cascade_fires.jsonl за 60 дней\n")

    results = []
    for c in cascades:
        side_liq = c.get("side")  # "long" = longs liquidated, "short" = shorts liq
        # Rule: long_liq → SHORT (2026 inverted), short_liq → LONG (fade)
        trade_side = "SHORT" if side_liq == "long" else "LONG"
        ts_str = c.get("ts")
        try:
            ts_signal = datetime.fromisoformat(ts_str)
        except (TypeError, ValueError):
            continue

        # Read entry price = close at signal ts (or nearest)
        end_window = ts_signal + timedelta(hours=5)
        bars = _load_btc_1m_window(ts_signal, end_window)
        if not bars:
            results.append({"ts": ts_str, "side_liq": side_liq, "trade_side": trade_side,
                             "outcome": "no_bars", "pnl_usd": 0})
            continue

        # Find entry — first bar at/after ts_signal
        entry = None
        for ts, hi, lo, cl in bars:
            if ts >= ts_signal:
                entry = cl
                break
        if entry is None or entry <= 0:
            continue

        sim = simulate_trade(trade_side, entry, ts_signal, bars)
        results.append({
            "ts": ts_str,
            "side_liq": side_liq,
            "trade_side": trade_side,
            "qty_btc": c.get("qty_btc"),
            "entry": entry,
            **sim,
        })

    # Summary
    closed = [r for r in results if r.get("outcome") in ("tp_hit", "sl_hit", "timeout")]
    wins = sum(1 for r in closed if r["outcome"] == "tp_hit")
    losses = sum(1 for r in closed if r["outcome"] == "sl_hit")
    timeouts = sum(1 for r in closed if r["outcome"] == "timeout")
    total_pnl = sum(r["pnl_usd"] for r in closed)

    print(f"=== Cascade-fade retro-test: 60-day window ===")
    print(f"Total signals:    {len(results)}")
    print(f"Simulated trades: {len(closed)}")
    print(f"  TP hits (wins): {wins} ({100*wins/max(len(closed),1):.0f}%)")
    print(f"  SL hits:        {losses}")
    print(f"  Timeouts:       {timeouts}")
    print(f"Total PnL @ $1k:  ${total_pnl:+,.2f}")
    print()

    # Per-side breakdown
    for side in ("LONG", "SHORT"):
        rs = [r for r in closed if r["trade_side"] == side]
        if not rs:
            continue
        w = sum(1 for r in rs if r["outcome"] == "tp_hit")
        pnl = sum(r["pnl_usd"] for r in rs)
        print(f"  {side:5}: {len(rs):3} trades  WR {100*w/len(rs):.0f}%  PnL ${pnl:+,.2f}")
        print(f"         (triggered by {'long_liq' if side=='SHORT' else 'short_liq'} cascades)")

    print()
    print("Verdict:")
    if len(closed) < 5:
        print("  ⚠ N too small (need ≥5 closed). Накопится больше через paper_signal_tracker.")
    elif total_pnl > 0 and wins > losses:
        print("  ✓ Rule profitable. Recommend automate в bot_brain / TG cards с buttons.")
    elif total_pnl < 0:
        print("  ✗ Rule unprofitable in this window. Possible reasons:")
        print("    - cascade events too rare in last 60d")
        print("    - 2026 inversion может не работать в этом конкретном sub-period")
        print("    - try paper_signal_tracker over weeks для лучшей выборки")
    else:
        print("  ◐ Neutral. Wait for more data.")


if __name__ == "__main__":
    main()
