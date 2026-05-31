"""The real suspect: entry timing. My engine enters at close[i] of the SIGNAL
bar — but the signal (close>high[i-1]) is only KNOWN at that close. Entering at
the same close is fine (no lookahead) BUT exit-checking starts next bar. The
gap vs Mac is likely: do we enter at close[i] (signal bar) or open[i+1] (next
bar)? And is reverse counted as 1 or 2 fills? Test next-bar entry = realistic.
"""
from pathlib import Path
import numpy as np, pandas as pd
ROOT = Path(__file__).resolve().parents[1]
FROZEN = ROOT/"backtests"/"frozen"; FEE=0.00075; TP_MULT,SL_MULT=5.0,3.0

def load_4h(p="BTCUSDT"):
    df=pd.read_csv(FROZEN/f"{p}_15m_2y.csv"); df["ts"]=pd.to_datetime(df["ts"],unit="ms",utc=True)
    return df.set_index("ts").resample("4h").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna()

def atr(df,n=14):
    h,l,c=df["high"],df["low"],df["close"]
    tr=pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    return tr.ewm(alpha=1/n,adjust=False).mean()

def signals(df):
    inside=(df["high"]<df["high"].shift())&(df["low"]>df["low"].shift())
    mh=df["high"].shift(); ml=df["low"].shift(); sig=pd.Series(0,index=df.index); c=df["close"]
    for i in range(2,len(df)):
        if not inside.iloc[i-1]: continue
        if c.iloc[i]>mh.iloc[i-1]: sig.iloc[i]=1
        elif c.iloc[i]<ml.iloc[i-1]: sig.iloc[i]=-1
    return sig

def sim(df,sig,entry_at):
    """entry_at: 'close_i' (signal-bar close) or 'open_next' (next bar open)."""
    o=df["open"].to_numpy(float); c=df["close"].to_numpy(float)
    hi=df["high"].to_numpy(float); lo=df["low"].to_numpy(float); a=atr(df,14).to_numpy(float)
    s=sig.to_numpy(); eq=1.0; pos=0; entry=0.0; tp=sl=0.0; eb=-1; rets=[]
    pending=0  # signal waiting for next-bar open
    for i in range(len(df)):
        # execute pending next-bar entry at open[i]
        if entry_at=="open_next" and pending!=0:
            if pos!=0:
                r=(o[i]/entry-1) if pos==1 else (entry/o[i]-1); eq*=(1+r-FEE); rets.append(r-FEE)
            pos=pending; entry=o[i]; eb=i; eq*=(1-FEE); pending=0
            if pos==1: tp=entry+TP_MULT*a[i]; sl=entry-SL_MULT*a[i]
            else: tp=entry-TP_MULT*a[i]; sl=entry+SL_MULT*a[i]
        if pos!=0 and i>eb:
            cl=None
            if pos==1:
                if lo[i]<=sl: cl=sl/entry-1
                elif hi[i]>=tp: cl=tp/entry-1
            else:
                if hi[i]>=sl: cl=entry/sl-1
                elif lo[i]<=tp: cl=entry/tp-1
            if cl is not None: eq*=(1+cl-FEE); rets.append(cl-FEE); pos=0
        if s[i]!=0 and s[i]!=pos:
            if entry_at=="close_i":
                if pos!=0:
                    r=(c[i]/entry-1) if pos==1 else (entry/c[i]-1); eq*=(1+r-FEE); rets.append(r-FEE)
                pos=int(s[i]); entry=c[i]; eb=i; eq*=(1-FEE)
                if pos==1: tp=entry+TP_MULT*a[i]; sl=entry-SL_MULT*a[i]
                else: tp=entry-TP_MULT*a[i]; sl=entry+SL_MULT*a[i]
            else:
                pending=int(s[i])
    rr=np.array(rets) if rets else np.array([0.0])
    return (eq-1)*100, round((rr>0).mean()*100), len(rets)

df=load_4h(); sig=signals(df)
print("===== entry timing test (BTC 4h 2024-26, Wilder ATR, fee 0.15%) =====")
for ea in ("close_i","open_next"):
    t,wr,n=sim(df,sig,ea)
    print(f"  entry_at={ea:10}  net={t:+.1f}%  WR={wr}%  trades={n}")
