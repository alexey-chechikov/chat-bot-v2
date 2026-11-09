"""Funding evaluation of frozen +24h scores/actions. NO MODEL FIT OR RETUNING."""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
import pickle
import numpy as np
import pandas as pd
from replay_cashflows import event_net, prepare_funding

ROOT=Path(__file__).resolve().parent
CUT=int(pd.Timestamp("2023-01-01",tz="UTC").timestamp())

def utc(ts):return pd.Timestamp(int(ts),unit="s",tz="UTC").strftime("%Y-%m-%d %H:%M")

def summarize(d,name):
    strict=d.final_funding_complete&d.overlay_funding_complete
    q=d[strict]
    return dict(group=name,n=len(d),strict_complete_n=int(strict.sum()),unknown_n=int((~strict).sum()),
        action_n=int(d.frozen_exit_action.sum()),
        baseline_no_funding=float(q.final_no_funding.sum()),overlay_no_funding=float(q.overlay_no_funding.sum()),
        delta_no_funding=float((q.overlay_no_funding-q.final_no_funding).sum()),
        baseline_corrected_funded=float(q.final_funded_strict.sum()),overlay_corrected_funded=float(q.overlay_funded_strict.sum()),
        delta_corrected_funded=float((q.overlay_funded_strict-q.final_funded_strict).sum()),
        change_in_delta_due_funding=float(((q.overlay_funded_strict-q.final_funded_strict)-(q.overlay_no_funding-q.final_no_funding)).sum()),
        baseline_funding_cost=float(q.final_funding_cost.sum()),overlay_funding_cost=float(q.overlay_funding_cost.sum()))

