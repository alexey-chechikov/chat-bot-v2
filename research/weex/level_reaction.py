"""Реакция цены у уровней карты дня (24.10, оператор: «что эта аналитика даёт в принятии торговых решений?»): при первом
касании уровня — отскок или пробой, что раньше; против случайных уровней на тех же расстояниях.

ПРАВИЛА ДО ПРОГОНА (не менять после):
- Данные: frozen 1m Binance spot BTC и ETH (копии). День — окно [08:00 Варшавы; следующее 08:00), как у прогноза dr-3.
  Цена отсчёта p — закрытие минуты 07:59, ATR — среднее истинного диапазона 14 закрытых часов до 08:00.
- Уровни дня (выше p — «верх», ниже — «низ»):
    коридор — p ± квантиль 90% хода каждой стороны в ATR по ВСЕМ прошлым дням (≥100 дней, причинно), как dr-3;
    вчера H/L — максимум/минимум предыдущего полного UTC-дня;
    круглые — ближайшие круглые над и под p (BTC шаг 1000, ETH шаг 50), не ближе 0.1% к p.
- Событие — первое касание уровня в окне дня (верх: high ≥ L; низ: low ≤ L). После касания, начиная со следующей минуты,
  до 24 ч: «отскок» — цена ушла на 0.5% от уровня обратно (верх: low ≤ L·0.995), «пробой» — на 0.5% за уровень (верх:
  high ≥ L·1.005); обе в одной минуте — пробой (против торговли от уровня). Вторично — 1.0%.
- Контроль — плацебо: тот же день, та же сторона, расстояние от p — как у уровня того же типа в случайный другой день
  (сохраняется распределение расстояний); 20 плацебо на событие, сиды фиксированы.
- Сделка «от уровня» (лимитка на уровне, стоп и цель по 0.5%): ожидание на сделку = (2·доля отскоков − 1)·0.5% − расходы
  0.08% (мейкер вход + тейкер стоп/мейкер цель в среднем + проскальзывание). Перевес считается, только если доля отскоков
  выше плацебо с 95% интервалом в обеих половинах по времени и ожидание после расходов > 0.
Запуск: level_reaction.py --btc=<копия> --eth=<копия>
"""
from __future__ import annotations

import math
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ARG = {a.split("=", 1)[0]: a.split("=", 1)[1] for a in sys.argv[1:] if "=" in a}
SRC = {"BTCUSDT": ARG.get("--btc", "/Users/alexeychechikov/code/bot7/backtests/frozen/BTCUSDT_1m_2y.csv"),
       "ETHUSDT": ARG.get("--eth", "/Users/alexeychechikov/code/bot7/backtests/frozen/ETHUSDT_1m_2y.csv")}
ROUND = {"BTCUSDT": 1000.0, "ETHUSDT": 50.0}
WAW = ZoneInfo("Europe/Warsaw")
Q, MIN_HIST, N_PLACEBO = 0.90, 100, 20
COST = 0.0008


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if not n:
        return 0.0, 1.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return c - h, c + h


def outcome(h, l, j, lvl, up, thr, n):
    """После касания в минуте j: True — отскок раньше пробоя, False — пробой, "amb" — порядок внутри минуты неизвестен,
    None — ни то ни другое за 24 ч. 25.10 (аудит GPT R4): сначала сама минута касания — пробой в ней (цена прошла
    уровень и ушла дальше) → пробой; «отскок» в ней или оба порога → неоднозначно (экстремум мог быть до касания)."""
    if up:
        brk0, rev0 = h[j] >= lvl * (1 + thr), l[j] <= lvl * (1 - thr)
    else:
        brk0, rev0 = l[j] <= lvl * (1 - thr), h[j] >= lvl * (1 + thr)
    if rev0:
        return "amb"
    if brk0:
        return False
    a, b = j + 1, min(j + 1 + 1440, n)
    if a >= b:
        return None
    hs, ls = h[a:b], l[a:b]
    if up:
        rev, brk = np.flatnonzero(ls <= lvl * (1 - thr)), np.flatnonzero(hs >= lvl * (1 + thr))
    else:
        rev, brk = np.flatnonzero(hs >= lvl * (1 + thr)), np.flatnonzero(ls <= lvl * (1 - thr))
    r = rev[0] if len(rev) else None
    k = brk[0] if len(brk) else None
    if r is None and k is None:
        return None
    if k is not None and (r is None or k <= r):
        return False
    return True


def first_touch(h, l, a, b, lvl, up):
    idx = np.flatnonzero(h[a:b] >= lvl) if up else np.flatnonzero(l[a:b] <= lvl)
    return a + idx[0] if len(idx) else None


def days_of(ts_ms: np.ndarray):
    first = datetime.fromtimestamp(ts_ms[0] / 1000, timezone.utc).date() + timedelta(days=2)
    last = datetime.fromtimestamp(ts_ms[-1] / 1000, timezone.utc).date() - timedelta(days=1)
    d = first
    while d <= last:
        nd = d + timedelta(days=1)                  # 25.10: до СЛЕДУЮЩЕГО 08:00 по Варшаве (переход времени — 23/25 ч)
        yield d, int(datetime(d.year, d.month, d.day, 8, tzinfo=WAW).timestamp() * 1000), \
            int(datetime(nd.year, nd.month, nd.day, 8, tzinfo=WAW).timestamp() * 1000)
        d += timedelta(days=1)


