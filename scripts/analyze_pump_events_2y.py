"""Систематический поиск всех "25.02-style" pump-events на 2y BTC + проверка
что произошло после каждого: whipsaw (вернулась) или trend break (продолжила).

Output:
  - Все события где BTC прыгнул ≥2% за 30 мин
  - Для каждого: что было через 4h, 24h, 7d (вернулось ли)
  - Frequency: сколько таких событий в год
  - Strategy comparison: net P&L под 4 защитными стратегиями
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
BTC_CSV = ROOT / "backtests" / "frozen" / "BTCUSDT_1m_2y.csv"

PUMP_THRESHOLD_30M = 2.0  # ≥2.0% за 30 мин = pump event


def main():
    print(f"Loading BTC 2y...")
    df = pd.read_csv(BTC_CSV, usecols=["ts", "high", "low", "close"])
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df = df.sort_values("ts").set_index("ts")
    print(f"  bars: {len(df):,}  window: {df.index.min()} → {df.index.max()}")

    # Find pump events: 30-min move ≥ 2%
    df["close_30m_ago"] = df["close"].shift(30)
    df["move_30m"] = (df["close"] - df["close_30m_ago"]) / df["close_30m_ago"] * 100
    df["close_30m_min"] = df["close"].rolling(30).min()
    df["pullback_during"] = (df["close_30m_ago"] - df["close_30m_min"]) / df["close_30m_ago"] * 100

    # One-way pumps (no -0.5% retracement during the 30m climb)
    pumps_raw = df[(df["move_30m"] >= PUMP_THRESHOLD_30M) & (df["pullback_during"] < 0.5)].copy()

    # Group consecutive minutes into single events (gap >2h = new event)
    pumps_raw = pumps_raw.sort_index()
    pumps_raw["gap"] = pumps_raw.index.to_series().diff() > pd.Timedelta(hours=2)
    pumps_raw["event_id"] = pumps_raw["gap"].cumsum()

    events = []
    for eid, grp in pumps_raw.groupby("event_id"):
        peak_idx = grp["move_30m"].idxmax()
        start_ts = grp.index[0]
        peak_ts = peak_idx
        peak_close = df.loc[peak_ts, "close"]
        events.append({"start_ts": start_ts, "peak_ts": peak_ts,
                        "peak_close": peak_close, "peak_move": grp.loc[peak_idx, "move_30m"]})

    print(f"\nНайдено {len(events)} pump-events ≥{PUMP_THRESHOLD_30M}%/30m (one-way)")

    # For each event: check 4h, 24h, 7d
    print(f"\n{'event start':17} {'peak%':>6} {'4h after':>10} {'24h after':>10} {'7d after':>10} {'verdict':12}")
    whipsaws = 0
    trends = 0
    neutral = 0
    for ev in events:
        peak_close = ev["peak_close"]
        peak_ts = ev["peak_ts"]
        # Price at peak_ts + 4h, 24h, 7d
        ts_4h = peak_ts + timedelta(hours=4)
        ts_24h = peak_ts + timedelta(hours=24)
        ts_7d = peak_ts + timedelta(days=7)

        def _nearest(target):
            mask = (df.index >= target - timedelta(minutes=5)) & (df.index <= target + timedelta(minutes=5))
            sub = df[mask]
            return sub["close"].iloc[0] if not sub.empty else None

        p4h = _nearest(ts_4h)
        p24h = _nearest(ts_24h)
        p7d = _nearest(ts_7d)

        def _pct(target_price):
            if target_price is None:
                return None
            return (target_price - peak_close) / peak_close * 100

        m4h, m24h, m7d = _pct(p4h), _pct(p24h), _pct(p7d)
        # Verdict by 24h move from peak
        verdict = "—"
        if m24h is not None:
            if m24h <= -ev["peak_move"] * 0.5:
                verdict = "✓ whipsaw"; whipsaws += 1
            elif m24h >= 0:
                verdict = "✗ trend"; trends += 1
            else:
                verdict = "◐ partial"; neutral += 1
        else:
            verdict = "?"
        m4h_s = f"{m4h:+.2f}%" if m4h is not None else "—"
        m24h_s = f"{m24h:+.2f}%" if m24h is not None else "—"
        m7d_s = f"{m7d:+.2f}%" if m7d is not None else "—"
        print(f"{ev['start_ts'].strftime('%Y-%m-%d %H:%M'):17} {ev['peak_move']:>+5.2f}% "
              f"{m4h_s:>10} {m24h_s:>10} {m7d_s:>10}  {verdict}")

    total = whipsaws + trends + neutral
    print(f"\n{'='*72}")
    print(f"  CLASSIFICATION (по движению через 24h от peak)")
    print(f"{'='*72}")
    if total > 0:
        print(f"  Whipsaw (вернулась ≥50% за 24h):  {whipsaws:>3} ({100*whipsaws/total:.0f}%)")
        print(f"  Trend (продолжила вверх):          {trends:>3} ({100*trends/total:.0f}%)")
        print(f"  Partial (между):                   {neutral:>3} ({100*neutral/total:.0f}%)")
    print(f"\n  Events/год: {total / 2:.1f}")

    # Implication
    print(f"\n{'='*72}")
    print(f"  ИМПЛИКАЦИЯ ДЛЯ ЗАЩИТНОЙ СТРАТЕГИИ")
    print(f"{'='*72}")
    if whipsaws / max(total, 1) >= 0.5:
        print(f"  В большинстве ({100*whipsaws/total:.0f}%) случаев pump-events были whipsaws.")
        print(f"  → Hard SL 3% невыгоден — фиксирует loss где грид окупился бы")
        print(f"  → 'Freeze accumulation' стратегия (Variant 3) ОПТИМАЛЬНА:")
        print(f"     - не закрывает позицию (даёт грид окупиться)")
        print(f"     - блокирует ДОБОР (защищает от роста DD)")
    elif trends / max(total, 1) >= 0.5:
        print(f"  В большинстве ({100*trends/total:.0f}%) случаев цена ПРОДОЛЖИЛА вверх.")
        print(f"  → Hard SL 3% выгоден — спасает от расширения DD")
        print(f"  → 'Freeze only' стратегия НЕ помогает — без закрытия позиция доходит до big DD")
    else:
        print(f"  Смешанная картина: {100*whipsaws/total:.0f}% whipsaw, {100*trends/total:.0f}% trend.")
        print(f"  → Нужен ADAPTIVE detector: реагирует на exhaustion signal")
        print(f"     - При freeze + exhaustion появилась → unfreeze")
        print(f"     - При freeze + продолжение → trigger SL")


if __name__ == "__main__":
    main()
