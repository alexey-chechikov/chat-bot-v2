"""Boundary/coverage acceptance tests for the research funding cashflows only."""
import numpy as np
import pandas as pd
import pytest
from replay_cashflows import event_net, prepare_funding

H = 3600

def data(end=24):
    t=np.arange(end+1)*H
    return {"t":t,"c":np.full(len(t),100.)}

def fund(values):
    f=pd.Series([r for _,r in values],index=[t*H for t,_ in values])
    f.attrs["supported_from_s"]=0
    return f

def event(end=16,tag="над синей",side=1,add=None):
    p={"entry_t":0,"entry":100.,"side":side,"tag":tag,"w":1.,"add_done":add is not None,"add_t":None,"add_px":None}
    if add is not None:p.update(add_t=add*H,add_px=200.)
    return {"pos":p,"side":side,"tag":tag,"t":end*H,"res":10.,"why":"regular close"}

def test_entry_payment_excluded_and_regular_exit_payment_included():
    r=event_net(event(),data(),fund([(0,.99),(8,.02),(16,-.01)]))
    assert r["funding_cost_pct"]==pytest.approx(.5)
    assert r["net_with_funding_strict"]==pytest.approx(9.5)
    assert r["funding_complete"]

def test_standing_add_receives_its_close_payment_but_old_clock_does_not():
    e=event(add=8);f=fund([(0,0),(8,.01),(16,0)])
    new=event_net(e,data(),f)
    old=event_net(e,data(),f,"old_event_clock")
    assert new["funding_cost_pct"]==pytest.approx(.75)
    assert old["funding_cost_pct"]==pytest.approx(.5)

def test_same_bar_add_and_regular_exit_funds_both_existing_legs():
    e=event(end=8,add=8);f=fund([(0,0),(8,.01)])
    r=event_net(e,data(),f)
    assert r["funding_cost_pct"]==pytest.approx(.75)
    assert r["funding_complete"]

def test_target_exit_excludes_exit_bar_close_payment():
    e=event(tag="под жёлтой");e["why"]="цель: синяя +0.5%"
    f=fund([(0,0),(8,.02),(16,.01)])
    new=event_net(e,data(),f);old=event_net(e,data(),f,"old_event_clock")
    assert new["funding_cost_pct"]==pytest.approx(2.)
    assert old["funding_cost_pct"]==pytest.approx(3.)

def test_target_at_hour_open_funding_precedes_standing_exit():
    e=event(end=9,tag="под жёлтой");e["why"]="цель: синяя +0.5%"
    r=event_net(e,data(),fund([(0,0),(8,.01)]))
    assert r["funding_cost_pct"]==pytest.approx(1.)
    assert r["funding_complete"]

def test_add_funding_at_hour_open_excluded_and_basis_bug_starts_at_entry():
    e=event(end=16,add=9);f=fund([(0,0),(8,.01),(16,0)])
    new=event_net(e,data(),f);bug=event_net(e,data(),f,"basis_bug")
    assert new["funding_cost_pct"]==pytest.approx(.5)
    assert bug["funding_cost_pct"]==pytest.approx(.75)

def test_short_receipt_is_negative_cost_and_432_uses_unit_weight():
    e=event(tag="432",side=-1);e["pos"]["w"]=123.
    r=event_net(e,data(),fund([(0,0),(8,.01),(16,0)]))
    assert r["funding_cost_pct"]==pytest.approx(-1.)
    assert r["net_with_funding_strict"]==pytest.approx(11.)

def test_missing_history_is_not_observed_zero():
    r=event_net(event(),data(),fund([(0,0),(16,0)]))
    assert not r["funding_complete"]
    assert r["missing_funding_times"]==[8*H]
    assert np.isnan(r["net_with_funding_strict"])
    assert r["benchmark_net_with_observed_funding"]==10.

def test_observed_zero_is_complete_even_without_pay_price():
    a=data();a["t"]=np.delete(a["t"],8);a["c"]=np.delete(a["c"],8)
    r=event_net(event(),a,fund([(0,0),(8,0),(16,0)]))
    assert r["funding_complete"] and r["net_with_funding_strict"]==10.

