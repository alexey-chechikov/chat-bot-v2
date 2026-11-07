"""W1: индикатор как код. Модель решений Pine: new4 = закрытие часа кратно 4ч, счётчики обновляются только на new4.
Что меряем: 1) пропуск часа, закрывающего 4ч (в Pine new4 не сработает, в Python сработает на следующем часе); 2) начало истории графика; 3) старт EMA (первое значение или SMA).
Запуск: python -X utf8 w1_pine_check.py"""
from __future__ import annotations

import numpy as np
import pandas as pd

import lab_core as lc

K = 2
H4 = 14400


def pine_run(t, c, cf, g, r, b, new4, jmap, side=0):
    """Построчная модель runS из Pine с обновлением счётчиков только на new4. Вход и выход по закрытию часа."""
    rG, rR = 0, 0
    legs = []
    entry, ei = 0.0, -1

    def f_run(prev, x):
        s = 0 if not np.isfinite(x) else int(np.sign(x))
        if s == 0:
            return 0
        return prev + s if prev != 0 and (s > 0) == (prev > 0) else s

    for i in range(len(t)):
        if not new4[i]:
            continue
        j = jmap[i]
        fc, fG, fR, fB = cf[j], g[j], r[j], b[j]
        rG, rR = f_run(rG, fc - fG), f_run(rR, fc - fR)
        close_now = (side == 1 and rR <= -K) or (side == -1 and rG >= K)
        if close_now:
            legs.append((ei, i, entry, float(c[i]), side))
            side = 0
        if side == 0:
            o = 0
            if fc > fB:
                if rG >= K and rR > -K:
                    o = 1
            elif rG <= -K:
                o = -1
            if o:
                side, entry, ei = o, float(c[i]), i
    return legs


def ema_sma_seed(x, n):
    """EMA со стартом от SMA первых n значений: так считается в части библиотек. Сверка чувствительности, не утверждение о Pine."""
    a = 2.0 / (n + 1)
    out = np.full(len(x), np.nan)
    ok = np.flatnonzero(np.isfinite(x))
    b = ok[0]
    if len(ok) < n:
        return out
    acc = np.mean(x[b:b + n])
    out[b + n - 1] = acc
    for i in range(b + n, len(x)):
        acc = a * x[i] + (1 - a) * acc
        out[i] = acc
    return out


def tema_sma(x, n):
    e1 = ema_sma_seed(x, n)
    e2 = ema_sma_seed(e1, n)
    e3 = ema_sma_seed(e2, n)
    return 3 * e1 - 3 * e2 + e3


def since(S, legs, frm):
    return [(int(S.t[x[0]]), int(S.t[x[1]]), x[4]) for x in legs if S.t[x[0]] >= frm]


def compare(a, b):
    sa, sb = set(a), set(b)
    return len(sa & sb), len(sa - sb), len(sb - sa)


def main():
    frm = lc.T("2025-01-01")
    print("== 1. Пропуск часа, закрывающего 4ч: new4 в Pine = time_close кратно 4ч")
    for name in ("BTC", "ETH", "XRP", "BybitBTC"):
        S = lc.load(name)
        new_p = S.t % H4 == 0
        ref = lc.run(S)
        ref5 = [x[:5] for x in ref if x[7] != "конец"]
        cf, g, r, b = S.h4["c"], S.line4(lc.G), S.line4(lc.R), S.line4(lc.B)
        i0 = S.i0
        idx = np.arange(i0, len(S.t))
        leg = pine_run(S.t[idx], S.c[idx], cf, g, r, b, new_p[idx], S.j[idx])
        leg = [(int(idx[x[0]]), int(idx[x[1]]), x[2], x[3], x[4]) for x in leg]
        miss = np.flatnonzero(S.is4 & (~new_p))
        miss = miss[miss >= i0]
        print(name, "4ч-баров с пропущенным закрывающим часом:", len(miss), "в том числе с 2025:", int((S.t[miss] >= frm).sum()), "сделки Pine/Python всего:", len(leg), len(ref5), "совпало сделок:", compare([(x[0], x[1], x[4]) for x in leg], [(x[0], x[1], x[4]) for x in ref5]))
        if len(miss):
            print("   примеры:", [pd.Timestamp(int(S.t[q]), unit="s").strftime("%Y-%m-%d %H:%M") for q in miss[:6]])
        print("   счёт сделок с 2025: совпало, только Pine, только Python:", compare(since(S, leg, frm), since(S, ref5, frm)))

    print("== 2. Начало истории: линии 4ч считаются только с даты начала, автомат стартует без позиции. Сделки с 01.01.2025 против полной истории")
    for name in ("BTC", "BybitBTC"):
        S = lc.load(name)
        ref = [x for x in lc.run(S) if x[7] != "конец"]
        ref_s = since(S, ref, frm)
        rr = lc.nets(S, [x for x in ref if S.t[x[0]] >= frm]).sum()
        raw = pd.read_csv(lc.ld.DATA / ("spot_BTCUSDT_1h.csv" if name == "BTC" else "bybit_BTCUSDT_1h.csv"))
        raw["ts"] = raw["ms"].to_numpy(np.int64) // 1000
        rows = []
        for st, warm in (("2024-12-01", "1 мес"), ("2024-10-01", "3 мес"), ("2024-07-01", "6 мес"), ("2024-01-01", "1 год"), ("2023-01-01", "2 года"), ("2022-01-01", "3 года"), ("2021-01-01", "4 года")):
            cut = lc.T(st)
            if cut < raw["ts"].iloc[0]:
                continue
            X = lc.build(name, raw[raw["ts"] >= cut], S.fund_rate, st)
            leg = [x for x in lc.run(X) if x[7] != "конец"]
            cmp_ = compare(since(X, leg, frm), ref_s)
            rx = lc.nets(X, [x for x in leg if X.t[x[0]] >= frm]).sum()
            first = next((pd.Timestamp(int(a), unit="s").strftime("%d.%m.%Y") for a in [q[0] for q in sorted(set(since(X, leg, frm)) ^ set(ref_s))][-1:]), "—")
            rows.append({"история с": st, "разгон": warm, "совпало": cmp_[0], "лишних": cmp_[1], "потеряно": cmp_[2], "итог с 2025": round(float(rx), 1), "полная": round(float(rr), 1), "последнее расхождение": first})
        print(name, "сделок с 2025 в полной истории:", len(ref_s))
        print(pd.DataFrame(rows).to_string(index=False))

    print("== 3. Старт EMA: первое значение против SMA, вся история BTC")
    S = lc.load("BTC")
    ref = [x for x in lc.run(S) if x[7] != "конец"]
    c = S.h4["c"]
    S2 = lc.load("BTC")
    for ln, fn in ((lc.G, lambda: tema_sma(c, 50)), (lc.R, lambda: tema_sma(c, 200)), (lc.B, lambda: ema_sma_seed(c, 200))):
        S2.cache[("l4", ln)] = fn()
    leg = [x for x in lc.run(S2) if x[7] != "конец"]
    print("совпало, только SMA, только первое значение:", compare([(x[0], x[1], x[4]) for x in leg], [(x[0], x[1], x[4]) for x in ref]))


if __name__ == "__main__":
    main()
