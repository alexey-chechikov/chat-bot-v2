"""Invented local fixtures only. No network/evidence/account access."""
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import analytics_daily as a

BASE = 1792075500000
END = BASE + 96 * a.STEP


def bar(t, price=100, base=10, buy=6):
    return {"bar_start_ms": t, "bar_end_ms": t + a.STEP, "closed": True,
            "open": str(price), "high": str(price + 2), "low": str(price - 1), "close": str(price + 1),
            "base_volume": str(base), "quote_volume": str(base * 100),
            "taker_buy_base": str(buy), "taker_buy_quote": str(buy * 100)}


def source(sid="binance_spot_15m", rows=None):
    return {"id": sid, "status": "OK", "url": "https://example.test/klines?startTime=1",
            "market_scope": "spot" if sid == "binance_spot_15m" else "futures", "aggregation": "bar",
            "settings": {"symbol": "BTCUSDT", "interval": "15m", "requested_closed_bars": 96,
                         "start_ms_inclusive": BASE, "end_ms_exclusive": END, "units": "OHLC USDT; base BTC"},
            "values": [{"name": "observations", "type": "json", "value": rows if rows is not None else [bar(BASE + i * a.STEP, 100 + i) for i in range(96)], "unit": "normalized bars"}]}


def run(stamp=END + 1000, sources=None, rid=None):
    report = {"schema": "daily-as-seen-v1", "synthetic": False, "order_permission": False,
              "archived_at_ms": stamp, "collected_at_ms": stamp - 500, "finished_at_ms": stamp - 100,
              "sources": sources if sources is not None else [source(), source("binance_perp_15m")]}
    return {"id": rid or f"2026-10-16/run_{stamp}", "sha256": hashlib.sha256(a.encoded(report)).hexdigest(), "report": report}


def values(group):
    return {m["name"]: None if m["value"] is None else Decimal(m["value"]) for m in group["metrics"]}