def test_pre_inception_and_bitstamp_have_benchmark_only():
    f=fund([(0,0),(8,0),(16,0)]);f.attrs.clear()
    r=event_net(event(),data(),f)
    assert not r["funding_complete"] and np.isnan(r["net_with_funding_strict"])
    assert "before_observed_funding_inception" in r["status"]
    assert r["benchmark_net_with_observed_funding"]==10.
    f.attrs.update(supported_from_s=0,venue="Bitstamp")
    r=event_net(event(),data(),f)
    assert r["status"]=="unsupported_venue"

def test_jitter_floored_to_minute_and_duplicate_not_double_charged():
    f=pd.Series([0,.01,.01,0],index=[0,8*H+.047,8*H+.023,16*H+.001]);f.attrs["supported_from_s"]=0
    r=event_net(event(),data(),f)
    assert r["funding_complete"]
    assert r["funding_cost_pct"]==pytest.approx(.5)

def test_conflicting_duplicate_rate_is_missing():
    f=fund([(0,0),(8,.01),(8,.02),(16,0)])
    r=event_net(event(),data(),f)
    assert not r["funding_complete"] and "conflicting_or_nonfinite_duplicate_rates" in r["status"]

def test_intrabar_payment_order_has_bounds_when_price_supplied():
    # Synthetic explicit price at an unusual settlement clock. Normal 8h UTC
    # settlements cannot fall strictly inside a whole-hour standing-add bar.
    a={"t":np.array([0,H,90*60,2*H,3*H]),"c":np.full(5,100.)}
    f=fund([(0,0),(1.5,.01),(3,0)])
    f.attrs.update(expected_interval_s=90*60)
    r=event_net(event(end=3,add=2),a,f)
    assert not r["funding_complete"] and r["funding_history_complete"]
    assert r["funding_cost_lower_pct"]==pytest.approx(.5)
    assert r["funding_cost_upper_pct"]==pytest.approx(.75)
    assert r["net_with_funding_lower_pct"]==pytest.approx(9.25)
    assert r["net_with_funding_upper_pct"]==pytest.approx(9.5)
    assert np.isnan(r["net_with_funding_strict"])

def test_nonzero_payment_without_same_clock_price_is_unknown():
    a=data();a["t"]=np.delete(a["t"],8);a["c"]=np.delete(a["c"],8)
    r=event_net(event(),a,fund([(0,0),(8,.01),(16,0)]))
    assert not r["funding_complete"] and r["missing_proxy_price_times"]==[8*H]
    assert np.isnan(r["net_with_funding_strict"])

@pytest.mark.parametrize("tag",["над синей","под жёлтой","432"])
def test_basis_bug_only_changes_add_and_no_other_trade_clocks(tag):
    e=event(tag=tag)
    if tag=="под жёлтой":e["why"]="цель: синяя +0.5%"
    f=fund([(0,0),(8,.01),(16,.02)])
    new=event_net(e,data(),f)
    bug=event_net(e,data(),f,"basis_bug")
    assert new["funding_cost_pct"]==bug["funding_cost_pct"]
    assert new["net_with_funding_strict"]==bug["net_with_funding_strict"]

def test_prepared_funding_is_immutable_and_equivalent_for_all_modes():
    f=fund([(0,0),(8,.01),(16,.02)])
    prepared=prepare_funding(f,attrs={"expected_interval_s":8*H})
    f.iloc[1]=.99
    f.attrs["supported_from_s"]=100000
    assert prepared.rates[8*H]==.01
    assert prepared.attrs["supported_from_s"]==0
    with pytest.raises(TypeError):prepared.rates[8*H]=.33
    with pytest.raises(TypeError):prepared.attrs["supported_from_s"]=23
    original=fund([(0,0),(8,.01),(16,.02)])
    for mode in ["corrected","old_event_clock","basis_bug"]:
        x=event_net(event(add=8),data(),original,mode)
        y=event_net(event(add=8),data(),prepared,mode)
        assert x==y

def test_funding_record_dict_top_level_interval_controls_coverage():
    f={"times":[0,2*H],"rates_pct":[0,0],"expected_interval_s":H,"attrs":{"supported_from_s":0}}
    r=event_net(event(end=2),data(),prepare_funding(f))
    assert not r["funding_complete"]
    assert r["missing_funding_times"]==[H]
