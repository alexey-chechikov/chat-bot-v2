"""IMPROVE the canonical BTC Inside Bar. Test filters that should cut the -36% DD
and raise PF, each validated per-year (no overfit). Keep only what helps in
ALL years. Filters tested (on top of CANON detector):

  base         : canonical, no filter
  +vol         : skip breakouts in the bottom-tercile ATR (dead chop = whipsaw)
  +trend200    : LONG only if close>EMA200, SHORT only if close<EMA200
  +trend50     : same with EMA50 (faster trend)
  +bigbreak    : require breakout to clear mother by >0.15*ATR (avoid fakeouts)
  +timestop    : exit after 12 bars (48h) if neither TP nor SL hit
  best-combo   : stack the winners
"""
from pathlib import Path
import numpy as np, pandas as pd
ROOT=Path(__file__).resolve().parents[1]; FROZEN=ROOT/"backtests"/"frozen"
FEE=0.00075; TP_MULT,SL_MULT=5.0,3.0; SLIP=0.0005

def load_4h(p="BTCUSDT"):
    df=pd.read_csv(FROZEN/f"{p}_15m_2y.csv"); df["ts"]=pd.to_datetime(df["ts"],unit="ms",utc=True)
    return df.set_index("ts").resample("4h").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna()

def atr_w(df,n=14):
    h,l,c=df["high"],df["low"],df["close"]
    tr=pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    return tr.ewm(alpha=1/n,adjust=False).mean()

def signals(df, vol_floor=0, big_break=0, trend=None):
    H=df["high"].to_numpy(); L=df["low"].to_numpy(); C=df["close"].to_numpy()
    a=atr_w(df,14).to_numpy(); a_med=pd.Series(a).rolling(100).median().to_numpy()
    ema=df["close"].ewm(span=trend).mean().to_numpy() if trend else None
    sig=np.zeros(len(df),int); armed=False; mh=ml=0.0
    for i in range(1,len(df)):
        is_inside=H[i]<H[i-1] and L[i]>L[i-1]
        if is_inside and not armed:
            armed=True; mh=H[i-1]; ml=L[i-1]
        elif armed:
            longb = C[i]>mh+big_break*a[i]
            shortb= C[i]<ml-big_break*a[i]
            ok_vol = (vol_floor==0) or (not np.isnan(a_med[i]) and a[i]>=vol_floor*a_med[i])
            if (longb or shortb) and ok_vol:
                if longb and (ema is None or C[i]>ema[i]): sig[i]=1; armed=False
                elif shortb and (ema is None or C[i]<ema[i]): sig[i]=-1; armed=False
                elif (longb or shortb): armed=False  # filtered out, disarm
            elif not is_inside: armed=False
    return pd.Series(sig,index=df.index)

def bt(df,sig,timestop=0):
    c=df["close"].to_numpy(float); hi=df["high"].to_numpy(float); lo=df["low"].to_numpy(float)
    a=atr_w(df,14).to_numpy(float); s=sig.to_numpy()
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
            if cl is None and timestop and (i-eb)>=timestop:
                cl=(c[i]/entry-1) if pos==1 else (entry/c[i]-1)
            if cl is not None: eq*=(1+cl-FEE); rets.append(cl-FEE); tss.append(df.index[i]); pos=0
        if s[i]!=0 and s[i]!=pos:
            if pos!=0:
                r=(c[i]/entry-1) if pos==1 else (entry/c[i]-1); eq*=(1+r-FEE); rets.append(r-FEE); tss.append(df.index[i])
            entry=c[i]*(1+SLIP) if s[i]==1 else c[i]*(1-SLIP); pos=int(s[i]); eb=i; eq*=(1-FEE)
            if pos==1: tp=entry+TP_MULT*a[i]; sl=entry-SL_MULT*a[i]
            else: tp=entry-TP_MULT*a[i]; sl=entry+SL_MULT*a[i]
        curve.append(eq)
    return pd.Series(curve,index=df.index),np.array(rets),tss

def report(name,df,sig,timestop=0):
    eq,rets,tss=bt(df,sig,timestop)
    if len(rets)==0: print(f"{name:16} no trades"); return
    net=(eq.iloc[-1]-1)*100; wr=round((rets>0).mean()*100); dd=((eq/eq.cummax())-1).min()*100
    gw=rets[rets>0].sum(); gl=-rets[rets<0].sum(); pf=round(gw/gl,2) if gl else 99
    ser=pd.Series(rets,index=pd.to_datetime(tss)); ys=ser.groupby(ser.index.year)
    yv={y:((1+g).cumprod().iloc[-1]-1)*100 for y,g in ys}
    allpos="YES" if all(v>0 for v in yv.values()) else "no"
    yrs=" ".join(f"{y}:{v:+.0f}" for y,v in yv.items())
    print(f"{name:16} net={net:+7.1f}% PF={pf:>4} WR={wr}% DD={dd:>6.1f}% n={len(rets):>3} all+={allpos:3} | {yrs}")

df=load_4h("BTCUSDT")
print("===== IMPROVE BTC Inside Bar (per-year validated) =====")
report("base", df, signals(df))
report("+vol1.0", df, signals(df,vol_floor=1.0))
report("+vol1.2", df, signals(df,vol_floor=1.2))
report("+trend200", df, signals(df,trend=200))
report("+trend50", df, signals(df,trend=50))
report("+bigbreak.15", df, signals(df,big_break=0.15))
report("+bigbreak.30", df, signals(df,big_break=0.30))
report("base+timestop12", df, signals(df), timestop=12)
report("vol1.2+big.15", df, signals(df,vol_floor=1.2,big_break=0.15))
report("vol1.2+big.15+ts12", df, signals(df,vol_floor=1.2,big_break=0.15), timestop=12)
