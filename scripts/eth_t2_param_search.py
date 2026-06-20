"""Поиск аналогичных T2 параметров для ETH.

T2 на BTC (production):
  - side: SHORT inverse XBTUSD
  - gs (grid step): 0.030%
  - max_opened_orders: 280
  - target: 0.25% (TP)
  - minQ: 0.001 BTC (~$80 при $80k цене)
  - in.start.cnds: PRICE% > 0.3 за 30 мин (gate)

Что делаем:
  1. SHORT-only inverse grid sim (mirror моего LONG-OBJEM)
  2. Калибровка: T2 params на BTC 2y → сравнить с known live volume ($8k/день)
  3. Sweep по ETH 2y:
     - Variant A: exact T2 (gs=0.030, target=0.25)
     - Variant B: gs ×1.5 для ETH vol (gs=0.045, target=0.25)
     - Variant C: target ×1.5 (gs=0.030, target=0.38)
     - Variant D: both (gs=0.045, target=0.38)
  4. Per-week окна: volume, max DD, fills, realized PnL
  5. Recommend best ETH config

Notes/caveats:
  - in.start.cnds gate НЕ имплементирован — sim показывает MAX activity.
    Live с gate будет давать ~50-70% от sim volume.
  - SHORT inverse PnL: pnl_eth = qty_usd × (1/exit - 1/entry); USD = pnl_eth × exit_price.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean, median

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
BTC_CSV = ROOT / "backtests" / "frozen" / "BTCUSDT_1m_2y.csv"
ETH_CSV = ROOT / "backtests" / "frozen" / "ETHUSDT_1m_2y.csv"


@dataclass
class Params:
    gs_pct: float            # grid spacing per level (%)
    max_levels: int          # SELL levels ABOVE anchor
    target_pct: float        # TP % below each SELL entry
    order_size_usd: float    # USD notional per SELL


@dataclass
class Position:
    entry: float
    qty_usd: float
    tp_price: float
    level_idx: int


@dataclass
class WindowResult:
    anchor: float
    fills_sell: int
    fills_tp: int
    volume_usd: float
    realized_pnl_usd: float
    unrealized_end_usd: float
    max_dd_usd: float
    final_price: float
    asset_move_pct: float


def short_inverse_pnl_usd(entry: float, exit_price: float, qty_usd: float) -> float:
    """Inverse SHORT PnL: pnl_native = qty_usd × (1/exit - 1/entry); USD = pnl_native × exit."""
    if entry <= 0 or exit_price <= 0:
        return 0.0
    pnl_native = qty_usd * (1.0 / exit_price - 1.0 / entry)
    return pnl_native * exit_price


def simulate_window(bars: pd.DataFrame, p: Params) -> WindowResult:
    """SHORT-only inverse grid mimicking GinArea T2 logic.

    Anchor = first bar close.
    SELL grid levels ABOVE anchor at p.gs_pct intervals.
    On price rises to level → SELL fill, create TP BUY at level × (1 - target%).
    On price drops to TP → BUY closes position.
    Level re-enabled after TP fills (GinArea auto-replace).
    """
    if bars.empty:
        return WindowResult(0, 0, 0, 0, 0, 0, 0, 0, 0)

    anchor = float(bars.iloc[0]["close"])
    grid_levels = [anchor * (1.0 + p.gs_pct / 100.0 * (i + 1)) for i in range(p.max_levels)]
    filled_sell = [False] * p.max_levels
    open_positions: list[Position] = []
    realized = 0.0
    volume = 0.0
    fills_sell = 0
    fills_tp = 0

    equity_curve: list[float] = []

    for _, row in bars.iterrows():
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])

        # 1) TP BUY fills (price dropped to TP for any open SHORT)
        for pos in list(open_positions):
            if low <= pos.tp_price:
                pnl = short_inverse_pnl_usd(pos.entry, pos.tp_price, pos.qty_usd)
                realized += pnl
                volume += pos.qty_usd  # exit notional
                fills_tp += 1
                filled_sell[pos.level_idx] = False  # level free for re-fill
                open_positions.remove(pos)

        # 2) SELL fills (price rose to grid level)
        if len(open_positions) < p.max_levels:
            for idx, level in enumerate(grid_levels):
                if filled_sell[idx]:
                    continue
                if high >= level:
                    filled_sell[idx] = True
                    qty_usd = p.order_size_usd
                    tp_price = level * (1.0 - p.target_pct / 100.0)
                    open_positions.append(Position(entry=level, qty_usd=qty_usd,
                                                    tp_price=tp_price, level_idx=idx))
                    fills_sell += 1
                    volume += qty_usd

        unrealized = sum(short_inverse_pnl_usd(pos.entry, close, pos.qty_usd)
                          for pos in open_positions)
        equity_curve.append(realized + unrealized)

    max_dd = 0.0
    peak = equity_curve[0] if equity_curve else 0.0
    for e in equity_curve:
        peak = max(peak, e)
        dd = peak - e
        if dd > max_dd:
            max_dd = dd

    final_price = float(bars.iloc[-1]["close"])
    unr_end = sum(short_inverse_pnl_usd(pos.entry, final_price, pos.qty_usd)
                   for pos in open_positions)
    return WindowResult(
        anchor=anchor,
        fills_sell=fills_sell,
        fills_tp=fills_tp,
        volume_usd=volume,
        realized_pnl_usd=realized,
        unrealized_end_usd=unr_end,
        max_dd_usd=max_dd,
        final_price=final_price,
        asset_move_pct=(final_price - anchor) / anchor * 100.0,
    )


def run_windows(df: pd.DataFrame, p: Params, window_days: int = 7) -> list[WindowResult]:
    results: list[WindowResult] = []
    bars_per_window = window_days * 24 * 60
    n_windows = len(df) // bars_per_window
    for i in range(n_windows):
        start = i * bars_per_window
        end = start + bars_per_window
        win = df.iloc[start:end]
        if len(win) < bars_per_window * 0.95:
            continue
        results.append(simulate_window(win, p))
    return results


def load_1m(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, usecols=["ts", "open", "high", "low", "close"])
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df = df.sort_values("ts").set_index("ts")
    return df


def summarize(label: str, results: list[WindowResult], p: Params,
              asset_name: str = "BTC") -> dict:
    if not results:
        print(f"  {label}: no windows")
        return {}
    volumes = [r.volume_usd for r in results]
    dds = [r.max_dd_usd for r in results]
    realized = [r.realized_pnl_usd for r in results]
    fills_sell = [r.fills_sell for r in results]

    avg_weekly_vol = mean(volumes)
    monthly_vol = avg_weekly_vol * 4
    daily_vol = avg_weekly_vol / 7

    print(f"\n{'─'*72}")
    print(f"  {label} ({asset_name})")
    print(f"  gs={p.gs_pct}%  max={p.max_levels}  target={p.target_pct}%  size=${p.order_size_usd}")
    print(f"  max-exposure=${p.order_size_usd * p.max_levels:,.0f}")
    print(f"{'─'*72}")
    print(f"Volume:   mean ${avg_weekly_vol:>10,.0f}/wk  =${daily_vol:>8,.0f}/day  =${monthly_vol/1_000_000:.2f}M/mo")
    print(f"Realized: mean ${mean(realized):>+10,.0f}/wk  median ${median(realized):>+9,.0f}")
    print(f"Max DD:   mean ${mean(dds):>+10,.0f}/wk  median ${median(dds):>+9,.0f}  worst ${max(dds):>+9,.0f}")
    print(f"Fills:    mean {mean(fills_sell):>10.0f} sell/wk")
    dd_high = sum(1 for d in dds if d >= 3000)
    print(f"DD ≥$3k:  {dd_high}/{len(dds)} ({100*dd_high/len(dds):.0f}%) — tail risk")
    return {
        "label": label,
        "asset": asset_name,
        "daily_vol_usd": daily_vol,
        "monthly_vol_usd": monthly_vol,
        "mean_realized_per_wk": mean(realized),
        "mean_dd": mean(dds),
        "worst_dd": max(dds),
        "n_windows": len(results),
    }


def main():
    print("Loading 2y datasets...")
    btc = load_1m(BTC_CSV)
    eth = load_1m(ETH_CSV)
    print(f"  BTC bars: {len(btc):,}  ETH bars: {len(eth):,}")

    summaries = []

    # ─── Калибровка на BTC ─────────────────────────────────────────────────
    print("\n=== КАЛИБРОВКА: T2 params на BTC (sanity check) ===")
    p_btc_t2 = Params(gs_pct=0.030, max_levels=280, target_pct=0.25,
                       order_size_usd=80)
    btc_results = run_windows(btc, p_btc_t2)
    s = summarize("BTC T2 baseline (gs=0.030 max=280 target=0.25 size=$80)",
                   btc_results, p_btc_t2, "BTC")
    summaries.append(s)
    print(f"\n  Known live BTC T2: ~$8k/day volume (events.csv calc)")
    print(f"  Sim daily volume:  ${s['daily_vol_usd']:,.0f}")
    ratio = s["daily_vol_usd"] / 8000.0
    print(f"  Ratio:             {ratio:.1f}× (sim {'over' if ratio>1 else 'under'}-estimates)")

    # ─── ETH variants ──────────────────────────────────────────────────────
    print("\n\n=== ETH variants: 4 шт. для подбора аналогичного T2 ===")

    variants = [
        ("A: exact T2 params on ETH",
         Params(gs_pct=0.030, max_levels=280, target_pct=0.25, order_size_usd=80)),
        ("B: gs ×1.5 (vol-adjusted)",
         Params(gs_pct=0.045, max_levels=280, target_pct=0.25, order_size_usd=80)),
        ("C: target ×1.5",
         Params(gs_pct=0.030, max_levels=280, target_pct=0.38, order_size_usd=80)),
        ("D: gs ×1.5 + target ×1.5",
         Params(gs_pct=0.045, max_levels=280, target_pct=0.38, order_size_usd=80)),
    ]

    eth_summaries = []
    for label, p in variants:
        results = run_windows(eth, p)
        s = summarize(label, results, p, "ETH")
        eth_summaries.append(s)

    # ─── Recommendation ───────────────────────────────────────────────────
    print(f"\n\n{'='*72}")
    print("  РЕКОМЕНДАЦИЯ для ETH T2-equivalent")
    print(f"{'='*72}")

    # Score: prefer high daily volume / low DD ratio
    for s in eth_summaries:
        risk_score = s["daily_vol_usd"] / max(s["mean_dd"], 1)
        s["volume_per_dd"] = risk_score
    eth_summaries.sort(key=lambda s: -s["volume_per_dd"])

    print(f"\nRanking by volume / mean DD ratio (higher = better):")
    print(f"{'variant':40} {'daily $vol':>12} {'mean DD':>10} {'worst DD':>10} {'vol/DD':>8}")
    for s in eth_summaries:
        print(f"{s['label']:40} ${s['daily_vol_usd']:>10,.0f} ${s['mean_dd']:>+9,.0f} ${s['worst_dd']:>+9,.0f} {s['volume_per_dd']:>7.1f}")

    best = eth_summaries[0]
    print(f"\n→ Лучший: {best['label']}")

    # Extract params from best
    best_label = best["label"]
    best_p = next(p for lbl, p in variants if lbl == best_label)
    print(f"\nGinArea конфиг для ETH (T2-equivalent):")
    print(f"  Биржа:              BITMEX")
    print(f"  Контракт:           ETHUSD (inverse, ETH-margined) ИЛИ ETHUSDT (linear)")
    print(f"  Стратегия:          INDICATOR GRID (как T2 BTC)")
    print(f"  Направление:        Short ⬇")
    print(f"  Условие входа:      PRICE% > 0.3 за 30 мин на 1m ind (как T2 BTC)")
    print(f"  Шаг сетки:          {best_p.gs_pct}")
    print(f"  Количество ордеров: {best_p.max_levels}")
    print(f"  Размер ордера:      0.01 ETH (минимум на GinArea) ≈ ${30 if best_p.order_size_usd<50 else 80}")
    print(f"  Макс. размер:       0.03 ETH")
    print(f"  Целевой уровень:    {best_p.target_pct}")
    print(f"  Инстоп:             {best_p.gs_pct}")
    print(f"  Мин. Стоп:          0.015")
    print(f"  Макс. Стоп:         0.04")
    print(f"  Плечо:              1x")

    print(f"\nОжидаемое (на основе 2y backtest, 104 weeks):")
    print(f"  Daily volume:   ${best['daily_vol_usd']:,.0f}")
    print(f"  Monthly volume: ${best['monthly_vol_usd']/1_000_000:.2f}M")
    print(f"  Mean weekly DD: ${best['mean_dd']:,.0f}")
    print(f"  Worst weekly DD: ${best['worst_dd']:,.0f}")
    print(f"  Mean realized PnL/wk: ${best['mean_realized_per_wk']:+,.0f}")

    print(f"\nCaveats:")
    print(f"  - sim НЕ моделирует in.start.cnds gate → live volume будет ~50-70% от sim")
    print(f"  - sim assumes ideal maker fills → реальный slippage + half-taker даст −20-30% PnL")
    print(f"  - 2y данные covers 2024-05 → 2026-05; будущий рынок может отличаться")
    print(f"  - ETH inverse contract имеет lower liquidity чем ETHUSDT linear — учти при выборе")


if __name__ == "__main__":
    main()
