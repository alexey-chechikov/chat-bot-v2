"""Fixed-signal quantity/MTM replay of the one already evaluated funding rule.

No refit, threshold search, new entry/exit, or production mutation. Hour-close
marks and funding use the declared spot proxy, not historical exchange marks.
"""
from __future__ import annotations
import hashlib
import json
import pickle
from pathlib import Path
import numpy as np
import pandas as pd
from replay_paths import LAB_ROOT, auxiliary_file
from replay_cashflows import event_net, prepare_funding

ROOT=LAB_ROOT
SC=.068
CUT=1672531200
VIEW="fixed2023_repaired_available_population"

def utc(t):return pd.Timestamp(int(t),unit="s",tz="UTC").strftime("%Y-%m-%d %H:%M")
def leg_net(s,p0,p1):return s*(p1/p0-1)*100-SC-SC*p1/p0

def replay_event(e,a,fund):
    """One trade's per-hour net liquidation value and gross marked exposure."""
    n=len(a["t"])
    eq=np.zeros(n);gross=np.zeros(n);fund_open=np.zeros(n)
    paid=np.zeros(n);closed=np.zeros(n)
    p=e["pos"];tag=e["tag"];s=int(e["side"])
    i0=int(p["entry_i"]);i1=int(e["i"])
    weight=float(p["w"])
    legs=[("initial",i0,float(p["entry"]),weight*.5 if tag in {"над синей","под синей"} else weight)]
    if tag in {"над синей","под синей"} and p["add_done"]:
        ai=int(np.searchsorted(a["t"],p["add_t"]))
        assert a["t"][ai]==p["add_t"] and i0<=ai<=i1
        legs.append(("add",ai,float(p["add_px"]),weight*.5))
    cash=event_net(e,a,fund,mode="corrected")
    assert cash["funding_complete"],cash["status"]
    calc=sum(leg_net(s,px,float(e["px"]))*w for _,_,px,w in legs)
    assert abs(calc-float(e["res"]))<1e-10
    for label,start,p0,w in legs:
        payment=np.zeros(n)
        for pay in cash["payments"]:
            if pay["leg"]!=label:continue
            assert pay["membership"]=="present"
            j=int(np.searchsorted(a["t"],pay["pay_t"]))
            assert a["t"][j]==pay["pay_t"]
            payment[j]+=pay["funding_cost_pct"]
        cumulative=np.cumsum(payment)
        k=np.arange(start,i1)
        px=np.asarray(a["c"])[k]
        # Fixed quantity = base*w/p0. Fees include entry and expected exit.
        eq[k]+=w*(s*(px/p0-1)*100-SC-SC*px/p0)-cumulative[k]
        gross[k]+=w*px/p0*100
        fund_open[k]+=cumulative[k]
        paid+=payment
    closed[i1]=cash["net_with_funding_strict"]
    eq+=np.cumsum(closed)
    assert gross[i1]==0 and abs(eq[-1]-cash["net_with_funding_strict"])<1e-10
    return eq,gross,paid,closed,cash

def checks():
    t=np.arange(5,dtype=np.int64)*3600
    a=dict(t=t,c=np.array([100.,101.,103.,95.,90.]))
    pos=dict(entry=100.,entry_t=0,entry_i=0,side=1,w=1.,tag="над синей",add_done=True,add_t=7200,add_px=102.)
    e=dict(pos=pos,tag="над синей",side=1,t=14400,i=4,px=90.,why="close",res=.5*leg_net(1,100,90)+.5*leg_net(1,102,90))
    f=prepare_funding(pd.Series([.01,.02],index=[7200,14400]),attrs={"supported_from_s":0,"expected_interval_s":7200,"venue":"Binance"})
    eq,gross,paid,closed,cash=replay_event(e,a,f)
    expected2=.5*leg_net(1,100,103)+.5*leg_net(1,102,103)-(.5/100*103+.5/102*103)
    assert abs(eq[2]-expected2)<1e-12 # add at this close also receives same-close funding cost.
    assert abs(gross[1]-50.5)<1e-12 and abs(gross[2]-(51.5+.5*103/102*100))<1e-12
    expected_final=e["res"]-(.5/100*103+.5/102*103)-(.5/100*90*2+.5/102*90*2)
    assert abs(eq[-1]-expected_final)<1e-12 and abs(closed[-1]-expected_final)<1e-12
    dd=eq-np.maximum.accumulate(np.r_[0.,eq])[1:]
    assert abs(dd[-1]-(eq[-1]-max(0.,eq[:-1].max())))<1e-12
    # Intrabar target exits before same-hour close/payment; later close is not an open-position mark.
    b=dict(t=np.arange(4,dtype=np.int64)*3600,c=np.array([100.,99.,95.,110.]))
    p=dict(entry=100.,entry_t=0,entry_i=0,side=-1,w=1.,tag="под жёлтой",add_done=False,add_t=None,add_px=None)
    event=dict(pos=p,tag="под жёлтой",side=-1,t=10800,i=3,px=90.,why="цель: test",res=leg_net(-1,100,90))
    ff=prepare_funding(pd.Series([.01,.01,.01],index=[3600,7200,10800]),attrs={"supported_from_s":0,"expected_interval_s":3600,"venue":"Binance"})
    curve,ex,_,_,c=replay_event(event,b,ff)
    assert abs(curve[-1]-(event["res"]+.99+.95))<1e-12 and ex[-1]==0
    assert not any(x['pay_t']==10800 for x in c['payments'])
    return {"synthetic_long_add_close_funding_DD":"passed","synthetic_intrabar_target_close_order":"passed"}

