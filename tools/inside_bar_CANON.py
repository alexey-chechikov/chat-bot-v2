"""CANONICAL Inside Bar — THE single source of truth. Win + Mac run THIS file,
byte-for-byte, on the same frozen data. No re-implementation, no divergence.

Strategy (fixed, no ambiguity):
  inside cluster: bar is inside prev bar (high<prevH and low>prevL).
  ARM on first inside bar, remember mother = that prev bar's H/L.
  FIRE LONG when a later close > mother_H ; SHORT when close < mother_L.
  one fire per cluster (disarm after fire or when inside-context breaks).
  exit: ATR(14 Wilder) TP=TP_MULT / SL=SL_MULT, stop-and-reverse on opposite fire.
  fee: 0.15% round-trip taker. entry at signal-bar close.
"""
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path(__file__).resolve().parents[1]
FROZEN = ROOT / "backtests" / "frozen"
FEE = 0.00075
TP_MULT, SL_MULT = 5.0, 3.0

def load_4h(pair):
    df = pd.read_csv(FROZEN / f"{pair}_15m_2y.csv") if (FROZEN/f"{pair}_15m_2y.csv").exists() \
         else pd.read_csv(FROZEN / f"{pair}_1h_2y.csv")
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return df.set_index("ts").resample("4h").agg(
        {"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna()

def atr_wilder(df, n=14):
    h,l,c = df["high"],df["low"],df["close"]
    tr = pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    return tr.ewm(alpha=1/n, adjust=False).mean()

def signals(df):
    H,L,C = df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy()
    sig = np.zeros(len(df), int); armed=False; mh=ml=0.0
    for i in range(1,len(df)):
        is_inside = H[i]<H[i-1] and L[i]>L[i-1]
        if is_inside and not armed:
            armed=True; mh=H[i-1]; ml=L[i-1]
        elif armed:
            if C[i]>mh: sig[i]=1; armed=False
            elif C[i]<ml: sig[i]=-1; armed=False
            elif not is_inside: armed=False
    return pd.Series(sig, index=df.index)

def backtest(df, sig, frac=1.0, slip=0.0005):
    c=df["close"].to_numpy(float); hi=df["high"].to_numpy(float); lo=df["low"].to_numpy(float)
    a=atr_wilder(df,14).to_numpy(float); s=sig.to_numpy()
    eq=1.0; pos=0; entry=0.0; tp=sl=0.0; eb=-1; rets=[]; tss=[]; curve=[]
    for i in range(len(df)):
        if pos!=0 and i>eb:
            cl=None
            if pos==1:
                if lo[i]<=sl: cl=sl/entry-1
                elif hi[i]>=tp: cl=tp/entry-1
            else:
                if hi[i]>=sl: cl=entry/sl-1
                elif lo[i]<=tp: cl=entry/tp-1
            if cl is not None:
                eq*=(1+frac*(cl-FEE)); rets.append(cl-FEE); tss.append(df.index[i]); pos=0
        if s[i]!=0 and s[i]!=pos:
            if pos!=0:
                r=(c[i]/entry-1) if pos==1 else (entry/c[i]-1)
                eq*=(1+frac*(r-FEE)); rets.append(r-FEE); tss.append(df.index[i])
            entry = c[i]*(1+slip) if s[i]==1 else c[i]*(1-slip)
            pos=int(s[i]); eb=i; eq*=(1-frac*FEE)
            if pos==1: tp=entry+TP_MULT*a[i]; sl=entry-SL_MULT*a[i]
            else: tp=entry-TP_MULT*a[i]; sl=entry+SL_MULT*a[i]
        curve.append(eq)
    return pd.Series(curve,index=df.index), np.array(rets), tss

def stats(eq, rets):
    if len(rets)==0: return dict(net=0,wr=0,n=0,dd=0,pf=0)
    net=(eq.iloc[-1]-1)*100; wr=round((rets>0).mean()*100)
    dd=((eq/eq.cummax())-1).min()*100
    gw=rets[rets>0].sum(); gl=-rets[rets<0].sum()
    return dict(net=net, wr=wr, n=len(rets), dd=dd, pf=round(gw/gl,2) if gl else 99)

if __name__=="__main__":
    print(f"===== CANON Inside Bar 4h TP{TP_MULT:g}/SL{SL_MULT:g} fee{FEE*200:.2f}% slip0.05% =====")
    for pair in ("BTCUSDT","ETHUSDT","XRPUSDT"):
        df=load_4h(pair); sig=signals(df); eq,rets,tss=backtest(df,sig)
        st=stats(eq,rets); bh=(df["close"].iloc[-1]/df["close"].iloc[0]-1)*100
        print(f"\n{pair}: net={st['net']:+.1f}% (B&H {bh:+.0f}%) PF={st['pf']} WR={st['wr']}% DD={st['dd']:.1f}% n={st['n']}")
        ser=pd.Series(rets,index=pd.to_datetime(tss))
        for y,g in ser.groupby(ser.index.year):
            print(f"    {y}: {((1+g).cumprod().iloc[-1]-1)*100:+.1f}%  (n={len(g)})")
