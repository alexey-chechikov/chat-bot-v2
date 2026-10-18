"""Explain old/new path changes and audit funding exit-boundary ambiguity."""
from pathlib import Path
import json
import numpy as np
import pandas as pd

OUT=Path(__file__).resolve().parent
SRC=OUT.parent/'expectancy_20261006'
old=pd.read_csv(SRC/'intraday/fresh_trades_ETHUSDT_intraday_impulse_follow_z2.5_h120.csv')
new=pd.read_csv(OUT/'ledger_static_all_in_4bp.csv')
assert len(old)==len(new)==174
old_ts=pd.to_datetime(old.entry_time,utc=True).to_numpy(dtype='datetime64[ms]').astype(np.int64)
old_exit_ts=pd.to_datetime(old.exit_time,utc=True).to_numpy(dtype='datetime64[ms]').astype(np.int64)
assert np.array_equal(old_ts,new.signal_time)
assert np.array_equal(old.side,new.side)
assert np.allclose(old.entry_mid,new.entry_mid,rtol=0,atol=0)
old_net=(old.gross.to_numpy()-.0004)*1000
new_net=new.net_usd.to_numpy()
new_reason=new.reason.replace({'stop_both':'stop'})
same_bar=old_exit_ts==new.exit_bar.to_numpy()
same_reason=old.reason.to_numpy()==new_reason.to_numpy()
same_price=np.isclose(old.exit_mid.to_numpy(),new.exit_raw.to_numpy(),rtol=0,atol=1e-9)
groups=np.where(same_bar&same_reason&same_price,'unchanged',np.where(same_bar&same_reason,'same_bar_reason_reanchored_price','changed_exit_bar_or_reason'))
compare=pd.DataFrame({'candidate':new.candidate,'signal_time':new.signal_time,'side':new.side,
    'old_exit_bar':old_exit_ts,'new_exit_bar':new.exit_bar,'old_reason':old.reason,'new_reason':new_reason,
    'entry_mid':new.entry_mid,'old_entry_slipped':old.entry_exec,'old_exit_raw':old.exit_mid,'new_exit_raw':new.exit_raw,
    'old_static_4bp_usd':old_net,'new_static_4bp_usd':new_net,'delta_usd':new_net-old_net,'change_group':groups})
compare.to_csv(OUT/'legacy_path_comparison.csv',index=False)
summary=[]
for name,g in compare.groupby('change_group'):
    summary.append({'group':name,'n':len(g),'delta_usd':float(g.delta_usd.sum())})
examples=compare.loc[groups!='unchanged'].iloc[np.argsort(-np.abs(compare.loc[groups!='unchanged'].delta_usd.to_numpy()))[:3]].to_dict(orient='records')
fund=pd.read_csv(SRC/'public_data/binance_futures_ETHUSDT_funding.csv')
further=[]
for scenario in ('decomposed_fee1bp_slip1bp','decomposed_fee1bp_slip3bp'):
    t=pd.read_csv(OUT/f'ledger_{scenario}.csv')
    for r in t.itertuples(index=False):
        if r.execution_kind!='open':continue
        matches=fund[fund.fundingTime.eq(r.exit_time)]
        for f in matches.itertuples(index=False):
            further.append({'scenario':scenario,'candidate':int(r.candidate),'time':int(r.exit_time),'reason':r.reason,
              'side':int(r.side),'potential_funding_usd':float(-r.side*r.quantity*f.fundingRate*f.markPrice)})
result={'old_static4_total_usd':float(old_net.sum()),'new_static4_total_usd':float(new_net.sum()),
    'delta_usd':float((new_net-old_net).sum()),'groups':summary,'examples':examples,
    'decomposed_exit_open_exact_funding_timestamp_cases':further,
    'explanation':'Old stop/target anchored to entry_mid*(1+side*0.0002); static new path anchors to raw entry_mid. Same174signals and 1000 entry notional. Levels/path transitions change without parameter fitting. This is diagnostic model change, not new unseen profit.'}
(OUT/'LEGACY_COMPARISON_QA.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False))
