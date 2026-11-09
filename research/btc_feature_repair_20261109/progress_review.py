"""Fixed +24h hold/exit diagnostic; +4/+12h descriptive landmarks only.

Uses corrected replay cache. No grid search; no production mutation or network.
"""
from __future__ import annotations
import hashlib
import copy
import json
from pathlib import Path
import pickle
import platform
import numpy as np
import pandas as pd
from scipy.stats import rankdata, spearmanr
import sklearn
from sklearn.linear_model import Ridge
from sklearn.metrics import roc_auc_score, mean_absolute_error
from sklearn.preprocessing import StandardScaler
from replay_paths import LAB_ROOT, PROJECT_ROOT, bootstrap_project

bootstrap_project()
from services.btc_signals import engine

ROOT=LAB_ROOT
CACHE=ROOT/"replay_cache.pkl"
CUT=int(pd.Timestamp("2023-01-01",tz="UTC").timestamp())
TYPES=["лонг над синей","шорт под синей","шорт под жёлтой","лонг 432"]
FEATURES=["close_now_net","mfe_sofar_entryATR","mae_sofar_entryATR","ATR_current_to_entry",
          "signed_current_green_distance_ATR","ER24_current","signed_green_slope24_ATR","current_exposure_weight"]
SPEC=dict(model="one pooled Ridge alpha=10, type offsets, no tuning",features=FEATURES,
    y="corrected engine net(final) minus net(if closed at +24h), no funding",
    target_clip="none: preserve complete positive and negative tail",
    transform="train-only median imputation and StandardScaler; no feature clipping",
    train="Binance entry2018-22 with exit strictly before2023-01-01; +24h strictly before base exit",
    test="Binance entry>=2023-01-01; immutable fixed historical split, not historical real-time forecasts",
    exit_rule="predicted future increment < 0, fixed zero threshold",
    other_landmarks="+4h/+12h description only, no fitted models",
    event_order="standing add counts iff add_t<=landmark_time, then close at known hour-close",
    price_coverage="exact clock landmark; require continuous entry-to-landmark hourly OHLC and continuous 24h feature window",
    path="entry hour excluded; only completed hours ending before/at landmark included",
    effect="one-off static exit overlay, not replacement state-machine replay; early exit can allow new entries",
    interpretation="chronological retrospective diagnostic on already researched history, not causal nor independent forward proof",
    execution="same-close execution after observing close retained from engine; may be optimistic",
    funding="excluded, to be supplied in a later separate correction")

def utc(ts):return pd.Timestamp(int(ts),unit="s",tz="UTC").strftime("%Y-%m-%d %H:%M")

def close_net(p,tag,side,px,when):
    if tag in engine.MAIN:
        result=engine.leg_net(side,p["entry"],px)*p["w"]*engine.FIRST
        added=bool(p["add_done"] and p["add_t"] is not None and int(p["add_t"])<=when)
        if added:result+=engine.leg_net(side,p["add_px"],px)*p["w"]*engine.ADD
        exposure=p["w"]*(engine.FIRST+(engine.ADD if added else 0))
    else:
        added=False
        result=engine.leg_net(side,p["entry"],px)*p["w"]
        exposure=p["w"]
    return float(result),added,float(exposure)

def phase(mfe,mae,move):
    if mfe<1 and move<=-1:return "not_developed_and_current_below_minus1ATR"
    if mfe<1:return "not_yet_developed_plus1ATR"
    if mfe>=2 and move<=0:return "developed2ATR_then_reversed_to_entry_or_worse"
    if mfe>=2 and mfe-move>=1:return "developed2ATR_with_ge1ATR_pullback"
    return "developed_remaining"

