"""Independent read-only checks of archived points and retrospective join."""
import csv
import hashlib
import json
import math
from pathlib import Path

ROOT=Path(__file__).resolve().parent
STEP=900_000


def main():
    folder=ROOT/'public_oi'
    manifest=json.loads((folder/'manifest.json').read_text())
    context=json.loads((folder/'context_manifest.json').read_text())
    indexes={}
    for symbol in ('BTCUSDT','ETHUSDT'):
        rows=[]
        for req in manifest['requests']:
            if not req['cache'].startswith(symbol):continue
            raw=(folder/req['cache']).read_bytes()
            assert hashlib.sha256(raw).hexdigest()==req['sha256']
            rows.extend(json.loads(raw))
        times=[r['timestamp'] for r in rows]
        assert times==list(range(manifest['start_ms_inclusive'],manifest['end_ms_exclusive'],STEP))
        assert all(r['symbol']==symbol for r in rows)
        path=folder/f'{symbol}_oi_15m.csv'
        assert hashlib.sha256(path.read_bytes()).hexdigest()==manifest['symbols'][symbol]['sha256']
        with path.open(newline='') as f:csv_rows=list(csv.DictReader(f))
        assert len(csv_rows)==len(rows)
        for source,export in zip(rows,csv_rows):
            assert int(export['timestamp'])==source['timestamp']
            for key in ('sumOpenInterest','sumOpenInterestValue'):
                assert export[key]==source[key]
                assert math.isfinite(float(export[key])) and float(export[key])>=0
        indexes[symbol]={r['timestamp']:r for r in rows}
    paired=ROOT.parent/'strategy_workplan_20261015/public_history/paired_BTCUSDT_spot_perp_15m.csv'
    assert hashlib.sha256(paired.read_bytes()).hexdigest()==context['input_sha256'][paired.name]
    with paired.open(newline='') as f:pair={int(r['ts']):r for r in csv.DictReader(f)}
    path=folder/'BTCUSDT_price_flow_oi_diagnostic.csv'
    assert hashlib.sha256(path.read_bytes()).hexdigest()==context['sha256']
    with path.open(newline='') as f:actual=list(csv.DictReader(f))
    expected=[t for t in sorted(pair) if t+STEP in indexes['BTCUSDT']]
    assert [int(r['bar_start_ms']) for r in actual]==expected
    for r in actual:
        start=int(r['bar_start_ms']); end=start+STEP
        assert int(r['bar_end_ms'])==end
        assert r['historical_received_ms']=='' and r['publication_lag_ms']==''
        assert r['availability']=='UNKNOWN_HISTORICAL_LAG_DIAGNOSTIC_ONLY'
        for key in pair[start]:assert r[key]==pair[start][key]
        point=indexes['BTCUSDT'][end]
        assert r['oi_same_end_quantity']==point['sumOpenInterest']
        assert r['oi_same_end_usd']==point['sumOpenInterestValue']
        for lag in (1,4):
            past=indexes['BTCUSDT'].get(end-lag*STEP)
            value=r[f'oi_lag{lag}_quantity']
            assert value==(past['sumOpenInterest'] if past else '')
    print(json.dumps({'status':'PASS','raw_oi_points':sum(len(x) for x in indexes.values()),
      'raw_response_hashes':len(manifest['requests']),'context_rows':len(actual),
      'historical_lag':'UNKNOWN','map_prediction_or_trading_result':False},indent=2))


if __name__=='__main__':main()
