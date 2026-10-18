"""Invented stdlib-only tests. No market files, transport, accounts or services."""
from dataclasses import replace
from decimal import Decimal as D
import hashlib
from pathlib import Path
import random
import unittest

import proxy as p


ANCHOR = 1790920800000  # 2026-10-02 06:00 UTC


def bar(end, oi=100, price=100, low=None, high=None, unit="BTC", received=None):
    price = D(str(price))
    return p.FeatureBar(end - p.FIVE_MIN, end, price, D(str(high)) if high is not None else price,
                        D(str(low)) if low is not None else price, price, D(1), price,
                        D(str(oi)), unit, received)


def history(anchor=ANCHOR, lag=5, count=288):
    cutoff = anchor - lag * p.MINUTE
    return [bar(cutoff - (count - 1 - i) * p.FIVE_MIN) for i in range(count)]


def snapshot(oi=(), price=(), sid="invented"):
    return p.Snapshot(sid, ANCHOR, ANCHOR - p.FIVE_MIN, 5, D(100), "BTC", D(100),
                      (D(100) - sum((c.mass for c in oi if c.side == "LONG"), D(0)),
                       D(100) - sum((c.mass for c in oi if c.side == "SHORT"), D(0))),
                      tuple(oi), tuple(price), 288)


def cohort(side="LONG", level=100, mass=1, age_minutes=60):
    return p.Cohort(side, ANCHOR - p.FIVE_MIN - age_minutes * p.MINUTE, D(str(level)), D(str(mass)))


def path(prices=None):
    prices = [100] * 240 if prices is None else prices
    return [p.MarkMinute(ANCHOR + i * p.MINUTE, ANCHOR + (i + 1) * p.MINUTE,
                         D(str(value)), "MARK", True) for i, value in enumerate(prices)]


def message(identity="id", side="LONG", minute=0, digest=None):
    return p.Message(identity, ANCHOR + minute * p.MINUTE, side, p.EVENT_SCHEMA,
                     digest or hashlib.sha256(identity.encode()).hexdigest(), "BINANCE", "USD-M", "BTCUSDT",
                     ANCHOR + minute*p.MINUTE + 7)


def spans():
    return [p.ConnectedSpan(ANCHOR, ANCHOR + 240 * p.MINUTE, p.EVENT_SCHEMA, True,"INVENTED:connected-session")]


class Registration(unittest.TestCase):
    def test_fixed_documents_unchanged_before_synthetic_execution(self):
        result = p.verify_registration(Path(__file__).resolve().parent)
        self.assertTrue(result["verified"])
        self.assertEqual(result["files"]["PROTOCOL.md"], p.PROTOCOL_SHA256)
        self.assertEqual(result["files"]["MODEL.md"], p.MODEL_SHA256)


