"""Targeted sensitivity of existing funding7d quintile sizing rule; NO fitting/sweep.

All listed views are accounting/population controls, not competing optimized policies.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
from replay_paths import LAB_ROOT, ORIGINAL_SOURCE, ensure_original_sources, auxiliary_file

ROOT=LAB_ROOT
OLD=ORIGINAL_SOURCE
FEATURE="фандинг 7д, %"
MULT=np.array([.5,.75,1.,1.25,1.5])
NPERM=999
NBOOT=9999

def get_table(path):
    d=pd.read_csv(path,sep=";",decimal=",")
    d=d[(d["ряд"]=="Binance")&(d["тип"]=="шорт под синей")].copy()
    d["trade_id"]=d["ряд"]+"|"+d["тип"]+"|"+d["вход UTC"]
    return d.sort_values("вход UTC").set_index("trade_id",verify_integrity=True)

def metrics(test,y,m,q,rng):
    y=np.asarray(y,float)
    assert np.isfinite(y).all()
    actual=float((y*m).sum())
    base=float(y.sum())
    delta=y*(m-1)
    null=np.array([(y*rng.permutation(m)).sum() for _ in range(NPERM)])
    p=float((1+(null>=actual).sum())/(NPERM+1))
    shifts=np.array([(y*np.roll(m,k)).sum() for k in range(len(m))])
    month=pd.to_datetime(test["вход UTC"]).dt.to_period("M")
    months=pd.period_range(month.min(),month.max(),freq="M")
    sums=pd.Series(delta,index=month.to_numpy()).groupby(level=0).sum().reindex(months,fill_value=0).to_numpy()
    brng=np.random.default_rng(911091)
    bs=sums[brng.integers(0,len(sums),size=(NBOOT,len(sums)))].sum(1)
    best_contrib=np.argsort(delta)
    best_outcome=np.argsort(y)
    return dict(n=len(y),baseline=base,sized=actual,gain=float(delta.sum()),mean_multiplier=float(m.mean()),
        constant_same_mean_multiplier_net=float(base*m.mean()),allocation_over_constant_same_mean=float(actual-base*m.mean()),
        rough_mean_multiplier_normalized_net=float(actual/m.mean()),rough_mean_multiplier_normalized_gain=float(actual/m.mean()-base),
        iid_perm_p=p,illustrative_bonferroni_3_neighbors=min(1.,3*p),
        circular_shift_p=float((shifts>=actual).mean()),calendar_months=len(months),bootstrap_repeats=NBOOT,
        monthly_cluster_gain_ci95=np.quantile(bs,[.025,.975]).tolist(),
        gain_delete_best_delta1=float(delta.sum()-delta[best_contrib[-1:]].sum()),
        gain_delete_best_delta3=float(delta.sum()-delta[best_contrib[-3:]].sum()),
        gain_delete_top_raw_outcome1=float(delta.sum()-delta[best_outcome[-1:]].sum()),
        gain_delete_top_raw_outcome3=float(delta.sum()-delta[best_outcome[-3:]].sum()),
        quintile_counts=np.bincount(q,minlength=5).tolist(),
        quintile_pnl=[float(y[q==k].sum()) for k in range(5)],
        quintile_mean_pnl=[float(y[q==k].mean()) if (q==k).any() else None for k in range(5)],
        largest_delta_cases=[dict(trade_id=str(test.index[i]),outcome=float(y[i]),multiplier=float(m[i]),gain_contribution=float(delta[i])) for i in best_contrib[-3:][::-1]])

def evaluate(name,train,test,cash):
    assert train[FEATURE].notna().all() and test[FEATURE].notna().all()
    edges=np.quantile(train[FEATURE],[.2,.4,.6,.8])
    q=np.searchsorted(edges,test[FEATURE].to_numpy(float))
    m=MULT[q]
    c=cash.reindex(test.index)
    assert c.funding_complete.all() and c.corrected_net_funding_strict.notna().all()
    rng=np.random.default_rng(91109)
    no=metrics(test,c.corrected_net_no_funding.to_numpy(),m,q,rng)
    funded=metrics(test,c.corrected_net_funding_strict.to_numpy(),m,q,rng)
    rows=pd.DataFrame(dict(view=name,trade_id=test.index,entry_utc=test["вход UTC"].to_numpy(),feature=test[FEATURE].to_numpy(),
        quintile=q+1,multiplier=m,no_funding=c.corrected_net_no_funding.to_numpy(),strict_funded=c.corrected_net_funding_strict.to_numpy()))
    rows["no_funding_gain_contribution"]=rows.no_funding*(rows.multiplier-1)
    rows["funded_gain_contribution"]=rows.strict_funded*(rows.multiplier-1)
    return dict(view=name,n_train=len(train),n_test=len(test),train_start=train["вход UTC"].iloc[0],train_last=train["вход UTC"].iloc[-1],
        test_start=test["вход UTC"].iloc[0],test_end=test["вход UTC"].iloc[-1],
        thresholds=edges.tolist(),train_ids=train.index.tolist(),test_ids=test.index.tolist(),
        strict_n=len(test),no_funding=no,strict_funded=funded),rows

def main():
    ensure_original_sources()
    protected=[auxiliary_file("audit_bad_trades_predictions.csv"),ROOT/"progress_24h_predictions.csv"]
    protected_before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in protected}
    old=get_table(OLD/"research/chart_walk_20261105/out/trade_table_btc.csv")
    new=get_table(ROOT/"results/trade_table_btc_corrected.csv")
    cash=pd.read_csv(ROOT/"results/trade_repair_all.csv").set_index("trade_id",verify_integrity=True)
    old_av=old[old[FEATURE].notna()]
    new_av=new[new[FEATURE].notna()]
    oh=len(old_av)//2;nh=len(new_av)//2
    otr,ote=old_av.iloc[:oh],old_av.iloc[oh:]
    ntr,nte=new_av.iloc[:nh],new_av.iloc[nh:]
    valid_ids=set(new_av.index)
    calendar_old_train=old_av[old_av["вход UTC"]<"2023-01-01"]
    calendar_old_test=old_av[old_av["вход UTC"]>="2023-01-01"]
    calendar_new_train=new_av[new_av["вход UTC"]<"2023-01-01"]
    calendar_new_test=new_av[new_av["вход UTC"]>="2023-01-01"]
    views=[
        ("original_half_original_population",otr,ote),
        ("repaired_available_half",ntr,nte),
        ("same_repaired_half_IDs_old_values",old.loc[ntr.index],old.loc[nte.index]),
        ("original_time_split_repaired_available_train",new.loc[[i for i in otr.index if i in valid_ids]],new.loc[[i for i in ote.index if i in valid_ids]]),
        ("fixed2023_original_train_population",calendar_old_train,calendar_old_test),
        ("fixed2023_repaired_available_population",calendar_new_train,calendar_new_test),
        ("same_fixed2023_IDs_old_values",old.loc[calendar_new_train.index],old.loc[calendar_new_test.index]),
    ]
    results=[];assignment=[]
    for name,tr,te in views:
        out,rows=evaluate(name,tr,te,cash)
        results.append(out);assignment.append(rows)
    primary=next(r for r in results if r['view']=='repaired_available_half')
    assert primary['n_train']==90 and primary['n_test']==91
    assert abs(primary['no_funding']['sized']-30.308599063)<1e-5
    assert abs(primary['strict_funded']['sized']-32.190829108)<1e-5
    excluded=old_av.loc[[i for i in old_av.index if i not in valid_ids]]
    moved=[i for i in ote.index if i in set(ntr.index)]
    old_test_removed=[i for i in ote.index if i not in set(nte.index)]
    proof=dict(old_available=len(old_av),new_available=len(new_av),availability_removed=len(excluded),
        removed_old_train=int(excluded.index.isin(otr.index).sum()),removed_old_test=int(excluded.index.isin(ote.index).sum()),
        original_test_moved_to_repaired_train_n=len(moved),original_test_moved_to_repaired_train=moved,
        removed_from_original_test_n=len(old_test_removed),
        max_old_new_feature_difference_on_common=float((old.loc[new_av.index,FEATURE]-new_av[FEATURE]).abs().max()),
        old_new_feature_difference_exceeds_4decimal_rounding_n=int(((old.loc[new_av.index,FEATURE]-new_av[FEATURE]).abs()>.00005001).sum()),
        original_fakezero_n=int((excluded[FEATURE]==0).sum()))
    pop=old[["вход UTC",FEATURE]].rename(columns={FEATURE:"old_feature"}).join(new[[FEATURE]].rename(columns={FEATURE:"new_feature"}))
    pop['original_split']=np.where(pop.index.isin(otr.index),'train','test')
    pop['repaired_split']=np.where(pop.index.isin(ntr.index),'train',np.where(pop.index.isin(nte.index),'test','unavailable'))
    pop.reset_index().to_csv(ROOT/"funding_candidate_population.csv",index=False,encoding="utf-8-sig")
    pd.concat(assignment,ignore_index=True).to_csv(ROOT/"funding_candidate_assignments.csv",index=False,encoding="utf-8-sig")
    flat=[]
    for r in results:
        for target in ['no_funding','strict_funded']:
            flat.append(dict(view=r['view'],target=target,n_train=r['n_train'],test_start=r['test_start'],**r[target]))
    df=pd.DataFrame(flat)
    df.to_csv(ROOT/"funding_candidate_summary.csv",index=False,encoding="utf-8-sig")
    paths=[OLD/"research/chart_walk_20261105/out/trade_table_btc.csv",ROOT/"results/trade_table_btc_corrected.csv",ROOT/"results/trade_repair_all.csv"]
    protected_after={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in protected}
    assert protected_before==protected_after
    controls={}
    byname={x['view']:x for x in results}
    for left,right in [('repaired_available_half','same_repaired_half_IDs_old_values'),('fixed2023_repaired_available_population','same_fixed2023_IDs_old_values')]:
        x=pd.concat(assignment,ignore_index=True)
        one=x[x.view==left].set_index('trade_id')
        two=x[x.view==right].set_index('trade_id')
        assert one.index.equals(two.index)
        controls[left]=dict(same_test_ids=True,changed_quintile_assignments=int((one.quintile!=two.quintile).sum()),
            gain_difference_no_fund=byname[left]['no_funding']['gain']-byname[right]['no_funding']['gain'],
            gain_difference_funded=byname[left]['strict_funded']['gain']-byname[right]['strict_funded']['gain'])
    report=dict(feature=FEATURE,rule="train quintiles .2/.4/.6/.8; multipliers .5/.75/1/1.25/1.5, higher funding -> larger short",input_hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
        no_new_model=True,no_threshold_or_policy_search=True,population=proof,results=results,
        same_ID_controls=controls,protected_scores_before=protected_before,protected_scores_after=protected_after,
        limits=["Accounting/population sensitivities are all reported; none selected as new winning policy.",
                "Corrected y/cash used for all views to isolate population and x precision; original CSV rounded net differs slightly.",
                "Fixed2023 comparison uses calendar split, with both test87 sets identical; original147 vs repaired94 train IDs differ.",
                "Same-index controls use identical train/test IDs and corrected outcomes; only old/new x differ (including window/source/clock changes and rounding).",
                "Iid permutation assumes exchangeability; circular shift assumes temporal stationarity; monthly clusters do not prove either.",
                "Bonferroni*3 is illustrative for three named neighbors only, not adjustment for all past/future visible searches.",
                "Prior history has repeatedly been examined, and 26 old test trades enter new train after availability repair; this is not independent confirmation.",
                "Mean-multiplier normalization is an ex post exposure sensitivity, not matching actual holding-time/dollar exposure or risk.",
                "Strict funding uses same-clock spot proxy and declared event-order convention, not actual mark prices."])
    (ROOT/"funding_candidate_review.json").write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
    text=[]
    text.append("# Funding7д для short под синей: точечная проверка положительного кандидата\n")
    text.append("Проверено прежнее правило: пять корзин по границам20/40/60/80% обучающих значений funding7д, множители.5/.75/1/1.25/1.5. Новых признаков, моделей, оптимизации alpha, горизонта или порога нет. Ниже все запрошенные population/accounting controls, а не выбор победителя среди разных настроек. Исходные risk/progress forecasts не перефитывались и не менялись; их SHA до/после совпадают.\n")
    text.append("## Что действительно изменилось\n")
    text.append("Из234 shortblue с якобы доступным funding7д осталось181 с реально наблюдаемой зрелой историей.53 старых нуля были отсутствием истории; все53 находились в прежнем train. При правиле 'первая половина/вторая половина' граница test сдвинулась с04.05.2022 на10.12.2022:26 сделок прежнего test теперь попали в train. Поэтому117/117 и90/91 — **разные обучение и проверка**. Переход от p=.239 к.020 не является новым независимым успехом на прежнем неизменном test.\n")
    text.append("На **тех же90/91 ID** старые и новые значения funding дают те же корзины и те же денежные результаты. То же верно для matched94/87 ID календарного контроля. Максимальная разница значений на общих датах.049285 п.п., так что изменения x не сводятся к округлению; однако именно в этих двух фиксированных правилах они не изменили ни одного назначения корзины. Главная причина изменения headline здесь — состав/граница выборки и обучающие квантильные границы.\n")
    text.append("Все представленные денежные цели взяты из corrected cash таблицы: no-funding — точный исправленный engine; funded — `corrected_net_funding_strict`. Во всех test-выборках покрытие полное. Старый baseline53.2224 отличается от перепроверенного53.2220 только точностью опубликованной CSV; старую ошибочную funded-цель из basis_bug в новые проверки не подмешивали. Funding всё ещё использует объявленную same-clock spot proxy, не actual mark.\n")
    text.append("## Денежные результаты и чувствительность\n")
    labels={'original_half_original_population':'Исходная population/половина','repaired_available_half':'Исправленная availability/половина','same_repaired_half_IDs_old_values':'Те же corrected-half IDs, старые x','original_time_split_repaired_available_train':'Старая временная граница, valid train','fixed2023_original_train_population':'Фиксированный2023, старый train','fixed2023_repaired_available_population':'Фиксированный2023, valid train','same_fixed2023_IDs_old_values':'Те же fixed2023 IDs, старые x'}
    text.append("| Контроль | train/test | Цель | База | С размером | Δ | iid p | shift p | Месячный95%CI Δ |\n|---|---:|---|---:|---:|---:|---:|---:|---|\n"+"\n".join(f"| {labels[r['view']]} | {r['n_train']}/{r['n_test']} | {target} | {r[target]['baseline']:.4f} | {r[target]['sized']:.4f} | {r[target]['gain']:+.4f} | {r[target]['iid_perm_p']:.3f} | {r[target]['circular_shift_p']:.4f} | [{r[target]['monthly_cluster_gain_ci95'][0]:+.2f}; {r[target]['monthly_cluster_gain_ci95'][1]:+.2f}] |" for r in results for target in ['no_funding','strict_funded'])+"\n")
    text.append("Исправленная половина90/91: no-funding21.4144→30.3086 (+8.8942), funded23.3673→32.1908 (+8.8235). iid999 перестановок даёт.020/.014; круговые сдвиги4/91=.04396. Месячные интервалы обеих целей пересекают0: [−1.44;+20.31] и[−1.55;+20.31]. Положительный iid результат не превращается в устойчивое к любому временному resampling подтверждение.\n")
    text.append("Календарный контроль<2023 / >=2023 сохраняет один test из87 сделок. Со зрелым train94 funded24.6584→35.7296 (+11.0712), iid.010, shift1/87=.01149, месячныйCI[+2.23;+21.78]. Это более устойчивый положительный исследовательский результат, который заслуживает сохранения. Но этот календарь и сама история уже многократно просматривались; нельзя выдавать его за второе независимое подтверждение или выбирать его только потому, что CI красивее.\n")
    text.append("Контроль прежней временной границы04.05.2022 со зрелым train64 и теми же117 test-датами даёт funded55.0948→50.1561 (Δ−4.9387). Здесь среднийmult лишь.7564: постоянный такой же средний размер дал бы41.6743, а после грубой нормировки50.1561/.7564 получается66.3081. Поэтому это отрицательная чувствительность **абсолютной суммы** правила при меньшем среднем размере, не доказательство отсутствия полезной аллокации; её iid p=.094 также слабее. Смена состава обучающего периода и среды2022 существенна. Все строки оставлены в отчёте.\n")
    text.append("## Размер, экспозиция и отдельные сделки\n")
    selected=[r for r in results if r['view'] in ['repaired_available_half','fixed2023_repaired_available_population']]
    text.append("| Контроль | Цель | Средний mult | Net/среднийmult | База | Δ без лучшего вклада | Δ без3 лучших вкладов |\n|---|---|---:|---:|---:|---:|---:|\n"+"\n".join(f"| {labels[r['view']]} | {target} | {r[target]['mean_multiplier']:.4f} | {r[target]['rough_mean_multiplier_normalized_net']:.4f} | {r[target]['baseline']:.4f} | {r[target]['gain_delete_best_delta1']:+.4f} | {r[target]['gain_delete_best_delta3']:+.4f} |" for r in selected for target in ['no_funding','strict_funded'])+"\n")
    text.append("Средний множитель.8819 в corrected-half и.8966 в fixed2023: прирост не объясняется простым ростом среднего плеча. У funded-half постоянный такой же средний множитель дал бы20.6069, а правило32.1908; условное деление результата на.8819 даёт36.5030 против базы23.3673. Но это ex-post контроль среднего множителя сделки: он не выравнивает долларовую экспозицию во времени, волатильность, DD и исходный volatility size. Нормированные множители также могут выйти за исходный cap1.5, поэтому это не новая исполнимая настройка.\n")
    text.append("Лучшие вклады означают `(mult−1)*net`, а не просто крупнейшие прибыльные сделки. В funded-half после удаления лучшего/трёх лучших вкладов остаётся+4.9182/+2.5037; в fixed2023 +7.1659/+4.7514. Полные дополнительные проверки удаления крупнейших raw-победителей сохранены вJSON. Положительный эффект не создан одной единственной сделкой, хотя от хвостов зависит существенно.\n")
    text.append("| Контроль | Корзина | n | Funded PnL | Средний funded на сделку |\n|---|---:|---:|---:|---:|\n"+"\n".join(f"| {labels[r['view']]} | {k+1} | {r['strict_funded']['quintile_counts'][k]} | {r['strict_funded']['quintile_pnl'][k]:+.4f} | {r['strict_funded']['quintile_mean_pnl'][k]:+.4f} |" for r in selected for k in range(5))+"\n")
    text.append("На corrected-half корзины11/30/42/7/1. Максимальная корзина funding представлена одной сделкой; четвёртая семью, и её прибыль сильно зависит от short16.08.2023. Нельзя утверждать доказанную широкую монотонность или надёжность extreme-funding зоны.\n")
    text.append("Крупнейший funded-вклад: short16.08.2023, базовый net15.6211, multiplier1.25, добавка+3.9053. Это та же трендовая сделка, которую24ч Ridge overlay закрыл слишком рано и потерял14.1439 funded. Складывать два исследовательских улучшения по отдельным таблицам нельзя: их решения могут уничтожать пользу друг друга. Совместный эффект здесь не симулировался.\n")
    text.append("## Поправки на выбор и пределы вывода\n")
    text.append("Для строго ограниченной семьи из трёх названных соседей (basis7d, point basis, funding7d) иллюстративный Bonferroni×3 даёт corrected-half p=.060 no-funding и.042 funded; fixed2023:.012 и.030. Это корректная арифметика при валидных маргинальных p, **не общая search-adjusted вероятность**. Она не учитывает прежние189 признаков, цели/типологии, M/M2, выбор соседей, смену календаря, повторные просмотры и сам факт, что положительный funding стал поводом для этой sensitivity. Блочная зависимость ещё ограничивает трактовку iid p. По круговым сдвигам half×3=.1319, fixed2023×3=.0345; эти модели шума нельзя выбирать по удобному порогу.\n")
    text.append("999 перестановок используют фиксированный seed91109 и прежний порядок no-funding→funded; это воспроизведение p из repeated_findings. CI —9999 ресэмплирований календарных месяцев входа, включая нулевые месяцы:48 месяцев half,47 fixed2023. Долгие позиции/режимы могут связывать соседние месяцы; bootstrap не равен полноценной MTM-проверке и не устраняет selection bias. У всех same-ID контролей идентичные outcomes/корзины — это ноль новых независимых наблюдений.\n")
    text.append("**Вывод:** найден полезный положительный исследовательский кандидат для размера shortblue; отбрасывать его как отсутствие всякого сигнала неправильно. Но исправление данных не доказало живое преимущество: менялись population и split, календарная устойчивость неполна, крайние корзины малы, полная поправка на прежний поиск не выполнена. Следующее действие — один зафиксированный shadow-протокол с выбранной заранее границей обучения/порогами, полным cashflow и неизменным prospective периодом; не ещё один поиск лучшего разреза на этой истории. Текущая sensitivity ничего не внедряет и не создаёт сборщиков/расписаний.\n")
    text.append("Файлы: funding_candidate_review.py/.md/.json; funding_candidate_summary.csv; funding_candidate_assignments.csv (каждая сделка/корзина/множитель/вклад); funding_candidate_population.csv (старый и новый split/availability). Полные SHA исходной и исправленной таблиц/cashflow содержатся вJSON.\n")
    (ROOT/"funding_candidate_review.md").write_text('\n'.join(text),encoding='utf-8')
    print(json.dumps(proof,ensure_ascii=False,indent=2))
    print(df[['view','target','n_train','n','baseline','sized','gain','mean_multiplier','iid_perm_p','circular_shift_p','monthly_cluster_gain_ci95','gain_delete_best_delta1','gain_delete_best_delta3','quintile_counts']].to_string(index=False))

if __name__=="__main__":main()
