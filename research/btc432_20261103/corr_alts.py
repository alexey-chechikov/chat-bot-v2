"""Оператор 03.11: «12 монет — разве они раскоррелированы от битка?» Замер: корреляция дневных доходностей альтов с BTC
и совпадение сигналов 432 по времени (вход альта в течение ±3 суток от входа BTC). Данные — research/trend_expand/data/*_4h.csv
(Binance spot 4h)."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research" / "tv_lab_1025"))
from validate_432 import s432  # noqa: E402

D = ROOT / "research" / "trend_expand" / "data"
ALTS = ["ETHUSDT", "BNBUSDT", "XRPUSDT", "LTCUSDT", "ADAUSDT", "LINKUSDT", "DOGEUSDT", "TRXUSDT", "SOLUSDT"]


def load(sym):
    d = pd.read_csv(D / f"{sym}_4h.csv")
    tcol = next(c for c in d.columns if c in ("ts", "open_time", "t", "time"))
    t = pd.to_datetime(d[tcol], unit="ms" if d[tcol].iloc[0] > 1e11 else "s", utc=True)
    return d.set_index(t)[["open", "high", "low", "close"]].astype(float)


def entries(df):
    arr = tuple(df[k].to_numpy() for k in ("open", "high", "low", "close"))
    t = df.index
    return pd.DatetimeIndex([t[j] for j, k, *_r in s432(arr)])


btc = load("BTCUSDT")
bd = btc["close"].resample("1D").last().pct_change()
be = entries(btc)
print(f"BTC: 4h {btc.index[0].date()} → {btc.index[-1].date()}, сделок 432 {len(be)}")
print("монета | корр. дневных доходностей с BTC: всё / 2024–2026 | сделок 432 | доля входов в ±3 сут от входа BTC")
for s in ALTS:
    df = load(s)
    d = df["close"].resample("1D").last().pct_change()
    j = pd.concat([bd, d], axis=1, join="inner").dropna()
    j2 = j[j.index >= "2024-01-01"]
    ae = entries(df)
    near = np.mean([np.min(np.abs((be - a).total_seconds())) <= 3 * 86400 for a in ae]) if len(ae) else np.nan
    print(f"{s} | {j.corr().iloc[0, 1]:.2f} / {j2.corr().iloc[0, 1]:.2f} | {len(ae)} | {100 * near:.0f}%")
