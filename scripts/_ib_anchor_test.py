"""Inside Bar 4h — ANCHOR-SHIFT robustness test (проверка вывода Win).
Реальный эдж не должен зависеть от того, где проходит граница 4ч-бара.
Ресэмплим с offset 0/1/2/3ч и смотрим net/WR baseline и +ATR-фильтр на МОЁМ каноне.
"""
import sys
from pathlib import Path
import pandas as pd

ROOT = Path("/Users/alexeychechikov/code/bot7")
sys.path.insert(0, str(ROOT))
from tools._inside_bar_canonical import backtest, metrics

AGG = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}


def load_off(pair, off_h):
    df = pd.read_csv(ROOT / "backtests" / "frozen" / f"{pair}_1m_2y.csv")
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    s = df.set_index("ts")
    if off_h == 0:
        return s.resample("4h").agg(AGG).dropna()
    return s.resample("4h", offset=f"{off_h}h").agg(AGG).dropna()


def main():
    pair = sys.argv[1] if len(sys.argv) > 1 else "BTCUSDT"
    print(f"=== {pair} Inside Bar — ANCHOR SHIFT (resample offset), MAC engine ===")
    for off in (0, 1, 2, 3):
        o = load_off(pair, off)
        b = metrics(backtest(o))
        f = metrics(backtest(o, filt=["atr_lo"]))
        bn = b["net"] if b else None
        bw = b["wr"] if b else None
        fn = f["net"] if f else None
        fw = f["wr"] if f else None
        fnn = f["n"] if f else None
        print(f"  offset {off}h | baseline net={bn:>5}% WR={bw}%  ||  +ATR net={fn:>5}% WR={fw}% n={fnn}")


if __name__ == "__main__":
    main()
