"""Strategy 432 портфелем (25.10, оператор: «что ещё можем сделать»). Правила до прогона:
- 12 монет (BTC, ETH + 10 альтов из cross_coin_432), свечи 4h Binance spot с листинга по 24.10.2026, параметры автора,
  исполнение — open следующего бара, издержки 0.068%/сторона, фандинга нет (спот, одинаково для всех);
- ПОРТФЕЛЬ: каждая сделка — одинаковый номинал $1000, сделки разных монет одновременно разрешены; итог по месяцам и годам,
  просадка совместной кривой (по закрытию сделок), максимум одновременно открытых;
- общий контроль: для КАЖДОЙ сделки случайный вход той же монеты в баре выше EMA200 с той же длительностью, средний net
  всего портфеля, 2000 повторов, ранг; плюс половины 2017–2021 / 2022–2026;
- ШОРТ-зеркало: close < минимума low прошлых 30 баров, ADX ≥ 22, close < EMA200, пробой вниз ≥ 0.5 ATR; выход close >
  максимума прошлых 30 баров или 20 баров; контроль — случайный шорт ниже EMA200;
- вывод «портфель работает» — ранг ≤ 0.01 и обе половины в плюсе; «шорт работает» — то же для шортов."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import strategies as S  # noqa: E402
from cross_coin_432 import COINS, klines  # noqa: E402


def run432(df, short=False):
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    hi = pd.Series(h).shift(1).rolling(30).max().to_numpy()
    lo = pd.Series(l).shift(1).rolling(30).min().to_numpy()
    a = S.atr(h, l, c, 14)
    e = S.ema(c, 200)
    _, _, adx = S.dmi(h, l, c, 14, 14)
    if short:
        ent = (c < lo) & (adx >= 22) & (c < e) & (np.where(a > 0, (lo - c) / a, 0) >= 0.5)
    else:
        ent = (c > hi) & (adx >= 22) & (c > e) & (np.where(a > 0, (c - hi) / a, 0) >= 0.5)
    ent[:300] = False
    out, pos = [], None
    side = -1 if short else 1
    for i in range(len(c) - 1):
        if pos is not None:
            j, si = pos
            ex = (c[i] > hi[i]) if short else (c[i] < lo[i])
            if ex or i - si >= 20:
                out.append((j, i + 1))
                pos = None
                continue
        if pos is None and ent[i]:
            pos = (i + 1, i)
    t = df.index
    return [(t[j], t[k], side * (o[k] / o[j] - 1) - 2 * S.COST, j, k - j) for j, k in out]


def control(df, trades, short, rng):
    o, c = df["open"].to_numpy(), df["close"].to_numpy()
    e = S.ema(c, 200)
    ok = np.flatnonzero(c < e) if short else np.flatnonzero(c > e)
    ok = ok[(ok > 300) & (ok < len(o) - 25)]
    d = np.array([x[4] for x in trades])
    j = rng.choice(ok, size=len(d)) + 1
    k = np.minimum(j + d, len(o) - 1)
    s = -1 if short else 1
    return s * (o[k] / o[j] - 1) - 2 * S.COST


def report(name, data, short):
    allt = []
    for sym, df in data.items():
        allt += [(sym, *x) for x in run432(df, short)]
    tr = pd.DataFrame(allt, columns=["sym", "t_in", "t_out", "net", "j", "bars"]).sort_values("t_out")
    m = tr["net"].mean()
    se = tr["net"].std(ddof=1) / np.sqrt(len(tr))
    rng = np.random.default_rng(17)
    ctl = np.empty(2000)
    by = {s: [x for x in allt if x[0] == s] for s in data}
    for r in range(2000):
        ctl[r] = np.concatenate([control(data[s], [x[1:] for x in v], short, rng) for s, v in by.items() if v]).mean()
    usd = 1000 * tr["net"]
    eq = usd.cumsum().to_numpy()
    dd = float((eq - np.maximum.accumulate(eq)).min())
    h1 = usd[tr["t_in"] < pd.Timestamp("2022-01-01")].sum()
    h2 = usd[tr["t_in"] >= pd.Timestamp("2022-01-01")].sum()
    ev = sorted([(x[1], 1) for x in allt] + [(x[2], -1) for x in allt])
    cur = mx = 0
    for _, d in ev:
        cur += d
        mx = max(mx, cur)
    yr = usd.groupby(tr["t_in"].dt.year).agg(["count", "sum"])
    print(f"== {name}: сделок {len(tr)} на {tr['sym'].nunique()} монетах, net {100 * m:+.2f}%/сделку "
          f"[{100 * (m - 1.96 * se):+.2f}…{100 * (m + 1.96 * se):+.2f}], случайный того же режима {100 * np.median(ctl):+.2f}% "
          f"(95% {100 * np.quantile(ctl, .95):+.2f}%), ранг {(1 + int((ctl >= m).sum())) / 2001:.4f}")
    print(f"   по $1000 на сделку: итог ${usd.sum():+,.0f}, 2017–2021 ${h1:+,.0f} / 2022–2026 ${h2:+,.0f}, просадка "
          f"${dd:+,.0f}, одновременно открыто до {mx}")
    print("   по годам: " + ", ".join(f"{y} ${s:+,.0f} (n {int(k)})" for y, (k, s) in yr.iterrows()))


def main():
    cache = Path(sys.argv[1])
    data = {s: klines(s, cache) for s in ["BTCUSDT", "ETHUSDT"] + COINS}
    report("ЛОНГ-портфель 12 монет", data, short=False)
    report("ШОРТ-зеркало 12 монет", data, short=True)
    report("ШОРТ-зеркало только BTC+ETH", {k: data[k] for k in ("BTCUSDT", "ETHUSDT")}, short=True)


if __name__ == "__main__":
    main()
