"""Independent price-path/cash audit; does not import the replay implementation."""
from pathlib import Path
import hashlib
import json
import math
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parent
SOURCE=ROOT.parent/'expectancy_20261006/public_data'
MINUTE=60_000

def main():
    prices=pd.read_csv(SOURCE/'binance_futures_ETHUSDT_1m.csv')
    times=prices.ts.to_numpy(dtype=np.int64)
    o=prices.open.to_numpy(); h=prices.high.to_numpy(); l=prices.low.to_numpy()
    index={int(t):i for i,t in enumerate(times)}
    funding=pd.read_csv(SOURCE/'binance_futures_ETHUSDT_funding.csv')
    frecords=list(funding.itertuples(index=False))
    report=json.loads((ROOT/'REPORT.json').read_bytes())
    cases=[('static_all_in_4bp',.0004,0.,0.,.0004),
           ('static_all_in_8bp',.0008,0.,0.,.0008),
           ('decomposed_fee1bp_slip1bp',0.,.0001,.0001,.0004),
           ('decomposed_fee1bp_slip3bp',0.,.0001,.0003,.0008)]
    audits=[]
    for name,flat,fee,slip,reserve in cases:
        path=ROOT/f'ledger_{name}.csv'
        raw=path.read_bytes()
        ledger=pd.read_csv(path)
        assert len(ledger)==174 and ledger.status.eq('completed').all()
        errors=[]; entry_times=[]
        for row in ledger.itertuples(index=False):
            t=int(row.signal_time); i=index[t]; side=int(row.side)
            entry=o[i]*(1+side*slip)
            q=min(1000/entry,10/(entry*(.009+reserve)))
            stop=entry*(1-side*.009); target=entry*(1+side*.018)
            chosen=None
            for offset in range(121):
                j=i+offset; ts=int(times[j])
                assert ts==t+offset*MINUTE
                op=float(o[j])
                if side*(op-stop)<=0:
                    chosen=(ts,ts,op,'open'); break
                if side*(op-target)>=0:
                    chosen=(ts,ts,target,'open'); break
                if offset==120:
                    chosen=(ts,ts,op,'open'); break
                stop_hit=(l[j]<=stop if side==1 else h[j]>=stop)
                target_hit=(h[j]>=target if side==1 else l[j]<=target)
                if stop_hit or target_hit:
                    chosen=(ts,ts+MINUTE-1,stop if stop_hit else target,'intraminute'); break
            exit_bar,exit_ts,x,kind=chosen
            assert exit_ts==int(row.exit_time) and exit_bar==int(row.exit_bar)
            assert kind==row.execution_kind
            exit_exec=x*(1-side*slip)
            lo=hi=0.
            if fee:
                for f in frecords:
                    ft=int(f.fundingTime)
                    if t < ft <= exit_ts:
                        cash=-side*q*float(f.fundingRate)*float(f.markPrice)
                        uncertain=(kind=='intraminute' and ft>exit_bar) or (kind=='open' and ft==exit_ts)
                        lo+=min(0,cash) if uncertain else cash
                        hi+=max(0,cash) if uncertain else cash
            net=q*side*(exit_exec-entry)-fee*q*(entry+exit_exec)-flat*q*entry+lo
            errors.extend([abs(entry-row.entry_exec),abs(q-row.quantity),abs(x-row.exit_raw),
                           abs(lo-row.funding_usd),abs(hi-row.funding_upper_usd),abs(net-row.net_usd)])
            assert row.entry_notional<=1000+1e-8
            assert q*(abs(entry-stop)+reserve*entry)<=10+1e-8
            entry_times.append(t)
        assert max(errors)<1e-8
        assert all(b-a>=121*MINUTE for a,b in zip(entry_times,entry_times[1:]))
        published=next(s for s in report['scenarios'] if s['scenario']==name)
        assert abs(ledger.net_usd.sum()-published['net_total_usd'])<1e-8
        assert abs(ledger.sort_values('net_usd').iloc[:-3].net_usd.sum()-published['after_remove_best_three_total_usd'])<1e-8
        points=pd.read_csv(ROOT/f'equity_points_{name}.csv')
        assert points.ts.diff().dropna().ge(0).all()
        dd=float((points.pnl_usd.cummax()-points.pnl_usd).max())
        assert abs(dd-published['max_DD_liquidation_point_usd'])<1e-8
        assert abs(points.pnl_usd.iloc[-1]-ledger.net_usd.sum())<1e-8
        audits.append({'scenario':name,'trades_checked':len(ledger),'max_numeric_error':max(errors),
                       'ledger_sha256':hashlib.sha256(raw).hexdigest(),'net_usd':float(ledger.net_usd.sum()),
                       'price_path_cash_size_deadline_and_summary':'PASS'})
    out={'status':'PASS','independent_implementation_imported':False,'network_calls':0,
         'source_1m_rows':len(prices),'trade_paths_checked':sum(x['trades_checked'] for x in audits),
         'scenarios':audits,'limitations':'Numerical/chronology QA is not out-of-sample or execution validation.'}
    (ROOT/'ROOT_INDEPENDENT_QA.json').write_text(json.dumps(out,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(out))

if __name__=='__main__':main()