class MetricsTests(unittest.TestCase):
    def test_96_closed_grid_return_and_separate_spot_perp(self):
        spot, perp = source(), source("binance_perp_15m", [bar(BASE + i * a.STEP, 200 + i) for i in range(96)])
        groups, _ = a.analyze_run(run(sources=[spot, perp]), END + 2000)
        x, y = values(groups[spot["id"]]), values(groups[perp["id"]])
        self.assertEqual(x["return_24h_pct"], 96)
        self.assertEqual(y["return_24h_pct"], 48)
        self.assertEqual(x["high_24h"], 197)
        self.assertEqual(x["low_24h"], 99)
        self.assertEqual(x["return_1h_pct"], (Decimal(196) / 192 - 1) * 100)
        self.assertEqual(x["return_4h_pct"], (Decimal(196) / 180 - 1) * 100)

    def test_flow_weighted_not_mean_f_and_quote_base_separate(self):
        rows = [bar(BASE + i * a.STEP, base=0, buy=0) for i in range(96)]
        rows[0] = bar(BASE, base=1, buy=1); rows[1] = bar(BASE + a.STEP, base=9, buy=0)
        group, _ = a.market_metrics(source(rows=rows), END)
        metrics = values(group)
        self.assertEqual(metrics["F_volume_weighted"], Decimal("-.8"))
        self.assertEqual(metrics["delta_base_24h"], -8)
        self.assertEqual(metrics["delta_quote_24h"], -800)
        self.assertEqual(metrics["taker_sell_base_24h"], 9)

    def test_zero_flow_denominator_null(self):
        group, _ = a.market_metrics(source(rows=[bar(BASE + i * a.STEP, base=0, buy=0) for i in range(96)]), END)
        self.assertIsNone(values(group)["F_volume_weighted"])

    def test_missing_forming_conflict_and_invalid_bars_cannot_make_96(self):
        for mode in ("missing", "forming", "conflict", "invalid"):
            s = source(); rows = s["values"][0]["value"]
            if mode == "missing": rows.pop(10)
            elif mode == "forming": rows[10]["closed"] = False
            elif mode == "conflict": rows.append({**rows[10], "close": "110.5"})
            else: rows[10]["taker_buy_base"] = "1000"
            result, _ = a.market_metrics(s, END)
            self.assertFalse(result["coverage"]["complete_96_closed"])
            self.assertEqual(result["metrics"], [])

    def test_semantic_stable_settings_ignore_volatile_requests_and_timestamps(self):
        x, y = source(), source()
        y["settings"].update(start_ms_inclusive=BASE + a.STEP, end_ms_exclusive=END + a.STEP,
                               request={"url": "changed", "captured_at_ms": 999}, validation={"new": True}, captured_at_ms=999)
        y["url"] = "https://example.test/klines?startTime=999"
        self.assertEqual(a.semantic_hash(x), a.semantic_hash(y))
        y["settings"]["interval"] = "1h"
        self.assertNotEqual(a.semantic_hash(x), a.semantic_hash(y))

    def test_previous_baseline_absent_units_changed_zero_denominator(self):
        g, _ = a.market_metrics(source(), END)
        self.assertTrue(all(c["absolute"] is None for c in a.compare_groups({"s": g}, None)))
        previous = deepcopy(g); previous["metrics"][0]["value"] = "0"
        result = a.compare_groups({"s": g}, {"s": previous})
        self.assertIsNone(result[0]["relative_fraction"])
        self.assertEqual(Decimal(result[0]["absolute"]), 100)
        previous["metrics"][0]["unit"] = "USD"
        self.assertEqual(a.compare_groups({"s": g}, {"s": previous})[0]["status"], "INCOMPARABLE_SEMANTICS_OR_UNIT")

    def test_oi_quantity_value_and_time_alignment(self):
        perp, _ = a.market_metrics(source("binance_perp_15m"), END)
        s = {"id": "binance_oi_15m", "settings": {"start_ms_inclusive": BASE, "end_ms_inclusive": END},
             "values": [{"name": "observations", "type": "json", "value": [
                 {"timestamp_ms": BASE + i * a.STEP, "sum_open_interest": str(100 + i), "sum_open_interest_value": str(1000 + 2 * i), "quantity_unit": "contracts", "value_unit": "provider_value"} for i in range(97)]}]}
        g = a.oi_metrics(s, perp, END)
        self.assertEqual(g["perp_window_alignment"], "matched")
        self.assertEqual(values(g)["oi_quantity_change"], 96)
        self.assertEqual(values(g)["oi_value_change"], 192)
        self.assertEqual(values(g)["oi_quantity_change_pct"], 96)
        self.assertEqual(values(g)["oi_value_change_pct"], Decimal("19.2"))
        bad = deepcopy(perp); bad["window_end_ms"] += a.STEP
        self.assertEqual(a.oi_metrics(s, bad, END)["perp_window_alignment"], "MISMATCH_OR_UNAVAILABLE")

    def test_funding_signed_observed_events_no_interval_assumption(self):
        s = {"id": "binance_funding_24h", "values": [{"name": "observations", "type": "json", "value": [
            {"funding_time_ms": BASE + t, "funding_rate_fraction": rate} for t, rate in ((1, ".0001"), (12345, "-.0002"), (543210, ".00005"))]}]}
        result = a.funding_metrics(s, END)
        self.assertFalse(result["settlement_interval_assumed"])
        self.assertEqual(values(result)["funding_observed_signed_sum"], Decimal("-.00005"))
        self.assertEqual(result["observed_intervals_ms"], [12344, 530865])

    def test_funding_regular_special_same_timestamp_both_preserved(self):
        for second_rate in (".0001", ".0002"):
            s = {"id": "funding", "values": [{"name": "observations", "type": "json", "value": [
                {"funding_time_ms": BASE, "funding_rate_fraction": rate, "rate_type": typ}
                for rate, typ in ((".0001", "Regular"), (second_rate, "Special"))]}]}
            result = a.funding_metrics(s, END)
            self.assertEqual(len(result["events"]), 2)
            self.assertEqual(values(result)["funding_observed_signed_sum"], Decimal(".0001") + Decimal(second_rate))

    def test_missing_funding_count_zero_not_comparable_as_real_drop(self):
        missing = a.funding_metrics({"id": "funding", "values": []}, END)
        available = deepcopy(missing); available.update(status="OK", comparison_eligible=True)
        available["metrics"][0]["value"] = "3"
        comparisons = a.compare_groups({"funding": missing}, {"funding": available})
        self.assertEqual(comparisons[0]["status"], "INCOMPARABLE_SOURCE_STATUS")
        self.assertIsNone(comparisons[0]["absolute"])


