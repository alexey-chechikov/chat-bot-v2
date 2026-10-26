"""Strategy 432 на 1h и 15m (26.10, оператор: «посмотри на таймах час и 15 минут»). Правила до прогона:
- параметры автора без изменений: канал 30 баров, ADX14 ≥ 22, close > EMA200, пробой ≥ 0.5 ATR14, выход close ниже
  канала или 20 баров (на 1h это 30 ч / 20 ч, на 15m — 7.5 ч / 5 ч); исполнение — open следующего бара; 0.068%/сторона;
- BTC и ETH — минутки Binance spot 2017–2026 (фандинг учтён); портфель 12 монет — свечи Binance spot нужного TF
  (фандинга нет), $1000 на сделку;
- контроль: случайный вход той же монеты в баре выше EMA200 с той же длительностью, 2000 повторов (портфель — 1000);
- «работает на TF» — ранг ≤ 0.01 и обе половины (до/после 2022-01-01) в плюсе; для BTC/ETH — каждая монета отдельно.
Запуск: tf_432.py <1m BTC> <1m ETH> <кэш свечей>"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import run as R  # noqa: E402
import strategies as S  # noqa: E402
from cross_coin_432 import COINS, END  # noqa: E402
from pooled_432 import control as pctl, run432  # noqa: E402
from validate_432 import control, s432  # noqa: E402

TFS = {"1h": ("1h", 3600), "15min": ("15m", 900)}
HALF = pd.Timestamp("2022-01-01")


def bars_tf(path, tf):
    d = pd.read_csv(path, usecols=["ts", "open", "high", "low", "close"])
    d.index = pd.to_datetime(d["ts"], unit="ms")
    return d.resample(tf).agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()


def klines(sym, interval, step_s, cache: Path):
    f = cache / f"{sym}_{interval}.csv"
    if f.exists():
        d = pd.read_csv(f)
    else:
        rows, start = [], 0
        while True:
            url = (f"https://api.binance.com/api/v3/klines?symbol={sym}&interval={interval}&limit=1000"
                   f"&startTime={start}&endTime={END - 1}")
            for k in range(5):
                try:
                    chunk = json.loads(urllib.request.urlopen(url, timeout=30).read())
                    break
                except Exception:                           # noqa: BLE001
                    time.sleep(2 + 3 * k)
            else:
                raise RuntimeError(f"{sym} {interval}: не скачалось {start}")
            if not chunk:
                break
            rows += [r[:5] for r in chunk if int(r[6]) < END]
            start = int(chunk[-1][0]) + step_s * 1000
            if len(chunk) < 1000:
                break
            time.sleep(0.15)
        d = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close"]).astype(float)
        d.to_csv(f, index=False)
    d.index = pd.to_datetime(d["ts"].astype("int64"), unit="ms")
    return d[["open", "high", "low", "close"]]


def single(sym, df, fund, tf):
    tr = R.evaluate(df, s432(tuple(df[k].to_numpy() for k in ("open", "high", "low", "close"))), fund)
    m, lo, hi = R.ci(tr["net"].to_numpy())
    ctl = control(df, tr, fund)
    rank = (1 + int((ctl >= m).sum())) / 2001
    h1, h2 = tr[tr["t"] < HALF]["net"].sum(), tr[tr["t"] >= HALF]["net"].sum()
    fr = tr[tr["t"] >= R.FRESH]["net"]
    ok = rank <= 0.01 and h1 > 0 and h2 > 0
    print(f"   {sym[:3]} {tf:>5}: n {len(tr):>4}, net {100 * m:+.3f}% [{100 * lo:+.3f}…{100 * hi:+.3f}], до изд. "
          f"{100 * tr['gross'].mean():+.3f}% | случайный выше EMA200 {100 * np.median(ctl):+.3f}% ранг {rank:.4f} | "
          f"2017–21 {100 * h1:+.0f}% / 2022–26 {100 * h2:+.0f}% | 2г {100 * fr.sum():+.0f}% (n {len(fr)}) | "
          f"{'РАБОТАЕТ' if ok else 'нет'}", flush=True)


def pooled(tf, interval, step_s, cache, btc_eth):
    data = {**btc_eth, **{s: klines(s, interval, step_s, cache) for s in COINS}}
    allt = []
    for sym, df in data.items():
        allt += [(sym, *x) for x in run432(df)]
    tr = pd.DataFrame(allt, columns=["sym", "t_in", "t_out", "net", "j", "bars"])
    m = tr["net"].mean()
    se = tr["net"].std(ddof=1) / np.sqrt(len(tr))
    rng = np.random.default_rng(23)
    by = {s: [x[1:] for x in allt if x[0] == s] for s in data}
    ctl = np.array([np.concatenate([pctl(data[s], v, False, rng) for s, v in by.items() if v]).mean()
                    for _ in range(1000)])
    usd = 1000 * tr["net"]
    h1, h2 = usd[tr["t_in"] < HALF].sum(), usd[tr["t_in"] >= HALF].sum()
    eq = usd[np.argsort(tr["t_out"].to_numpy())].cumsum().to_numpy()
    dd = float((eq - np.maximum.accumulate(eq)).min())
    rank = (1 + int((ctl >= m).sum())) / 1001
    yr = usd.groupby(tr["t_in"].dt.year).sum()
    ok = rank <= 0.01 and h1 > 0 and h2 > 0
    print(f"   ПОРТФЕЛЬ 12 монет {tf}: n {len(tr)}, net {100 * m:+.3f}% [{100 * (m - 1.96 * se):+.3f}…"
          f"{100 * (m + 1.96 * se):+.3f}], случайный {100 * np.median(ctl):+.3f}% ранг {rank:.4f} | $1000/сделку: "
          f"${usd.sum():+,.0f} (2017–21 ${h1:+,.0f} / 2022–26 ${h2:+,.0f}), просадка ${dd:+,.0f} | "
          f"{'РАБОТАЕТ' if ok else 'нет'}", flush=True)
    print("      по годам: " + ", ".join(f"{y} ${s:+,.0f}" for y, s in yr.items()), flush=True)


def main():
    cache = Path(sys.argv[3])
    cache.mkdir(parents=True, exist_ok=True)
    for tf, (interval, step_s) in TFS.items():
        print(f"== {tf}", flush=True)
        be = {}
        for sym, path in (("BTCUSDT", sys.argv[1]), ("ETHUSDT", sys.argv[2])):
            df = bars_tf(path, tf)
            single(sym, df, R.funding(sym), tf)
            be[sym] = df
        pooled(tf, interval, step_s, cache, be)


if __name__ == "__main__":
    main()
