"""Re-run the full backtest with DEF-C (armed-cluster, one-fire) signals —
the strict TV-style Inside Bar — to see if it lands near Mac's +130%.
Wilder ATR, TP5/SL3, fee 0.15%, per-year breakdown.
"""
from pathlib import Path
import numpy as np, pandas as pd
ROOT=Path(__file__).resolve().parents[1]; FROZEN=ROOT/"backtests"/"frozen"
FEE=0.00075; TP_MULT,SL_MULT=5.0,3.0

def load_4h(p="BTCUSDT"):
    df=pd.read_csv(FROZEN/f"{p}_15m_2y.csv"); df["ts"]=pd.to_datetime(df["ts"],unit="ms",utc=True)
    return df.set_index("ts").resample("4h").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna()

def atr(df,n=14):
    h,l,c=df["high"],df["low"],df["close"]
    tr=pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    return tr.ewm(alpha=1/n,adjust=False).mean()

def signals_defc(df):
    H,L,C=df["high"].to_numpy(),df["low"].to_numpy(),df["close"].to_numpy()
    sig=pd.Series(0,index=df.index); armed=False; mh=ml=0
    for i in range(1,len(df)):
        is_inside = H[i]<H[i-1] and L[i]>L[i-1]
        if is_inside and not armed:
            armed=True; mh=H[i-1]; ml=L[i-1]
        elif armed:
            if C[i]>mh: sig.iloc[i]=1; armed=False
            elif C[i]<ml: sig.iloc[i]=-1; armed=False
            elif not is_inside: armed=False
    return sig

def run(df,sig):
    c=df["close"].to_numpy(float); hi=df["high"].to_numpy(float); lo=df["low"].to_numpy(float)
    a=atr(df,14).to_numpy(float); s=sig.to_numpy()
    eq=1.0; pos=0; entry=0.0; tp=sl=0.0; eb=-1; rets=[]; tss=[]
    for i in range(len(df)):
        if pos!=0 and i>eb:
            cl=None
            if pos==1:
                if lo[i]<=sl: cl=sl/entry-1
                elif hi[i]>=tp: cl=tp/entry-1
            else:
                if hi[i]>=sl: cl=entry/sl-1
                elif lo[i]<=tp: cl=entry/tp-1
            if cl is not None: eq*=(1+cl-FEE); rets.append(cl-FEE); tss.append(df.index[i]); pos=0
        if s[i]!=0 and s[i]!=pos:
            if pos!=0:
                r=(c[i]/entry-1) if pos==1 else (entry/c[i]-1); eq*=(1+r-FEE); rets.append(r-FEE); tss.append(df.index[i])
            pos=int(s[i]); entry=c[i]; eb=i; eq*=(1-FEE)
            if pos==1: tp=entry+TP_MULT*a[i]; sl=entry-SL_MULT*a[i]
            else: tp=entry-TP_MULT*a[i]; sl=entry+SL_MULT*a[i]
    return (eq-1)*100, rets, tss

df=load_4h(); sig=signals_defc(df)
total,rets,tss=run(df,sig)
rr=np.array(rets)
print("===== DEF-C strict Inside Bar (BTC 4h 2024-26, Wilder, TP5/SL3, fee 0.15%) =====")
bh=(df['close'].iloc[-1]/df['close'].iloc[0]-1)*100
print(f"  net={total:+.1f}%  vs buy&hold {bh:+.1f}%  WR={round((rr>0).mean()*100)}%  trades={len(rets)}")
# per year
ser=pd.Series(rets,index=pd.to_datetime(tss))
for y,g in ser.groupby(ser.index.year):
    yt=((1+g).cumprod().iloc[-1]-1)*100
    print(f"    {y}: net={yt:+.1f}%  trades={len(g)}")