class StateTests(unittest.TestCase):
    def test_cold_unknown_equal_both_sides_then_balanced_positive_oi(self):
        state = p.ProxyState()
        state.add_bar(bar(10 * p.FIVE_MIN, 100))
        self.assertEqual(state.unknown, {"LONG": D(100), "SHORT": D(100)})
        self.assertFalse(state.oi_cohorts)
        state.add_bar(bar(11 * p.FIVE_MIN, 140))
        for side in p.SIDES:
            own = [c for c in state.oi_cohorts if c.side == side]
            self.assertEqual(len(own), 4)
            self.assertEqual([c.mass for c in own], [D(10)] * 4)
            self.assertEqual(sum(c.mass for c in own) + state.unknown[side], D(140))

    def test_one_contraction_scales_unknown_and_active_once(self):
        state = p.ProxyState()
        for end, oi in ((p.FIVE_MIN, 100), (2*p.FIVE_MIN, 140), (3*p.FIVE_MIN, 70)):
            state.add_bar(bar(end, oi))
        for side in p.SIDES:
            self.assertEqual(state.unknown[side], D(50))
            self.assertEqual(sum(c.mass for c in state.oi_cohorts if c.side == side), D(20))
        state.add_bar(bar(4*p.FIVE_MIN, 0))
        self.assertEqual(sum(state.unknown.values()), 0)
        self.assertFalse(state.oi_cohorts)

    def test_newborn_is_not_touched_by_its_own_birth_bar(self):
        state = p.ProxyState()
        state.add_bar(bar(p.FIVE_MIN, 100))
        state.add_bar(bar(2*p.FIVE_MIN, 140, low=80, high=120))
        self.assertEqual(len(state.oi_cohorts), 8)
        self.assertEqual(len(state.price_cohorts), 8)

    def test_previous_bar_newborn_touch_equality_then_single_contraction(self):
        state = p.ProxyState()
        state.add_bar(bar(p.FIVE_MIN, 100))
        state.add_bar(bar(2*p.FIVE_MIN, 120))
        report = state.add_bar(bar(3*p.FIVE_MIN, 60, low=98, high=100))
        self.assertEqual(state.unknown["LONG"], D(55))
        self.assertEqual(state.unknown["SHORT"], D(50))
        self.assertEqual(sum(c.mass for c in state.oi_cohorts if c.side == "LONG"), D(5))
        self.assertEqual(sum(c.mass for c in state.oi_cohorts if c.side == "SHORT"), D(10))
        self.assertEqual(report["retired_mass_by_disjoint_reason"]["touch_only"], "10")

    def test_gap_price_and_simultaneous_expiry_touch_count_once(self):
        state = p.ProxyState()
        state.add_bar(bar(p.FIVE_MIN, 0))
        state.add_bar(bar(2*p.FIVE_MIN, 40))
        for i in range(3,290):
            state.add_bar(bar(i*p.FIVE_MIN, 40))
        report = state.add_bar(bar(290*p.FIVE_MIN, 40, low=80, high=120))
        self.assertEqual(report["retired_mass_by_disjoint_reason"]["touch_and_expiry"], "80")
        self.assertEqual(state.unknown, {"LONG": D(40), "SHORT": D(40)})
        self.assertFalse(state.oi_cohorts)

    def test_gap_resets_unknown_and_warmup(self):
        state = p.ProxyState()
        for item in history():
            state.add_bar(item)
        self.assertTrue(state.warm)
        report = state.add_bar(bar(state.last_end_ms + 2*p.FIVE_MIN, 120))
        self.assertEqual(report["reset_reason"], "missing_5m_grid")
        self.assertEqual(state.contiguous_bars, 1)
        self.assertFalse(state.warm)
        self.assertEqual(state.unknown, {"LONG": D(120), "SHORT": D(120)})

    def test_duplicate_invalid_and_units_reset_without_silent_repair(self):
        state = p.ProxyState()
        state.add_bar(bar(p.FIVE_MIN))
        with self.assertRaises(p.IntegrityError):
            state.add_bar(bar(p.FIVE_MIN))
        self.assertIsNone(state.last_end_ms)
        state.add_bar(bar(2*p.FIVE_MIN))
        report = state.add_bar(bar(3*p.FIVE_MIN, unit="CONTRACT"))
        self.assertEqual(report["reset_reason"], "quantity_unit_changed")
        self.assertEqual(state.unit, "CONTRACT")

    def test_bad_ohlc_zero_volume_nan_negative_oi_clear_segment(self):
        for bad in (replace(bar(p.FIVE_MIN), low=D(101)),
                    replace(bar(p.FIVE_MIN), base_volume=D(0)),
                    replace(bar(p.FIVE_MIN), oi_quantity=D(-1)),
                    replace(bar(p.FIVE_MIN), close=D("NaN"))):
            state = p.ProxyState()
            with self.assertRaises(p.IntegrityError):
                state.add_bar(bad)
            self.assertIsNone(state.last_end_ms)

    def test_expiry_transfers_mass_no_rebirth_at_constant_oi(self):
        state = p.ProxyState()
        state.add_bar(bar(p.FIVE_MIN, 0))
        state.add_bar(bar(2*p.FIVE_MIN, 40))
        for i in range(3, 291):
            state.add_bar(bar(i*p.FIVE_MIN, 40))
        self.assertFalse(state.oi_cohorts)
        self.assertEqual(state.unknown, {"LONG": D(40), "SHORT": D(40)})
        self.assertTrue(state.price_cohorts)

    def test_price_comparator_births_are_independent_of_oi_growth(self):
        constant, growing = p.ProxyState(), p.ProxyState()
        for i in range(1, 10):
            constant.add_bar(bar(i*p.FIVE_MIN, 100))
            growing.add_bar(bar(i*p.FIVE_MIN, 100 + i))
        self.assertEqual(constant.price_cohorts, growing.price_cohorts)
        self.assertFalse(constant.oi_cohorts)
        self.assertTrue(growing.oi_cohorts)

    def test_identity_violation_is_an_error(self):
        state = p.ProxyState()
        state.add_bar(bar(p.FIVE_MIN, 10))
        state.unknown["LONG"] = D(9)
        with self.assertRaises(p.IntegrityError):
            state.check_identities()


