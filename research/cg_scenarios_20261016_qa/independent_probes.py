"""Read-only independent builder probes; invented synthetic prices only."""
from pathlib import Path
from copy import deepcopy
import hashlib
import json
import sys

ROOT=Path(__file__).resolve().parent
SOURCE=ROOT.parent/'cg_scenarios_20261016'
sys.path.insert(0,str(SOURCE))
import scenario_card as lab


def fixture():
    m=15*60_000
    freeze=100*m
    signal=freeze+m
    close=signal+m
    bars=[]
    for t in range(freeze-20*m,signal+m,m):
        row={'ts_ms':t,'open':'100','high':'101','low':'99','close':'100'}
        if t==signal:
            row.update(open='94',high='96',low='89',close='95')
        bars.append(row)
    return {'schema_version':'cg-manual-scenario-v1','synthetic':True,
      'data_asof_ms':close+1000,'atr_seed_start_ms':freeze-20*m,'attempt_state':'unused',
      'snapshot':{'snapshot_id':'qa-invented-001','capture_ms':freeze,'annotation_lock_ms':freeze,
        'source_asof_ms':freeze,'lag_status':'known','source_record_complete':True,
        'source_record_fresh':True,'annotation_frozen':True,'frozen_spot':'100',
        'lower_zone':{'low':'90','high':'91'},'upper_zone':{'low':'120','high':'121'},
        'settings':{'provider':'CoinGlass','product':'liquidation_heatmap','model':'model1',
          'exchange':'Binance','symbol':'BTCUSDT','market':'perpetual','lookback':'24h','threshold':'0.85'}},
      'contract':{'exchange':'Binance','symbol':'BTCUSDT','market':'perpetual','min_quantity':'0.001','min_notional':'5',
        'verified':True,'tick_size':'0.1','quantity_step':'0.001','verified_at_ms':freeze,
        'verification_source':'invented synthetic metadata, not actual exchange metadata'},
      'price_source':{'exchange':'Binance','symbol':'BTCUSDT','market':'perpetual','timezone':'UTC'},
      'ohlc_15m':bars,'ohlc_1m':[],
      'next_available_quote':{'received_ms':close+1,'signal_close_ms':close,'price':'95',
        'executable':True,'first_available_after_close':True,'exchange':'Binance',
        'symbol':'BTCUSDT','market':'perpetual','side':'BUY'}}


def main():
    cases={}
    a=fixture()
    cases['valid_synthetic']=lab.build_card(a,synthetic=True)
    b=deepcopy(a); b['snapshot']['lag_status']='unknown'
    cases['unknown_source_lag']=lab.build_card(b,synthetic=True)
    b=deepcopy(a); b['next_available_quote']['received_ms']=a['data_asof_ms']+1
    cases['future_quote']=lab.build_card(b,synthetic=True)
    b=deepcopy(a); b.pop('next_available_quote')
    cases['no_entry_quote']=lab.build_card(b,synthetic=True)
    b=deepcopy(a); b['snapshot'].pop('snapshot_id')
    cases['missing_snapshot_id']=lab.build_card(b,synthetic=True)
    b=deepcopy(a); b['contract']['min_quantity']='100'; b['contract']['min_notional']='100000'
    cases['declared_impossible_minima']=lab.build_card(b,synthetic=True)
    expected={'valid_synthetic':'READY_RESEARCH','unknown_source_lag':'CONDITIONAL',
      'future_quote':'NO_TRADE','no_entry_quote':'CONDITIONAL',
      'missing_snapshot_id':'NO_TRADE','declared_impossible_minima':'NO_TRADE'}
    for name,status in expected.items():
        assert cases[name]['status']==status,(name,cases[name])
        assert cases[name]['trade_permission'] is False
        assert cases[name]['primary_admitted'] is False
    result={'source_sha256':hashlib.sha256((SOURCE/'scenario_card.py').read_bytes()).hexdigest(),
      'scope':'Invented offline fixture; no production IO/data/API',
      'cases':{k:{f:v.get(f) for f in ('status','reasons','entry','quantity','snapshot_id','trade_permission','primary_admitted')} for k,v in cases.items()}}
    (ROOT/'independent_probe_results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':
    main()
