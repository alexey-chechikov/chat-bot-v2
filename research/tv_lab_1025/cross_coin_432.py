"""Strategy 432 с параметрами автора (подбор шёл на BTC) на монетах, где автор не подбирал — проверка переноса (25.10).
ПРАВИЛО ДО ПРОГОНА: «переносится», если на ≥7 из 10 монет net после издержек в плюсе И на ≥6 из 10 ранг против
случайного входа выше EMA200 (те же длительности, 1000 повторов) ≤ 0.05; иначе — подгонка под BTC.
Данные: свечи 4h Binance spot с листинга по 24.10.2026 (публичный API, только закрытые бары); фандинга нет (спот) —
издержки 0.068%/сторона как у WEEX тейкера. Запуск: cross_coin_432.py <папка для кэша>"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import strategies as S  # noqa: E402
from validate_432 import s432  # noqa: E402

COINS = ["BNBUSDT", "XRPUSDT", "LTCUSDT", "ADAUSDT", "LINKUSDT", "DOGEUSDT", "TRXUSDT", "SOLUSDT", "XLMUSDT", "ETCUSDT"]
END = int(pd.Timestamp("2026-10-24").timestamp() * 1000)


def klines(sym: str, cache: Path) -> pd.DataFrame:
    f = cache / f"{sym}_4h.csv"
    if f.exists():
        d = pd.read_csv(f)
    else:
        rows, start = [], 0
        while True:
            url = f"https://api.binance.com/api/v3/klines?symbol={sym}&interval=4h&limit=1000&startTime={start}&endTime={END - 1}"
            chunk = json.loads(urllib.request.urlopen(url, timeout=30).read())
            if not chunk:
                break
            rows += [r[:5] for r in chunk if int(r[6]) < END]
            start = int(chunk[-1][0]) + 4 * 3600 * 1000
            if len(chunk) < 1000:
                break
            time.sleep(0.2)
        d = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close"]).astype(float)
        d.to_csv(f, index=False)
    d.index = pd.to_datetime(d["ts"].astype("int64"), unit="ms")
    return d[["open", "high", "low", "close"]]


def evaluate(df, trades):
    o = df["open"].to_numpy()
    return np.array([s * (po / pi - 1) - 2 * S.COST for j, k, s, pi, po, _ in trades if k > j]), \
        np.array([k - j for j, k, *_ in trades if k > j])


def control(df, durs, reps=1000, seed=3):
    o, c = df["open"].to_numpy(), df["close"].to_numpy()
    ok = np.flatnonzero(c > S.ema(c, 200))
    ok = ok[(ok > 300) & (ok < len(o) - 25)]
    rng = np.random.default_rng(seed)
    res = np.empty(reps)
    for r in range(reps):
        j = rng.choice(ok, size=len(durs)) + 1
        k = np.minimum(j + durs, len(o) - 1)
        res[r] = (o[k] / o[j] - 1 - 2 * S.COST).mean()
    return res


def main():
    cache = Path(sys.argv[1])
    cache.mkdir(parents=True, exist_ok=True)
    pos = beat = 0
    for sym in COINS:
        df = klines(sym, cache)
        net, durs = evaluate(df, s432(tuple(df[k].to_numpy() for k in ("open", "high", "low", "close"))))
        if len(net) < 5:
            print(f"{sym}: сделок {len(net)} — мало")
            continue
        ctl = control(df, durs)
        m = net.mean()
        rank = (1 + int((ctl >= m).sum())) / 1001
        pos += m > 0
        beat += rank <= 0.05
        se = net.std(ddof=1) / np.sqrt(len(net))
        print(f"{sym}: {df.index[0].date()}…, n {len(net)}, net {100 * m:+.2f}% [{100 * (m - 1.96 * se):+.2f}…"
              f"{100 * (m + 1.96 * se):+.2f}], сумма {100 * net.sum():+.0f}%, случайный выше EMA200 {100 * np.median(ctl):+.2f}%, "
              f"ранг {rank:.3f}", flush=True)
    print(f"ИТОГ: в плюсе {pos} из {len(COINS)}, обгоняет случайный (ранг ≤0.05) {beat} из {len(COINS)} → "
          + ("ПЕРЕНОСИТСЯ" if pos >= 7 and beat >= 6 else "НЕ переносится — похоже на подгонку под BTC"))


if __name__ == "__main__":
    main()
