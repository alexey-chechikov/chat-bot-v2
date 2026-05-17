"""Independent LONG-only inverse XBTUSD grid sim — проверка DD/volume claims
колеги по двум конфигам:
  - LONG-ОБЪЁМ: gs=0.02, max=200, target=0.13 (плотный mid-range)
  - LONG-ХЕДЖ:  gs=0.04, max=80,  target=0.85 (широкий + ленивый TP)

Mimics GinArea Indicator Grid behavior:
- Static anchor (per window start price)
- BUY limit orders at 200 levels below anchor (0.02% spacing → 4% range)
- Each BUY fill creates TP SELL at fill_price × (1 + target/100)
- max_opened limits concurrent open orders (BUY + TP)
- Inverse contract: 1 contract = $1 USD notional, margin/PnL в BTC
- LONG inverse PnL_BTC = qty_usd × (1/entry - 1/exit)
- Equity_USD = realized_PnL_USD + unrealized_PnL_USD at current price

Runs 100+ 7-day windows over 2y BTC 1m data. Per-window:
- total volume (entry + exit notional)
- max DD = peak-to-trough of (realized + unrealized) USD
- realized PnL at window end

Цель: подтвердить или опровергнуть колегин claim "DD=$0 в 11/11 окон".
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean, median

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA_CSV = ROOT / "backtests" / "frozen" / "BTCUSDT_1m_2y.csv"


@dataclass
class Params:
    gs_pct: float = 0.02            # grid spacing per level (%)
    max_levels: int = 200           # total grid levels (= max BUYs to place)
    target_pct: float = 0.13        # TP % above each BUY entry
    order_size_usd: float = 100.0   # USD notional per BUY
    contract: str = "inverse"       # XBTUSD
    # GinArea LONG-ОБЪЁМ has no in.start.cnds — always-on (per колеги doc)
    always_on: bool = True


@dataclass
class Position:
    """Single open BUY position with its TP target. level_idx tracks
    which grid level it came from — used to re-enable that level on TP close."""
    entry: float
    qty_usd: float
    tp_price: float
    level_idx: int


@dataclass
class WindowResult:
    window_start: pd.Timestamp
    window_end: pd.Timestamp
    anchor: float
    fills_buy: int
    fills_tp: int
    volume_usd: float
    realized_pnl_usd: float
    unrealized_end_usd: float
    max_dd_usd: float           # peak-to-trough of equity (rea+unr) during window
    max_dd_pct: float           # DD as % of cum capital ($order_size * max_open_count)
    end_open_positions: int     # positions still open at window end
    final_price: float
    btc_move_pct: float         # window-end vs anchor %


def long_inverse_pnl_usd(entry: float, exit_price: float, qty_usd: float) -> float:
    """Inverse XBTUSD LONG: PnL_BTC = qty_usd × (1/entry - 1/exit); USD = PnL_BTC × exit."""
    if entry <= 0 or exit_price <= 0:
        return 0.0
    pnl_btc = qty_usd * (1.0 / entry - 1.0 / exit_price)
    return pnl_btc * exit_price


def simulate_window(bars: pd.DataFrame, p: Params) -> WindowResult:
    """Simulate one 7-day window starting fresh.

    Anchor = first bar's close.
    BUY grid: 200 levels from anchor × (1 - 0.02%) down to anchor × (1 - 200 × 0.02%).
    Each level fills once when price low touches it.
    On fill: open position with TP = entry × (1 + target/100).
    TP fills when price high reaches TP.
    """
    if bars.empty:
        return WindowResult(pd.Timestamp(0), pd.Timestamp(0), 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)

    anchor = float(bars.iloc[0]["close"])
    grid_levels = [anchor * (1.0 - p.gs_pct / 100.0 * (i + 1)) for i in range(p.max_levels)]
    # filled_buy[level_idx] = bool — once filled, level не re-filled (one-shot per window)
    filled_buy = [False] * p.max_levels

    open_positions: list[Position] = []
    realized = 0.0
    volume = 0.0
    fills_buy = 0
    fills_tp = 0

    equity_curve: list[float] = []

    for _, row in bars.iterrows():
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])

        # 1) Process TP fills first (price up to TP).
        # On TP close: re-enable that grid level (GinArea auto-replaces BUY).
        for pos in list(open_positions):
            if high >= pos.tp_price:
                pnl_usd = long_inverse_pnl_usd(pos.entry, pos.tp_price, pos.qty_usd)
                realized += pnl_usd
                volume += pos.qty_usd  # exit notional
                fills_tp += 1
                filled_buy[pos.level_idx] = False  # level becomes available again
                open_positions.remove(pos)

        # 2) Process BUY fills (price down to grid levels). max_opened cap enforced.
        if len(open_positions) < p.max_levels:
            for idx, level in enumerate(grid_levels):
                if filled_buy[idx]:
                    continue
                if low <= level:
                    filled_buy[idx] = True
                    qty_usd = p.order_size_usd
                    tp_price = level * (1.0 + p.target_pct / 100.0)
                    open_positions.append(Position(entry=level, qty_usd=qty_usd,
                                                    tp_price=tp_price, level_idx=idx))
                    fills_buy += 1
                    volume += qty_usd  # entry notional

        # 3) Compute equity at close of this bar (realized + unrealized)
        unrealized = sum(long_inverse_pnl_usd(pos.entry, close, pos.qty_usd) for pos in open_positions)
        equity_curve.append(realized + unrealized)

    # Max DD on equity curve
    max_dd = 0.0
    peak = equity_curve[0] if equity_curve else 0.0
    for e in equity_curve:
        peak = max(peak, e)
        dd = peak - e
        if dd > max_dd:
            max_dd = dd

    # End-of-window unrealized
    final_price = float(bars.iloc[-1]["close"])
    unr_end = sum(long_inverse_pnl_usd(pos.entry, final_price, pos.qty_usd) for pos in open_positions)
    total_capital_usd = p.order_size_usd * p.max_levels  # max possible exposure
    dd_pct = max_dd / total_capital_usd * 100.0 if total_capital_usd > 0 else 0.0

    return WindowResult(
        window_start=bars.index[0],
        window_end=bars.index[-1],
        anchor=anchor,
        fills_buy=fills_buy,
        fills_tp=fills_tp,
        volume_usd=volume,
        realized_pnl_usd=realized,
        unrealized_end_usd=unr_end,
        max_dd_usd=max_dd,
        max_dd_pct=dd_pct,
        end_open_positions=len(open_positions),
        final_price=final_price,
        btc_move_pct=(final_price - anchor) / anchor * 100.0,
    )


def run_all_windows(df: pd.DataFrame, p: Params, window_days: int = 7) -> list[WindowResult]:
    """Split 2y data into N rolling-but-non-overlapping windows of 7 days each."""
    results: list[WindowResult] = []
    bars_per_window = window_days * 24 * 60  # 7d × 24h × 60min
    n_windows = len(df) // bars_per_window
    print(f"  splitting {len(df):,} bars into {n_windows} × {window_days}d windows")
    for i in range(n_windows):
        start = i * bars_per_window
        end = start + bars_per_window
        win = df.iloc[start:end]
        if len(win) < bars_per_window * 0.95:
            continue
        r = simulate_window(win, p)
        results.append(r)
    return results


def report_config(label: str, p: Params, results: list[WindowResult],
                   colleague_claim_monthly: float, colleague_claim_dd: str) -> dict:
    """Print per-config summary and return aggregate dict."""
    if not results:
        print(f"\n{label}: no windows simulated.")
        return {}
    volumes = [r.volume_usd for r in results]
    dds = [r.max_dd_usd for r in results]
    realized = [r.realized_pnl_usd for r in results]
    dd_zero = sum(1 for d in dds if d < 1.0)
    dd_low = sum(1 for d in dds if d < 500)
    dd_mid = sum(1 for d in dds if 500 <= d < 3000)
    dd_high = sum(1 for d in dds if d >= 3000)
    avg_weekly_vol = mean(volumes)
    monthly_vol = avg_weekly_vol * 4

    print(f"\n{'='*70}")
    print(f"  {label}")
    print(f"  Config: gs={p.gs_pct}%, max={p.max_levels}, target={p.target_pct}%, "
          f"size=${p.order_size_usd}, max-exposure=${p.order_size_usd * p.max_levels:,.0f}")
    print(f"{'='*70}")
    print(f"Volume:     mean ${mean(volumes):>10,.0f}/wk  median ${median(volumes):>10,.0f}  max ${max(volumes):>10,.0f}")
    print(f"Realized:   mean ${mean(realized):>+10,.0f}/wk  median ${median(realized):>+10,.0f}")
    print(f"Max DD:     mean ${mean(dds):>+10,.0f}/wk  median ${median(dds):>+10,.0f}  worst ${max(dds):>+10,.0f}")
    print(f"DD dist:    $0: {100*dd_zero/len(dds):.0f}%  <$500: {100*(dd_low-dd_zero)/len(dds):.0f}%  "
          f"$500-3k: {100*dd_mid/len(dds):.0f}%  $3k+: {100*dd_high/len(dds):.0f}%")
    print(f"Monthly vol: ${monthly_vol/1_000_000:.2f}M  vs колеги ${colleague_claim_monthly/1_000_000:.2f}M  "
          f"({(monthly_vol/colleague_claim_monthly - 1)*100:+.1f}%)")
    print(f"DD verdict vs колеги '{colleague_claim_dd}':")
    if mean(dds) < 200:
        print(f"  ◐ ~подтверждён (mean ${mean(dds):.0f})")
    elif mean(dds) < 1000:
        print(f"  ⚠ overstated — реальный DD ~${mean(dds):.0f}/нед mean, worst ${max(dds):.0f}")
    else:
        print(f"  ✗ NOT confirmed — mean DD ${mean(dds):.0f}, deploy carefully")
    return {
        "label": label,
        "monthly_vol_usd": monthly_vol,
        "mean_dd_usd": mean(dds),
        "median_dd_usd": median(dds),
        "worst_dd_usd": max(dds),
        "mean_realized_per_wk": mean(realized),
        "n_windows": len(results),
        "dd_high_pct": 100 * dd_high / len(dds),
    }


def main():
    print(f"Loading {DATA_CSV.name}...")
    df = pd.read_csv(DATA_CSV, usecols=["ts", "open", "high", "low", "close"])
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df = df.sort_values("ts").set_index("ts")
    print(f"  bars: {len(df):,}  range: {df.index.min()} → {df.index.max()}")

    configs = [
        ("LONG-ОБЪЁМ",
         Params(gs_pct=0.02, max_levels=200, target_pct=0.13, order_size_usd=100),
         1_680_000, "DD=$0 в 11/11 окон"),
        ("LONG-ХЕДЖ",
         Params(gs_pct=0.04, max_levels=80, target_pct=0.85, order_size_usd=100),
         2_060_000, "DD=$0 в 11/11 окон"),
    ]

    summaries = []
    for label, p, claim_vol, claim_dd in configs:
        print(f"\nRunning {label}...")
        results = run_all_windows(df, p)
        summaries.append(report_config(label, p, results, claim_vol, claim_dd))

    # Combined comparison
    if len(summaries) == 2 and all(s for s in summaries):
        print(f"\n{'='*70}")
        print(f"  COMBINED: LONG-ОБЪЁМ + LONG-ХЕДЖ параллельно")
        print(f"{'='*70}")
        s1, s2 = summaries
        print(f"  Total volume:    ${(s1['monthly_vol_usd']+s2['monthly_vol_usd'])/1_000_000:.2f}M/мес")
        print(f"  Worst DD (sum):  ${s1['worst_dd_usd']+s2['worst_dd_usd']:.0f} (если совпали в одно окно — редко)")
        print(f"  Worst DD (max):  ${max(s1['worst_dd_usd'], s2['worst_dd_usd']):.0f} (типичный случай)")
        print(f"  Mean realized:   ${(s1['mean_realized_per_wk']+s2['mean_realized_per_wk'])*52:.0f}/год")


if __name__ == "__main__":
    main()