def make_landmarks(cache):
    rows=[]
    exclusions=[]
    trades=[]
    for venue,v in cache.items():
        a=v["a"]
        t=np.asarray(a["t"],np.int64)
        for (t0,tag,side),e in v["trades"].items():
            p=e["pos"]
            i0=int(p["entry_i"])
            typ=("лонг " if side==1 else "шорт ")+tag
            tid=venue+"|"+typ+"|"+utc(t0)
            final=float(e["res"])
            split="Bitstamp_backcast" if venue=="Bitstamp" else ("train2018_22" if t0<CUT else "test2023_plus")
            trades.append(dict(trade_id=tid,venue=venue,type=typ,entry_t=t0,entry_time=utc(t0),exit_t=int(e["t"]),
                exit_time=utc(e["t"]),final_net=final,split=split,final_add=bool(p["add_done"])))
            for hours in [4,12,24]:
                lm=int(t0+hours*3600)
                if e["t"]<=lm:
                    exclusions.append(dict(trade_id=tid,landmark_h=hours,reason="base_already_exited_at_or_before_landmark"))
                    continue
                j=int(np.searchsorted(t,lm))
                if j>=len(t) or t[j]!=lm:
                    exclusions.append(dict(trade_id=tid,landmark_h=hours,reason="exact_clock_landmark_absent"))
                    continue
                j24=int(np.searchsorted(t,lm-24*3600))
                continuous_path=(j-i0==hours and np.all(np.diff(t[i0:j+1])==3600))
                feature24=(j24<len(t) and t[j24]==lm-24*3600 and j-j24==24 and np.all(np.diff(t[j24:j+1])==3600))
                if not continuous_path or not feature24:
                    exclusions.append(dict(trade_id=tid,landmark_h=hours,reason="hourly_gap_in_path_or_24h_state_window"))
                    continue
                c=float(a["c"][j])
                entry=float(p["entry"])
                atr0=float(p["atr"])
                atrnow=float(a["atr4"][j])
                hh=np.asarray(a["h"][i0+1:j+1],float)
                ll=np.asarray(a["l"][i0+1:j+1],float)
                if not (np.isfinite(hh).all() and np.isfinite(ll).all() and np.isfinite(c) and atr0>0 and atrnow>0):
                    exclusions.append(dict(trade_id=tid,landmark_h=hours,reason="invalid_ohlc_or_ATR"))
                    continue
                favorable=(hh-entry) if side==1 else (entry-ll)
                adverse=(entry-ll) if side==1 else (hh-entry)
                mfe=float(max(0,np.max(favorable))/atr0)
                mae=float(max(0,np.max(adverse))/atr0)
                move=float(side*(c-entry)/atr0)
                now,added,exposure=close_net(p,tag,side,c,lm)
                f=dict(close_now_net=now,mfe_sofar_entryATR=mfe,mae_sofar_entryATR=mae,
                    ATR_current_to_entry=atrnow/atr0,
                    signed_current_green_distance_ATR=float(side*(c-a["f_G"][j])/atrnow),
                    ER24_current=float(a["er24"][j]),
                    signed_green_slope24_ATR=float(side*(a["f_G"][j]-a["f_G"][j24])/atrnow),
                    current_exposure_weight=exposure)
                rows.append(dict(trade_id=tid,venue=venue,type=typ,split=split,entry_t=t0,entry_time=utc(t0),
                    exit_t=int(e["t"]),exit_time=utc(e["t"]),landmark_h=hours,landmark_t=lm,landmark_time=utc(lm),
                    final_net=final,final_is_loss=final<0,future_incremental_net=final-now,
                    price_move_sofar_entryATR=move,giveback_sofar_entryATR=mfe-move,
                    add_done_by_landmark=added,state_phase=phase(mfe,mae,move),**f))
    return pd.DataFrame(rows),pd.DataFrame(exclusions),pd.DataFrame(trades)

def interval(z,values):
    months=pd.to_datetime(z.landmark_time).dt.to_period("M")
    allmonths=pd.period_range(months.min(),months.max(),freq="M")
    grouped=pd.Series(np.asarray(values),index=months).groupby(level=0).sum().reindex(allmonths,fill_value=0).to_numpy()
    rng=np.random.default_rng(112409)
    bs=grouped[rng.integers(0,len(grouped),size=(9999,len(grouped)))].sum(1)
    return np.quantile(bs,[.025,.975]).tolist(),len(grouped)

