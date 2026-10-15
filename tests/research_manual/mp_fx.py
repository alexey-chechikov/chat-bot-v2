"""Синтетика для тестов research/manual_pullback (протокол docs/PULLBACK_4H_PROTOCOL_2026-10-15.md).
Никаких CSV, сети и живого кода. Модули грузятся под уникальными именами (mp_replay, mp_stats)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd

MP = Path(__file__).resolve().parents[2] / "research" / "manual_pullback"


def _load(name: str, file: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, MP / file)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


rp = _load("mp_replay", "replay.py")
ms = _load("mp_stats", "stats.py")

MIN, M15, H4, DAY = rp.MIN, rp.M15, rp.H4, rp.DAY
START = rp.START                                  # 2024-05-15 00:00 UTC
NOSLIP = rp.Costs("noslip", slip=0.0)


def flat_minutes(n: int, price: float = 100.0, start: int = START) -> dict:
    ts = start + np.arange(n, dtype=np.int64) * MIN
    return {"ts": ts, **{k: np.full(n, price, float) for k in ("o", "h", "l", "c")}}


def set_min(m: dict, t: int, o=None, h=None, l=None, c=None) -> None:
    i = int(np.searchsorted(m["ts"], t))
    assert m["ts"][i] == t
    for k, v in (("o", o), ("h", h), ("l", l), ("c", c)):
        if v is not None:
            m[k][i] = v


def drop_min(m: dict, t: int) -> dict:
    keep = m["ts"] != t
    return {k: v[keep] for k, v in m.items()}


def funding_df(rows) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["fundingTime", "fundingRate", "markPrice"]).astype(
        {"fundingTime": np.int64, "fundingRate": float, "markPrice": float})


def sym_from_minutes(m: dict, name: str = "ETHUSDT", funding=None, start: int = START, cfg=None):
    end = int(m["ts"][-1]) + MIN
    return rp.make_sym(name, m, funding, start, end, cfg or rp.CFG)


def sym15(bars, ema=100.0, atr=0.5, name: str = "ETHUSDT", start: int = START):
    """Sym только с 15m-свечами (o,h,l,c) и заданными EMA/ATR; минуты — 15 копий свечи (open минуты 0 = open свечи)."""
    a = np.asarray(bars, float)
    n = len(a)
    b15 = {"t": start + np.arange(n, dtype=np.int64) * M15, "o": a[:, 0], "h": a[:, 1], "l": a[:, 2], "c": a[:, 3],
           "ok": np.ones(n, bool)}
    ema15 = np.full(n, ema, float) if np.isscalar(ema) else np.asarray(ema, float)
    atr15 = np.full(n, atr, float) if np.isscalar(atr) else np.asarray(atr, float)
    ts = start + np.arange(n * 15, dtype=np.int64) * MIN
    rep = lambda x: np.repeat(x, 15)                                  # noqa: E731
    tick, step = rp.SPEC[name]
    return rp.Sym(name, tick, step, ts, rep(a[:, 0]), rep(a[:, 1]), rep(a[:, 2]), rep(a[:, 3]), b15, None, ema15,
                  atr15, None, np.zeros(0, np.int64), np.zeros(1), start, start + n * M15)


def sym4(H, L, C, adx=25.0, name: str = "ETHUSDT", start: int = START):
    H, L, C = (np.asarray(x, float) for x in (H, L, C))
    n = len(C)
    b4 = {"t": start + np.arange(n, dtype=np.int64) * H4, "o": C.copy(), "h": H, "l": L, "c": C,
          "ok": np.ones(n, bool)}
    adx4 = np.full(n, adx, float) if np.isscalar(adx) else np.asarray(adx, float)
    return rp.Sym(name, 0.01, 0.001, np.zeros(0, np.int64), *(np.zeros(0) for _ in range(4)), None, b4, None, None,
                  adx4, np.zeros(0, np.int64), np.zeros(1), start, start + n * H4)


def drive(p, s, j_from: int = 0):
    """Прогнать машину ожидания по свечам, вернуть (j, исход) первого не-None исхода или (None, None)."""
    for j in range(j_from, len(s.b15["c"])):
        if j < p.k1:
            continue
        r = rp.step(p, s, j)
        if r is not None:
            return j, r
    return None, None
