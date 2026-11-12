"""Лимитка с догоном против рыночного — по НАСТОЯЩЕМУ стакану и сделкам WEEX BTCUSDT (state/weex_book, 02–12.11.2026).
Вопрос 4 разбора GPT aadc2a4: замер на минутах Binance spot не знает очереди; здесь — очередь и сделки той же площадки.

На каждом закрытии часа (и отдельно 4ч), обе стороны, объём 0.007 BTC (~$500):
  MKT    — рыночный через 1 с после закрытия по лучшей цене стакана (объём ≪ уровня), тейкер 0.048%;
  CHASE  — post-only на свою лучшую цену через 1 с, в КОНЕЦ очереди (впереди весь объём уровня). Очередь двигают только
           сделки агрессора по этой цене (отмены чужих заявок не засчитываются — консервативно); цена прошла сквозь
           уровень — исполнено. Лучшая цена ушла — через 20 с перестановка в конец новой очереди. 300 с — рыночный;
  PO300  — post-only один раз, без перестановок, 300 с — рыночный.
Издержка — б.п. от середины стакана на закрытии часа (плюс — хуже), с комиссией (мейкер 0.016%, тейкер 0.048%).
Запуск: book_tactics.py [каталог weex_book]"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

D = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/Users/alexeychechikov/code/bot7/state/weex_book")
MAKER, TAKER = 1.6, 4.8      # б.п.
LAT, REPRICE, WAIT = 1000, 20_000, 300_000  # мс
Q = 0.007


def load(day: str):
    b = pd.read_csv(D / f"BTCUSDT_{day}_book.csv")
    tr = pd.read_csv(D / f"BTCUSDT_{day}_trades2.csv", usecols=["T", "p", "q", "m_raw"])
    tr["sell_aggr"] = tr["m_raw"].astype(str).str.lower().eq("true")   # isBuyerMaker = агрессор продавец
    return b.sort_values("E").reset_index(drop=True), tr.sort_values("T").reset_index(drop=True)


def book_at(b, t):
    i = int(np.searchsorted(b["E"].to_numpy(), t, side="right")) - 1
    return None if i < 0 else b.iloc[i]


def run_limit(b, tr, t0, side, reprice: bool):
    """→ (цена, мейкер?, мс ожидания)."""
    t_place = t0 + LAT
    s = book_at(b, t_place)
    if s is None:
        return None
    P, queue = (s["b1"], s["b1q"]) if side > 0 else (s["a1"], s["a1q"])
    T, p, q, sa = tr["T"].to_numpy(), tr["p"].to_numpy(), tr["q"].to_numpy(), tr["sell_aggr"].to_numpy()
    i = int(np.searchsorted(T, t_place, side="right"))
    next_check = t_place + REPRICE
    while i < len(T) and T[i] < t0 + WAIT:
        if reprice and T[i] >= next_check:
            s = book_at(b, next_check)
            best = s["b1"] if side > 0 else s["a1"]
            if (side > 0 and best > P) or (side < 0 and best < P):
                P, queue = (s["b1"], s["b1q"]) if side > 0 else (s["a1"], s["a1q"])
                t_place = next_check
                i = int(np.searchsorted(T, t_place, side="right"))
            next_check += REPRICE
            continue
        if side > 0:
            if p[i] < P - 1e-9:
                return P, True, T[i] - t0
            if abs(p[i] - P) < 1e-9 and sa[i]:
                queue -= q[i]
        else:
            if p[i] > P + 1e-9:
                return P, True, T[i] - t0
            if abs(p[i] - P) < 1e-9 and not sa[i]:
                queue -= q[i]
        if queue < -Q / 2:
            return P, True, T[i] - t0
        i += 1
    s = book_at(b, t0 + WAIT)
    return (s["a1"] if side > 0 else s["b1"]), False, WAIT


def main():
    days = sorted({p.name.split("_")[1] for p in D.glob("BTCUSDT_*_book.csv")})
    rows = []
    for day in days:
        try:
            b, tr = load(day)
        except Exception as e:  # noqa: BLE001
            print(day, "пропуск", e)
            continue
        h0 = int(b["E"].iloc[0] // 3_600_000 + 1) * 3_600_000
        for t0 in range(h0, int(b["E"].iloc[-1]) - WAIT, 3_600_000):
            s0 = book_at(b, t0)
            if s0 is None or book_at(b, t0 + WAIT) is None:
                continue
            mid = (s0["b1"] + s0["a1"]) / 2
            sm = book_at(b, t0 + LAT)
            for side in (1, -1):
                mk = sm["a1"] if side > 0 else sm["b1"]
                r = {"t": t0, "h4": (t0 // 1000) % 14400 == 0, "side": side, "MKT": side * (mk / mid - 1) * 1e4 + TAKER}
                for name, rp in (("CHASE", True), ("PO300", False)):
                    out = run_limit(b, tr, t0, side, rp)
                    if out is None:
                        break
                    px, maker, wait = out
                    r[name] = side * (px / mid - 1) * 1e4 + (MAKER if maker else TAKER)
                    r[name + "_fill"] = maker
                    r[name + "_wait"] = wait / 1000
                rows.append(r)
        print(day, "всего исполнений", len(rows), flush=True)
    df = pd.DataFrame(rows).dropna()
    for lab, m in (("все закрытия часа", np.ones(len(df), bool)), ("закрытия 4ч", df["h4"].to_numpy())):
        x = df[m]
        print(f"\n=== {lab}: {len(x)} исполнений (обе стороны), {x['t'].min() // 86_400_000 * 86_400_000 if len(x) else 0} ===")
        for name in ("MKT", "CHASE", "PO300"):
            v = x[name]
            line = f"{name:6s}: издержка медиана {v.median():+.2f} б.п., средняя {v.mean():+.2f} ± {v.std() / np.sqrt(len(v)):.2f}"
            if name != "MKT":
                line += f", лимиткой {x[name + '_fill'].mean() * 100:.0f}%, ожидание медиана {x[name + '_wait'].median():.0f} с"
            print(line)
        d = x["MKT"] - x["CHASE"]
        print(f"CHASE лучше MKT на {d.mean():+.2f} ± {d.std() / np.sqrt(len(d)):.2f} б.п. за исполнение "
              f"(≈ ${d.mean() / 1e4 * 1000 * 0.75:.3f} на исполнение при среднем лоте $750; за 2 года ~290 исполнений: ${d.mean() / 1e4 * 750 * 290:.0f})")


if __name__ == "__main__":
    main()
