"""Шаг 3 (14.11, «что ещё усилить, пока ждём GPT»): варианты страховки поверх BTC+ETH-сеток (grid_hourly2.npz), те же
шорты системы (ev.json), база «всё» (лонги BTC + ETH в $).

ПРАВИЛА (до прогона):
- A «как исследование»: вход k·0.5·база на часе входа, добор k·0.5·база на часе добора, выход на выходе системы,
  0.068%/сторону, фандинг не считается.
- B «как исполнитель»: добор тоже от базы на часе ВХОДА (исполнитель ставит стоп добора заранее).
- C = B + фандинг: шорт получает ставку Binance × номинал в каждый расчёт (ставка > 0 — шорт получает, < 0 — платит).
- D = C + аварийный стоп исполнителя: закрытие часа выше средней входа на 12% → страховка закрыта до конца эпизода
  (по закрытию часа — внутри часа стоп сработал бы раньше и лучше/хуже на ход часа; это оценка).
- k ∈ {0.25, 0.5, 0.75, 1.0, 1.25, 1.5} для C — соседние ячейки (ворота плоской поверхности).
Метрики: итог, просадка, 2-я половина, 3 года, 2 года — всё вместе с сетками; плюс итог самой страховки."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
NPZ = next(p for p in (HERE / "grid_hourly2.npz", Path("/Users/alexeychechikov/code/bot7/research/grid_hedge_20261114/grid_hourly2.npz"))
           if p.exists())
FUND = Path("/Users/alexeychechikov/code/bot7/backtests/frozen/BTCUSDT_funding_full.csv")
SC = 0.00068
z = np.load(NPZ)
T, CB, CE = z["t"], z["cb"], z["ce"]
EQ = z["eqb"] + z["eqe"]
BASE = z["qb"] * CB + z["qe"] * CE                  # лонги BTC + ETH в $
n = len(T)
class _Rows:
    """Событие с меткой t (закрытие часа) → строка часа, закончившегося не позже t; пропуск ряда > 3 ч — None
    (разбор ead2ca4: точное равенство меток теряло события на пропусках, метка начала часа брала будущий час)."""

    def __init__(self, T):
        self.T = T

    def get(self, t, default=None):
        i = int(np.searchsorted(self.T, int(t), side="right")) - 1
        return i if i >= 0 and int(t) - int(self.T[i]) <= 3 * 3600 else default


pos_of_t = _Rows(T)
mid, y3, y2 = n // 2, int(np.searchsorted(T, T[-1] - 3 * 365 * 86400)), int(np.searchsorted(T, T[-1] - 2 * 365 * 86400))

fr = pd.read_csv(FUND)
ft = fr["fundingTime"].to_numpy(np.int64) // 1000
FR = np.zeros(n)                                    # ставка, отнесённая к часу, в котором расчёт
idx = np.searchsorted(T, ft, side="right") - 1
ok = (idx >= 0) & (ft < T[-1] + 3600)
np.add.at(FR, idx[ok], fr["fundingRate"].to_numpy(float)[ok])


def trades():
    ev = json.load(open(HERE / "ev.json", encoding="utf-8"))
    out, cur = [], None
    for e in ev:
        if e.get("side") != -1 or e.get("tag") not in ("под синей", "под жёлтой"):
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


TR = trades()


def hedge_pnl(k, add_at_entry=True, funding=False, stop_pct=None, cap_base=False):
    """Почасовой PnL страховки (накопленный) и объём шорта по часам. cap_base (E, разбор ead2ca4 «предел отношения шорта
    к текущей позиции»): каждый час шорт не больше k × текущие лонги / цена — лонги закрылись тейками → страховка
    урезается рыночным (издержка на урезанное), обратно не наращивается до следующего входа/добора системы."""
    pnl = np.zeros(n)
    hq_all = np.zeros(n)
    stops = 0
    for a, b, x in TR:
        legs = [(a, k * 0.5 * BASE[a] / CB[a])]
        if b is not None:
            legs.append((b, k * 0.5 * (BASE[a] if add_at_entry else BASE[b]) / CB[b]))
        hq = np.zeros(n)
        cost = np.zeros(n)
        for i0, q in legs:
            hq[i0:x] += q
            cost[i0] += q * CB[i0] * SC
        if cap_base:
            starts = {i0 for i0, _ in legs}
            cur = 0.0
            for i in range(a, x):
                want = cur + sum(q for i0, q in legs if i0 == i) if i in starts else cur
                lim = k * BASE[i] / CB[i]
                new = min(want, lim)
                if new < want:
                    cost[i] += (want - new) * CB[i] * SC
                cur = new
                hq[i] = cur
        end = x
        if stop_pct:
            for i in range(a, x):
                q = hq[i]
                if q <= 0:
                    continue
                avg = sum(qq * CB[ii] for ii, qq in legs if ii <= i) / sum(qq for ii, qq in legs if ii <= i)
                if CB[i] >= avg * (1 + stop_pct / 100):
                    end = i
                    hq[i:x] = 0
                    stops += 1
                    break
        cost[end] += hq[end - 1] * CB[end] * SC if end > a else 0.0
        step = np.zeros(n)
        step[1:] = -hq[:-1] * (CB[1:] - CB[:-1])
        if funding:
            step += hq * CB * FR                    # ставка > 0 — шорт получает
        pnl += step - cost
        hq_all += hq
    return np.cumsum(pnl), hq_all, stops


def dd(x):
    return float(np.min(x - np.maximum.accumulate(x)))


def row(name, h):
    tot = EQ + h
    parts = " | ".join(f"{tot[-1] - tot[lo]:+8,.0f} ({dd(tot[lo:]):+,.0f})" for lo in (mid, y3, y2))
    return f"{name:44s} | {tot[-1]:+9,.0f} | {dd(tot):+8,.0f} | {parts} | страховка {h[-1]:+8,.0f} (2 г {h[-1] - h[y2]:+,.0f})"


def main():
    print(f"часов {n}, шортов системы {len(TR)}; фандинг: расчётов {int((FR != 0).sum())}, средняя ставка {FR[FR != 0].mean() * 100:.4f}%")
    print("вариант | итог | просадка | 2-я половина (просадка) | 3 года (просадка) | 2 года (просадка) | сама страховка")
    print(row("сетки без страховки", np.zeros(n)))
    for k in (0.5, 1.0):
        a, _, _ = hedge_pnl(k, add_at_entry=False)
        b, _, _ = hedge_pnl(k)
        c, hq, _ = hedge_pnl(k, funding=True)
        d, _, ns = hedge_pnl(k, funding=True, stop_pct=12.0)
        print(row(f"k={k} A как исследование", a))
        print(row(f"k={k} B добор от базы на входе (исполнитель)", b))
        print(row(f"k={k} C = B + фандинг шорта", c))
        print(row(f"k={k} D = C + аварийный стоп 12% ({ns} срабатываний)", d))
        print(f"      фандинг страховки k={k}: {c[-1] - b[-1]:+,.0f}$, за 2 года {(c[-1] - c[y2]) - (b[-1] - b[y2]):+,.0f}$")
        e2, hq_e, _ = hedge_pnl(k, add_at_entry=False, funding=True, cap_base=True)
        print(row(f"k={k} E = A + фандинг, шорт ≤ k × текущие лонги", e2))
        over = hq > k * BASE / CB + 1e-12
        print(f"      без предела: часов, где шорт больше k × лонги, {over.mean():.1%} от всех; "
              f"с пределом страховка {e2[-1] - c[-1]:+,.0f}$ к C, 2 года {(e2[-1] - e2[y2]) - (c[-1] - c[y2]):+,.0f}$")
    print("\nсоседние k (вариант C):")
    for k in (0.25, 0.5, 0.75, 1.0, 1.25, 1.5):
        c, _, _ = hedge_pnl(k, funding=True)
        print(row(f"k={k}", c))


if __name__ == "__main__":
    main()
