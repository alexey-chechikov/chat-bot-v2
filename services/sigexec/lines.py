"""Линии системы и 432 из часовых свечей ЛЮБОГО источника (Binance spot, Bybit, OKX, WEEX) — без кода разбора.

Повторяет research/chart_walk_20261105 (mr_data.bars/add_ind, rules.prepare, words.add_runs, plus.layer) по формулам:
  зелёная G = TEMA50, жёлтая Y = TEMA100, красная R = TEMA200, синяя B = EMA200 — на закрытиях 4ч;
  ATR14 4ч (Wilder, старт средним первых 14), закрытий подряд над/под линией;
  ранг ATR100/цена за год (2190 свечей 4ч) и вес = медиана за год / текущая (0.5–2).
Значения 4ч на часе — последняя ЗАКРЫТАЯ свеча 4ч (known ≤ закрытия часа); B4p — синяя, известная к НАЧАЛУ часа.
t — время ЗАКРЫТИЯ часа (сек UTC). Совпадение с движком службы — tests/services/sigexec/test_lines_parity.py."""
from __future__ import annotations

import numpy as np
import pandas as pd

H1 = 3600
H4 = 14400
YEAR = 2190
I0_DEFAULT = 1514764800  # 01.01.2018 — как entry_rules.prep


def ema(x: np.ndarray, n: int) -> np.ndarray:
    al = 2.0 / (n + 1)
    out = np.empty(len(x), dtype=float)
    acc = float(x[0]) if len(x) else 0.0
    for i, v in enumerate(x):
        acc = float(v) if i == 0 else al * float(v) + (1 - al) * acc
        out[i] = acc
    return out


def tema(x: np.ndarray, n: int) -> np.ndarray:
    e1 = ema(x, n)
    e2 = ema(e1, n)
    return 3 * e1 - 3 * e2 + ema(e2, n)


def rma(x: np.ndarray, n: int) -> np.ndarray:
    """Как mr_data.rma: NaN до n−1, на n−1 — среднее первых n, дальше Wilder."""
    out = np.full(len(x), np.nan)
    if len(x) < n:
        return out
    acc = float(np.mean(x[:n]))
    out[n - 1] = acc
    for i in range(n, len(x)):
        acc = (acc * (n - 1) + float(x[i])) / n
        out[i] = acc
    return out


def run_len(sign: np.ndarray) -> np.ndarray:
    out = np.zeros(len(sign), dtype=int)
    cur = 0
    for i, s in enumerate(sign):
        if s == 0 or s != s:
            cur = 0
        elif (s > 0) == (cur > 0) and cur != 0:
            cur += int(s)
        else:
            cur = int(s)
        out[i] = cur
    return out


def check_hours(t: np.ndarray, o, h, l, c) -> None:
    """Часы строго возрастают, на сетке часа, цены конечные и положительные — иначе ValueError (не считать по битым данным)."""
    t = np.asarray(t, np.int64)
    if len(t) == 0:
        raise ValueError("нет часов")
    if (t % H1).any() or (np.diff(t) <= 0).any():
        raise ValueError("часы не на сетке или не строго возрастают")
    px = np.c_[o, h, l, c].astype(float)
    if not np.isfinite(px).all() or (px <= 0).any() or (np.asarray(h) < np.asarray(l)).any():
        raise ValueError("битые цены часов")


def bars4(t: np.ndarray, o, h, l, c) -> dict:
    """Свечи 4ч из часов: start, known (= start + 4ч), open/high/low/close. Последняя может быть неполной (known в будущем)."""
    t = np.asarray(t, np.int64)
    k = (t - 1) // H4
    first = np.flatnonzero(np.r_[True, k[1:] != k[:-1]])
    last = np.r_[first[1:], len(t)] - 1
    start = k[first] * H4
    return {"start": start, "known": start + H4, "o": np.asarray(o, float)[first], "h": np.maximum.reduceat(np.asarray(h, float), first),
            "l": np.minimum.reduceat(np.asarray(l, float), first), "c": np.asarray(c, float)[last], "first": first, "last": last}


