"""Finite historical BTC flow dataset; no scheduler, live stream, account or orders.

Fixed interval matches the already inspected futures research, so it is NOT unseen
validation. Downloads 10 official archive ZIPs and their checksums, then exits.
"""
from __future__ import annotations
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import math
from pathlib import Path
import re
import tempfile
import os
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent
FUTURES = ROOT.parent / 'expectancy_20261006/public_data/binance_futures_BTCUSDT_1m.csv'
MINUTE = 60_000
STEP = 15 * MINUTE
START = int(datetime(2026, 5, 7, tzinfo=timezone.utc).timestamp() * 1000)
END = int(datetime(2026, 10, 6, tzinfo=timezone.utc).timestamp() * 1000)
FIELDS = ['ts','open','high','low','close','volume','close_ts','quote_volume',
          'trade_count','taker_buy_volume','taker_buy_quote_volume']
BASE = 'https://data.binance.vision/data/spot/'

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError('unexpected redirect')

def positive(value, allow_zero=False):
    x = float(value)
    if not math.isfinite(x) or (x < 0 if allow_zero else x <= 0):
        raise ValueError('invalid numeric field')
    return x

def normalize_epoch(value):
    value = int(value)
    if value >= 1_000_000_000_000_000:
        return value // 1000, 'microseconds'
    if value >= 1_000_000_000_000:
        return value, 'milliseconds'
    raise ValueError('timestamp is not epoch ms/us')

def parse_row(raw, step=STEP):
    if len(raw) != 12:
        raise ValueError('expected exactly 12 exchange fields')
    ts, unit = normalize_epoch(raw[0])
    close_ts, close_unit = normalize_epoch(raw[6])
    if unit != close_unit or ts % step or close_ts != ts + step - 1:
        raise ValueError('invalid candle grid or duration')
    out = dict(zip(FIELDS, raw[:11]))
    out.update(ts=ts, close_ts=close_ts)
    for key in ('open','high','low','close'):
        out[key] = positive(out[key])
    for key in ('volume','quote_volume','taker_buy_volume','taker_buy_quote_volume'):
        out[key] = positive(out[key], True)
    count = int(out['trade_count'])
    if count < 0 or str(count) != str(out['trade_count']):
        raise ValueError('invalid trade count')
    out['trade_count'] = count
    if (out['low'] > min(out['open'],out['close']) or
        out['high'] < max(out['open'],out['close']) or out['low'] > out['high']):
        raise ValueError('invalid OHLC')
    if (out['taker_buy_volume'] > out['volume'] + 1e-9 or
        out['taker_buy_quote_volume'] > out['quote_volume'] + 1e-6):
        raise ValueError('buy volume exceeds total')
    return out, unit

def get(url, cap):
    if not url.startswith(BASE) or not re.fullmatch(r'[A-Za-z0-9_./:-]+',url):
        raise ValueError('non-allowlisted archive URL')
    req = urllib.request.Request(url, method='GET',headers={'User-Agent':'fixed-historical-btc-flow-research-v1'})
    with urllib.request.build_opener(NoRedirect()).open(req,timeout=25) as response:
        data = response.read(cap+1)
    if len(data) > cap:
        raise ValueError('response size cap exceeded')
    return data

def atomic(path, data):
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError('refusing to overwrite differing research artifact: '+path.name)
        return
    with tempfile.NamedTemporaryFile(dir=path.parent,delete=False) as f:
        temp = Path(f.name)
        f.write(data); f.flush(); os.fsync(f.fileno())
    try:
        os.replace(temp,path)
    finally:
        temp.unlink(missing_ok=True)

def csv_bytes(rows, fields):
    s=io.StringIO(newline='')
    w=csv.DictWriter(s,fieldnames=fields,lineterminator='\n')
    w.writeheader(); w.writerows(rows)
    return s.getvalue().encode('utf-8')

