"""Шаг 8 (14.11): вариант D («держать страховку до входа системы в лонг») против A («до выхода системы») на независимых
данных — Bitstamp BTC/USD 2014–2017 (часовые свечи; публичный API Bitstamp; при выборе D не смотрелись).

ПРАВИЛА (до прогона): система — тот же движок (services/btc_signals через services/sigexec/lines) на часовых Bitstamp;
сетка — только основная 0.6/1.4 (шаг 0.1% на часовых свечах не моделируется), ордер $82, 50 лотов, путь часа O→L→H→C /
O→H→L→C, вход по уровню при пересечении сверху, мейкер 0.016%, фандинга нет (перпов не было). Страховка k=1 от
позиции сетки ($): A — шорт с входа системы до её выхода; D — до следующего входа в лонг. Издержка 0.068%/сторону.
Метрики: прибавка итога к сетке, просадка, по годам; шанс ликвидации за год при депозите $1 000 / $2 000 (позиция
сетки до $4 100). D считается подтверждённым, если просадка лучше A и ликвидаций не больше ни в одной ячейке."""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from services.btc_signals import engine as en  # noqa: E402
from services.sigexec import lines  # noqa: E402

CACHE = Path("/private/tmp/claude-501/-Users-alexeychechikov/eda61999-8155-4742-9545-80b33164ecc5/scratchpad/bitstamp_btcusd_1h.csv")
START, END = 1388534400, 1546300800          # 2014-01-01 … 2019-01-01 (прогрев линий — первые месяцы)
MAKER, SC, MM = 0.00016, 0.00068, 0.005


def fetch():
    if CACHE.exists():
        return pd.read_csv(CACHE)
    rows, t = [], START
    while t < END:
        url = f"https://www.bitstamp.net/api/v2/ohlc/btcusd/?step=3600&limit=1000&start={t}"
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "research"}), timeout=30) as r:
            data = json.loads(r.read())["data"]["ohlc"]
        if not data:
            break
        rows += data
        t = int(data[-1]["timestamp"]) + 3600
        time.sleep(0.3)
    d = pd.DataFrame(rows).astype(float).drop_duplicates("timestamp").sort_values("timestamp")
    d = d[(d["timestamp"] >= START) & (d["timestamp"] < END) & (d["close"] > 0)]
    d.to_csv(CACHE, index=False)
    return d


def grid(o, h, l, c):
    """Основная сетка 0.6/1.4 на часовых свечах → капитал и позиция BTC на закрытии каждого часа."""
    g, tp, usd, mx = 0.006, 0.014, 82.0, 50
    lots, ref, real, fee, prev = [], None, 0.0, 0.0, None
    eq, q = np.zeros(len(c)), np.zeros(len(c))
    for i in range(len(c)):
        up = c[i] >= o[i]
        for p in (o[i], l[i] if up else h[i], h[i] if up else l[i], c[i]):
            pp, prev = prev, p
            while lots and p >= lots[-1][1]:
                e, t, qq = lots.pop()
                real += qq * (t - e)
                fee += qq * t * MAKER
            ref = lots[-1][0] if lots else (p if ref is None else max(ref, p))
            lvl = ref * (1 - g)
            if p <= lvl and len(lots) < mx:
                px = lvl if (pp is not None and pp > lvl) else p
                lots.append([px, px * (1 + tp), usd / px])
                fee += usd * MAKER
        Q = sum(x[2] for x in lots)
        eq[i] = real - fee + sum(x[2] * (c[i] - x[0]) for x in lots)
        q[i] = Q
    return eq, q


