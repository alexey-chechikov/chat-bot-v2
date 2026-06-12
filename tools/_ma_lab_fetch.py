"""Fetch & cache 2y of 1h klines from BitMEX for the MA-cross lab (BTC/ETH/SOL).
Paginates trade/bucketed (max 1000/req). Cache -> data/ma_lab/<sym>_1h.csv (idempotent)."""
import urllib.request, json, time, os
import pandas as pd

UA = {"User-Agent": "Mozilla/5.0"}
OUT = "data/ma_lab"
SYMS = ["XBTUSDT", "ETHUSDT", "SOLUSDT"]
DAYS = 760  # ~2y + warmup for MA200(4h)

def get(url):
    return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30))

def fetch(sym):
    start = (pd.Timestamp.utcnow() - pd.Timedelta(days=DAYS)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    rows, st = [], start
    while True:
        u = (f"https://www.bitmex.com/api/v1/trade/bucketed?binSize=1h&partial=false"
             f"&symbol={sym}&count=1000&reverse=false&startTime={st}")
        k = get(u)
        if not k:
            break
        rows += k
        if len(k) < 1000:
            break
        st = k[-1]["timestamp"]
        time.sleep(1.1)  # rate limit
    df = pd.DataFrame(rows)
    df["ts"] = pd.to_datetime(df["timestamp"])
    df = df.drop_duplicates("ts").set_index("ts").sort_index()
    return df[["open", "high", "low", "close", "volume"]]

def main():
    os.makedirs(OUT, exist_ok=True)
    for sym in SYMS:
        path = f"{OUT}/{sym}_1h.csv"
        if os.path.exists(path):
            d = pd.read_csv(path, index_col=0, parse_dates=True)
            print(f"{sym}: cached {len(d)} bars {d.index[0]} .. {d.index[-1]}")
            continue
        d = fetch(sym)
        d.to_csv(path)
        print(f"{sym}: fetched {len(d)} bars {d.index[0]} .. {d.index[-1]}")

if __name__ == "__main__":
    main()