def pair_flow(spot, futures_path=FUTURES):
    grouped={}
    with Path(futures_path).open(encoding='utf-8',newline='') as f:
        reader=csv.DictReader(f)
        if reader.fieldnames != FIELDS:
            raise ValueError('unexpected futures CSV schema')
        previous=None
        for raw in reader:
            row,_=parse_row([raw[k] for k in FIELDS]+['0'],MINUTE)
            ts=row['ts']
            if previous is not None and ts <= previous:
                raise ValueError('duplicate or unordered futures minute')
            previous=ts
            if START <= ts < END:
                grouped.setdefault(ts//STEP*STEP,[]).append(row)
    paired=[]
    for row in spot:
        ts=row['ts']; group=grouped.get(ts,[])
        if [r['ts'] for r in group] != list(range(ts,ts+STEP,MINUTE)):
            raise ValueError('missing futures minute in paired 15m')
        v=math.fsum(r['volume'] for r in group)
        b=math.fsum(r['taker_buy_volume'] for r in group)
        sv,sb=row['volume'],row['taker_buy_volume']
        paired.append({'ts':ts,'spot_volume_btc':sv,'spot_taker_buy_btc':sb,
            'spot_delta_btc':2*sb-sv,'spot_F':(2*sb-sv)/sv if sv else '',
            'perp_volume_btc':v,'perp_taker_buy_btc':b,
            'perp_delta_btc':2*b-v,'perp_F':(2*b-v)/v if v else '',
            'perp_open':group[0]['open'],'perp_close':group[-1]['close']})
    return paired

def main():
    files=[('monthly','2026-'+month) for month in ('05','06','07','08','09')]
    files += [('daily','2026-10-'+day) for day in ('01','02','03','04','05')]
    cache=ROOT/'public_history/archive_cache'
    sources=[]; selected={}; units=set()
    for kind,date in files:
        name='BTCUSDT-15m-'+date+'.zip'
        url=BASE+kind+'/klines/BTCUSDT/15m/'+name
        zip_path=cache/name; check_path=cache/(name+'.CHECKSUM')
        payload=zip_path.read_bytes() if zip_path.exists() else get(url,5_000_000)
        check=check_path.read_bytes() if check_path.exists() else get(url+'.CHECKSUM',4096)
        parts=check.decode('ascii').strip().split()
        digest=hashlib.sha256(payload).hexdigest()
        if len(parts)!=2 or parts[0]!=digest or parts[1].lstrip('*')!=name:
            raise ValueError('official checksum mismatch: '+name)
        with zipfile.ZipFile(io.BytesIO(payload)) as z:
            info=z.infolist()
            if len(info)!=1 or info[0].filename!=name[:-4]+'.csv' or info[0].file_size>20_000_000:
                raise ValueError('unexpected archive member')
            data=z.read(info[0])
        count=0
        for raw in csv.reader(io.StringIO(data.decode('utf-8-sig'))):
            row,unit=parse_row(raw); units.add(unit)
            if START <= row['ts'] < END:
                if row['ts'] in selected:
                    raise ValueError('duplicate spot timestamp')
                selected[row['ts']]=row; count+=1
        atomic(zip_path,payload); atomic(check_path,check)
        sources.append({'url':url,'zip_sha256':digest,'selected_rows':count,'official_checksum_verified':True})
        print(json.dumps({'archive':name,'selected_rows':count}),flush=True)
    expected=list(range(START,END,STEP))
    if sorted(selected)!=expected:
        raise ValueError('spot historical coverage is incomplete')
    rows=[selected[ts] for ts in expected]
    paired=pair_flow(rows)
    spot_csv=csv_bytes(rows,FIELDS)
    paired_csv=csv_bytes(paired,list(paired[0]))
    out=ROOT/'public_history'
    atomic(out/'binance_spot_BTCUSDT_15m.csv',spot_csv)
    atomic(out/'paired_BTCUSDT_spot_perp_15m.csv',paired_csv)
    manifest={'status':'ok','purpose':'historical feature readiness, not a trading result',
      'start_ms':START,'end_exclusive_ms':END,'interval_ms':STEP,'rows':len(rows),
      'expected_rows':len(expected),'missing':0,'source_timestamp_units':sorted(units),
      'timestamp_normalization':'epoch us // 1000; candle close remains end-exclusive minus 1ms',
      'futures_file':FUTURES.name,'futures_sha256':hashlib.sha256(FUTURES.read_bytes()).hexdigest(),
      'spot_csv_sha256':hashlib.sha256(spot_csv).hexdigest(),
      'paired_csv_sha256':hashlib.sha256(paired_csv).hexdigest(),
      'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
      'sources':sources,'unseen_validation':False,'live_collector_created':False,
      'OI_liquidations_heatmap_available':False,
      'received_time_history':'not reconstructed; historical archives are not prospective observations'}
    # Acquisition metadata may differ from a prior run, so preserve fixed deterministic contents.
    atomic(out/'manifest.json',(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
    print(json.dumps({'status':'ok','paired_rows':len(paired),'missing':0,'out':str(out)}))

if __name__=='__main__':
    main()
