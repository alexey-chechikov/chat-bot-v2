"""One fixed, entry-only severe-loss ranking audit of committed 762ec6f trade CSV.

No hyperparameter/threshold sweep. Pure research; static masking is not a stateful replay.
Run from an isolated snapshot: python -X utf8 audit_bad_trades.py
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import platform
import numpy as np
import pandas as pd
import scipy
from scipy.stats import rankdata
import sklearn
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, average_precision_score
from sklearn.preprocessing import StandardScaler

from replay_paths import LAB_ROOT, ORIGINAL_SOURCE, ensure_original_sources
ROOT=LAB_ROOT
SOURCE=ORIGINAL_SOURCE/"research/chart_walk_20261105/out/trade_table_btc.csv"
TYPES=["лонг над синей","шорт под синей","шорт под жёлтой","лонг 432"]
FEATURES=["ADX4h","efficiency24h","crossings_GY_30d","ATR4h_pct",
          "signed_distance_green_ATR","signed_green_slope24h_ATR","signed_RSI4h_minus50","signed_move7d_pct"]
SPEC=dict(commit="762ec6f8124cb499a7104fd74544887190d04acb",source=str(SOURCE),
          features=FEATURES,model="pooled L2 LogisticRegression C=0.1, no interactions, no class_weight",
          target="net_without_funding <= type-specific 20th percentile of Binance 2018-22 outcomes",
          preprocessing="feature 1/99 pct clipping, median imputation, standardization: TRAIN ONLY",
          split="train Binance entry<2023-01-01 and exit<2023-01-01; test Binance entry>=2023-01-01",
          entry_policy="skip score >= type-specific train-score q80, frozen once",
          bins="type-specific train-score q20/q40/q60/q80, frozen once",
          external="Bitstamp 2014-17 backcast: descriptive transport check, not forward validation",
          flow="spot flow24h and price-vs-CVD72h in case descriptors only; no flow model fitted",
          no_sweep=True,path_features_used=False)

def read_data():
    ensure_original_sources()
    d=pd.read_csv(SOURCE,sep=";",decimal=",")
    d["entry_time"]=pd.to_datetime(d["вход UTC"])
    d["exit_time"]=pd.to_datetime(d["выход UTC"])
    d["trade_id"]=d["ряд"]+"|"+d["тип"]+"|"+d["вход UTC"]
    side=d["сторона"].to_numpy(float)
    X=pd.DataFrame({
        "ADX4h":d["ADX 4ч"],"efficiency24h":d["эффективность 24ч"],
        "crossings_GY_30d":d["пересечений З/Ж за 30д"],"ATR4h_pct":d["ATR 4ч, %"],
        "signed_distance_green_ATR":side*d["от зелёной, ATR"],
        "signed_green_slope24h_ATR":side*d["наклон зелёной 24ч, ATR"],
        "signed_RSI4h_minus50":side*(d["RSI 4ч"]-50),
        "signed_move7d_pct":side*d["ход 7д, %"],
    },index=d.index).replace([np.inf,-np.inf],np.nan)
    # These columns are deliberately computed only after X is closed.
    d["net"]=d["итог, % базы"]
    d["split"]=np.where(d["ряд"]=="Bitstamp","Bitstamp_backcast",np.where(d.entry_time<"2023-01-01","train2018_22","test2023_plus"))
    d["era"]=np.where(d["ряд"]=="Bitstamp","Bitstamp2014_17",np.where(d.entry_time<"2023-01-01","Binance2018_22",np.where(d.entry_time<"2025-01-01","Binance2023_24","Binance2025_plus")))
    return d,X

def summary(z,label):
    net=z.net.to_numpy(float)
    skip=z.skip.to_numpy(bool)
    neg=net<0
    pos=net>0
    severe=z.severe.to_numpy(bool)
    top=np.zeros(len(z),bool)
    for typ in TYPES:
        ids=np.flatnonzero((z["тип"]==typ).to_numpy()&pos)
        top[ids[np.argsort(net[ids])[-5:]]]=True
    tp=int((skip&severe).sum())
    den=int(severe.sum())
    raw_delta=-net[skip]
    months=z.entry_time.dt.to_period("M")
    cl=pd.DataFrame({"month":months,"delta":np.where(skip,-net,0)}).groupby("month").delta.sum().to_numpy()
    rng=np.random.default_rng(11109)
    boot=cl[rng.integers(0,len(cl),size=(9999,len(cl)))].sum(1)
    return dict(group=label,n=len(z),baseline=float(net.sum()),static_kept_net=float(net[~skip].sum()),
        static_delta=float(-net[skip].sum()),skip_n=int(skip.sum()),skip_pct=float(skip.mean()),
        severe_n=den,severe_skipped=tp,bad_tail_capture=(tp/den if den else None),
        severe_precision=(tp/int(skip.sum()) if skip.any() else None),base_loss_rate=float(neg.mean()),
        base_severe_rate=float(severe.mean()),losses_n=int(neg.sum()),losses_skipped=int((skip&neg).sum()),
        loss_amount_removed=float(-net[skip&neg].sum()),positive_profit_removed=float(net[skip&pos].sum()),
        strong_winner_n=int(z.strong_win.sum()),strong_winner_skipped=int((skip&z.strong_win.to_numpy(bool)).sum()),
        top5_positive_per_type_n=int(top.sum()),top5_positive_per_type_skipped=int((top&skip).sum()),
        top5_positive_per_type_profit_removed=float(net[top&skip].sum()),
        active_months=len(cl),exploratory_month_bootstrap_static_delta_lo=float(np.quantile(boot,.025)),
        exploratory_month_bootstrap_static_delta_hi=float(np.quantile(boot,.975)),
        severe_auc=float(roc_auc_score(severe,z.score)) if len(np.unique(severe))>1 else None,
        severe_average_precision=float(average_precision_score(severe,z.score)) if severe.any() else None)

def auc_fast(y,x):
    pos=int(y.sum())
    neg=len(y)-pos
    if not pos or not neg:return np.nan
    ranks=rankdata(x)
    return float((ranks[y].sum()-pos*(pos+1)/2)/(pos*neg))

def cluster_auc_ci(z,x,orientation):
    y=z.severe.to_numpy(bool)
    months=z.entry_time.dt.to_period("M").to_numpy()
    unique=np.unique(months)
    ids=[np.flatnonzero(months==m) for m in unique]
    rng=np.random.default_rng(11109)
    null=[]
    for _ in range(999):
        ix=np.concatenate([ids[k] for k in rng.integers(0,len(ids),size=len(ids))])
        value=auc_fast(y[ix],orientation*x[ix])
        if np.isfinite(value):null.append(value)
    return np.quantile(null,[.025,.975]).tolist()

def main():
    (ROOT/"audit_bad_trades_spec.json").write_text(json.dumps(SPEC,ensure_ascii=False,indent=2),encoding="utf-8")
    d,X=read_data()
    assert len(d)==973 and d.trade_id.nunique()==973
    assert not any(x in " ".join(FEATURES).lower() for x in ["mfe","mae","path","funding","outcome"])
    train=(d["split"]=="train2018_22")&(d.exit_time<"2023-01-01")
    test=d["split"]=="test2023_plus"
    assert d.loc[train,"exit_time"].max()<d.loc[test,"entry_time"].min()
    thresholds={}
    d["severe"]=False
    d["strong_win"]=False
    for typ in TYPES:
        y=d.loc[train&(d["тип"]==typ),"net"]
        lo,hi=np.quantile(y,[.2,.8])
        assert lo<0 and hi>0
        thresholds[typ]=dict(severe_net=float(lo),strong_win_net=float(hi),n_train=len(y))
        m=d["тип"]==typ
        d.loc[m,"severe"]=d.loc[m,"net"]<=lo
        d.loc[m,"strong_win"]=d.loc[m,"net"]>=hi
    d["outcome_class"]=np.select([d.severe,d.net<0,d.strong_win,d.net>0],["severe_loss","ordinary_loss","strong_win","ordinary_win"],default="zero")
    # A false-start flag is provisional diagnosis of legacy labels, never model input.
    d["provisional_false_start"]=(d.net<0)&(d["MFE, ATR"]<1)
    d["provisional_gave_back_2ATR"]=(d.net<0)&(d["MFE, ATR"]>=2)
    d["provisional_path_mechanism"]=np.select([
        (d.net<0)&(d["MFE, ATR"]<1),
        (d.net<0)&(d["MFE, ATR"]>=2),
        (d.net<0)&(d["MFE, ATR"]>=1),
        (d.net>0)&(d["MAE, ATR"]>=1),
        d.net>0],
        ["loss_never_plus1ATR","loss_gave_back_ge2ATR","loss_gave_back_1to2ATR","winner_recovered_from_ge1ATR_MAE","winner_MAE_lt1ATR"],
        default="flat_or_unknown")
    lo=X.loc[train].quantile(.01)
    hi=X.loc[train].quantile(.99)
    med=X.loc[train].median()
    A=X.clip(lower=lo,upper=hi,axis=1).fillna(med)
    assert not A.isna().any().any()
    scaler=StandardScaler().fit(A.loc[train])
    Z=scaler.transform(A)
    # Unpenalized global intercept + penalized type offsets. First type is reference.
    D=np.column_stack([Z]+[(d["тип"]==t).to_numpy(float)[:,None] for t in TYPES[1:]])
    model=LogisticRegression(C=.1,max_iter=3000,solver="lbfgs",random_state=11109).fit(D[train],d.loc[train,"severe"])
    d["score"]=model.predict_proba(D)[:,1]
    d["risk_bin"]=0
    d["skip"]=False
    score_edges={}
    for typ in TYPES:
        edges=np.quantile(d.loc[train&(d["тип"]==typ),"score"],[.2,.4,.6,.8])
        score_edges[typ]=edges.tolist()
        m=d["тип"]==typ
        d.loc[m,"risk_bin"]=np.searchsorted(edges,d.loc[m,"score"],side="right")+1
        d.loc[m,"skip"]=d.loc[m,"score"]>=edges[-1]
    # Freeze transforming/threshold artefacts, sufficient for local score reconstruction.
    artifact=dict(spec=SPEC,source_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        feature_missing_counts={str(k):int(v) for k,v in X.isna().sum().items()},
        outcome_thresholds=thresholds,score_edges=score_edges,feature_median=med.to_dict(),clip_lo=lo.to_dict(),clip_hi=hi.to_dict(),
        scaler_mean=scaler.mean_.tolist(),scaler_scale=scaler.scale_.tolist(),
        intercept=float(model.intercept_[0]),coefficients=dict(zip(FEATURES+["type:"+t for t in TYPES[1:]],model.coef_[0].tolist())),
        environment=dict(python=platform.python_version(),numpy=np.__version__,pandas=pd.__version__,scipy=scipy.__version__,sklearn=sklearn.__version__),
        train_ids=d.loc[train,"trade_id"].tolist(),test_ids=d.loc[test,"trade_id"].tolist(),
        limits=["All results are retrospective research on already inspected history, not independent forward confirmation.",
                "Outcome excludes funding; entry/path/add/exit simulator defects remain in source snapshot.",
                "Static removal preserves old trade sequence and is NOT a replay of a changed trading automaton.",
                "Legacy MFE/MAE path flags are provisional, never features.",
                "Monthly active-entry-cluster intervals are exploratory, not stationary equity block-bootstrap or selection-adjusted inference.",
                "Bitstamp is backward transport, not a second prospective test."])
    rows=[]
    for split,z in d.groupby("split",sort=False):
        rows.append(summary(z,split+"|ALL"))
        for typ,p in z.groupby("тип",sort=False): rows.append(summary(p,split+"|"+typ))
    for era,z in d.groupby("era",sort=False):
        rows.append(summary(z,era+"|ALL"))
        for typ,p in z.groupby("тип",sort=False): rows.append(summary(p,era+"|"+typ))
    S=pd.DataFrame(rows)
    bins=d.groupby(["split","тип","risk_bin"],observed=True).agg(n=("net","size"),net=("net","sum"),
        severe_n=("severe","sum"),loss_rate=("net",lambda x:float((x<0).mean())),
        severe_rate=("severe","mean"),strong_win_n=("strong_win","sum"),avg_risk=("score","mean")).reset_index()
    classes=d.groupby(["era","тип","outcome_class"],observed=True).agg(n=("net","size"),net=("net","sum"),
        median_net=("net","median"),mean_duration_h=("часов в сделке","mean"),
        provisional_false_starts=("provisional_false_start","sum"),provisional_gaveback2ATR=("provisional_gave_back_2ATR","sum")).reset_index()
    # Descriptive feature medians are not inference and are not used to choose the fitted model.
    descript=pd.concat([d[["era","тип","outcome_class"]],X,
        d[["дельта агрессора спота 24ч, доля","цена минус CVD в канале 72ч"]]],axis=1)
    descript=descript.groupby(["era","тип","outcome_class"],observed=True).median(numeric_only=True).reset_index()
    descript=descript.merge(d.groupby(["era","тип","outcome_class"],observed=True).size().rename("n").reset_index(),how="left")
    factorrows=[]
    for typ in TYPES:
        tr=d[train&(d["тип"]==typ)]
        te=d[test&(d["тип"]==typ)]
        for feature in FEATURES:
            xx=X.loc[tr.index,feature].to_numpy(float)
            yy=tr.severe.to_numpy(bool)
            yytest=te.severe.to_numpy(bool)
            xt=X.loc[te.index,feature].to_numpy(float)
            ar=auc_fast(yy,xx)
            orientation=1 if ar>=.5 else -1
            tra=auc_fast(yy,orientation*xx)
            tea=auc_fast(yytest,orientation*xt)
            ci_train=cluster_auc_ci(tr,xx,orientation)
            ci_test=cluster_auc_ci(te,xt,orientation)
            factorrows.append(dict(type=typ,feature=feature,risk_direction_from_train="higher" if orientation==1 else "lower",
                train_severe_median=float(np.median(xx[yy])),train_rest_median=float(np.median(xx[~yy])),
                train_median_diff_in_train_std=float((np.median(xx[yy])-np.median(xx[~yy]))/np.std(xx,ddof=0)),
                train_auc_risk=tra,train_auc_cluster_lo=ci_train[0],train_auc_cluster_hi=ci_train[1],
                test_severe_median=float(np.median(xt[yytest])),test_rest_median=float(np.median(xt[~yytest])),
                test_median_diff_in_train_std=float((np.median(xt[yytest])-np.median(xt[~yytest]))/np.std(xx,ddof=0)),
                test_auc_fixed_direction=tea,test_auc_cluster_lo=ci_test[0],test_auc_cluster_hi=ci_test[1],
                descriptive_direction_preserved=tea>.5,n_train=len(tr),severe_train=int(yy.sum()),n_test=len(te),severe_test=int(yytest.sum())))
    factors=pd.DataFrame(factorrows).sort_values(["type","train_auc_risk"],ascending=[True,False])
    factors["rank_within_type_from_train"]=factors.groupby("type").cumcount()+1
    # Two worst TEST losses per type and nearest TEST positive winner in fixed standardized entry coordinates.
    caseids=[]
    pairrecords=[]
    for typ in TYPES:
        losses=d[test&(d["тип"]==typ)&(d.net<0)].nsmallest(2,"net")
        winners=d[test&(d["тип"]==typ)&(d.net>0)]
        for i in losses.index:
            dist=np.linalg.norm(Z[winners.index]-Z[i],axis=1)
            j=winners.index[int(dist.argmin())]
            pairrecords.append(dict(loss_id=d.loc[i,"trade_id"],winner_id=d.loc[j,"trade_id"],
                standardized_distance=float(dist.min()),loss_net=float(d.loc[i,"net"]),winner_net=float(d.loc[j,"net"])))
            caseids.extend([i,j])
    casecols=["trade_id","ряд","тип","вход UTC","выход UTC","net","outcome_class","score","risk_bin","skip",
              "MFE, ATR","MAE, ATR","часов до MFE","часов до MAE","часов в сделке","provisional_path_mechanism",
              "дельта агрессора спота 24ч, доля","цена минус CVD в канале 72ч","прошлая сделка, % базы"]
    cases=pd.concat([d.loc[sorted(set(caseids)),casecols],X.loc[sorted(set(caseids))]],axis=1)
    pathgroups=d.groupby(["era","тип","provisional_path_mechanism"],observed=True).agg(n=("net","size"),net=("net","sum"),median_hours_to_MFE=("часов до MFE","median"),median_hours_to_MAE=("часов до MAE","median"),median_duration_h=("часов в сделке","median")).reset_index()
    for name,df in [("policy",S),("bins",bins),("classes",classes),("feature_medians",descript),("factor_ranking",factors),("path_groups",pathgroups),("cases",cases),("case_pairs",pd.DataFrame(pairrecords))]:
        df.to_csv(ROOT/("audit_bad_trades_"+name+".csv"),index=False,encoding="utf-8-sig")
    pd.concat([d[["trade_id","split","era","тип","net","outcome_class","severe","strong_win","score","risk_bin","skip",
       "provisional_false_start","provisional_gave_back_2ATR","provisional_path_mechanism"]],X],axis=1).to_csv(ROOT/"audit_bad_trades_predictions.csv",index=False,encoding="utf-8-sig")
    artifact["policy_summary"]=S.to_dict("records")
    artifact["test_bins"]=bins[bins.split=="test2023_plus"].to_dict("records")
    artifact["case_pairs"]=pairrecords
    artifact["factor_ranking"]=factors.to_dict("records")
    (ROOT/"audit_bad_trades_results.json").write_text(json.dumps(artifact,ensure_ascii=False,indent=2),encoding="utf-8")
    sections=[]
    sections.append("# Плохие сделки: 973 исходных случая, признаки до входа и один риск-рейтинг\n")
    sections.append("Исходный snapshot `762ec6f8124cb499a7104fd74544887190d04acb`; SHA256 таблицы `"+artifact["source_sha256"]+"`. Это реальный численный пересчёт закоммиченной CSV, а не проект анализа. Исторические ошибки funding/добора/исполнения/пути ещё не исправлены. Все суммы — % фиксированной базы, без funding, по исходным сделкам. Path-поля имеют временный статус; они не входят в признаки модели.\n")
    sections.append("## Определения и заранее выбранная модель\n")
    sections.append("«Тяжёлый убыток» = итог не выше 20-го перцентиля своего типа на Binance2018–22; «сильный победитель» = итог не ниже 80-го перцентиля той же обучающей выборки. Остальные отрицательные/положительные — обычный убыток/плюс. Это операционные ретроспективные классы, не доказательство неправильности решения об исходном входе. Порог каждого типа различен; вероятность класса не равна размеру денежной потери.\n")
    sections.append("| Тип | n train | Тяжёлый убыток <= | Сильный победитель >= |\n|---|---:|---:|---:|\n"+"\n".join(f"| {t} | {v['n_train']} | {v['severe_net']:.4f} | {v['strong_win_net']:.4f} |" for t,v in thresholds.items())+"\n")
    sections.append("Одна L2-логистика C=.1: общие восемь коэффициентов и смещения по типам. До просмотра результатов выбраны ADX4ч, ER24ч, число пересечений З/Ж30д, ATR4ч%, направленное расстояние до зелёной/ATR, направленный наклон зелёной24ч/ATR, направленный RSI−50, направленный ход7д. Направленный означает ×side. Все восемь полей заполнены во всех973 строках. Clipping1/99, медианы и scaler выучены только на train. Funding, его coverage, будущий MFE/MAE, ход после входа, добор, длительность и итог не входят в X. Flow оставлен для описания кейсов. Список/гиперпараметр/порог не перебирались.\n")
    sections.append("Train365 (112/147/40/66 по long/shortblue/shortyellow/432), test288 (106/87/45/50). Порог пропуска = q80 **обучающего** score отдельно по типу; границы пяти корзин также только train. Bitstamp320 — обратная историческая проверка переноса, не forward. История уже изучалась, поэтому test — temporal holdout для этого fit, но не новый независимый эксперимент.\n")
    sections.append("## Состав классов по эпохам\n")
    sections.append("| Эпоха | Тип | n | Тяжёлые убытки | Обычные убытки | Обычные плюсы | Сильные победители | Ноль |\n|---|---|---:|---:|---:|---:|---:|---:|\n"+"\n".join(
        f"| {era} | {typ} | {len(z)} | {int((z.outcome_class=='severe_loss').sum())} | {int((z.outcome_class=='ordinary_loss').sum())} | {int((z.outcome_class=='ordinary_win').sum())} | {int((z.outcome_class=='strong_win').sum())} | {int((z.outcome_class=='zero').sum())} |"
        for (era,typ),z in d.groupby(["era","тип"],sort=False))+"\n")
    sections.append("## Главный результат: риск убытка не равен выгодности пропуска\n")
    sections.append("| Проверка2023+ | n | База | После статического пропуска | Δ | Пропущено | Тяжёлых поймано | AUC тяжёлого убытка | Потеряно hindsight top5 |\n|---|---:|---:|---:|---:|---:|---:|---:|---:|\n"+"\n".join(
        f"| {r.group.split('|')[-1]} | {r.n} | {r.baseline:.2f} | {r.static_kept_net:.2f} | {r.static_delta:+.2f} | {r.skip_n} | {r.severe_skipped}/{r.severe_n} | {r.severe_auc:.3f} | {r.top5_positive_per_type_skipped}/{r.top5_positive_per_type_n} |"
        for r in S[S.group.str.startswith("test2023_plus")].itertuples())+"\n")
    alltest=S[S.group=="test2023_plus|ALL"].iloc[0]
    sections.append(f"Фильтр удалил {alltest.skip_n}/288 ({alltest.skip_pct:.1%}) вместо ожидаемых по train около20%: сдвиг score существенен. Удалено {alltest.losses_skipped}/177 убыточных сделок; предотвращённые убытки +{alltest.loss_amount_removed:.2f} проиграли уничтоженной положительной прибыли {alltest.positive_profit_removed:.2f}. Из46 сильных победителей удалены24; из20 лучших положительных сделок (top5 каждого типа, лишь диагностическая hindsight группа) —13 с прибылью155.03. AUC=.578 не превращается в полезный фильтр. Удаление109 сделок захватывает18/41 тяжёлых исходов, precision16.5% против базовых14.2% — слабая концентрация.\n")
    sections.append("Это **статический контрфактический отбор старого списка**, не новый backtest автомата: пропуск входа может изменить блокировки, последующие сигналы и позиции. Оценки являются диагностикой этого списка; точный эффект требует полного replay. Экспозиция уменьшилась, риск не выровнен.\n")
    sections.append("По эпохам: Binance2023–24 база276.77→141.14 (Δ−135.63), с2025 база67.48→42.54 (Δ−24.94). Ни один из четырёх типов не улучшился за всю проверку2023+. Единственное позднее положительное подокно — shortyellow с2025:18 сделок, Δ+4.69, но весь тип2023+ Δ−8.83; выбирать его по этому результату нельзя. Месячные исследовательские интервалы и полный состав приведены в policy.csv.\n")
    sections.append("## Корзины риска на проверке\n")
    sections.append("Границы заморожены на train. Ячейка = n / тяжёлых / суммарный итог. Последняя корзина совпадает с пропускаемыми.\n")
    sections.append("| Тип | Q1 низкий риск | Q2 | Q3 | Q4 | Q5 высокий риск |\n|---|---|---|---|---|---|\n"+"\n".join(
        "| "+typ+" | "+" | ".join(next((f"{int(r.n)} / {int(r.severe_n)} / {r.net:+.2f}" for r in bins[(bins.split=='test2023_plus')&(bins['тип']==typ)&(bins.risk_bin==q)].itertuples()),"0 / 0 / 0") for q in range(1,6))+" |" for typ in TYPES)+"\n")
    sections.append("Нет монотонной концентрации тяжёлых потерь по всему диапазону. В Q5 long находятся8 тяжёлых исходов и12 сильных победителей, итог+83.51. У432 Q5 даёт+64.00 и лишь1 тяжёлый исход из17. Для shortblue большая часть тяжёлых потерь оказаласьQ4 (6/8), а неQ5. Менять порог после просмотра этой таблицы — новый поиск.\n")
    sections.append("## Ранжирование самих факторов\n")
    sections.append("Все32 сравнения = восемь заранее заданных факторов × четыре типа. Ранг и направление риска определены только train; на test направление не переворачивается. AUC относится к тяжёлому убытку против всех остальных. Интервалы —999 пересэмплирований активных месяцев входа; они описательные, без поправки на32 сравнения/уже просмотренную историю и без полной временной equity. Полные медианы severe/rest, стандартизованные различия и интервалы находятся в factor_ranking.csv.\n")
    sections.append("| Тип | Ранг train | Фактор и риск-направление | AUC train | AUC test (95% CI) |\n|---|---:|---|---:|---|\n"+"\n".join(
        f"| {r.type} | {r.rank_within_type_from_train} | {r.feature}: {r.risk_direction_from_train} | {r.train_auc_risk:.3f} | {r.test_auc_fixed_direction:.3f} [{r.test_auc_cluster_lo:.3f}; {r.test_auc_cluster_hi:.3f}] |" for r in factors.itertuples())+"\n")
    sections.append("Наиболее содержательная сохраняющаяся группа — геометрия входа long: расстояние до зелёной AUC.656→.624, наклон зелёной.624→.668; RSI.709→.621. Но это ещё не оценка net-цены пропуска, и положительные победители могут иметь ту же геометрию. У432 наиболее сильный наtrain ход7д меняет смысл: AUC.672→.182, RSI.514→.102; нельзя переносить «перекупленность плоха» на все типы. Уshortblue расстояние.575→.737, но всего8 тяжёлых test-исходов; RSI почти случайный наtrain(.502), поэтому его test.739 — не независимо выбранный сильный фактор. Все эти сравнения — диагностика, не32 новых подтверждённых сигналов.\n")
    sections.append("У единой логистики коэффициенты общие для типов: разные направления/нелинейности могли быть потеряны. Отрицательный результат одной заранее выбранной модели не доказывает бесполезность всех entry-признаков или всех компактных моделей. Новый fit после изучения этих строк будет следующей гипотезой, не исправлением текущего результата.\n")
    sections.append("## Конкретные плохие случаи рядом с похожими победителями\n")
    sections.append("Выбраны два худших test-убытка каждого типа; рядом ближайший прибыльный test-случай того же типа в восьми train-standardized/clipped координатах. Поиск пары использует результат только для объяснения уже полученных исходов; пары не независимые эксперименты и не использовались в модели.\n")
    sections.append("| Убыточный вход | Итог | Ближайший прибыльный вход | Итог | Расстояние в8D |\n|---|---:|---|---:|---:|\n"+"\n".join(
        f"| {r['loss_id']} | {r['loss_net']:.4f} | {r['winner_id']} | {r['winner_net']:.4f} | {r['standardized_distance']:.3f} |" for r in pairrecords)+"\n")
    sections.append("1. **Long28.05.2023 −9.2940 против10.04.2023 +2.7405.** До входа обе ситуации: ADX19.20/22.70, ER24ч.618/.506, всего2 пересечения за30д, distanceGreen2.379/3.454ATR, агрессор спота+.0657/+.0604. Высокий поток покупок и геометрия тренда сами по себе не разделили исход. По временной старой path-разметке проигравший имел MFE3.638ATR уже через5ч, затем MAE8.443ATR через192ч и выход; победитель MFE6.214 через83ч, MAE.354 через1ч. Это пример раннего развития и последующего возврата, требующий анализа удержания, а не только входа.\n")
    sections.append("2. **Long29.08.2023 −6.2468 против16.10.2023 +27.3528.** ADX29.02/25.87, ER.630/.614, distanceGreen4.943/4.611ATR, RSI82.04/77.79. Модель присвоила обоимQ5 и выкинула оба. Убыточный по старому path едва получил.167ATR через1ч и оставался312ч; победитель принёс35.051ATR MFE через187ч. Похожий «поздний» вход может закончиться срывом или большим трендом.\n")
    sections.append("3. **Shortblue10.10.2024 −3.7090 против08.05.2023 +4.3352.** До входа directed distanceGreen1.502/1.517ATR, ATR1.267/1.320%, ER.306/.289. В убыточной позиции MFE2.20ATR через19ч сменился MAE2.361 через40ч; победитель MFE6.977 через116ч и MAE.535 через1ч. Доходное решение «ждать развившийся short» нельзя вывести из итогового MFE задним числом.\n")
    sections.append("4. **Shortyellow14.05.2025 −3.6665 против23.05.2025 +2.5072.** ОбеQ5: ADX37.34/42.46, distanceGreen.965/.900ATR, направленный RSI−3.758/−3.335. Но наблюдённая дельта спота+.0111 против−.0938 (продавцы у победителя); это описание одной пары, не доказанный flow-фильтр. Убыточный MFE1.714ATR через35ч, MAE2.903 через161ч; победитель MFE3.643 через180ч, MAE1.103 через94ч. Позднее развитие и промежуточная просадка бывают и у победителя.\n")
    sections.append("5. **43221.10.2026 −5.7346 против08.05.2025 +5.4064.** Очень близкая пара distance.628: ADX27.82/25.70, ER.529/.440, distanceGreen2.521/2.710ATR, дельта спота+.0602/+.0652. Модель оставила обаQ4. Убыточный старый path MFE.437ATR через1ч и MAE6.489 через72ч; победитель MFE5.369 через68ч, MAE.395 через3ч. Это срыв пробоя против развившегося пробоя при схожем входном состоянии.\n")
    sections.append("Нельзя называть `MFE<1ATR` установленной неудачей уже на4/12/24ч: это метка полного будущего пути. Она лишь отделяет сделки, которые вообще не дали+1ATR в исходном replay. Группа `loss_gave_back_ge2ATR` — убыточные позиции, имевшие >=2ATR положительного хода; это не готовая рекомендация фиксировать2ATR. В path_groups.csv отдельно даны количество, деньги и времена экстремумов; для реальных решений нужны точные corrected milestones и заявки.\n")
    sections.append("## Что передаётся следующему этапу\n")
    sections.append("Сохранены все973 scores и classes в predictions.csv; замороженный preprocessing/model/thresholds и IDs в results.json; классы по эпохам, rank bins, risk-filter price, факторные медианы и32 ранжирования, кейсы и provisional path-группы — отдельными CSV. Скрипт не меняет производственные файлы.\n")
    sections.append("Следующий полезный шаг — наложить на те же ID исправленные cashflows/path и реальные4/12/24ч состояния. До этого не переобучать следующую модель и не менять входы. При анализе развития оценивать будущий **добавочный net** от HOLD/ADD против действия сейчас, сохраняя конечных победителей с промежуточной просадкой. Важнее разделить плохой вход, отсутствие развития и отданный хороший ход, чем подменить их одной меткой 'проиграл'.\n")
    (ROOT/"audit_bad_trades.md").write_text("\n".join(sections),encoding="utf-8")
    print(S[S.group.str.startswith("test2023_plus")].to_string(index=False))
    print("\nCoefficients",json.dumps(artifact["coefficients"],ensure_ascii=False))
    print("\nTrain thresholds",json.dumps(thresholds,ensure_ascii=False))
    print("\nCases",pd.DataFrame(pairrecords).to_string(index=False))

if __name__=="__main__": main()
