"""Independent invented-input QA. No market data, network, accounts or services."""
from dataclasses import replace
from datetime import datetime, timezone, timedelta
from decimal import Decimal as D
import hashlib
from pathlib import Path
import random
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import proxy as p

ANCHOR = 1790920800000


class IndependentQA(unittest.TestCase):
    def test_coverage_window_ignores_postwindow_reconnection_gap(self):
        full = p.ConnectedSpan(ANCHOR, ANCHOR + 240*p.MINUTE, p.EVENT_SCHEMA, True, "INVENTED")
        later = p.ConnectedSpan(ANCHOR + 300*p.MINUTE, ANCHOR + 400*p.MINUTE,
                                p.EVENT_SCHEMA, True, "INVENTED")
        p._check_spans([full], ANCHOR, ANCHOR + 240*p.MINUTE)
        # An unrelated gap 60 minutes AFTER a fully covered outcome must not
        # turn this historical anchor into a missing event-feed episode.
        p._check_spans([full, later], ANCHOR, ANCHOR + 240*p.MINUTE)

    def test_identical_public_envelope_dedups_with_distinct_local_receipts(self):
        msg = p.Message("public-id", ANCHOR, "LONG", p.EVENT_SCHEMA,
                        hashlib.sha256(b"INVENTED_PUBLIC_ENVELOPE").hexdigest(),
                        "BINANCE", "USD-M", "BTCUSDT", ANCHOR, "o.T", ANCHOR+100)
        unique, duplicates = p._canonical_messages(
            [msg, replace(msg, received_at_ms=ANCHOR+200)], ANCHOR, ANCHOR+240*p.MINUTE)
        self.assertEqual((len(unique), duplicates), (1, 1))

    def test_randomized_native_mass_identities_across_contraction_expiry_and_gap(self):
        rng, state = random.Random(31118), p.ProxyState()
        quantity = 100
        end = p.FIVE_MIN
        for i in range(620):
            if i == 310:
                end += p.FIVE_MIN
            quantity = max(0, quantity + rng.randrange(-20, 21))
            close = D(10000 + rng.randrange(-150, 151))/100
            b = p.FeatureBar(end-p.FIVE_MIN, end, close, close*D("1.01"), close*D(".99"),
                             close, D(1), close, D(quantity), "BTC")
            state.add_bar(b)
            for side in p.SIDES:
                total = state.unknown[side] + sum(
                    (c.mass for c in state.oi_cohorts if c.side == side), D(0))
                self.assertLessEqual(abs(total-D(quantity)), D("1e-9")*max(1, quantity))
            end += p.FIVE_MIN

    def test_nonconstant_whole_week_bootstrap_matches_direct_cluster_oracle(self):
        rows = []
        for day in range(60):
            for slot in range(2 + (day % 2)):
                value = ((day % 13) - 6)/5 + slot/17
                rows.append(p.ScoreRecord(ANCHOR+day*p.DAY+slot*6*60*p.MINUTE, value, 1, 2))
        actual = p.validation_summary(rows)
        daily = {}
        for row in rows:
            date = datetime.fromtimestamp(row.anchor_ms/1000, timezone.utc).date()
            daily.setdefault(date, []).append(row.anchor_d)
        week_values = {}
        for date, values in sorted(daily.items()):
            week = date - timedelta(days=date.weekday())
            week_values.setdefault(week, []).append(sum(values)/len(values))
        weeks, rng, distribution = sorted(week_values), random.Random(20261018), []
        for _ in range(10000):
            chosen = [rng.choice(weeks) for _ in weeks]
            values = [value for week in chosen for value in week_values[week]]
            distribution.append(sum(values)/len(values))
        distribution.sort()
        def quantile(q):
            x = (len(distribution)-1)*q
            lo = int(x)
            hi = min(lo+1, len(distribution)-1)
            return distribution[lo] + (distribution[hi]-distribution[lo])*(x-lo)
        self.assertFalse(actual["unmet_gates"])
        self.assertAlmostEqual(actual["CI95"][0], quantile(.025), places=12)
        self.assertAlmostEqual(actual["CI95"][1], quantile(.975), places=12)


if __name__ == "__main__":
    unittest.main()
