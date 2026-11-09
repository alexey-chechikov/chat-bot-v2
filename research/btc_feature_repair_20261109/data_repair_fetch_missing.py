"""One-off public supplements for the pinned BTC audit; no collectors/trading.

Original raw files remain unchanged. API bodies, retrieval metadata and SHA256
are saved under this script's directory. Minute OHLC cannot resolve tick order
within a minute; callers must retain ambiguity bounds.
"""
from __future__ import annotations
import concurrent.futures
import hashlib
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime,timezone
from pathlib import Path
import numpy as np
import pandas as pd

from replay_paths import LAB_ROOT, PROJECT_ROOT, ORIGINAL_SOURCE, DATA_DIR, ensure_original_sources, raw_data_file

ROOT=LAB_ROOT
BASE=PROJECT_ROOT
AUDIT=ORIGINAL_SOURCE
RAW=ROOT/"public_supplements"
SPOT="https://data-api.binance.vision/api/v3/klines"
FUNDING="https://fapi.binance.com/fapi/v1/fundingRate"
H=3600000

def utcnow():return datetime.now(timezone.utc).isoformat()
def sha_bytes(b):return hashlib.sha256(b).hexdigest()
def atomic_new(p,b):
    # Existing successful raw responses are immutable across retries.
    if p.exists():
        assert p.read_bytes()==b, f"Refusing to overwrite differing {p}"
    else:p.write_bytes(b)

def public_get(job):
    ident,url=job
    path=RAW/(ident+".json")
    meta=RAW/(ident+".meta.json")
    if path.exists() and meta.exists():
        payload=path.read_bytes();rec=json.loads(meta.read_text(encoding="utf-8"))
        assert sha_bytes(payload)==rec["sha256"]
        return ident,json.loads(payload),rec
    req=urllib.request.Request(url,headers={"User-Agent":"bot7-independent-audit/2026-11-09"})
    last=None
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req,timeout=20) as response:
                payload=response.read();status=response.status
            obj=json.loads(payload)
            if not isinstance(obj,list):raise ValueError(f"Expected array, received {str(obj)[:300]}")
            rec={"id":ident,"url":url,"retrieved_at":utcnow(),"http_status":status,"sha256":sha_bytes(payload),"bytes":len(payload),"records":len(obj),"source":"Binance public market data"}
            atomic_new(path,payload);atomic_new(meta,json.dumps(rec,ensure_ascii=False,indent=2).encode())
            return ident,obj,rec
        except Exception as e:
            last=e
            if attempt==0:time.sleep(.3)
    return ident,None,{"id":ident,"url":url,"attempted_at":utcnow(),"error":repr(last)}

def kline_url(interval,start,end):
    return SPOT+"?"+urllib.parse.urlencode({"symbol":"BTCUSDT","interval":interval,"startTime":int(start),"endTime":int(end),"limit":1000})

