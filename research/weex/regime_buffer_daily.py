"""Проверка полосы SMA100 на длинной истории (25.10) — прокси к regime_buffer.py: сетку по дневкам не прогнать, поэтому
мерится вклад самого выключателя: держать 1 единицу лонга, пока режим ЛОНГ (правило как у сеток, с полосой b), иначе вне
рынка. Решение на закрытии дня d, позиция в день d+1 (доходность close(d+1)/close(d) − 1); каждая смена — 0.068%
(тейкер 0.048% + проскальзывание 0.02%). Полосы — те же 5 точек 0/0.5/1/2/3 %.
Периоды: до 23.08.2024 — до окна сеточного бэктеста и выбора SMA100 (вне выборки для полосы); с 23.08.2024 — окно сеток.
Данные: data/historical/daily_{BTC,ETH}USDT.csv (Binance spot, с 17.08.2017). Это не итог сеток: показывает только,
помогает ли гистерезис выключателю вообще, на большем числе пересечений."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
BANDS = (0.0, 0.5, 1.0, 2.0, 3.0)
COST = 0.00068
SPLIT = pd.Timestamp("2024-08-23")


def regime(close: pd.Series, band: float) -> pd.Series:
    sma = close.rolling(100).mean()
    b, st, out = band / 100, None, []
    for x, s in zip(close, sma):
        if np.isnan(s):
            out.append(np.nan)
            continue
        if st is None:
            st = x > s
        elif st and x < s * (1 - b):
            st = False
        elif not st and x > s * (1 + b):
            st = True
        out.append(float(st))
    return pd.Series(out, index=close.index)


def stats(close: pd.Series, reg: pd.Series, lo, hi) -> tuple[float, int, float, int]:
    pos = reg.shift(1)                                    # решение дня d — позиция в день d+1
    ret = close.pct_change()
    m = (close.index >= lo) & (close.index < hi) & pos.notna()
    p, r = pos[m], ret[m]
    flips = int((p.diff().abs() == 1).sum())
    pnl = (p * r).sum() * 100 - flips * COST * 100        # % от единицы позиции, без сложного процента
    eq = (p * r).cumsum() - (p.diff().abs() == 1).cumsum() * COST
    dd = float((eq - eq.cummax()).min() * 100)
    return pnl, flips, dd, int(p.sum())


def main():
    for sym in ("BTCUSDT", "ETHUSDT"):
        d = pd.read_csv(ROOT / "data" / "historical" / f"daily_{sym}.csv")
        close = pd.Series(d["close"].to_numpy(float), index=pd.to_datetime(d["ts_ms"], unit="ms"))
        if close.index.duplicated().any() or (close.index.to_series().diff().dropna() != pd.Timedelta(days=1)).any():
            sys.exit(f"{sym}: дни с пропусками или дублями — отказ")
        print(f"{sym}: {close.index[0].date()} … {close.index[-1].date()}, дней {len(close)}")
        print(f"{'полоса':>7} | {'2017–08.2024: лонг %':>20} {'смен':>5} {'просадка':>9} | "
              f"{'08.2024–2026: лонг %':>20} {'смен':>5} {'просадка':>9}")
        for b in BANDS:
            reg = regime(close, b)
            a = stats(close, reg, close.index[0], SPLIT)
            z = stats(close, reg, SPLIT, close.index[-1] + pd.Timedelta(days=1))
            print(f"{b:>6g}% | {a[0]:>+20.1f} {a[1]:>5} {a[2]:>+9.1f} | {z[0]:>+20.1f} {z[1]:>5} {z[2]:>+9.1f}")


if __name__ == "__main__":
    main()
