import unittest
from fetch_oi import PERIOD, coverage, validate


class OITests(unittest.TestCase):
    def row(self, ts=PERIOD):
        return {'symbol':'BTCUSDT','timestamp':ts,'sumOpenInterest':'10.5','sumOpenInterestValue':'800000'}

    def test_no_invented_missing_values(self):
        rows=validate([self.row(PERIOD)], 'BTCUSDT', 0, 3*PERIOD)
        c=coverage(rows, 0, 3*PERIOD)
        self.assertEqual(c['missing_timestamps'],[0,2*PERIOD])
        self.assertIsNone(c['historical_received_time'])
        self.assertEqual(len(rows),1)

    def test_exclusive_end_and_millisecond_units(self):
        for ts in (3*PERIOD, PERIOD*1000+1, -PERIOD, True):
            with self.assertRaises(ValueError):
                validate([self.row(ts)],'BTCUSDT',0,3*PERIOD)

    def test_units_kept_separate(self):
        r=validate([self.row()], 'BTCUSDT', 0, 3*PERIOD)[0]
        self.assertEqual(r['sumOpenInterest'],'10.5')
        self.assertEqual(r['sumOpenInterestValue'],'800000')

    def test_duplicates_bad_symbol_and_invalid_oi_rejected(self):
        with self.assertRaises(ValueError):
            validate([self.row(),self.row()], 'BTCUSDT', 0, 3*PERIOD)
        for key,value in [('symbol','ETHUSDT'),('sumOpenInterest','NaN'),('sumOpenInterestValue','-1')]:
            r=self.row();r[key]=value
            with self.assertRaises(ValueError):
                validate([r], 'BTCUSDT', 0, 3*PERIOD)


if __name__=='__main__':unittest.main()
