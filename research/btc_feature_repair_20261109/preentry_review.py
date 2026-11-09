"""Eight fixed, entry-only descriptive axes; no model/policy/threshold search.

Run once: python -X utf8 preentry_review.py
All rolling windows use a reindexed UTC hourly clock; missing != zero.
"""
from __future__ import annotations
import hashlib,json,pickle
from datetime import datetime,timezone
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.stats import rankdata

from replay_paths import LAB_ROOT, ORIGINAL_SOURCE, DATA_DIR, ensure_original_sources, auxiliary_file

ROOT=LAB_ROOT
OLD=ORIGINAL_SOURCE
SOURCE=DATA_DIR/"spot_BTCUSDT_1h.csv"
H=3600
FEATURES=["signed_move12h_ATR","signed_acceleration4h_ATR","pullback24h_ATR",
          "signed_green_distance_change12h_ATR","ER24_change12h","volume4h_relative30d",
          "signed_taker_fraction4h","signed_taker_fraction4h_minus24h"]
TYPES=["лонг над синей","шорт под синей","шорт под жёлтой","лонг 432"]
PAIR_ROWS=[0,1,2,4,6]
SPEC={"axes":FEATURES,"comparisons":32,"new_model_or_policy":False,
      "target":"original CSV net_without_funding <= per-type train q20",
      "train":"Binance entry<2023-01-01 AND exit<2023-01-01; only mature labels",
      "test":"Binance entry>=2023-01-01; direction and ranking frozen from train",
      "orientation":"risk higher if train raw AUC>=0.5; otherwise lower; no test flip",
      "coverage":"exact UTC endpoints; ER24 all25 closes, high/low/flow full 4/24 hourly observations; volume baseline >=648/720 prior rolling4h observations",
      "volume_baseline":"median of past 720 rolling4h volumes, current observation excluded",
      "delta_definition":"delta_k = sum(2*taker_base-volume,k hours)/sum(volume,k hours)",
      "CI":"999 resamples of active entry-month clusters, exploratory 95% percentile intervals; >=25 finite observations and both classes",
      "case_pair_rows":PAIR_ROWS,"prefix_check":"recompute raw/green input prefix at five selected case entries",
      "novelty_limit":"Working specification fixed before this run; original outcomes and existing matched pairs were already inspected. Not an untouched holdout or historical preregistration."}

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write_json(name,obj):
    (ROOT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding="utf-8")

def build_frame(raw,green):
    ts=raw["ms"].to_numpy(np.int64)//1000+H
    x=raw.copy();x.index=ts
    assert x.index.is_unique and x.index.is_monotonic_increasing
    grid=np.arange(int(ts.min()),int(ts.max())+H,H)
    z=x.reindex(grid)
    c=z["close"]
    v=z["volume"]
    tb=z["taker_base"]
    valid=np.isfinite(v)&np.isfinite(tb)&(v>=0)&(tb>=0)&(tb<=v+1e-6)
    v=v.where(valid);delta=(2*tb-v).where(valid)
    v4=v.rolling(4,min_periods=4).sum();v24=v.rolling(24,min_periods=24).sum()
    d4=delta.rolling(4,min_periods=4).sum()/v4.where(v4>0)
    d24=delta.rolling(24,min_periods=24).sum()/v24.where(v24>0)
    er=(c-c.shift(24)).abs()/c.diff().abs().rolling(24,min_periods=24).sum().replace(0,np.nan)
    g=green.reindex(grid)
    f=pd.DataFrame(index=grid)
    f["price"]=c;f["green"]=g
    f["move12h"]=c-c.shift(12)
    f["accel4h"]=c-2*c.shift(4)+c.shift(8)
    f["high24"]=z["high"].rolling(24,min_periods=24).max()
    f["low24"]=z["low"].rolling(24,min_periods=24).min()
    f["green_distance_change12h"]=(c-g)-(c-g).shift(12)
    f["ER24"]=er;f["ER24_change12h"]=er-er.shift(12)
    base=v4.shift(1).rolling(720,min_periods=648).median()
    f["volume4h_relative30d"]=v4/base.where(base>0)
    f["taker_fraction4h"]=d4;f["taker_fraction24h"]=d24
    f["delta_change"]=d4-d24
    f["volume4h"]=v4;f["volume24h"]=v24
    f["raw_delta4h"]=delta.rolling(4,min_periods=4).sum()
    f["raw_delta24h"]=delta.rolling(24,min_periods=24).sum()
    f["coverage4h"]=z["close"].notna().rolling(4,min_periods=4).sum()
    f["coverage24h"]=z["close"].notna().rolling(24,min_periods=24).sum()
    f["volume_baseline_valid4h"]=v4.shift(1).rolling(720,min_periods=1).count()
    return f

