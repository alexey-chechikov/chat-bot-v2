"""Синтетические минутки с taker_buy для тестов research/atlas_data (протокол ATLAS 14.10). Без CSV, сети и живого кода."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "research" / "gold", ROOT / "research" / "atlas_data"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import delta_test1 as d1  # noqa: E402
import sweep_backtest as sb  # noqa: E402

DAY0 = 20_000                     # 2024-10-04 UTC
INST = "BTCUSDT_UM"               # полный день = 1440 минут


def days(n_days: int, start_day: int = DAY0, price: float = 100.0, seed: int = 0, drift: float = 0.0) -> dict:
    """n_days полных UTC-дней по 1440 минут. Объём 1 в минуту; доля покупателя-агрессора — случайная 0.3–0.7, общая
    для всех минут 15m-свечи. drift — сдвиг цены за минуту (open минуты i = price + drift·i, close = open + drift)."""
    rng = np.random.default_rng(seed)
    n = n_days * 1440
    ts = (start_day * sb.DAY + np.arange(n) * sb.MIN).astype(np.int64)
    o = price + drift * np.arange(n, dtype=float)
    c = o + drift
    frac = np.repeat(rng.uniform(0.3, 0.7, size=n // 15), 15)
    return {"ts": ts, "open": o, "high": np.maximum(o, c), "low": np.minimum(o, c), "close": c,
            "volume": np.ones(n), "taker_buy": frac.copy()}


def info_of(a: dict) -> dict:
    return {"file": "synthetic", "rows": len(a["ts"]), "first": int(a["ts"][0]), "last": int(a["ts"][-1]),
            "sha256": "synthetic", "missing_minutes": 0}


def bar_mask(a: dict, bar_id: int):
    return (a["ts"] >= bar_id * sb.BAR) & (a["ts"] < (bar_id + 1) * sb.BAR)


def set_bar(a: dict, bar_id: int, *, o=None, h=None, l=None, c=None, tb_frac=None, volume=None) -> None:
    """Все минуты 15m-свечи `bar_id` (абсолютный номер) получают o/h/l/c; taker_buy = объём × tb_frac."""
    mk = bar_mask(a, bar_id)
    for k, val in (("open", o), ("high", h), ("low", l), ("close", c), ("volume", volume)):
        if val is not None:
            a[k][mk] = val
    if tb_frac is not None:
        a["taker_buy"][mk] = a["volume"][mk] * tb_frac


def drop_minute(a: dict, t_ms: int) -> dict:
    keep = a["ts"] != t_ms
    return {k: v[keep] for k, v in a.items()}


def bar_id(day: int, bar_in_day: int) -> int:
    return day * 96 + bar_in_day
