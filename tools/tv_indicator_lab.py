"""Лаборатория индикаторов TradingView: ~50 популярных сигналов как входы с риском
1R и тейком 2R/3R/5R, стоп по ATR (1/1.5/2) или за свинг.

Оператор 05.10: «изучить индикаторы TradingView глубже, не топ-5; формация и входы
с ходом 3 к 1, 5 к 1».

Правила честности:
- сигнал по ЗАКРЫТОЙ свече своего ТФ, вход по открытию следующей часовой;
- выход по часовым свечам; если в одной свече и стоп, и тейк — считаем стоп;
- комиссия 0.10% за круг (факт OKX), в R = 0.001 × цена / стоп;
- одна сделка за раз на сигнал (новая — только после выхода из старой);
- контроль: вход на КАЖДОЙ свече той же стороной с тем же стопом и тейком —
  «что даёт рынок без сигнала» (в бычьем году лонги в плюсе и без индикатора);
- три периода по календарю: old 2017-08…2020-09, mid 2020-10…2023-09,
  fresh 2023-10…сейчас. Подбор нигде не делается: параметры — дефолты TradingView.

    .venv/bin/python3 tools/tv_indicator_lab.py              # BTC ETH XRP SOL, 1h и 4h
    .venv/bin/python3 tools/tv_indicator_lab.py BTCUSDT 4h   # одна монета/ТФ
Результат: state/research/tv_lab_cells.csv
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view as swv

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "historical"
OUT = ROOT / "state" / "research"
FEE = 0.0010
PERIODS = (("old", "2017-08-01", "2020-10-01"),
           ("mid", "2020-10-01", "2023-10-01"),
           ("fresh", "2023-10-01", "2100-01-01"))
RRS = (2.0, 3.0, 5.0)
STOPS = (("atr1", 1.0), ("atr1.5", 1.5), ("atr2", 2.0), ("swing", None))
HOLD = {"1h": 168, "4h": 720}          # часов: неделя для 1h, месяц для 4h
COINS = ("BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT")


# ---------------------------------------------------------------- данные
def load_1h(sym: str) -> pd.DataFrame:
    d = pd.read_csv(DATA / f"1h_{sym}.csv")
    d.index = pd.to_datetime(d.pop("ts_ms"), unit="ms", utc=True)
    d = d.astype(float).rename(columns={"open": "o", "high": "h", "low": "l",
                                        "close": "c", "volume": "v"})
    return d[~d.index.duplicated()].sort_index()


def resample(d: pd.DataFrame, tf: str) -> pd.DataFrame:
    if tf == "1h":
        return d
    r = d.resample("4h")
    out = pd.DataFrame({"o": r.o.first(), "h": r.h.max(), "l": r.l.min(),
                        "c": r.c.last(), "v": r.v.sum(), "n": r.c.count()})
    return out[out.n == 4].drop(columns="n")


# ---------------------------------------------------------------- примитивы
def ema(x, n):
    return x.ewm(span=n, adjust=False).mean()


def rma(x, n):
    return x.ewm(alpha=1.0 / n, adjust=False).mean()


def sma(x, n):
    return x.rolling(n).mean()


def wma(x: pd.Series, n: int) -> pd.Series:
    k = np.arange(n, 0, -1, dtype=float)
    out = np.convolve(x.to_numpy(float), k)[: len(x)] / k.sum()
    out[: n - 1] = np.nan
    return pd.Series(out, x.index)


def linreg_end(y: pd.Series, n: int) -> pd.Series:
    k = (n - 1) / 2 - np.arange(n)
    b = np.convolve(y.to_numpy(float), k)[: len(y)] / (n * (n * n - 1) / 12)
    out = y.rolling(n).mean().to_numpy() + b * (n - 1) / 2
    out[: n - 1] = np.nan
    return pd.Series(out, y.index)


def true_range(df):
    pc = df.c.shift()
    return pd.concat([df.h - df.l, (df.h - pc).abs(), (df.l - pc).abs()], axis=1).max(axis=1)


def atr(df, n=14):
    return rma(true_range(df), n)


def rsi(c, n=14):
    d = c.diff()
    up, dn = rma(d.clip(lower=0), n), rma(-d.clip(upper=0), n)
    return 100 - 100 / (1 + up / dn)


def xup(a, b):
    b1 = b.shift() if isinstance(b, pd.Series) else b
    return (a > b) & (a.shift() <= b1)


def xdn(a, b):
    b1 = b.shift() if isinstance(b, pd.Series) else b
    return (a < b) & (a.shift() >= b1)


def flips(direction: np.ndarray, index) -> tuple[pd.Series, pd.Series]:
    s = pd.Series(direction, index)
    p = s.shift()
    return (s == 1) & (p == -1), (s == -1) & (p == 1)


def pivots(x: np.ndarray, k: int, high: bool) -> np.ndarray:
    s = pd.Series(x)
    w = s.rolling(2 * k + 1, center=True)
    ext = w.max() if high else w.min()
    return (s == ext).to_numpy() & ~np.isnan(ext.to_numpy())


# ---------------------------------------------------------------- индикаторы с циклом
def supertrend(df, n=10, m=3.0):
    h, l, c = df.h.to_numpy(), df.l.to_numpy(), df.c.to_numpy()
    a = atr(df, n).to_numpy()
    src = (h + l) / 2
    up, dn = src - m * a, src + m * a
    tr = np.ones(len(c))
    for i in range(1, len(c)):
        if c[i - 1] > up[i - 1]:
            up[i] = max(up[i], up[i - 1])
        if c[i - 1] < dn[i - 1]:
            dn[i] = min(dn[i], dn[i - 1])
        if tr[i - 1] == -1 and c[i] > dn[i - 1]:
            tr[i] = 1
        elif tr[i - 1] == 1 and c[i] < up[i - 1]:
            tr[i] = -1
        else:
            tr[i] = tr[i - 1]
    return tr


def ut_bot(df, key=1.0, n=10):
    c = df.c.to_numpy()
    nl = key * atr(df, n).to_numpy()
    t = np.zeros(len(c))
    for i in range(1, len(c)):
        p = t[i - 1]
        if c[i] > p and c[i - 1] > p:
            t[i] = max(p, c[i] - nl[i])
        elif c[i] < p and c[i - 1] < p:
            t[i] = min(p, c[i] + nl[i])
        elif c[i] > p:
            t[i] = c[i] - nl[i]
        else:
            t[i] = c[i] + nl[i]
    trail = pd.Series(t, df.index)
    return xup(df.c, trail), xdn(df.c, trail)


def psar(df, start=0.02, inc=0.02, mx=0.2):
    h, l = df.h.to_numpy(), df.l.to_numpy()
    out = np.zeros(len(h))
    bull, af, ep, sar = True, start, h[0], l[0]
    for i in range(1, len(h)):
        sar = sar + af * (ep - sar)
        if bull:
            sar = min(sar, l[i - 1], l[i - 2] if i > 1 else l[i - 1])
            if l[i] < sar:
                bull, sar, ep, af = False, ep, l[i], start
            elif h[i] > ep:
                ep, af = h[i], min(af + inc, mx)
        else:
            sar = max(sar, h[i - 1], h[i - 2] if i > 1 else h[i - 1])
            if h[i] > sar:
                bull, sar, ep, af = True, ep, h[i], start
            elif l[i] < ep:
                ep, af = l[i], min(af + inc, mx)
        out[i] = 1 if bull else -1
    return out


def chandelier(df, n=22, m=3.0):
    c = df.c.to_numpy()
    a = m * atr(df, n).to_numpy()
    ls = (df.c.rolling(n).max().to_numpy() - a).copy()
    ss = (df.c.rolling(n).min().to_numpy() + a).copy()
    d = np.ones(len(c))
    for i in range(1, len(c)):
        lp, sp = ls[i - 1], ss[i - 1]
        if c[i - 1] > lp:
            ls[i] = max(ls[i], lp)
        if c[i - 1] < sp:
            ss[i] = min(ss[i], sp)
        d[i] = 1 if c[i] > sp else (-1 if c[i] < lp else d[i - 1])
    return d


def ssl(df, n=10):
    c = df.c.to_numpy()
    hi, lo = sma(df.h, n).to_numpy(), sma(df.l, n).to_numpy()
    d = np.zeros(len(c))
    for i in range(1, len(c)):
        d[i] = 1 if c[i] > hi[i] else (-1 if c[i] < lo[i] else d[i - 1])
    return d


def halftrend(df, amp=2, dev=2.0):
    h, l, c = df.h.to_numpy(), df.l.to_numpy(), df.c.to_numpy()
    hp = df.h.rolling(amp).max().to_numpy()
    lp = df.l.rolling(amp).min().to_numpy()
    hma, lma = sma(df.h, amp).to_numpy(), sma(df.l, amp).to_numpy()
    trend, nxt = 0, 0
    maxlow, minhigh = l[0], h[0]
    out = np.zeros(len(c))
    for i in range(1, len(c)):
        if nxt == 1:
            maxlow = max(lp[i], maxlow)
            if hma[i] < maxlow and c[i] < l[i - 1]:
                trend, nxt, minhigh = 1, 0, hp[i]
        else:
            minhigh = min(hp[i], minhigh)
            if lma[i] > minhigh and c[i] > h[i - 1]:
                trend, nxt, maxlow = 0, 1, lp[i]
        out[i] = 1 if trend == 0 else -1
    return out


def qqe(df, rn=6, sf=5, q=3.0):
    r = ema(rsi(df.c, rn), sf)
    ar = (r - r.shift()).abs()
    dar = ema(ema(ar, 2 * rn - 1), 2 * rn - 1) * q
    R, D = r.to_numpy(), dar.to_numpy()
    n = len(R)
    lb, sb, tr = np.zeros(n), np.zeros(n), np.ones(n)
    for i in range(1, n):
        nl, ns = R[i] - D[i], R[i] + D[i]
        lb[i] = max(lb[i - 1], nl) if (R[i - 1] > lb[i - 1] and R[i] > lb[i - 1]) else nl
        sb[i] = min(sb[i - 1], ns) if (R[i - 1] < sb[i - 1] and R[i] < sb[i - 1]) else ns
        if i > 1 and (R[i] > sb[i - 1]) != (R[i - 1] > sb[i - 2]):
            tr[i] = 1
        elif i > 1 and (lb[i - 1] > R[i]) != (lb[i - 2] > R[i - 1]):
            tr[i] = -1
        else:
            tr[i] = tr[i - 1]
    return tr


def heikin_green(df):
    o, h, l, c = (df[k].to_numpy() for k in "ohlc")
    hc = (o + h + l + c) / 4
    ho = np.empty_like(hc)
    ho[0] = (o[0] + c[0]) / 2
    for i in range(1, len(hc)):
        ho[i] = (ho[i - 1] + hc[i - 1]) / 2
    return hc > ho


def smc(df, k=5):
    h, l, c = df.h.to_numpy(), df.l.to_numpy(), df.c.to_numpy()
    ph, pl = pivots(h, k, True), pivots(l, k, False)
    n = len(c)
    bos_l, bos_s, ch_l, ch_s = (np.zeros(n, bool) for _ in range(4))
    sh = slo = np.nan
    sh_on = sl_on = False
    trend = 0
    for i in range(n):
        if i >= k and ph[i - k]:
            sh, sh_on = h[i - k], True
        if i >= k and pl[i - k]:
            slo, sl_on = l[i - k], True
        if sh_on and c[i] > sh:
            (ch_l if trend == -1 else bos_l)[i] = True
            trend, sh_on = 1, False
        elif sl_on and c[i] < slo:
            (ch_s if trend == 1 else bos_s)[i] = True
            trend, sl_on = -1, False
    return bos_l, bos_s, ch_l, ch_s


def fvg(df, a, max_age=50, min_gap=0.2):
    h, l, c = df.h.to_numpy(), df.l.to_numpy(), df.c.to_numpy()
    n = len(c)
    lo_sig, sh_sig = np.zeros(n, bool), np.zeros(n, bool)
    bull, bear = [], []
    for i in range(2, n):
        keep = []
        for top, bot, born in bull:
            if i - born > max_age:
                continue
            if l[i] <= top:
                lo_sig[i] |= c[i] > bot
                continue
            keep.append((top, bot, born))
        bull = keep
        keep = []
        for top, bot, born in bear:
            if i - born > max_age:
                continue
            if h[i] >= bot:
                sh_sig[i] |= c[i] < top
                continue
            keep.append((top, bot, born))
        bear = keep
        g = min_gap * a[i] if not np.isnan(a[i]) else np.inf
        if l[i] - h[i - 2] >= g:
            bull.append((l[i], h[i - 2], i))
        if l[i - 2] - h[i] >= g:
            bear.append((l[i - 2], h[i], i))
    return lo_sig, sh_sig


def divergence(df, osc: np.ndarray, k=5, lo=5, hi=60):
    h, l = df.h.to_numpy(), df.l.to_numpy()
    n = len(h)
    bull, bear = np.zeros(n, bool), np.zeros(n, bool)
    for arr, is_low in ((pivots(osc, k, False), True), (pivots(osc, k, True), False)):
        prev = None
        for p in np.flatnonzero(arr):
            if p + k >= n:
                break
            if prev is not None and lo <= p - prev <= hi:
                if is_low and osc[p] > osc[prev] and l[p] < l[prev]:
                    bull[p + k] = True
                if not is_low and osc[p] < osc[prev] and h[p] > h[prev]:
                    bear[p + k] = True
            prev = p
    return bull, bear


# ---------------------------------------------------------------- сигналы
NAMES = {
    "rsi_30_70": "RSI 14: выход из перепроданности 30 / перекупленности 70",
    "rsi_50": "RSI 14: пересечение 50",
    "rsi_div": "RSI: классическая дивергенция (пивоты 5/5)",
    "rsi_pullback_ema200": "откат RSI 40/60 по тренду EMA200",
    "macd_cross": "MACD 12/26/9: пересечение сигнальной",
    "macd_cross_zone": "MACD: пересечение ниже/выше нуля",
    "macd_zero": "MACD: пересечение нуля",
    "macd_ema200": "MACD-крест по тренду EMA200 (популярная ютуб-стратегия)",
    "ema_9_21": "EMA 9/21 крест",
    "ema_20_50": "EMA 20/50 крест",
    "golden_cross": "SMA 50/200 золотой/мёртвый крест",
    "ema_stochrsi": "EMA 8>14>50 + Stoch RSI крест",
    "bb_revert": "Боллинджер 20/2: возврат внутрь канала",
    "bb_breakout": "Боллинджер 20/2: пробой канала",
    "bb_rsi": "Боллинджер + RSI<30/>70: возврат",
    "sqz_fire": "Squeeze Momentum [LazyBear]: выстрел сжатия",
    "sqz_turn": "Squeeze Momentum [LazyBear]: разворот гистограммы",
    "keltner_break": "Кельтнер 20/2: пробой",
    "donchian20": "Дончиан 20 пробой (черепахи)",
    "donchian55": "Дончиан 55 пробой (черепахи)",
    "stoch_cross": "Stoch 14/3: крест в зоне 20/80",
    "stochrsi_cross": "Stoch RSI: крест в зоне 20/80",
    "cci_100": "CCI 20: выход из ±100",
    "willr": "Williams %R: выход из −80/−20",
    "mfi_20_80": "MFI 14 (RSI с объёмом): выход из 20/80",
    "wavetrend": "WaveTrend [LazyBear] / точки Cipher B: крест в зоне ±53",
    "qqe": "QQE MOD: переворот",
    "supertrend": "SuperTrend 10/3: переворот",
    "st_ema200": "SuperTrend по тренду EMA200",
    "ut_bot": "UT Bot Alerts: buy/sell",
    "psar": "Parabolic SAR: переворот",
    "chandelier": "Chandelier Exit 22/3: переворот",
    "ssl": "SSL Channel 10: переворот",
    "hull": "Hull Suite 55: смена цвета",
    "halftrend": "HalfTrend: переворот",
    "adx_di": "ADX/DMI: крест +DI/−DI при ADX>20",
    "aroon": "Aroon 14: крест",
    "ao_zero": "Awesome Oscillator: ноль",
    "ichi_tk": "Ишимоку: крест Тенкан/Киджун за облаком",
    "ichi_cloud": "Ишимоку: пробой облака",
    "heikin_flip": "Хейкин-Аши: смена цвета после 3 свечей",
    "vwap_cross": "VWAP (день для 1h / неделя для 4h): пересечение",
    "pivot_s1r1": "Классические пивоты дня: отскок от S1/R1",
    "vixfix": "Williams Vix Fix [CM]: конец всплеска страха",
    "nw_env": "Nadaraya-Watson Envelope [LuxAlgo] без перерисовки: возврат",
    "smc_bos": "SMC [LuxAlgo-стиль]: слом структуры BOS",
    "smc_choch": "SMC: смена характера CHoCH",
    "fvg_retest": "SMC: ретест FVG (имбаланса)",
    "engulfing": "Поглощение после снижения/роста",
    "pin_bar": "Пин-бар у 10-свечного экстремума",
    "inside_break": "Пробой внутреннего бара",
    "vol_spike": "Всплеск объёма ×2.5 по ходу свечи",
    "vol_spike_fade": "Всплеск объёма ×2.5 — против свечи (капитуляция)",
}


def signals(df: pd.DataFrame, tf: str) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    o, h, l, c, v = df.o, df.h, df.l, df.c, df.v
    idx = df.index
    a14 = atr(df, 14)
    r14 = rsi(c, 14)
    e200 = ema(c, 200)
    S: dict[str, tuple] = {}

    S["rsi_30_70"] = (xup(r14, 30), xdn(r14, 70))
    S["rsi_50"] = (xup(r14, 50), xdn(r14, 50))
    S["rsi_div"] = divergence(df, r14.to_numpy())
    S["rsi_pullback_ema200"] = ((c > e200) & xup(r14, 40), (c < e200) & xdn(r14, 60))

    macd = ema(c, 12) - ema(c, 26)
    sig = ema(macd, 9)
    S["macd_cross"] = (xup(macd, sig), xdn(macd, sig))
    S["macd_cross_zone"] = (xup(macd, sig) & (macd < 0), xdn(macd, sig) & (macd > 0))
    S["macd_zero"] = (xup(macd, 0), xdn(macd, 0))
    S["macd_ema200"] = (xup(macd, sig) & (macd < 0) & (c > e200),
                        xdn(macd, sig) & (macd > 0) & (c < e200))

    e9, e21, e20, e50 = ema(c, 9), ema(c, 21), ema(c, 20), ema(c, 50)
    S["ema_9_21"] = (xup(e9, e21), xdn(e9, e21))
    S["ema_20_50"] = (xup(e20, e50), xdn(e20, e50))
    S["golden_cross"] = (xup(sma(c, 50), sma(c, 200)), xdn(sma(c, 50), sma(c, 200)))

    st_raw = 100 * (r14 - r14.rolling(14).min()) / (r14.rolling(14).max() - r14.rolling(14).min())
    srk = sma(st_raw, 3)
    srd = sma(srk, 3)
    e8, e14 = ema(c, 8), ema(c, 14)
    S["ema_stochrsi"] = ((e8 > e14) & (e14 > e50) & xup(srk, srd) & (srk < 30),
                         (e8 < e14) & (e14 < e50) & xdn(srk, srd) & (srk > 70))
    S["stochrsi_cross"] = (xup(srk, srd) & (srk < 20), xdn(srk, srd) & (srk > 80))

    bb_mid = sma(c, 20)
    bb_dev = 2 * c.rolling(20).std(ddof=0)
    bbu, bbl = bb_mid + bb_dev, bb_mid - bb_dev
    S["bb_revert"] = (xup(c, bbl), xdn(c, bbu))
    S["bb_breakout"] = (xup(c, bbu), xdn(c, bbl))
    was_os = (r14.shift() < 30) & (c.shift() < bbl.shift())
    was_ob = (r14.shift() > 70) & (c.shift() > bbu.shift())
    S["bb_rsi"] = (was_os & (c > bbl), was_ob & (c < bbu))

    rng_ma = sma(true_range(df), 20)
    kcu, kcl = bb_mid + 1.5 * rng_ma, bb_mid - 1.5 * rng_ma
    sqz_on = (bbl > kcl) & (bbu < kcu)
    mid = ((h.rolling(20).max() + l.rolling(20).min()) / 2 + bb_mid) / 2
    val = linreg_end(c - mid, 20)
    fire = sqz_on.shift(fill_value=False) & ~sqz_on
    S["sqz_fire"] = (fire & (val > 0), fire & (val < 0))
    S["sqz_turn"] = ((val < 0) & (val > val.shift()) & (val.shift() <= val.shift(2)),
                     (val > 0) & (val < val.shift()) & (val.shift() >= val.shift(2)))

    a10 = atr(df, 10)
    S["keltner_break"] = (xup(c, ema(c, 20) + 2 * a10), xdn(c, ema(c, 20) - 2 * a10))
    for n in (20, 55):
        hh, ll = h.rolling(n).max().shift(), l.rolling(n).min().shift()
        S[f"donchian{n}"] = (xup(c, hh), xdn(c, ll))

    hh14, ll14 = h.rolling(14).max(), l.rolling(14).min()
    k = 100 * (c - ll14) / (hh14 - ll14)
    d = sma(k, 3)
    S["stoch_cross"] = (xup(k, d) & (k < 20), xdn(k, d) & (k > 80))
    wr = -100 * (hh14 - c) / (hh14 - ll14)
    S["willr"] = (xup(wr, -80), xdn(wr, -20))

    tp = (h + l + c) / 3
    win = swv(np.r_[np.full(19, np.nan), tp.to_numpy()], 20)
    md = np.nanmean(np.abs(win - win.mean(axis=1, keepdims=True)), axis=1)
    cci = (tp - sma(tp, 20)) / (0.015 * pd.Series(md, idx))
    S["cci_100"] = (xup(cci, -100), xdn(cci, 100))
    raw = tp * v
    dtp = tp.diff()
    pos = raw.where(dtp > 0, 0.0).rolling(14).sum()
    neg = raw.where(dtp < 0, 0.0).rolling(14).sum()
    mfi = 100 - 100 / (1 + pos / neg)
    S["mfi_20_80"] = (xup(mfi, 20), xdn(mfi, 80))

    esa = ema(tp, 10)
    dd = ema((tp - esa).abs(), 10)
    wt1 = ema((tp - esa) / (0.015 * dd), 21)
    wt2 = sma(wt1, 4)
    S["wavetrend"] = (xup(wt1, wt2) & (wt1 < -53), xdn(wt1, wt2) & (wt1 > 53))

    S["qqe"] = flips(qqe(df), idx)
    st = supertrend(df)
    S["supertrend"] = flips(st, idx)
    S["st_ema200"] = (S["supertrend"][0] & (c > e200), S["supertrend"][1] & (c < e200))
    S["ut_bot"] = ut_bot(df)
    S["psar"] = flips(psar(df), idx)
    S["chandelier"] = flips(chandelier(df), idx)
    S["ssl"] = flips(ssl(df), idx)
    hull = wma(2 * wma(c, 27) - wma(c, 55), 7)
    S["hull"] = flips(np.where(hull > hull.shift(2), 1, -1), idx)
    S["halftrend"] = flips(halftrend(df), idx)

    up_m, dn_m = h.diff(), -l.diff()
    pdm = up_m.where((up_m > dn_m) & (up_m > 0), 0.0)
    mdm = dn_m.where((dn_m > up_m) & (dn_m > 0), 0.0)
    trr = rma(true_range(df), 14)
    pdi, mdi = 100 * rma(pdm, 14) / trr, 100 * rma(mdm, 14) / trr
    adx = 100 * rma((pdi - mdi).abs() / (pdi + mdi), 14)
    S["adx_di"] = (xup(pdi, mdi) & (adx > 20), xdn(pdi, mdi) & (adx > 20))

    hw = swv(np.r_[np.full(14, np.nan), h.to_numpy()], 15)
    lw = swv(np.r_[np.full(14, np.nan), l.to_numpy()], 15)
    since_h = np.argmax(np.nan_to_num(hw, nan=-np.inf)[:, ::-1], axis=1)
    since_l = np.argmin(np.nan_to_num(lw, nan=np.inf)[:, ::-1], axis=1)
    aup = pd.Series(100 * (14 - since_h) / 14, idx)
    adn = pd.Series(100 * (14 - since_l) / 14, idx)
    S["aroon"] = (xup(aup, adn), xdn(aup, adn))
    hl2 = (h + l) / 2
    ao = sma(hl2, 5) - sma(hl2, 34)
    S["ao_zero"] = (xup(ao, 0), xdn(ao, 0))

    tk = (h.rolling(9).max() + l.rolling(9).min()) / 2
    kj = (h.rolling(26).max() + l.rolling(26).min()) / 2
    sa = ((tk + kj) / 2).shift(25)
    sb = ((h.rolling(52).max() + l.rolling(52).min()) / 2).shift(25)
    top, bot = np.maximum(sa, sb), np.minimum(sa, sb)
    S["ichi_tk"] = (xup(tk, kj) & (c > top), xdn(tk, kj) & (c < bot))
    S["ichi_cloud"] = (xup(c, top), xdn(c, bot))

    g = pd.Series(heikin_green(df), idx)
    red3 = (~g.shift(1, fill_value=True)) & (~g.shift(2, fill_value=True)) & (~g.shift(3, fill_value=True))
    grn3 = g.shift(1, fill_value=False) & g.shift(2, fill_value=False) & g.shift(3, fill_value=False)
    S["heikin_flip"] = (g & red3, ~g & grn3)

    anchor = idx.floor("1D") if tf == "1h" else (idx - pd.to_timedelta(idx.dayofweek, unit="D")).floor("1D")
    grp = pd.Series(anchor, idx)
    vw = (tp * v).groupby(grp).cumsum() / v.groupby(grp).cumsum()
    same = grp == grp.shift()
    S["vwap_cross"] = (xup(c, vw) & same, xdn(c, vw) & same)

    day = pd.Series(idx.floor("1D"), idx)
    dly = pd.DataFrame({"h": h.groupby(day).max(), "l": l.groupby(day).min(),
                        "c": c.groupby(day).last()}).shift(1)
    P = (dly.h + dly.l + dly.c) / 3
    s1 = (2 * P - dly.h).reindex(day.values).to_numpy()
    r1 = (2 * P - dly.l).reindex(day.values).to_numpy()
    lo_c = pd.Series((l.to_numpy() <= s1) & (c.to_numpy() > s1), idx)
    sh_c = pd.Series((h.to_numpy() >= r1) & (c.to_numpy() < r1), idx)
    S["pivot_s1r1"] = (lo_c & (lo_c.groupby(day).cumsum() == 1),
                       sh_c & (sh_c.groupby(day).cumsum() == 1))

    hc22, lc22 = c.rolling(22).max(), c.rolling(22).min()
    for side, wvf in (("l", (hc22 - l) / hc22 * 100), ("s", (h - lc22) / lc22 * 100)):
        upper = sma(wvf, 20) + 2 * wvf.rolling(20).std(ddof=0)
        spike = (wvf >= upper) | (wvf >= wvf.rolling(50).max() * 0.85)
        end = spike.shift(fill_value=False) & ~spike
        if side == "l":
            vf_l = end
        else:
            vf_s = end
    S["vixfix"] = (vf_l, vf_s)

    w = np.exp(-(np.arange(64) ** 2) / (2 * 8.0 ** 2))
    est = np.convolve(c.to_numpy(), w)[: len(c)] / w.sum()
    est[:63] = np.nan
    est = pd.Series(est, idx)
    mae = (c - est).abs().rolling(499).mean() * 3
    S["nw_env"] = (xup(c, est - mae), xdn(c, est + mae))

    bl, bs, cl, cs = smc(df)
    S["smc_bos"] = (bl, bs)
    S["smc_choch"] = (cl, cs)
    S["fvg_retest"] = fvg(df, a14.to_numpy())

    body = (c - o).abs()
    S["engulfing"] = ((c > o) & (c.shift() < o.shift()) & (c >= o.shift()) & (o <= c.shift())
                      & (body > body.shift()) & (c.shift() < c.shift(4)),
                      (c < o) & (c.shift() > o.shift()) & (c <= o.shift()) & (o >= c.shift())
                      & (body > body.shift()) & (c.shift() > c.shift(4)))
    rng = (h - l).replace(0, np.nan)
    low_w = np.minimum(o, c) - l
    up_w = h - np.maximum(o, c)
    S["pin_bar"] = ((low_w >= 0.6 * rng) & (body <= 0.3 * rng) & (l <= l.rolling(10).min()),
                    (up_w >= 0.6 * rng) & (body <= 0.3 * rng) & (h >= h.rolling(10).max()))
    inside = (h.shift() < h.shift(2)) & (l.shift() > l.shift(2))
    S["inside_break"] = (inside & (c > h.shift(2)), inside & (c < l.shift(2)))

    spike = v > 2.5 * sma(v, 20).shift()
    pos_in = (c - l) / rng
    up_bar = spike & (c > o) & (pos_in > 0.7)
    dn_bar = spike & (c < o) & (pos_in < 0.3)
    S["vol_spike"] = (up_bar, dn_bar)
    S["vol_spike_fade"] = (dn_bar, up_bar)

    out = {}
    for name, (lo_s, sh_s) in S.items():
        lo_a = np.asarray(pd.Series(lo_s, idx).fillna(False), dtype=bool)
        sh_a = np.asarray(pd.Series(sh_s, idx).fillna(False), dtype=bool)
        out[name] = (lo_a, sh_a)
    return out


# ---------------------------------------------------------------- симуляция
class Sim:
    def __init__(self, d1: pd.DataFrame, hold: int):
        self.H = hold
        self.ts = d1.index.asi8
        self.o = d1.o.to_numpy()
        pad = np.full(hold, np.nan)
        self.hp = np.r_[d1.h.to_numpy(), pad]
        self.lp = np.r_[d1.l.to_numpy(), pad]
        self.cp = np.r_[d1.c.to_numpy(), pad]
        self.N = len(d1)

    def entry_index(self, tf_df: pd.DataFrame, tf: str) -> np.ndarray:
        close_ts = (tf_df.index + pd.Timedelta(tf)).asi8
        i = np.searchsorted(self.ts, close_ts)
        ok = i < self.N
        ok[ok] = self.ts[i[ok]] == close_ts[ok]
        return np.where(ok, i, -1)

    def trade(self, e: np.ndarray, side: int, D: np.ndarray) -> dict:
        """Для входов e (индекс часовой свечи), стороны и стопа D → R по каждому RR."""
        H = self.H
        res = {rr: (np.full(len(e), np.nan), np.zeros(len(e), np.int64), np.zeros(len(e), bool))
               for rr in RRS}
        steps = np.arange(H)
        for s in range(0, len(e), 3000):
            ee, dd = e[s:s + 3000], D[s:s + 3000]
            rows = ee[:, None] + steps
            hi, lo = self.hp[rows], self.lp[rows]
            ent = self.o[ee]
            complete = ee + H <= self.N
            if side == 1:
                sm = lo <= (ent - dd)[:, None]
            else:
                sm = hi >= (ent + dd)[:, None]
            si = np.where(sm.any(1), sm.argmax(1), H)
            last = self.cp[np.minimum(ee + H - 1, self.N + H - 1)]
            cost = FEE * ent / dd
            for rr in RRS:
                if side == 1:
                    tm = hi >= (ent + rr * dd)[:, None]
                else:
                    tm = lo <= (ent - rr * dd)[:, None]
                ti = np.where(tm.any(1), tm.argmax(1), H)
                win = ti < si
                loss = (si <= ti) & (si < H)
                tout = (si == H) & (ti == H)
                r = np.where(win, rr, np.where(loss, -1.0, side * (last - ent) / dd))
                r = r - cost
                r[tout & ~complete] = np.nan
                ex = ee + np.minimum(np.minimum(si, ti), H - 1)
                R, X, W = res[rr]
                R[s:s + 3000], X[s:s + 3000], W[s:s + 3000] = r, ex, win
        return res


def non_overlap(e: np.ndarray, x: np.ndarray, r: np.ndarray) -> np.ndarray:
    keep = np.zeros(len(e), bool)
    free = -1
    for i in range(len(e)):
        if e[i] >= free and not np.isnan(r[i]):
            keep[i] = True
            free = x[i] + 1
    return keep


def stops(tf_df: pd.DataFrame, side: int, entry_px: np.ndarray, a: np.ndarray, kind, mult):
    if mult is not None:
        return mult * a
    if side == 1:
        lvl = tf_df.l.rolling(5).min().to_numpy() - 0.1 * a
        D = entry_px - lvl
    else:
        lvl = tf_df.h.rolling(5).max().to_numpy() + 0.1 * a
        D = lvl - entry_px
    return np.clip(D, 0.5 * a, 3.0 * a)


def period_masks(ts_ns: np.ndarray) -> dict[str, np.ndarray]:
    out = {}
    for name, a, b in PERIODS:
        lo, hi = pd.Timestamp(a, tz="UTC").value, pd.Timestamp(b, tz="UTC").value
        out[name] = (ts_ns >= lo) & (ts_ns < hi)
    return out


def stats(r: np.ndarray, win: np.ndarray) -> dict:
    n = len(r)
    if n == 0:
        return {"n": 0}
    m = float(r.mean())
    sd = float(r.std(ddof=1)) if n > 1 else np.nan
    pos, neg = r[r > 0].sum(), -r[r < 0].sum()
    return {"n": n, "mean": m, "lo": m - 1.96 * sd / np.sqrt(n), "hi": m + 1.96 * sd / np.sqrt(n),
            "wr": float(win.mean()), "pf": float(pos / neg) if neg > 0 else np.inf,
            "sum": float(r.sum())}


def placebo(sigs: dict, seed: int, min_shift: int) -> dict:
    """Плацебо: каждый сигнал циклически сдвинут на случайное число свечей.
    Частота и кучность сигнала те же, связь с ценой разорвана. Сколько ячеек
    пройдёт ворота у плацебо — столько находок у настоящих сигналов ничего не стоят."""
    rng = np.random.default_rng(seed)
    out = {}
    for name, (lo_s, sh_s) in sigs.items():
        n = len(lo_s)
        out[name] = tuple(np.roll(x, int(rng.integers(min_shift, n - min_shift))) for x in (lo_s, sh_s))
    return out


def run(sym: str, tf: str, seed: int | None = None) -> list[dict]:
    t0 = time.time()
    d1 = load_1h(sym)
    df = resample(d1, tf)
    sim = Sim(d1, HOLD[tf])
    eidx = sim.entry_index(df, tf)
    valid = eidx >= 0
    a = atr(df, 14).to_numpy()
    entry_px = np.where(valid, sim.o[np.maximum(eidx, 0)], np.nan)
    good = valid & ~np.isnan(a) & (np.arange(len(df)) > 250)
    pm_bar = period_masks(df.index.asi8)
    sigs = signals(df, tf)
    if seed is not None:
        sigs = placebo(sigs, seed, 720 if tf == "1h" else 180)
    rows = []
    ctrl_step = 2 if tf == "1h" else 1
    ctrl_sel = np.flatnonzero(good)[::ctrl_step]
    for side in (1, -1):
        for kind, mult in STOPS:
            D_all = stops(df, side, entry_px, a, kind, mult)
            stop_pct = D_all / entry_px
            ctrl = sim.trade(eidx[ctrl_sel], side, D_all[ctrl_sel])
            ctrl_mean = {}
            for rr in RRS:
                R = ctrl[rr][0]
                for p, m in pm_bar.items():
                    mm = m[ctrl_sel] & ~np.isnan(R)
                    ctrl_mean[(rr, p)] = float(R[mm].mean()) if mm.any() else np.nan
            for name, (lo_s, sh_s) in sigs.items():
                fire = (lo_s if side == 1 else sh_s) & good
                sel = np.flatnonzero(fire)
                if len(sel) < 5:
                    continue
                res = sim.trade(eidx[sel], side, D_all[sel])
                for rr in RRS:
                    R, X, W = res[rr]
                    keep = non_overlap(eidx[sel], X, R)
                    row = {"sym": sym, "tf": tf, "signal": name, "side": "long" if side == 1 else "short",
                           "stop": kind, "rr": rr,
                           "stop_pct_med": float(np.nanmedian(stop_pct[sel]))}
                    for p, m in pm_bar.items():
                        mk = keep & m[sel]
                        st = stats(R[mk], W[mk])
                        for k2, v2 in st.items():
                            row[f"{p}_{k2}"] = v2
                        row[f"{p}_ctrl"] = ctrl_mean[(rr, p)]
                    st = stats(R[keep], W[keep])
                    for k2, v2 in st.items():
                        row[f"all_{k2}"] = v2
                    rows.append(row)
            for rr in RRS:
                row = {"sym": sym, "tf": tf, "signal": "_control", "side": "long" if side == 1 else "short",
                       "stop": kind, "rr": rr, "stop_pct_med": float(np.nanmedian(stop_pct[ctrl_sel]))}
                R, X, W = ctrl[rr]
                for p, m in pm_bar.items():
                    mk = m[ctrl_sel] & ~np.isnan(R)
                    st = stats(R[mk], W[mk])
                    for k2, v2 in st.items():
                        row[f"{p}_{k2}"] = v2
                    row[f"{p}_ctrl"] = ctrl_mean[(rr, p)]
                rows.append(row)
    print(f"{sym} {tf}: {len(rows)} ячеек за {time.time() - t0:.0f}с", flush=True)
    return rows


def main(argv: list[str]) -> None:
    coins = [a for a in argv if a.endswith("USDT")] or list(COINS)
    tfs = [a for a in argv if a in HOLD] or ["4h", "1h"]
    seed = next((int(a.split("=")[1]) for a in argv if a.startswith("placebo=")), None)
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / ("tv_lab_cells.csv" if seed is None else f"tv_lab_cells_placebo{seed}.csv")
    rows = []
    for sym in coins:
        if not (DATA / f"1h_{sym}.csv").exists():
            print(f"{sym}: нет часовой истории, пропуск")
            continue
        for tf in tfs:
            rows += run(sym, tf, seed)
            pd.DataFrame(rows).to_csv(out, index=False)
    print(f"готово → {out}")


if __name__ == "__main__":
    main(sys.argv[1:])
