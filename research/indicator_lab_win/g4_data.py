"""G4: внешние данные. Бесплатные источники без ключей, отсечка та же: до 07.11.2026.

Источник и момент известности (known) каждого ряда. Ничего не используется раньше known:
  Deribit DVOL, час: начало часа + 1 час.
  Архив Binance metrics (OI, L/S, тейкеры), 5 минут: время строки.
  CoinMetrics community, день D: с 00:00 UTC дня D+2 (показатель дня готов только после его конца, запас ещё сутки).
  DefiLlama стейблы, день D: с 00:00 UTC дня D+2.
  blockchain.com хешрейт, день D: с 00:00 UTC дня D+2.
  Yahoo макро (SPX, DXY, золото, 10 лет, VIX), день D: с 00:00 UTC дня D+1, рынки США к этому моменту закрыты.
FRED и Stooq с этой машины не отвечают, вместо них Yahoo. Потоки на биржи в community закрыты (403).
"""
from __future__ import annotations

import io
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

import lab_data as ld

END_S = ld.END // 1000
DAY = 86400


def dvol(cur):
    p = ld.DATA / f"g4_dvol_{cur}.csv"
    if p.exists():
        return p
    rows, end = [], ld.END
    start = 1616544000000
    while end > start:
        d = ld.get("https://www.deribit.com/api/v2/public/get_volatility_index_data", {"currency": cur, "start_timestamp": start, "end_timestamp": end, "resolution": 3600})["result"]
        batch = d["data"]
        if not batch:
            break
        rows += batch
        if d.get("continuation") is None:
            break
        end = int(d["continuation"])
    f = pd.DataFrame(rows, columns=["ms", "open", "high", "low", "close"]).drop_duplicates("ms").sort_values("ms")
    f = f[f["ms"] + 3_600_000 <= ld.END]
    f.to_csv(p, index=False)
    return p


def probe_cm(asset):
    """Какие показатели реально открыты в community для монеты."""
    cand = ["CapMVRVCur", "AdrActCnt", "HashRate", "TxCnt", "TxTfrCnt", "CapMrktCurUSD", "CapRealUSD", "SplyCur", "NVTAdj", "ROI30d", "VtyDayRet30d", "DiffMean", "FeeTotUSD", "IssTotUSD", "SplyAct1yr", "TxTfrValAdjUSD"]
    ok = []
    for m in cand:
        try:
            r = ld.get("https://community-api.coinmetrics.io/v4/timeseries/asset-metrics", {"assets": asset, "metrics": m, "frequency": "1d", "page_size": 1, "start_time": "2023-01-01"}, tries=1)
            if r.get("data"):
                ok.append(m)
        except Exception:
            pass
    return ok


