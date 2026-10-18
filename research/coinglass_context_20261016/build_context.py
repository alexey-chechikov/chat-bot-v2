"""Offline retrospective join; never claims historical publication availability."""
import csv
import hashlib
import io
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent
PAIR=ROOT.parent/'strategy_workplan_20261015/public_history/paired_BTCUSDT_spot_perp_15m.csv'
STEP=900_000


def read_csv(path):
    raw=path.read_bytes()
    return list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))),hashlib.sha256(raw).hexdigest()


def main():
    pair,phash=read_csv(PAIR)
    oi,ohash=read_csv(ROOT/'public_oi/BTCUSDT_oi_15m.csv')
    indexed={int(r['timestamp']):r for r in oi}
    if len(indexed)!=len(oi):raise ValueError('duplicate OI time')
    rows=[]
    for r in pair:
        start=int(r['ts']); end=start+STEP
        point=indexed.get(end)
        if point is None:continue  # explicit intersection; no filled observations
        out=dict(r)
        out.update(bar_start_ms=start,bar_end_ms=end,
                   oi_same_end_quantity=point['sumOpenInterest'],
                   oi_same_end_usd=point['sumOpenInterestValue'],
                   historical_received_ms='',publication_lag_ms='',
                   availability='UNKNOWN_HISTORICAL_LAG_DIAGNOSTIC_ONLY')
        for lag in (1,4):
            past=indexed.get(end-lag*STEP)
            out[f'oi_lag{lag}_quantity']=past['sumOpenInterest'] if past else ''
            out[f'oi_change_{lag*15}m_fraction']=(float(point['sumOpenInterest'])/float(past['sumOpenInterest'])-1) if past and float(past['sumOpenInterest'])>0 else ''
        rows.append(out)
    if not rows:raise ValueError('no temporal intersection')
    buf=io.StringIO(newline='')
    writer=csv.DictWriter(buf,fieldnames=list(rows[0]),lineterminator='\n')
    writer.writeheader();writer.writerows(rows)
    raw=buf.getvalue().encode()
    path=ROOT/'public_oi/BTCUSDT_price_flow_oi_diagnostic.csv'
    if path.exists() and path.read_bytes()!=raw:raise ValueError('changed output; refuse overwrite')
    if not path.exists():path.write_bytes(raw)
    manifest={
      'status':'RETROSPECTIVE_CONTEXT_ONLY', 'rows':len(rows),
      'first_bar_start_ms':rows[0]['bar_start_ms'],'last_bar_end_ms':rows[-1]['bar_end_ms'],
      'closed_price_flow_known_at':'bar_end, before feed delay',
      'oi_timestamp_semantics':'provider-declared period end',
      'historical_publication_lag_ms':None,
      'entry_signal_or_profit_computed':False,
      'same_end_oi_is_proven_available_at_bar_close':False,
      'lag_columns_are_sensitivity_not_measured_delay':True,
      'missing_lag1':sum(r['oi_lag1_quantity']=='' for r in rows),
      'missing_lag4':sum(r['oi_lag4_quantity']=='' for r in rows),
      'sha256':hashlib.sha256(raw).hexdigest(),
      'input_sha256':{'paired_BTCUSDT_spot_perp_15m.csv':phash,'BTCUSDT_oi_15m.csv':ohash},
      'code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
      'no_fill_or_interpolation':True,
      'coinglass_matrices_available':False,
      'primary_map_observations':0,
      'separate_secondary_pilot_episodes':1
    }
    target=ROOT/'public_oi/context_manifest.json'
    data=(json.dumps(manifest,indent=2)+'\n').encode()
    if target.exists() and target.read_bytes()!=data:raise ValueError('changed manifest; refuse overwrite')
    if not target.exists():target.write_bytes(data)
    print(json.dumps(manifest,indent=2))


if __name__=='__main__':main()
