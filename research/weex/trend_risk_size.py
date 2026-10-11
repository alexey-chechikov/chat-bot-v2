"""Риск на сделку трендового бота WEEX ($33 → $50–70?, вопрос оператора 11.10).

Правила как в tools/trend_state: вход — закрытие 4ч за экстремумом 30 баров при ADX(14) ≥ 20, выход — закрытие за
Chandelier (пик ∓ 3·ATR14). Размер как в services/weex_trend: qty = риск / расстояние до стопа на входе, но
нотионал не больше потолка. Комиссия 0.1% за круг. Данные — Binance 4ч, 2 года (research/trend_expand/data).
ETH и XRP торгуются одновременно: капитал в $ по моментам выхода. Считаем итог, последний год, худшую просадку
и худшую серию убытков в $ для риска 33/50/70 и потолка 1500/3000."""
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
                stop = pk - s * k * atr[i]
                pos = [s, cl[i], pk, d.index[i], abs(cl[i] - stop) / cl[i] * 100]
            continue
        s, e, pk, t0, sd = pos
        pk = max(pk, hi[i]) if s > 0 else min(pk, lo[i])
        pos[2] = pk
        stop = pk - s * k * atr[i]
        if (s > 0 and cl[i] < stop) or (s < 0 and cl[i] > stop):
            out.append({"sym": sym, "t0": t0, "t1": d.index[i], "pnl": s * (cl[i] / e - 1) * 100 - FEE, "sd": sd})
            pos = None
    return pd.DataFrame(out)


def main():
    t = pd.concat([trades("ETHUSDT"), trades("XRPUSDT")]).sort_values("t1").reset_index(drop=True)
    year = t["t1"] >= t["t1"].max() - pd.Timedelta(days=365)
    print(f"сделок {len(t)} (ETH {sum(t.sym == 'ETHUSDT')}, XRP {sum(t.sym == 'XRPUSDT')}), стоп на входе: медиана "
          f"{t.sd.median():.1f}%, 10–90% {t.sd.quantile(0.1):.1f}–{t.sd.quantile(0.9):.1f}%; в плюсе {(t.pnl > 0).mean():.0%}")
    print(f"{'риск':>5} {'потолок':>7} | {'нотионал медиана':>16} {'упёрлось':>8} | {'2 года':>7} {'посл. год':>9} | "
          f"{'худшая просадка':>15} {'худшая серия':>12} {'худшая сделка':>13}")
    for risk in (33, 50, 70):
        for cap in (1500, 3000):
            notional = np.minimum(risk / (t.sd / 100), cap)
            usd = notional * t.pnl / 100
            eq = usd.cumsum()
            dd = (eq - eq.cummax()).min()
            streak, worst_streak = 0.0, 0.0
            for x in usd:
                streak = streak + x if x < 0 else 0.0
                worst_streak = min(worst_streak, streak)
            print(f"{risk:>5} {cap:>7} | {notional.median():>16,.0f} {(notional >= cap).mean():>8.0%} | {usd.sum():>+7.0f} "
                  f"{usd[year].sum():>+9.0f} | {dd:>+15.0f} {worst_streak:>+12.0f} {usd.min():>+13.0f}")


if __name__ == "__main__":
    main()