def axes(row,side,atr):
    return dict(zip(FEATURES,[side*row.move12h/atr,side*row.accel4h/atr,
        (row.high24-row.price if side==1 else row.price-row.low24)/atr,
        side*row.green_distance_change12h/atr,row.ER24_change12h,row.volume4h_relative30d,
        side*row.taker_fraction4h,side*row.delta_change]))

def auc(y,x):
    y=np.asarray(y,bool);p=int(y.sum());n=len(y)-p
    return float((rankdata(x)[y].sum()-p*(p+1)/2)/(p*n)) if p and n else np.nan

def describe(part,feature,orientation):
    z=part[np.isfinite(part[feature])].copy()
    x=z[feature].to_numpy(float);y=z.severe.to_numpy(bool)
    result={"n":len(z),"severe_n":int(y.sum()),"rest_n":int((~y).sum()),"coverage_fraction":len(z)/len(part),
            "severe_median":float(np.median(x[y])) if y.any() else None,
            "rest_median":float(np.median(x[~y])) if (~y).any() else None}
    if len(z)<25 or len(np.unique(y))<2:
        result["status"]="insufficient_n_or_class";return result
    result["status"]="exploratory"
    result["auc"]=auc(y,orientation*x)
    months=z.entry_time.dt.strftime("%Y-%m").to_numpy()
    ids=[np.flatnonzero(months==m) for m in np.unique(months)]
    rng=np.random.default_rng(11110)
    draws=[]
    for _ in range(999):
        ix=np.concatenate([ids[j] for j in rng.integers(0,len(ids),size=len(ids))])
        xx,yy=x[ix],y[ix]
        if len(np.unique(yy))<2:continue
        sm,rm=float(np.median(xx[yy])),float(np.median(xx[~yy]))
        draws.append([auc(yy,orientation*xx),sm,rm,sm-rm])
    draws=np.asarray(draws)
    result["active_entry_months"]=len(ids);result["valid_bootstrap_draws"]=len(draws)
    ci=np.quantile(draws,[.025,.975],axis=0)
    for j,label in enumerate(["auc","severe_median","rest_median","median_difference"]):
        result[label+"_lo"]=float(ci[0,j]);result[label+"_hi"]=float(ci[1,j])
    result["median_difference"]=result["severe_median"]-result["rest_median"]
    return result

def fmt(x,d=3):return "NA" if x is None or not np.isfinite(x) else f"{x:.{d}f}"

