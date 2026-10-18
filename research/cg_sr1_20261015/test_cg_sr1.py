"""Synthetic edge-case tests. No historical screenshot is used as a backtest."""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal as D
import json
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import cg_sr1 as cg

BASE = int(datetime(2026, 10, 16, tzinfo=timezone.utc).timestamp() * 1000)


def fixture():
    meta = {
        "schema_version": "cg-sr1-input-v0", "series_id": cg.SERIES,
        "collection_role": "prospective-forward-v2", "synthetic": True,
        "provider": "CoinGlass", "model": "model1", "exchange": "Binance",
        "symbol": "BTCUSDT", "instrument": "perpetual", "lookback": "24h", "threshold": "0.85",
        "data_as_of_ms": BASE + 800 * cg.MINUTE, "atr_seed_start_ms": BASE - 300 * cg.MINUTE,
        "price_source": {"exchange": "Binance", "symbol": "BTCUSDT", "instrument": "perpetual",
                         "interval": "1m", "timezone": "UTC", "closed_only": True},
        "contract": {"tick_size": "0.1", "quantity_step": "0.001", "verified": True,
                     "verification_source": "SYNTHETIC TEST CONTRACT; not current exchange specifications",
                     "verified_at_ms": BASE - 600 * cg.MINUTE},
    }
    snap = {"snapshot_id": "synthetic-A", "series_id": cg.SERIES, "synthetic": True,
            "slot_ms": BASE, "capture_ms": BASE, "annotation_lock_ms": BASE,
            "status": "frozen", "source_record_complete": True, "source_record_fresh": True,
            "settings_match": True, "annotation_frozen": True, "frozen_spot": "100",
            "lower_zone": {"low": "97", "high": "98"}, "upper_zone": {"low": "120", "high": "122"}}
    rows = [{"ts_ms": ts, "open": "100", "high": "100.2", "low": "99.8", "close": "100"}
            for ts in range(BASE - 300 * cg.MINUTE, BASE + 800 * cg.MINUTE, cg.MINUTE)]
    alter(rows, BASE + 15 * cg.MINUTE, low="96", high="101")
    return meta, [snap], rows


def alter(rows, ts, **changes):
    for row in rows:
        if row["ts_ms"] == ts:
            row.update(changes)
            return
    raise AssertionError(f"fixture minute not found: {ts}")


def run_case(meta=None, snapshots=None, rows=None):
    default = fixture()
    return cg.run_research(meta if meta is not None else default[0],
                           snapshots if snapshots is not None else default[1],
                           rows if rows is not None else default[2], synthetic=True)


def internal_candidate(sid="A", entry=None, freeze=None, deadline=None, side="LONG"):
    entry = BASE + 30 * cg.MINUTE if entry is None else entry
    return {"snapshot_id": sid, "freeze_ms": BASE if freeze is None else freeze,
            "entry_ms": entry, "deadline_ms": entry + 3 * cg.MINUTE if deadline is None else deadline,
            "status": "READY", "reasons": [], "side": side, "entry": D("100"),
            "stop": D("95") if side == "LONG" else D("105"),
            "target": D("120") if side == "LONG" else D("80"),
            "quantity": D("1"), "entry_notional": D("100")}