class FreezeTests(unittest.TestCase):
    def test_warmup_288_complete_bars_and_exact_5m_cutoff(self):
        snap = p.freeze_prefix(history(), ANCHOR, "frozen", 5)
        self.assertEqual(snap.feature_end_ms, ANCHOR - p.FIVE_MIN)
        self.assertEqual(snap.contiguous_bars, 288)
        with self.assertRaises(p.NotAssessable):
            p.freeze_prefix(history(count=287), ANCHOR, "short", 5)
        with self.assertRaises(p.NotAssessable):
            p.freeze_prefix(history()[:-1], ANCHOR, "stale", 5)

    def test_30m_sensitivity_and_late_receive_reject(self):
        self.assertEqual(p.freeze_prefix(history(lag=30), ANCHOR, "lag30", 30).feature_end_ms,
                         ANCHOR - 30*p.MINUTE)
        items = history()
        items[-2] = replace(items[-2], received_at_ms=ANCHOR + 1)
        with self.assertRaises(p.NotAssessable):
            p.freeze_prefix(items, ANCHOR, "late", 5)
        with self.assertRaises(p.IntegrityError):
            p.freeze_prefix(history(), ANCHOR, "tuned", 10)

    def test_future_bars_do_not_change_snapshot_and_snapshot_is_detached(self):
        items = history()
        frozen = p.freeze_prefix(items, ANCHOR, "detached", 5)
        future = bar(ANCHOR + p.FIVE_MIN, 200)
        self.assertEqual(frozen, p.freeze_prefix(items + [future], ANCHOR, "detached", 5))
        items[-1] = bar(items[-1].end_ms, 200)
        self.assertEqual(frozen.oi_quantity, D(100))

    def test_anchor_schedule_and_id_guard(self):
        for anchor, sid in ((ANCHOR + p.MINUTE, "bad"), (ANCHOR, "")):
            with self.assertRaises(p.IntegrityError):
                p.freeze_prefix(history(), anchor, sid, 5)