def coinmetrics(asset):
    p = ld.DATA / f"g4_cm_{asset}.csv"
    if p.exists():
        return p
    ms = probe_cm(asset)
    rows = []
    url = "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
    params = {"assets": asset, "metrics": ",".join(ms), "frequency": "1d", "page_size": 10000, "start_time": "2013-01-01", "end_time": "2026-11-06"}
    r = ld.get(url, params)
    rows += r["data"]
    while r.get("next_page_url"):
        r = ld.get(r["next_page_url"], None)
        rows += r["data"]
    f = pd.DataFrame(rows).drop(columns=["asset"])
    f["day"] = (pd.to_datetime(f["time"]).astype("int64") // 10 ** 9).astype("int64")
    f = f.drop(columns=["time"]).sort_values("day")
    f = f[f["day"] + DAY <= END_S]
    f.to_csv(p, index=False)
    print("CoinMetrics", asset, ms, len(f), flush=True)
    return p


def stable():
    p = ld.DATA / "g4_stable.csv"
    if p.exists():
        return p
    r = ld.get("https://stablecoins.llama.fi/stablecoincharts/all", None)
    f = pd.DataFrame([{"day": int(x["date"]), "usd": x["totalCirculatingUSD"].get("peggedUSD", np.nan)} for x in r])
    f = f[f["day"] + DAY <= END_S].sort_values("day")
    f.to_csv(p, index=False)
    return p


def hash_bc():
    p = ld.DATA / "g4_hash.csv"
    if p.exists():
        return p
    r = ld.get("https://api.blockchain.info/charts/hash-rate", {"timespan": "all", "format": "json", "sampled": "false"})
    f = pd.DataFrame(r["values"]).rename(columns={"x": "day", "y": "hash"})
    f = f[f["day"] + DAY <= END_S].sort_values("day")
    f.to_csv(p, index=False)
    return p


YAHOO = {"spx": "^GSPC", "dxy": "DX-Y.NYB", "gold": "GC=F", "tnx": "^TNX", "vix": "^VIX", "ndx": "^NDX"}


def macro():
    p = ld.DATA / "g4_macro.csv"
    if p.exists():
        return p
    out = {}
    for k, sym in YAHOO.items():
        r = ld.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}", {"period1": 1388534400, "period2": END_S, "interval": "1d"})["chart"]["result"][0]
        ts = np.array(r["timestamp"], dtype=np.int64)
        c = np.array(r["indicators"]["quote"][0]["close"], dtype=float)
        s = pd.Series(c, index=ts // DAY * DAY).dropna()
        out[k] = s[~s.index.duplicated(keep="last")]
    f = pd.DataFrame(out).sort_index()
    f = f[f.index + DAY <= END_S]
    f.index.name = "day"
    f.to_csv(p)
    return p


def _metrics_day(args):
    sym, day = args
    url = f"https://data.binance.vision/data/futures/um/daily/metrics/{sym}/{sym}-metrics-{day}.zip"
    import urllib.request
    for k in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=ld.UA), timeout=40) as r:
                raw = r.read()
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                f = pd.read_csv(z.open(z.namelist()[0]))
            f["ts"] = pd.to_datetime(f["create_time"]).astype("int64") // 10 ** 9
            f = f[f["ts"] % 14400 == 0]
            return f.drop(columns=["create_time", "symbol"])
        except Exception as e:
            if "404" in str(e):
                return None
    return None


def metrics(sym):
    p = ld.DATA / f"g4_metrics_{sym}.csv"
    if p.exists():
        return p
    days = pd.date_range("2021-12-01", "2026-11-06", freq="D").strftime("%Y-%m-%d").tolist()
    with ThreadPoolExecutor(8) as ex:
        parts = [x for x in ex.map(_metrics_day, [(sym, d) for d in days]) if x is not None]
    f = pd.concat(parts).drop_duplicates("ts").sort_values("ts")
    f = f[f["ts"] < END_S]
    f.to_csv(p, index=False)
    print("metrics", sym, len(f), flush=True)
    return p


def main():
    for c in ("BTC", "ETH"):
        print("dvol", c, dvol(c), flush=True)
    for a in ("btc", "eth", "xrp"):
        coinmetrics(a)
    print(stable(), hash_bc(), macro(), flush=True)
    for s in ("BTCUSDT", "ETHUSDT", "XRPUSDT"):
        metrics(s)
    rows = []
    for p in sorted(ld.DATA.glob("g4_*.csv")):
        f = pd.read_csv(p)
        first = f.columns[0]
        key = "ms" if "ms" in f else "ts" if "ts" in f else "day"
        rows.append({"файл": p.name, "строк": len(f), "с": str(pd.Timestamp(int(f[key].min()) // (1000 if key == "ms" else 1), unit="s"))[:16], "по": str(pd.Timestamp(int(f[key].max()) // (1000 if key == "ms" else 1), unit="s"))[:16], "столбцы": ",".join(f.columns[:14]), "sha256": ld.sha(p)})
    m = pd.DataFrame(rows)
    m.to_csv(Path(__file__).parent / "out" / "g4_manifest.csv", index=False)
    print(m.drop(columns=["sha256"]).to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
