"""A/B experiment tracker: T1 (без auto-pause) vs TB (с auto-pause).

Setup 2026-05-18: оператор убрал T1 из `cascade_short_*.*` affect_tiers
в `state/short_bots_managed.json`. TB остаётся under auto-pause guard.
Цель — сравнить через 1-2 недели:
  - чей объём выше (T1 ожидаемо больше — не паузится)
  - чей нет realized PnL лучше после tail events (cascades)
  - кто проседает сильнее в drawdown во время каскадов

Usage:
    python scripts/ab_compare_t1_tb.py [--days N]

Defaults to last 7 days. Reads:
  - ginarea_live/events.csv (per-fill volume)
  - ginarea_live/snapshots.csv (positions, profit)
  - state/short_bots_auto_pause.json (pause events for TB)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
EVENTS_CSV = ROOT / "ginarea_live" / "events.csv"
SNAPSHOTS_CSV = ROOT / "ginarea_live" / "snapshots.csv"
AUTO_PAUSE_PATH = ROOT / "state" / "short_bots_auto_pause.json"

T1_ID = "4729923198"
TB_ID = "4525648417"
EXPERIMENT_START = "2026-05-18T00:00:00+00:00"


def load_per_bot(events: pd.DataFrame, snapshots: pd.DataFrame, bot_id: str,
                 since: datetime):
    e = events[events.bot_id.astype(str).str.split(".").str[0] == bot_id].copy()
    e = e[e.ts >= since]
    s = snapshots[snapshots.bot_id.astype(str).str.split(".").str[0] == bot_id].copy()
    s = s[s.ts >= since]
    return e, s


def daily_volume_and_pnl(events_bot: pd.DataFrame, snapshots_bot: pd.DataFrame
                          ) -> pd.DataFrame:
    """Return DataFrame[date, fills, vol_usd, end_profit_usd, max_position_usd]."""
    if events_bot.empty:
        return pd.DataFrame()
    events_bot = events_bot.sort_values("ts").copy()
    events_bot["date"] = events_bot.ts.dt.date
    events_bot["prev_pos"] = events_bot.position_after.shift(1).fillna(0)
    events_bot["dpos"] = events_bot.position_after - events_bot.prev_pos
    events_bot["vol_usd"] = events_bot.apply(
        lambda r: abs(r["dpos"]) * r["price_last"], axis=1
    )

    daily = events_bot.groupby("date").agg(
        fills=("ts", "count"),
        vol_usd=("vol_usd", "sum"),
        avg_price=("price_last", "mean"),
    ).reset_index()

    if not snapshots_bot.empty:
        snapshots_bot = snapshots_bot.sort_values("ts").copy()
        snapshots_bot["date"] = snapshots_bot.ts.dt.date
        snapshots_bot["profit_num"] = pd.to_numeric(
            snapshots_bot["current_profit"], errors="coerce"
        )
        snapshots_bot["pos_num"] = pd.to_numeric(
            snapshots_bot["position"], errors="coerce"
        )
        eod = snapshots_bot.groupby("date").agg(
            end_profit_usd=("profit_num", "last"),
            max_pos_abs=("pos_num", lambda s: float(s.abs().max())),
            min_profit_intraday=("profit_num", "min"),
        ).reset_index()
        daily = daily.merge(eod, on="date", how="left")
        daily["max_position_usd_est"] = daily["max_pos_abs"] * daily["avg_price"]

    return daily


def count_pauses_in_window(bot_id: str, since: datetime) -> int:
    """Count how many cascade_short_* triggers fired since `since` and affected this bot.
    Read from log if available; fallback to auto_pause.json last_fire_ts."""
    log = ROOT / "logs" / "app.log"
    count = 0
    if log.exists():
        for line in log.read_text(encoding="utf-8", errors="ignore").splitlines():
            if f"short_bots_guard.paused bot={bot_id}" not in line:
                continue
            ts_str = line.split(" | ")[0]
            try:
                ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S,%f")
                ts = ts.replace(tzinfo=timezone.utc)
                if ts >= since:
                    count += 1
            except ValueError:
                pass
    return count


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7,
                     help="Window size in days (default 7)")
    args = ap.parse_args()

    since = datetime.now(timezone.utc) - timedelta(days=args.days)
    exp_start = datetime.fromisoformat(EXPERIMENT_START)
    if since < exp_start:
        since = exp_start

    print(f"\n=== A/B experiment: T1 (no auto-pause) vs TB (auto-pause guard) ===")
    print(f"Experiment start: {exp_start.strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"Window:           {since.strftime('%Y-%m-%d %H:%M UTC')} → now")
    print(f"Days analysed:    {(datetime.now(timezone.utc) - since).total_seconds()/86400:.2f}")

    if not EVENTS_CSV.exists() or not SNAPSHOTS_CSV.exists():
        print("Missing events.csv or snapshots.csv")
        sys.exit(1)

    print("\nLoading data...")
    events = pd.read_csv(EVENTS_CSV)
    events["ts"] = pd.to_datetime(events["ts_utc"], format="ISO8601",
                                    errors="coerce", utc=True)
    events = events.dropna(subset=["ts"])

    snapshots = pd.read_csv(SNAPSHOTS_CSV, dtype={"position": str, "current_profit": str})
    snapshots["ts"] = pd.to_datetime(snapshots["ts_utc"], format="ISO8601",
                                       errors="coerce", utc=True)
    snapshots = snapshots.dropna(subset=["ts"])

    e_t1, s_t1 = load_per_bot(events, snapshots, T1_ID, since)
    e_tb, s_tb = load_per_bot(events, snapshots, TB_ID, since)
    d_t1 = daily_volume_and_pnl(e_t1, s_t1)
    d_tb = daily_volume_and_pnl(e_tb, s_tb)

    pauses_t1 = count_pauses_in_window(T1_ID, since)
    pauses_tb = count_pauses_in_window(TB_ID, since)

    print("\n=== Per-bot summary ===")
    for label, d, pauses in [("T1 (no auto-pause)", d_t1, pauses_t1),
                              ("TB (auto-pause)", d_tb, pauses_tb)]:
        print(f"\n{label}:")
        if d.empty:
            print("  no data in window")
            continue
        print(f"  days with fills:       {len(d)}")
        print(f"  total fills:           {int(d.fills.sum()):,}")
        print(f"  total volume:          ${d.vol_usd.sum():,.0f}")
        print(f"  avg daily volume:      ${d.vol_usd.mean():,.0f}")
        if "end_profit_usd" in d.columns:
            end_profit = d["end_profit_usd"].dropna()
            if not end_profit.empty:
                profit_start = end_profit.iloc[0]
                profit_end = end_profit.iloc[-1]
                print(f"  current_profit start:  ${profit_start:+,.2f}")
                print(f"  current_profit end:    ${profit_end:+,.2f}")
                print(f"  Δ profit (window):     ${profit_end - profit_start:+,.2f}")
            if "min_profit_intraday" in d.columns:
                worst = d["min_profit_intraday"].min()
                print(f"  worst intraday profit: ${worst:+,.2f}")
        if "max_position_usd_est" in d.columns:
            max_pos = d["max_position_usd_est"].max()
            print(f"  max position (USD est):${max_pos:,.0f}")
        print(f"  auto-pause events:     {pauses}")

    # Side-by-side daily
    if not d_t1.empty and not d_tb.empty:
        print("\n=== Daily side-by-side ===")
        m = d_t1.merge(d_tb, on="date", how="outer",
                        suffixes=("_T1", "_TB")).sort_values("date")
        print(f"{'date':12} {'T1_vol':>10} {'TB_vol':>10} {'T1_fills':>8} {'TB_fills':>8} "
              f"{'T1_Δprof':>10} {'TB_Δprof':>10}")
        for _, r in m.iterrows():
            t1_vol = r.get("vol_usd_T1") or 0
            tb_vol = r.get("vol_usd_TB") or 0
            t1_fills = r.get("fills_T1") or 0
            tb_fills = r.get("fills_TB") or 0
            t1_prof = r.get("end_profit_usd_T1") or 0
            tb_prof = r.get("end_profit_usd_TB") or 0
            print(f"{str(r.date):12} ${t1_vol:>9,.0f} ${tb_vol:>9,.0f} "
                  f"{int(t1_fills):>8} {int(tb_fills):>8} "
                  f"${t1_prof:>+9,.2f} ${tb_prof:>+9,.2f}")

    print("\n=== Interpretation hints ===")
    print("  • T1 vol > TB vol = expected (T1 never paused)")
    print("  • T1 Δprofit << TB Δprofit during cascade events = auto-pause saved bleed")
    print("  • T1 Δprofit ≈ TB Δprofit = auto-pause не помогает (false alarms преобладают)")
    print("  • T1 max position >> TB max position в cascade-day = T1 bleed во время каскадов")


if __name__ == "__main__":
    main()
