"""One frozen ETH candidate: causal candle PRICE/MARKET replay, no network."""
from pathlib import Path
from dataclasses import dataclass
import hashlib
import json
import math
import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parent
RESEARCH = OUT.parent
MINUTE = 60_000
HOLD = 120


@dataclass(frozen=True)
class Scenario:
    name: str
    flat_cost: float = 0.0
    fee: float = 0.0
    slip: float = 0.0
    reserve: float = .0004
    use_funding: bool = False


SCENARIOS = (
    Scenario('static_all_in_4bp', flat_cost=.0004),
    Scenario('static_all_in_8bp', flat_cost=.0008, reserve=.0008),
    Scenario('decomposed_fee1bp_slip1bp', fee=.0001, slip=.0001, use_funding=True),
    Scenario('decomposed_fee1bp_slip3bp', fee=.0001, slip=.0003, reserve=.0008, use_funding=True),
)


def quantity(entry, reserve, risk=10.0, max_notional=1000.0):
    return min(max_notional/entry, risk/(entry*(.009+reserve)))


def reconstruct_signals(d):
    x = d.copy()
    x['dt'] = pd.to_datetime(x.ts, unit='ms', utc=True)
    z = x.set_index('dt').resample('15min', origin='epoch').agg(
        close=('close','last'), volume=('volume','sum'), count=('close','size'))
    ret = z.close.pct_change(fill_method=None)
    scale = ret.shift(4).rolling(96, min_periods=96).std(ddof=1)*math.sqrt(4)
    move = z.close/z.close.shift(4)-1
    vsum = z.volume.rolling(4,min_periods=4).sum()
    vm = vsum.shift(4).rolling(96,min_periods=96).median()
    full = z['count'].eq(15).rolling(4,min_periods=4).sum().eq(4)
    qualify = ((move.abs()/scale>=2.5)&(move.abs()>=.006)&(vsum/vm>=2)&full).fillna(False).to_numpy()
    side = np.sign(move).fillna(0).to_numpy().astype(int)
    onset = qualify & (~np.r_[False,qualify[:-1]] | (side!=np.r_[0,side[:-1]]))
    entry_ts = z.index.to_numpy(dtype='datetime64[ms]').astype(np.int64)+15*MINUTE
    next_allowed = -1
    result = []
    ts = d.ts.to_numpy(dtype=np.int64)
    available = set(ts.tolist())
    dropped_horizon = 0
    for j in np.flatnonzero(onset):
        t0 = int(entry_ts[j])
        if t0 < next_allowed or t0 not in available:
            continue
        next_allowed = t0+121*MINUTE
        if t0+HOLD*MINUTE > int(ts[-1]):
            dropped_horizon += 1
            continue
        result.append((t0,int(side[j])))
    return result, {'onsets':int(onset.sum()), 'selected_full_horizon':len(result), 'excluded_end_horizon':dropped_horizon}


