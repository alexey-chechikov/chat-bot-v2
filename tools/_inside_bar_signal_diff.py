"""Find the signal-count divergence: Win ~168 trades vs Mac ~150.
Test 2 inside-bar definitions and 2 breakout references:
  DEF-A (mine): inside[i-1] vs [i-2]; breakout of bar[i-1] high/low by close[i]
  DEF-B (TV-ish): current bar[i] is inside bar[i-1]; breakout of MOTHER bar[i-1]
                  by a LATER bar's close
Also count raw signals each way (before exit sim).
"""
from pathlib import Path
import numpy as np, pandas as pd
ROOT=Path(__file__).resolve().parents[1]; FROZEN=ROOT/"backtests"/"frozen"

def load_4h(p="BTCUSDT"):
    df=pd.read_csv(FROZEN/f"{p}_15m_2y.csv"); df["ts"]=pd.to_datetime(df["ts"],unit="ms",utc=True)
    return df.set_index("ts").resample("4h").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna()

df=load_4h()
H,L,C=df["high"].to_numpy(),df["low"].to_numpy(),df["close"].to_numpy()
n=len(df)

# DEF-A (mine): mother=i-1, inside relation i-1 inside i-2, breakout by close[i]
a_long=a_short=0
for i in range(2,n):
    if H[i-1]<H[i-2] and L[i-1]>L[i-2]:
        if C[i]>H[i-1]: a_long+=1
        elif C[i]<L[i-1]: a_short+=1

# DEF-B: mother=i-1, inside bar=i (i inside i-1), breakout NEXT bar i+1 by close
b_long=b_short=0
for i in range(1,n-1):
    if H[i]<H[i-1] and L[i]>L[i-1]:           # bar i is inside bar i-1 (mother)
        if C[i+1]>H[i-1]: b_long+=1            # breakout of MOTHER by next close
        elif C[i+1]<L[i-1]: b_short+=1

# DEF-C: TV "Inside Bar Strategy" — enter on the bar that breaks the mother,
# but only one signal per inside cluster (no re-fire while still inside)
c_long=c_short=0; armed=False; mh=ml=0
for i in range(1,n):
    is_inside = H[i]<H[i-1] and L[i]>L[i-1]
    if is_inside and not armed:
        armed=True; mh=H[i-1]; ml=L[i-1]
    elif armed:
        if C[i]>mh: c_long+=1; armed=False
        elif C[i]<ml: c_short+=1; armed=False
        elif not is_inside: armed=False  # mother context lost

print("===== Inside-bar signal-count by definition (BTC 4h 2024-26) =====")
print(f"  DEF-A (mine):  long={a_long} short={a_short} total={a_long+a_short}")
print(f"  DEF-B (i inside i-1, breakout next close): long={b_long} short={b_short} total={b_long+b_short}")
print(f"  DEF-C (armed-cluster, one fire): long={c_long} short={c_short} total={c_long+c_short}")