def main():
    ensure_original_sources()
    spec_path=ROOT/"preentry_spec.json"
    if spec_path.exists():
        existing=json.loads(spec_path.read_text(encoding="utf-8"));assert existing["spec"]==SPEC
    else:write_json("preentry_spec.json",{"fixed_before_run_at":datetime.now(timezone.utc).isoformat(),"spec":SPEC})
    with (ROOT/"replay_cache.pkl").open("rb") as fh:cache=pickle.load(fh)
    ca=cache["Binance"]["old_a"]
    raw=pd.read_csv(SOURCE)
    green=pd.Series(ca["f_G"],index=np.asarray(ca["t"],np.int64))
    frame=build_frame(raw,green)
    trades=pd.read_csv(OLD/"research/chart_walk_20261105/out/trade_table_btc.csv",sep=";",decimal=",")
    trades=trades[trades["ряд"]=="Binance"].copy()
    rows=[]
    for _,r in trades.iterrows():
        entry=pd.Timestamp(r["вход UTC"],tz="UTC");sec=int(entry.timestamp());side=int(r["сторона"])
        tag=r["тип"].split(" ",1)[1]
        e=cache["Binance"]["old_trades"][(sec,tag,side)]
        atr=float(e["pos"]["atr"])
        point=frame.loc[sec]
        assert point.price==float(r["цена входа"])
        rows.append({"trade_id":"Binance|"+r["тип"]+"|"+r["вход UTC"],"type":r["тип"],"entry_time":entry,
                     "exit_time":pd.Timestamp(r["выход UTC"],tz="UTC"),"side":side,"atr_entry":atr,"entry_price":point.price,
                     "original_net":float(r["итог, % базы"]),**axes(point,side,atr),
                     "coverage4h":point.coverage4h,"coverage24h":point.coverage24h,"volume_baseline_valid4h":point.volume_baseline_valid4h})
    d=pd.DataFrame(rows)
    cutoff=pd.Timestamp("2023-01-01",tz="UTC")
    train=(d.entry_time<cutoff)&(d.exit_time<cutoff)
    test=d.entry_time>=cutoff
    d["split"]=np.select([train,test],["train2018_22","test2023_plus"],default="unmatured_at_cutoff")
    d["severe"]=False;thresholds={}
    for typ in TYPES:
        tr=d[train&(d.type==typ)]
        q=float(tr.original_net.quantile(.2))
        thresholds[typ]={"train_n":len(tr),"severe_q20":q}
        d.loc[d.type==typ,"severe"]=d.loc[d.type==typ,"original_net"]<=q
    # Assert parity with the independently established severe-loss labels.
    prior=json.loads(auxiliary_file("audit_bad_trades_results.json").read_text(encoding="utf-8"))
    if "thresholds" in prior:
        for typ,value in thresholds.items():assert np.isclose(value["severe_q20"],prior["thresholds"][typ]["severe_net"])
    ranking=[]
    for typ in TYPES:
        tr=d[train&(d.type==typ)];te=d[test&(d.type==typ)]
        for feature in FEATURES:
            complete=tr[np.isfinite(tr[feature])]
            raw_auc=auc(complete.severe,complete[feature])
            orientation=1 if raw_auc>=.5 else -1
            item={"type":typ,"feature":feature,"risk_direction_train":"higher" if orientation==1 else "lower",
                  "orientation":orientation,"raw_train_auc":raw_auc}
            for lab,part in [("train",tr),("test",te)]:
                item.update({lab+"_"+k:v for k,v in describe(part,feature,orientation).items()})
            item["test_direction_preserved"]=bool(item.get("test_auc",np.nan)>.5)
            ranking.append(item)
    rank=pd.DataFrame(ranking).sort_values(["type","train_auc","feature"],ascending=[True,False,True])
    rank["rank_from_train"]=rank.groupby("type").cumcount()+1
    pairs=pd.read_csv(auxiliary_file("audit_bad_trades_case_pairs.csv")).iloc[PAIR_ROWS].copy().reset_index(drop=True)
    paths=[];prefix_checked=0
    for pair_i,pair in pairs.iterrows():
        for role in ["loss","winner"]:
            rec=d.set_index("trade_id").loc[pair[role+"_id"]]
            sec=int(rec.entry_time.timestamp())
            for lag in [-24,-12,-4,0]:
                pt=frame.loc[sec+lag*H]
                paths.append({"pair":int(pair_i+1),"role":role,"trade_id":pair[role+"_id"],"type":rec.type,
                    "entry_time":rec.entry_time,"original_net":rec.original_net,"hours_to_entry":lag,
                    "observed_time":pd.to_datetime(sec+lag*H,unit="s",utc=True),"price":pt.price,"green":pt.green,
                    "signed_price_vs_entry_ATR":rec.side*(pt.price-rec.entry_price)/rec.atr_entry,
                    "taker_fraction4h":pt.taker_fraction4h,"signed_taker_fraction4h":rec.side*pt.taker_fraction4h,
                    "taker_fraction24h":pt.taker_fraction24h,"signed_delta_acceleration":rec.side*pt.delta_change,
                    "volume4h":pt.volume4h,"raw_delta4h":pt.raw_delta4h,"volume4h_relative30d":pt.volume4h_relative30d,
                    "ER24":pt.ER24,"coverage4h":pt.coverage4h,"coverage24h":pt.coverage24h})
            if role=="loss":
                prefix_raw=raw[(raw.ms.to_numpy(np.int64)//1000+H)<=sec]
                prefix=build_frame(prefix_raw,green[green.index<=sec])
                x=axes(prefix.loc[sec],rec.side,rec.atr_entry)
                assert all((pd.isna(x[k]) and pd.isna(rec[k])) or np.isclose(x[k],rec[k],rtol=0,atol=1e-12) for k in FEATURES)
                prefix_checked+=1
    paths=pd.DataFrame(paths)
    d.to_csv(ROOT/"preentry_features.csv",index=False,encoding="utf-8-sig")
    rank.to_csv(ROOT/"preentry_factor_ranking.csv",index=False,encoding="utf-8-sig")
    pairs.to_csv(ROOT/"preentry_case_pairs.csv",index=False,encoding="utf-8-sig")
    paths.to_csv(ROOT/"preentry_case_trajectories.csv",index=False,encoding="utf-8-sig")
    results={"spec":SPEC,"thresholds":thresholds,"n":len(d),"train_n":int(train.sum()),"test_n":int(test.sum()),
             "unmatured_at_cutoff":int((~train&~test).sum()),"comparisons":len(rank),"prefix_checks_passed":prefix_checked,
             "price_entry_matches":len(d),"sources":{"spot_hour_sha256":sha(SOURCE),"cache_sha256":sha(ROOT/"replay_cache.pkl"),
             "original_trade_table_sha256":sha(OLD/"research/chart_walk_20261105/out/trade_table_btc.csv")},
             "ranking":rank.replace({np.nan:None}).to_dict("records"),"cases":pairs.to_dict("records"),
             "limitations":["32 exploratory comparisons, CIs not multiplicity or selection adjusted",
               "Entry-month cluster intervals are descriptive, not paired equity block bootstrap",
               "No policy, multivariate model, new thresholds, or OOS feature flip fitted",
               "Original 2023+ history and selected cases were already inspected; these are not new independent validations",
               "News, OI and futures orderflow absent from these eight axes; volume does not establish a news cause",
               "Known-time is assigned closed-hour time; vendor revisions and live availability not reconstructed"]}
    write_json("preentry_results.json",results)
    lines=["# Восемь осей ДО входа: фактические цены и spot-поток\n",
      "Фиксированная описательная проверка исходных Binance-сделок 762ec6f. Новый алгоритм входа/выхода не искался. Направление риска и порядок факторов получены только на зрелых сделках 2018–2022; на 2023+ они не переворачиваются. Метка тяжёлого убытка — прежний q20 net без funding каждого типа. История уже просматривалась: это 32 исследовательских сравнения, а не подтверждённая alpha.\n",
      f"Данные: {len(d)} сделок; train {int(train.sum())}, test {int(test.sum())}, исключено из train из-за незрелой метки {int((~train&~test).sum())}. Цены входа {len(d)}/{len(d)} совпали с исходной таблицей; {prefix_checked} prefix-проверок восьми осей прошли.\n",
      "## Определения и покрытие\n",
      "1. signed_move12h/ATRentry = s*(C0−C−12)/ATRentry.\n2. signed_acceleration = s*((C0−C−4)−(C−4−C−8))/ATRentry.\n3. pullback24h = (maxHigh24−C0)/ATRentry для long, (C0−minLow24)/ATRentry для short.\n4. signed_green_distance_change12h = s*((C0−G0)−(C−12−G−12))/ATRentry.\n5. ER24_change12h: изменение abs(C0−C−24)/sum(abs(hourly differences),24h) за12ч.\n6. Volume4h / медиана720 прошлых rolling4h объёмов (текущий не включён).\n7. s*δ4h.\n8. s*(δ4h−δ24h), где δk=Σ(2*taker_base−V)/ΣV за k календарных часов.\n",
      "s=+1 long, −1 short. Все окна — реальный UTC clock, восстановлена полная часовая сетка; пропуск не заполняется нулём. Endpoints требуют точных наблюдений; high/low и flow окна требуют всех24/4 часов, ER всех25 closes, volume reference — не менее648/720 прошлых значений. Неполные значения не импутируются. Тесты каждого фактора поэтому показывают собственные n и coverage. Green — состояние исходного закрытого4h индикатора.\n",
      "## Ранги и перенос направления\n",
      "Конкретное наблюдение: у short под синей тестовые severe-сделки уже прошли за12ч медианно2.508ATR против1.605 у остальных; рост ER24 за12ч —0.300 против0.122; увеличение signed расстояния от green —1.939 против1.305ATR. Их AUC в фиксированном направлении0.769/0.769/0.753; nominal CI ниже указаны. Эти три величины во многом описывают один уже состоявшийся направленный импульс, а не три независимых подтверждения. Это зацепка для разбора риска позднего short после снижения, а не доказанный фильтр.\n",
      "Для432 pullback24h: test severe median0.552ATR против0.337, AUC0.716[0.555;0.841], но severe всего5. Напротив, первый по train-рангу432 фактор acceleration не перенёс знак: test AUC0.302[0.152;0.475]. Направление не переворачивали.\n",
      "Прямой signed taker4h даёт test AUC0.51–0.55 для всех четырёх типов, интервалы пересекают0.5. У разности4h−24h test AUC ниже0.5 во всех четырёх типах при зафиксированном train направлении. Объёмный фактор также не переносит своё train направление для обоих short и432. Исполненный агрессорский поток сам по себе не дал чистого ранжирования тяжёлых убытков.\n",
      "Всего22 из32 описательных направлений сохранили AUC>0.5; четыре nominal95% CI оказались выше0.5 (три близкие величины short и pullback432). Это не22/4 независимых успеха: признаки зависимы, коррекция на32 сравнения и прежние просмотры не проведена.\n",
      "AUC — тяжёлый убыток против остальных; >0.5 означает совпадение направления, выбранного на train. Интервалы —999 cluster resamples активных месяцев входа; они не учитывают32 сравнения/выбор направления/старые просмотры и не являются CI будущей equity. Ранги в таблице — только по train AUC. Полные медианы severe/rest и их интервалы — в CSV/JSON.\n",
      "| Тип | Train rank | Ось | Риск на train | Train AUC | Test n/severe | Test AUC [95%] | Test med severe / rest |\n|---|---:|---|---|---:|---:|---|---|\n"]
    for r in rank.to_dict("records"):
        lines.append(f"| {r['type']} | {r['rank_from_train']} | {r['feature']} | {r['risk_direction_train']} | {fmt(r.get('train_auc'))} | {r['test_n']}/{r['test_severe_n']} | {fmt(r.get('test_auc'))} [{fmt(r.get('test_auc_lo'))}; {fmt(r.get('test_auc_hi'))}] | {fmt(r.get('test_severe_median'))} / {fmt(r.get('test_rest_median'))} |\n")
    lines+= ["\n## Пять фиксированных пар: траектория −24/−12/−4/0ч\n",
       "Это выбранные ранее post-outcome пары, а не случайные независимые подтверждения. Выбор строк0,1,2,4,6 зафиксирован до расчёта новых осей. Цена и потоки в каждой точке используют только данные к той точке. Нормировка пути по ATR будущего входа/стороне служит сравнению карточек, а не прогнозу, якобы выпущенному за24ч.\n"]
    for i,pair in pairs.iterrows():
        lines.append(f"\n### Пара {i+1}: {pair.loss_id.split('|')[1]}\n\nУбыток: {pair.loss_id.split('|')[-1]} → {pair.loss_net:+.4f}% базы; положительный аналог: {pair.winner_id.split('|')[-1]} → {pair.winner_net:+.4f}%.\n\n| Роль | До входа, ч | Цена | Green | Signed ход к entry, ATR | δ4h | δ24h | V4h / reference | ER24 |\n|---|---:|---:|---:|---:|---:|---:|---:|---:|\n")
        for r in paths[paths.pair==i+1].to_dict("records"):
            lines.append(f"| {r['role']} | {r['hours_to_entry']} | {fmt(r['price'],2)} | {fmt(r['green'],2)} | {fmt(r['signed_price_vs_entry_ATR'])} | {fmt(r['taker_fraction4h'])} | {fmt(r['taker_fraction24h'])} | {fmt(r['volume4h_relative30d'])} | {fmt(r['ER24'])} |\n")
        case_readings=[
          "Перед убыточным long цена за12ч выросла на1.183ATR, перед положительным —на3.022ATR. На самом входе flow почти одинаков: δ4h0.0608/0.0657 и V4h/reference1.823/1.837. Эта пара показывает, что по одному “есть покупатель и повышенный объём” отделить убыток нельзя. Более сильный предварительный рост здесь у победителя, хотя train ранжирует больший12h рост long как повышенный риск. Одну карточку нельзя превращать в обратное правило.",
          "Убыточный long пришёл после5.831ATR роста за12ч против3.799 у аналога. Основной всплеск убытка был раньше: к−4ч объём достиг8.997x reference и к входу остался6.249x; у аналога1.344x→4.271x. δ4h на входе0.0341 против0.0881. Гипотеза чтения — у убыточного случая большая часть импульса/объёма уже прошла; по этим данным нельзя установить новостную причину или объявить любой большой объём плохим.",
          "Убыточный short вошёл после снижения за12ч2.036ATR, аналог —после1.092ATR. Оба имеют преобладание агрессивных продаж на входе: δ4h−0.0778 и−0.0932; наличие продавца убыток не исключило. ER24 за последние12ч вырос у убыточного случая примерно0.208, у аналога0.037. Это конкретный пример уже ускорившегося снижения перед входом; возможное истощение является трактовкой для проверки, а не установленной причиной последующего убытка.",
          "Убыточный short под жёлтой выглядит более подтверждённым потоком: δ4h−0.0475 и volume1.505x. Победитель имел положительную δ4h+0.0512 (агрессор покупал) и лишь0.606x объёма; в последние4ч цена даже немного выросла. Эта пара против механического требования “short только при чистых продажах”: target-short имеет другую экономику, чем трендовый short. Она не доказывает обратный критерий.",
          "Для432 рост за12ч близок:2.204ATR у убытка и2.052 у аналога. Объём на входе2.595x/2.299x тоже близок. Победитель отличается более сильным последним4h движением1.954ATR против1.269 и δ4h0.1969 против0.0867. Это наблюдение пары, согласующееся с обратным переносом acceleration в текущем test, но оно не отменяет train-направление и не разрешает подобрать новый порог задним числом."
        ]
        lines.append("\nЧтение карточки: "+case_readings[i]+"\n")
    lines+= ["\n## Как читать результат\n",
       "Сильная AUC на train и слабая/обратная на test — нестабильная связь, а не повод изменить её знак задним числом. Даже совпавшее направление с CI выше0.5 остаётся исследовательским: нужна поправка на32 сравнения и новая независимая проверка. Медианы групп перекрываются; отдельная карточка не даёт гарантии.\n",
       "В этих восьми осях нет календаря новостей, OI, ликвидаций, стакана или futures aggressor. Spot volume/delta показывает исполненный поток, но не устанавливает причину всплеска или действия группы участников. Нельзя назвать объём “новостным”, а движение — “набором/ликвидацией” без соответствующего источника.\n",
       "Артефакты: preentry_features.csv, preentry_factor_ranking.csv, preentry_case_pairs.csv, preentry_case_trajectories.csv, preentry_results.json и preentry_spec.json. Исходный net сохранён; результаты исправленного ledger не подмешаны в label.\n"]
    (ROOT/"preentry_review.md").write_text("".join(lines),encoding="utf-8")
    print(json.dumps({"trades":len(d),"train":int(train.sum()),"test":int(test.sum()),"comparisons":len(rank),"prefix_checks":prefix_checked,"test_auc_over_half":int(rank.test_direction_preserved.sum())},ensure_ascii=False))

if __name__=="__main__":main()
