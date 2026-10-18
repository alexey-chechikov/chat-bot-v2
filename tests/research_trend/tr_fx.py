"""Синтетика для тестов research/trend_recheck: минуты строятся в памяти, модули грузятся по пути файла под
уникальными именами (tr_replay, tr_stats). Индикаторы (ATR/ADX/канал) в тестах исполнения задаются явно, чтобы
проверять цикл исполнения, а не данные."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd

TR = Path(__file__).resolve().parents[2] / "research" / "trend_recheck"


def _load(name: str, file: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, TR / file)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


rp = _load("tr_replay", "replay.py")
st = _load("tr_stats", "stats.py")

MIN, H4 = rp.MIN, rp.H4
START = 1717200000000            # 2024-06-01 00:00 UTC (P2, кратно 4 ч)
NB = 130                         # свечей: 120 прогрева + 10


def flat(nbars: int = NB, px: float = 100.0, start: int = START) -> dict:
    n = nbars * 240
    return {"ts": start + np.arange(n, dtype=np.int64) * MIN, "o": np.full(n, px), "h": np.full(n, px),
            "l": np.full(n, px), "c": np.full(n, px), "v": np.ones(n)}


def mi(bar: int, minute: int = 0) -> int:
    return bar * 240 + minute


def setm(m: dict, i: int, o=None, h=None, l=None, c=None) -> None:
    """Минута i: заданные поля, high/low расширяются до валидной свечи."""
    for k, v in (("o", o), ("h", h), ("l", l), ("c", c)):
        if v is not None:
            m[k][i] = v
    m["h"][i] = max(m["h"][i], m["o"][i], m["c"][i])
    m["l"][i] = min(m["l"][i], m["o"][i], m["c"][i])


def drop(m: dict, idx) -> dict:
    keep = np.ones(len(m["ts"]), bool)
    keep[np.atleast_1d(idx)] = False
    return {k: v[keep] for k, v in m.items()}


def series(m: dict, atr: float = 1.0, adx: float = 30.0, hh: float = 101.0, ll: float = 99.0,
           funding: pd.DataFrame | None = None, tick: float = 0.01, step: float = 0.001, offset_h: int = 0,
           end_ms: int | None = None) -> "rp.Series":
    s = rp.Series("ETHUSDT", m["ts"], m["o"], m["h"], m["l"], m["c"], m["v"], offset_h=offset_h, funding=funding,
                  end_ms=end_ms, tick=tick, step=step)
    s.atr = np.full(s.nb, float(atr))
    s.adx = np.full(s.nb, float(adx))
    s._chan[30] = (np.full(s.nb, float(hh)), np.full(s.nb, float(ll)))
    return s


def bar_of_ts(s, ts: int) -> int:
    return int(np.searchsorted(s.bstart, ts, "right")) - 1
