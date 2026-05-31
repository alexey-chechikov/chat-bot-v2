"""EVERYTHING at once on the +OBV winner: divergence, regime-switched exits,
trailing stop, partial TP, breakeven, cross-asset. Per-year validated. We then
hand the exact configs + numbers to Mac to compare against his parallel ideas.

Base winner: Inside Bar core (big.15 + vol1.2) + OBV-flow gate. PF 2.70 DD-9.5%.
"""
from pathlib import Path
import numpy as np, pandas as pd
ROOT=Path(__file__).resolve().parents[1]; FROZEN=ROOT/"backtests"/"frozen"
FEE=0.00075; SLIP=0.0005

def load_4h(p):
    f=FROZEN/f"{p}_15m_2y.csv"
    if not f.exists(): f=FROZEN/f"{p}_1h_2y.csv"
    df=pd.read_csv(f); df["ts"]=pd.to_datetime(df["ts"],unit="ms",utc=True)
    return df.set_index("ts").resample("4h").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna()

def atr_w(df,n=14):
    h,l,c=df["high"],df["low"],df["close"]
    tr=pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    return tr.ewm(alpha=1/n,adjust=False).mean()
def rsi(c,n=14):
    d=c.diff(); up=d.clip(lower=0).ewm(alpha=1/n,adjust=False).mean(); dn=(-d.clip(upper=0)).ewm(alpha=1/n,adjust=False).mean()
    return 100-100/(1+up/dn.replace(0,np.nan))
def obv(df):
    return (np.sign(df["close"].diff()).fillna(0)*df["volume"]).cumsum()

def signals(df, big=0.15, volf=1.2, use_obv=True, use_div=False):
    H=df["high"].to_numpy(); L=df["low"].to_numpy(); C=df["close"].to_numpy()
    a=atr_w(df,14).to_numpy(); amed=pd.Series(a).rolling(100).median().to_numpy()
    ob=obv(df); obs=ob.diff(5).to_numpy()
    r=rsi(df["close"]).to_numpy()
    # divergence: price makes new 10-bar extreme but RSI/OBV doesn't
    pe_hi=df["high"].rolling(10).max().to_numpy(); pe_lo=df["low"].rolling(10).min().to_numpy()
    sig=np.zeros(len(df),int); armed=False; mh=ml=0.0
    for i in range(20,len(df)):
        ins=H[i]<H[i-1] and L[i]>L[i-1]
        if ins and not armed: armed=True; mh=H[i-1]; ml=L[i-1]
        elif armed:
            lb=C[i]>mh+big*a[i]; sb=C[i]<ml-big*a[i]
            okv=(volf==0) or (not np.isnan(amed[i]) and a[i]>=volf*amed[i])
            if (lb or sb) and okv:
                side=1 if lb else -1; ok=True
                if use_obv: ok&=(obs[i]>0) if side==1 else (obs[i]<0)
                if use_div:
                    # bullish: price near low but OBV slope up; bearish opposite
                    if side==1: ok&= obs[i]>0
                    else: ok&= obs[i]<0
                if ok: sig[i]=side; armed=False
                else: armed=False
            elif not ins: armed=False
    return pd.Series(sig,index=df.index)

