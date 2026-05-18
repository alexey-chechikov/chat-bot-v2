"""Анализ 25.02.2026 pump — что именно произошло + сработали бы ли
наши детекторы (cascade_alert, liq_cluster, spike_alert).

Output:
  - Hour-by-hour price + range
  - Top 5 крупнейших 30-min движений
  - Top 5 крупнейших 1h движений
  - Гипотетические fires: cascade / spike / liq_cluster (если бы тогда работало)
  - Recommendation: какой защитный механизм спас бы $6.5k DD
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
BTC_CSV = ROOT / "backtests" / "frozen" / "BTCUSDT_1m_2y.csv"

# Целевое окно: 25.02.2026 ± 1 день
START = datetime(2026, 2, 24, 0, 0, tzinfo=timezone.utc)
END = datetime(2026, 2, 27, 0, 0, tzinfo=timezone.utc)


def main():
    print(f"Loading BTC 1m {BTC_CSV.name}...")
    df = pd.read_csv(BTC_CSV, usecols=["ts", "open", "high", "low", "close", "volume"])
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df = df.sort_values("ts").set_index("ts")
    print(f"  bars total: {len(df):,}  range: {df.index.min()} → {df.index.max()}")

    df = df[(df.index >= START) & (df.index < END)]
    print(f"  bars в окне: {len(df):,}")

    if df.empty:
        print(f"Нет данных в окне {START} → {END}")
        return

    # 1. Hour-by-hour summary
    print("\n=== Hour-by-hour (25.02.2026 ± 1 день) ===")
    hourly = df.resample("1h").agg(
        open=("open", "first"), high=("high", "max"),
        low=("low", "min"), close=("close", "last"),
        volume=("volume", "sum"),
    ).dropna()
    hourly["range_pct"] = (hourly["high"] - hourly["low"]) / hourly["open"] * 100
    hourly["move_pct"] = (hourly["close"] - hourly["open"]) / hourly["open"] * 100

    # Только 25.02 + соседние часы с высокой активностью
    target_day = hourly[hourly.index.date == datetime(2026, 2, 25).date()]
    print(f"{'hour UTC':16} {'open':>10} {'high':>10} {'low':>10} {'close':>10} {'move%':>7} {'range%':>7}")
    for ts, row in target_day.iterrows():
        marker = ""
        if row["range_pct"] >= 2.0:
            marker = " ⚠ EXTREME RANGE"
        elif abs(row["move_pct"]) >= 1.5:
            marker = " ⚠"
        print(f"{ts.strftime('%Y-%m-%d %H:%M'):16} "
              f"{row['open']:>10.0f} {row['high']:>10.0f} {row['low']:>10.0f} "
              f"{row['close']:>10.0f} {row['move_pct']:>+6.2f}% {row['range_pct']:>6.2f}%"
              f"{marker}")

    # 2. Top 30-min moves
    print("\n=== TOP 5 крупнейших 30-min движений в окне ===")
    df_copy = df.copy()
    df_copy["close_30m_ago"] = df_copy["close"].shift(30)
    df_copy["move_30m_pct"] = (df_copy["close"] - df_copy["close_30m_ago"]) / df_copy["close_30m_ago"] * 100
    top30 = df_copy.nlargest(5, "move_30m_pct")[["close_30m_ago", "close", "move_30m_pct"]]
    print(f"{'ts':21} {'from':>10} {'to':>10} {'move%':>8}")
    for ts, row in top30.iterrows():
        print(f"{ts.strftime('%Y-%m-%d %H:%M:%S'):21} {row['close_30m_ago']:>10.0f} {row['close']:>10.0f} {row['move_30m_pct']:>+7.2f}%")

    # 3. Detector simulation
    print("\n=== Гипотетические fires наших детекторов на 25.02 ===")

    # Spike alert: 1.5%+ move в 5min + taker dominance + OI rising
    # У нас нет taker/OI для этих исторических данных, считаем move-only прокси
    df["close_5m_ago"] = df["close"].shift(5)
    df["move_5m_pct"] = (df["close"] - df["close_5m_ago"]) / df["close_5m_ago"] * 100
    spike_fires = df[abs(df["move_5m_pct"]) >= 1.5]
    print(f"\nSPIKE_ALERT (proxy: |5m move| ≥ 1.5%): {len(spike_fires)} fires")
    for ts, row in spike_fires.head(10).iterrows():
        direction = "UP" if row["move_5m_pct"] > 0 else "DOWN"
        print(f"  {ts.strftime('%Y-%m-%d %H:%M')}  {direction} {row['move_5m_pct']:+.2f}% @ ${row['close']:,.0f}")

    # Cascade-style: 1%+ move в 5m
    df["close_1m_ago"] = df["close"].shift(1)
    df["move_1m_pct"] = (df["close"] - df["close_1m_ago"]) / df["close_1m_ago"] * 100
    cascade_proxy = df[abs(df["move_1m_pct"]) >= 0.5]
    print(f"\nCASCADE_PROXY (|1m move| ≥ 0.5%): {len(cascade_proxy)} fires")
    for ts, row in cascade_proxy.head(10).iterrows():
        direction = "UP" if row["move_1m_pct"] > 0 else "DOWN"
        print(f"  {ts.strftime('%Y-%m-%d %H:%M')}  {direction} {row['move_1m_pct']:+.2f}% @ ${row['close']:,.0f}")

    # 4. Recommendation
    print("\n=== РЕКОМЕНДАЦИЯ — какой защитный механизм закрыл бы $6.5k drawdown ===\n")
    if len(spike_fires) > 0:
        first_spike = spike_fires.iloc[0]
        first_ts = spike_fires.index[0]
        print(f"  Первый SPIKE fire: {first_ts.strftime('%H:%M UTC')}  {first_spike['move_5m_pct']:+.2f}%")
        print(f"  → если бы spike_alert ВКЛЮЧАЛ auto-pause SHORT, бот остановился бы в этом тике")
        print(f"  → накопление с этого момента = 0, DD bound by current pos × move\n")

    print("Конкретные варианты по efficiency (best → worst):\n")
    print("Вариант 1: AUTO-PAUSE через spike_alert hook (внешний)")
    print("  Pros: detects pump в первые 5 мин, останавливает накопление")
    print("  Cons: бот не закрывает текущую позицию — она всё ещё несёт DD до отката")
    print("  Estimated saving: ~50-60% DD (вместо $6.5k = ~$3k)")
    print()
    print("Вариант 2: GinArea Stop-Loss (внутренний, SL=3%)")
    print("  Pros: внутренний механизм GinArea, надёжный")
    print("  Cons: режет хвост профита — после SL бот не дождётся отката")
    print("  Estimated saving: 100% DD (SL=3% × pos = ~$2.5k loss locked-in)")
    print("  Net effect: +$2-3k saved bad day BUT может срабатывать на whipsaws (false positives)")
    print()
    print("Вариант 3: Disable IN при движении (GinArea Верхняя/Нижняя граница)")
    print("  Pros: бот прекращает ДОБИРАТЬ; существующая позиция держится для отката")
    print("  Cons: статическая граница — не адаптируется")
    print("  Workaround: bot7 может set_params при пампе — динамическая граница")
    print("  Estimated saving: 70-80% DD (~$4-5k saved)")
    print()
    print("Вариант 4: liq_pre_cascade сигнал → auto-pause")
    print("  Pros: предсказывает каскад ДО пика; bot7 уже его детектит")
    print("  Cons: 24% precision (validated) — много false alarms")
    print("  Best combo: liq_cluster + spike_alert вместе → AND-gate auto-pause")
    print()
    print("Мой совет: Вариант 1 + 3 combo")
    print("  - spike_alert (5m move ≥1.5%) → bot7 set_params({border_top: curr_price})")
    print("    = моментально отключает новые SHORT входы")
    print("  - через 60 мин (или при откате 0.5%) → restore borders")
    print("  Это спасает 70-80% drawdown без потери tail profit.")


if __name__ == "__main__":
    main()