class GeometryTests(unittest.TestCase):
    def test_top3_deterministic_non_touching_and_empty_allowed(self):
        cohorts = tuple(cohort(level=x, mass=m) for x, m in ((99, 3), (98, 2), (97, 1), (96, 1)))
        bands = p.top_bands(snapshot(oi=cohorts))["LONG"]
        self.assertEqual(len(bands), 3)
        # Equal mass scores prefer the candidate closest to reference, not
        # the cohort's own exact level (99.2 still contains level 99).
        self.assertEqual(bands[0]["center"], "99.200")
        for i, left in enumerate(bands):
            for right in bands[i+1:]:
                self.assertTrue(D(left["upper"]) < D(right["lower"]) or D(right["upper"]) < D(left["lower"]))
        self.assertEqual(p.top_bands(snapshot())["SHORT"], [])

    def test_placebo_fixed_199_seed_group_mass_geometry_and_global_rng(self):
        members = (cohort(level=99, mass=1), cohort(level=D("98.9"), mass=7),
                   cohort(side="SHORT", level=101, mass=4))
        snap = snapshot(oi=members, sid="fixed-id")
        before = random.getstate()
        shuffled, meta = p.placebos(snap)
        self.assertEqual(random.getstate(), before)
        self.assertEqual(len(shuffled), 199)
        self.assertEqual(shuffled, p.placebos(snap)[0])
        self.assertEqual(meta["replicate_indices"], "0..198")
        self.assertAlmostEqual(meta["singleton_cohort_fraction"], 1/3)
        for item in shuffled:
            self.assertEqual([(c.side,c.birth_end_ms,c.level) for c in item.oi_cohorts],
                             [(c.side,c.birth_end_ms,c.level) for c in shuffled[0].oi_cohorts])
            for side in p.SIDES:
                self.assertEqual(sum(c.mass for c in item.oi_cohorts if c.side == side),
                                 sum(c.mass for c in members if c.side == side))
        reversed_snap = replace(snap, oi_cohorts=tuple(reversed(snap.oi_cohorts)))
        self.assertEqual(shuffled, p.placebos(reversed_snap)[0])

    def test_age_and_distance_bucket_equality_boundaries(self):
        for age, expected in ((0,0),(60*p.MINUTE,1),(4*60*p.MINUTE,2),(12*60*p.MINUTE,3)):
            self.assertEqual(p._age_bucket(age), expected)
        with self.assertRaises(p.IntegrityError):
            p._age_bucket(p.DAY)
        for distance, expected in ((".49999",0),(".5",1),("1",2),("2",3),("3",4),("5",5),("10",5),("10.0001",6)):
            self.assertEqual(p._distance_bucket(D(distance)), expected)