class TimingAndEligibilityTests(unittest.TestCase):
    def test_t0_strictly_after_later_capture_or_lock(self):
        self.assertEqual(cg.effective_t0(BASE, BASE), BASE + cg.MINUTE)
        self.assertEqual(cg.effective_t0(BASE + 10_000, BASE + cg.MINUTE), BASE + 2 * cg.MINUTE)
        self.assertEqual(cg.effective_t0(BASE + 2 * cg.MINUTE, BASE), BASE + 3 * cg.MINUTE)

    def test_only_full_utc15_signal_after_t0(self):
        meta, snaps, rows = fixture()
        alter(rows, BASE, low="95")  # partial-at-t0 00:00 candle cannot signal
        trade = run_case(meta, snaps, rows)["ledger_4bp"][0]
        self.assertEqual(trade["signal_start_ms"], BASE + 15 * cg.MINUTE)
        self.assertEqual(trade["entry_ms"], BASE + 30 * cg.MINUTE)
        self.assertEqual(trade["deadline_ms"], BASE + 241 * cg.MINUTE)

    def test_signal_close_at_deadline_is_not_eligible(self):
        meta, snaps, rows = fixture()
        snapshot = cg.normalize_snapshot(snaps[0], True)
        snapshot["deadline_ms"] = BASE + 30 * cg.MINUTE
        bars = cg.parse_bars(rows, meta["data_as_of_ms"], D("0.1"))
        bars15 = cg.aggregate_15m(bars)
        result = cg.first_candidate(snapshot, bars, bars15,
                                    cg.previous_atr14(bars15, meta["atr_seed_start_ms"]), D("0.1"), D("0.001"))
        self.assertEqual(result["reasons"], ["NO_RECLAIM_BEFORE_DEADLINE"])

    def test_real_and_synthetic_require_explicit_matching_markers(self):
        meta, snaps, rows = fixture()
        with self.assertRaises(cg.ValidationError):
            cg.run_research(meta, snaps, rows)
        meta["synthetic"] = False
        with self.assertRaises(cg.ValidationError):
            cg.run_research(meta, snaps, rows, synthetic=True)
        snaps[0]["synthetic"] = False
        report = cg.run_research(meta, snaps, rows)
        self.assertFalse(report["synthetic"])

    def test_manual_pilot_or_reference_series_refused(self):
        meta, snaps, rows = fixture()
        for series in ("manual-pilot", "reference", "CG-model1-Binance-BTCUSDT-24h-ui085-forward-v1"):
            bad = deepcopy(meta)
            bad["series_id"] = series
            with self.assertRaises(cg.ValidationError):
                run_case(bad, snaps, rows)
        snaps[0]["series_id"] = "reference"
        with self.assertRaises(cg.ValidationError):
            run_case(meta, snaps, rows)

    def test_freeze_outside_window_and_source_reasons_retained(self):
        meta, snaps, rows = fixture()
        snaps[0].update(annotation_lock_ms=BASE + 120_001, source_record_complete=False, source_record_fresh=False)
        report = run_case(meta, snaps, rows)
        self.assertEqual(report["entered_count"], 0)
        for reason in ("FREEZE_OUTSIDE_SLOT_WINDOW", "SOURCE_INCOMPLETE", "SOURCE_NOT_FRESH"):
            self.assertEqual(report["reason_counts"][reason], 1)

    def test_first_admissible_freeze_wins_slot_with_id_tie_break(self):
        meta, snaps, rows = fixture()
        later = deepcopy(snaps[0]); later.update(snapshot_id="synthetic-B", capture_ms=BASE + cg.MINUTE)
        tied = deepcopy(snaps[0]); tied["snapshot_id"] = "synthetic-0"
        report = run_case(meta, [later, snaps[0], tied], rows)
        self.assertEqual(report["ledger_4bp"][0]["snapshot_id"], "synthetic-0")
        self.assertEqual(report["reason_counts"]["LATER_FREEZE_FOR_SLOT"], 2)

    def test_missed_attempt_preserved_and_duplicate_ids_rejected(self):
        meta, snaps, rows = fixture()
        missed = {"snapshot_id": "missed", "series_id": cg.SERIES, "synthetic": True,
                  "slot_ms": BASE + cg.SLOT, "status": "missed", "reason": "synthetic capture unavailable"}
        report = run_case(meta, snaps + [missed], rows)
        self.assertEqual(report["reason_counts"]["OBSERVATION_MISSED"], 1)
        with self.assertRaises(cg.ValidationError):
            run_case(meta, snaps + snaps, rows)

    def test_unclosed_duplicate_or_off_grid_price_rejected(self):
        meta, snaps, rows = fixture()
        bad = deepcopy(rows); bad[-1]["ts_ms"] = meta["data_as_of_ms"]
        with self.assertRaises(cg.ValidationError):
            run_case(meta, snaps, bad)
        with self.assertRaises(cg.ValidationError):
            run_case(meta, snaps, rows[:1] + rows)
        bad = deepcopy(rows); bad[0]["open"] = "100.01"
        with self.assertRaises(cg.ValidationError):
            run_case(meta, snaps, bad)

    def test_freeze_after_as_of_and_late_contract_declaration_refused(self):
        meta, snaps, rows = fixture()
        meta["data_as_of_ms"] = BASE - cg.MINUTE
        rows = [r for r in rows if r["ts_ms"] + cg.MINUTE <= meta["data_as_of_ms"]]
        report = run_case(meta, snaps, rows)
        self.assertEqual(report["snapshots"][0]["reasons"], ["OBSERVATION_AFTER_DATA_AS_OF", "FREEZE_AFTER_DATA_AS_OF"])
        meta, snaps, rows = fixture()
        meta["contract"]["verified_at_ms"] = BASE + 31 * cg.MINUTE
        report = run_case(meta, snaps, rows)
        self.assertEqual(report["snapshots"][0]["reasons"], ["CONTRACT_RULES_NOT_AVAILABLE_AT_ENTRY"])
        meta["contract"]["verified_at_ms"] = meta["data_as_of_ms"] + 1
        with self.assertRaises(cg.ValidationError):
            run_case(meta, snaps, rows)

    def test_unmature_episode_pending_not_missing_or_portfolio_unknown(self):
        meta, snaps, rows = fixture()
        meta["data_as_of_ms"] = BASE + 10 * cg.MINUTE  # before first eligible signal
        rows = [row for row in rows if row["ts_ms"] + cg.MINUTE <= meta["data_as_of_ms"]]
        report = run_case(meta, snaps, rows)
        self.assertEqual(report["snapshots"][0]["status"], "PENDING")
        self.assertEqual(report["pending_count"], 1)
        self.assertEqual(report["entered_count"], 0)
        self.assertEqual(report["censored_count"], 0)
        self.assertEqual(report["reason_counts"], {"EPISODE_NOT_MATURE": 1})

    def test_maturity_exact_boundary_then_historical_gap_is_censored(self):
        meta, snaps, rows = fixture()
        deadline = BASE + 241 * cg.MINUTE
        meta["data_as_of_ms"] = deadline + cg.MINUTE - 1
        prefix = [row for row in rows if row["ts_ms"] + cg.MINUTE <= meta["data_as_of_ms"]]
        self.assertEqual(run_case(meta, snaps, prefix)["pending_count"], 1)
        meta["data_as_of_ms"] = deadline + cg.MINUTE
        prefix = [row for row in rows if row["ts_ms"] + cg.MINUTE <= meta["data_as_of_ms"]]
        self.assertEqual(run_case(meta, snaps, prefix)["closed_count"], 1)
        prefix = [row for row in prefix if row["ts_ms"] != BASE + 31 * cg.MINUTE]
        report = run_case(meta, snaps, prefix)
        self.assertEqual(report["censored_count"], 1)
        self.assertEqual(report["pending_count"], 0)
        self.assertEqual(report["reason_counts"], {"MISSING_EXIT_PATH": 1})


