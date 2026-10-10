"""Бэктест правила в духе Bybit TradeGPT (сигнал от 10.10.2026: «разворот формы, за 6 часов объём растёт,
MACD разворачивается → снижается», плечо 5, без стопа и цели).

Перевод в проверяемые условия на 1ч свечах (закрытые бары, вход по открытию следующего):
  MACD  — гистограмма MACD(12,26,9) сменила знак: вниз → SHORT, вверх → LONG;
  ОБЪЁМ — объём последних 6 ч > объёма 6 ч до них × VOL_K;
  РАЗВОРОТ — 12 ч до сигнала цена шла в обратную сторону (для SHORT — росла).
Результат: доход позиции через 1/4/24 ч после входа, комиссия 0.1% за круг (без плеча — плечо не меняет
знак эджа, только размер). Контроль: (1) те же моменты, случайное направление; (2) сигналы, сдвинутые
по времени по кругу. Разрез по времени: старая/свежая половина. Данные — Binance spot, 2 года.
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(__file__).with_name("data")
DATA.mkdir(exist_ok=True)
COINS = ["AAVEUSDT", "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "LINKUSDT", "AVAXUSDT"]
HORIZ = [1, 4, 24]
FEE = 0.1          # % за круг
VOL_K = 1.0


def load(sym: str) -> pd.DataFrame:
    p = DATA / f"{sym}_1h.csv"
    if not p.exists():
        end = int(time.time() * 1000)
        start = end - 730 * 86_400_000
        rows = []
        while start < end:
            url = f"https://api.binance.com/api/v3/klines?symbol={sym}&interval=1h&limit=1000&startTime={start}"
            chunk = json.loads(urllib.request.urlopen(url, timeout=30).read())
            if not chunk:
                break
            rows += [[k[0], float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])] for k in chunk]
            start = chunk[-1][0] + 3_600_000
            time.sleep(0.1)
        pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"]).to_csv(p, index=False)
    d = pd.read_csv(p)
    d["dt"] = pd.to_datetime(d["ts"], unit="ms", utc=True)
    return d.set_index("dt")


def signals(d: pd.DataFrame, use_vol=True, use_rev=True) -> pd.Series:
    """+1 LONG / −1 SHORT / 0 на закрытии бара."""
    c = d["close"]
    macd = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    hist = macd - macd.ewm(span=9, adjust=False).mean()
    up = (hist > 0) & (hist.shift(1) <= 0)
    dn = (hist < 0) & (hist.shift(1) >= 0)
    ok = pd.Series(True, index=d.index)
    if use_vol:
        v6 = d["volume"].rolling(6).sum()
        ok &= v6 > VOL_K * v6.shift(6)
    sig = pd.Series(0, index=d.index)
    rev_up = c.shift(1) < c.shift(13)          # перед сигналом LONG 12 ч падали
    rev_dn = c.shift(1) > c.shift(13)          # перед SHORT 12 ч росли
    sig[up & ok & (rev_up if use_rev else True)] = 1
    sig[dn & ok & (rev_dn if use_rev else True)] = -1
    return sig


def forward(d: pd.DataFrame, h: int) -> pd.Series:
    """Доход позиции LONG с открытия следующего бара до открытия через h баров, %."""
    o = d["open"]
    return (o.shift(-1 - h) / o.shift(-1) - 1) * 100


def stats(x: np.ndarray) -> tuple[float, float, int]:
    x = x[~np.isnan(x)]
    if len(x) < 2:
        return np.nan, np.nan, len(x)
    return x.mean(), x.mean() / (x.std(ddof=1) / np.sqrt(len(x))), len(x)


def main():
    variants = {"MACD+объём+разворот (как TradeGPT)": (True, True), "MACD+объём": (True, False),
                "только MACD": (False, False)}
    rng = np.random.default_rng(5)
    for vname, (uv, ur) in variants.items():
        print(f"\n=== {vname}; комиссия {FEE}% за круг; средний доход сделки, % (t-статистика), N")
        allres = {h: [] for h in HORIZ}
        allplac = {h: [] for h in HORIZ}
        halves = {h: [[], []] for h in HORIZ}
        shift_means = {h: [] for h in HORIZ}
        for sym in COINS:
            d = load(sym)
            s = signals(d, uv, ur)
            idx = np.where(s.to_numpy() != 0)[0]
            dirs = s.to_numpy()[idx]
            row = [f"{sym:<9}"]
            for h in HORIZ:
                f = forward(d, h).to_numpy()
                r = dirs * f[idx] - FEE
                allres[h].append(r)
                rnd = rng.choice([-1, 1], len(idx)) * f[idx] - FEE
                allplac[h].append(rnd)
                cut = len(d) // 2
                halves[h][0].append(r[idx < cut])
                halves[h][1].append(r[idx >= cut])
                m, t, n = stats(r)
                row.append(f"{h}ч {m:+.3f} ({t:+.1f}) N{n}")
            print("  ".join(row))
        for h in HORIZ:
            r = np.concatenate(allres[h])
            p = np.concatenate(allplac[h])
            m, t, n = stats(r)
            mp, tp, _ = stats(p)
            h1, t1, n1 = stats(np.concatenate(halves[h][0]))
            h2, t2, n2 = stats(np.concatenate(halves[h][1]))
            print(f"ВСЕ {h:>2}ч: {m:+.3f}% (t {t:+.1f}, N {n}) | случайное направление {mp:+.3f}% (t {tp:+.1f}) | "
                  f"старая половина {h1:+.3f}% (t {t1:+.1f}) | свежая {h2:+.3f}% (t {t2:+.1f})")
        # контроль сдвигом сигналов по кругу (только для полного правила, 4ч)
        if vname.startswith("MACD+объём+разворот"):
            real = np.nanmean(np.concatenate(allres[4]))
            sh = []
            for k in rng.integers(200, 5000, 30):
                acc = []
                for sym in COINS:
                    d = load(sym)
                    s = np.roll(signals(d, uv, ur).to_numpy(), int(k))
                    idx = np.where(s != 0)[0]
                    acc.append(s[idx] * forward(d, 4).to_numpy()[idx] - FEE)
                sh.append(np.nanmean(np.concatenate(acc)))
            sh = np.array(sh)
            print(f"контроль 4ч: 30 сдвигов сигналов по кругу — {sh.min():+.3f}…{sh.max():+.3f}% (медиана "
                  f"{np.median(sh):+.3f}); не хуже настоящего ({real:+.3f}%): {int((sh >= real).sum())} из 30")


if __name__ == "__main__":
    main()