def main():
    pp=ROOT/"progress_24h_predictions.csv"
    original_bytes=pp.read_bytes()
    original_hash=hashlib.sha256(original_bytes).hexdigest()
    pred=pd.read_csv(pp)
    pred=pred[(pred.venue=="Binance")&(pred.entry_t>=CUT)].copy()
    assert len(pred)==195 and int(pred.exit_overlay.sum())==7
    assert (pred.prediction_scope=="saved_OOS_fixed_historical_split").all()
    pred=pred.set_index("trade_id",verify_integrity=True)
    cache=pickle.load((ROOT/"replay_cache.pkl").open("rb"))
    v=cache["Binance"]
    a=v["a"]
    fund=prepare_funding(v["fund"],attrs={"venue":"Binance","expected_interval_s":28800,"supported_from_s":1568102400})
    rows=[]
    for (t0,tag,side),event in v["trades"].items():
        if t0<CUT:continue
        typ=("лонг " if side==1 else "шорт ")+tag
        tid="Binance|"+typ+"|"+utc(t0)
        final=event_net(event,a,fund,mode="corrected")
        lm=tid in pred.index
        selected=bool(pred.loc[tid,"exit_overlay"]) if lm else False
        now=None
        if lm:
            lm_t=int(pred.loc[tid,"landmark_t"])
            i=int(np.searchsorted(a["t"],lm_t))
            assert a["t"][i]==lm_t
            hypothetical=copy.deepcopy(event)
            hypothetical.update(t=lm_t,i=i,px=float(a["c"][i]),res=float(pred.loc[tid,"close_now_net"]),why="landmark_close")
            pos=hypothetical["pos"]
            if pos.get("add_t") is not None and int(pos["add_t"])>lm_t:
                pos.update(add_done=False,add_t=None,add_px=None)
            now=event_net(hypothetical,a,fund,mode="corrected")
        alt=now if selected else final
        rows.append(dict(trade_id=tid,type=typ,entry_time=utc(t0),exit_time=utc(event["t"]),
            reached24h=lm,frozen_exit_action=selected,
            original_prediction_nofund=float(pred.loc[tid,"predicted_future_increment"]) if lm else None,
            final_no_funding=final["net_no_funding"],overlay_no_funding=alt["net_no_funding"],
            final_funded_strict=final["net_with_funding_strict"],overlay_funded_strict=alt["net_with_funding_strict"],
            final_funding_cost=final["funding_cost_pct"],overlay_funding_cost=alt["funding_cost_pct"],
            final_funding_complete=final["funding_complete"],overlay_funding_complete=alt["funding_complete"],
            final_funding_status=final["status"],overlay_funding_status=alt["status"],
            close24_funded_strict=now["net_with_funding_strict"] if lm else None,
            close24_funding_complete=now["funding_complete"] if lm else None,
            close24_funding_status=now["status"] if lm else None,
            future_incremental_net_funded=(final["net_with_funding_strict"]-now["net_with_funding_strict"]) if lm else None,
            funding_price_method=final["funding_price_method"]))
    d=pd.DataFrame(rows)
    assert len(d)==288 and int(d.reached24h.sum())==195 and int(d.frozen_exit_action.sum())==7
    assert d.final_funding_complete.all() and d.overlay_funding_complete.all()
    assert d.loc[d.reached24h,"close24_funding_complete"].all()
    d["delta_no_funding"]=d.overlay_no_funding-d.final_no_funding
    d["delta_corrected_funded"]=d.overlay_funded_strict-d.final_funded_strict
    d["delta_change_due_funding"]=d.delta_corrected_funded-d.delta_no_funding
    d.to_csv(ROOT/"progress_funded_evaluation_trades.csv",index=False,encoding="utf-8-sig")
    d[d.frozen_exit_action].to_csv(ROOT/"progress_funded_evaluation_actions.csv",index=False,encoding="utf-8-sig")
    result=[]
    for name,z in [("all288_test2023_plus",d),("reached195_landmark24h",d[d.reached24h]),("seven_frozen_exit_actions",d[d.frozen_exit_action])]:
        result.append(summarize(z,name))
        for typ,q in z.groupby("type",sort=False):result.append(summarize(q,name+"|"+typ))
    summary=pd.DataFrame(result)
    summary.to_csv(ROOT/"progress_funded_evaluation_summary.csv",index=False,encoding="utf-8-sig")
    assert pp.read_bytes()==original_bytes
    report=dict(method="Evaluate same frozen unfunded model/actions with corrected funding; no new fit, feature, threshold or selection.",
        prediction_file_sha256_before=original_hash,prediction_file_sha256_after=hashlib.sha256(pp.read_bytes()).hexdigest(),
        cache_sha256=hashlib.sha256((ROOT/"replay_cache.pkl").read_bytes()).hexdigest(),
        cashflow_code_sha256=hashlib.sha256((ROOT/"replay_cashflows.py").read_bytes()).hexdigest(),
        mode="corrected",n_all=288,n_reached=195,n_actions=7,
        funding_complete_all=True,close_now_funding_complete_reached=True,
        funding_price_method="same_clock_spot_hour_close_proxy_not_actual_mark",
        limits=["Funding re-evaluation of old unfunded policy, NOT a model trained on funded labels.",
                "Same-close execution and original strategy/overlay state-machine limitations still apply.",
                "Strict completeness verifies source/time/order under declared convention, not actual mark-price execution."],
        summary=result)
    (ROOT/"progress_funded_evaluation_results.json").write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
    lines=["## Дополнение: funding для тех же замороженных действий\n",
        "Нового обучения не было. Взяты ровно те же195 OOS scores и7 действий исходной no-funding модели; SHA256 файла прогнозов до/после совпадает: `"+original_hash+"`. Для каждой альтернативы close24 заново построены действующие ноги, будущий добор удалён, payout clock и funding рассчитаны `replay_cashflows.event_net(mode='corrected')`.\n",
        "| Набор | n / strict complete | База без funding | Overlay без funding | Δ без funding | База funded | Overlay funded | Δ funded | ИзменениеΔ из-за funding |\n|---|---:|---:|---:|---:|---:|---:|---:|---:|\n"]
    lines.append("\n".join(f"| {r.group} | {r.n}/{r.strict_complete_n} | {r.baseline_no_funding:.4f} | {r.overlay_no_funding:.4f} | {r.delta_no_funding:+.4f} | {r.baseline_corrected_funded:.4f} | {r.overlay_corrected_funded:.4f} | {r.delta_corrected_funded:+.4f} | {r.change_in_delta_due_funding:+.4f} |" for r in summary[~summary.group.str.contains('|',regex=False)].itertuples()))
    lines.append("\nВсе288 финальных исходов и все195 альтернатив close24 имеют полное покрытие по объявленной spot-proxy convention; неизвестные значения не превращались в нули. Это исправленная денежная оценка **той же политики**, а не обучение на funded target. Spot-price proxy при funding всё ещё не actual mark. Возможность новых входов после раннего выхода этим one-off overlay не моделируется.\n")
    paragraph="\n".join(lines)
    (ROOT/"progress_funded_evaluation.md").write_text(paragraph,encoding="utf-8")
    target=ROOT/"progress_review.md"
    content=target.read_text(encoding="utf-8")
    marker="## Дополнение: funding для тех же замороженных действий"
    content=content.split(marker)[0].rstrip()+"\n\n"+paragraph
    target.write_text(content,encoding="utf-8")
    print(summary.to_string(index=False))
    print(d[d.frozen_exit_action][["trade_id","delta_no_funding","delta_corrected_funded","delta_change_due_funding"]].to_string(index=False))

if __name__=="__main__":main()