def risk(t,equity,gross):
    peak=np.maximum.accumulate(np.r_[0.,equity])[1:]
    dd=equity-peak
    j=int(np.argmin(dd))
    prev=int(np.argmax(np.r_[0.,equity[:j+1]]))-1
    changes=np.diff(equity)
    onehour=np.diff(t)==3600
    hourly=changes[onehour]
    k=max(1,int(np.ceil(.05*len(hourly))))
    monthly=pd.Series(equity,index=pd.to_datetime(t,unit='s',utc=True)).resample('ME').last()
    month_delta=monthly.diff();month_delta.iloc[0]=monthly.iloc[0]
    # End-of-hour quadrature on observed calendar-hour endpoints, excluding the missing hour.
    return dict(final_net=float(equity[-1]),MTM_max_drawdown_pp=float(dd.min()),
        drawdown_trough_utc=utc(t[j]),drawdown_peak_utc=utc(t[prev]) if prev>=0 else "initial_zero",
        max_hour_close_gross_pct_base=float(gross.max()),mean_observed_hour_close_gross_pct_base=float(gross.mean()),
        time_weighted_gross_pct_base_observed_hour_endpoint=float(gross[1:].mean()),
        mean_hour_endpoint_nominal_USDT_if_base1000=float(gross[1:].mean()*10),
        gross_time_hours_pctbase_observed_endpoint=float(gross[1:].sum()),
        fraction_observed_closes_with_exposure=float((gross>0).mean()),
        worst_month=str(month_delta.idxmin()),worst_month_net_change=float(month_delta.min()),
        hourly_change_var5_pp=float(np.quantile(hourly,.05)),hourly_change_ES5_pp=float(np.sort(hourly)[:k].mean()),
        strictly_one_hour_changes_n=int(onehour.sum()),excluded_long_gap_changes_n=int((~onehour).sum()),
        hourly_tail_n=k),month_delta

