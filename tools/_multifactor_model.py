"""Multi-factor breakout model: Inside Bar core + stacked confirmations, with
regime-aware behavior. Operator's point (right): a 1-indicator strategy already
hits PF 1.98 — stacking real confirmations (RSI, volume, OBV-divergence, trend
regime) should make it cleaner. Each layer is a GATE that must agree; we measure
how PF/DD/per-year move as we add layers, keeping only what helps in ALL years.

Core: CANON Inside Bar (armed-cluster, mother breakout), ATR(14w) TP5/SL3, fee
0.15%+slip. Layers (toggled):
  R  RSI confirm: long needs RSI>50 rising, short RSI<50 falling (momentum align)
  V  volume confirm: breakout bar volume > 1.2x its 20-bar avg (real participation)
  O  OBV trend: OBV slope agrees with breakout side (smart-money flow)
  T  regime: ADX-style — only trade when trending (DI gap), skip pure chop
We test core, each layer alone, and the full stack. Per-year validated.
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

def rsi(c,n=14):
    d=c.diff(); up=d.clip(lower=0).ewm(alpha=1/n,adjust=False).mean()
    dn=(-d.clip(upper=0)).ewm(alpha=1/n,adjust=False).mean()
    return 100-100/(1+up/dn.replace(0,np.nan))

def obv(df):
    sign=np.sign(df["close"].diff()).fillna(0)
    return (sign*df["volume"]).cumsum()

def adx(df,n=14):
    up=df["high"].diff(); dn=-df["low"].diff()
    plus=np.where((up>dn)&(up>0),up,0.0); minus=np.where((dn>up)&(dn>0),dn,0.0)
    tr=atr_w(df,n)*n  # approx
    pdi=100*pd.Series(plus,index=df.index).ewm(alpha=1/n,adjust=False).mean()/tr.replace(0,np.nan)
    mdi=100*pd.Series(minus,index=df.index).ewm(alpha=1/n,adjust=False).mean()/tr.replace(0,np.nan)
    dx=100*(pdi-mdi).abs()/(pdi+mdi).replace(0,np.nan)
    return dx.ewm(alpha=1/n,adjust=False).mean()

def signals(df, big_break=0.15, vol_floor=1.2, use_R=False, use_V=False, use_O=False, use_T=False):
    H=df["high"].to_numpy(); L=df["low"].to_numpy(); C=df["close"].to_numpy()
    a=atr_w(df,14).to_numpy(); a_med=pd.Series(a).rolling(100).median().to_numpy()
    r=rsi(df["close"]).to_numpy(); r_prev=pd.Series(r).shift().to_numpy()
    v=df["volume"].to_numpy(); v_avg=df["volume"].rolling(20).mean().to_numpy()
    ob=obv(df); ob_slope=ob.diff(5).to_numpy()
    ad=adx(df).to_numpy()
    sig=np.zeros(len(df),int); armed=False; mh=ml=0.0
    for i in range(20,len(df)):
        is_inside=H[i]<H[i-1] and L[i]>L[i-1]
        if is_inside and not armed:
            armed=True; mh=H[i-1]; ml=L[i-1]
        elif armed:
            longb=C[i]>mh+big_break*a[i]; shortb=C[i]<ml-big_break*a[i]
            ok_vol=(vol_floor==0) or (not np.isnan(a_med[i]) and a[i]>=vol_floor*a_med[i])
            if (longb or shortb) and ok_vol:
                side=1 if longb else -1
                ok=True
                if use_R: ok&= (r[i]>50 and r[i]>r_prev[i]) if side==1 else (r[i]<50 and r[i]<r_prev[i])
                if use_V: ok&= v[i]>1.2*v_avg[i] if not np.isnan(v_avg[i]) else False
                if use_O: ok&= (ob_slope[i]>0) if side==1 else (ob_slope[i]<0)
                if use_T: ok&= ad[i]>20 if not np.isnan(ad[i]) else False
                if ok: sig[i]=side; armed=False
                else: armed=False
            elif not is_inside: armed=False
    return pd.Series(sig,index=df.index)

def bt(df,sig):
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
            if cl is not None: eq*=(1+cl-FEE); rets.append(cl-FEE); tss.append(df.index[i]); pos=0
        if s[i]!=0 and s[i]!=pos:
            if pos!=0:
                rr=(c[i]/entry-1) if pos==1 else (entry/c[i]-1); eq*=(1+rr-FEE); rets.append(rr-FEE); tss.append(df.index[i])
            entry=c[i]*(1+SLIP) if s[i]==1 else c[i]*(1-SLIP); pos=int(s[i]); eb=i; eq*=(1-FEE)
            if pos==1: tp=entry+TP_MULT*a[i]; sl=entry-SL_MULT*a[i]
            else: tp=entry-TP_MULT*a[i]; sl=entry+SL_MULT*a[i]
        curve.append(eq)
    return pd.Series(curve,index=df.index),np.array(rets),tss

def report(name,df,**kw):
    eq,rets,tss=bt(df,signals(df,**kw))
    if len(rets)<5: print(f"{name:22} only {len(rets)} trades (skip)"); return
    net=(eq.iloc[-1]-1)*100; wr=round((rets>0).mean()*100); dd=((eq/eq.cummax())-1).min()*100
    gw=rets[rets>0].sum(); gl=-rets[rets<0].sum(); pf=round(gw/gl,2) if gl else 99
    ser=pd.Series(rets,index=pd.to_datetime(tss)); yv={y:((1+g).cumprod().iloc[-1]-1)*100 for y,g in ser.groupby(ser.index.year)}
    allpos="YES" if all(v>0 for v in yv.values()) else "no"
    yrs=" ".join(f"{y}:{v:+.0f}" for y,v in yv.items())
    print(f"{name:22} net={net:+7.1f}% PF={pf:>4} WR={wr}% DD={dd:>6.1f}% n={len(rets):>3} all+={allpos:3}|{yrs}")

df=load_4h("BTCUSDT")
print("===== MULTI-FACTOR BTC (Inside Bar core + confirmations, per-year) =====")
report("core(big.15+vol1.2)", df)
report("+RSI", df, use_R=True)
report("+Volume", df, use_V=True)
report("+OBV", df, use_O=True)
report("+ADX-trend", df, use_T=True)
report("+RSI+OBV", df, use_R=True, use_O=True)
report("+RSI+ADX", df, use_R=True, use_T=True)
report("+OBV+ADX", df, use_O=True, use_T=True)
report("FULL stack RVOТ", df, use_R=True, use_V=True, use_O=True, use_T=True)
report("RSI+OBV+ADX", df, use_R=True, use_O=True, use_T=True)
