"""Phase 3.6 — when does the volume-farm grid actually grind?

Hypothesis: grid bot performance is highly regime-dependent. RANGE + LOW vol
should be sweet-spot (lots of fills, small drawdowns), TREND + HIGH vol
should be killing (one-sided fills + cap quickly + big DD).

Method:
  Walk 2y BTC 1m data (backtests/frozen/BTCUSDT_1m_2y.csv).
  For each day:
    - Classify regime: TREND_UP / TREND_DOWN / RANGE (based on 24h % move)
    - Classify vol: LOW / MEDIUM / HIGH (based on ATR percentile)
    - Run grid simulation for that day (one-day slice, sweet-spot params)
    - Record: daily_net, fills, max_dd
  Aggregate by (regime, vol) cells. Show heatmap of average daily net.

Output:
  docs/RESEARCH_regime_conditional_grid_2026-05-17.md
  state/bot_brain_regime_grid_config.json — per-regime recommended size_usd
    multiplier (0.0 = pause grid in this regime, 1.0 = full, 2.0 = double)

Trader value: bot_brain R3-type rule "when regime=X + vol=Y, set size to Z%"
becomes data-driven, not heuristic.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA_CSV = ROOT / "backtests" / "frozen" / "BTCUSDT_1m_2y.csv"
DOC_PATH = ROOT / "docs" / "RESEARCH_regime_conditional_grid_2026-05-17.md"
CONFIG_PATH = ROOT / "state" / "bot_brain_regime_grid_config.json"

sys.path.insert(0, str(ROOT / "scripts"))
import volume_farm_grid_backtest as g  # type: ignore

# Sweet-spot params from earlier sweep
BEST = dict(
    contract="inverse", grid_range_pct=0.6, grid_levels=120,
    order_size_usd=1000.0, inventory_cap_btc=0.10,
    reanchor_drift_pct=0.3, hard_stop_unrealized_usd=-2000.0,
)


def load_price() -> pd.DataFrame:
    df = pd.read_csv(DATA_CSV, usecols=["ts", "open", "high", "low", "close", "volume"])
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return df.sort_values("ts").reset_index(drop=True)


def classify_day(day_df: pd.DataFrame, vol_percentile_thresholds: tuple[float, float]
                 ) -> tuple[str, str]:
    """Classify a day's regime + vol.
      Regime: TREND_UP if close_eod - close_sod > +1.5%, TREND_DOWN if < -1.5%,
              RANGE otherwise.
      Vol:    based on ATR percentile vs vol_thresholds (q33, q67).
    """
    if len(day_df) < 60:
        return "INSUFFICIENT", "INSUFFICIENT"
    open_p = float(day_df["close"].iloc[0])
    close_p = float(day_df["close"].iloc[-1])
    move_pct = (close_p - open_p) / open_p * 100.0
    if move_pct > 1.5:
        regime = "TREND_UP"
    elif move_pct < -1.5:
        regime = "TREND_DOWN"
    else:
        regime = "RANGE"

    # ATR proxy: mean true-range over the day
    tr = (day_df["high"] - day_df["low"]).mean()
    atr_pct = tr / close_p * 100.0
    if atr_pct < vol_percentile_thresholds[0]:
        vol = "LOW"
    elif atr_pct < vol_percentile_thresholds[1]:
        vol = "MEDIUM"
    else:
        vol = "HIGH"
    return regime, vol


def calibrate_vol_thresholds(df: pd.DataFrame) -> tuple[float, float]:
    """Compute q33, q67 ATR percentiles across all days for classification."""
    df = df.copy()
    df["date"] = df["ts"].dt.date
    daily_atr = df.groupby("date").apply(
        lambda d: (d["high"] - d["low"]).mean() / d["close"].iloc[-1] * 100.0
        if len(d) > 0 else np.nan
    ).dropna()
    return float(np.percentile(daily_atr, 33)), float(np.percentile(daily_atr, 67))


def run_day(day_df: pd.DataFrame) -> Optional[dict]:
    """Run grid sim for one day. Returns net/fills/max_dd or None if data short."""
    if len(day_df) < 60 or len(day_df) >= 24 * 60 + 200:
        # 1440 expected; allow some slack
        pass  # don't restrict
    p = g.Params(**BEST)
    try:
        r = g.run(day_df, p)
    except Exception:
        return None
    if not r.get("days_df") is not None:
        pass
    return {
        "net_usd": r.get("total_net_usd", 0),
        "volume_usd": r.get("total_volume_usd", 0),
        "fills_total": int(r["days_df"]["fills"].sum()) if "days_df" in r else 0,
        "max_dd": r.get("max_drawdown_in_run_usd", 0),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=None,
                    help="limit to last N days (default: all)")
    args = ap.parse_args()

    print("Loading 2y BTC...")
    df = load_price()
    if args.days is not None:
        cutoff = df["ts"].iloc[-1] - pd.Timedelta(days=args.days)
        df = df[df["ts"] >= cutoff].reset_index(drop=True)
    print(f"  bars: {len(df):,}  {df.ts.iloc[0]} → {df.ts.iloc[-1]}")

    vol_q33, vol_q67 = calibrate_vol_thresholds(df)
    print(f"  vol thresholds: LOW < {vol_q33:.3f}% < MEDIUM < {vol_q67:.3f}% < HIGH")

    df["date"] = df["ts"].dt.date
    days = sorted(df["date"].unique())
    print(f"  total days: {len(days)}")

    # Run each day, classify, aggregate
    cells: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for i, day in enumerate(days):
        day_df = df[df["date"] == day].reset_index(drop=True)
        if len(day_df) < 60:
            continue
        regime, vol = classify_day(day_df, (vol_q33, vol_q67))
        if regime == "INSUFFICIENT":
            continue
        result = run_day(day_df)
        if result is None:
            continue
        cells[(regime, vol)].append({
            "date": str(day), "regime": regime, "vol": vol, **result,
        })
        if (i + 1) % 100 == 0:
            print(f"  processed {i+1}/{len(days)} days...")

    # Aggregate
    print("\n=== Regime × Vol matrix (avg daily net $) ===")
    print(f"{'regime':12} {'LOW':>10} {'MEDIUM':>10} {'HIGH':>10} {'all':>10}")
    matrix = {}
    for regime in ["RANGE", "TREND_UP", "TREND_DOWN"]:
        row = [regime]
        cell_data = {}
        for vol in ["LOW", "MEDIUM", "HIGH"]:
            data = cells.get((regime, vol), [])
            if not data:
                row.append(f"{'—':>10}")
                cell_data[vol] = None
                continue
            net = np.mean([d["net_usd"] for d in data])
            n = len(data)
            row.append(f"${net:>+7,.0f} (n{n})")
            cell_data[vol] = {"avg_net_usd": round(net, 2), "n_days": n}
        # all-vol row average
        all_data = sum((cells.get((regime, v), []) for v in ["LOW", "MEDIUM", "HIGH"]), [])
        if all_data:
            net_all = np.mean([d["net_usd"] for d in all_data])
            row.append(f"${net_all:>+7,.0f}")
            cell_data["all"] = {"avg_net_usd": round(net_all, 2), "n_days": len(all_data)}
        else:
            row.append(f"{'—':>10}")
        print(f"{row[0]:12} {row[1]:>15} {row[2]:>15} {row[3]:>15} {row[4]:>10}")
        matrix[regime] = cell_data

    print("\n=== Fill rate / DD matrix ===")
    print(f"{'regime':12} {'vol':6} {'n':>4} {'avg_net':>9} {'med_net':>9} {'avg_fills':>10} {'avg_DD':>9}")
    for regime in ["RANGE", "TREND_UP", "TREND_DOWN"]:
        for vol in ["LOW", "MEDIUM", "HIGH"]:
            data = cells.get((regime, vol), [])
            if not data:
                continue
            print(f"{regime:12} {vol:6} {len(data):>4} "
                  f"${np.mean([d['net_usd'] for d in data]):>+8.0f} "
                  f"${np.median([d['net_usd'] for d in data]):>+8.0f} "
                  f"{np.mean([d['fills_total'] for d in data]):>10.1f} "
                  f"${np.mean([d['max_dd'] for d in data]):>+8.0f}")

    # Save config recommendations
    config = {
        "generated_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "source_script": "scripts/regime_conditional_grid_research.py",
        "params_used": BEST,
        "vol_thresholds_pct_atr": {"q33": vol_q33, "q67": vol_q67},
        "matrix_avg_daily_net_usd": matrix,
        # Recommended size multiplier per regime (relative to baseline 1.0)
        # Based on observed avg_net signs (+/−), with caution
        "size_multiplier_by_regime": _derive_size_multipliers(matrix),
    }
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nWrote {CONFIG_PATH}")

    # Write doc
    _write_doc(cells, matrix, vol_q33, vol_q67, config["size_multiplier_by_regime"])


def _derive_size_multipliers(matrix: dict) -> dict:
    """Derive size-multiplier recommendation per (regime, vol) cell.
    Heuristic: if avg_net positive AND median positive → 1.0 (full size),
               if positive but small → 0.7, if neutral/slightly negative → 0.5,
               if clearly negative → 0.0 (pause grid)."""
    out = {}
    for regime, cells in matrix.items():
        out[regime] = {}
        for vol, data in cells.items():
            if data is None:
                out[regime][vol] = None
                continue
            net = data["avg_net_usd"]
            if net > 300:
                m = 1.5
            elif net > 100:
                m = 1.0
            elif net > 0:
                m = 0.7
            elif net > -100:
                m = 0.5
            else:
                m = 0.0  # pause grid
            out[regime][vol] = m
    return out


def _write_doc(cells, matrix, vol_q33, vol_q67, multipliers) -> None:
    lines = [
        "# Regime-conditional grid performance — Phase 3.6 (2026-05-17)",
        "",
        "**Цель:** определить когда volume-farm grid bot реально работает.",
        "Если в TREND/HIGH vol он минусует — на эти периоды размер уменьшать или паузить.",
        "Если RANGE/LOW — увеличивать.",
        "",
        f"**Method:** 2y BTC 1m данных, sweet-spot params (levels=120, size=$1000, "
        f"cap=0.10 BTC). Каждый день классифицируется (regime × vol) и симулируется "
        f"отдельно. Vol thresholds: LOW < {vol_q33:.3f}% < MED < {vol_q67:.3f}% < HIGH "
        f"(daily ATR % of close).",
        "",
        "## Avg daily net (USD) по cells",
        "",
        "| Regime | LOW vol | MEDIUM | HIGH | all vols |",
        "|---|---|---|---|---|",
    ]
    for regime in ["RANGE", "TREND_UP", "TREND_DOWN"]:
        row = [regime]
        for vol in ["LOW", "MEDIUM", "HIGH", "all"]:
            d = matrix.get(regime, {}).get(vol)
            if d is None:
                row.append("—")
            else:
                row.append(f"${d['avg_net_usd']:+,.0f} (n={d['n_days']})")
        lines.append(f"| {row[0]} | {row[1]} | {row[2]} | {row[3]} | {row[4]} |")
    lines.append("")
    lines.append("## Size multiplier recommendation")
    lines.append("")
    lines.append("Use as bot_brain rule R3.x param: при `regime=X, vol=Y` множитель base size на коэффициент.")
    lines.append("")
    lines.append("| Regime | LOW | MEDIUM | HIGH |")
    lines.append("|---|---|---|---|")
    for regime, vols in multipliers.items():
        row = [regime, vols.get("LOW"), vols.get("MEDIUM"), vols.get("HIGH")]
        lines.append(f"| {row[0]} | {row[1]} | {row[2]} | {row[3]} |")
    lines.append("")
    lines.append("## Применение")
    lines.append("")
    lines.append("`state/bot_brain_regime_grid_config.json` — машиночитаемая версия. "
                  "Будущий R3.5_regime_resize правило consult'ит этот файл и предлагает "
                  "resize action для testbed bot когда detect'ит regime/vol cell с "
                  "multiplier ≠ 1.0.")
    lines.append("")
    lines.append("## Caveats")
    lines.append("")
    lines.append("- Classification одного дня — coarse. Реальный регайм меняется внутри дня.")
    lines.append("- Sample sizes неравномерные: некоторые cells могут быть малыми.")
    lines.append("- Sweet-spot params — те же что в sweep. Если базовые params поменяются, "
                  "matrix нужно пересчитать.")
    lines.append("- 0.0 multiplier = pause grid — НЕ паузит сам по себе. Это рекомендация "
                  "operator decision-support layer.")
    DOC_PATH.parent.mkdir(parents=True, exist_ok=True)
    DOC_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {DOC_PATH}")


if __name__ == "__main__":
    main()
