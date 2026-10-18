import tempfile
from pathlib import Path
import unittest
from fetch_spot_flow_history import parse_row, normalize_epoch, pair_flow, FIELDS, START, MINUTE

def row(ts=START, us=False):
    close=ts+15*MINUTE-1
    if us:
        ts=ts*1000; close=close*1000+999
    return [str(ts),'100','102','99','101','10',str(close),'1000','5','6','600','0']

class HistoryTests(unittest.TestCase):
    def test_microseconds_preserve_closed_interval(self):
        a,unit=parse_row(row(us=True))
        b,_=parse_row(row())
        self.assertEqual(a,b)
        self.assertEqual(unit,'microseconds')
    def test_seconds_not_silently_accepted(self):
        with self.assertRaises(ValueError): normalize_epoch(1790000000)
    def test_bad_buy_volume_and_forming_timestamp_rejected(self):
        for index,value in ((9,'11'),(6,str(START+15*MINUTE))):
            a=row(); a[index]=value
            with self.assertRaises(ValueError): parse_row(a)
    def test_pair_requires_all_fifteen_minutes(self):
        import csv
        spot,_=parse_row(row())
        base=Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory(dir=base,prefix='.test-flow-') as d:
            self.assertTrue(Path(d).resolve().is_relative_to(base))
            p=Path(d)/'public_futures.csv'
            with p.open('w',newline='',encoding='utf-8') as f:
                w=csv.DictWriter(f,fieldnames=FIELDS); w.writeheader()
                for i in range(15):
                    ts=START+i*MINUTE
                    a=row(ts); a[6]=str(ts+MINUTE-1)
                    v,_=parse_row(a,MINUTE); w.writerow(v)
            v=pair_flow([spot],p)[0]
            self.assertAlmostEqual(v['spot_F'],.2)
            self.assertAlmostEqual(v['perp_F'],.2)
            self.assertAlmostEqual(v['perp_volume_btc'],150)
            lines=p.read_text().splitlines()
            p.write_text('\n'.join(lines[:-1])+'\n')
            with self.assertRaises(ValueError): pair_flow([spot],p)

if __name__=='__main__': unittest.main()
