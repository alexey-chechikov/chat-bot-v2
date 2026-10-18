import unittest
import numpy as np
import pandas as pd
from run_replay import replay_trade, Scenario, quantity, MINUTE


def candles(overrides=None, missing=None):
    values=[]
    for i in range(121):
        row={'ts':i*MINUTE,'open':100.,'high':100.1,'low':99.9,'close':100.,'volume':1.}
        row.update((overrides or {}).get(i,{}))
        if i!=missing:
            values.append(row)
    return pd.DataFrame(values)


class ReplayTests(unittest.TestCase):
    def test_expiry_open_precedes_high_low(self):
        d=candles({120:{'open':100.5,'high':110.,'low':80.}})
        r,_=replay_trade(d,0,1,Scenario('flat',flat_cost=.0004))
        self.assertEqual(r['reason'],'time')
        self.assertEqual(r['exit_time'],120*MINUTE)
        self.assertEqual(r['exit_raw'],100.5)
        self.assertAlmostEqual(r['net_usd'],4.6)

    def test_deadline_gap_target_long_is_capped(self):
        d=candles({120:{'open':103.,'high':104.,'low':102.}})
        r,_=replay_trade(d,0,1,Scenario('flat'))
        self.assertEqual(r['reason'],'target')
        self.assertEqual(r['exit_time'],120*MINUTE)
        self.assertAlmostEqual(r['exit_raw'],101.8)
        self.assertAlmostEqual(r['net_usd'],18.)

    def test_deadline_gap_target_short_is_capped(self):
        d=candles({120:{'open':97.,'high':98.,'low':96.}})
        r,_=replay_trade(d,0,-1,Scenario('flat'))
        self.assertEqual(r['reason'],'target')
        self.assertEqual(r['exit_time'],120*MINUTE)
        self.assertAlmostEqual(r['exit_raw'],98.2)
        self.assertAlmostEqual(r['net_usd'],18.)

    def test_gap_stop_uses_open_long(self):
        r,_=replay_trade(candles({3:{'open':98.,'high':98.5,'low':97.}}),0,1,Scenario('flat'))
        self.assertEqual(r['reason'],'stop')
        self.assertEqual(r['exit_time'],3*MINUTE)
        self.assertEqual(r['exit_raw'],98.)
        self.assertAlmostEqual(r['net_usd'],-20.)

    def test_gap_stop_uses_open_short(self):
        r,_=replay_trade(candles({3:{'open':102.,'high':103.,'low':101.}}),0,-1,Scenario('flat'))
        self.assertEqual(r['exit_raw'],102.)
        self.assertAlmostEqual(r['net_usd'],-20.)

    def test_same_minute_stop_first(self):
        r,_=replay_trade(candles({1:{'high':104.,'low':98.}}),0,1,Scenario('flat'))
        self.assertEqual(r['reason'],'stop_both')
        self.assertAlmostEqual(r['net_usd'],-9.)

    def test_known_open_target_before_later_stop(self):
        r,_=replay_trade(candles({1:{'open':103.,'high':104.,'low':98.}}),0,1,Scenario('flat'))
        self.assertEqual(r['reason'],'target')
        self.assertEqual(r['execution_kind'],'open')
        self.assertAlmostEqual(r['net_usd'],18.)

    def test_missing_entry_no_late_fill(self):
        r,_=replay_trade(candles(missing=0),0,1,Scenario('flat'))
        self.assertEqual(r['status'],'missing_entry')
        self.assertEqual(r['net_usd'],0.)

    def test_missing_held_minute_unresolved(self):
        r,_=replay_trade(candles(missing=3),0,1,Scenario('flat'))
        self.assertEqual(r['status'],'unresolved_missing_held_minute')
        self.assertIsNone(r['net_usd'])

    def test_missing_exact_deadline_unresolved(self):
        r,_=replay_trade(candles(missing=120),0,1,Scenario('flat'))
        self.assertEqual(r['status'],'unresolved_missing_held_minute')

    def test_continuous_size_downward_cap(self):
        self.assertAlmostEqual(quantity(100.,.0004),10.)
        self.assertAlmostEqual(quantity(100.,.0004,risk=5.),5./.94)
        r,_=replay_trade(candles(),0,1,Scenario('flat',flat_cost=.0008,reserve=.0008))
        self.assertLessEqual(r['planned_stop_risk_usd'],10.)

    def test_actual_entry_rebuilds_stop_and_target(self):
        s=Scenario('exec',fee=.0001,slip=.0001)
        r,_=replay_trade(candles(),0,1,s)
        self.assertAlmostEqual(r['entry_exec'],100.01)
        self.assertAlmostEqual(r['stop'],100.01*.991)
        self.assertAlmostEqual(r['target'],100.01*1.018)
        self.assertEqual(r['flat_all_in_cost_usd'],0.)

    def test_flat_cost_does_not_add_funding(self):
        f=pd.DataFrame([{'fundingTime':MINUTE,'fundingRate':.01,'markPrice':100.}])
        r,_=replay_trade(candles(),0,1,Scenario('flat',flat_cost=.0004),f)
        self.assertAlmostEqual(r['net_usd'],-.4)
        self.assertEqual(r['funding_usd'],0.)

    def test_gap_exit_excludes_later_funding(self):
        f=pd.DataFrame([{'fundingTime':3*MINUTE+1,'fundingRate':.01,'markPrice':100.}])
        r,_=replay_trade(candles({3:{'open':98.,'high':98.5,'low':97.}}),0,1,Scenario('exec',use_funding=True),f)
        self.assertEqual(r['funding_usd'],0.)

    def test_entry_exact_boundary_excludes_earlier_settlement(self):
        f=pd.DataFrame([{'fundingTime':0,'fundingRate':.01,'markPrice':100.},
                        {'fundingTime':MINUTE,'fundingRate':.01,'markPrice':100.}])
        r,_=replay_trade(candles(),0,1,Scenario('exec',use_funding=True),f)
        self.assertAlmostEqual(r['funding_usd'],-10.)

    def test_intraminute_funding_order_is_bounded(self):
        f=pd.DataFrame([{'fundingTime':MINUTE+1,'fundingRate':-.01,'markPrice':100.}])
        r,_=replay_trade(candles({1:{'high':104.}}),0,1,Scenario('exec',use_funding=True),f)
        self.assertEqual(r['ambiguous_funding_events'],1)
        self.assertEqual(r['funding_usd'],0.)
        self.assertAlmostEqual(r['funding_upper_usd'],10.)

    def test_funding_exact_exit_open_is_bounded(self):
        f=pd.DataFrame([{'fundingTime':120*MINUTE,'fundingRate':.01,'markPrice':100.}])
        r,_=replay_trade(candles(),0,1,Scenario('exec',use_funding=True),f)
        self.assertEqual(r['ambiguous_funding_events'],1)
        self.assertAlmostEqual(r['funding_usd'],-10.)
        self.assertEqual(r['funding_upper_usd'],0.)


if __name__=='__main__':
    unittest.main()
