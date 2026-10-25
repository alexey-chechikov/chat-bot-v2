"""Минутки 2017–2024 с остановками Binance → непрерывная минутная сетка для regime_grid (25.10).
Пропущенная минута = биржа не торговала: OHLC = закрытие предыдущей минуты, объём 0 (исполнений в остановку нет,
закрытие дня — последняя реальная цена), столбец filled = 1 — regime_grid в такие минуты не торгует. Печатает дыры.
Запуск: fill_outages.py <вход.csv> <выход.csv>"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd


def main():
    src, dst = sys.argv[1], sys.argv[2]
    d = pd.read_csv(src)
    ms = d["ts"].to_numpy(dtype=np.int64)
    if (ms % 60_000).any() or (np.diff(ms) <= 0).any():
        sys.exit("метки не на минутной сетке или не возрастают — отказ")
    full = np.arange(ms[0], ms[-1] + 60_000, 60_000, dtype=np.int64)
    gaps = np.diff(ms) // 60_000 - 1
    big = np.argsort(gaps)[::-1][:8]
    print(f"{src}: строк {len(d)}, нужно {len(full)}, пропущено минут {len(full) - len(d)}")
    for i in big:
        if gaps[i] > 0:
            print(f"  дыра {gaps[i]:>6} мин после {pd.to_datetime(ms[i], unit='ms')}")
    days = pd.Series(1, index=pd.to_datetime(ms, unit="ms").floor("D")).groupby(level=0).size()
    print(f"  неполных дней {(days < 1440).sum()} из {len(days)}")
    f = d.set_index("ts").reindex(full)
    filled = f["close"].isna().astype(int)              # 25.10: метка заполненной минуты — симулятор там не торгует
    c = f["close"].ffill()
    for k in ("open", "high", "low"):
        f[k] = f[k].fillna(c)
    f["close"] = c
    f["volume"] = f["volume"].fillna(0.0)
    f["filled"] = filled
    f.index.name = "ts"
    f.reset_index().to_csv(dst, index=False)
    print(f"  → {dst}: {len(f)} строк")


if __name__ == "__main__":
    main()
