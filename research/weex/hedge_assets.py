"""Противовес биткоину (21.10, оператор: «проработать золото, нефть, серебро и что ещё торгуется как противовес и как
отдельный инструмент»). Только данные, без сеток: что делает актив, когда падает BTC.

ПРАВИЛА ДО ПРОГОНА:
- Дневные закрытия по UTC. BTC — frozen 1m Binance spot (копия); золото на 2 года — PAXG (frozen 1m Binance spot);
  серебро XAG, нефть CL, медь COPPER, платина XPT, S&P500 — дневные свечи WEEX (история с листинга: с 01–06.2026).
- Для каждой пары — только общие дни. Метрики: корреляция дневных доходностей; средняя доходность актива в дни, когда
  BTC −3% и хуже; в недели (7 дней подряд, без перекрытия), когда BTC −7% и хуже; доля таких дней/недель, когда
  актив вырос; бета к BTC.
- Противовес = в плохие дни BTC актив в среднем растёт и растёт чаще половины случаев. Иначе — не противовес.
Запуск: hedge_assets.py --btc=<копия BTC 1m> --paxg=<копия PAXG 1m>
"""
from __future__ import annotations

import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, "/Users/alexeychechikov/code/bot7")
from services.weex_api.client import FUTURES, WeexClient  # noqa: E402

ARG = {a.split("=", 1)[0]: a.split("=", 1)[1] for a in sys.argv[1:] if "=" in a}
BTC = ARG.get("--btc", "/Users/alexeychechikov/code/bot7/backtests/frozen/BTCUSDT_1m_2y.csv")
PAXG = ARG.get("--paxg", "/Users/alexeychechikov/code/bot7/backtests/frozen/PAXGUSDT_1m_2y.csv")
WEEX = ("XAGUSDT", "CLUSDT", "COPPERUSDT", "XPTUSDT", "SP500USDT", "XAUUSDT")


def daily_from_1m(path: str) -> pd.Series:
    d = pd.read_csv(path, usecols=["ts", "close"])
    s = pd.Series(d["close"].to_numpy(float), index=pd.to_datetime(d["ts"], unit="ms"))
    day = s.resample("1D").last()
    cnt = s.resample("1D").count()
    return day[cnt == 1440]                       # только полные дни


def daily_weex(sym: str) -> pd.Series:
    r = WeexClient()._http(FUTURES + f"/capi/v3/market/klines?symbol={sym}&interval=1d&limit=1000")
    s = pd.Series([float(x[4]) for x in r], index=pd.to_datetime([int(x[0]) for x in r], unit="ms"))
    return s.sort_index().iloc[:-1]               # последняя свеча дня ещё не закрыта


def stats(name: str, btc: pd.Series, a: pd.Series) -> str:
    j = pd.concat([btc, a], axis=1, keys=["b", "a"]).dropna()
    r = j.pct_change().dropna()
    if len(r) < 30:
        return f"{name:<10} мало общих дней ({len(r)})"
    corr = r["b"].corr(r["a"])
    beta = np.cov(r["a"], r["b"])[0, 1] / r["b"].var()
    bad = r[r["b"] <= -0.03]
    w = j.iloc[::7].pct_change().dropna()
    badw = w[w["b"] <= -0.07]
    return (f"{name:<10} {j.index[0].date()}…{j.index[-1].date()} дней {len(r):4d} | корр {corr:+.2f} бета {beta:+.3f} | "
            f"дни BTC ≤−3%: {len(bad):3d}, актив в среднем {bad['a'].mean() * 100:+.2f}% (BTC {bad['b'].mean() * 100:+.1f}%), "
            f"рос в {(bad['a'] > 0).mean() * 100:3.0f}% | недели BTC ≤−7%: {len(badw):2d}, актив "
            f"{(badw['a'].mean() * 100 if len(badw) else float('nan')):+.2f}%, рос в "
            f"{((badw['a'] > 0).mean() * 100 if len(badw) else float('nan')):3.0f}%")


def main():
    btc = daily_from_1m(BTC)
    print(f"BTC дневных закрытий {len(btc)}: {btc.index[0].date()} … {btc.index[-1].date()}")
    print(stats("PAXG", btc, daily_from_1m(PAXG)))
    for sym in WEEX:
        try:
            print(stats(sym.replace("USDT", ""), btc, daily_weex(sym)))
        except Exception as exc:  # noqa: BLE001
            print(f"{sym}: не прочитано ({str(exc)[:80]})")
        time.sleep(0.5)


if __name__ == "__main__":
    main()
