"""Расширение трендового бота (10.10): какие ещё монеты проходят те же проверки, что ETH/XRP 28.07.

Правила tools/trend_state: вход — закрытие 4ч за экстремумом LB баров при ADX(14) ≥ 20, выход — закрытие за
Chandelier (пик ± K·ATR14). Комиссия 0.1% за круг. Данные — Binance spot 4ч, 2 года.
Критерии отбора (как у ETH/XRP): (1) ВСЕ 16 ячеек LB∈{20,30,45,60} × K∈{2,2.5,3,4} в плюсе; (2) базовая
ячейка LB30/K3 в плюсе в ОБОИХ годах; (3) PF базовой ≥ 1.2; (4) сделок базовой ≥ 30.
Контроли: ETH, XRP (должны пройти), BTC (не должен)."""
import json
import sys
import time
import urllib.request
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.trend_state import _adx, _atr  # noqa: E402

DATA = Path(__file__).with_name("data")
DATA.mkdir(exist_ok=True)
COINS = ["ETHUSDT", "XRPUSDT", "BTCUSDT", "SOLUSDT", "BNBUSDT", "DOGEUSDT", "ADAUSDT", "LINKUSDT", "AVAXUSDT",
         "DOTUSDT", "LTCUSDT", "TRXUSDT", "AAVEUSDT", "UNIUSDT", "NEARUSDT", "SUIUSDT", "APTUSDT", "ARBUSDT",
         "INJUSDT"]
LBS = [20, 30, 45, 60]
KS = [2.0, 2.5, 3.0, 4.0]
FEE = 0.1


def load(sym: str) -> pd.DataFrame:
    p = DATA / f"{sym}_4h.csv"
    if not p.exists():
        end = int(time.time() * 1000)
        start = end - 730 * 86_400_000
        rows = []
        while start < end:
            url = f"https://api.binance.com/api/v3/klines?symbol={sym}&interval=4h&limit=1000&startTime={start}"
            chunk = json.loads(urllib.request.urlopen(url, timeout=30).read())
            if not chunk:
                break
            rows += [[k[0], float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])] for k in chunk]
            start = chunk[-1][0] + 4 * 3_600_000
            time.sleep(0.1)
        pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"]).to_csv(p, index=False)
    d = pd.read_csv(p)
    d["dt"] = pd.to_datetime(d["ts"], unit="ms", utc=True)
    return d.set_index("dt").iloc[:-1]                        # последний бар может формироваться


def backtest(d: pd.DataFrame, lb: int, k: float) -> pd.DataFrame:
    d = d.copy()
    d["atr"] = _atr(d)
    d["adx"], _, _ = _adx(d)
    d["hh"] = d["high"].rolling(lb).max().shift(1)
    d["ll"] = d["low"].rolling(lb).min().shift(1)
    d = d.dropna()
    hi, lo, cl, atr, adx, hh, ll = (d[c].to_numpy() for c in ("high", "low", "close", "atr", "adx", "hh", "ll"))
    idx = d.index
    trades, pos = [], None
    for i in range(len(d)):
        if pos is None:
            if cl[i] > hh[i] and adx[i] >= 20:
                pos = [1, cl[i], hi[i], idx[i]]
            elif cl[i] < ll[i] and adx[i] >= 20:
                pos = [-1, cl[i], lo[i], idx[i]]
            continue
        s, e, pk, t0 = pos
        pk = max(pk, hi[i]) if s > 0 else min(pk, lo[i])
        pos[2] = pk
        stop = pk - k * atr[i] if s > 0 else pk + k * atr[i]
        if (s > 0 and cl[i] < stop) or (s < 0 and cl[i] > stop):
            trades.append((t0, s, s * (cl[i] / e - 1) * 100 - FEE))
            pos = None
    return pd.DataFrame(trades, columns=["ts", "side", "pnl"])


def scan(sym: str):
    try:
        d = load(sym)
    except Exception as exc:                                  # noqa: BLE001
        return sym, None, str(exc)
    grid = {}
    for lb in LBS:
        for k in KS:
            t = backtest(d, lb, k)
            grid[(lb, k)] = t["pnl"].sum() if len(t) else 0.0
    base = backtest(d, 30, 3.0)
    mid = d.index[0] + (d.index[-1] - d.index[0]) / 2
    y1 = base[base["ts"] < mid]["pnl"].sum()
    y2 = base[base["ts"] >= mid]["pnl"].sum()
    w, l_ = base["pnl"][base["pnl"] > 0], base["pnl"][base["pnl"] <= 0]
    pf = w.sum() / -l_.sum() if l_.sum() else float("inf")
    res = {"cells_pos": sum(1 for v in grid.values() if v > 0), "cells_min": min(grid.values()),
           "cells_max": max(grid.values()), "base": base["pnl"].sum(), "n": len(base), "pf": pf, "y1": y1, "y2": y2,
           "long": base[base["side"] > 0]["pnl"].sum(), "short": base[base["side"] < 0]["pnl"].sum(),
           "move": (d["close"].iloc[-1] / d["close"].iloc[0] - 1) * 100}
    res["pass"] = res["cells_pos"] == 16 and y1 > 0 and y2 > 0 and pf >= 1.2 and len(base) >= 30
    return sym, res, None


if __name__ == "__main__":
    with ProcessPoolExecutor(max_workers=4) as ex:
        out = list(ex.map(scan, COINS))
    print(f"{'монета':<9} | {'ячеек+':>6} {'мин':>6} {'макс':>6} | {'база':>6} {'PF':>5} {'N':>3} {'1-й г':>6} {'2-й г':>6} | "
          f"{'лонг':>6} {'шорт':>6} | {'цена 2г':>7} | итог")
    for sym, r, err in sorted(out, key=lambda x: -(x[1] or {}).get("base", -1e9)):
        if r is None:
            print(f"{sym:<9} | ошибка данных: {err[:60]}")
            continue
        print(f"{sym:<9} | {r['cells_pos']:>4}/16 {r['cells_min']:>+6.0f} {r['cells_max']:>+6.0f} | {r['base']:>+6.0f} "
              f"{r['pf']:>5.2f} {r['n']:>3} {r['y1']:>+6.0f} {r['y2']:>+6.0f} | {r['long']:>+6.0f} {r['short']:>+6.0f} | "
              f"{r['move']:>+6.0f}% | {'✅ ПРОШЛА' if r['pass'] else '—'}")
