"""Operator's MA-zone rule book (4h BTC) — base rule + reclaim/loss exit triggers.

The operator's framework (his words, his direction — NOT my segmentation):
  yellow = TEMA100(4h), red = TEMA200(4h).
  ZONES:  LONG  = close>yellow AND yellow>red (bull stack)
          SHORT = close<yellow AND yellow<red (bear stack)
          HEDGE = price tangled around the MAs (neither stack)  -> hedge/stand aside
  TRIGGERS (the exit rules he asked for):
    RECLAIM (exit short -> long): close holds >yellow for HOLD bars AND yellow crosses >red
    LOSS    (exit long  -> short): mirror
  HARD EXIT: a violent break AGAINST the side (ATR%>1.4x base AND 1d thrust>4%) — the slow
    MA lags a crash, so this yanks you out immediately (validated: 0 false fires in range).

Anchor he gave & we verified: 2024-07-14 price reclaimed the yellow, yellow>red, then +13%.

Strictly causal. Light computation on frozen 2y data.
"""
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backtests" / "frozen" / "BTCUSDT_1h_2y.csv"
HOLD = 3          # bars a stack must hold to commit (operator: "закрепился")
FWD = 60          # forward eval window (10 days of 4h bars)
ADV = 30          # adverse-excursion window (5 days)


def load_4h():
    df = pd.read_csv(SRC)
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df = df.set_index("ts")
    return df.resample("4h").agg({"open": "first", "high": "max", "low": "min",
                                  "close": "last", "volume": "sum"}).dropna()


def tema(s, n):
    e1 = s.ewm(span=n, adjust=False).mean()
    e2 = e1.ewm(span=n, adjust=False).mean()
    e3 = e2.ewm(span=n, adjust=False).mean()
    return 3 * e1 - 3 * e2 + e3


def atr(df, n=14):
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def build(df):
    c = df["close"]
    df["yellow"] = tema(c, 100)
    df["red"] = tema(c, 200)
    df["atr"] = atr(df)
    df["atr_pct"] = df["atr"] / c
    df["atrp_exp"] = df["atr_pct"] / df["atr_pct"].rolling(60).median()
    df["thrust"] = (c / c.shift(6) - 1) * 100
    df["volX"] = df["volume"] / df["volume"].rolling(60).median()
    raw_long = (c > df["yellow"]) & (df["yellow"] > df["red"])
    raw_short = (c < df["yellow"]) & (df["yellow"] < df["red"])
    # commit a zone after HOLD consecutive bars; HEDGE when tangled HOLD bars
    zone = np.zeros(len(df), dtype=int)   # 1 long, -1 short, 0 hedge
    ls = ss = ns = 0
    state = 0
    rl = raw_long.to_numpy(); rs = raw_short.to_numpy()
    for i in range(len(df)):
        ls = ls + 1 if rl[i] else 0
        ss = ss + 1 if rs[i] else 0
        ns = ns + 1 if (not rl[i] and not rs[i]) else 0
        if ls >= HOLD: state = 1
        elif ss >= HOLD: state = -1
        elif ns >= HOLD: state = 0
        zone[i] = state
    df["zone"] = zone
    df["hard_exit"] = (df["atrp_exp"] > 1.4) & (df["thrust"].abs() > 4.0)
    return df


def flips(df):
    z = df["zone"].to_numpy()
    c = df["close"].to_numpy()
    out = []
    for i in range(1, len(df)):
        if z[i] != z[i - 1] and z[i] != 0:           # entered LONG or SHORT
            d = z[i]
            fwd = (c[min(i + FWD, len(c) - 1)] / c[i] - 1) * 100 * d
            seg = c[i:i + ADV]
            adv = ((seg.min() / c[i] - 1) * 100) if d > 0 else ((seg.max() / c[i] - 1) * 100)
            adv = adv * d                            # signed against-you move (neg = pain)
            out.append((df.index[i], d, c[i], fwd, adv, df["volX"].iat[i]))
    return out


def main():
    df = build(load_4h())
    print(f"Data {df.index[0]:%Y-%m-%d} -> {df.index[-1]:%Y-%m-%d}  ({len(df)} 4h bars)")
    pct = lambda v: 100 * v
    z = df["zone"]
    print(f"\nZone time:  LONG {pct((z==1).mean()):.0f}%   SHORT {pct((z==-1).mean()):.0f}%"
          f"   HEDGE {pct((z==0).mean()):.0f}%")

    fl = flips(df)
    worked = [f for f in fl if f[3] > 0]
    print(f"\nFLIPS into LONG/SHORT: {len(fl)}   'worked' (fwd 10d in dir >0): "
          f"{len(worked)}/{len(fl)} = {100*len(worked)/len(fl):.0f}%")
    fwd = np.array([f[3] for f in fl])
    adv = np.array([f[4] for f in fl])
    print(f"  mean fwd-10d (signed) {fwd.mean():+.1f}%   median {np.median(fwd):+.1f}%")
    print(f"  mean adverse-5d (pain before working) {adv.mean():+.1f}%   worst {adv.min():+.1f}%")
    # volume-confirmed subset
    vc = [f for f in fl if f[5] > 1.5]
    if vc:
        vcw = [f for f in vc if f[3] > 0]
        print(f"  volume-confirmed flips (volX>1.5): {len(vc)}, worked {len(vcw)}/{len(vc)}"
              f" = {100*len(vcw)/len(vc):.0f}%   mean fwd {np.mean([f[3] for f in vc]):+.1f}%")

    print(f"\n{'дата':12}{'напр':>6}{'цена':>9}{'fwd10д':>8}{'против5д':>9}{'volX':>6}  итог")
    for ts, d, px, f, a, v in fl:
        lab = "LONG " if d > 0 else "SHORT"
        res = "OK" if f > 0 else "FAKE"
        print(f"{ts:%Y-%m-%d}{lab:>6}{px:9.0f}{f:+8.1f}{a:+9.1f}{v:6.1f}  {res}")


if __name__ == "__main__":
    main()
