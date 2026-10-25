"""25.10 (оператор: «42 страницы стратегий TradingView — не верю, что там нет ничего полезного; проверь вдумчиво»).
Стратегии сообщества TradingView (открытый код, разобран построчно 25.10) — перенос на Python С ПАРАМЕТРАМИ АВТОРОВ, без
подгонки. Правила до прогона:
- данные: минутки Binance spot BTCUSDT/ETHUSDT 17.08.2017–24.10.2026 (остановки биржи заполнены, в них бар плоский),
  бары 1h / 4h / 1d по UTC собираются из минуток;
- сигнал на закрытии бара → исполнение по open следующего бара; стоп/тейк внутри бара — по high/low, если в одном баре
  достижимы оба — сначала стоп (осторожно); выход по сигналу — по open следующего бара;
- издержки WEEX за сторону: тейкер 0.048% + проскальзывание 0.02% (вход и выход рыночные; лимитный тейк — тоже 0.068%,
  осторожно); фандинг Binance USDⓈ-M с 10.09.2019: лонг платит ставку × номинал в каждый расчёт, пока позиция открыта;
- размер: 1 единица номинала на сделку (итог — сумма % на сделку, без сложного процента) — чтобы сравнивать механику,
  а не настройку риска; R — для стратегий со стопом;
- отчёт: сделок, доля плюсовых, средний net % на сделку [95% ДИ], сумма, до издержек, по половинам периода и за
  последние 2 года, худшая просадка суммы; контроль — те же длительности сделок со случайным входом (200 повторов, ранг).
Ошибки в исходниках авторов отмечены у функций; переносится замысел, ошибка — отдельно."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

COST = 0.00048 + 0.0002                                   # за сторону


# ---------------------------------------------------------------- индикаторы (как ta.* в Pine)
def rma(x: np.ndarray, n: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    a = 1.0 / n
    s, k = 0.0, 0
    for i, v in enumerate(x):
        if np.isnan(v):
            continue
        if k < n:
            s += v
            k += 1
            if k == n:
                out[i] = s / n
        else:
            out[i] = out[i - 1] + a * (v - out[i - 1])
    return out


def ema(x, n):
    return pd.Series(x).ewm(span=n, adjust=False).mean().to_numpy()


def sma(x, n):
    return pd.Series(x).rolling(n).mean().to_numpy()


def tr(h, l, c):
    pc = np.r_[np.nan, c[:-1]]
    return np.nanmax(np.c_[h - l, np.abs(h - pc), np.abs(l - pc)], axis=1)


def atr(h, l, c, n):
    return rma(tr(h, l, c), n)


def rsi(c, n):
    d = np.diff(c, prepend=np.nan)
    up, dn = rma(np.where(d > 0, d, 0.0), n), rma(np.where(d < 0, -d, 0.0), n)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(dn == 0, 100.0, 100 - 100 / (1 + up / dn))


def dmi(h, l, c, n, sm):
    up, dn = np.diff(h, prepend=np.nan), -np.diff(l, prepend=np.nan)
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    mdm = np.where((dn > up) & (dn > 0), dn, 0.0)
    t = rma(tr(h, l, c), n)
    with np.errstate(divide="ignore", invalid="ignore"):
        pdi, mdi = 100 * rma(pdm, n) / t, 100 * rma(mdm, n) / t
        dx = 100 * np.abs(pdi - mdi) / (pdi + mdi)
    return pdi, mdi, rma(np.nan_to_num(dx, nan=0.0), sm)


def supertrend(h, l, c, factor, n):
    """ta.supertrend: (линия, направление −1 вверх / +1 вниз)."""
    a = atr(h, l, c, n)
    hl2 = (h + l) / 2
    ub, lb = hl2 + factor * a, hl2 - factor * a
    fu, fl = ub.copy(), lb.copy()
    d = np.ones(len(c))
    st = np.full(len(c), np.nan)
    for i in range(1, len(c)):
        if np.isnan(a[i]):
            continue
        fl[i] = lb[i] if (np.isnan(fl[i - 1]) or lb[i] > fl[i - 1] or c[i - 1] < fl[i - 1]) else fl[i - 1]
        fu[i] = ub[i] if (np.isnan(fu[i - 1]) or ub[i] < fu[i - 1] or c[i - 1] > fu[i - 1]) else fu[i - 1]
        if np.isnan(a[i - 1]):
            d[i] = 1
        elif st[i - 1] == fu[i - 1]:
            d[i] = -1 if c[i] > fu[i] else 1
        else:
            d[i] = 1 if c[i] < fl[i] else -1
        st[i] = fl[i] if d[i] == -1 else fu[i]
    return st, d


# ---------------------------------------------------------------- исполнение
def trades_from_signals(o, h, l, c, entries, exits=None, stops=None, tps=None, max_bars=None):
    """entries[i] ∈ {+1,−1,0} на закрытии бара i → вход по o[i+1]. exits[i] (bool/направление) — выход по o[i+1].
    stops/tps — функции (i_entry, side, entry_px) → (стоп, тейк) или массивы уровня стопа по барам (трейлинг).
    Возвращает список (i_in, i_out, side, px_in, px_out, why)."""
    out, pos = [], None
    n = len(c)
    for i in range(n - 1):
        if pos is not None:
            j, side, px, sl, tp = pos
            hit = None
            # стоп-линия, известная к началу бара i (в Pine strategy.exit на закрытии i−1 действует на баре i)
            lvl_sl = (sl[i - 1] if i > 0 else np.nan) if isinstance(sl, np.ndarray) else sl
            if i >= j:                                     # и на баре входа (вход по его open): осторожно
                if side > 0:
                    if lvl_sl is not None and not np.isnan(lvl_sl) and l[i] <= lvl_sl:
                        hit = (min(o[i], lvl_sl), "стоп")
                    elif tp is not None and h[i] >= tp:
                        hit = (max(o[i], tp), "тейк")
                else:
                    if lvl_sl is not None and not np.isnan(lvl_sl) and h[i] >= lvl_sl:
                        hit = (max(o[i], lvl_sl), "стоп")
                    elif tp is not None and l[i] <= tp:
                        hit = (min(o[i], tp), "тейк")
            if hit:
                out.append((j, i, side, px, hit[0], hit[1]))
                pos = None
            elif (exits is not None and exits[i] and (exits[i] is True or exits[i] == side)) or \
                    (max_bars and i - j >= max_bars) or (entries[i] == -side):
                out.append((j, i + 1, side, px, o[i + 1], "сигнал"))
                pos = None
        if pos is None and entries[i] != 0 and not (out and out[-1][1] == i + 1 and out[-1][2] == entries[i]):
            side, px = int(entries[i]), o[i + 1]
            sl, tp = stops(i, side, c[i]) if stops else (None, None)
            pos = (i + 1, side, px, sl, tp)
    if pos is not None:
        j, side, px, _, _ = pos
        out.append((j, n - 1, side, px, c[-1], "конец"))
    return out


# ---------------------------------------------------------------- стратегии (параметры авторов)
def superflip(b):
    """Bitcoin SuperFlip (852 буста): ta.supertrend(1.8, 10) разворот + close vs EMA200; лонг и шорт; выход — обратный
    разворот. Стоп/тейк у автора выключены. Автор: BTCUSD 1H, комиссия 0.075%."""
    o, h, l, c = b
    _, d = supertrend(h, l, c, 1.8, 10)
    e200 = ema(c, 200)
    bull = np.r_[False, np.diff(d) < 0]
    bear = np.r_[False, np.diff(d) > 0]
    ent = np.where(bull & (c > e200), 1, np.where(bear & (c < e200), -1, 0))
    ex = np.where(bear, 1, np.where(bull, -1, 0))
    return trades_from_signals(o, h, l, c, ent, exits=ex)


def trendshift(b):
    """TrendShift (712): SuperTrend с множителем по ADX (ADX>25 — 1.75, <20 — 4.5, между — прежний); в «шуме» входов нет;
    стоп — линия SuperTrend (трейлинг), тейк 2R. У автора тейк пересчитывается каждый бар от текущей линии («уезжает») —
    здесь тейк фиксирован на входе (замысел)."""
    o, h, l, c = b
    _, _, adx = dmi(h, l, c, 14, 14)
    reg = np.zeros(len(c))
    cur = 0
    for i, a in enumerate(adx):
        if a > 25:
            cur = 1
        elif a < 20:
            cur = -1
        reg[i] = cur
    st_t, d_t = supertrend(h, l, c, 1.75, 10)
    st_w, d_w = supertrend(h, l, c, 4.5, 10)
    st = np.where(reg == -1, st_w, st_t)
    d = np.where(reg == -1, d_w, d_t)
    flip = np.r_[False, np.diff(d) != 0]
    ok = reg != -1
    ent = np.where(flip & (d == -1) & ok, 1, np.where(flip & (d == 1) & ok, -1, 0))

    def stops(i, side, px):
        dist = abs(px - st[i])
        return st, px + side * 2 * dist
    return trades_from_signals(o, h, l, c, ent, stops=stops)


def gaussian_channel(b, N=4, per=89, mult=1.5):
    """TRADLEWARE Gaussian Channel + StochRSI (ETH, 398): канал Эйлерса (4 полюса, период 89, ×1.5 TR); вход — канал
    растёт и close > верхней полосы и StochRSI K >80 или <25 и close > SMA200 и свеча зелёная; выход — close ниже
    верхней полосы или фильтр падает; стоп — нижняя полоса. Только лонг."""
    o, h, l, c = b
    src = (h + l + c) / 3
    beta = (1 - math.cos(4 * math.asin(1) / per)) / (math.pow(1.414, 2 / N) - 1)
    alpha = -beta + math.sqrt(beta * beta + 2 * beta)
    x = 1 - alpha

    def filt(s):
        f = np.zeros(len(s))
        coef = [math.comb(N, k) for k in range(N + 1)]
        for i in range(len(s)):
            v = alpha ** N * (0 if np.isnan(s[i]) else s[i])
            for k in range(1, N + 1):
                if i - k >= 0:
                    v += (-1) ** (k + 1) * coef[k] * x ** k * f[i - k]
            f[i] = v
        return f
    fl = filt(src)
    ftr = filt(np.nan_to_num(tr(h, l, c)))
    hb, lb = fl + ftr * mult, fl - ftr * mult
    r = rsi(c, 14)
    lo, hi = pd.Series(r).rolling(14).min().to_numpy(), pd.Series(r).rolling(14).max().to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        st = 100 * (r - lo) / (hi - lo)
    k = sma(st, 3)
    s200 = sma(c, 200)
    green = np.r_[False, fl[1:] > fl[:-1]]
    ent = np.where(green & (c > hb) & ((k > 80) | (k < 25)) & (c > s200) & (c > o), 1, 0)
    ent[:300] = 0                                          # прогрев фильтра
    ex = (c < hb) | ~green
    return trades_from_signals(o, h, l, c, ent, exits=ex, stops=lambda i, s, px: (lb, None))


def rsi_mr(b):
    """RSI Mean Reversion (554): RSI(3) пересёк 40 вверх — лонг (шорт закрыть), пересёк 70 вниз — шорт (лонг закрыть);
    всегда в рынке. Автор: фьючерсы, $40 за ордер."""
    o, h, l, c = b
    r = rsi(c, 3)
    up = np.r_[False, (r[1:] > 40) & (r[:-1] <= 40)]
    dn = np.r_[False, (r[1:] < 70) & (r[:-1] >= 70)]
    ent = np.where(up, 1, np.where(dn, -1, 0))
    return trades_from_signals(o, h, l, c, ent)


def glow_ribbon(b):
    """Glow Ribbon Flip (594): EMA21 ± 2×ATR10, полоса двигается только в сторону сделки; разворот направления — вход,
    откат к базису внутри тренда — повторный вход; стоп — полоса, тейк 2R."""
    o, h, l, c = b
    bs, a = ema(c, 21), atr(h, l, c, 10)
    lo, hi = np.full(len(c), np.nan), np.full(len(c), np.nan)
    d = np.zeros(len(c))
    for i in range(1, len(c)):
        if np.isnan(a[i]):
            continue
        ln, hn = bs[i] - 2 * a[i], bs[i] + 2 * a[i]
        pl, ph = lo[i - 1], hi[i - 1]
        lo[i] = ln if np.isnan(pl) or ln > pl or c[i - 1] < pl else pl
        hi[i] = hn if np.isnan(ph) or hn < ph or c[i - 1] > ph else ph
        if d[i - 1] == 0:
            d[i] = 1 if c[i] > bs[i] else -1
        elif d[i - 1] == 1 and c[i] < pl:
            d[i] = -1
        elif d[i - 1] == -1 and c[i] > ph:
            d[i] = 1
        else:
            d[i] = d[i - 1]
    prev = np.r_[0, d[:-1]]
    flip = d != prev
    pull_b = (d == 1) & (prev == 1) & (c > bs) & (np.r_[np.nan, c[:-1]] <= np.r_[np.nan, bs[:-1]])
    pull_s = (d == -1) & (prev == -1) & (c < bs) & (np.r_[np.nan, c[:-1]] >= np.r_[np.nan, bs[:-1]])
    ent = np.where((flip & (d == 1)) | pull_b, 1, np.where((flip & (d == -1)) | pull_s, -1, 0))
    line = np.where(d == 1, lo, hi)

    def stops(i, side, px):
        return line, px + side * 2 * abs(px - line[i])
    return trades_from_signals(o, h, l, c, ent, stops=stops)


def coil_breaker(b):
    """Coil Breaker (157): размах RSI(14) за 20 баров в нижних 20% своей истории (100) за последние 5 баров + RSI пробил
    свой 20-барный максимум + EMA50 растёт 5 баров + ADX ≥ 15 → лонг (шорт зеркально); стоп 2×ATR14, тейк 2R.
    ОШИБКА у автора: тейк лонга = close + stopPrice×2 (цена, а не расстояние) — почти недостижим; здесь — 2R (замысел)."""
    o, h, l, c = b
    r = rsi(c, 14)
    rh = pd.Series(r).rolling(20).max().to_numpy()
    rl = pd.Series(r).rolling(20).min().to_numpy()
    rng = rh - rl
    pr = pd.Series(rng).rolling(100).apply(lambda w: (w[:-1] <= w[-1]).mean() * 100 if not np.isnan(w).any() else np.nan,
                                           raw=True).to_numpy()
    sq = pr <= 20
    last = np.full(len(c), 10 ** 9)
    k = 10 ** 9
    for i in range(len(c)):
        k = 0 if sq[i] else k + 1
        last[i] = k
    recent = last <= 5
    e = ema(c, 50)
    up = e > np.r_[np.full(5, np.nan), e[:-5]]
    dn = e < np.r_[np.full(5, np.nan), e[:-5]]
    _, _, adx = dmi(h, l, c, 14, 14)
    lt = np.r_[False, (r[1:] > rh[:-1]) & (r[:-1] <= np.r_[np.nan, rh[:-2]])]
    stt = np.r_[False, (r[1:] < rl[:-1]) & (r[:-1] >= np.r_[np.nan, rl[:-2]])]
    ent = np.where(lt & recent & up & (adx >= 15), 1, np.where(stt & recent & dn & (adx >= 15), -1, 0))
    a = atr(h, l, c, 14)

    def stops(i, side, px):
        return px - side * 2 * a[i], px + side * 4 * a[i]
    return trades_from_signals(o, h, l, c, ent, stops=stops)


def z_regime(b):
    """Z-Regime Switch: z цены за 60; спокойный режим (z ATR% за 120 ≤ 0.5) и ER20 ≤ 0.35 — возврат: z пересёк −2 вверх
    и скорость z > 0 → лонг (выход |z| ≤ 0.25); бурный режим и ER ≥ 0.4 — тренд: z пересёк 1.5 вверх → лонг (выход z
    ниже 0.25); EMA200 — сторона; стоп 2.5×ATR входа, время 30 баров. Шорт зеркально."""
    o, h, l, c = b
    mu, sd = sma(c, 60), pd.Series(c).rolling(60).std(ddof=0).to_numpy()
    z = (c - mu) / sd
    a = atr(h, l, c, 14)
    ap = a / c * 100
    rz = (ap - sma(ap, 120)) / pd.Series(ap).rolling(120).std(ddof=0).to_numpy()
    zv = ema(np.diff(z, prepend=np.nan), 3)
    pl = pd.Series(np.abs(np.diff(c, prepend=np.nan))).rolling(20).sum().to_numpy()
    er = np.abs(c - np.r_[np.full(20, np.nan), c[:-20]]) / pl
    bias = ema(c, 200)
    hot, calm = rz > 0.5, rz <= 0.5
    zp = np.r_[np.nan, z[:-1]]
    rl = calm & (er <= 0.35) & (c > bias) & (z > -2) & (zp <= -2) & (zv > 0)
    rs = calm & (er <= 0.35) & (c < bias) & (z < 2) & (zp >= 2) & (zv < 0)
    tl = hot & (er >= 0.4) & (c > bias) & (z > 1.5) & (zp <= 1.5) & (zv > 0)
    ts = hot & (er >= 0.4) & (c < bias) & (z < -1.5) & (zp >= -1.5) & (zv < 0)
    ent = np.where(rl | tl, 1, np.where(rs | ts, -1, 0))
    mode = np.where(rl | rs, 1, np.where(tl | ts, 2, 0))
    out, pos = [], None
    for i in range(len(c) - 1):
        if pos is not None:
            j, side, px, md, sl = pos
            if i >= j and ((side > 0 and l[i] <= sl) or (side < 0 and h[i] >= sl)):
                out.append((j, i, side, px, min(o[i], sl) if side > 0 else max(o[i], sl), "стоп"))
                pos = None
            else:
                if md == 1:
                    sig = z[i] >= -0.25 if side > 0 else z[i] <= 0.25
                else:
                    sig = (z[i] < 0.25 <= zp[i]) if side > 0 else (z[i] > -0.25 >= zp[i])
                if sig or i - j >= 30:
                    out.append((j, i + 1, side, px, o[i + 1], "сигнал"))
                    pos = None
        if pos is None and ent[i] != 0 and not np.isnan(a[i]):
            side = int(ent[i])
            pos = (i + 1, side, o[i + 1], mode[i], o[i + 1] - side * 2.5 * a[i])
    return out


def aurora_kama(b):
    """Aurora KAMA (307): KAMA(10, 2, 30) растёт 3 бара и close > SMA200 → лонг (не чаще раза в 5 баров); выход: стоп 4%,
    трейлинг 6% от максимума после 5 баров, KAMA падает 3 бара. Шорт зеркально (у автора фильтр SMA200 и для шорта)."""
    o, h, l, c = b
    er_n = 10
    ch = np.abs(c - np.r_[np.full(er_n, np.nan), c[:-er_n]])
    vol = pd.Series(np.abs(np.diff(c, prepend=np.nan))).rolling(er_n).sum().to_numpy()
    er = np.where(vol > 0, ch / vol, 0)
    sc = (er * (2 / 3 - 2 / 31) + 2 / 31) ** 2
    k = np.full(len(c), np.nan)
    for i in range(len(c)):
        if np.isnan(sc[i]):
            continue
        k[i] = c[i] if np.isnan(k[i - 1]) else k[i - 1] + sc[i] * (c[i] - k[i - 1])
    rising = np.r_[np.zeros(3, bool), (k[3:] > k[2:-1]) & (k[2:-1] > k[1:-2]) & (k[1:-2] > k[:-3])]
    falling = np.r_[np.zeros(3, bool), (k[3:] < k[2:-1]) & (k[2:-1] < k[1:-2]) & (k[1:-2] < k[:-3])]
    s200 = sma(c, 200)
    out, pos, last_in = [], None, -10
    for i in range(len(c) - 1):
        if pos is not None:
            j, side, px, ext = pos
            ext = max(ext, h[i]) if side > 0 else min(ext, l[i])
            sl = px * (1 - side * 0.04)
            if i - j >= 5:
                tsl = ext * (1 - side * 0.06)
                sl = max(sl, tsl) if side > 0 else min(sl, tsl)
            if i >= j and ((side > 0 and l[i] <= sl) or (side < 0 and h[i] >= sl)):
                out.append((j, i, side, px, min(o[i], sl) if side > 0 else max(o[i], sl), "стоп"))
                pos = None
            elif (side > 0 and falling[i]) or (side < 0 and rising[i]):
                out.append((j, i + 1, side, px, o[i + 1], "сигнал"))
                pos = None
            else:
                pos = (j, side, px, ext)
        if pos is None and i - last_in >= 5:
            side = 1 if rising[i] and c[i] > s200[i] else (-1 if falling[i] and c[i] < s200[i] else 0)
            if side:
                pos = (i + 1, side, o[i + 1], o[i + 1])
                last_in = i
    return out


STRATS = {"SuperFlip (Supertrend+EMA200)": (superflip, ["1h", "4h"]),
          "TrendShift (Supertrend по ADX)": (trendshift, ["1h", "4h"]),
          "Gaussian Channel + StochRSI": (gaussian_channel, ["1d", "4h"]),
          "RSI Mean Reversion RSI(3)": (rsi_mr, ["1h", "4h"]),
          "Glow Ribbon Flip": (glow_ribbon, ["1h", "4h"]),
          "Coil Breaker (сжатие RSI)": (coil_breaker, ["1h", "4h"]),
          "Z-Regime Switch": (z_regime, ["1h", "4h"]),
          "Aurora KAMA": (aurora_kama, ["4h", "1d"])}