def main():
    d = fetch()
    t = d["timestamp"].to_numpy(np.int64) + 3600              # метка — закрытие часа (как у движка)
    o, h, l, c = (d[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    print(f"Bitstamp часов {len(t)}: {pd.to_datetime(t[0], unit='s'):%Y-%m-%d} … {pd.to_datetime(t[-1], unit='s'):%Y-%m-%d}")
    a, lay = lines.build(t, o, h, l, c, i0_t=int(t[0]))
    ev, _ = en.simulate(a, lay)
    T = np.asarray(a["t"], dtype=np.int64)
    C = np.asarray(a["c"], dtype=float)
    idx = {int(x): i for i, x in enumerate(T)}
    eq, Q = grid(np.asarray(a["o"], float), np.asarray(a["h"], float), np.asarray(a["l"], float), C)
    n = len(T)
    shorts, longs, cur = [], [], None
    for e in ev:
        i = idx.get(int(e["t"]))
        if i is None:
            continue
        if e["side"] == 1 and e["kind"] == "вход":
            longs.append(i)
        if e["side"] != -1 or e["tag"] not in ("под синей", "под жёлтой"):
            continue
        if e["kind"] == "вход":
            cur = [i, None, None]
        elif e["kind"] == "добор" and cur:
            cur[1] = i
        elif e["kind"] == "выход" and cur:
            cur[2] = i
            shorts.append(tuple(cur))
            cur = None
    longs = np.array(sorted(longs))
    t0 = int(np.searchsorted(T, 1420070400))                 # 2015-01-01: прогрев линий и сетки
    print(f"шортов системы {len(shorts)}, входов в лонг {len(longs)}; оценка с {pd.to_datetime(T[t0], unit='s'):%Y-%m-%d}")

    def hedge(hold):
        hq, cost = np.zeros(n + 1), np.zeros(n + 1)
        trades = []
        for a_, b_, x in shorts:
            if hold:
                j = int(np.searchsorted(longs, x))
                x = int(longs[j]) if j < len(longs) else n - 1
            trades.append((a_, b_, max(x, a_ + 1)))
        trades.sort()
        merged = []
        for tr in trades:
            if merged and tr[0] < merged[-1][2]:
                merged[-1] = (merged[-1][0], merged[-1][1], max(merged[-1][2], tr[2]))
            else:
                merged.append(tr)
        for a_, b_, x in merged:
            base = Q[a_] * C[a_]
            for i0 in (a_, b_):
                if i0 is None or i0 >= x:
                    continue
                qq = 0.5 * base / C[i0]
                hq[i0] += qq
                hq[x] -= qq
                cost[i0] += qq * C[i0] * SC
                cost[x] += qq * C[x] * SC
        hq = np.cumsum(hq)[:n]
        pnl = np.zeros(n)
        pnl[1:] = -hq[:-1] * (C[1:] - C[:-1])
        return eq + np.cumsum(pnl) - np.cumsum(cost[:n]), hq

    def dd(x):
        return float(np.min(x - np.maximum.accumulate(x)))

    def liq(tot, gross, dep):
        hits = cnt = 0
        st = t0
        while True:
            end = int(np.searchsorted(T, T[st] + 365 * 86400, side="right"))
            if end >= n:
                break
            cnt += 1
            w = tot[st:end] - tot[st] + dep
            hits += bool(np.any(w <= MM * gross[st:end]))
            st = int(np.searchsorted(T, T[st] + 86400))
        return hits / max(cnt, 1)

    res = {"сетка": (eq, np.zeros(n)), "A": hedge(False), "D": hedge(True)}
    print("\nвариант | итог с 2015 | просадка | в шорте | ликвидация за год $1 000 / $2 000")
    for k, (tot, hq) in res.items():
        seg = tot[t0:] - tot[t0]
        gross = Q * C + hq * C
        print(f"{k:5s} | {seg[-1]:+8,.0f} | {dd(tot[t0:]):+8,.0f} | {(hq[t0:] > 0).mean():4.0%} | "
              f"{liq(tot, gross, 1000) * 100:3.0f}% / {liq(tot, gross, 2000) * 100:3.0f}%")
    years = pd.to_datetime(T, unit="s").year
    print("\nпо годам: прибавка A / D к сетке · просадка года сетка / A / D")
    for y in sorted(set(years[t0:])):
        m = np.flatnonzero(years == y)
        lo, hi = m[0], m[-1]
        ga = (res["A"][0][hi] - res["A"][0][lo]) - (eq[hi] - eq[lo])
        gd = (res["D"][0][hi] - res["D"][0][lo]) - (eq[hi] - eq[lo])
        print(f"  {y}: {ga:+7,.0f} / {gd:+7,.0f} · {dd(eq[lo:hi + 1]):+7,.0f} / {dd(res['A'][0][lo:hi + 1]):+7,.0f} / {dd(res['D'][0][lo:hi + 1]):+7,.0f}")


if __name__ == "__main__":
    main()
