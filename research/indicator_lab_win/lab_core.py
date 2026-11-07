"""Быстрый движок лаборатории (W4). Независимая реализация простого правила и его вариантов: ни одной строки из words3.py и ledger.py.

Время бара t — момент закрытия часа. Значение 4ч на часе — последняя ЗАКРЫТАЯ свеча 4ч. Вход и выход по линиям — по закрытию часа, на котором закрылась 4ч.
Стопы и цели — по уровню или открытию часа (как в words3). Плавающий уровень считается только по уже закрытым часам.
Учёт: постоянное количество монеты в сделке, $1000 × вес на вход, 0.068% оборота на сторону, фандинг по цене выплаты. Итог в % от $1000.
Сделка: (i0, i1, p0, p1, s, w, tag, why). Фильтры считаются полным потоком: отклонённый сигнал меняет все следующие сделки.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

import lab_data as ld

SIDE_COST = 0.00068
H = 3600
H4 = 14400


def T(s):
    return int(pd.Timestamp(s, tz="UTC").timestamp())


def ema(x, n):
    return pd.Series(x).ewm(alpha=2.0 / (n + 1), adjust=False).mean().to_numpy()


def sma(x, n):
    return pd.Series(x).rolling(n).mean().to_numpy()


def tema(x, n):
    a = ema(x, n)
    b = ema(a, n)
    return 3 * a - 3 * b + ema(b, n)


def rma(x, n):
    """RMA как ta.rma: старт средним первых n значений, до этого NaN. NaN в начале x пропускаются."""
    x = np.asarray(x, float)
    out = np.full(len(x), np.nan)
    ok = np.flatnonzero(np.isfinite(x))
    if len(ok) < n:
        return out
    b = ok[0]
    acc = x[b:b + n].mean()
    out[b + n - 1] = acc
    for i in range(b + n, len(x)):
        acc = (acc * (n - 1) + x[i]) / n
        out[i] = acc
    return out


def run_len(diff):
    """Закрытий подряд с одной стороны от линии. Ровно на линии или NaN — сброс в 0."""
    s = np.sign(np.nan_to_num(np.asarray(diff, float), nan=0.0)).astype(np.int64)
    out = np.zeros(len(s), dtype=np.int64)
    chg = np.flatnonzero(np.r_[True, s[1:] != s[:-1]])
    lens = np.diff(np.r_[chg, len(s)])
    for b, ln in zip(chg, lens):
        if s[b] != 0:
            out[b:b + ln] = s[b] * np.arange(1, ln + 1)
    return out


@dataclass
class Series:
    name: str
    t: np.ndarray
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    v: np.ndarray
    tb: np.ndarray            # объём агрессивных покупок, если есть
    j: np.ndarray
    is4: np.ndarray
    pos4: np.ndarray
    fm: np.ndarray
    i0: int
    h4: dict
    fund_rate: pd.Series
    cache: dict = field(default_factory=dict)

    def line4(self, ln):
        """ln: ('T'|'E'|'S', длина) на барах 4ч."""
        key = ("l4", ln)
        if key not in self.cache:
            k, n = ln
            c = self.h4["c"]
            self.cache[key] = tema(c, n) if k == "T" else ema(c, n) if k == "E" else sma(c, n)
        return self.cache[key]

    def line1(self, ln):
        key = ("l1", ln)
        if key not in self.cache:
            k, n = ln
            self.cache[key] = tema(self.c, n) if k == "T" else ema(self.c, n) if k == "E" else sma(self.c, n)
        return self.cache[key]

    def run4(self, ln):
        key = ("r4", ln)
        if key not in self.cache:
            self.cache[key] = run_len(self.h4["c"] - self.line4(ln))
        return self.cache[key]

    def run1(self, ln):
        key = ("r1", ln)
        if key not in self.cache:
            self.cache[key] = run_len(self.c - self.line1(ln))
        return self.cache[key]

    def atr4(self, n=14):
        key = ("atr4", n)
        if key not in self.cache:
            h, l, c = self.h4["h"], self.h4["l"], self.h4["c"]
            pc = np.r_[c[0], c[:-1]]
            self.cache[key] = rma(np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc))), n)
        return self.cache[key]


def bars4(df):
    """Бары 4ч из часовых. df: ts — начало часа, сек UTC."""
    k = df["ts"].to_numpy() // H4 * H4
    g = df.groupby(k, sort=True)
    out = {"t0": np.array(sorted(set(k.tolist())), dtype=np.int64), "o": g["open"].first().to_numpy(float), "h": g["high"].max().to_numpy(float), "l": g["low"].min().to_numpy(float),
           "c": g["close"].last().to_numpy(float), "v": g["volume"].sum().to_numpy(float)}
    out["known"] = out["t0"] + H4
    if "taker_base" in df:
        out["tb"] = g["taker_base"].sum().to_numpy(float)
    return out


def build(name, df, fund, start):
    df = df.sort_values("ts").reset_index(drop=True)
    t = df["ts"].to_numpy(np.int64) + H
    h4 = bars4(df)
    j = np.clip(np.searchsorted(h4["known"], t, side="right") - 1, 0, None)
    is4 = j != np.r_[-1, j[:-1]]
    c = df["close"].to_numpy(float)
    fm = np.zeros(len(t))
    if len(fund):
        idx = np.searchsorted(t, fund.index.to_numpy(np.int64), side="left")
        keep = idx < len(t)
        np.add.at(fm, idx[keep], fund.to_numpy(float)[keep] * c[idx[keep]])
    fm = np.cumsum(fm)
    i0 = int(np.searchsorted(t, T(start)))
    tb = df["taker_base"].to_numpy(float) if "taker_base" in df else np.full(len(t), np.nan)
    return Series(name, t, df["open"].to_numpy(float), df["high"].to_numpy(float), df["low"].to_numpy(float), c, df["volume"].to_numpy(float), tb, j, is4, np.flatnonzero(is4), fm, i0, h4, fund)


def _fund(path):
    r = pd.read_csv(path)
    return pd.Series(r["rate"].to_numpy(float), index=(r["ms"].to_numpy(np.int64) // 1000))


def _klines(path, cut=None):
    f = pd.read_csv(path)
    f["ts"] = (f["ms"].to_numpy(np.int64) // 1000)
    return f[f["ts"] + H <= cut] if cut else f


def load(name, cut=None):
    """cut — последний момент закрытия часа, сек. По умолчанию всё, что загружено (до 07.11.2026)."""
    D = ld.DATA
    if name in ("BTC", "ETH"):
        return build(name, _klines(D / f"spot_{name}USDT_1h.csv", cut), _fund(D / f"um_{name}USDT_funding.csv"), "2018-01-01")
    if name == "XRP":
        return build(name, _klines(D / "um_XRPUSDT_1h.csv", cut), _fund(D / "um_XRPUSDT_funding.csv"), "2020-07-01")
    if name == "Bitstamp":
        f = pd.read_csv(D / "bitstamp_btcusd_1h.csv")
        f["ts"] = f["timestamp"].astype(np.int64)
        return build(name, f[f["close"] > 0], pd.Series([0.0], index=[T("2013-01-01")]), "2014-01-01")
    if name == "BybitBTC":
        return build(name, _klines(D / "bybit_BTCUSDT_1h.csv", cut), _fund(D / "um_BTCUSDT_funding.csv"), "2020-10-01")
    f = _klines(D / f"um_{name}USDT_1h.csv", cut)
    st = pd.Timestamp(int(f["ts"].iloc[0]) + 180 * 86400, unit="s").strftime("%Y-%m-%d")
    return build(name, f, _fund(D / f"um_{name}USDT_funding.csv"), st)


G, Y, R, B = ("T", 50), ("T", 100), ("T", 200), ("E", 200)
DEF = dict(
    le=G, lx=R, se=G, sx=G, reg=B,          # линии входа, выхода и режима
    k_le=2, k_lx=2, k_se=2, k_sx=2,         # закрытий 4ч
    long=True, short=True,
    Lok=None, Sok=None,                     # булевы массивы 4ч: условие на момент сигнала (полный поток)
    stop=None, tp=None,                     # ATR 4ч на входе от цены входа
    sstop=None, stp=None,                   # то же только для шорта (иначе общие)
    be=None,                                # после пика +be ATR стоп на вход
    trail=None, trail_on=0.0,               # плавающий стоп trail ATR от экстремума, включается после +trail_on ATR
    trail_side=0,                           # 0 обе стороны, 1 только лонг, -1 только шорт
    t_n=None, t_x=0.0,                      # через t_n часов, если показатель меньше t_x ATR, выход на закрытии часа
    t_side=0, t_mode="peak",                # peak — пик сделки, cur — текущий результат
    lx0=None, k_lx0=2, lx_sw=None,          # пока пик лонга меньше lx_sw ATR, выход по lx0, дальше по lx
    sx0=None, k_sx0=2, sx_sw=None,          # то же для шорта
    band_l=0.0, band_s=0.0,                 # зазор от синей в ATR: лонг только выше B+band, шорт только ниже B-band
    part=None, part_w=0.5,                  # (линия, закрытий): часть лонга закрывается раньше, остаток по lx
    spart=None,                             # то же для шорта
    cool=0,                                 # после убыточного выхода столько баров 4ч нет входа в ту же сторону
    rebreak=False,                          # после убыточного выхода тот же вход только за экстремум закрытий этой сделки
    x1=None, x1_k=3, x1_after=None,         # выход по 1ч: линия, закрытий, только после пика +x1_after ATR
    x1_with4=None,                          # выход: 4ч k закрытий за линией И 1ч за x1, как X01
    w_fn=None,                              # массив весов на барах 4ч (постоянный риск)
    entry="close",                          # close | pull1 | conf1 | early
    e_line=G, e_band=0.25, e_wait=8,        # откат/подтверждение на 1ч
    e_conf=None, e_k=3,
)


def run(S, **kw):
    P = {**DEF, **kw}
    t, o, h, l, c, j, is4 = S.t, S.o, S.h, S.l, S.c, S.j, S.is4
    n = len(t)
    Cf = S.h4["c"]
    Bv = S.line4(P["reg"])
    rle, rlx, rse, rsx = S.run4(P["le"]), S.run4(P["lx"]), S.run4(P["se"]), S.run4(P["sx"])
    k_le, k_lx, k_se, k_sx = P["k_le"], P["k_lx"], P["k_se"], P["k_sx"]
    atr = S.atr4()
    Lok, Sok = P["Lok"], P["Sok"]
    allow_l, allow_s = P["long"], P["short"]
    stop, tp, sstop, stp = P["stop"], P["tp"], P["sstop"], P["stp"]
    be, trail, trail_on, trail_side = P["be"], P["trail"], P["trail_on"], P["trail_side"]
    t_n, t_x, t_side, t_mode = P["t_n"], P["t_x"], P["t_side"], P["t_mode"]
    lx0, lx_sw, k_lx0 = P["lx0"], P["lx_sw"], P["k_lx0"]
    sx0, sx_sw, k_sx0 = P["sx0"], P["sx_sw"], P["k_sx0"]
    rlx0 = S.run4(lx0) if lx0 else None
    rsx0 = S.run4(sx0) if sx0 else None
    band_l, band_s = P["band_l"], P["band_s"]
    H4h, H4l = S.h4["h"], S.h4["l"]
    cool, rebreak = P["cool"], P["rebreak"]
    x1, x1_k, x1_after, x1_with4 = P["x1"], P["x1_k"], P["x1_after"], P["x1_with4"]
    part, part_w, spart = P["part"], P["part_w"], P["spart"]
    rpart = S.run4(part[0]) if part else None
    srpart = S.run4(spart[0]) if spart else None
    r1x = S.run1(x1) if x1 else None
    rx4 = S.run4(x1_with4) if x1_with4 else None
    w_fn = P["w_fn"]
    emode = P["entry"]
    hourly = any(v is not None for v in (stop, tp, sstop, stp, be, trail, t_n, x1)) or emode != "close"
    idx = range(S.i0, n) if hourly else S.pos4[S.pos4 >= S.i0].tolist()
    legs = []
    side, i_e, p_e, a_e, w_e, tag = 0, -1, 0.0, 0.0, 1.0, ""
    w_left, part_done = 1.0, False
    mfe_px = 0.0                                  # экстремум цены с момента входа по закрытым часам
    lock_l, lock_s = -1, -1                       # индекс 4ч, до которого запрет после убытка
    brk_l, brk_s = None, None                     # уровень нового экстремума после убытка
    best_c = 0.0
    pend, pend_i = 0, -1                          # отложенный вход на 1ч
    e_line4 = S.line4(P["e_line"]) if emode == "pull1" else None
    e_band, e_wait = P["e_band"], P["e_wait"]
    r1conf = S.run1(P["e_conf"]) if emode == "conf1" else None
    e_k = P["e_k"]
    early_ln = S.line4(P["le"])

    def close(i, px, why):
        nonlocal side, tag, w_left, part_done, lock_l, lock_s, brk_l, brk_s
        legs.append((i_e, i, p_e, float(px), side, w_e * w_left, tag, why))
        lost = side * (px / p_e - 1) <= 2 * SIDE_COST
        if lost:
            if cool:
                if side == 1:
                    lock_l = j[i] + cool
                else:
                    lock_s = j[i] + cool
            if rebreak:
                if side == 1:
                    brk_l = best_c
                else:
                    brk_s = best_c
        side, tag = 0, ""
        w_left, part_done = 1.0, False

    def opn(i, s, tg):
        nonlocal side, i_e, p_e, a_e, w_e, tag, mfe_px, best_c, pend
        side, i_e, p_e, tag = s, i, float(c[i]), tg
        a_e = float(atr[j[i]])
        w_e = float(w_fn[j[i]]) if w_fn is not None else 1.0
        mfe_px = p_e
        best_c = p_e
        pend = 0

    for i in idx:
        jj = j[i]
        new4 = is4[i]
        if side != 0:
            hi, lo = h[i], l[i]
            if hourly:
                s_st = (sstop if sstop is not None else stop) if side == -1 else stop
                s_tp = (stp if stp is not None else tp) if side == -1 else tp
                lvl_stop = None
                if s_st is not None:
                    lvl_stop = p_e - side * s_st * a_e
                if be is not None and side * (mfe_px - p_e) >= be * a_e:
                    lvl_stop = p_e if lvl_stop is None else (max(lvl_stop, p_e) if side == 1 else min(lvl_stop, p_e))
                if trail is not None and (trail_side == 0 or trail_side == side) and side * (mfe_px - p_e) >= trail_on * a_e:
                    lv = mfe_px - side * trail * a_e
                    lvl_stop = lv if lvl_stop is None else (max(lvl_stop, lv) if side == 1 else min(lvl_stop, lv))
                if lvl_stop is not None and ((side == 1 and lo <= lvl_stop) or (side == -1 and hi >= lvl_stop)):
                    close(i, min(lvl_stop, o[i]) if side == 1 else max(lvl_stop, o[i]), "стоп")
                    continue
                if s_tp is not None:
                    lv = p_e + side * s_tp * a_e
                    if (side == 1 and hi >= lv) or (side == -1 and lo <= lv):
                        close(i, max(lv, o[i]) if side == 1 else min(lv, o[i]), "тейк")
                        continue
                if side == 1:
                    mfe_px = max(mfe_px, hi)
                else:
                    mfe_px = min(mfe_px, lo)
                if t_n is not None and (t_side == 0 or t_side == side) and i - i_e == t_n and side * ((mfe_px if t_mode == "peak" else c[i]) - p_e) < t_x * a_e:
                    close(i, c[i], "время")
                    continue
                if x1 is not None and side * r1x[i] <= -x1_k and (x1_after is None or side * (mfe_px - p_e) >= x1_after * a_e):
                    if x1_with4 is None or side * rx4[jj] <= -k_lx:
                        close(i, c[i], "1ч")
                        continue
            if new4:
                best_c = max(best_c, Cf[jj]) if side == 1 else min(best_c, Cf[jj])
                if not hourly:
                    mfe_px = max(mfe_px, H4h[jj]) if side == 1 else min(mfe_px, H4l[jj])
                if side == 1:
                    if part and not part_done and rpart[jj] <= -part[1]:
                        legs.append((i_e, i, p_e, float(c[i]), 1, w_e * part_w, tag, "часть"))
                        w_left, part_done = 1.0 - part_w, True
                    if rlx[jj] <= -k_lx or (lx0 and mfe_px - p_e < lx_sw * a_e and rlx0[jj] <= -k_lx0):
                        close(i, c[i], "линия")
                else:
                    if spart and not part_done and srpart[jj] >= spart[1]:
                        legs.append((i_e, i, p_e, float(c[i]), -1, w_e * part_w, tag, "часть"))
                        w_left, part_done = 1.0 - part_w, True
                    if rsx[jj] >= k_sx or (sx0 and p_e - mfe_px < sx_sw * a_e and rsx0[jj] >= k_sx0):
                        close(i, c[i], "линия")
        if side == 0 and pend != 0:
            if i - pend_i > e_wait or (pend == 1 and rlx[jj] <= -k_lx) or (pend == -1 and rsx[jj] >= k_sx):
                pend = 0
            elif emode == "pull1":
                lv = e_line4[jj] + pend * e_band * atr[jj]
                if (pend == 1 and l[i] <= lv) or (pend == -1 and h[i] >= lv):
                    opn(i, pend, "откат")
                    continue
            elif emode == "conf1":
                if pend * r1conf[i] >= e_k:
                    opn(i, pend, "1ч")
                    continue
        if emode == "early" and side == 0 and not new4 and hourly:
            f = Cf[jj]
            if allow_l and f > Bv[jj] and rle[jj] >= k_le - 1 and c[i] > early_ln[jj] and rlx[jj] > -k_lx and (Lok is None or Lok[jj]) and jj >= lock_l and (brk_l is None or f > brk_l):
                opn(i, 1, "до закрытия")
                continue
            if allow_s and f <= Bv[jj] and rse[jj] <= -(k_se - 1) and rsx[jj] < k_sx and c[i] < early_ln[jj] and (Sok is None or Sok[jj]) and jj >= lock_s and (brk_s is None or f < brk_s):
                opn(i, -1, "до закрытия")
                continue
        if side != 0 or not new4:
            continue
        f = Cf[jj]
        go = 0
        if f > Bv[jj]:
            if allow_l and f > Bv[jj] + band_l * atr[jj] and rle[jj] >= k_le and rlx[jj] > -k_lx and (Lok is None or Lok[jj]) and jj >= lock_l:
                if brk_l is None or f > brk_l:
                    go = 1
                    brk_l = None
        else:
            if allow_s and f < Bv[jj] - band_s * atr[jj] and rse[jj] <= -k_se and rsx[jj] < k_sx and (Sok is None or Sok[jj]) and jj >= lock_s:
                if brk_s is None or f < brk_s:
                    go = -1
                    brk_s = None
        if go:
            if emode in ("pull1", "conf1"):
                pend, pend_i = go, i
            else:
                opn(i, go, "сигнал")
    if side != 0:
        close(n - 1, c[n - 1], "конец")
    return legs


def nets(S, legs):
    """Итог каждой сделки в % от $1000 с учётом веса."""
    if not legs:
        return np.zeros(0)
    a = np.array([x[:6] for x in legs], dtype=float)
    i0, i1 = a[:, 0].astype(np.int64), a[:, 1].astype(np.int64)
    p0, p1, s, w = a[:, 2], a[:, 3], a[:, 4], a[:, 5]
    return w * (s * (p1 / p0 - 1) - SIDE_COST - SIDE_COST * p1 / p0 - s * (S.fm[i1] - S.fm[i0]) / p0) * 100


def equity(S, legs, close_cost=True):
    """Кривая по часам, % от $1000: закрытые плюс открытые по закрытию часа с вычетом издержки выхода."""
    n = len(S.t)
    closed, op = np.zeros(n), np.zeros(n)
    r = nets(S, legs)
    for x, v in zip(legs, r):
        i0, i1, p0, p1, s, w = x[:6]
        closed[i1] += v
        if i1 > i0:
            k = np.arange(i0, i1)
            ck = S.c[k]
            op[k] += w * (s * (ck / p0 - 1) - SIDE_COST - (SIDE_COST * ck / p0 if close_cost else 0.0) - s * (S.fm[k] - S.fm[i0]) / p0) * 100
    return np.cumsum(closed) + op


def max_dd(eq):
    return float((eq - np.maximum.accumulate(np.r_[0.0, eq])[1:]).min())


PERIODS = (("2018-21", T("2018-01-01"), T("2022-01-01")), ("2022-07.24", T("2022-01-01"), T("2024-08-01")), ("08.24-26", T("2024-08-01"), T("2031-01-01")))
CUT25 = T("2025-01-01")


def stats(S, legs):
    if not legs:
        return {"n": 0, "итог": 0.0, "лонг": 0.0, "шорт": 0.0, "с2025": 0.0, "просадка": 0.0, "p1": 0.0, "p2": 0.0, "p3": 0.0, "плюс%": 0.0, "ди_низ": 0.0, "отн": 0.0}
    r = nets(S, legs)
    s = np.array([x[4] for x in legs])
    tt = S.t[np.array([x[0] for x in legs])]
    eq = equity(S, legs)[S.i0:]
    dd = max_dd(eq)
    w = np.array([x[5] for x in legs])
    se = r.std(ddof=1) / np.sqrt(len(r)) if len(r) > 1 else 0.0
    out = {"n": len(r), "итог": round(float(r.sum()), 1), "лонг": round(float(r[s == 1].sum()), 1), "шорт": round(float(r[s == -1].sum()), 1), "с2025": round(float(r[tt >= CUT25].sum()), 1), "просадка": round(dd, 1)}
    for lab, (_, x, z) in zip(("p1", "p2", "p3"), PERIODS):
        out[lab] = round(float(r[(tt >= x) & (tt < z)].sum()), 1)
    out["плюс%"] = round(float((r > 0).mean() * 100), 1)
    out["ди_низ"] = round(float(r.mean() - 1.96 * se), 3)
    out["отн"] = round(float(r.sum()) / max(abs(dd), 1.0), 2)
    out["вес"] = round(float(w.mean()), 3)
    return out


def daily_returns(S, legs):
    """Дневные изменения кривой, % от $1000 (последний час UTC-дня)."""
    eq = equity(S, legs)
    d = pd.Series(eq, index=pd.to_datetime(S.t, unit="s"))
    d = d[d.index >= pd.Timestamp(int(S.t[S.i0]), unit="s")]
    return d.resample("1D").last().ffill().diff().dropna()