def layer(t: np.ndarray, h, l, c, n: int = 100) -> tuple[np.ndarray, np.ndarray]:
    """Ранг и вес на каждом часе (plus.layer): ATR100 свечей 4ч / цена, ранг за год, вес = медиана за год / текущая."""
    b = bars4(t, h, h, l, c)
    Hb, Lb, Cb = b["h"], b["l"], b["c"]
    pc = np.r_[Cb[0], Cb[:-1]]
    tr = np.maximum(Hb - Lb, np.maximum(np.abs(Hb - pc), np.abs(Lb - pc)))
    atr = rma(tr, n)
    V = atr / Cb
    s = pd.Series(V)
    rk = s.rolling(YEAR + 1, min_periods=YEAR // 2).apply(lambda w: np.mean(w[:-1] < w[-1]) if np.isfinite(w[-1]) else np.nan, raw=True).to_numpy()
    med = s.rolling(YEAR, min_periods=500).median().shift(1).to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        w = np.clip(med / V, 0.5, 2.0)
    w = np.where(np.isfinite(w), w, 1.0)
    idx = np.clip(np.searchsorted(b["known"], np.asarray(t, np.int64), side="right") - 1, 0, None)
    return rk[idx], w[idx]


LENS = (50, 100, 200, 200)  # зелёная TEMA, жёлтая TEMA, красная TEMA, синяя EMA — длины системы оператора


def build(t: np.ndarray, o, h, l, c, i0_t: int = I0_DEFAULT, lens: tuple = LENS) -> tuple[dict, tuple[np.ndarray, np.ndarray]]:
    """→ (a, lay) в форме services/btc_signals/engine: simulate(a, lay) и simulate432(a).
    lens — длины линий (по умолчанию как у системы); другие длины — для ансамбля скоростей (research/sigexec_20261112)."""
    t = np.asarray(t, np.int64)
    o, h, l, c = (np.asarray(x, float) for x in (o, h, l, c))
    check_hours(t, o, h, l, c)
    b = bars4(t, o, h, l, c)
    C4 = b["c"]
    gl, yl, rl, bl = (int(x) for x in lens)
    G, Y, R, B = tema(C4, gl), tema(C4, yl), tema(C4, rl), ema(C4, bl)
    pc = np.r_[C4[0], C4[:-1]]
    tr = np.maximum(b["h"] - b["l"], np.maximum(np.abs(b["h"] - pc), np.abs(b["l"] - pc)))
    atr = rma(tr, 14)
    k4 = b["known"]
    j_raw = np.searchsorted(k4, t, side="right") - 1
    jp_raw = np.searchsorted(k4, t - H1, side="right") - 1
    j, jp = np.clip(j_raw, 0, None), np.clip(jp_raw, 0, None)
    # разбор aadc2a4: до первой закрытой 4ч (и до той, что известна к началу часа) clip(0) подставлял будущую свечу —
    # такие часы в расчёт не идут: i0 не раньше первого часа, где обе известны честно
    first_ok = int(np.argmax((j_raw >= 0) & (jp_raw >= 0))) if ((j_raw >= 0) & (jp_raw >= 0)).any() else len(t)
    a = {"t": t, "o": o, "h": h, "l": l, "c": c, "j": j, "B4p": B[jp], "atr4": atr[j],
         "f_close": C4[j], "f_G": G[j], "f_Y": Y[j], "f_R": R[j], "f_B": B[j],
         "i0": max(int(np.searchsorted(t, i0_t)), first_ok)}
    for name, line in (("f_run_G", G), ("f_run_Y", Y), ("f_run_R", R), ("f_run_B", B)):
        a[name] = run_len(np.sign(C4 - line))[j]
    return a, layer(t, h, l, c)


def hours_from_minutes(ts_s: np.ndarray, o, h, l, c) -> tuple[np.ndarray, ...]:
    """Часы из минут (ts — начало минуты, сек UTC) → (t закрытия часа, o, h, l, c); последний неполный час отбрасывается."""
    ts_s = np.asarray(ts_s, np.int64)
    last = int(ts_s[-1]) + 60
    keep = ts_s < last // H1 * H1
    ts_s, o, h, l, c = ts_s[keep], np.asarray(o, float)[keep], np.asarray(h, float)[keep], np.asarray(l, float)[keep], np.asarray(c, float)[keep]
    k = ts_s // H1
    first = np.flatnonzero(np.r_[True, k[1:] != k[:-1]])
    lst = np.r_[first[1:], len(k)] - 1
    return (k[first] + 1) * H1, o[first], np.maximum.reduceat(h, first), np.minimum.reduceat(l, first), c[lst]