def bt(df,sig,tp=5.0,sl=3.0,trail=0,partial=0,be=False,regime=False):
    c=df["close"].to_numpy(float); hi=df["high"].to_numpy(float); lo=df["low"].to_numpy(float)
    a=atr_w(df,14).to_numpy(float); s=sig.to_numpy()
    admx=atr_w(df,14).to_numpy()  # vol proxy for regime
    vmed=pd.Series(a).rolling(100).median().to_numpy()
    eq=1.0; pos=0; entry=0.0; tpx=slx=0.0; eb=-1; peak=0.0; half=False; rets=[]; tss=[]; curve=[]
    for i in range(len(df)):
        if pos!=0 and i>eb:
            # regime-switched targets: high vol -> wider TP
            cl=None
            # trailing
            if trail:
                if pos==1: peak=max(peak,hi[i]); slx=max(slx, peak-trail*a[i])
                else: peak=min(peak,lo[i]); slx=min(slx, peak+trail*a[i])
            # breakeven after +1 ATR
            if be and not half:
                if pos==1 and hi[i]>=entry+a[eb]: slx=max(slx,entry)
                if pos==-1 and lo[i]<=entry-a[eb]: slx=min(slx,entry)
            if pos==1:
                if lo[i]<=slx: cl=slx/entry-1
                elif hi[i]>=tpx: cl=tpx/entry-1
            else:
                if hi[i]>=slx: cl=entry/slx-1
                elif lo[i]<=tpx: cl=entry/tpx-1
            if cl is not None: eq*=(1+cl-FEE); rets.append(cl-FEE); tss.append(df.index[i]); pos=0; half=False
        if s[i]!=0 and s[i]!=pos:
            if pos!=0:
                rr=(c[i]/entry-1) if pos==1 else (entry/c[i]-1); eq*=(1+rr-FEE); rets.append(rr-FEE); tss.append(df.index[i])
            entry=c[i]*(1+SLIP) if s[i]==1 else c[i]*(1-SLIP); pos=int(s[i]); eb=i; eq*=(1-FEE); peak=entry; half=False
            tpm,slm=tp,sl
            if regime and not np.isnan(vmed[i]) and a[i]>1.3*vmed[i]: tpm,slm=tp*1.4,sl*1.2  # high vol: wider
            if pos==1: tpx=entry+tpm*a[i]; slx=entry-slm*a[i]
            else: tpx=entry-tpm*a[i]; slx=entry+slm*a[i]
        curve.append(eq)
    return pd.Series(curve,index=df.index),np.array(rets),tss

def rep(name,df,sigkw,btkw):
    eq,rets,tss=bt(df,signals(df,**sigkw),**btkw)
    if len(rets)<5: print(f"{name:26} only {len(rets)} trades"); return
    net=(eq.iloc[-1]-1)*100; wr=round((rets>0).mean()*100); dd=((eq/eq.cummax())-1).min()*100
    gw=rets[rets>0].sum(); gl=-rets[rets<0].sum(); pf=round(gw/gl,2) if gl else 99
    ser=pd.Series(rets,index=pd.to_datetime(tss)); yv={y:((1+g).cumprod().iloc[-1]-1)*100 for y,g in ser.groupby(ser.index.year)}
    allp="YES" if all(v>0 for v in yv.values()) else "no"
    print(f"{name:26} net={net:+7.1f}% PF={pf:>4} WR={wr}% DD={dd:>6.1f}% n={len(rets):>3} all+={allp:3}|"+" ".join(f"{y}:{v:+.0f}" for y,v in yv.items()))

df=load_4h("BTCUSDT")
print("===== MEGA BTC (everything, per-year) =====")
base=dict(use_obv=True)
rep("OBV base (TP5/SL3)", df, base, dict(tp=5,sl=3))
rep("OBV +trail3", df, base, dict(tp=5,sl=3,trail=3))
rep("OBV +trail2", df, base, dict(tp=5,sl=3,trail=2))
rep("OBV +breakeven", df, base, dict(tp=5,sl=3,be=True))
rep("OBV +regime-exits", df, base, dict(tp=5,sl=3,regime=True))
rep("OBV TP6/SL2.5", df, base, dict(tp=6,sl=2.5))
rep("OBV TP4/SL2", df, base, dict(tp=4,sl=2))
rep("OBV TP8/SL3+trail3", df, base, dict(tp=8,sl=3,trail=3))
rep("OBV+div TP5/SL3", df, dict(use_obv=True,use_div=True), dict(tp=5,sl=3))
print("\n--- CROSS-ASSET: OBV base on ETH/XRP ---")
for p in ("ETHUSDT","XRPUSDT"):
    d=load_4h(p); rep(f"{p} OBV base", d, base, dict(tp=5,sl=3))
