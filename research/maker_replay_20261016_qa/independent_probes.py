"""In-memory risk-guard counterexamples; no market/account/process IO."""
from pathlib import Path
import hashlib
import json
import sys

ROOT=Path(__file__).resolve().parent
SOURCE=ROOT.parent/'maker_replay_20261016'
sys.path.insert(0,str(SOURCE))
from replay import Engine


def frame(seq,t,raw=None):
    return {'seq':seq,'ms':t,'raw':raw or {'event':'noop'}}


def initialized():
    e=Engine(10000,delay_ms=100,queue_factor=0,min_levels=1,quote_usd=100)
    e.frame(frame(1,0,{'e':'depthSnapshot','s':'ETHUSDT','U':1,'u':1,
      'b':[['100','10']],'a':[['100.01','10']]}))
    return e


def fill_frame(seq,t,qty=1):
    return frame(seq,t,{'e':'trade','s':'ETHUSDT','d':[
      {'t':f'invented-{seq}','T':t-50,'p':'100','q':str(qty),'m':True}]})


def main():
    stale=initialized()
    stale.frame(fill_frame(2,200))
    stale.frame(frame(3,1501))
    first=initialized()
    first.frame(frame(2,150,{'e':'depth','s':'ETHUSDT','U':1,'u':2,
      'b':[['100','0'],['99','10']],'a':[['100.01','0'],['99.01','10']]}))
    first.frame(fill_frame(3,200))
    late=initialized()
    late.frame(frame(2,150,{'e':'depth','s':'ETHUSDT','U':1,'u':2,
      'b':[['100','0'],['99','10']],'a':[['100.01','0'],['99.01','10']]}))
    late.frame(fill_frame(3,200,.4))
    late.frame(fill_frame(4,250,.3))
    before_cancel=late.position
    late.frame(fill_frame(5,350,.9))
    late.frame(frame(6,450))
    result={'source_sha256':hashlib.sha256((SOURCE/'replay.py').read_bytes()).hexdigest(),
      'scope':'invented in-memory fixtures; not evidence any real episode hit this condition',
      'stale_held_position':{'now':stale.now,'position':stale.position,'fresh':stale.fresh(),
        'liquidating':stale.liquidating,'risk_triggers':stale.episode['risk_triggers'],
        'order_kind':stale.order.kind if stale.order else None},
      'first_fill_with_current_bid_below_stop':{'now':first.now,'position':first.position,
        'fresh':first.fresh(),'bid':max(first.books['b']),'stop':first.entry_price*(1-25/10000),
        'liquidating':first.liquidating,'risk_triggers':first.episode['risk_triggers'],
        'order_kind':first.order.kind if first.order else None},
      'stop_cancel_late_fill_then_single_reduce_exit':{'inventory_before_cancel_ack':before_cancel,
        'final_position':late.position,'buy_qty':sum(r['qty'] for r in late.fills if r['side']=='buy'),
        'sell_qty':sum(r['qty'] for r in late.fills if r['side']=='sell'),
        'exit_fills':sum(r['side']=='sell' for r in late.fills),
        'net_scenario':late.episodes[0]['net_scenario'],
        'tp_submitted':any(r['event']=='submit' and r.get('kind')=='exit' for r in late.ledger)}}
    assert stale.position==1 and not stale.fresh() and stale.liquidating
    assert first.position==1 and first.fresh() and max(first.books['b'])<first.entry_price*(1-25/10000) and first.liquidating
    assert not any(r['event']=='submit' and r.get('kind')=='exit' for r in first.ledger)
    assert abs(before_cancel-.7)<1e-10 and late.position==0
    assert abs(result['stop_cancel_late_fill_then_single_reduce_exit']['buy_qty']-.7)<1e-10
    assert abs(result['stop_cancel_late_fill_then_single_reduce_exit']['sell_qty']-.7)<1e-10
    assert result['stop_cancel_late_fill_then_single_reduce_exit']['exit_fills']==1
    (ROOT/'independent_probe_results.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result))


if __name__=='__main__':
    main()