def main():
    test_results=checks()
    protected=[auxiliary_file('audit_bad_trades_predictions.csv'),ROOT/'progress_24h_predictions.csv']
    before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in protected}
    cache=pickle.load((ROOT/'replay_cache.pkl').open('rb'))['Binance'];a=cache['a'];t=np.asarray(a['t'],np.int64)
    funding=prepare_funding(cache['fund'],attrs={'venue':'Binance','supported_from_s':1568102400,'expected_interval_s':28800})
    assignment=pd.read_csv(ROOT/'funding_candidate_assignments.csv')
    assignment=assignment[assignment.view==VIEW].set_index('trade_id',verify_integrity=True)
    assert len(assignment)==87
    n=len(t);base_eq=np.zeros(n);cand_eq=np.zeros(n);base_g=np.zeros(n);cand_g=np.zeros(n)
    base_paid=np.zeros(n);cand_paid=np.zeros(n);base_closed=np.zeros(n);cand_closed=np.zeros(n)
    rows=[]
    for (t0,tag,s),e in cache['trades'].items():
        if t0<CUT:continue
        typ=('лонг ' if s==1 else 'шорт ')+tag;tid='Binance|'+typ+'|'+utc(t0)
        m=float(assignment.loc[tid,'multiplier']) if tag=='под синей' else 1.
        eq,gross,paid,closed,cash=replay_event(e,a,funding)
        base_eq+=eq;cand_eq+=m*eq;base_g+=gross;cand_g+=m*gross
        base_paid+=paid;cand_paid+=m*paid;base_closed+=closed;cand_closed+=m*closed
        rows.append(dict(trade_id=tid,type=typ,entry_t=t0,exit_t=int(e['t']),multiplier=m,
            baseline_funded=cash['net_with_funding_strict'],candidate_funded=m*cash['net_with_funding_strict'],
            funding_complete=cash['funding_complete'],baseline_no_funding=cash['net_no_funding']))
    trades=pd.DataFrame(rows);assert len(trades)==288 and trades.funding_complete.all()
    start=int(trades.entry_t.min());end=int(trades.exit_t.max());mask=(t>=start)&(t<=end)
    bt,be,ce,bg,cg=t[mask],base_eq[mask],cand_eq[mask],base_g[mask],cand_g[mask]
    assert np.isfinite(be).all() and np.isfinite(ce).all()
    identity_base=float(be[-1]-trades.baseline_funded.sum())
    identity_candidate=float(ce[-1]-trades.candidate_funded.sum())
    assert abs(identity_base)<1e-9 and abs(identity_candidate)<1e-9
    expected=pd.read_csv(ROOT/'funding_candidate_summary.csv')
    expected=expected[(expected.view==VIEW)&(expected.target=='strict_funded')].iloc[0]
    short=trades[trades.type=='шорт под синей']
    assert abs(short.candidate_funded.sum()-expected.sized)<1e-6,(short.candidate_funded.sum(),expected.sized)
    assert abs((ce[-1]-be[-1])-expected.gain)<1e-6,((ce[-1]-be[-1]),expected.gain)
    bm,bmonths=risk(bt,be,bg);cm,cmonths=risk(bt,ce,cg)
    frame=pd.DataFrame(dict(t=bt,utc=[utc(x) for x in bt],price_close=a['c'][mask],baseline_MTM_net=be,candidate_MTM_net=ce,
        baseline_gross_pct_base=bg,candidate_gross_pct_base=cg,baseline_funding_cost_at_t=base_paid[mask],candidate_funding_cost_at_t=cand_paid[mask],
        baseline_closed_funded_cash_at_t=base_closed[mask],candidate_closed_funded_cash_at_t=cand_closed[mask]))
    # Explicit full hourly index: unavailable mark remains NaN, never price-filled.
    calendar=np.arange(start,end+3600,3600,dtype=np.int64)
    frame=frame.set_index('t').reindex(calendar).rename_axis('t').reset_index()
    frame['utc']=[utc(x) for x in frame.t]
    frame['observed_hour_close']=frame.price_close.notna()
    frame.to_csv(ROOT/'funding_sizing_equity_hourly.csv',index=False,encoding='utf-8-sig')
    trades.to_csv(ROOT/'funding_sizing_equity_trades.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(dict(month=bmonths.index.astype(str),baseline_change=bmonths.to_numpy(),candidate_change=cmonths.to_numpy(),delta=cmonths.to_numpy()-bmonths.to_numpy())).to_csv(ROOT/'funding_sizing_equity_monthly.csv',index=False,encoding='utf-8-sig')
    after={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in protected};assert before==after
    observed_set=set(bt)
    result=dict(rule=VIEW,scope='288 closed test2023+ trades only; actual positions still open at end are excluded',
        start_utc=utc(start),end_utc=utc(end),calendar_closes_n=len(calendar),observed_closes_n=len(bt),
        missing_hour_closes=[utc(x) for x in calendar if x not in observed_set],
        funding_price_method='same_clock_spot_hour_close_proxy_not_actual_mark',all_trade_funding_complete=True,
        baseline=bm,candidate=cm,delta_final=ce[-1]-be[-1],shortblue=dict(n=len(short),baseline=short.baseline_funded.sum(),candidate=short.candidate_funded.sum()),
        checks={**test_results,'baseline_end_cash_identity_error':identity_base,'candidate_end_cash_identity_error':identity_candidate,'candidate_vs_prior_quintile_identity_error':float(short.candidate_funded.sum()-expected.sized)},
        source_hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [ROOT/'replay_cache.pkl',ROOT/'replay_cashflows.py',ROOT/'funding_candidate_assignments.csv']},
        protected_before=before,protected_after=after,
        limitations=['Quantity scaling only, unchanged fixed signals/entry/add trigger/exit. No capital or margin constraint is imposed.',
            'Hourly liquidation-value marks include entry and expected exit fees; within-hour drawdown/exposure extremes are not observed.',
            'One missing close is NaN, not filled. DD/max exposure are observed-close measures; hourly ES excludes the two-hour transition.',
            'Time-weighted nominal is endpoint hourly approximation on available marks, not exact intrabar notional integration.',
            'No equal-risk normalization; different gross exposure must be judged directly.',
            'This is closed-cohort retrospective research on previously inspected history, not full live-account equity or independent forward proof.'])
    (ROOT/'funding_sizing_equity.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    text=['# Денежный replay единственного funding sizing-кандидата\n',
        'Фиксированная политика из calendar-контроля: valid train94 до2023, test87 shortblue с2023, те же пять train-квантилей и множители.5/.75/1/1.25/1.5. Новых границ или моделей нет. Изменяется только количество каждой ноги shortblue; входы, доборы, выходы и остальные201 сделки остаются базовыми.\n',
        f'Период {utc(start)}—{utc(end)} UTC. Учтены все288 исходно закрытых сделок2023+, включая87 shortblue. **Это closed cohort:** фактические открытые на конце позиции исключены, поэтому график не является полным живым счётом. Funding complete у всех288 по объявленной spot-proxy clock-конвенции.\n',
        '| Показатель | База | Funding sizing |\n|---|---:|---:|']
    keys=[('Итог, % фиксированной базы','final_net'),('MTM max drawdown, п.п. базы','MTM_max_drawdown_pp'),('Максимальный gross на close, % базы','max_hour_close_gross_pct_base'),('Средний gross наблюдаемых close, % базы','mean_observed_hour_close_gross_pct_base'),('Средний nominal endpoint, при базе$1000','mean_hour_endpoint_nominal_USDT_if_base1000'),('Худший месяц, net change','worst_month_net_change'),('5% hourly VaR, п.п. базы','hourly_change_var5_pp'),('5% hourly ES, п.п. базы','hourly_change_ES5_pp')]
    text.append('\n'.join(f'| {label} | {bm[k]:.6f} | {cm[k]:.6f} |' for label,k in keys))
    text.append(f"\nИтог всех288: **{be[-1]:.6f}→{ce[-1]:.6f}**, Δ{ce[-1]-be[-1]:+.6f}. Shortblue отдельно: {short.baseline_funded.sum():.6f}→{short.candidate_funded.sum():.6f}. Конечная equity совпала с суммой strict funded outcomes по каждой ноге/сделке с ошибкой<1e−9. Размеры и риск не нормировались постфактум. Худший месяц базы: {bm['worst_month']}; кандидата: {cm['worst_month']}.\n")
    text.append('Количество фиксируется на цене каждой ноги; MTM каждого часа = движение позиции минус entry fee и ожидаемая exit fee минус уже начисленный funding. На выходе открытая оценка заменяется окончательным закрытым cashflow ровно по exit timestamp. Стоящий добор учитывает funding на close своего часа согласно cash helper; target до close не получает post-exit mark/позднюю выплату. Два synthetic-сценария проверили эти границы, открытый добор и drawdown.\n')
    text.append(f"В полной сетке{len(calendar)} часовых close отсутствует spot14:00UTC24.03.2023; тогда был открыт long13–27марта. Строка оставленаNaN. {len(bt)} close наблюдены; DD/gross относятся к ним. Hourly tail использует только{bm['strictly_one_hour_changes_n']} переходов ровно3600с, исключая переход13:00→15:00. Месячные изменения определяются известными концами месяцев; крайние январь2023/ноябрь2026 неполные. Средний nominal/time exposure — приближение по почасовым endpoint, с одним неизвестным mark; intrahour пики не восстановлены.\n")
    text.append('Это полноценный replay количества при фиксированных сигналах, но не проверка капитальных/маржинальных лимитов и не новый независимый forward. Сравнивать увеличение прибыли нужно вместе с изменением gross, drawdown и хвостов. Funding mark-прокси, исполнение после известного close и закрытая выборка ограничивают вывод. Остальные прогнозы побайтно неизменны.\n')
    (ROOT/'funding_sizing_equity.md').write_text('\n'.join(text),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
