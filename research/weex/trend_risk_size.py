"""Риск на сделку трендового бота WEEX ($33 → $50–70?, вопрос оператора 11.10).

Правила как в tools/trend_state: вход — закрытие 4ч за экстремумом 30 баров при ADX(14) ≥ 20, выход — закрытие за
Chandelier (пик ∓ 3·ATR14). Размер как в services/weex_trend ПОСЛЕ правки 11.10: qty = риск / (расстояние до
АВАРИЙНОГО стопа на бирже = Chandelier ± 1.5% + тейкер двух ног 0.1%), нотионал не больше потолка. Комиссия
0.1% за круг. Данные — Binance 4ч, 2 года (research/trend_expand/data). ETH и XRP одновременно.

Исправлено по разбору GPT 11.10 (docs/WEEX_GPT_STATE_ANSWERS_2026-10-11.md №11): капитал с нулевого старта,
открытая на конец позиция оценена по последней цене, просадка — по закрытиям 4ч баров с плавающим результатом
открытых сделок (было: только по моментам выхода), «последний год» — от конца данных."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "research" / "trend_expand"))
from tools.trend_state import _adx, _atr  # noqa: E402
from scan import load  # noqa: E402

FEE = 0.1
BUF = 1.5          # аварийный стоп на бирже дальше Chandelier, %


def trades(sym, lb=30, k=3.0):
    d = load(sym).copy()
    d["atr"] = _atr(d)
    d["adx"], _, _ = _adx(d)
    d["hh"] = d["high"].rolling(lb).max().shift(1)
    d["ll"] = d["low"].rolling(lb).min().shift(1)
    d = d.dropna()
    hi, lo, cl, atr, adx, hh, ll = (d[c].to_numpy() for c in ("high", "low", "close", "atr", "adx", "hh", "ll"))
    out, pos = [], None
    for i in range(len(d)):
        if pos is None:
            s = 1 if (cl[i] > hh[i] and adx[i] >= 20) else (-1 if (cl[i] < ll[i] and adx[i] >= 20) else 0)
            if s:
                pk = hi[i] if s > 0 else lo[i]
                hard = (pk - s * k * atr[i]) * (1 - s * BUF / 100)
                pos = {"s": s, "e": cl[i], "pk": pk, "t0": d.index[i], "sd": abs(cl[i] - hard) / cl[i] * 100 + FEE,
                       "path": {}}
            continue
        s, e = pos["s"], pos["e"]
        pos["pk"] = max(pos["pk"], hi[i]) if s > 0 else min(pos["pk"], lo[i])
        stop = pos["pk"] - s * k * atr[i]
        pos["path"][d.index[i]] = s * (cl[i] / e - 1) * 100 - FEE
        if (s > 0 and cl[i] < stop) or (s < 0 and cl[i] > stop):
            out.append({"sym": sym, "t0": pos["t0"], "t1": d.index[i], "pnl": pos["path"][d.index[i]],
                        "sd": pos["sd"], "path": pos["path"], "open": False})
            pos = None
    if pos is not None and pos["path"]:                     # открытая на конец — по последней цене
        last = max(pos["path"])
        out.append({"sym": sym, "t0": pos["t0"], "t1": last, "pnl": pos["path"][last], "sd": pos["sd"],
                    "path": pos["path"], "open": True})
    return out, d.index


def main():
    te, ie = trades("ETHUSDT")
    tx, ix = trades("XRPUSDT")
    t = sorted(te + tx, key=lambda r: r["t1"])
    idx = ie.union(ix)
    end = idx.max()
    year0 = end - pd.Timedelta(days=365)
    pnl = np.array([r["pnl"] for r in t])
    sd = np.array([r["sd"] for r in t])
    print(f"сделок {len(t)} (открытых на конец {sum(r['open'] for r in t)}), стоп до биржевого на входе: медиана "
          f"{np.median(sd):.1f}%, 10–90% {np.quantile(sd, 0.1):.1f}–{np.quantile(sd, 0.9):.1f}%; в плюсе {(pnl > 0).mean():.0%}")
    print(f"{'риск':>5} {'потолок':>7} | {'нотионал мед.':>13} {'упёрлось':>8} | {'2 года':>7} {'посл. год':>9} | "
          f"{'просадка (4ч, с плавающим)':>26} {'худшая сделка':>13}")
    for risk in (33, 50, 70):
        for cap in (1500, 3000):
            notional = np.minimum(risk / (sd / 100), cap)
            eq = pd.Series(0.0, index=idx)
            year = 0.0
            for r, n in zip(t, notional):
                path = pd.Series(r["path"]) * n / 100
                eq = eq.add(path.reindex(idx).ffill().where(idx >= r["t0"], 0.0).fillna(0.0), fill_value=0.0)
                # после выхода результат сделки остаётся в капитале (ffill по индексу уже держит последнее значение)
                if r["t1"] >= year0:
                    before = path[path.index < year0]
                    year += path.iloc[-1] - (before.iloc[-1] if len(before) else 0.0)
            eq = pd.concat([pd.Series([0.0]), eq.reset_index(drop=True)])
            dd = (eq - eq.cummax()).min()
            print(f"{risk:>5} {cap:>7} | {np.median(notional):>13,.0f} {(notional >= cap).mean():>8.0%} | "
                  f"{eq.iloc[-1]:>+7.0f} {year:>+9.0f} | {dd:>+26.0f} {(pnl * notional / 100).min():>+13.0f}")


if __name__ == "__main__":
    main()
