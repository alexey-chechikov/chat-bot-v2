"""Общее для позиций: часовые столбцы, издержки, фандинг, периоды, контроль случайным входом."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import cw_data as cw  # noqa: E402
import rules  # noqa: E402

COST = 0.136
OUT = cw.HERE / "out"
PER = {"A": (cw.T("2018-01-01"), cw.T("2022-01-01")), "B": (cw.T("2022-01-01"), cw.T("2024-08-01")), "C": (cw.T("2024-08-01"), cw.T("2030-01-01"))}


def load():
    m, h1, h4, d1, fund = cw.load()
    del m
    a = rules.prepare(h1, h4)
    t = a["t"]
    f = np.zeros(len(t))
    idx = np.clip(np.searchsorted(t, fund.index.to_numpy(), side="left"), 0, len(t) - 1)
    np.add.at(f, idx, fund.to_numpy())
    a["F"] = np.cumsum(f) * 100                                       # накопленный фандинг, % номинала
    a["atr4"] = h4["atr"].to_numpy()[a["j"]]
    a["R1"] = h1["R"].to_numpy()
    a["B1h"] = h1["B"].to_numpy()
    a["G1h"] = h1["G"].to_numpy()
    a["run_B1"] = h1["run_B"].to_numpy()
    a["known4"] = h4["known"].to_numpy()[a["j"]]
    i0 = int(np.searchsorted(t, cw.T("2018-01-01")))
    a["i0"] = i0
    return a, h1, h4, d1, fund


def period_of(t: np.ndarray) -> np.ndarray:
    out = np.full(len(t), "", dtype=object)
    for p, (x, z) in PER.items():
        out[(t >= x) & (t < z)] = p
    return out


def pnl(a, i0, i1, side, p0=None, p1=None):
    """Результат позиции, % номинала: ход − издержки − фандинг (лонг платит положительную ставку)."""
    p0 = a["c"][i0] if p0 is None else p0
    p1 = a["c"][i1] if p1 is None else p1
    return side * (p1 / p0 - 1) * 100 - COST - side * (a["F"][i1] - a["F"][i0])


def stats(x: np.ndarray) -> dict:
    x = np.asarray(x, dtype=float)
    if len(x) == 0:
        return {"n": 0, "среднее_%": None, "медиана_%": None, "плюс_%": None, "сумма_%": 0.0, "худшая_%": None, "ди_низ": None, "ди_верх": None}
    se = x.std(ddof=1) / np.sqrt(len(x)) if len(x) > 1 else np.nan
    return {"n": len(x), "среднее_%": round(float(x.mean()), 3), "медиана_%": round(float(np.median(x)), 3), "плюс_%": round(float((x > 0).mean() * 100), 1),
            "сумма_%": round(float(x.sum()), 1), "худшая_%": round(float(x.min()), 2), "ди_низ": round(float(x.mean() - 1.96 * se), 3), "ди_верх": round(float(x.mean() + 1.96 * se), 3)}


def max_dd(x: np.ndarray) -> float:
    """Просадка суммы сделок, % номинала."""
    c = np.cumsum(x)
    return round(float((c - np.maximum.accumulate(np.r_[0.0, c])[1:]).min()), 1) if len(c) else 0.0


def control_fixed(a, legs_i0, legs_dur, side, n_rep=999, seed=20261105):
    """Случайный вход: та же сторона, тот же период, та же сторона голубой 4ч на входе, те же длительности. → суммы по периодам и всего."""
    rng = np.random.default_rng(seed)
    t, c, F = a["t"], a["c"], a["F"]
    above = a["f_close"] > a["f_B"]
    per = period_of(t)
    legs_i0, legs_dur = np.asarray(legs_i0), np.asarray(legs_dur)
    leg_per = period_of(t[legs_i0])
    leg_above = above[legs_i0]
    tot = {p: np.zeros(n_rep) for p in PER}
    n = len(t)
    for p in PER:
        for st in (True, False):
            sel = (leg_per == p) & (leg_above == st)
            if not sel.any():
                continue
            pool = np.where((per == p) & (above == st) & (np.arange(n) >= a["i0"]))[0]
            durs = legs_dur[sel]
            draws = rng.integers(0, len(pool), size=(n_rep, len(durs)))
            s = pool[draws]
            e = np.minimum(s + durs, n - 1)
            r = side * (c[e] / c[s] - 1) * 100 - COST - side * (F[e] - F[s])
            tot[p] += r.sum(axis=1)
    return tot


def rank_row(real: dict, ctl: dict) -> dict:
    """real, ctl — суммы по периодам; → ранг и «лучше случайного в X%» по периодам и всего."""
    out = {}
    all_real = sum(real.values())
    all_ctl = sum(ctl.values())
    for k, r, c in [(p, real[p], ctl[p]) for p in PER] + [("всё", all_real, all_ctl)]:
        out[k] = {"сумма_%": round(float(r), 1), "случайные_медиана_%": round(float(np.median(c)), 1), "лучше_случайного_%": round(float((c < r).mean() * 100), 1),
                  "ранг": round(float(((c >= r).sum() + 1) / (len(c) + 1)), 3)}
    return out


def utc_full(t: int) -> str:
    return pd.Timestamp(int(t), unit="s").strftime("%d.%m.%Y %H:%M")