def replay_trade(d, t0, side, scenario, funding=None):
    """Exit path rebuilt from actual scenario entry; missing held interval unresolved."""
    by_ts = d if isinstance(d,dict) else {int(r.ts):r for r in d.itertuples(index=False)}
    base = {'signal_time':t0, 'side':side, 'scenario':scenario.name}
    if t0 not in by_ts:
        return {**base,'status':'missing_entry','net_usd':0.0}, []
    e = float(by_ts[t0].open)
    ee = e*(1+side*scenario.slip)
    q = quantity(ee,scenario.reserve)
    stop = ee*(1-side*.009)
    target = ee*(1+side*.018)
    deadline = t0+HOLD*MINUTE
    ex = None
    for j in range(HOLD+1):
        now = t0+j*MINUTE
        if now not in by_ts:
            return {**base,'status':'unresolved_missing_held_minute','missing_ts':now,'quantity':q,'entry_exec':ee,'net_usd':None}, []
        bar = by_ts[now]
        o,h,l = float(bar.open),float(bar.high),float(bar.low)
        if side*(o-stop)<=0:
            ex=(now,now,o,'stop','open')
            break
        if side*(o-target)>=0:
            ex=(now,now,target,'target','open')
            break
        if now == deadline:
            ex=(now,now,o,'time','open')
            break
        stop_hit = l<=stop if side==1 else h>=stop
        target_hit = h>=target if side==1 else l<=target
        if stop_hit:
            ex=(now,now+MINUTE-1,stop,'stop_both' if target_hit else 'stop','intraminute')
            break
        if target_hit:
            ex=(now,now+MINUTE-1,target,'target','intraminute')
            break
    exit_bar, exit_ts, x, reason, execution_kind = ex
    xx = x*(1-side*scenario.slip)
    entry_notional = q*ee
    raw_gross = q*side*(x-e)
    execution_gross = q*side*(xx-ee)
    slip_cost = raw_gross-execution_gross
    fees = scenario.fee*q*(ee+xx)
    flat_cost = scenario.flat_cost*entry_notional
    fund = 0.0
    fund_upper = 0.0
    fund_events=[]
    if scenario.use_funding and funding is not None:
        rows = funding[(funding.fundingTime>t0)&(funding.fundingTime<=exit_ts)]
        for row in rows.itertuples(index=False):
            if not np.isfinite(row.markPrice) or row.markPrice<=0:
                return {**base,'status':'unresolved_invalid_funding_mark','net_usd':None}, []
            cash = -side*q*float(row.fundingRate)*float(row.markPrice)
            ambiguous = ((execution_kind=='intraminute' and int(row.fundingTime)>exit_bar)
                         or (execution_kind=='open' and int(row.fundingTime)==exit_ts))
            lower,upper = (min(0,cash),max(0,cash)) if ambiguous else (cash,cash)
            fund += lower
            fund_upper += upper
            fund_events.append({'time':int(row.fundingTime),'cash':cash,'ambiguous':ambiguous,'lower':lower,'upper':upper})
    net = execution_gross-fees-flat_cost+fund
    out={**base,'status':'completed','entry_mid':e,'entry_exec':ee,'quantity':q,'entry_notional':entry_notional,
         'stop':stop,'target':target,'deadline':deadline,'exit_bar':exit_bar,'exit_time':exit_ts,
         'exit_raw':x,'exit_exec':xx,'execution_kind':execution_kind,'reason':reason,
         'raw_gross_usd':raw_gross,'execution_gross_usd':execution_gross,'slippage_cost_usd':slip_cost,
         'fees_usd':fees,'flat_all_in_cost_usd':flat_cost,'funding_usd':fund,
         'funding_upper_usd':fund_upper,'ambiguous_funding_events':sum(r['ambiguous'] for r in fund_events),
         'net_usd':net,'net_funding_upper_usd':net+fund_upper-fund,'net_return_pct':net/entry_notional*100,
         'net_R':net/10,'planned_stop_risk_usd':q*ee*(.009+scenario.reserve),
         'elapsed_minutes':(exit_ts-t0)/MINUTE}
    # Include hypothetical immediate liquidation friction and all surviving
    # minute closes. Exit point uses actual open or conservative accounting time.
    def liquidate(raw_price, funds):
        actual = raw_price*(1-side*scenario.slip)
        return q*side*(actual-ee)-scenario.fee*q*(ee+actual)-flat_cost+funds
    points=[{'ts':t0,'local_pnl':liquidate(e,0),'kind':'entry_immediate_liquidation'}]
    for now in range(t0,exit_bar,MINUTE):
        bar_end=now+MINUTE-1
        settled=sum(r['cash'] for r in fund_events if r['time']<=bar_end)
        points.append({'ts':bar_end,'local_pnl':liquidate(float(by_ts[now].close),settled),'kind':'minute_close_liquidation'})
    points.append({'ts':exit_ts,'local_pnl':net,'kind':'exit_realized'})
    return out,points


def drawdown(values):
    v=np.asarray(values,dtype=float)
    return float((np.maximum.accumulate(v)-v).max())


