"""Get the trade count UP (18 is statistical noise) while keeping PF healthy.
Three levers: timeframe (1h/2h/4h), filter strength (loosen vol/big gates),
portfolio (BTC+ETH+XRP pooled). Per-year validated. Find configs with n>=100.
"""
from pathlib import Path
import numpy as np, pandas as pd
ROOT=Path(__file__).resolve().parents[1]; FROZEN=ROOT/"backtests"/"frozen"
FEE=0.00075; SLIP=0.0005

def load_tf(p, tf):
    src=FROZEN/f"{p}_15m_2y.csv"
    if not src.exists(): src=FROZEN/f"{p}_1h_2y.csv"
    df=pd.read_csv(src); df["ts"]=pd.to_datetime(df["ts"],unit="ms",utc=True)
    return df.set_index("ts").resample(tf).agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna()

def atr_w(df,n=14):
    h,l,c=df["high"],df["low"],df["close"]
    tr=pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    return tr.ewm(alpha=1/n,adjust=False).mean()
def obv(df): return (np.sign(df["close"].diff()).fillna(0)*df["volume"]).cumsum()

def signals(df, big, volf, use_obv):
    H=df["high"].to_numpy(); L=df["low"].to_numpy(); C=df["close"].to_numpy()
    a=atr_w(df,14).to_numpy(); amed=pd.Series(a).rolling(100).median().to_numpy()
    obs=obv(df).diff(5).to_numpy()
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
                if ok: sig[i]=side; armed=False
                else: armed=False
            elif not ins: armed=False
    return pd.Series(sig,index=df.index)

def bt(df,sig,tp=5,sl=3,regime=True):
    c=df["close"].to_numpy(float); hi=df["high"].to_numpy(float); lo=df["low"].to_numpy(float)
    a=atr_w(df,14).to_numpy(float); s=sig.to_numpy(); vmed=pd.Series(a).rolling(100).median().to_numpy()
    eq=1.0; pos=0; entry=0.0; tpx=slx=0.0; eb=-1; rets=[]; tss=[]; curve=[]
    for i in range(len(df)):
        if pos!=0 and i>eb:
            cl=None
            if pos==1:
                if lo[i]<=slx: cl=slx/entry-1
                elif hi[i]>=tpx: cl=tpx/entry-1
            else:
                if hi[i]>=slx: cl=entry/slx-1
                elif lo[i]<=tpx: cl=entry/tpx-1
            if cl is not None: eq*=(1+cl-FEE); rets.append(cl-FEE); tss.append(df.index[i]); pos=0
        if s[i]!=0 and s[i]!=pos:
            if pos!=0:
                rr=(c[i]/entry-1) if pos==1 else (entry/c[i]-1); eq*=(1+rr-FEE); rets.append(rr-FEE); tss.append(df.index[i])
            entry=c[i]*(1+SLIP) if s[i]==1 else c[i]*(1-SLIP); pos=int(s[i]); eb=i; eq*=(1-FEE)
            tpm,slm=tp,sl
            if regime and not np.isnan(vmed[i]) and a[i]>1.3*vmed[i]: tpm,slm=tp*1.4,sl*1.2
            if pos==1: tpx=entry+tpm*a[i]; slx=entry-slm*a[i]
            else: tpx=entry-tpm*a[i]; slx=entry+slm*a[i]
        curve.append(eq)
    return pd.Series(curve,index=df.index),np.array(rets),tss

def metrics(rets):
    if len(rets)==0: return 0,0,0,0
    wr=round((rets>0).mean()*100); gw=rets[rets>0].sum(); gl=-rets[rets<0].sum()
    return wr, round(gw/gl,2) if gl else 99, len(rets), rets

def rep(name,df,big,volf,obvf,tf):
    eq,rets,tss=bt(df,signals(df,big,volf,obvf))
    if len(rets)<5: print(f"{name:30} n={len(rets)} (skip)"); return
    wr,pf,n,_=metrics(rets); net=(eq.iloc[-1]-1)*100; dd=((eq/eq.cummax())-1).min()*100
    ser=pd.Series(rets,index=pd.to_datetime(tss)); yv={y:((1+g).cumprod().iloc[-1]-1)*100 for y,g in ser.groupby(ser.index.year)}
    allp="YES" if all(v>0 for v in yv.values()) else "no"
    flag=" <<<" if (n>=100 and pf>=1.6 and allp=="YES") else ""
    print(f"{name:30} net={net:+7.0f}% PF={pf:>4} WR={wr}% DD={dd:>6.0f}% n={n:>3} all+={allp:3}{flag}")

print("===== MORE TRADES: TF x filter strength (BTC) =====")
for tf in ("4h","2h","1h"):
    df=load_tf("BTCUSDT",tf)
    print(f"--- TF={tf} (bars={len(df)}) ---")
    rep(f"  tight big.15 vol1.2 obv", df, 0.15,1.2,True,tf)
    rep(f"  med   big.10 vol1.0 obv", df, 0.10,1.0,True,tf)
    rep(f"  loose big.05 vol0.8 obv", df, 0.05,0.8,True,tf)
    rep(f"  loose noVolfloor obv",    df, 0.05,0.0,True,tf)
    rep(f"  loose noOBV noVol",       df, 0.05,0.0,False,tf)

print("\n===== PORTFOLIO BTC+ETH+XRP pooled (4h, loosened) =====")
allrets=[]; allts=[]
for p in ("BTCUSDT","ETHUSDT","XRPUSDT"):
    d=load_tf(p,"4h"); _,r,t=bt(d,signals(d,0.10,1.0,True))
    allrets+=list(r); allts+=list(t)
ser=pd.Series(allrets,index=pd.to_datetime(allts)).sort_index()
wr,pf,n,_=metrics(np.array(allrets))
eqp=(1+ser).cumprod(); netp=(eqp.iloc[-1]-1)*100; ddp=((eqp/eqp.cummax())-1).min()*100
yv={y:((1+g).cumprod().iloc[-1]-1)*100 for y,g in ser.groupby(ser.index.year)}
print(f"  3-asset pooled big.10 vol1.0 obv: net={netp:+.0f}% PF={pf} WR={wr}% DD={ddp:.0f}% n={n} | "+" ".join(f"{y}:{v:+.0f}" for y,v in yv.items()))
