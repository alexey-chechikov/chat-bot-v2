"""Last honest check (operator video insight: 'entry was never the problem,
the exits were'). Same REAL detectors, same 2y BTC, but sweep exit params:
wider TP, wider/looser SL, longer hold. If NO exit combo turns EV positive
net of fees, the mean-reversion setups are genuinely dead — not a tuning issue.
"""
import sys
from datetime import timedelta
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.setup_detector.setup_types import (
    detect_long_pdl_bounce, detect_long_dump_reversal, DetectionContext,
    detect_short_rally_fade, detect_short_pdh_rejection, detect_short_overbought_fade,
)
try:
    from services.setup_detector.double_top_bottom import detect_double_top_setup
except Exception:
    detect_double_top_setup = None

FEES = 0.165
STEP_MIN, M1_WIN, H1_WIN = 15, 60, 60
FROZEN = ROOT / "backtests" / "frozen"
# (TP%, SL%, HOLD_min) grid
GRID = [(1.5,0.5,120),(2.0,1.0,240),(3.0,1.5,480),(1.0,1.0,120),(2.5,2.0,720),(0.7,0.4,360)]

def _load(pair):
    df = pd.read_csv(FROZEN/f"{pair}_1m_2y.csv")
    df["ts"]=pd.to_datetime(df["ts"],unit="ms",utc=True)
    return df.set_index("ts")[["open","high","low","close","volume"]].sort_index()

def _regime(h1,price):
    if len(h1)<5: return "range_wide"
    p4=float(h1["close"].iloc[-5]); chg=(price/p4-1)*100 if p4 else 0
    return "trend_up" if chg>1 else "trend_down" if chg<-1 else "range_wide"

def collect_signals(pair):
    """Run detectors ONCE, store (entry_pos, side); exits simmed per-grid after."""
    m1=_load(pair)
    h1=m1.resample("1h").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna()
    h1_ns=h1.index.astype("int64").to_numpy(); m1_idx=m1.index
    cl=m1["close"].to_numpy(float)
    sigs=[]
    for pos in range(M1_WIN,len(m1)-720,STEP_MIN):
        t=m1_idx[pos]
        hpos=int(np.searchsorted(h1_ns,t.value,side="right"))
        if hpos<16: continue
        h1_win=h1.iloc[max(0,hpos-H1_WIN):hpos]; price=float(cl[pos])
        ctx=DetectionContext(pair=pair,current_price=price,regime_label=_regime(h1_win,price),
                             session_label="ANY",ohlcv_1m=m1.iloc[pos-M1_WIN:pos+1],ohlcv_1h=h1_win)
        for fn,name,side in [(detect_long_dump_reversal,"dump","long"),(detect_long_pdl_bounce,"pdl","long"),
                (detect_short_rally_fade,"rally","short"),(detect_short_pdh_rejection,"pdh","short"),
                (detect_short_overbought_fade,"ob","short")]+([(detect_double_top_setup,"dt","short")] if detect_double_top_setup else []):
            try: s=fn(ctx)
            except Exception: s=None
            if s is not None:
                sigs.append((pos,side)); break
    return m1,sigs

def sim(m1,sigs,TP,SL,HOLD):
    hi=m1["high"].to_numpy(float); lo=m1["low"].to_numpy(float); cl=m1["close"].to_numpy(float)
    pnls=[]; last=-1
    for pos,side in sigs:
        if pos<last: continue
        entry=cl[pos]; end=pos+HOLD
        if end>=len(hi): continue
        r=None
        if side=="long":
            tp,sl=entry*(1+TP/100),entry*(1-SL/100)
            for i in range(pos,end):
                if lo[i]<=sl: r=-SL-FEES;break
                if hi[i]>=tp: r=TP-FEES;break
            if r is None: r=(cl[end-1]/entry-1)*100-FEES
        else:
            tp,sl=entry*(1-TP/100),entry*(1+SL/100)
            for i in range(pos,end):
                if hi[i]>=sl: r=-SL-FEES;break
                if lo[i]<=tp: r=TP-FEES;break
            if r is None: r=(entry/cl[end-1]-1)*100-FEES
        pnls.append(r); last=pos+HOLD
    return pnls

def main():
    pair=sys.argv[1] if len(sys.argv)>1 else "BTCUSDT"
    print(f"===== {pair} EXIT SWEEP (2y, real detectors) =====")
    m1,sigs=collect_signals(pair)
    print(f"signals collected: {len(sigs)}")
    print(f"{'TP':>4} {'SL':>4} {'HOLD':>5} | {'n':>5} {'WR':>4} {'EV/tr':>8} {'sum':>9}")
    for TP,SL,HOLD in GRID:
        p=sim(m1,sigs,TP,SL,HOLD)
        if not p: print(f"{TP:>4} {SL:>4} {HOLD:>5} | no trades"); continue
        n=len(p); wr=round(sum(1 for x in p if x>0)/n*100); ev=round(sum(p)/n,3); sm=round(sum(p),1)
        flag=" <-- POSITIVE" if ev>0 else ""
        print(f"{TP:>4} {SL:>4} {HOLD:>5} | {n:>5} {wr:>3}% {ev:>+8.3f} {sm:>+8.1f}%{flag}")

if __name__=="__main__": main()
