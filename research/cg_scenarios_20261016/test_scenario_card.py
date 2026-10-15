from copy import deepcopy
from decimal import Decimal as D
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from make_synthetic import BASE, sample_input, examples
import scenario_card as sc


def run(data=None):
    return sc.build_card(sample_input() if data is None else data, synthetic=True)


class CardTests(unittest.TestCase):
    def test_ready_is_research_only_no_primary_or_order_permission(self):
        card = run()
        self.assertEqual(card["status"], "READY_RESEARCH")
        self.assertEqual(card["setup"], "LONG_RECLAIM")
        self.assertTrue(card["conditions_passed"])
        self.assertFalse(card["trade_permission"])
        self.assertFalse(card["primary_admitted"])
        self.assertEqual(D(card["entry"]), D(100))

    def test_synthetic_requires_explicit_mode_and_matching_flag(self):
        with self.assertRaises(sc.InputError):
            sc.build_card(sample_input())
        data = sample_input(); data["synthetic"] = False
        with self.assertRaises(sc.InputError):
            run(data)

    def test_t0_uses_later_freeze_strictly_and_signal_whole_bar(self):
        data = sample_input()
        data["snapshot"]["annotation_lock_ms"] = BASE + sc.MINUTE
        data["ohlc_15m"][-2].update(low="95")  # 00:00 bar begins before t0
        card = run(data)
        self.assertEqual(card["t0_ms"], BASE + 2 * sc.MINUTE)
        self.assertEqual(card["signal"]["start_ms"], BASE + 15 * sc.MINUTE)

    def test_wait_for_full_closed_bar_no_touch_entry(self):
        data = examples()["wait"]
        card = run(data)
        self.assertEqual(card["status"], "WAIT")
        self.assertIsNone(card["entry"])
        data = sample_input()
        data["ohlc_15m"][-1]["close"] = "97.5"
        self.assertEqual(run(data)["status"], "WAIT")

    def test_reclaim_strict_on_extreme_and_close_both_sides(self):
        for low, close in (("97", "100"), ("96", "98")):
            data = sample_input(); data["ohlc_15m"][-1].update(low=low, close=close)
            self.assertEqual(run(data)["status"], "WAIT")
        data = sample_input()
        data["snapshot"]["lower_zone"] = {"low": "75", "high": "78"}
        data["snapshot"]["upper_zone"] = {"low": "102", "high": "103"}
        data["ohlc_15m"][-1].update(low="99.8", high="104")
        data["next_available_quote"]["side"] = "SELL"
        card = run(data)
        self.assertEqual(card["status"], "READY_RESEARCH")
        self.assertEqual(card["setup"], "SHORT_RECLAIM")
        self.assertEqual(D(card["stop"]), D("104.1"))
        self.assertEqual(D(card["target"]), D(78))

    def test_both_zones_consumes_snapshot_without_entry(self):
        data = sample_input(); data["ohlc_15m"][-1]["high"] = "121"
        card = run(data)
        self.assertEqual(card["status"], "NO_TRADE")
        self.assertEqual(card["reasons"], ["BOTH_ZONES_IN_SIGNAL_BAR"])
        self.assertTrue(card["attempt_consumed"])

    def test_unknown_entry_stays_conditional_never_close_spot_or_zone_price(self):
        for quote in (None, {"price": None, "received_ms": BASE + 30 * sc.MINUTE}):
            data = sample_input(); data["next_available_quote"] = quote
            data["snapshot"]["frozen_spot"] = "110"
            card = run(data)
            self.assertEqual(card["status"], "CONDITIONAL")
            self.assertIsNone(card["entry"])
            self.assertIsNone(card["quantity"])
            self.assertNotIn("net_rr_reserve8bp", card)
            self.assertEqual(D(card["target"]), D(120))

    def test_lag_unknown_outside_primary_and_known_stale_refused(self):
        card = run(examples()["unknown_lag"])
        self.assertEqual(card["status"], "CONDITIONAL")
        self.assertEqual(card["source_lag_status"], "UNKNOWN")
        self.assertFalse(card["conditions_passed"])
        self.assertFalse(card["primary_admitted"])
        for source_asof in (BASE - 120_001, BASE + 1):
            data = sample_input(); data["snapshot"]["source_asof_ms"] = source_asof
            self.assertEqual(run(data)["status"], "NO_TRADE")

    def test_unknown_settings_or_contract_cannot_be_ready(self):
        data = sample_input(); del data["snapshot"]["settings"]["model"]
        self.assertEqual(run(data)["status"], "CONDITIONAL")
        data = sample_input(); data["contract"] = {}
        card = run(data)
        self.assertEqual(card["status"], "CONDITIONAL")
        self.assertIsNone(card["entry"])
        self.assertIsNone(card["stop"])

    def test_invalid_source_and_explicit_stale_or_incomplete_refused(self):
        for field in ("source_record_fresh", "source_record_complete", "annotation_frozen"):
            data = sample_input(); data["snapshot"][field] = False
            self.assertEqual(run(data)["status"], "NO_TRADE")
        data = sample_input(); data["snapshot"]["settings"]["exchange"] = "WEEX"
        self.assertEqual(run(data)["status"], "NO_TRADE")

    def test_snapshot_id_required_and_contract_bound_to_exact_market(self):
        for sid in (None, "", "  "):
            data = sample_input(); data["snapshot"]["snapshot_id"] = sid
            self.assertEqual(run(data)["status"], "NO_TRADE")
            self.assertIn("MISSING_SNAPSHOT_ID", run(data)["reasons"])
        data = sample_input(); data["contract"]["exchange"] = "WEEX"
        self.assertIn("WRONG_CONTRACT_BINDING", run(data)["reasons"])
        data = sample_input(); del data["contract"]["market"]
        self.assertEqual(run(data)["status"], "CONDITIONAL")

    def test_declared_contract_minimums_required_and_enforced(self):
        data = sample_input(); data["contract"].pop("min_quantity")
        card = run(data)
        self.assertEqual(card["status"], "CONDITIONAL")
        self.assertIn("UNKNOWN_CONTRACT_MINIMUMS", card["reasons"])
        data = sample_input(); data["contract"].update(min_quantity="100", min_notional="100000")
        card = run(data)
        self.assertEqual(card["status"], "NO_TRADE")
        self.assertIn("BELOW_CONTRACT_MIN_QUANTITY", card["reasons"])
        self.assertIn("BELOW_CONTRACT_MIN_NOTIONAL", card["reasons"])
        data = sample_input(); data["contract"]["min_notional"] = "-1"
        self.assertIn("INVALID_CONTRACT_MINIMUMS", run(data)["reasons"])
        data = sample_input(); data["contract"]["tick_size"] = "0"
        self.assertEqual(run(data)["status"], "NO_TRADE")

    def test_freeze_future_or_expired_deadline_refused(self):
        data = sample_input(); data["snapshot"]["annotation_lock_ms"] = data["data_asof_ms"] + 1
        self.assertIn("FREEZE_AFTER_DATA_ASOF", run(data)["reasons"])
        data = sample_input(); data["data_asof_ms"] = BASE + 241 * sc.MINUTE
        self.assertIn("DEADLINE_REACHED", run(data)["reasons"])

    def test_quote_before_close_future_old_or_other_signal_refused(self):
        for update in ({"received_ms": BASE + 30 * sc.MINUTE - 1},
                       {"received_ms": BASE + 30 * sc.MINUTE + 1},
                       {"signal_close_ms": BASE + 15 * sc.MINUTE}, {"side": "SELL"}, {"exchange": "WEEX"}):
            data = sample_input(); data["next_available_quote"].update(update)
            self.assertEqual(run(data)["status"], "NO_TRADE")
        data = sample_input(); data["data_asof_ms"] += 60_001
        self.assertIn("QUOTE_STALE", run(data)["reasons"])

    def test_quote_executability_and_first_receipt_not_assumed(self):
        for field in ("executable", "first_available_after_close"):
            data = sample_input(); data["next_available_quote"].pop(field)
            card = run(data)
            self.assertEqual(card["status"], "CONDITIONAL")
            self.assertIsNone(card["entry"])

    def test_late_quote_not_rescued_by_current_freshness(self):
        data = sample_input()
        data["data_asof_ms"] += 2 * 60 * sc.MINUTE
        data["next_available_quote"]["received_ms"] = data["data_asof_ms"]
        card = run(data)
        self.assertEqual(card["status"], "NO_TRADE")
        self.assertIn("LATE_FIRST_ENTRY_QUOTE", card["reasons"])
        data = sample_input()
        data["data_asof_ms"] += 60_000
        data["next_available_quote"]["received_ms"] += 60_000
        self.assertEqual(run(data)["status"], "READY_RESEARCH")
        data["data_asof_ms"] += 1
        data["next_available_quote"]["received_ms"] += 1
        self.assertIn("LATE_FIRST_ENTRY_QUOTE", run(data)["reasons"])

    def test_atr_and_outward_stop_do_not_use_signal_extrema(self):
        card = run()
        self.assertEqual(D(card["previous_atr14"]), D("0.4"))
        self.assertEqual(D(card["stop"]), D("95.9"))
        data = sample_input(); data["ohlc_15m"][-1]["low"] = "80"
        changed = run(data)
        self.assertEqual(card["previous_atr14"], changed["previous_atr14"])
        self.assertEqual(changed["status"], "NO_TRADE")

    def test_minimum_atr_true_prevclose_and_wilder_gap(self):
        bars = {i * sc.M15: sc.Bar(i * sc.M15, D(100), D(101), D(99), D(100)) for i in range(15)}
        self.assertIsNone(sc.atr_before(bars, 0, 14 * sc.M15))
        self.assertEqual(sc.atr_before(bars, 0, 15 * sc.M15), D(2))
        bars[15 * sc.M15] = sc.Bar(15 * sc.M15, D(110), D(111), D(109), D(110))
        self.assertEqual(sc.atr_before(bars, 0, 16 * sc.M15), (D(13) * 2 + 11) / 14)

    def test_missing_causal_atr_or_signal_data_refused(self):
        data = sample_input(); data["ohlc_15m"].pop(3)
        self.assertIn("MISSING_PREVIOUS_ATR14", run(data)["reasons"])
        data = sample_input(); data["data_asof_ms"] += sc.M15
        data["ohlc_15m"][-1].update(low="99.8")  # first possible bar has no reclaim
        self.assertIn("MISSING_SIGNAL_BAR", run(data)["reasons"])

    def test_unclosed_misaligned_duplicate_price_not_accepted(self):
        for field, update in (("ts_ms", BASE + 16 * sc.MINUTE), ("high", "99")):
            data = sample_input(); data["ohlc_15m"][-1][field] = update
            self.assertEqual(run(data)["status"], "NO_TRADE")
        data = sample_input(); data["ohlc_15m"].append(deepcopy(data["ohlc_15m"][-1]))
        self.assertEqual(run(data)["status"], "NO_TRADE")
        data = sample_input(); data["data_asof_ms"] -= 1
        self.assertEqual(run(data)["status"], "NO_TRADE")

    def test_one_minute_aggregate_and_crosscheck_no_false_fullness(self):
        data = sample_input()
        original = data["ohlc_15m"][-1]
        data["ohlc_1m"] = [{"ts_ms": BASE + i * sc.MINUTE, "open": "100", "high": "100.2", "low": "99.8", "close": "100"}
                           for i in range(15, 30)]
        data["ohlc_1m"][0].update(high="101", low="96")
        self.assertEqual(run(data)["status"], "READY_RESEARCH")
        data["ohlc_1m"][0]["low"] = "95"
        self.assertEqual(run(data)["status"], "NO_TRADE")
        data["ohlc_1m"][0]["low"] = original["low"]
        data["ohlc_1m"].pop(5)
        self.assertEqual(run(data)["status"], "NO_TRADE")

    def test_rr_exact_two_below_and_size_cost_once(self):
        data = sample_input(); data["contract"]["tick_size"] = "0.01"
        data["snapshot"]["upper_zone"] = {"low": "108.32", "high": "109"}
        card = run(data)
        self.assertEqual(card["status"], "READY_RESEARCH")
        self.assertEqual(D(card["net_rr_reserve8bp"]), D(2))
        self.assertLessEqual(D(card["planned_loss_with_reserve"]), D(25))
        self.assertLessEqual(D(card["entry_notional"]), D(10000))
        self.assertEqual(D(card["planned_loss_with_reserve"]), D(card["quantity"]) * (D("4.04") + D("0.08")))
        data["snapshot"]["upper_zone"]["low"] = "108.31"
        self.assertIn("NET_RR_BELOW_2", run(data)["reasons"])

    def test_signed_geometry_gap_and_quantity_rounding(self):
        for entry in ("94", "120", "130"):
            data = sample_input(); data["next_available_quote"]["price"] = entry
            self.assertIn("INVALID_SIGNED_GEOMETRY", run(data)["reasons"])
        data = sample_input(); data["contract"]["quantity_step"] = "1000"
        self.assertIn("QUANTITY_ROUNDED_TO_ZERO", run(data)["reasons"])

    def test_consumed_and_busy_are_refusals_not_retries(self):
        for state in ("consumed", "position_open"):
            data = sample_input(); data["attempt_state"] = state
            card = run(data)
            self.assertEqual(card["status"], "NO_TRADE")
            self.assertIsNone(card["entry"])
            self.assertTrue(card["attempt_consumed"])

    def test_quote_is_price_anchor_and_colours_are_not_forecasts(self):
        data = sample_input(); data["snapshot"]["frozen_spot"] = "110"
        data["snapshot"]["upper_zone"].update(colour="yellow", intensity="99999999999")
        card = run(data)
        self.assertEqual(card["entry"], run()["entry"])
        data["next_available_quote"]["price"] = "110"
        self.assertEqual(run(data)["entry"], "110")
        self.assertIn("NET_RR_BELOW_2", run(data)["reasons"])
        baseline = sample_input(); coloured = deepcopy(baseline)
        coloured["snapshot"]["upper_zone"].update(colour="yellow", intensity="99999999")
        self.assertEqual(run(baseline), run(coloured))

    def test_continuation_is_diagnostic_with_invalidation_no_entry(self):
        for opening, high, low, close, expected in (("130", "131", "129", "130", "UP_DIAGNOSTIC_ONLY"),
                                                  ("90", "91", "89", "90", "DOWN_DIAGNOSTIC_ONLY")):
            data = sample_input(); data["ohlc_15m"][-1].update(open=opening, high=high, low=low, close=close)
            data["next_available_quote"] = None
            card = run(data)
            self.assertEqual(card["continuation"]["status"], expected)
            self.assertIn("invalidation", card["continuation"])
            self.assertFalse(card["continuation"]["executable"])
            self.assertEqual(card["status"], "WAIT")
            self.assertIsNone(card["entry"])

    def test_spot_perp_f_same_closed_bar_only_diagnostic_never_filter(self):
        data = sample_input()
        def flow(market, f):
            return {"market": market, "exchange": "Binance", "symbol": "BTCUSDT", "verified": True,
                    "bar_start_ms": BASE + 15 * sc.MINUTE, "received_ms": BASE + 30 * sc.MINUTE, "F": f}
        for f in ("-1", "1"):
            data["flows"] = {"spot": flow("spot", f), "perp": flow("perpetual", "0.2")}
            card = run(data)
            self.assertEqual(card["status"], "READY_RESEARCH")
            self.assertEqual(card["flow"]["status"], "AVAILABLE_DIAGNOSTIC_ONLY")
            self.assertFalse(card["flow"]["used_as_filter"])
        data["flows"]["spot"]["bar_start_ms"] -= sc.M15
        self.assertEqual(run(data)["flow"]["status"], "UNAVAILABLE")
        self.assertEqual(run(data)["status"], "READY_RESEARCH")

    def test_pure_no_input_mutation_and_markdown_has_no_fake_entry(self):
        data = examples()["conditional"]; original = deepcopy(data)
        card = run(data); markdown = sc.render_markdown(card)
        self.assertEqual(data, original)
        self.assertIn("E: неизвестна", markdown)
        self.assertNotIn("E: 100", markdown)
        self.assertIn("Ценовая инвалидация:", markdown)
        self.assertIn("S=95.9", markdown)
        self.assertIn("Нет исполнимой E", markdown)


class CLITests(unittest.TestCase):
    def test_bytes_parsing_hash_and_explicit_synthetic_no_overwrite(self):
        with tempfile.TemporaryDirectory(prefix="cg_card_test_") as temp:
            root = Path(temp)
            source = root / "input.json"
            payload = json.dumps(sample_input()).encode()
            source.write_bytes(payload)
            args = ["--input", str(source), "--json-out", str(root / "out.json"), "--md-out", str(root / "out.md")]
            with self.assertRaises(SystemExit):
                sc.main(args)
            original_read = Path.read_bytes
            calls = []
            def read_once(path):
                calls.append(path)
                result = original_read(path)
                path.write_bytes(b"invalid mutation after read")
                return result
            with patch.object(Path, "read_bytes", read_once), patch("builtins.print"):
                self.assertEqual(sc.main(args + ["--synthetic"]), 0)
            self.assertEqual(calls, [source])
            card = json.loads((root / "out.json").read_text(encoding="utf-8"))
            self.assertEqual(card["input_sha256"], hashlib.sha256(payload).hexdigest())
            self.assertEqual(card["status"], "READY_RESEARCH")
            with self.assertRaises(SystemExit):
                sc.main(args + ["--synthetic"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