def evaluate(d, signals, scenario, funding):
    rows=[]; points=[{'ts':int(d.ts.iloc[0]),'pnl_usd':0.0,'kind':'initial'}]
    realized=0.0
    last_exit=-1
    lookup={int(r.ts):r for r in d.itertuples(index=False)}
    for n,(t0,side) in enumerate(signals):
        if t0<=last_exit:
            rows.append({'candidate':n,'signal_time':t0,'side':side,'status':'occupied','net_usd':0.0})
            continue
        r,p=replay_trade(lookup,t0,side,scenario,funding)
        r['candidate']=n
        rows.append(r)
        if r['status']!='completed':
            if r['net_usd'] is None:
                raise RuntimeError(f"Unresolved risk invalidates aggregate: {r}")
            continue
        for point in p:
            points.append({'ts':point['ts'],'pnl_usd':realized+point['local_pnl'],'kind':point['kind'],'candidate':n})
        realized+=r['net_usd']
        last_exit=r['exit_time']
    ledger=pd.DataFrame(rows)
    equity=pd.DataFrame(points)
    # Every source minute close receives the last available realized or marked
    # value. No future point is propagated backwards.
    close_ts=d.ts.to_numpy(dtype=np.int64)+MINUTE-1
    eqts=equity.ts.to_numpy(dtype=np.int64)
    pos=np.searchsorted(eqts,close_ts,side='right')-1
    minute=pd.DataFrame({'ts':close_ts,'liquidation_pnl_usd':equity.pnl_usd.to_numpy()[np.maximum(pos,0)]})
    completed=ledger[ledger.status.eq('completed')]
    ranked=completed.sort_values('net_usd',ascending=False)
    net=completed.net_usd.to_numpy()
    gross=completed.raw_gross_usd.to_numpy()
    monthly=pd.DataFrame({'month':pd.to_datetime(completed.signal_time,unit='ms',utc=True).dt.strftime('%Y-%m'),'net_pct':completed.net_return_pct}).groupby('month').net_pct.agg(['sum','count'])
    rng=np.random.default_rng(20261006)
    sample=rng.integers(0,len(monthly),size=(4000,len(monthly)))
    ci=np.quantile(monthly['sum'].to_numpy()[sample].sum(axis=1)/monthly['count'].to_numpy()[sample].sum(axis=1),[.025,.975])
    summary={'scenario':scenario.name,'source_candidates':len(signals),'completed':len(completed),
        'status_counts':ledger.status.value_counts().to_dict(),'reason_counts':completed.reason.value_counts().to_dict(),
        'net_total_usd':float(net.sum()),'net_mean_usd_per_source_candidate':float(net.sum()/len(signals)),
        'net_mean_return_pct_completed':float(completed.net_return_pct.mean()),'net_mean_R':float(completed.net_R.mean()),
        'raw_gross_total_usd':float(gross.sum()),'slippage_total_usd':float(completed.slippage_cost_usd.sum()),
        'fees_total_usd':float(completed.fees_usd.sum()),'flat_all_in_cost_total_usd':float(completed.flat_all_in_cost_usd.sum()),
        'funding_total_usd':float(completed.funding_usd.sum()),'funding_upper_total_usd':float(completed.funding_upper_usd.sum()),
        'ambiguous_funding_events':int(completed.ambiguous_funding_events.sum()),
        'PF':float(net[net>0].sum()/-net[net<0].sum()),'monthly_block_CI95_mean_net_pct':ci.tolist(),
        'max_DD_liquidation_point_usd':drawdown(np.r_[0,equity.pnl_usd]),
        'max_DD_minute_close_usd':drawdown(np.r_[0,minute.liquidation_pnl_usd]),
        'max_loss_trade_usd':float(-net.min()),'minimum_research_equity_1000':float(1000+equity.pnl_usd.min()),
        'capital_1000_breached':bool((1000+equity.pnl_usd<=0).any()),
        'best_three':ranked.head(3)[['candidate','signal_time','side','reason','net_usd']].to_dict(orient='records'),
        'after_remove_best_three_total_usd':float(ranked.iloc[3:].net_usd.sum()),
        'after_remove_best_three_mean_return_pct':float(ranked.iloc[3:].net_return_pct.mean()),
        'planned_max_stop_risk_usd':float(completed.planned_stop_risk_usd.max())}
    return ledger,equity,minute,summary


