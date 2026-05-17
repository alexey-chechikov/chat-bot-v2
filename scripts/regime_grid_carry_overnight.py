"""Phase 3.6 v2 — carry-overnight grid sim with regime×vol classification.

Phase 3.6 v1 (regime_conditional_grid_research.py) ran daily-isolated sims —
each day starts fresh, no position carries over. That gave unrealistic
avg_DD=$0 in all cells.

This version:
  1. Run ONE continuous 2y grid sim with carry-overnight position
  2. For each day's daily_df row, classify (regime, vol)
  3. Aggregate net + max_dd by cell

Real DDs that accumulate across days (e.g. multi-day trending markets that
keep position pinned at cap) now properly reflected.

Usage:
    python scripts/regime_grid_carry_overnight.py
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA_CSV = ROOT / "backtests" / "frozen" / "BTCUSDT_1m_2y.csv"
DOC_PATH = ROOT / "docs" / "RESEARCH_regime_grid_carry_overnight_2026-05-17.md"
CONFIG_PATH = ROOT / "state" / "bot_brain_regime_grid_config_v2.json"

sys.path.insert(0, str(ROOT / "scripts"))
import volume_farm_grid_backtest as g  # type: ignore

BEST = dict(
    contract="inverse", grid_range_pct=0.6, grid_levels=120,
    order_size_usd=1000.0, inventory_cap_btc=0.10,
    reanchor_drift_pct=0.3, hard_stop_unrealized_usd=-2000.0,
)


def classify_day_regime(day_close_start: float, day_close_end: float) -> str:
    move_pct = (day_close_end - day_close_start) / day_close_start * 100.0
    if move_pct > 1.5:
        return "TREND_UP"
    if move_pct < -1.5:
        return "TREND_DOWN"
    return "RANGE"


def classify_day_vol(daily_atr_pct: float, q33: float, q67: float) -> str:
    if daily_atr_pct < q33:
        return "LOW"
    if daily_atr_pct < q67:
        return "MEDIUM"
    return "HIGH"


def main():
    print("Loading 2y BTC...")
    df = pd.read_csv(DATA_CSV, usecols=["ts", "open", "high", "low", "close", "volume"])
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df = df.sort_values("ts").reset_index(drop=True)
    print(f"  bars: {len(df):,}")

    # Daily ATR % for vol classification (calibrate q33/q67)
    df["date"] = df["ts"].dt.date
    daily = df.groupby("date").agg(
        open_first=("close", "first"),
        close_last=("close", "last"),
        atr_mean=("high", lambda h: 0),  # placeholder, override below
    ).reset_index()
    # Compute mean true-range per day, %
    atr_per_day = df.groupby("date").apply(
        lambda d: (d["high"] - d["low"]).mean() / d["close"].iloc[-1] * 100.0,
        include_groups=False,
    )
    daily["atr_pct"] = daily["date"].map(atr_per_day)
    q33 = float(np.percentile(daily["atr_pct"].dropna(), 33))
    q67 = float(np.percentile(daily["atr_pct"].dropna(), 67))
    print(f"  vol thresholds: LOW < {q33:.3f}% < MED < {q67:.3f}% < HIGH")

    # Classify each day
    daily["regime"] = daily.apply(
        lambda r: classify_day_regime(r["open_first"], r["close_last"]), axis=1)
    daily["vol"] = daily["atr_pct"].apply(lambda v: classify_day_vol(v, q33, q67))

    # Run ONE carry-overnight sim across full 2y
    print("Running carry-overnight grid sim (this may take ~1-2 min)...")
    p = g.Params(**BEST)
    result = g.run(df, p)
    days_df = result["days_df"].copy()
    print(f"  total_net: ${result['total_net_usd']:+,.0f}")
    print(f"  total_volume: ${result['total_volume_usd']:+,.0f}")
    print(f"  max DD (cum net): ${result['max_drawdown_in_run_usd']:+,.0f}")

    # Compute per-day max intraday DD: unrealized within day. For now use
    # net_usd (daily net) as proxy. True intraday DD requires bar-level
    # tracking inside the sim. We use day's net_usd to compare cells.
    days_df["date"] = pd.to_datetime(days_df["date"])
    daily["date_ts"] = pd.to_datetime(daily["date"])

    joined = days_df.merge(
        daily[["date_ts", "regime", "vol"]],
        left_on="date", right_on="date_ts", how="inner",
    )

    # Aggregate by cell
    print("\n=== Regime × Vol matrix (carry-overnight) ===")
    print(f"{'regime':12} {'vol':6} {'n':>4} {'avg_net':>9} {'med_net':>9} "
          f"{'min_day':>10} {'max_day':>10} {'avg_fills':>10} {'avg_pos_eod':>12}")
    cells = defaultdict(list)
    for _, row in joined.iterrows():
        cells[(row["regime"], row["vol"])].append({
            "date": str(row["date"].date()),
            "net": float(row["net_usd"]),
            "volume": float(row["volume_usd"]),
            "fills": int(row["fills"]),
            "pos_eod": float(row["pos_btc_eod"]),
            "unr_eod": float(row["unrealized_usd_eod"]),
        })

    matrix = {}
    for regime in ["RANGE", "TREND_UP", "TREND_DOWN"]:
        matrix[regime] = {}
        for vol in ["LOW", "MEDIUM", "HIGH"]:
            data = cells.get((regime, vol), [])
            if not data:
                continue
            nets = [d["net"] for d in data]
            print(f"{regime:12} {vol:6} {len(data):>4} "
                  f"${np.mean(nets):>+8.0f} ${np.median(nets):>+8.0f} "
                  f"${min(nets):>+9.0f} ${max(nets):>+9.0f} "
                  f"{np.mean([d['fills'] for d in data]):>10.1f} "
                  f"{np.mean([d['pos_eod'] for d in data]):>+12.4f}")
            matrix[regime][vol] = {
                "n_days": len(data),
                "avg_net": round(np.mean(nets), 2),
                "median_net": round(np.median(nets), 2),
                "min_day_net": round(min(nets), 2),
                "max_day_net": round(max(nets), 2),
                "neg_day_pct": round(100 * sum(1 for n in nets if n < 0) / len(nets), 1),
            }

    # Aggregate over all vols per regime
    print(f"\n{'regime':12} {'all vols':>10} {'avg_net':>9} {'neg_days%':>10}")
    matrix_summary = {}
    for regime in ["RANGE", "TREND_UP", "TREND_DOWN"]:
        all_data = sum((cells.get((regime, v), []) for v in ["LOW", "MEDIUM", "HIGH"]), [])
        if all_data:
            nets = [d["net"] for d in all_data]
            neg_pct = 100 * sum(1 for n in nets if n < 0) / len(nets)
            print(f"{regime:12} {len(all_data):>10} ${np.mean(nets):>+8.0f} {neg_pct:>9.1f}%")
            matrix_summary[regime] = {
                "n_days": len(all_data), "avg_net": round(np.mean(nets), 2),
                "neg_day_pct": round(neg_pct, 1),
            }

    config = {
        "generated_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "source": "scripts/regime_grid_carry_overnight.py",
        "version": "v2 — carry-overnight",
        "params": BEST,
        "total_net_usd": float(result["total_net_usd"]),
        "total_volume_usd": float(result["total_volume_usd"]),
        "max_drawdown_cum_net_usd": float(result["max_drawdown_in_run_usd"]),
        "vol_thresholds_atr_pct": {"q33": q33, "q67": q67},
        "matrix_by_cell": matrix,
        "matrix_by_regime": matrix_summary,
    }
    CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nWrote {CONFIG_PATH}")

    # Compare with daily-isolated Phase 3.6 v1
    v1_path = ROOT / "state" / "bot_brain_regime_grid_config.json"
    v1_summary = None
    if v1_path.exists():
        v1 = json.loads(v1_path.read_text(encoding="utf-8"))
        v1_summary = v1.get("matrix_avg_daily_net_usd", {})

    # Write doc
    lines = [
        "# Regime-conditional grid (carry-overnight) — Phase 3.6 v2",
        "",
        "**Difference from v1:** continuous 2y simulation (position carries over),",
        "instead of daily-isolated. Phase 3.6 v1 had artifact `avg_DD=$0` because each",
        "day reset state. This version captures real cross-day drawdowns.",
        "",
        f"**Total 2y net:** ${result['total_net_usd']:+,.0f}",
        f"**Total volume:** ${result['total_volume_usd']:+,.0f}",
        f"**Max DD (cumulative net):** ${result['max_drawdown_in_run_usd']:+,.0f}",
        f"**Vol thresholds (ATR %):** LOW < {q33:.3f}% < MED < {q67:.3f}% < HIGH",
        "",
        "## Matrix avg daily net (carry-overnight)",
        "",
        "| Regime | LOW | MEDIUM | HIGH |",
        "|---|---|---|---|",
    ]
    for regime in ["RANGE", "TREND_UP", "TREND_DOWN"]:
        row = [regime]
        for vol in ["LOW", "MEDIUM", "HIGH"]:
            d = matrix.get(regime, {}).get(vol)
            row.append(f"${d['avg_net']:+,.0f} (n={d['n_days']}, neg={d['neg_day_pct']}%)"
                       if d else "—")
        lines.append(f"| {row[0]} | {row[1]} | {row[2]} | {row[3]} |")
    lines.append("")
    lines.append("## Negative-day % per cell — risk indicator")
    lines.append("Days with negative net (loss days) as % of cell's days.")
    lines.append("")
    lines.append("| Regime | LOW | MEDIUM | HIGH |")
    lines.append("|---|---|---|---|")
    for regime in ["RANGE", "TREND_UP", "TREND_DOWN"]:
        row = [regime]
        for vol in ["LOW", "MEDIUM", "HIGH"]:
            d = matrix.get(regime, {}).get(vol)
            row.append(f"{d['neg_day_pct']}%" if d else "—")
        lines.append(f"| {row[0]} | {row[1]} | {row[2]} | {row[3]} |")
    lines.append("")

    if v1_summary:
        lines.append("## Comparison vs v1 (daily-isolated)")
        lines.append("")
        lines.append("| Cell | v1 avg | v2 avg (carry) | delta |")
        lines.append("|---|---|---|---|")
        for regime in ["RANGE", "TREND_UP", "TREND_DOWN"]:
            for vol in ["LOW", "MEDIUM", "HIGH"]:
                v2 = matrix.get(regime, {}).get(vol)
                v1c = v1_summary.get(regime, {}).get(vol)
                if v2 and v1c:
                    v1_net = v1c.get("avg_net_usd", 0)
                    v2_net = v2["avg_net"]
                    lines.append(f"| {regime}/{vol} | ${v1_net:+,.0f} | "
                                  f"${v2_net:+,.0f} | ${v2_net - v1_net:+,.0f} |")
        lines.append("")

    lines.append("## Применение")
    lines.append("")
    lines.append("Use `state/bot_brain_regime_grid_config_v2.json` for sizing decisions.")
    lines.append("`neg_day_pct` is the risk-side companion to `avg_net` — cell with 70% +days")
    lines.append("and low DD is safer than cell with 50% +days even if average higher.")
    lines.append("")
    lines.append("⚠ Real-world deviations:")
    lines.append("- BitMEX slippage (not modeled)")
    lines.append("- Funding payments accumulation (not modeled)")
    lines.append("- Exchange outages / data gaps")
    lines.append("- Simulator uses fixed sweet-spot params; live bot may be tuned differently")
    DOC_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {DOC_PATH}")


if __name__ == "__main__":
    main()