class ProspectiveTests(unittest.TestCase):
    def plan(self, created=BASE + 123):
        return {"source_id": "binance_spot_15m", "semantic_hash": "same", "created_at_ms": created,
                "anchor_start_ms": a.anchor_at(created)}

    def rows(self, start, count):
        return a.parse_bars(source(rows=[bar(start + i * a.STEP, 120 + i) for i in range(count)]), start + count * a.STEP)[0]

    def test_anchor_ceil_uses_first_full_bar_open_no_hindsight(self):
        plan = self.plan(); self.assertEqual(plan["anchor_start_ms"], BASE + a.STEP)
        rows = self.rows(BASE, 3)
        result = a.outcome(plan, 15, rows, set(), END)
        self.assertEqual(result["status"], "MATURE")
        self.assertEqual(Decimal(result["baseline_open"]), 121)
        self.assertEqual(Decimal(result["end_close"]), 122)
        self.assertEqual(a.anchor_at(BASE), BASE)

    def test_strict_horizons_1_4_16_96_bars(self):
        plan = self.plan(BASE); rows = self.rows(BASE, 96)
        for horizon, count in ((15, 1), (60, 4), (240, 16), (1440, 96)):
            result = a.outcome(plan, horizon, rows, set(), END)
            self.assertEqual(result["expected_bars"], count)
            self.assertEqual(result["status"], "MATURE")

    def test_elapsed_without_new_refresh_stays_pending_not_zero(self):
        result = a.outcome(self.plan(BASE), 60, {}, set(), END)
        self.assertTrue(result["horizon_elapsed"])
        self.assertFalse(result["refresh_after_target"])
        self.assertEqual(result["status"], "PENDING")
        self.assertIsNone(result["return_pct"])

    def test_new_failed_or_stale_refresh_makes_missing_even_latestend_old(self):
        plan = self.plan(BASE); target = BASE + 4 * a.STEP
        refresh = {"collected_at_ms": target + a.STEP, "finished_at_ms": target + a.STEP + 1}
        result = a.outcome(plan, 60, {}, set(), END, [refresh])
        self.assertTrue(result["refresh_after_target"])
        self.assertEqual(result["status"], "MISSING")
        self.assertIsNone(result["return_pct"])

    def test_missing_middle_bar_endpoint_prices_not_enough(self):
        plan = self.plan(BASE); rows = self.rows(BASE, 4); rows.pop(BASE + a.STEP)
        refresh = {"collected_at_ms": BASE + 5 * a.STEP, "finished_at_ms": BASE + 5 * a.STEP}
        result = a.outcome(plan, 60, rows, set(), END, [refresh])
        self.assertEqual(result["status"], "MISSING")
        self.assertEqual(result["available_bars"], 3)

    def test_future_horizon_not_elapsed_even_rows_supplied(self):
        result = a.outcome(self.plan(BASE), 60, self.rows(BASE, 4), set(), BASE + 3 * a.STEP)
        self.assertEqual(result["status"], "PENDING")
        self.assertEqual(result["reason"], "horizon_not_elapsed")

    def test_archived_and_current_rows_merge_but_conflicts_are_missing(self):
        first, second = source(rows=[bar(BASE), bar(BASE + a.STEP)]), source(rows=[bar(BASE + 2 * a.STEP), bar(BASE + 3 * a.STEP)])
        merged, conflicts = a.merge_history([run(END + 1, [first]), run(END + 2, [second])], END + 3)
        key = a.semantic_hash(first)
        self.assertEqual(len(merged[key]), 4)
        overlap = source(rows=[{**bar(BASE), "close": "102"}])
        merged, conflicts = a.merge_history([run(END + 1, [first]), run(END + 2, [overlap])], END + 3)
        self.assertNotIn(BASE, merged[key]); self.assertIn(BASE, conflicts[key])

    def test_conflict_inside_later_snapshot_cannot_resurrect_older_valid_bar(self):
        first = source(rows=[bar(BASE)])
        later = source(rows=[bar(BASE), {**bar(BASE), "close": "102"}])
        merged, conflicts = a.merge_history([run(END + 1, [first]), run(END + 2, [later])], END + 3)
        key = a.semantic_hash(first)
        self.assertIn(BASE, conflicts[key]); self.assertNotIn(BASE, merged[key])

    def test_prior_anchor_cannot_be_rewritten_to_old_market_bar(self):
        prior = {"created_at_ms": END + 123, "prospective_plan": [{**self.plan(BASE), "created_at_ms": END + 123}]}
        with self.assertRaises(ValueError): a.compute([run()], [prior], END + 2000)

    def test_mature_1h_aligned_flow_oi_same_window_not_current_daily(self):
        prior = {"prospective_plan": [{"source_id": sid, "semantic_hash": key} for sid, key in
                 (("binance_spot_15m", "spotdef"), ("binance_perp_15m", "perpdef"))],
                 "current_sources": {"binance_oi_15m": {"semantic_hash": "oidef"}}}
        bars = self.rows(BASE, 4)
        points = {BASE: {"quantity": Decimal(100), "value": Decimal(1000), "quantity_unit": "contracts", "value_unit": "provider_value"},
                  BASE + 4 * a.STEP: {"quantity": Decimal(150), "value": Decimal(1200), "quantity_unit": "contracts", "value_unit": "provider_value"}}
        context = a.aligned_context(prior, BASE, BASE + 4 * a.STEP, {"spotdef": bars, "perpdef": bars}, {}, {"oidef": points}, {})
        self.assertEqual(context["spot"]["status"], "AVAILABLE")
        self.assertEqual(Decimal(context["spot"]["metrics"]["base_volume_BTC"]), 40)
        self.assertEqual(Decimal(context["perpetual"]["metrics"]["delta_base_BTC"]), 8)
        self.assertEqual(Decimal(context["oi"]["metrics"]["quantity_change_pct"]), 50)
        self.assertEqual(Decimal(context["oi"]["metrics"]["value_change"]), 200)
        self.assertFalse(context["causal_claim"])
        no_oi = a.aligned_context(prior, BASE, BASE + 4 * a.STEP, {"spotdef": bars, "perpdef": bars}, {}, {}, {})
        self.assertEqual(no_oi["oi"]["status"], "MISSING")
        self.assertIsNone(no_oi["oi"]["metrics"])


class ArchiveIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix=".analytics_synthetic_test_", dir=Path(__file__).resolve().parent)
        self.root = Path(self.temp.name)

    def tearDown(self): self.temp.cleanup()

    def save(self, item):
        path = self.root / item["id"] / "report.json"; path.parent.mkdir(parents=True)
        path.write_text(json.dumps(item["report"]), encoding="utf-8"); return path

    def test_skip_synthetic_preflight_and_reuse_one_per_input_without_rewrites(self):
        real_fixture = run(); original = self.save(real_fixture); original_bytes = original.read_bytes()
        ignored = run(END + 2000, rid=f"2026-10-16/run_{END+2000}"); ignored["report"]["synthetic"] = True; self.save(ignored)
        preflight = self.root / "preflight_123"; preflight.mkdir(); (preflight / "report.json").write_bytes(original_bytes)
        target, report, reused = a.analyze(self.root, _clock=lambda: END + 3000, _synthetic_test=True)
        self.assertFalse(reused); before = (target / "report.json").read_bytes()
        same, _, reused = a.analyze(self.root, _clock=lambda: END + 4000, _synthetic_test=True)
        self.assertTrue(reused); self.assertEqual(target, same)
        self.assertEqual((target / "report.json").read_bytes(), before)
        self.assertEqual(original.read_bytes(), original_bytes)
        self.assertFalse(report["order_permission"])
        self.assertEqual(len(list((self.root / "analytics").glob("analysis_*"))), 1)

    def test_changed_immutable_input_rejected(self):
        path = self.save(run())
        a.analyze(self.root, _clock=lambda: END + 3000, _synthetic_test=True)
        data = json.loads(path.read_text()); data["status"] = "changed"; path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "SHA changed"):
            a.analyze(self.root, _clock=lambda: END + 4000, _synthetic_test=True)

    def test_mutated_old_input_with_new_latest_run_is_rejected(self):
        first = self.save(run())
        a.analyze(self.root, _clock=lambda: END + 3000, _synthetic_test=True)
        data = json.loads(first.read_text()); data["status"] = "mutated_old"; first.write_text(json.dumps(data))
        self.save(run(END + 4000))
        with self.assertRaisesRegex(ValueError, "SHA changed"):
            a.analyze(self.root, _clock=lambda: END + 5000, _synthetic_test=True)

    def test_no_historical_clock_cli_or_non_synthetic_clock_override(self):
        self.save(run())
        with self.assertRaises(ValueError): a.analyze(self.root, _clock=lambda: BASE)


if __name__ == "__main__": unittest.main()
