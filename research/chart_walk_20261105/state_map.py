"""Состояние рынка в словах оператора: расстояние до линий, направление линий, порядок, пересечения. Всё только из закрытых баров.
Расстояния и наклоны в ATR 4ч, поэтому участки разных лет и монет сравнимы. Числовые пороги фаз — мои, оператор их не задавал."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import cw_data as cw  # noqa: E402
import entry_common as ec  # noqa: E402

H5D = 120
FLAT_B4 = 0.5   # голубая 4ч плоская: изменение за 5 дней не больше 0.5 ATR 4ч
NAMES = ("до_G", "до_Y", "до_R", "до_B4", "до_B1", "до_R1", "накл_G", "накл_Y", "накл_R", "накл_B4", "порядок", "часов_GY", "часов_YR", "часов_B4", "кросс_GY")
# Участки, которые оператор разобрал: (с, по, название)
WINDOWS = (("2025-02-20", "2025-05-15", "записки 1–3"), ("2025-11-28", "2026-01-03", "записка 4"), ("2026-06-09", "2026-07-22", "записка 5"), ("2026-09-29", "2026-11-06", "записка 6"))


def since(cross):
    """Часов после последнего пересечения, по булеву ряду событий."""
    out = np.zeros(len(cross))
    cur = 10000.0
    for i, x in enumerate(cross):
        cur = 0.0 if x else cur + 1.0
        out[i] = cur
    return out


def add_state(a):
    """Почасовые столбцы состояния: st — матрица признаков, phase — фаза, flat — 0 нет, 1 сжатие, 2 локальный диапазон, 3 переход."""
    if "st" in a:
        return a
    ec.extras(a)
    c, fc, atr = a["c"], a["f_close"], a["atr4"]
    g, y, r, b, b1 = a["f_G"], a["f_Y"], a["f_R"], a["f_B"], a["f_B1"]
    n = len(c)

    def lagged(x, k):
        return np.r_[np.full(k, np.nan), x[:-k]]

    sg_gy, sg_yr, sg_b = np.sign(g - y), np.sign(y - r), np.sign(fc - b)
    a["h_gy"] = since(np.r_[False, sg_gy[1:] != sg_gy[:-1]])
    a["h_yr"] = since(np.r_[False, sg_yr[1:] != sg_yr[:-1]])
    a["h_b4"] = since(np.r_[False, sg_b[1:] != sg_b[:-1]])
    a["s_b4"] = (b - lagged(b, H5D)) / atr
    order = np.where((g > y) & (y > r), 1.0, np.where((g < y) & (y < r), -1.0, 0.0))
    a["order"] = order
    a["st"] = np.c_[(fc - g) / atr, (fc - y) / atr, (fc - r) / atr, (fc - b) / atr, (c - a["B1h"]) / atr, (c - a["R1"]) / atr,
                    (g - lagged(g, 24)) / atr, (y - lagged(y, 24)) / atr, (r - lagged(r, 24)) / atr, a["s_b4"], order,
                    np.log1p(a["h_gy"]), np.log1p(a["h_yr"]), np.log1p(a["h_b4"]), a["x_cross"]]
    over, under = (fc > b) & (fc > b1), (fc < b) & (fc < b1)
    b_up, b_dn = a["s_b4"] > FLAT_B4, a["s_b4"] < -FLAT_B4
    ph = np.full(n, "между голубыми", dtype=object)
    ph[over] = "над голубыми, рост не сформирован"
    ph[over & b_up & (order == 1)] = "рост"
    ph[under] = "под голубыми, цветные смешаны"
    ph[under & (order == -1)] = "падение"
    ph[under & (order == 1)] = "отскок под голубыми"
    a["phase"] = ph
    comp = (np.abs(g - y) <= 0.75 * atr) & (a["x_cross"] > 0)
    dg, dy = np.abs(g - lagged(g, 24)) <= 0.5 * atr, np.abs(y - lagged(y, 24)) <= 0.5 * atr
    s = pd.Series(c)
    er = ((s - s.shift(24)).abs() / s.diff().abs().rolling(24).sum()).to_numpy()
    hi, lo = pd.Series(a["h"]).rolling(24).max().shift(1).to_numpy(), pd.Series(a["l"]).rolling(24).min().shift(1).to_numpy()
    inside = (c <= hi + 0.25 * atr) & (c >= lo - 0.25 * atr)
    loc = comp & dg & dy & (er <= 0.35) & (np.abs(c - a["B1h"]) <= 1.5 * atr) & inside
    a["flat"] = np.where(loc, 2, np.where(comp, 3, 0))
    a["er24"] = er
    return a


def forward(a, H=H5D):
    """Что было потом за H часов, в ATR 4ч: итог, ход вверх, ход вниз, эффективность движения."""
    n = len(a["c"])
    c, h, l, atr = a["c"], a["h"], a["l"], a["atr4"]
    hh = pd.Series(h[::-1]).rolling(H, min_periods=H).max().to_numpy()[::-1]
    ll = pd.Series(l[::-1]).rolling(H, min_periods=H).min().to_numpy()[::-1]
    up = np.r_[hh[1:], np.nan]
    dn = np.r_[ll[1:], np.nan]
    fut = np.r_[c[H:], np.full(H, np.nan)]
    path = pd.Series(np.abs(np.diff(c, prepend=c[0]))[::-1]).rolling(H, min_periods=H).sum().to_numpy()[::-1]
    path = np.r_[path[1:], np.nan]
    return {"ret": (fut - c) / atr, "up": (up - c) / atr, "dn": (c - dn) / atr, "er": np.abs(fut - c) / path, "n": n}


def scales(a, upto):
    """Масштаб признаков по данным до upto (без данных из будущего относительно проверки)."""
    st = a["st"][a["i0"]:upto]
    sd = np.nanstd(np.clip(st, -30, 30), axis=0)
    return np.where(sd > 1e-9, sd, 1.0)


def nearest(X, cand, x, k=30, gap=72, sc=None, times=None):
    """k ближайших точек из cand к x, между ними не меньше gap часов: иначе все похожие окажутся из одного участка."""
    d = np.sqrt(np.nansum(((np.clip(X[cand], -30, 30) - np.clip(x, -30, 30)) / sc) ** 2, axis=1))
    order = np.argsort(d)
    out, kept = [], []
    tt = cand if times is None else times[cand]
    for o in order:
        if all(abs(tt[o] - z) >= gap for z in kept):
            out.append(o)
            kept.append(tt[o])
            if len(out) >= k:
                break
    return cand[np.array(out, dtype=int)], d[np.array(out, dtype=int)]


def utc(t):
    return pd.Timestamp(int(t), unit="s").strftime("%d.%m.%Y %H:%M")


def T(s):
    return cw.T(s)