def main():
    ensure_original_sources()
    RAW.mkdir(exist_ok=True)
    t=pd.read_csv(AUDIT/"research/chart_walk_20261105/out/trade_table_btc.csv",sep=";",decimal=",")
    target=t[(t["ряд"]=="Binance")&t["причина выхода"].str.contains("цель",na=False)].copy()
    exit_ms=pd.to_datetime(target["выход UTC"],utc=True).astype("int64").to_numpy()//10**6
    starts=np.unique(exit_ms-H)
    local_path=raw_data_file("research/weex_regime_review_20261011/data/BTCUSDT_1m_reconstructed.csv")
    local=pd.read_csv(local_path)
    local["source_id"]="local_spot_reconstructed"
    frozen_path=raw_data_file("backtests/frozen/BTCUSDT_1m_2y.csv")
    frozen=pd.read_csv(frozen_path)
    frozen["source_id"]="local_spot_frozen"
    # Prefer the complete reconstructed minute over the frozen source's final
    # partially observed 2026-05-07 11:45 minute; preserve both raw originals.
    local=pd.concat([local,frozen],ignore_index=True).drop_duplicates("ts",keep="first").sort_values("ts")
    selected=[];jobs=[];hour_manifest=[]
    for st in starts:
        g=local[(local["ts"]>=st)&(local["ts"]<st+H)].copy()
        complete=len(g)==60 and np.array_equal(g["ts"].to_numpy(),np.arange(st,st+H,60000))
        if complete:
            g=g.rename(columns={"ts":"open_ms"})
            selected.append(g)
            hour_manifest.append({"hour_open_ms":int(st),"minute_rows":60,"source_id":str(g["source_id"].iloc[0]),"path":str(local_path if g["source_id"].iloc[0]=="local_spot_reconstructed" else frozen_path)})
        else:
            ident="spot_1m_"+pd.to_datetime(st,unit="ms",utc=True).strftime("%Y%m%dT%H%MZ")
            jobs.append((ident,kline_url("1m",st,st+H-1)))
            hour_manifest.append({"hour_open_ms":int(st),"source_id":ident})
    spot=pd.read_csv(DATA_DIR/"spot_BTCUSDT_1h.csv",usecols=["ms"])
    max_exit=int(pd.to_datetime(t[t["ряд"]=="Binance"]["выход UTC"],utc=True).max().timestamp()*1000)
    h1_start=int(spot["ms"].max()+H)
    if h1_start<max_exit:jobs.append(("spot_1h_tail",kline_url("1h",h1_start,max_exit-1)))
    funding=pd.read_csv(DATA_DIR/"um_BTCUSDT_funding.csv")
    fund_start=int(funding["ms"].max()+1)
    jobs.append(("funding_tail",FUNDING+"?"+urllib.parse.urlencode({"symbol":"BTCUSDT","startTime":fund_start,"endTime":max_exit,"limit":1000})))
    (ROOT/"data_repair_public_fetch_plan.json").write_text(json.dumps({"original_target_exit_trades":len(target),"unique_exit_hours":len(starts),"local_hours":len(selected),"jobs":jobs,"h1_start_ms":h1_start,"max_original_exit_ms":max_exit},ensure_ascii=False,indent=2),encoding="utf-8")
    records=[];tail=[];fund=[];errors=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for ident,obj,rec in pool.map(public_get,jobs):
            records.append(rec)
            if obj is None:errors.append(rec);continue
            if ident=="funding_tail":fund=obj;continue
            frame=pd.DataFrame([[int(r[0]),*map(float,r[1:6])] for r in obj],columns=["open_ms","open","high","low","close","volume"])
            frame["source_id"]=ident
            if ident=="spot_1h_tail":tail.append(frame)
            else:
                st=int(frame["open_ms"].min()) if len(frame) else None
                if len(frame)!=60 or not np.array_equal(frame["open_ms"].to_numpy(),np.arange(st,st+H,60000)):
                    errors.append({"id":ident,"error":"Incomplete or irregular 1m hour","rows":len(frame)});continue
                selected.append(frame)
    minutes=pd.concat(selected,ignore_index=True).sort_values("open_ms") if selected else pd.DataFrame()
    minutes.to_csv(ROOT/"target_exit_minutes.csv",index=False)
    if tail:pd.concat(tail,ignore_index=True).to_csv(ROOT/"spot_hour_tail.csv",index=False)
    if fund:pd.DataFrame(fund).to_csv(ROOT/"funding_tail.csv",index=False)
    result={"created_at":utcnow(),"purpose":"one-off original BTC audit supplement; no trading/collector",
            "original_commit":"762ec6f8124cb499a7104fd74544887190d04acb","target_trade_count":len(target),
            "target_exit_hours":len(starts),"minute_hours_available":len(minutes)//60,"minute_rows":len(minutes),
            "local_target_hours":sum(x["source_id"].startswith("local_") for x in hour_manifest),
            "hour_tail_rows":sum(len(x) for x in tail),"funding_tail_rows":len(fund),
            "local_sources":[{"path":str(p),"sha256":sha_bytes(p.read_bytes())} for p in (local_path,frozen_path)],
            "target_hours":hour_manifest,"requests":records,"errors":errors,
            "ambiguity":"Each 1m bar leaves high/low order unknown; do not report tick-exact execution.",
            "excluded":"No futures OHLC substitution; no Bitstamp 1m download; no collectors."}
    (ROOT/"data_repair_public_fetch_manifest.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({k:result[k] for k in ("target_trade_count","target_exit_hours","minute_hours_available","minute_rows","local_target_hours","hour_tail_rows","funding_tail_rows","errors")},ensure_ascii=False,indent=2))
    if errors:raise SystemExit(2)

if __name__=="__main__":main()