def main():
    manifest=json.loads((OUT/'INPUT_MANIFEST.json').read_text(encoding='utf-8'))
    assert hashlib.sha256((OUT/'README_ASSUMPTIONS.md').read_bytes()).hexdigest()==manifest['assumptions_sha256']
    for r in manifest['files']:
        assert hashlib.sha256((RESEARCH/r['file']).read_bytes()).hexdigest()==r['sha256'],r['file']
    d=pd.read_csv(RESEARCH/'expectancy_20261006/public_data/binance_futures_ETHUSDT_1m.csv')
    for c in ('open','high','low','close','volume'):
        assert np.isfinite(d[c]).all() and (d[c]>=0).all()
    assert (d[['open','high','low','close']]>0).all().all()
    assert not d.ts.duplicated().any() and d.ts.diff().dropna().eq(MINUTE).all() and d.ts.mod(MINUTE).eq(0).all()
    assert ((d.high>=d[['open','close','low']].max(axis=1))&(d.low<=d[['open','close','high']].min(axis=1))).all()
    signals,audit=reconstruct_signals(d)
    old=pd.read_csv(RESEARCH/'expectancy_20261006/intraday/fresh_trades_ETHUSDT_intraday_impulse_follow_z2.5_h120.csv')
    expected=list(zip(pd.to_datetime(old.entry_time,utc=True).to_numpy(dtype='datetime64[ms]').astype(np.int64).tolist(),old.side.astype(int).tolist()))
    audit.update({'expected_ledger_rows':len(expected),'exact_signal_timestamp_side_match':signals==expected,'data_rows':len(d),
                  'start':str(pd.to_datetime(int(d.ts.iloc[0]),unit='ms',utc=True)),
                  'end':str(pd.to_datetime(int(d.ts.iloc[-1])+MINUTE,unit='ms',utc=True))})
    (OUT/'SIGNAL_AUDIT.json').write_text(json.dumps(audit,indent=2),encoding='utf-8')
    if signals!=expected or len(signals)!=174:
        raise RuntimeError('Non-comparable signal reconstruction; no strategy return computed.')
    # Prefix test excludes only records that lack a full horizon at the cut.
    half=len(d)//2
    prefix,_=reconstruct_signals(d.iloc[:half].copy())
    assert prefix==[s for s in signals if s[0]+HOLD*MINUTE<=int(d.ts.iloc[half-1])]
    f=pd.read_csv(RESEARCH/'expectancy_20261006/public_data/binance_futures_ETHUSDT_funding.csv')
    assert not f.fundingTime.duplicated().any()
    f=f.sort_values('fundingTime').reset_index(drop=True)
    summaries=[]
    for s in SCENARIOS:
        ledger,eq,minute,summary=evaluate(d,signals,s,f)
        ledger.to_csv(OUT/f'ledger_{s.name}.csv',index=False)
        eq.to_csv(OUT/f'equity_points_{s.name}.csv',index=False)
        minute.to_csv(OUT/f'equity_minute_{s.name}.csv',index=False)
        summaries.append(summary)
    result={'as_of':'2026-10-15','status':'diagnostic_not_validated','source':'Previously viewed Binance USD-M May-Oct 2026, ETH only',
      'signal_audit':audit,'quantity':'continuous diagnostic; no historical tick/step metadata verified',
      'not_maker_or_WEEX':True,'OOS':False,'scenarios':summaries,
      'limitations':['Same selected and previously inspected signal/data window; no independent holdout.',
      'OHLC uncertain intraminute ordering uses conservative stop-first; funding ambiguity bounded.',
      'No order book, fill/no-fill, queue, partials, network latency or real venue transfer proof.',
      'Constant risk budget and notional cap; no leverage, compounding or actual account state.',
      '1000 research capital is accounting only; no full cross-asset portfolio or daily risk overlay.',
      'Monthly bootstrap CI descriptive after selection, not multiplicity-adjusted confirmation.']}
    (OUT/'REPORT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    lines=['# ETH causal PRICE/MARKET replay — 15.10.2026','','Один ранее выбранный ETH/follow/z2.5/h120. Binance USD-M, просмотренный период, не OOS, не WEEX и не maker replay. Исходные174сигнала независимо восстановлены точно; стопы/цели/выходы пересчитаны от новых входов.','','| Сценарий | N | Net USDT | Mean net % | PF | 95% monthly block CI % | DD liquidation USDT | Без3лучших net USDT |','|---|---:|---:|---:|---:|---|---:|---:|']
    for r in summaries:
        lines.append(f"| {r['scenario']} | {r['completed']} | {r['net_total_usd']:+.6f} | {r['net_mean_return_pct_completed']:+.9f} | {r['PF']:.6f} | {r['monthly_block_CI95_mean_net_pct']} | {r['max_DD_liquidation_point_usd']:.6f} | {r['after_remove_best_three_total_usd']:+.6f} |")
    lines+=['','Static all-in4/8bp: новые raw-price пути, плоский круг от entry notional без дополнительного funding/fees/slip. Decomposed: fee1bp за каждое исполнение + adverse slip1bp/3bp на сторону + signed Binance funding, без плоского круга. В каждом сценарии геометрия стопа0.9%/цели1.8% строится заново от его фактического входа, срок — точный t0+120min.','','Размер — continuous diagnostic: R10USDT, entry notional≤1000USDT, без проверенной исторической contract step/tick и без сложного процента. Суммы не доходность реального депозита. DD учитывает начальную точку, minute-close liquidation и immediate-entry friction; OHLC не показывает полный внутриминутный floating worst-case.','','Исключение трёх лучших — заранее заданный adversarial diagnostic, не оценка вероятности maker no-fill. Ранее просмотренные данные и месячный CI не подтверждают новую прибыльную систему. Макс.убыток, funding bounds, причины выходов, полный ledger/equity — REPORT.json и CSV.','','Файлы источников неизменны; хеши/допущения зафиксированы до расчёта в INPUT_MANIFEST.json и README_ASSUMPTIONS.md. Никаких private API, ключей, счёта, Mac, Claude или сетевых вызовов. Воспроизведение: сначала `python -m unittest test_replay -v`, затем `python run_replay.py` из этой папки с исходными соседними research-файлами.']
    (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({'signal_audit':audit,'results':summaries},ensure_ascii=False))


if __name__=='__main__':
    main()