class ATRAndCandidateTests(unittest.TestCase):
    def test_atr_requires_14_tr_with_real_previous_close(self):
        bars = {i * cg.M15: cg.Bar(i * cg.M15, D(100), D(101), D(99), D(100)) for i in range(15)}
        short = cg.previous_atr14(dict(list(bars.items())[:14]), 0)
        self.assertEqual(short, {})
        atr = cg.previous_atr14(bars, 0)
        self.assertEqual(atr, {15 * cg.M15: D(2)})

    def test_wilder_uses_gap_from_actual_previous_close(self):
        bars = {i * cg.M15: cg.Bar(i * cg.M15, D(100), D(101), D(99), D(100)) for i in range(15)}
        bars[15 * cg.M15] = cg.Bar(15 * cg.M15, D(110), D(111), D(109), D(110))
        atr = cg.previous_atr14(bars, 0)
        self.assertEqual(atr[16 * cg.M15], (D(13) * 2 + 11) / 14)

    def test_gap_breaks_fixed_atr_seed_no_silent_reseed(self):
        bars = {i * cg.M15: cg.Bar(i * cg.M15, D(100), D(101), D(99), D(100)) for i in range(40)}
        del bars[3 * cg.M15]
        self.assertEqual(cg.previous_atr14(bars, 0), {})

    def test_signal_and_future_extrema_do_not_enter_previous_atr(self):
        meta, snaps, rows = fixture()
        original = run_case(meta, snaps, rows)["ledger_4bp"][0]
        alter(rows, BASE + 16 * cg.MINUTE, low="80")
        alter(rows, BASE + 31 * cg.MINUTE, high="1000")
        changed = run_case(meta, snaps, rows)["snapshots"][0]
        self.assertEqual(original["previous_atr14"], changed["previous_atr14"])
        self.assertEqual(D(changed["previous_atr14"]), D("0.4"))

    def test_stop_rounded_outward_and_short_mirror(self):
        report = run_case()
        long = report["ledger_4bp"][0]
        self.assertEqual(D(long["stop_unrounded"]), D("95.96"))
        self.assertEqual(D(long["stop"]), D("95.9"))
        meta, snaps, rows = fixture()
        snaps[0]["lower_zone"] = {"low": "75", "high": "78"}
        snaps[0]["upper_zone"] = {"low": "102", "high": "103"}
        alter(rows, BASE + 15 * cg.MINUTE, low="99.8", high="104")
        short = run_case(meta, snaps, rows)["ledger_4bp"][0]
        self.assertEqual(short["side"], "SHORT")
        self.assertEqual(D(short["stop"]), D("104.1"))
        self.assertEqual(D(short["target"]), D("78"))

    def test_both_frozen_zones_consumes_snapshot(self):
        meta, snaps, rows = fixture()
        alter(rows, BASE + 15 * cg.MINUTE, high="121")
        alter(rows, BASE + 45 * cg.MINUTE, low="96")
        report = run_case(meta, snaps, rows)
        self.assertEqual(report["entered_count"], 0)
        self.assertEqual(report["snapshots"][0]["reasons"], ["BOTH_ZONES_IN_SIGNAL_BAR"])

    def test_first_reclaim_cancel_does_not_retry_later(self):
        meta, snaps, rows = fixture()
        alter(rows, BASE + 30 * cg.MINUTE, open="110", high="110", low="100", close="100")
        alter(rows, BASE + 45 * cg.MINUTE, low="96")
        report = run_case(meta, snaps, rows)
        self.assertEqual(report["entered_count"], 0)
        self.assertEqual(report["snapshots"][0]["entry_ms"], BASE + 30 * cg.MINUTE)
        self.assertEqual(report["snapshots"][0]["reasons"], ["NET_RR_BELOW_2"])

    def test_signed_geometry_rejects_entry_beyond_stop_or_target(self):
        for entry in ("94", "120", "130"):
            meta, snaps, rows = fixture()
            alter(rows, BASE + 30 * cg.MINUTE, open=entry, high=str(max(D(entry), D(100))), low=str(min(D(entry), D(100))))
            report = run_case(meta, snaps, rows)
            self.assertEqual(report["snapshots"][0]["reasons"], ["INVALID_SIGNED_TRADE_GEOMETRY"])

    def test_strict_reclaim_requires_pierce_and_close_beyond(self):
        for low, close in (("97", "100"), ("96", "98")):
            meta, snaps, rows = fixture()
            alter(rows, BASE + 15 * cg.MINUTE, low=low)
            alter(rows, BASE + 29 * cg.MINUTE, close=close, low=min(close, "99.8", key=D))
            report = run_case(meta, snaps, rows)
            self.assertEqual(report["entered_count"], 0)
            self.assertEqual(report["snapshots"][0]["reasons"], ["NO_RECLAIM_BEFORE_DEADLINE"])

    def test_missing_signal_entry_or_atr_never_late_fills(self):
        for remove_ts, reason in ((BASE + 16 * cg.MINUTE, "MISSING_SIGNAL_DATA"),
                                  (BASE + 30 * cg.MINUTE, "MISSING_ENTRY_OPEN"),
                                  (BASE - cg.MINUTE, "MISSING_PREVIOUS_ATR14")):
            meta, snaps, rows = fixture()
            rows = [row for row in rows if row["ts_ms"] != remove_ts]
            report = run_case(meta, snaps, rows)
            self.assertEqual(report["entered_count"], 0)
            self.assertEqual(report["snapshots"][0]["reasons"], [reason])

    def test_fixed_reserve_size_cap_floor_and_same_q_for_both_ledgers(self):
        report = run_case()
        a, b = report["ledger_4bp"][0], report["ledger_8bp"][0]
        self.assertEqual(a["quantity"], b["quantity"])
        self.assertEqual(D(a["quantity"]), cg.floor_step(D(25) / (D("4.1") + D("0.08")), D("0.001")))
        self.assertLessEqual(D(a["planned_loss_including_reserve"]), D(25))
        self.assertLessEqual(D(a["entry_notional"]), D(10000))
        self.assertEqual(D(a["net"]), D(a["raw_gross"]) - D(a["entry_notional"]) * D("0.0004"))
        self.assertEqual(D(b["net"]), D(b["raw_gross"]) - D(b["entry_notional"]) * D("0.0008"))

    def test_rr_exactly_two_accepted_just_below_refused(self):
        for target, accepted in (("108.32", True), ("108.31", False)):
            meta, snaps, rows = fixture()
            meta["contract"]["tick_size"] = "0.01"
            snaps[0]["upper_zone"] = {"low": target, "high": "109"}
            report = run_case(meta, snaps, rows)
            self.assertEqual(report["entered_count"], int(accepted))
            if accepted:
                self.assertEqual(D(report["snapshots"][0]["net_rr_reserve8bp"]), D(2))
            else:
                self.assertEqual(report["snapshots"][0]["reasons"], ["NET_RR_BELOW_2"])

    def test_notional_cap_and_zero_rounding(self):
        meta, snaps, rows = fixture()
        meta["contract"]["tick_size"] = "0.01"
        snaps[0]["lower_zone"] = {"low": "99.95", "high": "99.97"}
        for row in rows:
            row.update(high="100.02", low="99.98")
        alter(rows, BASE + 15 * cg.MINUTE, low="99.9")
        report = run_case(meta, snaps, rows)
        self.assertEqual(D(report["ledger_4bp"][0]["entry_notional"]), D(10000))
        meta["contract"]["quantity_step"] = "1000"
        report = run_case(meta, snaps, rows)
        self.assertEqual(report["snapshots"][0]["reasons"], ["QUANTITY_ROUNDED_TO_ZERO"])