class ScoreTests(unittest.TestCase):
    def test_zero_mass_uniform_but_zero_message_not_zero_result(self):
        result = p.score(snapshot(), path(), [], spans())
        self.assertEqual(result["status"], "NO_OBSERVED_MESSAGES")
        self.assertIsNone(result["anchor_d"])
        self.assertIsNone(result["sides"]["LONG"]["d"])
        self.assertAlmostEqual(sum(result["sides"]["LONG"]["p_oi"]), 1)
        observed = p.score(snapshot(), path(), [message()], spans())
        self.assertEqual(observed["anchor_d"], 0)
        self.assertEqual(observed["sides"]["LONG"]["messages"], 1)

    def test_exact_same_path_conditional_logscore_independent_arithmetic(self):
        snap = snapshot(oi=(cohort(level=100, mass=5),), price=(cohort(level=101, mass=1),))
        prices = [100]*120 + [101]*120
        result = p.score(snap, path(prices), [message(minute=0)], spans())
        import math
        expected = math.log((.95/120+.05/240)/(.05/240))
        self.assertAlmostEqual(result["anchor_d"], expected)
        swapped = p.score(snapshot(oi=snap.price_cohorts, price=snap.oi_cohorts),
                          path(prices), [message(minute=0)], spans())
        self.assertAlmostEqual(result["anchor_d"], -swapped["anchor_d"])
        side = result["sides"]["LONG"]
        self.assertAlmostEqual(side["d"],side["descriptive_oi_vs_uniform"]-side["descriptive_price_vs_uniform"])

    def test_single_visited_minute_logscore_oracle_and_common_mass_scale(self):
        import math
        oi = (cohort(level=100,mass=1),)
        marks = path([100]+[110]*239)
        result = p.score(snapshot(oi=oi),marks,[message()],spans())
        self.assertAlmostEqual(result["anchor_d"],math.log(228.05))
        elsewhere = p.score(snapshot(oi=oi),marks,[message(minute=1)],spans())
        self.assertAlmostEqual(elsewhere["anchor_d"],math.log(.05))
        scaled = p.score(snapshot(oi=(replace(oi[0],mass=D(20)),)),marks,[message()],spans())
        self.assertEqual(result["anchor_d"],scaled["anchor_d"])

    def test_anchor_sides_receive_equal_weight_despite_100_to_1_messages(self):
        marks = path([100]*120+[101]*120)
        oi=(cohort("LONG",100),cohort("SHORT",100))
        comparator=(cohort("LONG",101),cohort("SHORT",101))
        messages = [message(str(i),"LONG",0) for i in range(100)] + [message("short","SHORT",200)]
        report=p.score(snapshot(oi=oi,price=comparator),marks,messages,spans())
        self.assertAlmostEqual(report["anchor_d"],0.)
        self.assertAlmostEqual(report["sides"]["LONG"]["d"],-report["sides"]["SHORT"]["d"])

    def test_exact_240_mark_grid_no_trade_substitution_or_missing_fill(self):
        invalids = [path()[:-1], path() + [path()[0]],
                    [replace(x, price_kind="TRADE") for x in path()],
                    [replace(x, closed=False) for x in path()]]
        for rows in invalids:
            with self.assertRaises(p.NotAssessable):
                p.score(snapshot(), rows, [], spans())

    def test_coverage_gap_unknown_schema_and_side_refused(self):
        with self.assertRaises(p.NotAssessable):
            p.score(snapshot(), path(), [], [replace(spans()[0], end_ms=ANCHOR+239*p.MINUTE)])
        for bad in (replace(message(), position_side="BUY"), replace(message(), schema_id="unknown"),
                    replace(message(), venue="BYBIT"), replace(message(), transport_sha256="missing"),
                    replace(message(), event_time_field="E")):
            with self.assertRaises(p.IntegrityError):
                p.score(snapshot(), path(), [bad], spans())

    def test_disjoint_future_disconnection_does_not_invalidate_covered_window(self):
        outside = p.ConnectedSpan(ANCHOR+300*p.MINUTE,ANCHOR+400*p.MINUTE,"other-schema",False,"OUTSIDE")
        regular=p.score(snapshot(),path(),[],spans())
        full_inventory=p.score(snapshot(),path(),[],spans()+[outside])
        self.assertEqual(regular,full_inventory)
        intersects=replace(outside,start_ms=ANCHOR+200*p.MINUTE)
        with self.assertRaises(p.NotAssessable):
            p.score(snapshot(),path(),[],[replace(spans()[0],end_ms=ANCHOR+199*p.MINUTE),intersects])

    def test_full_healthy_span_cannot_hide_contradictory_overlap(self):
        disconnected=p.ConnectedSpan(ANCHOR+60*p.MINUTE,ANCHOR+90*p.MINUTE,p.EVENT_SCHEMA,False,"INVENTED")
        with self.assertRaises(p.NotAssessable):
            p.score(snapshot(),path(),[],spans()+[disconnected])

    def test_transport_identical_dedup_conflicting_identity_and_halfopen(self):
        a = message()
        result = p.score(snapshot(), path(), [a,replace(a,received_at_ms=ANCHOR+1000)], spans())
        self.assertEqual(result["canonical_messages"], 1)
        self.assertEqual(result["transport_duplicates"], 1)
        self.assertEqual(result["message_receive_audit"][0]["known_receipts"],1)
        self.assertEqual(result["message_receive_audit"][0]["receive_min_ms"],ANCHOR+1000)
        self.assertEqual(p.score(snapshot(),path(),[replace(a,envelope_event_ms=ANCHOR+p.MINUTE)],spans())
                         ["sides"]["LONG"]["minute_counts"][0],1)
        with self.assertRaises(p.IntegrityError):
            p.score(snapshot(), path(), [a, replace(a, position_side="SHORT")], spans())
        for event_time in (ANCHOR-1, ANCHOR+240*p.MINUTE):
            with self.assertRaises(p.IntegrityError):
                p.score(snapshot(), path(), [replace(a, event_ms=event_time)], spans())

    def test_boundary_band_is_inclusive_and_single_defined_side_not_halved(self):
        boundary = D(100)*D("1.0025")
        result = p.score(snapshot(oi=(cohort(level=100),)), path([boundary]*240),
                         [message(side="SHORT")], spans())
        self.assertEqual(result["defined_sides"], ["SHORT"])
        self.assertEqual(result["anchor_d"], result["sides"]["SHORT"]["d"])
        mixed = p.score(snapshot(oi=(cohort(level=100),)),path([boundary]+[110]*239),[message()],spans())
        just_outside = p.score(snapshot(oi=(cohort(level=100),)),
                               path([boundary+D(".00000001")]+[110]*239),[message()],spans())
        self.assertGreater(mixed["sides"]["LONG"]["p_oi"][0],1/240)
        self.assertEqual(just_outside["sides"]["LONG"]["p_oi"][0],1/240)
        self.assertFalse(mixed["sides"]["LONG"]["uniform_oi"])
        self.assertTrue(just_outside["sides"]["LONG"]["uniform_oi"])


