"""Шаг 2б (14.11): шорт системы поверх ВСЕХ сеток счёта — BTC и ETH вместе (grid_hourly2.npz из grid_sim2.py).

ПРАВИЛА (записаны до прогона, как overlay.py / control.py / equal_risk.py):
- Страховка — шорт BTC, пока система в шорте (теги «под синей», «под жёлтой»): на входе системы k × 0.5 × база, на
  доборе ещё k × 0.5 × база, выход — выход системы. Вход — по закрытию часа события (событие помечено закрытием часа;
  страховка держится с этого часа). Издержка 0.068% на сторону, фандинг страховки не считается (обычно шорт получает).
- База: «BTC» — позиция BTC-сеток в BTC; «всё» — позиция BTC-сеток + позиция ETH-сетки в пересчёте на BTC по цене часа
  (ETH прикрывается шортом BTC — система только по BTC).
- Масштаб сеток s ∈ {1, 0.5}: капитал и позиции ×s, страховка — от уменьшенной позиции.
- Ликвидация: старт каждый день, горизонт год; ликвидация — депозит + PnL с даты старта ≤ 0.5% ВАЛОВОГО номинала (лонги
  BTC + лонг ETH + шорт страховки: на бирже поддерживающая маржа берётся с каждой позиции, в хедж-режиме тоже).
  Депозиты $1 200, $3 200, $5 000 (сценарии).
- Окна: вся история; старты 11.2022–11.2025 (годовые окна внутри последних ~4 лет); старты 11.2023–11.2025.
- Контроль: те же сделки системы, круговой сдвиг ≥30 сут, 999 сдвигов, ранг (k+1)/(n+1).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
EV = HERE / "ev.json"           # dump_signals.py: события системы на 13.11
SC = 0.00068
MM = 0.005
H = 365 * 24

z = np.load(HERE / "grid_hourly2.npz")
T, CB, CE = z["t"], z["cb"], z["ce"]
EQB, EQE, QB, QE = z["eqb"], z["eqe"], z["qb"], z["qe"]
EQ = EQB + EQE
n = len(T)
pos_of_t = {int(x): i for i, x in enumerate(T)}
mid = n // 2
y3 = int(np.searchsorted(T, T[-1] - 3 * 365 * 86400))
y2 = int(np.searchsorted(T, T[-1] - 2 * 365 * 86400))


def trades_of(tags=("под синей", "под жёлтой")):
    ev = json.load(open(EV, encoding="utf-8"))
    out, cur = [], None
    for e in ev:
        if e.get("side") != -1 or e.get("tag") not in tags:
            continue
        i = pos_of_t.get(int(e["t"]))
        if i is None:
            continue
        if e["kind"] == "вход":
            cur = [i, None, None]
        elif e["kind"] == "добор" and cur:
            cur[1] = i
        elif e["kind"] == "выход" and cur:
            cur[2] = i
            out.append(tuple(cur))
            cur = None
    if cur:
        out.append((cur[0], cur[1], n - 1))
    return out


TR = trades_of()
BASE = {"BTC": QB, "всё": QB + QE * CE / CB}


def hedge(k, base, s=1.0, shift=0):
    """Объём шорта страховки по часам (BTC ≥ 0) и накопленные издержки."""
    hq = np.zeros(n + 1)
    cost = np.zeros(n)
    if k:
        for a, b, x in TR:
            a2, b2, x2 = a + shift, (None if b is None else b + shift), x + shift
            if shift:
                a2, x2 = a2 % n, x2 % n
                b2 = None if b2 is None else b2 % n
                if x2 <= a2 or (b2 is not None and not a2 <= b2 <= x2):
                    continue
            for i0 in (a2, b2):
                if i0 is None:
                    continue
                q = k * 0.5 * s * BASE[base][i0]
                hq[i0] += q
                hq[x2] -= q
                cost[i0] += q * CB[i0] * SC
                cost[x2] += q * CB[x2] * SC
    hq = np.cumsum(hq)[:n]
    return hq, np.cumsum(cost)


def total(k, base, s=1.0, shift=0):
    hq, cc = hedge(k, base, s, shift)
    pnl = np.zeros(n)
    pnl[1:] = -hq[:-1] * (CB[1:] - CB[:-1])
    return s * EQ + np.cumsum(pnl) - cc, hq


def dd(x):
    return float(np.min(x - np.maximum.accumulate(x)))


def gross(hq, s):
    return s * (QB * CB + QE * CE) + hq * CB


def liq(tot, gr, dep, lo, hi):
    hits, rets = 0, []
    for st in range(lo, min(hi, n - H), 24):
        w = tot[st:st + H] - tot[st] + dep
        if np.any(w <= MM * gr[st:st + H]):
            hits += 1
            rets.append(-dep)
        else:
            rets.append(tot[st + H - 1] - tot[st])
    r = np.array(rets)
    return hits / len(r), float(np.median(r)), float(np.percentile(r, 10)), len(r)


def main():
    print(f"часов {n}: {pd.to_datetime(T[0], unit='s'):%Y-%m-%d} … {pd.to_datetime(T[-1], unit='s'):%Y-%m-%d %H:%M}; "
          f"половины с {pd.to_datetime(T[mid], unit='s'):%Y-%m-%d}; 3 года с {pd.to_datetime(T[y3], unit='s'):%Y-%m-%d}; "
          f"2 года с {pd.to_datetime(T[y2], unit='s'):%Y-%m-%d}; шортов системы {len(TR)}")
    print(f"сетки отдельно: BTC итог {EQB[-1]:+,.0f} (просадка {dd(EQB):+,.0f}), ETH итог {EQE[-1]:+,.0f} "
          f"(просадка {dd(EQE):+,.0f}), вместе {EQ[-1]:+,.0f} (просадка {dd(EQ):+,.0f})")
    print("\nвариант | итог | просадка | 1-я половина (просадка) | 2-я половина (просадка) | 3 года (просадка) | 2 года (просадка)")
    variants = [("сетки без страховки", 0, "BTC"), ("страховка от BTC k=0.5", 0.5, "BTC"),
                ("страховка от BTC k=1", 1.0, "BTC"), ("страховка от всего k=0.5", 0.5, "всё"),
                ("страховка от всего k=1", 1.0, "всё")]
    for name, k, base in variants:
        tot, _ = total(k, base)
        parts = []
        for lo, hi in ((0, mid), (mid, n - 1), (y3, n - 1), (y2, n - 1)):
            parts.append(f"{tot[hi] - tot[lo]:+8,.0f} ({dd(tot[lo:hi + 1]):+,.0f})")
        print(f"{name:26s} | {tot[-1]:+9,.0f} | {dd(tot):+8,.0f} | " + " | ".join(parts))

    # худшие эпизоды вместе — что делала страховка
    x = EQ
    under = x - np.maximum.accumulate(x)
    used = np.zeros(n, bool)
    tot_a, hq_a = total(0.5, "всё")
    print("\nхудшие просадки сеток BTC+ETH и страховка «от всего» k=0.5 за эпизод:")
    for _ in range(6):
        m = np.where(used, 0, under)
        j = int(np.argmin(m))
        if m[j] >= -100:
            break
        pk = np.maximum.accumulate(x)[j]
        p = int(np.flatnonzero(x[:j + 1] >= pk - 1e-9)[-1])
        r = j + int(np.argmax(x[j:] >= pk)) if np.any(x[j:] >= pk) else n - 1
        used[p:r + 1] = True
        print(f"  {pd.to_datetime(T[p], unit='s'):%Y-%m-%d} → дно {pd.to_datetime(T[j], unit='s'):%Y-%m-%d}: сетки "
              f"{x[j] - x[p]:+,.0f}$ (BTC {CB[p]:,.0f}→{CB[j]:,.0f}, ETH {CE[p]:,.0f}→{CE[j]:,.0f}) · система в шорте "
              f"{(hq_a[p:j + 1] > 0).mean():.0%} часов · страховка {(tot_a[j] - tot_a[p]) - (x[j] - x[p]):+,.0f}$")

    print("\nшанс ликвидации за год · медиана года · худшие 10% лет (старт каждый день)")
    lo3 = int(np.searchsorted(T, T[-1] - 4 * 365 * 86400))
    lo2 = int(np.searchsorted(T, T[-1] - 3 * 365 * 86400))
    windows = (("вся история", 0), (f"старты {pd.to_datetime(T[lo3], unit='s'):%m.%Y}–{pd.to_datetime(T[n - H], unit='s'):%m.%Y}", lo3),
               (f"старты {pd.to_datetime(T[lo2], unit='s'):%m.%Y}–{pd.to_datetime(T[n - H], unit='s'):%m.%Y}", lo2))
    for s in (1.0, 0.5):
        for dep in (1200, 3200, 5000):
            print(f"\nсетки ×{s:g}, депозит ${dep:,}:")
            for name, k, base in variants:
                tot, hq = total(k, base, s)
                gr = gross(hq, s)
                cells = []
                for wl, lo in windows:
                    p, med, p10, cnt = liq(tot, gr, dep, lo, n)
                    cells.append(f"{wl}: {p * 100:3.0f}% · {med:+7,.0f} · {p10:+7,.0f}")
                print(f"  {name:26s} " + " | ".join(cells))

    print("\nконтроль: те же сделки системы, сдвиг по времени (999), страховка от всего, сетки ×1")
    rng = np.random.default_rng(20261114)
    shifts = rng.integers(30 * 24, n - 30 * 24, 999)
    for k in (0.5, 1.0):
        real, _ = total(k, "всё")

        def met(tt):
            return {"итог": tt[-1] - EQ[-1], "просадка": dd(tt) - dd(EQ),
                    "3 года итог": (tt[-1] - tt[y3]) - (EQ[-1] - EQ[y3]), "3 года просадка": dd(tt[y3:]) - dd(EQ[y3:]),
                    "2 года итог": (tt[-1] - tt[y2]) - (EQ[-1] - EQ[y2]), "2 года просадка": dd(tt[y2:]) - dd(EQ[y2:])}
        m = met(real)
        ctrl = [met(total(k, "всё", 1.0, int(sh))[0]) for sh in shifts]
        print(f"k={k}:")
        for key, v in m.items():
            arr = np.array([c[key] for c in ctrl])
            rank = (np.sum(arr >= v) + 1) / (len(arr) + 1)
            print(f"   {key:16s} {v:+9,.0f}$ · случайные: медиана {np.median(arr):+9,.0f}$ · ранг {rank:.3f}")


if __name__ == "__main__":
    main()