class ExitAndPortfolioTests(unittest.TestCase):
    def bars(self, rows=None):
        meta, _, default = fixture()
        return cg.parse_bars(default if rows is None else rows, meta["data_as_of_ms"], D("0.1"))

    def test_same_minute_stop_and_target_worst_case_both_sides(self):
        for side in ("LONG", "SHORT"):
            _, _, rows = fixture()
            trade = internal_candidate(side=side)
            alter(rows, trade["entry_ms"], high="125", low="75")
            outcome = cg.simulate_exit(trade, self.bars(rows))
            self.assertEqual(outcome["exit_reason"], "STOP_BOTH_TOUCHED")
            self.assertEqual(outcome["exit"], trade["stop"])

    def test_known_open_target_precedes_unknown_low_or_high(self):
        for side, opening, high, low in (("LONG", "125", "130", "80"), ("SHORT", "75", "120", "70")):
            _, _, rows = fixture()
            trade = internal_candidate(side=side)
            ts = trade["entry_ms"] + cg.MINUTE
            alter(rows, ts, open=opening, high=high, low=low)
            outcome = cg.simulate_exit(trade, self.bars(rows))
            self.assertEqual(outcome["exit_reason"], "TARGET_GAP_OPEN_CAPPED")
            self.assertEqual(outcome["exit"], trade["target"])

    def test_stop_gap_fills_at_open_can_exceed_budget(self):
        _, _, rows = fixture()
        trade = internal_candidate()
        alter(rows, trade["entry_ms"] + cg.MINUTE, open="80", high="101", low="79")
        outcome = cg.simulate_exit(trade, self.bars(rows))
        self.assertEqual(outcome["exit_reason"], "STOP_GAP_OPEN")
        self.assertEqual(outcome["exit"], D(80))

    def test_exact_non15m_deadline_open(self):
        meta, snaps, rows = fixture()
        deadline = BASE + 241 * cg.MINUTE
        alter(rows, deadline, open="105", high="125", low="80")
        trade = run_case(meta, snaps, rows)["ledger_4bp"][0]
        self.assertEqual(trade["exit_ms"], deadline)
        self.assertEqual(trade["exit_reason"], "DEADLINE")
        self.assertEqual(D(trade["exit"]), D(105))

    def test_deadline_open_preserves_target_cap_both_sides(self):
        for side, opening, high, low in (("LONG", "125", "130", "80"), ("SHORT", "75", "120", "70")):
            _, _, rows = fixture()
            trade = internal_candidate(side=side)
            alter(rows, trade["deadline_ms"], open=opening, high=high, low=low)
            outcome = cg.simulate_exit(trade, self.bars(rows))
            self.assertEqual(outcome["exit_ms"], trade["deadline_ms"])
            self.assertEqual(outcome["exit_reason"], "TARGET_GAP_OPEN_CAPPED")
            self.assertEqual(outcome["exit"], trade["target"])

    def test_deadline_stop_gap_fills_open_both_sides(self):
        for side, opening, high, low in (("LONG", "80", "130", "75"), ("SHORT", "125", "130", "70")):
            _, _, rows = fixture()
            trade = internal_candidate(side=side)
            alter(rows, trade["deadline_ms"], open=opening, high=high, low=low)
            outcome = cg.simulate_exit(trade, self.bars(rows))
            self.assertEqual(outcome["exit_ms"], trade["deadline_ms"])
            self.assertEqual(outcome["exit_reason"], "STOP_GAP_OPEN")
            self.assertEqual(outcome["exit"], D(opening))

    def test_missing_deadline_open_is_censored_not_later_open(self):
        meta, snaps, rows = fixture()
        deadline = BASE + 241 * cg.MINUTE
        rows = [r for r in rows if r["ts_ms"] != deadline]
        alter(rows, deadline + cg.MINUTE, open="110", high="110")
        trade = run_case(meta, snaps, rows)["ledger_4bp"][0]
        self.assertEqual(trade["status"], "CENSORED")
        self.assertEqual(trade["reasons"], ["MISSING_DEADLINE_OPEN"])
        self.assertIsNone(trade["exit"])
        self.assertIsNone(trade["net"])

    def test_missing_path_cannot_infer_later_known_target(self):
        meta, snaps, rows = fixture()
        missing = BASE + 31 * cg.MINUTE
        rows = [r for r in rows if r["ts_ms"] != missing]
        alter(rows, missing + cg.MINUTE, high="125")
        trade = run_case(meta, snaps, rows)["ledger_4bp"][0]
        self.assertEqual(trade["reasons"], ["MISSING_EXIT_PATH"])
        self.assertIsNone(trade["exit"])

    def test_earlier_known_exit_survives_later_missing_minute(self):
        meta, snaps, rows = fixture()
        alter(rows, BASE + 30 * cg.MINUTE, high="120")
        rows = [r for r in rows if r["ts_ms"] != BASE + 31 * cg.MINUTE]
        trade = run_case(meta, snaps, rows)["ledger_4bp"][0]
        self.assertEqual(trade["exit_reason"], "TARGET")

    def test_no_reentry_after_first_trade_exits(self):
        meta, snaps, rows = fixture()
        alter(rows, BASE + 30 * cg.MINUTE, high="120")
        alter(rows, BASE + 45 * cg.MINUTE, low="96")
        report = run_case(meta, snaps, rows)
        self.assertEqual(report["entered_count"], 1)
        self.assertEqual(report["ledger_4bp"][0]["entry_ms"], BASE + 30 * cg.MINUTE)

    def test_portfolio_busy_consumes_no_delayed_retry(self):
        first = internal_candidate("A")
        second = internal_candidate("B", entry=first["entry_ms"] + cg.MINUTE, freeze=BASE + 1)
        candidates = [second, first]
        ledger = cg.apply_portfolio(candidates, self.bars())
        self.assertEqual([r["snapshot_id"] for r in ledger], ["A"])
        self.assertEqual(second["reasons"], ["PORTFOLIO_BUSY"])

    def test_portfolio_priority_freeze_then_immutable_id(self):
        a = internal_candidate("A", freeze=BASE + 1)
        b = internal_candidate("B", freeze=BASE)
        c = internal_candidate("0", freeze=BASE)
        ledger = cg.apply_portfolio([a, b, c], self.bars())
        self.assertEqual([r["snapshot_id"] for r in ledger], ["0"])

    def test_open_exit_releases_at_open_intrabar_exit_only_next_minute(self):
        first = internal_candidate("A")
        second = internal_candidate("B", entry=first["entry_ms"] + cg.MINUTE)
        _, _, rows = fixture()
        alter(rows, second["entry_ms"], high="125")
        ledger = cg.apply_portfolio([first, second], self.bars(rows))
        self.assertEqual(len(ledger), 1)
        self.assertEqual(second["reasons"], ["PORTFOLIO_BUSY"])
        first, second = internal_candidate("A"), internal_candidate("B", entry=first["entry_ms"] + cg.MINUTE)
        alter(rows, second["entry_ms"], open="125", high="125", low="99.8")
        ledger = cg.apply_portfolio([first, second], self.bars(rows))
        self.assertEqual(len(ledger), 2)

    def test_censored_position_blocks_future_unknown_capacity(self):
        a = internal_candidate("A")
        b = internal_candidate("B", entry=a["entry_ms"] + 10 * cg.MINUTE)
        bars = self.bars(); del bars[a["entry_ms"] + cg.MINUTE]
        ledger = cg.apply_portfolio([a, b], bars)
        self.assertEqual(len(ledger), 1)
        self.assertEqual(b["reasons"], ["PORTFOLIO_STATE_UNKNOWN"])

    def test_pure_function_does_not_mutate_inputs_and_file_order_irrelevant(self):
        meta, snaps, rows = fixture()
        before = deepcopy((meta, snaps, rows))
        first = run_case(meta, snaps, rows)
        second = run_case(meta, reversed(snaps), rows)
        self.assertEqual(first, second)
        self.assertEqual((meta, snaps, rows), before)


