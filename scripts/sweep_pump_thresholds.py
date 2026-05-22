"""Sweep по порогам pump-detection + оценка эффективности паузы на 2y BTC.

Для каждого порога меряет:
  - Events/год
  - Доли whipsaw / trend / partial по 24h движению от peak
  - Average peak_move ПОСЛЕ trigger (сколько ещё цена прошла от trigger до peak)
  - Estimated DD avoided если пауза сработала на trigger (proxy)

Использует упрощённую модель бота: при отсутствии паузы бот добирает 1 BTC
в течение всего pump-окна (от trigger до peak); avg entry = midway.
DD без паузы ≈ accumulated_btc × (peak_price - avg_entry).
DD с паузой ≈ 0 (новые входы заблокированы).

Recommendation: balance events/год vs avg_dd_saved.
"""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
BTC_CSV = ROOT / "backtests" / "frozen" / "BTCUSDT_1m_2y.csv"

# Assumed bot accumulation during a 30-min pump (1 BTC at avg entry).
# Используется для proxy DD avoided. Реальное value зависит от bot config.
BOT_ACCUM_BTC = 1.0


def find_events(df: pd.DataFrame, *, threshold_pct: float, window_min: int,
                 max_pullback_pct: float = 0.5) -> pd.DataFrame:
    """Find one-way pump events ≥ threshold_pct в window_min."""
    df = df.copy()
    df["close_back"] = df["close"].shift(window_min)
    df["move_pct"] = (df["close"] - df["close_back"]) / df["close_back"] * 100
    df["min_back"] = df["close"].rolling(window_min).min()
    df["pullback"] = (df["close_back"] - df["min_back"]) / df["close_back"] * 100
    raw = df[(df["move_pct"] >= threshold_pct) & (df["pullback"] < max_pullback_pct)].copy()
    if raw.empty:
        return raw
    raw = raw.sort_index()
    raw["gap"] = raw.index.to_series().diff() > pd.Timedelta(hours=2)
    raw["event_id"] = raw["gap"].cumsum()

    events = []
    for eid, grp in raw.groupby("event_id"):
        peak_idx = grp["move_pct"].idxmax()
        events.append({
            "trigger_ts": grp.index[0],  # первый бар где move ≥ threshold
            "peak_ts": peak_idx,
            "trigger_close": grp.iloc[0]["close"],
            "peak_close": grp.loc[peak_idx, "close"],
            "trigger_move_pct": grp.iloc[0]["move_pct"],
            "peak_move_pct": grp.loc[peak_idx, "move_pct"],
        })
    return pd.DataFrame(events)


def classify_outcome(peak_close: float, peak_move: float,
                      df: pd.DataFrame, peak_ts) -> str:
    """24h-from-peak: whipsaw if reverted ≥50%, trend if continued up, partial else."""
    target = peak_ts + timedelta(hours=24)
    mask = (df.index >= target - timedelta(minutes=5)) & (df.index <= target + timedelta(minutes=5))
    sub = df[mask]
    if sub.empty:
        return "?"
    p24 = sub["close"].iloc[0]
    move = (p24 - peak_close) / peak_close * 100
    if move <= -peak_move * 0.5:
        return "whipsaw"
    if move >= 0:
        return "trend"
    return "partial"


def estimate_dd_avoided(events: pd.DataFrame, df: pd.DataFrame) -> dict:
    """Per-event estimate какой DD spaшается paused-стратегией.

    Модель: без паузы бот добирает BOT_ACCUM_BTC за окно от trigger до peak.
    Avg entry = midway между trigger_close и peak_close.
    DD at peak = BOT_ACCUM_BTC × (peak - avg_entry).
    Saved DD = эта величина (paused = 0 new accumulation).
    """
    saves = []
    for _, ev in events.iterrows():
        trigger_close = ev["trigger_close"]
        peak_close = ev["peak_close"]
        # avg entry of new shorts during the move (linear price climb assumption)
        avg_entry = (trigger_close + peak_close) / 2
        dd_avoided = BOT_ACCUM_BTC * (peak_close - avg_entry)
        saves.append(dd_avoided)
    if not saves:
        return {"mean": 0, "median": 0, "total": 0, "max": 0}
    s = pd.Series(saves)
    return {"mean": s.mean(), "median": s.median(), "total": s.sum(), "max": s.max()}


