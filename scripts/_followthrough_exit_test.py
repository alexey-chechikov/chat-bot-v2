"""Follow-through EXIT test — бьёт ли «режь на затухании health» наивный выход (regime-flip)?
И переживает ли это anchor-shift (урок IB)?

Entry (общий для всех вариантов): на edge режима (regDir 0/opp -> +-1) по close.
Exit-варианты:
  regime              : выход только на смене режима (наивный baseline)
  regime+voloff       : + vol-off
  regime+fizzle       : + health<=35 два бара (follow-through ранний выход)
  regime+voloff+fizzle: всё
Entry зафиксирован -> сравнение чистое про ВЫХОД. Прогон по offset 0/1/2/3ч.
Health = как в Pine v5.5: close vs t50/t100/t200 (25/15/10) + тело(20) + объём(15) + сила закрытия(15).
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path("/Users/alexeychechikov/code/bot7")
sys.path.insert(0, str(ROOT))
from tools._inside_bar_canonical import atr_wilder

AGG = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
BAND, CONF, FEE = 2.5, 2, 0.15


def load_off(pair, off_h):
    df = pd.read_csv(ROOT / "backtests" / "frozen" / f"{pair}_1m_2y.csv")
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    s = df.set_index("ts")
    return (s.resample("4h").agg(AGG).dropna() if off_h == 0
            else s.resample("4h", offset=f"{off_h}h").agg(AGG).dropna())


def tema(s, n):
    e1 = s.ewm(span=n, adjust=False).mean()
    e2 = e1.ewm(span=n, adjust=False).mean()
    e3 = e2.ewm(span=n, adjust=False).mean()
    return (3 * e1 - 3 * e2 + e3).to_numpy(float)


def build(o):
    o = o.copy()
    op = o["open"].to_numpy(float); h = o["high"].to_numpy(float)
    l = o["low"].to_numpy(float); c = o["close"].to_numpy(float)
    v = o["volume"].to_numpy(float); n = len(c)
    t50, t100, t200 = tema(o["close"], 50), tema(o["close"], 100), tema(o["close"], 200)
    bull = (t50 > t100) & (t100 > t200)
    bear = (t50 < t100) & (t100 < t200)
    aboveRed = (c - t200) / t200 * 100.0
    atr_pct = (atr_wilder(o, 14).to_numpy(float)) / c
    sma = pd.Series(atr_pct).rolling(100).mean().to_numpy()
    sd = pd.Series(atr_pct).rolling(100).std().to_numpy()
    z = (atr_pct - sma) / sd
    voloff = np.zeros(n, bool); st = False
    for i in range(n):
        if np.isfinite(z[i]):
            if z[i] >= 2.5: st = True
            elif z[i] < 1.0: st = False
        voloff[i] = st
    # regDir (confBars)
    rawUp = (aboveRed > BAND) & bull
    rawDn = (aboveRed < -BAND) & bear
    regDir = np.zeros(n, int); up = dn = 0; cur = 0
    for i in range(n):
        up = up + 1 if rawUp[i] else 0
        dn = dn + 1 if rawDn[i] else 0
        if up >= CONF: cur = 1
        elif dn >= CONF: cur = -1
        elif not rawUp[i] and not rawDn[i]: cur = 0
        regDir[i] = cur
    # health
    rng = h - l
    closeStr = np.where(rng > 0, (c - l) / np.where(rng > 0, rng, 1), 0.5)
    vma = pd.Series(v).rolling(100).mean().to_numpy()
    volPart = np.where(np.isfinite(vma), v > vma, False)
    ftBull = 25*(c > t50) + 15*(c > t100) + 10*(c > t200) + 20*(c > op) + 15*volPart + 15*(closeStr > 0.6)
    ftBear = 25*(c < t50) + 15*(c < t100) + 10*(c < t200) + 20*(c <= op) + 15*volPart + 15*(closeStr < 0.4)
    return dict(c=c, regDir=regDir, voloff=voloff, ftBull=ftBull, ftBear=ftBear, n=n)


def bt(d, mode, fee=FEE):
    c, regDir, voloff, ftBull, ftBear, n = d["c"], d["regDir"], d["voloff"], d["ftBull"], d["ftBear"], d["n"]
    pos = 0; entry = 0.0; rets = []
    for i in range(2, n):
        if pos != 0:
            hd = ftBull[i] if pos == 1 else ftBear[i]
            hp = ftBull[i-1] if pos == 1 else ftBear[i-1]
            fz = hd <= 35 and hp <= 35
            ex = regDir[i] != pos
            if "voloff" in mode and voloff[i]: ex = True
            if "fizzle" in mode and fz: ex = True
            if ex:
                rets.append((c[i] - entry) / entry * pos - fee / 100.0)
                pos = 0
        if pos == 0 and regDir[i] != regDir[i-1] and regDir[i] != 0:
            pos = regDir[i]; entry = c[i]
    return rets


def metr(r):
    if len(r) < 3: return None
    r = np.array(r); eq = np.cumprod(1 + r)
    dd = ((eq - np.maximum.accumulate(eq)) / np.maximum.accumulate(eq)).min() * 100
    return dict(n=len(r), net=round((eq[-1]-1)*100), wr=round((r > 0).mean()*100), dd=round(dd), avg=round(r.mean()*100, 2))


def main():
    pair = sys.argv[1] if len(sys.argv) > 1 else "BTCUSDT"
    modes = ["regime", "regime+voloff", "regime+fizzle", "regime+voloff+fizzle"]
    print(f"=== {pair} 4h  FOLLOW-THROUGH EXIT test (entry=regime-edge, exit=variant)  fee {FEE}% ===")
    for off in (0, 1, 2, 3):
        d = build(load_off(pair, off))
        print(f"\n-- offset {off}h --")
        for m in modes:
            print(f"  {m:22s} {metr(bt(d, m))}")


if __name__ == "__main__":
    main()