def run(sym: str, path: str) -> None:
    df = pd.read_csv(path)
    ts = df["ts"].to_numpy(np.int64)
    h, l, c = (df[k].to_numpy(float) for k in ("high", "low", "close"))
    n = len(ts)
    pos = {int(t): i for i, t in enumerate(ts)}
    hr = df.assign(t=pd.to_datetime(ts, unit="ms")).set_index("t").resample("1h").agg(
        {"high": "max", "low": "min", "close": "last"}).dropna()
    tr = np.maximum(hr["high"] - hr["low"], np.maximum(abs(hr["high"] - hr["close"].shift()),
                                                       abs(hr["low"] - hr["close"].shift())))
    atr_h = tr.rolling(14).mean()
    dayhl = df.assign(d=pd.to_datetime(ts, unit="ms").date).groupby("d").agg(H=("high", "max"), L=("low", "min"),
                                                                            N=("high", "size"))
    hist_up, hist_dn, days = [], [], []
    for d, a_ms, b_ms in days_of(ts):
        i0, i1 = pos.get(a_ms - 60_000), pos.get(b_ms - 60_000)
        if i0 is None or i1 is None:
            continue
        t_h = pd.Timestamp(a_ms - 3_600_000, unit="ms")
        if t_h not in atr_h.index or not np.isfinite(atr_h.loc[t_h]):
            continue
        p, atr = c[i0], float(atr_h.loc[t_h])
        up_mv, dn_mv = (h[i0 + 1:i1 + 1].max() - p) / atr, (p - l[i0 + 1:i1 + 1].min()) / atr
        lv = {}
        if len(hist_up) >= MIN_HIST:
            lv["коридор"] = (p + np.quantile(hist_up, Q) * atr, p - np.quantile(hist_dn, Q) * atr)
        yd = d - timedelta(days=1)
        if yd in dayhl.index and dayhl.loc[yd, "N"] == 1440:
            yh, yl = float(dayhl.loc[yd, "H"]), float(dayhl.loc[yd, "L"])
            lv["вчера H/L"] = (yh if yh > p else None, yl if yl < p else None)
        step = ROUND[sym]
        ru, rd = math.ceil(p / step) * step, math.floor(p / step) * step
        lv["круглые"] = (ru if ru / p - 1 > 0.001 else ru + step, rd if 1 - rd / p > 0.001 else rd - step)
        days.append({"d": d, "i0": i0, "i1": i1, "p": p, "lv": lv})
        hist_up.append(up_mv)
        hist_dn.append(dn_mv)
    mid = days[len(days) // 2]["d"]
    rng = np.random.default_rng(20261024)
    types = ("коридор", "вчера H/L", "круглые")
    dist = {t: [(x["lv"][t][0] / x["p"] - 1 if x["lv"][t][0] else None, 1 - x["lv"][t][1] / x["p"] if x["lv"][t][1] else None)
                for x in days if t in x["lv"]] for t in types}
    print(f"\n{sym}: дней {len(days)} ({days[0]['d']} … {days[-1]['d']}), срез половин {mid}")
    for thr in (0.005, 0.010):
        print(f"  порог {thr * 100:.1f}%: тип | касаний | отскок первым [95%] | 1-я / 2-я половина | плацебо | "
              f"ожидание сделки от уровня после расходов")
        for t in types:
            real, plac, amb = {0: [], 1: []}, {0: [], 1: []}, {0: 0, 1: 0}
            for x in days:
                if t not in x["lv"]:
                    continue
                half = 0 if x["d"] < mid else 1
                for side, lvl in ((True, x["lv"][t][0]), (False, x["lv"][t][1])):
                    if not lvl:
                        continue
                    j = first_touch(h, l, x["i0"] + 1, x["i1"] + 1, lvl, side)
                    if j is not None:
                        o = outcome(h, l, j, lvl, side, thr, n)
                        if o == "amb":
                            amb[half] += 1
                        elif o is not None:
                            real[half].append(o)
                    pool = [dd[0 if side else 1] for dd in dist[t] if dd[0 if side else 1]]
                    for _ in range(N_PLACEBO):
                        dd = pool[rng.integers(len(pool))]
                        pl = x["p"] * (1 + dd) if side else x["p"] * (1 - dd)
                        j2 = first_touch(h, l, x["i0"] + 1, x["i1"] + 1, pl, side)
                        if j2 is not None:
                            o2 = outcome(h, l, j2, pl, side, thr, n)
                            if o2 is not None and o2 != "amb":
                                plac[half].append(o2)
            allr = real[0] + real[1]
            allp = plac[0] + plac[1]
            if not allr:
                continue
            k, nn = sum(allr), len(allr)
            lo, hi = wilson(k, nn)
            pr = sum(allp) / len(allp) if allp else float("nan")
            hv = " / ".join(f"{sum(real[s]) / len(real[s]) * 100:.0f}% vs {sum(plac[s]) / len(plac[s]) * 100:.0f}%"
                            if real[s] and plac[s] else "—" for s in (0, 1))
            ev = (2 * k / nn - 1) * thr - COST
            na = amb[0] + amb[1]
            lo_b, hi_b = k / (nn + na), (k + na) / (nn + na)          # все неоднозначные — пробой / все — отскок
            print(f"    {t:<10} | {nn:4d} (+{na} неоднозн.) | {k / nn * 100:5.1f}% [{lo * 100:.0f}…{hi * 100:.0f}], "
                  f"границы {lo_b * 100:.0f}…{hi_b * 100:.0f}% | {hv} | {pr * 100:5.1f}% | {ev * 100:+.3f}%")


def main():
    for sym, p in SRC.items():
        run(sym, p)


if __name__ == "__main__":
    main()
