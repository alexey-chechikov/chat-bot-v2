"""Индикатор на его графике BYBIT:BTCUSDT.P показал 222 сделки и +12.2%, Binance даёт 233 и −23.3%. Здесь тот же автомат на часовых барах Bybit и разбор, откуда разница. Публичные данные, без ключей, только чтение."""
from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import cw_data as cw  # noqa: E402
import gpt_check as gc  # noqa: E402
import pine_expected as pe  # noqa: E402
import pos  # noqa: E402
import state_card as sc  # noqa: E402
import state_map as sm  # noqa: E402
import words as wd  # noqa: E402
import words2 as w2  # noqa: E402

pd.set_option("display.width", 220, "display.max_columns", 30, "display.max_rows", 120)
DIR = cw.SCR / "holdout" / "bybit"
DIR.mkdir(parents=True, exist_ok=True)
URL = "https://api.bybit.com/v5/market/kline"
START = cw.T("2020-03-25") * 1000


def fetch():
    p = DIR / "BTCUSDT_1h.csv"
    if p.exists() and time.time() - p.stat().st_mtime < 6 * 3600:
        return pd.read_csv(p)
    rows, end = [], int(time.time() * 1000)
    while end > START:
        q = urllib.parse.urlencode({"category": "linear", "symbol": "BTCUSDT", "interval": "60", "end": end, "limit": 1000})
        req = urllib.request.Request(URL + "?" + q, headers={"User-Agent": "Mozilla/5.0 research"})
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.loads(r.read())["result"]["list"]
        if not d:
            break
        rows += [x[:6] for x in d]
        end = int(d[-1][0]) - 1
        time.sleep(0.12)
    f = pd.DataFrame(rows, columns=["ms", "open", "high", "low", "close", "volume"]).astype(float).drop_duplicates("ms").sort_values("ms")
    f = f[f["ms"] + 3600_000 <= time.time() * 1000]
    f.to_csv(p, index=False)
    return f


def load_bybit():
    f = fetch()
    f["ts"] = (f["ms"] // 1000).astype(np.int64)
    print("Bybit бары", len(f), pd.Timestamp(f["ms"].iloc[0], unit="ms"), pd.Timestamp(f["ms"].iloc[-1], unit="ms"), flush=True)
    fund = pd.Series([0.0], index=[int(f["ts"].iloc[0])])
    a = gc.from_hourly(f, fund, pd.Timestamp(int(f["ts"].iloc[0]) + 180 * 86400, unit="s").strftime("%Y-%m-%d"))
    wd.add_runs(a)
    sm.add_state(a)
    return a


def main():
    frm = sm.T("2025-01-01")
    by = load_bybit()
    bn, _, _ = sc.load_coin("BTC")
    out = {}
    for lab, a in (("Binance", bn), ("Bybit", by)):
        st = {}
        legs = w2.run(a, **w2.MAIN26, stop_at=len(a["t"]) - 1, out=st)
        d = pe.table(a, legs, frm)
        d["t0"] = [a["t"][x[0]] for x in legs if a["t"][x[0]] >= frm]
        print(f"{lab}: закрытых {len(d)}, итог {d['в_итог'].sum():+.1f}%, лонг {d.loc[d['сторона'] == 'L', 'в_итог'].sum():+.1f}, шорт {d.loc[d['сторона'] == 'S', 'в_итог'].sum():+.1f}; открыта: {st['cur'][3] if st['cur'] else 'нет'}", flush=True)
        out[lab] = d
        d.drop(columns="t0").to_csv(pos.OUT / f"bybit_check_{lab}.csv", index=False)
    for lab, d in out.items():
        d["кв"] = pd.to_datetime(d["t0"], unit="s").dt.to_period("Q").astype(str)
    q = pd.DataFrame({lab: d.groupby("кв")["в_итог"].sum().round(1) for lab, d in out.items()})
    q["разница"] = (q["Bybit"] - q["Binance"]).round(1)
    print(q.to_string(), flush=True)
    kb, kn = out["Bybit"], out["Binance"]
    same = set(zip(kb["t0"], kb["сторона"])) & set(zip(kn["t0"], kn["сторона"]))
    print("входов в тот же час и в ту же сторону:", len(same), "из", len(kb), "и", len(kn), flush=True)
    onlyb = kb[[(x, y) not in same for x, y in zip(kb["t0"], kb["сторона"])]].sort_values("в_итог", ascending=False)
    onlyn = kn[[(x, y) not in same for x, y in zip(kn["t0"], kn["сторона"])]].sort_values("в_итог")
    print("только Bybit: сумма", round(onlyb["в_итог"].sum(), 1), "| только Binance: сумма", round(onlyn["в_итог"].sum(), 1), flush=True)
    cols = ["вход", "выход", "сторона", "тип", "причина", "p0", "p1", "net", "вес"]
    print(onlyb[cols].head(8).to_string(index=False), flush=True)
    print(onlyn[cols].head(8).to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