class AggregateTests(unittest.TestCase):
    def test_daily_weighting_not_anchor_weighting_and_unmet_gates_null_ci(self):
        records = [p.ScoreRecord(ANCHOR, 1., 1, 1),
                   p.ScoreRecord(ANCHOR+6*60*p.MINUTE, 3., 1, 1),
                   p.ScoreRecord(ANCHOR+24*60*p.MINUTE, -2., 1, 1)]
        report = p.validation_summary(records)
        self.assertEqual(report["primary_mean"], 0.)
        self.assertEqual(report["verdict"], "INCONCLUSIVE")
        self.assertIsNone(report["CI95"])
        self.assertIn("calendar_week_clusters_lt_8", report["unmet_gates"])
        self.assertEqual(report["largest3_deleted_diagnostic"]["defined_anchors"], 0)

    def test_zero_message_record_undefined_not_invented_win(self):
        with self.assertRaises(p.IntegrityError):
            p.validation_summary([p.ScoreRecord(ANCHOR, 0., 0, 0)])
        result = p.validation_summary([p.ScoreRecord(ANCHOR, None, 0, 0)])
        self.assertIsNone(result["primary_mean"])
        self.assertEqual(result["no_message_anchors"], 1)

    def test_empty_feed_valid_days_do_not_inflate_defined_gates(self):
        rows = [p.ScoreRecord(ANCHOR+day*p.DAY,None,0,0) for day in range(60)]
        rows[0] = replace(rows[0],anchor_d=1.,long_messages=1)
        report = p.validation_summary(rows)
        self.assertGreaterEqual(report["valid_days"],40)
        self.assertEqual(report["defined_days"],1)
        self.assertEqual(report["score_defined_calendar_weeks"],1)
        self.assertIn("defined_UTC_days_lt_40",report["unmet_gates"])

    def test_fixed_week_bootstrap_negative_and_positive_gates(self):
        rows = [p.ScoreRecord(ANCHOR+day*p.DAY+slot*6*60*p.MINUTE, -1., 2, 3)
                for day in range(60) for slot in range(3)]
        before = random.getstate()
        report = p.validation_summary(rows)
        self.assertEqual(random.getstate(), before)
        self.assertEqual(report["CI95"], [-1.,-1.])
        self.assertFalse(report["unmet_gates"])
        self.assertTrue(report["verdict"].startswith("REJECT_FIXED_PROXY"))
        positive = p.validation_summary([replace(row,anchor_d=1.) for row in rows])
        self.assertTrue(positive["verdict"].startswith("POSITIVE_INTERVAL_REQUIRES"))
        self.assertFalse(positive["order_permission"])


if __name__ == "__main__":
    unittest.main()
