"""Inside Bar 4h — honest replication + reconciliation with Mac (+281%).
Tests: conservative fills, commission, and 4h-bar-boundary sensitivity (the likely cause of the
+142% (Win) vs +281% (Mac TV) gap — different 4h anchors -> different inside bars -> different trades.
If net swings wildly with the offset, the edge is bar-alignment-fragile = not robust."""
import numpy as np, pandas as pd
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
RAW = pd.read_csv(ROOT/"backtests/frozen/BTCUSDT_1h_2y.csv")
RAW["ts"] = pd.to_datetime(RAW["ts"], unit="ms", utc=True)
RAW = RAW.set_index("ts")
COM = 0.00075

def bt(offset_h=0, use_filt=True, com=COM, tpM=5.0, slM=3.0):
    d4 = RAW.resample("4h", offset=f"{offset_h}h").agg(
        {"open":"first","high":"max","low":"min","close":"last"}).dropna()
    h,l,c = d4["high"].values, d4["low"].values, d4["close"].values
    tr = np.maximum(h[1:]-l[1:], np.maximum(abs(h[1:]-c[:-1]), abs(l[1:]-c[:-1])))
    atr=np.full(len(c),np.nan); a=tr[0]
    for i in range(2,len(c)): a=(a*13+tr[i-1])/14; atr[i]=a
    atrpct=atr/c; med=pd.Series(atrpct).rolling(100).median().values
    eq=1.0; pos=0; ep=0.0; ea=0.0; wins=0; n=0
    def closep(px):
        nonlocal eq,pos,wins,n
        r=(px/ep-1)*pos-2*com; eq*=(1+r); wins+= (r>0); n+=1; pos=0
    for i in range(3,len(c)):
        if pos!=0:
            tp=ep+tpM*ea*pos; sl=ep-slM*ea*pos
            if pos>0: tph,slh=h[i]>=tp,l[i]<=sl
            else: tph,slh=l[i]<=tp,h[i]>=sl
            hit='sl' if (tph and slh) else ('tp' if tph else ('sl' if slh else None))
            if hit: closep(tp if hit=='tp' else sl)
        inside=h[i-1]<h[i-2] and l[i-1]>l[i-2]
        filt=(not use_filt) or (atrpct[i]>=med[i] if not np.isnan(med[i]) else False)
        lS=inside and c[i]>h[i-2] and filt; sS=inside and c[i]<l[i-2] and filt
        if lS and pos<=0:
            if pos<0: closep(c[i])
            pos=1; ep=c[i]; ea=atr[i]
        elif sS and pos>=0:
            if pos>0: closep(c[i])
            pos=-1; ep=c[i]; ea=atr[i]
    return (eq-1)*100, n, (100*wins/n if n else 0)

print("=== 4h-ГРАНИЦА: чувствительность к якорю бара (вероятная причина gap Win vs Mac) ===")
print(f"{'offset':>7}{'фильтр net%':>13}{'сделок':>8}{'WR':>6}   {'baseline net%':>14}")
nets=[]
for off in (0,1,2,3):
    nf,n,wr=bt(off,True); nb,_,_=bt(off,False); nets.append(nf)
    print(f"{off:>6}h{nf:13.0f}{n:8d}{wr:6.0f}   {nb:14.0f}")
import numpy as np
print(f"\n  РАЗБРОС фильтр-net по 4 якорям: {min(nets):.0f}% .. {max(nets):.0f}%  "
      f"(среднее {np.mean(nets):.0f}, разброс {max(nets)-min(nets):.0f}pp)")
print("  → если разброс большой = результат зависит от того, ГДЕ режешь 4ч = НЕ робастно (и Win, и Mac — точки облака).")