def summarize(z,name):
    y=z.future_incremental_net.to_numpy(float)
    hit=z.exit_overlay.to_numpy(bool)
    delta=np.where(hit,-y,0.)
    ci,months=interval(z,delta)
    base=z.final_net.to_numpy(float)
    top=np.zeros(len(z),bool)
    for typ in TYPES:
        ix=np.flatnonzero((z.type==typ).to_numpy()&(base>0))
        top[ix[np.argsort(base[ix])[-5:]]]=True
    losses=base<0
    cut_winners=hit&(base>0)&(y>0)
    return dict(group=name,n=len(z),baseline_reached=float(base.sum()),overlay_reached=float((base+delta).sum()),
        static_delta=float(delta.sum()),exit_n=int(hit.sum()),beneficial_exit_n=int((hit&(y<0)).sum()),
        harmful_exit_n=int((hit&(y>0)).sum()),continuations_improved_by_exit=float((-y[hit&(y<0)]).sum()),
        continuation_profit_destroyed=float(y[hit&(y>0)].sum()),loss_final_n=int(losses.sum()),
        final_loss_exits=int((hit&losses).sum()),final_loss_delta=float(delta[losses].sum()),
        profitable_final_n=int((base>0).sum()),profitable_final_exits=int((hit&(base>0)).sum()),
        winner_future_profit_cut_n=int(cut_winners.sum()),winner_future_profit_cut=float(y[cut_winners].sum()),
        top5_positive_per_type_n=int(top.sum()),top5_modified=int((top&hit).sum()),
        top5_delta=float(delta[top].sum()),calendar_months=months,
        paired_month_cluster_delta_ci_lo=ci[0],paired_month_cluster_delta_ci_hi=ci[1],
        spearman_prediction_future=float(spearmanr(z.predicted_future_increment,y).statistic),
        mae=float(mean_absolute_error(y,z.predicted_future_increment)))

def auc(y,x):
    y=np.asarray(y,bool)
    if y.all() or not y.any():return np.nan
    ranks=rankdata(x)
    p=y.sum();n=len(y)-p
    return float((ranks[y].sum()-p*(p+1)/2)/(p*n))

def asof_selfchecks():
    p=dict(entry=100.,w=2.,add_done=True,add_t=20,add_px=102.)
    expected=engine.leg_net(1,100.,110.)
    n,added,weight=close_net(p,"над синей",1,110.,10)
    assert not added and weight==1. and abs(n-expected)<1e-12
    future=copy.deepcopy(p);future["add_px"]=999.
    assert close_net(future,"над синей",1,110.,10)==(n,added,weight)
    same,added,weight=close_net(p,"над синей",1,110.,20)
    assert added and weight==2. and abs(same-(expected+engine.leg_net(1,102.,110.)))<1e-12
    t=np.arange(60,dtype=np.int64)*3600
    c=100.+np.arange(60)*.1
    a=dict(t=t,c=c,h=c+.1,l=c-.1,atr4=np.ones(60),f_G=np.full(60,100.),er24=np.full(60,.2))
    pos=dict(entry=103.,entry_t=int(t[30]),entry_i=30,atr=1.,w=1.,add_done=True,add_t=int(t[52]),add_px=105.)
    ev=dict(pos=pos,t=int(t[59]),res=10.)
    cache={"Synthetic":{"a":a,"trades":{(int(t[30]),"над синей",1):ev}}}
    l1,_,_=make_landmarks(cache)
    changed=copy.deepcopy(cache)
    for name in ["c","h","l","f_G","atr4","er24"]:changed["Synthetic"]["a"][name][35:]+=500.
    changed["Synthetic"]["trades"][(int(t[30]),"над синей",1)]["pos"]["add_px"]=999.
    changed["Synthetic"]["trades"][(int(t[30]),"над синей",1)]["res"]=-500.
    l2,_,_=make_landmarks(changed)
    s1=l1[l1.landmark_h==4].iloc[0]
    s2=l2[l2.landmark_h==4].iloc[0]
    assert all(np.isclose(s1[k],s2[k]) for k in FEATURES+["price_move_sofar_entryATR","giveback_sofar_entryATR"])

def clean_json(x):
    if isinstance(x,dict):return {k:clean_json(v) for k,v in x.items()}
    if isinstance(x,list):return [clean_json(v) for v in x]
    if isinstance(x,float) and not np.isfinite(x):return None
    return x