def main():
    print(f"Loading BTC 2y...")
    df = pd.read_csv(BTC_CSV, usecols=["ts", "high", "low", "close"])
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df = df.sort_values("ts").set_index("ts")
    years = (df.index.max() - df.index.min()).total_seconds() / (365.25 * 86400)
    print(f"  bars: {len(df):,}  years: {years:.2f}\n")

    thresholds = [
        # (label, move%, window_min)
        ("СТРОГИЙ:  ≥2.5% / 30мин", 2.5, 30),
        ("СТРОГИЙ:  ≥2.0% / 30мин", 2.0, 30),
        ("СРЕДНИЙ:  ≥1.5% / 30мин", 1.5, 30),
        ("СРЕДНИЙ:  ≥1.5% / 15мин", 1.5, 15),
        ("ШИРОКИЙ:  ≥1.0% / 30мин", 1.0, 30),
        ("ШИРОКИЙ:  ≥1.0% / 15мин", 1.0, 15),
        ("FAST:     ≥0.8% / 10мин", 0.8, 10),
    ]

    print(f"{'config':28} {'events':>9} {'/год':>7} {'WS%':>5} {'TR%':>5} {'PT%':>5} "
          f"{'avg DD':>9} {'med DD':>9} {'total/2y':>11} {'/год':>9}")
    print("─" * 110)
    results = []
    for label, thr, win in thresholds:
        events = find_events(df, threshold_pct=thr, window_min=win)
        n = len(events)
        if n == 0:
            print(f"{label:28} {n:>9}")
            continue
        # Classify each
        outcomes = events.apply(
            lambda r: classify_outcome(r["peak_close"], r["peak_move_pct"], df, r["peak_ts"]),
            axis=1,
        )
        ws = (outcomes == "whipsaw").sum()
        tr = (outcomes == "trend").sum()
        pt = (outcomes == "partial").sum()
        dd = estimate_dd_avoided(events, df)
        per_year = n / years
        dd_total_year = dd["total"] / years
        print(f"{label:28} {n:>9} {per_year:>7.1f} "
              f"{100*ws/n:>4.0f}% {100*tr/n:>4.0f}% {100*pt/n:>4.0f}% "
              f"${dd['mean']:>+8.0f} ${dd['median']:>+8.0f} "
              f"${dd['total']:>+10,.0f} ${dd_total_year:>+8,.0f}")
        results.append({
            "label": label, "n": n, "per_year": per_year,
            "whipsaw_pct": 100 * ws / n, "trend_pct": 100 * tr / n,
            "avg_dd": dd["mean"], "total_dd_year": dd_total_year,
        })

    # Recommendation
    print()
    print("═" * 110)
    print("  ИНТЕРПРЕТАЦИЯ")
    print("═" * 110)
    print(f"  Колонки:")
    print(f"    events/год = частота срабатываний")
    print(f"    WS%/TR%/PT% = whipsaw / trend / partial по 24h движению от peak")
    print(f"    avg DD = средний DD avoided (на 1 BTC accumulated) при паузе на trigger")
    print(f"    total/год = годовая сумма avoided DD при 100% efficacy")
    print()
    print("  Trade-off:")
    print("    - Низкий порог → больше срабатываний, больше total saved, но больше false freeze")
    print("    - Высокий порог → меньше срабатываний, но крупные события точно ловятся")
    print()
    if results:
        # Best balance: max (total_dd_year / per_year) — DD-saved per event
        for r in results:
            r["dd_per_event"] = r["total_dd_year"] / max(r["per_year"], 1)
        best_balance = max(results, key=lambda r: r["total_dd_year"])
        best_per_event = max(results, key=lambda r: r["dd_per_event"])
        print(f"  Best by TOTAL saved DD/год: {best_balance['label']}")
        print(f"    → ${best_balance['total_dd_year']:,.0f}/год при {best_balance['per_year']:.0f} events/год")
        print(f"  Best by DD-per-event (наиболее качественный сигнал): {best_per_event['label']}")
        print(f"    → ${best_per_event['dd_per_event']:,.0f}/event при {best_per_event['per_year']:.0f} events/год")
        print()
        print("  Моя рекомендация:")
        # Find sweet spot — between high efficiency and reasonable freq
        # Prefer where TR% >= 30% (trends обязательно ловим) AND per_year <= 200
        good = [r for r in results if r["per_year"] <= 200 and r["trend_pct"] >= 30]
        if good:
            best = max(good, key=lambda r: r["total_dd_year"])
            print(f"    {best['label']}")
            print(f"    → {best['per_year']:.0f} events/год (~{best['per_year']/52:.1f}/неделя)")
            print(f"    → ${best['total_dd_year']:,.0f}/год avoided DD (proxy на 1 BTC accumulation)")
            print(f"    → {best['whipsaw_pct']:.0f}% whipsaw + {best['trend_pct']:.0f}% trend + остальное")
            print(f"    Balance: достаточно redko чтобы не быть noisy, ловит крупные movements")


if __name__ == "__main__":
    main()
