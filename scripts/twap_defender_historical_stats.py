"""Retro-analysis: сколько раз TWAP defender alert БЫ сработал на исторических snapshots.

Условие alert: |pos_usd| > $50k AND grew >= $1k за 30 мин.

Reads ginarea_live/snapshots.csv, для каждого managed-бота проходит trajectory,
считает hypothetical alerts. Помогает понять — будет ли defender реально полезен
или будет молчать.
"""
from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOTS = ROOT / "ginarea_live" / "snapshots.csv"
MARKET_1M = ROOT / "market_live" / "market_1m.csv"

MANAGED = {
    "4729923198": ("T1", "short"),
    "6287583200": ("T2", "short"),
    "5736281160": ("T3", "short"),
    "5154651487": ("LONG-D", "long"),
    "4979458320": ("LONG-V5", "long"),
    "4525648417": ("TB", "short"),
}

# 2026-05-18 update: пороги синхронизированы с services/twap_defender/state.py
BLEED_THRESHOLD_USD = 10_000.0
GROWTH_THRESHOLD_USD = 500.0
WATCH_SIDES = ("short",)


def _load_snapshots():
    """Yield (ts, bot_id, position) tuples."""
    if not SNAPSHOTS.exists():
        return
    with SNAPSHOTS.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                ts = datetime.fromisoformat(row["ts_utc"].replace("Z", "+00:00"))
            except (KeyError, ValueError):
                continue
            bid = str(row.get("bot_id", "")).split(".")[0]
            if bid not in MANAGED:
                continue
            try:
                pos = float(row.get("position", "") or 0)
            except ValueError:
                continue
            yield ts, bid, pos


def _build_price_index():
    """Build ts → close price from market_1m.csv tail (small enough)."""
    idx: dict[datetime, float] = {}
    if not MARKET_1M.exists():
        return idx
    with MARKET_1M.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                ts = datetime.fromisoformat(row["ts_utc"].replace("Z", "+00:00"))
                # round to minute key
                ts = ts.replace(second=0, microsecond=0)
                idx[ts] = float(row["close"])
            except (KeyError, ValueError):
                continue
    return idx


def _position_to_usd(pos: float, side: str, btc_price: float) -> float:
    if side == "short":
        return abs(pos) * btc_price  # inverse XBTUSD: BTC * price
    return abs(pos)  # linear: already USD


def main():
    print("Loading snapshots + market prices...")
    price_idx = _build_price_index()
    print(f"  market_1m price index: {len(price_idx):,} points")

    by_bot: dict[str, list[tuple[datetime, float]]] = {bid: [] for bid in MANAGED}
    for ts, bid, pos in _load_snapshots():
        by_bot[bid].append((ts, pos))

    print(f"\n=== TWAP Defender hypothetical alerts per managed bot ===\n")
    print(f"  trigger: |pos_usd| > ${BLEED_THRESHOLD_USD:,.0f} AND grew >= ${GROWTH_THRESHOLD_USD:,.0f} за 30 мин\n")

    total_alerts = 0
    for bid, (alias, side) in MANAGED.items():
        if side not in WATCH_SIDES:
            print(f"  {alias:8} side={side:5}  SKIPPED (side filter — SHORT-only)")
            continue
        traj = sorted(by_bot[bid], key=lambda t: t[0])
        if not traj:
            print(f"  {alias:8}  no snapshots")
            continue

        # Iterate every minute, compute pos_usd
        # For each ts: get pos_30min_ago and current pos, check conditions
        alerts = []
        # Build sparse index
        traj_idx = {t.replace(second=0, microsecond=0): pos for t, pos in traj}
        sorted_ts = sorted(traj_idx.keys())
        if not sorted_ts:
            print(f"  {alias:8}  no usable snapshots")
            continue

        # For each minute in trajectory:
        for ts in sorted_ts:
            pos_now = traj_idx[ts]
            # Find pos 30 min ago
            ts_back = ts - timedelta(minutes=30)
            # Find closest available
            best_back_ts = None
            for ts_candidate in sorted_ts:
                if ts_candidate > ts_back:
                    break
                best_back_ts = ts_candidate
            if best_back_ts is None:
                continue
            pos_back = traj_idx[best_back_ts]

            # Get BTC mid at this ts (closest minute)
            btc_price = price_idx.get(ts)
            if btc_price is None:
                # Try nearest minute
                for delta_min in range(1, 6):
                    btc_price = price_idx.get(ts - timedelta(minutes=delta_min))
                    if btc_price is not None:
                        break
                if btc_price is None:
                    continue

            pos_usd_now = _position_to_usd(pos_now, side, btc_price)
            pos_usd_back = _position_to_usd(pos_back, side, btc_price)
            delta = pos_usd_now - pos_usd_back

            if pos_usd_now >= BLEED_THRESHOLD_USD and delta >= GROWTH_THRESHOLD_USD:
                alerts.append((ts, pos_usd_now, delta))

        # Dedup: only count first alert in each 30-min cluster
        deduped = []
        last_alert_ts = None
        for ts, pos_usd, delta in alerts:
            if last_alert_ts is None or (ts - last_alert_ts).total_seconds() / 60 > 30:
                deduped.append((ts, pos_usd, delta))
                last_alert_ts = ts

        total_alerts += len(deduped)
        print(f"  {alias:8} side={side:5}  alerts={len(deduped):>3}  "
              f"(raw events: {len(alerts):>4})")
        if deduped:
            print(f"    Examples (top 3 biggest pos_usd):")
            top = sorted(deduped, key=lambda t: -t[1])[:3]
            for ts, pos_usd, delta in top:
                print(f"      {ts.strftime('%Y-%m-%d %H:%M')} pos=${pos_usd:>9,.0f} Δ30m=${delta:>+7,.0f}")

    print(f"\n=== TOTAL: {total_alerts} hypothetical alerts across all bots ===")
    if total_alerts == 0:
        print("  C3 TWAP defender молчит. Либо:")
        print("    - управляемые боты не достигали $50k bleed pos (ok — TWAP не нужен)")
        print("    - snapshots ещё короткий период")
    elif total_alerts < 5:
        print("  Низкая частота — TWAP defender полезен для редких но важных tail events.")
    else:
        print(f"  TWAP defender активно работал бы — {total_alerts} раз стримил signal-карточки.")


if __name__ == "__main__":
    main()
