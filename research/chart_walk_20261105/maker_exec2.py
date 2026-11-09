"""Два контура исполнения системы BTC по минуткам (оператор 08.11). Записано до прогона:
  вход и выход по правилу: лимитка POST_ONLY по цене закрытия 4ч; исполнена, если в первые k минут цена прошла сквозь неё
  (покупка: low минуты < цены × (1 − m), продажа: high > цены × (1 + m)); иначе по рынку на закрытии k-й минуты;
  k = 1, 3, 5, 15, 60; m = 0 (хоть на тик сквозь), 0.02%, 0.05%;
  цель шорта под жёлтой — тейк лимиткой (мейкер), добор — стоп-ордер (покупка выше цены / продажа ниже) — рынок;
  мейкер 0.016%, рынок 0.068% (тейкер WEEX 0.048% + проскальзывание, как во всём учёте). Без фандинга, вес как в системе."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("/Users/alexeychechikov/code/bot7")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))
import grid_by_system as gs  # noqa: E402
import plus as pl  # noqa: E402
import state_card as sc  # noqa: E402
from services.btc_signals import engine as en  # noqa: E402

TAKER, MAKER = 0.068, 0.016
T25 = 1735689600


def leg(side, p0, p1, f0, f1):
    return side * (p1 / p0 - 1) * 100 - f0 - f1 * (p1 / p0)


class Mins:
    def __init__(self, t0):
        self.ts, self.o, self.h, self.l, self.c = gs.minutes(t0)

    def fill(self, t_close, buy, px, k, m):
        """Лимитка выставлена в t_close (закрытие часа) → (цена, комиссия, исполнена ли, сдвиг рынка за k минут в %)."""
        j = int(np.searchsorted(self.ts, t_close))
        seg = slice(j, j + k)
        if j + k > len(self.ts) or self.ts[j] != t_close:
            return px, TAKER, False, 0.0
        hit = (self.l[seg] < px * (1 - m)).any() if buy else (self.h[seg] > px * (1 + m)).any()
        mk = float(self.c[j + k - 1])
        return (px, MAKER, True, 0.0) if hit else (mk, TAKER, False, (mk / px - 1) * 100 * (1 if buy else -1))


def run(M, ev, k, m):
    tot = t25 = 0.0
    n = fills = 0
    miss_cost = []
    for e in ev:
        if e["kind"] != "выход":
            continue
        p = e["pos"]
        s, w = e["side"], p["w"]
        q0, f0, ok0, d0 = M.fill(p["entry_t"], s == 1, p["entry"], k, m)
        if e["why"].startswith("цель"):
            q1, f1, ok1, d1 = e["px"], MAKER, True, 0.0
        else:
            q1, f1, ok1, d1 = M.fill(e["t"], s == -1, e["px"], k, m)
        n += 2
        fills += ok0 + ok1
        miss_cost += [x for x, ok in ((d0, ok0), (d1, ok1)) if not ok]
        if p["tag"] in en.MAIN:
            v = leg(s, q0, q1, f0, f1) * w * en.FIRST
            if p["add_done"]:
                v += leg(s, p["add_px"], q1, TAKER, f1) * w * en.ADD
        else:
            v = leg(s, q0, q1, f0, f1) * w
        tot += v
        if p["entry_t"] >= T25:
            t25 += v
    return tot, t25, fills / n, (float(np.mean(miss_cost)) if miss_cost else 0.0)


def main():
    a, _, _ = sc.load_coin("BTC")
    ev, _ = en.simulate(a, pl.layer(a))
    M = Mins(int(a["t"][a["i0"]]))
    base, b25 = run(M, ev, 1, 10.0)[:2]  # m = 1000% — лимитка не исполняется никогда, всё по рынку через 1 минуту
    ref = sum(e["res"] for e in ev if e["kind"] == "выход")
    print(f"учёт системы (рынок на закрытии 4ч): {ref:+.1f}; всё по рынку через 1 минуту: {base:+.1f}, с 2025 {b25:+.1f}", flush=True)
    rows = []
    for m in (0.0, 0.0002, 0.0005):
        for k in (1, 3, 5, 15, 60):
            tot, t25, fr, mc = run(M, ev, k, m)
            rows.append({"сквозь, %": m * 100, "ждём, мин": k, "исполнено %": round(fr * 100), "доплата при промахе, %": round(mc, 3), "итог": round(tot, 1), "к рынку": round(tot - base, 1), "с 2025": round(t25, 1), "с 2025 к рынку": round(t25 - b25, 1)})
    print(pd.DataFrame(rows).to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