class CLITests(unittest.TestCase):
    def test_cli_parses_and_hashes_same_single_read_bytes_despite_source_mutation(self):
        meta, snaps, rows = fixture()
        import csv
        with tempfile.TemporaryDirectory(prefix="cg_sr1_bytes_test_") as temp:
            root = Path(temp)
            (root / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
            (root / "snapshots.json").write_text(json.dumps(snaps), encoding="utf-8")
            with (root / "prices.csv").open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["ts_ms", "open", "high", "low", "close"])
                writer.writeheader()
                writer.writerows(rows)
            original_read = Path.read_bytes
            captured, calls = {}, {}

            def read_once(path):
                name = path.name
                calls[name] = calls.get(name, 0) + 1
                if calls[name] != 1:
                    raise AssertionError("input read more than once")
                payload = original_read(path)
                captured[name] = payload
                if name == "prices.csv":
                    # External mutation after the read must affect neither the
                    # parsed rows nor the digest attached to this calculation.
                    path.write_text("mutated source,not the captured input\n", encoding="utf-8")
                return payload

            argv = ["--metadata", str(root / "metadata.json"), "--snapshots", str(root / "snapshots.json"),
                    "--prices", str(root / "prices.csv"), "--output", str(root / "report.json"), "--synthetic"]
            with patch.object(Path, "read_bytes", read_once), \
                 patch.object(Path, "read_text", side_effect=AssertionError("input must be parsed from captured bytes")), \
                 patch("builtins.print"):
                self.assertEqual(cg.main(argv), 0)
            self.assertEqual(calls, {"metadata.json": 1, "snapshots.json": 1, "prices.csv": 1})
            report = json.loads((root / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["entered_count"], 1)
            self.assertEqual(report["input_sha256"], {
                name: hashlib.sha256(captured[filename]).hexdigest()
                for name, filename in (("metadata", "metadata.json"), ("snapshots", "snapshots.json"), ("prices", "prices.csv"))})
            self.assertNotEqual(report["input_sha256"]["prices"], hashlib.sha256(original_read(root / "prices.csv")).hexdigest())

    def test_cli_needs_synthetic_flag_and_does_not_overwrite(self):
        meta, snaps, rows = fixture()
        import csv
        with tempfile.TemporaryDirectory(prefix="cg_sr1_test_") as temp:
            root = Path(temp)
            (root / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
            (root / "snapshots.json").write_text(json.dumps(snaps), encoding="utf-8")
            with (root / "prices.csv").open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["ts_ms", "open", "high", "low", "close"])
                writer.writeheader(); writer.writerows(rows)
            command = [sys.executable, str(Path(cg.__file__)), "--metadata", str(root / "metadata.json"),
                       "--snapshots", str(root / "snapshots.json"), "--prices", str(root / "prices.csv"),
                       "--output", str(root / "report.json")]
            bad = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(bad.returncode, 2)
            self.assertFalse((root / "report.json").exists())
            good = subprocess.run(command + ["--synthetic"], capture_output=True, text=True)
            self.assertEqual(good.returncode, 0, good.stderr)
            report = json.loads((root / "report.json").read_text(encoding="utf-8"))
            self.assertTrue(report["synthetic"])
            self.assertEqual(len(report["input_sha256"]), 3)
            repeat = subprocess.run(command + ["--synthetic"], capture_output=True, text=True)
            self.assertEqual(repeat.returncode, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