def main():
    # Written before reading outcomes or fitting a model in this run.
    (ROOT/"progress_review_spec.json").write_text(json.dumps(SPEC,ensure_ascii=False,indent=2),encoding="utf-8")
    asof_selfchecks()
    cache=pickle.load(CACHE.open("rb"))
    L,E,T=make_landmarks(cache)
    assert len(T)==973 and T.trade_id.nunique()==973
    assert (L.landmark_t<L.exit_t).all()
    assert (L.mfe_sofar_entryATR>=0).all() and (L.mae_sofar_entryATR>=0).all()
    L.to_csv(ROOT/"progress_landmarks.csv",index=False,encoding="utf-8-sig")
    E.to_csv(ROOT/"progress_landmark_exclusions.csv",index=False,encoding="utf-8-sig")
    desc=L.groupby(["split","type","landmark_h","state_phase","final_is_loss"],observed=True).agg(
        n=("trade_id","size"),final_net=("final_net","sum"),close_now_net=("close_now_net","sum"),
        future_increment=("future_incremental_net","sum"),median_mfe=("mfe_sofar_entryATR","median"),
        median_mae=("mae_sofar_entryATR","median"),median_close_net=("close_now_net","median")).reset_index()
    desc.to_csv(ROOT/"progress_state_groups.csv",index=False,encoding="utf-8-sig")
    Z=L[L.landmark_h==24].copy()
    train=(Z.venue=="Binance")&(Z.entry_t<CUT)&(Z.exit_t<CUT)
    test=(Z.venue=="Binance")&(Z.entry_t>=CUT)
    assert Z.loc[train,"exit_t"].max()<Z.loc[test,"landmark_t"].min()
    X=Z[FEATURES].replace([np.inf,-np.inf],np.nan)
    med=X.loc[train].median()
    A=X.fillna(med)
    assert not A.isna().any().any()
    sc=StandardScaler().fit(A.loc[train])
    design=np.column_stack([sc.transform(A)]+[(Z.type==typ).to_numpy(float)[:,None] for typ in TYPES[1:]])
    model=Ridge(alpha=10.).fit(design[train],Z.loc[train,"future_incremental_net"])
    # Predict using solely frozen training model and each row's landmark inputs.
    Z["predicted_future_increment"]=model.predict(design)
    Z["exit_overlay"]=Z.predicted_future_increment<0
    Z["oneoff_overlay_net"]=np.where(Z.exit_overlay,Z.close_now_net,Z.final_net)
    Z["fold_id"]="fixed_train_Binance2018_22_test2023_plus"
    Z["fit_label_cutoff_utc"]="2023-01-01 00:00"
    Z["prediction_scope"]=np.where(test,"saved_OOS_fixed_historical_split",np.where(train,"in_sample_train_diagnostic","backward_transport_diagnostic"))
    Z.to_csv(ROOT/"progress_24h_predictions.csv",index=False,encoding="utf-8-sig")
    summaries=[]
    for split,z in Z.groupby("split",sort=False):
        summaries.append(summarize(z,split+"|ALL"))
        for typ,p in z.groupby("type",sort=False):summaries.append(summarize(p,split+"|"+typ))
    for label,m in [("test2023_24",test&(Z.entry_t<int(pd.Timestamp('2025-01-01',tz='UTC').timestamp()))),
                    ("test2025_plus",test&(Z.entry_t>=int(pd.Timestamp('2025-01-01',tz='UTC').timestamp())))]:
        z=Z[m]
        summaries.append(summarize(z,label+"|ALL"))
        for typ,p in z.groupby("type",sort=False):summaries.append(summarize(p,label+"|"+typ))
    S=pd.DataFrame(summaries)
    S.to_csv(ROOT/"progress_24h_policy.csv",index=False,encoding="utf-8-sig")
    # Attach one-off overlay to all973 closed original trades; unreached states remain baseline.
    delta=Z.set_index("trade_id").oneoff_overlay_net-Z.set_index("trade_id").final_net
    T["oneoff_overlay_delta"]=T.trade_id.map(delta).fillna(0.)
    T["oneoff_overlay_net"]=T.final_net+T.oneoff_overlay_delta
    T.to_csv(ROOT/"progress_all_trades_overlay.csv",index=False,encoding="utf-8-sig")
    frows=[]
    for typ in TYPES:
        tr=Z[train&(Z.type==typ)]
        te=Z[test&(Z.type==typ)]
        yt=tr.future_incremental_net.to_numpy(float)
        ye=te.future_incremental_net.to_numpy(float)
        for feature in FEATURES:
            xt=A.loc[tr.index,feature].to_numpy(float)
            xe=A.loc[te.index,feature].to_numpy(float)
            rtr=float(spearmanr(xt,yt).statistic) if np.ptp(xt)>0 else np.nan
            rte=float(spearmanr(xe,ye).statistic) if np.ptp(xe)>0 else np.nan
            a_train=auc(yt<0,xt)
            sg=1 if a_train>=.5 else -1
            frows.append(dict(type=typ,feature=feature,n_train=len(tr),n_test=len(te),
                train_future_increment_spearman=rtr,test_future_increment_spearman=rte,
                absolute_train_effect=abs(rtr),direction_preserved=(np.sign(rtr)==np.sign(rte)),
                train_risk_direction="higher" if sg==1 else "lower",
                train_bad_continuation_auc=auc(yt<0,sg*xt),test_bad_continuation_auc_fixed_direction=auc(ye<0,sg*xe),
                train_bad_median=float(np.median(xt[yt<0])),train_good_median=float(np.median(xt[yt>=0])),
                test_bad_median=float(np.median(xe[ye<0])),test_good_median=float(np.median(xe[ye>=0]))))
    factors=pd.DataFrame(frows).sort_values(["type","absolute_train_effect"],ascending=[True,False])
    factors["rank_from_train"]=factors.groupby("type").cumcount()+1
    factors.to_csv(ROOT/"progress_factor_ranking.csv",index=False,encoding="utf-8-sig")
    artifact=dict(spec=SPEC,cache_sha256=hashlib.sha256(CACHE.read_bytes()).hexdigest(),
        engine_sha256=hashlib.sha256((PROJECT_ROOT/"services/btc_signals/engine.py").read_bytes()).hexdigest(),
        environment=dict(python=platform.python_version(),numpy=np.__version__,pandas=pd.__version__,sklearn=sklearn.__version__),
        model_intercept=float(model.intercept_),coefficients=dict(zip(FEATURES+["type:"+t for t in TYPES[1:]],model.coef_.tolist())),
        scaler_mean=sc.mean_.tolist(),scaler_scale=sc.scale_.tolist(),median_imputer=med.to_dict(),
        n_train=int(train.sum()),n_test=int(test.sum()),train_ids=Z.loc[train,"trade_id"].tolist(),test_ids=Z.loc[test,"trade_id"].tolist(),
        missing_features=X.isna().sum().to_dict(),landmark_counts=L.groupby(["venue","landmark_h"]).size().reset_index(name="n").to_dict("records"),
        exclusions=E.groupby(["landmark_h","reason"]).size().reset_index(name="n").to_dict("records"),
        policies=S.to_dict("records"),factor_ranking=factors.to_dict("records"),
        all_trades_overlay=T.groupby(["split","type"]).agg(n=("trade_id","size"),base=("final_net","sum"),overlay=("oneoff_overlay_net","sum"),delta=("oneoff_overlay_delta","sum")).reset_index().to_dict("records"))
    (ROOT/"progress_review_results.json").write_text(json.dumps(clean_json(artifact),ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
    # Human-readable report is generated from the same frozen outputs.
    text=[]
    text.append("# Развитие позиции: наблюдаемые состояния на4/12/24ч и один выходной overlay\n")
    text.append("Это численный анализ восстановленных973 закрытых сделок на corrected engine. Исправленный replay сверялся с оригинальной CSV до изменения исполнения; все исходные входы/выходы сопоставлены. Настоящий анализ использует исправленный `exit_event.res`, без funding. Полный SHA256 replay cache: `"+artifact['cache_sha256']+"`; engine: `"+artifact['engine_sha256']+"`.\n")
    text.append("Ни одна запись ниже не выдаётся за прогноз, реально сохранённый в2018–2026 до исхода сделки. Это **saved OOS from one fixed historical split** на уже исследованной истории. Модель и порог не перебирались, торговые службы не менялись.\n")
    text.append("## Что известно в каждой точке\n")
    text.append("Для ещё открытой базовой сделки построены ровно+4/+12/+24 календарных часа после входа. Требуется `exit_time > landmark_time`, точная запись часа и непрерывное часовое покрытие пути/24ч окна признаков. Входной бар не входит в MFE/MAE; берутся только завершённые бары после входа до landmark. Поздний high/low выхода и окончательный будущий MFE/MAE сюда не попадают.\n")
    text.append("`close_now_net` включает entry/exit fees и каждую реально существующую ногу. Добор учитывается только при add_t<=landmark; равенство включено, поскольку стоящий stop исполнился до решения на закрытии. Количество каждой ноги соответствует весу/цене её входа, как в engine. Будущий добор и его будущая цена не входят в текущее состояние.\n")
    text.append("Сохраняется исходное допущение исполнения по уже известному close, потенциально оптимистичное для немедленной рыночной заявки. Funding не включён. После его добавления нужно пересчитать и текущий net, и конечный net, и целевой incremental net; это не простая поправка только к финалу.\n")
    text.append("| Площадка | +4ч | +12ч | +24ч |\n|---|---:|---:|---:|\n"+"\n".join("| "+venue+" | "+" | ".join(str(int(((L.venue==venue)&(L.landmark_h==h)).sum())) for h in [4,12,24])+" |" for venue in cache)+"\n")
    text.append("Причины отсутствия состояний: к4/12/24ч базовый выход уже состоялся в18/186/304 случаях; ещё13/6/2 строки исключены из-за часовых дыр. Это не заполнено соседней ценой и не заменено отсчётом строк. Все причины сохранены по каждому trade_id в exclusions.csv.\n")
    text.append("## Наблюдаемые состояния и будущий исход\n")
    text.append("Фиксированные описательные состояния: MFE<1ATR и текущий направленный ход<=−1ATR; MFE<1ATR без такого падения; MFE>=2ATR с возвратом к цене входа или хуже; MFE>=2ATR с откатом>=1ATR; прочее уже развившееся состояние. ATR фиксирован на исходном входе. Это ценовая геометрия, а не прибыль всей позиции: после добора weighted net может быть отрицательным, хотя цена ещё выше первого входа. Состояния вычисляются без будущего.\n")
    aggregate=L[L.split=='test2023_plus'].groupby(['landmark_h','state_phase'],observed=True).agg(n=('trade_id','size'),losses=('final_is_loss','sum'),final=('final_net','sum'),now=('close_now_net','sum'),future=('future_incremental_net','sum')).reset_index()
    aggregate.to_csv(ROOT/'progress_test_state_totals.csv',index=False,encoding='utf-8-sig')
    text.append("| Час | Наблюдаемое состояние | n | Финальных убытков | Конечный net | Net если закрыть сейчас | Будущий incremental net HOLD |\n|---:|---|---:|---:|---:|---:|---:|\n"+"\n".join(f"| {r.landmark_h} | {r.state_phase} | {r.n} | {r.losses} | {r.final:.2f} | {r.now:.2f} | {r.future:+.2f} |" for r in aggregate.itertuples())+"\n")
    text.append("**Высокая частота будущих убыточных сделок не равна выгоде выхода сейчас.** Уже на4ч слабое состояние MFE<1 и текущийход<=−1ATR дало9 будущих убытков из11, но удержание в сумме добавило+16.41 против немедленного закрытия. На12ч13/15 убыточных, удержание добавило+9.67. На24ч14/16 убыточных, но будущий incremental лишь−0.3304: почти весь наблюдаемый ущерб уже произошёл. Условный выход здесь не возвращает ранее потерянные деньги. Эти суммы — описание зафиксированных состояний, а не выбор лучшего нового порога.\n")
    text.append("С другой стороны, развитые к24ч позиции с MFE>=2ATR и откатом>=1ATR включают17 проигравших из44, но дальнейшее удержание в сумме добавило+33.95. Массовая фиксация отката от MFE опять рискует отрезать хвост. Нужна цель **net(final)−net(close now)**, а не просто final_loss. В state_groups.csv эти различия разложены отдельно по четырём типам, эпохе и финальному знаку.\n")
    text.append("## Ровно одна модель на24ч\n")
    text.append("Ridge alpha10, без clipping целевого y, восемь state-признаков + type offsets. Признаки: close_now_net, MFE/MAE до24ч в ATR входа, ATRcurrent/ATRentry, направленное расстояние текущего close до зелёной/ATRcurrent, текущаяER24, направленный наклон зелёной за24ч/ATRcurrent, действующий вес позиции. Imputer/scaler обучены только на Binance2018–22, конечная метка закрыта до01.01.2023. Без funding/flow и без будущих path-полей. Сырой хвост оставлен, поскольку он экономически важен.\n")
    text.append(f"Train{int(train.sum())} достигнутых24ч-состояний; test{int(test.sum())}. Действие EXIT только если predicted future_increment<0, порог0 зафиксирован до прогона. На4/12ч модели не обучались. Все исходные train/test IDs, fit cutoff, fold_id, входные состояния и predicted values сохранены; на test используется только обученная к cut-off матрица. Bitstamp — обратный перенос, не второй перспективный test.\n")
    text.append("| Проверка2023+ | n достигли24ч | База на них | Overlay | Δ | Выходов | Полезных / вредных |\n|---|---:|---:|---:|---:|---:|---:|\n"+"\n".join(f"| {r.group.split('|')[-1]} | {r.n} | {r.baseline_reached:.2f} | {r.overlay_reached:.2f} | {r.static_delta:+.4f} | {r.exit_n} | {r.beneficial_exit_n} / {r.harmful_exit_n} |" for r in S[S.group.str.startswith('test2023_plus')].itertuples())+"\n")
    text.append("Из195 достигших24ч модель закрыла только7 (4 полезно,3 вредно). Сэкономлено4.5458, уничтожено15.4763 будущего net. Единственный затронутый top5 shortblue потерял14.1110. Общий Δ−10.9305, исследовательский месячный интервал [−42.07;+7.50]. На всем списке288 test-сделок, включая уже закрытые до24ч, итог **344.2519→333.3214**; сравнивать406.07 у достигших24ч с базой344.25 всех сделок нельзя. Long и shortyellow модель не закрыла ни разу, поэтому их нулевой эффект не доказывает правильность HOLD в каждом случае.\n")
    text.append("2023–24: Δ−12.6984; с2025:+1.7680. Поздний плюс не отменяет полного отрицательного результата и не используется для выбора новой версии. Перестановок моделей/alpha/threshold, выбора лучшего horizon или нового fit после этих результатов не было.\n")
    text.append("**Границы оценки:** это one-off overlay на тех же базовых позициях. Изменение выхода может разрешить новые входы; этого здесь нет. Денежная экспозиция и оборот новой политики полностью не выровнены. Интервал строится ресэмплированием календарных месяцев landmark с нулевыми месяцами,9999 повторов; это кластерный анализ статической парнойΔ, не bootstrap всей MTM-equity. Долгие позиции могут зависеть через соседние месяцы, так что независимость блоков и выбор длины не доказаны. При7 действиях подтверждающая мощность низкая.\n")
    text.append("## Каждый test-выход модели\n")
    selected=Z[test&Z.exit_overlay]
    text.append("| Вход | Net на24ч | Конечный net | Прогноз HOLD−EXIT | Фактический HOLD−EXIT |\n|---|---:|---:|---:|---:|\n"+"\n".join(f"| {r.trade_id} | {r.close_now_net:.4f} | {r.final_net:.4f} | {r.predicted_future_increment:.4f} | {r.future_incremental_net:+.4f} |" for r in selected.itertuples())+"\n")
    text.append("Особенно существенен shortblue16.08.2023: к24ч MFE3.012ATR, MAE.378ATR, net+1.4464. Модель предсказала−.1639 и закрыла его, но базовое продолжение принесло ещё+14.1110 до конечных+15.5574. Маленький отрицательный прогноз не учитывает неопределённость и асимметрию хвоста. Это причина отрицательного результата данной спецификации, не основание менять порог на той же проверке.\n")
    text.append("## Факторы развития: описательное ранжирование\n")
    text.append("Ранг строится по |Spearman| с future_increment только на train; знак на test не переворачивается ради красивого результата. Также сохранены AUC отрицательного continuation, train-fixed направление риска и severe/good медианы.32 сравнения не являются32 независимо подтверждёнными гипотезами. Constant exposure432 имеет неопределённую корреляцию и выводится какNA. Корреляция со знаком риска и связь с размером будущей прибыли — разные цели; они могут различаться при редких трендах.\n")
    def fmt(v):return "NA" if not np.isfinite(v) else f"{v:.3f}"
    text.append("| Тип | Рангtrain | Фактор | Spearman train | Spearman test | AUC плохого continuation test, направлениеtrain |\n|---|---:|---|---:|---:|---:|\n"+"\n".join(f"| {r.type} | {r.rank_from_train} | {r.feature} | {fmt(r.train_future_increment_spearman)} | {fmt(r.test_future_increment_spearman)} | {fmt(r.test_bad_continuation_auc_fixed_direction)} |" for r in factors.itertuples())+"\n")
    text.append("Уlong больший наблюдённыйMAE положительно связан с дальнейшим incremental: rho+.280/+.275. Это не совет терпеть любую просадку: отбор только ещё открытых24ч-позиций, итоговая политика и большие восстановившиеся победители меняют картину. Уshortyellow связь текущего net с добавкой −.433/−.152 ослабевает на малых24/25 случаях. У432 расстояние до зелёной +.195/+.119, но всей fixed-модели этого недостаточно для убедительной прибыли. Новую модель по лучшим32 строкам не выбирали.\n")
    text.append("## Развитие конкретных плохих и успешных сделок\n")
    ids=[('лонг над синей','2023-05-28 20:00'),('лонг над синей','2023-10-16 08:00'),('лонг 432','2026-10-21 16:00'),('лонг 432','2025-05-08 04:00'),('лонг 432','2026-08-18 16:00')]
    case=L[(L.venue=='Binance')&pd.Series([(r.type,r.entry_time) in ids for r in L.itertuples()],index=L.index)].copy()
    case.to_csv(ROOT/'progress_case_landmarks.csv',index=False,encoding='utf-8-sig')
    text.append("| Вход | Час | Net закрытия сейчас | MFE/MAE до часа, ATR | Финальный net |\n|---|---:|---:|---|---:|\n"+"\n".join(f"| {r.trade_id} | {r.landmark_h} | {r.close_now_net:+.4f} | {r.mfe_sofar_entryATR:.3f}/{r.mae_sofar_entryATR:.3f} | {r.final_net:+.4f} |" for r in case.itertuples())+"\n")
    text.append("Long28.05.2023 сначала развился: к4ч net+1.0648, к12ч MFE3.638ATR, затем к24ч net−.7520 и финал−9.2940. При этом ценовойМАЕ к24ч всего.0055ATR относительно первого входа: убыток позиции усилил добор выше первой цены. Long16.10.2023 на4ч ещё был−.2979, а к12/24ч тоже выглядел развитым с большим откатом от MFE; итог+27.3528. Одинаковая словесная категория pullback не определяет правильное решение.\n")
    text.append("43221.10.2026: отсутствие развития к4ч, затем net−2.0449 на12ч и−3.5147 на24ч, финал−5.7346. Но43218.08.2026 при слабом состоянии на12ч net−.9439 восстановился до+20.6393. Чтобы отделить такие пути, нужны конкретные подтверждения состояния и правильная цена ожидания, а не задним числом выбранное правило 'всё слабое закрыть'.\n")
    text.append("## Что сохранено и что делать дальше\n")
    text.append("Файлы: progress_landmarks.csv, progress_landmark_exclusions.csv, progress_state_groups.csv, progress_test_state_totals.csv, progress_24h_predictions.csv, progress_24h_policy.csv, progress_all_trades_overlay.csv, progress_factor_ranking.csv, progress_case_landmarks.csv, progress_review_results.json и зафиксированный spec. Скрипт воспроизводит эти результаты.\n")
    text.append("Четыре целевых as-of проверки подтверждают игнорирование будущего добора/его цены, включение добора ровно в landmark и неизменность4ч-признаков при мутации всех последующих цен/индикаторов/финального исхода. Они не заменяют end-to-end проверку vendor revisions или реальные fills. На следующем этапе нужно дополнить обе стороны incremental метки корректным funding и проследить журналы исполнений. Текущая фиксированная24ч-модель не получила основания для внедрения.\n")
    (ROOT/'progress_review.md').write_text('\n'.join(text),encoding='utf-8')
    print(S[S.group.str.startswith("test2023_plus")].to_string(index=False))
    print("Counts",json.dumps(artifact["landmark_counts"],ensure_ascii=False))
    print("Exclusions",json.dumps(artifact["exclusions"],ensure_ascii=False))
    print("Coefficients",json.dumps(artifact["coefficients"],ensure_ascii=False))

if __name__=="__main__":main()
