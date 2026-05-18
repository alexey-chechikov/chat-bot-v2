"""XRP T2 param search — аналогично ETH, но на XRPUSDT 2y данных.

XRP волатильнее ETH (≈2-3× больше ATR vs BTC). Sweep по аналогии.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.eth_t2_param_search import (
    Params, load_1m, run_windows, summarize,
)

XRP_CSV = ROOT / "backtests" / "frozen" / "XRPUSDT_1m_2y.csv"


def main():
    print("Loading XRP 2y...")
    xrp = load_1m(XRP_CSV)
    print(f"  XRP bars: {len(xrp):,}")

    variants = [
        ("A: exact T2 (gs=0.030, tgt=0.25)",
         Params(gs_pct=0.030, max_levels=280, target_pct=0.25, order_size_usd=80)),
        ("B: gs ×2 (XRP wider vol)",
         Params(gs_pct=0.060, max_levels=280, target_pct=0.25, order_size_usd=80)),
        ("C: target ×2 (gs=0.030, tgt=0.50)",
         Params(gs_pct=0.030, max_levels=280, target_pct=0.50, order_size_usd=80)),
        ("D: both ×2",
         Params(gs_pct=0.060, max_levels=280, target_pct=0.50, order_size_usd=80)),
        ("E: gs ×3 (XRP very wide)",
         Params(gs_pct=0.090, max_levels=280, target_pct=0.25, order_size_usd=80)),
    ]

    summaries = []
    for label, p in variants:
        r = run_windows(xrp, p)
        s = summarize(label, r, p, "XRP")
        summaries.append((s, p))

    # Apply BTC calibration ratio (3.4×) since same sim has same overestimate
    print(f"\n\n{'='*72}")
    print("  РЕКОМЕНДАЦИЯ (real-world ÷ 3.4 калибровочный коэффициент)")
    print(f"{'='*72}")
    print(f"{'variant':40} {'sim daily':>11} {'real daily':>11} {'mean DD':>10} {'worst DD':>10}")
    for s, p in summaries:
        real_daily = s["daily_vol_usd"] / 3.4
        print(f"{s['label']:40} ${s['daily_vol_usd']:>9,.0f} ${real_daily:>9,.0f} "
              f"${s['mean_dd']:>+9,.0f} ${s['worst_dd']:>+9,.0f}")

    # Rank by vol/DD
    for s, p in summaries:
        s["vol_per_dd"] = s["daily_vol_usd"] / max(s["mean_dd"], 1)
    summaries.sort(key=lambda sp: -sp[0]["vol_per_dd"])
    best, best_p = summaries[0]

    print(f"\n→ Best by vol/DD ratio: {best['label']}")
    print(f"\nGinArea конфиг для XRP T2-equivalent:")
    print(f"  Биржа:              BITMEX")
    print(f"  Контракт:           XRPUSD inverse ИЛИ XRPUSDT linear")
    print(f"  Стратегия:          Indicator Grid")
    print(f"  Направление:        Short ⬇")
    print(f"  Условие входа:      PRICE% > 0.3 за 30 мин на 1m ind")
    print(f"  Шаг сетки:          {best_p.gs_pct}")
    print(f"  Количество ордеров: {best_p.max_levels}")
    print(f"  Размер ордера:      40 XRP (минимум на GinArea, ≈ $20-30)")
    print(f"  Макс. размер:       120 XRP")
    print(f"  Целевой уровень:    {best_p.target_pct}")
    print(f"  Плечо:              1x")

    print(f"\nОжидаемое в live (sim ÷ 3.4):")
    print(f"  Daily volume:   ${best['daily_vol_usd']/3.4:,.0f}")
    print(f"  Monthly volume: ${best['monthly_vol_usd']/3.4/1_000_000:.2f}M")
    print(f"  Mean weekly DD: ${best['mean_dd']:,.0f}")
    print(f"  Worst weekly DD: ${best['worst_dd']:,.0f}")


if __name__ == "__main__":
    main()
