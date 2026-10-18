"""Offline synthetic transport tests: these tests never open a network socket."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import tempfile
import stat
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import fetch_public_context as fetch

BASE = int(datetime(2026, 10, 16, 12, tzinfo=timezone.utc).timestamp() * 1000)
SERVER = BASE + 123_456
START = BASE - fetch.DAY


def klines():
    return [[ts, "100", "101", "99", "100", "10", ts + fetch.STEP - 1, "1000", 12, "7", "700", "0"]
            for ts in range(START, BASE, fetch.STEP)]


def oi():
    return [{"symbol": "BTCUSDT", "timestamp": ts, "sumOpenInterest": "12.5", "sumOpenInterestValue": "1250"}
            for ts in range(START, BASE + fetch.STEP, fetch.STEP)]


def funding():
    return [{"symbol": "BTCUSDT", "fundingTime": BASE - 8 * 3_600_000, "fundingRate": "-0.0001", "markPrice": "100", "rateType": "Regular"}]


def premium():
    return {"symbol": "BTCUSDT", "time": SERVER, "markPrice": "100", "indexPrice": "99.9",
            "lastFundingRate": "0.0001", "nextFundingTime": BASE + 8 * 3_600_000}


class FakeClock:
    def __init__(self):
        self.value = SERVER + 100

    def __call__(self):
        self.value += 1
        return self.value


class FakeClient:
    def __init__(self, overrides=None):
        self.urls = []
        self.overrides = overrides or {}

    def get(self, target):
        self.urls.append(target)
        path = urlsplit(target).path
        value = self.overrides.get(path)
        if value is None:
            value = {"/fapi/v1/time": {"serverTime": SERVER}, "/api/v3/klines": klines(),
                     "/fapi/v1/klines": klines(), "/futures/data/openInterestHist": oi(),
                     "/fapi/v1/fundingRate": funding(), "/fapi/v1/premiumIndex": premium()}[path]
        if isinstance(value, Exception):
            raise value
        if isinstance(value, fetch.Reply):
            return value
        return fetch.Reply(200, json.dumps(value).encode())


def collect(client=None, premium=False):
    return fetch.collect_context(client or FakeClient(), include_premium=premium, clock=FakeClock(), synthetic=True)


def by_id(fragment, sid):
    return next(source for source in fragment["sources"] if source["id"] == sid)


class ParserTests(unittest.TestCase):
    def test_96_closed_UTC_bars_delta_true_taker_and_units(self):
        rows, flags, details, event = fetch.parse_klines(klines(), START, BASE, SERVER)
        self.assertEqual(len(rows), 96)
        self.assertEqual(flags, [])
        self.assertEqual(details["missing_timestamps"], [])
        self.assertEqual(event, BASE)
        self.assertEqual(rows[-1]["provider_close_time_ms"], BASE - 1)
        self.assertEqual(Decimal(rows[-1]["delta_base"]), Decimal(4))
        self.assertEqual(Decimal(rows[-1]["F"]), Decimal("0.4"))
        self.assertEqual(Decimal(rows[-1]["buy_share"]), Decimal("0.7"))
        self.assertEqual(Decimal(rows[-1]["sell_share"]), Decimal("0.3"))

    def test_zero_volume_shares_null_no_missing_zero_substitution(self):
        data = klines()
        for index in (5, 7, 9, 10):
            data[0][index] = "0"
        rows, flags, _, _ = fetch.parse_klines(data, START, BASE, SERVER)
        self.assertIsNone(rows[0]["F"])
        self.assertIsNone(rows[0]["buy_share"])
        self.assertIsNone(rows[0]["sell_share"])
        self.assertEqual(rows[0]["delta_base"], "0")  # actual derived zero, not a missing value
        self.assertIn("zero_volume_F_and_shares_null", flags)

    def test_forming_bar_excluded_not_mislabeled_closed(self):
        data = klines() + [[BASE, "100", "101", "99", "100", "10", BASE + fetch.STEP - 1, "1000", 1, "7", "700", "0"]]
        rows, flags, details, _ = fetch.parse_klines(data, START, BASE, SERVER)
        self.assertEqual(len(rows), 96)
        self.assertIn("rows_rejected_or_ambiguous", flags)
        self.assertIn("forming_or_out_of_requested_closed_window", details["rejected_rows"][0]["reason"])

    def test_bar_closes_exactly_at_clock_boundary_is_closed(self):
        rows, flags, _, _ = fetch.parse_klines(klines(), START, BASE, BASE)
        self.assertEqual(len(rows), 96)
        self.assertEqual(flags, [])

    def test_grid_gap_and_duplicate_all_copies_excluded(self):
        data = klines(); duplicate = deepcopy(data[5]); data.append(duplicate); data.pop(2)
        rows, flags, details, _ = fetch.parse_klines(data, START, BASE, SERVER)
        self.assertEqual(len(rows), 94)
        self.assertEqual(len(details["missing_timestamps"]), 2)
        self.assertIn("rows_rejected_or_ambiguous", flags)
        self.assertNotIn(duplicate[0], [row["bar_start_ms"] for row in rows])

    def test_out_of_order_kept_sorted_but_quality_warning_preserved(self):
        data = klines(); data[0], data[1] = data[1], data[0]
        rows, flags, _, _ = fetch.parse_klines(data, START, BASE, SERVER)
        self.assertEqual(len(rows), 96)
        self.assertIn("response_out_of_order", flags)
        self.assertEqual(rows[0]["bar_start_ms"], START)

    def test_bad_prices_volumes_time_and_NaN_are_rejected_with_reasons(self):
        for field, bad in ((2, "98"), (5, "-1"), (9, "11"), (10, "1001"), (1, "NaN"), (6, BASE), (0, START + 1)):
            data = klines(); data[0][field] = bad
            rows, flags, details, _ = fetch.parse_klines(data, START, BASE, SERVER)
            self.assertEqual(len(rows), 95)
            self.assertEqual(len(details["rejected_rows"]), 1)
            self.assertIn("missing_expected_grid_points", flags)

    def test_error_object_is_not_market_data(self):
        with self.assertRaises(ValueError):
            fetch.parse_klines({"code": -1, "msg": "error"}, START, BASE, SERVER)

    def test_oi97_preserves_quantity_vs_value_and_missing_end(self):
        rows, flags, _, event = fetch.parse_oi(oi(), START, BASE)
        self.assertEqual(len(rows), 97)
        self.assertEqual(flags, [])
        self.assertEqual(event, BASE)
        self.assertEqual(rows[0]["sum_open_interest"], "12.5")
        self.assertEqual(rows[0]["sum_open_interest_value"], "1250")
        self.assertIsNone(rows[0]["historical_received_ms"])
        rows, flags, details, event = fetch.parse_oi(oi()[:-1], START, BASE)
        self.assertEqual(len(rows), 96)
        self.assertEqual(details["missing_timestamps"], [BASE])
        self.assertEqual(event, BASE - fetch.STEP)

    def test_oi_wrong_symbol_negative_or_duplicate_never_arbitrarily_selected(self):
        for key, bad in (("symbol", "ETHUSDT"), ("sumOpenInterest", "-1"), ("timestamp", START + 1)):
            data = oi(); data[0][key] = bad
            rows, _, details, _ = fetch.parse_oi(data, START, BASE)
            self.assertEqual(len(rows), 96)
            self.assertEqual(len(details["missing_timestamps"]), 1)
        data = oi() + [deepcopy(oi()[0])]
        self.assertEqual(len(fetch.parse_oi(data, START, BASE)[0]), 96)

    def test_funding_signed_fraction_and_regular_special_same_time(self):
        data = funding(); data.append(dict(data[0], rateType="Special", fundingRate="0.0002"))
        rows, flags, _, _ = fetch.parse_funding(data, SERVER - fetch.DAY, SERVER)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["funding_rate_fraction"], "-0.0001")
        self.assertIn("settlement_interval_not_assumed", flags)

    def test_empty_funding_is_not_zero_fee_missing_mark_stays_null(self):
        rows, flags, _, _ = fetch.parse_funding([], SERVER - fetch.DAY, SERVER)
        self.assertEqual(rows, [])
        self.assertIn("no_observed_funding_events_not_zero_cost", flags)
        data = funding(); data[0].pop("markPrice")
        rows, flags, _, _ = fetch.parse_funding(data, SERVER - fetch.DAY, SERVER)
        self.assertIsNone(rows[0]["mark_price_USDT"])
        self.assertIn("funding_mark_price_missing", flags)

    def test_premium_is_current_not_closed_or_executable(self):
        rows, flags, _, event = fetch.parse_premium(premium())
        self.assertEqual(rows[0]["mark_price_USDT"], "100")
        self.assertEqual(event, SERVER)
        self.assertIn("current_snapshot_not_closed_bar_not_executable_quote", flags)


class FiniteCollectionTests(unittest.TestCase):
    def test_5_or_6_gets_fixed_windows_no_primary_labels(self):
        for include, expected in ((False, 5), (True, 6)):
            client = FakeClient(); fragment, evidence = collect(client, include)
            self.assertEqual(len(client.urls), expected)
            self.assertEqual(fragment["fetch_summary"]["attempted_GETs"], expected)
            self.assertFalse(fragment["order_permission"])
            self.assertFalse(fragment["trade_primary"])
            spot = next(target for target in client.urls if "/api/v3/klines?" in target)
            query = parse_qs(urlsplit(spot).query)
            self.assertEqual(query["startTime"], [str(START)])
            self.assertEqual(query["endTime"], [str(BASE - 1)])
            self.assertEqual(query["limit"], ["96"])
            self.assertEqual(len(evidence), expected * 2)

    def test_actual_request_receive_and_provider_event_are_separate(self):
        fragment, _ = collect()
        source = by_id(fragment, "binance_perp_15m")
        audit = source["settings"]["request"]
        self.assertLess(audit["requested_at_ms"], audit["received_at_ms"])
        self.assertNotEqual(source["event_asof_ms"], audit["received_at_ms"])
        self.assertEqual(source["lag_status"], "unknown")
        self.assertIsNone(source["provider_lag_ms"])
        self.assertIsNone(audit["provider_lag_ms"])

    def test_failed_request_does_not_retry_or_hide_other_sources(self):
        client = FakeClient({"/api/v3/klines": fetch.Reply(429, b'{"code": -1003}', "HTTP_429")})
        fragment, evidence = collect(client, True)
        failed = by_id(fragment, "binance_spot_15m")
        self.assertEqual(failed["status"], "FAILED")
        self.assertIsNone(failed["values"])
        self.assertIn("request_failed", failed["quality_flags"])
        self.assertEqual(len(client.urls), 6)
        self.assertEqual(by_id(fragment, "binance_perp_15m")["status"], "OK")
        self.assertEqual(evidence[failed["evidence"][0]["path"]], b'{"code": -1003}')

    def test_bad_clock_prevents_market_requests_not_local_backdating(self):
        for value in (fetch.Reply(None, b"", "timeout"), {"serverTime": 0}):
            client = FakeClient({"/fapi/v1/time": value})
            fragment, _ = collect(client, True)
            self.assertEqual(len(client.urls), 1)
            self.assertEqual(len(fragment["sources"]), 6)
            self.assertEqual(fragment["sources"][0]["status"], "FAILED")
            self.assertTrue(all(source["status"] == "MISSING" for source in fragment["sources"][1:]))
            self.assertTrue(all(source["values"] is None for source in fragment["sources"][1:]))

    def test_malformed_http200_and_timeout_are_kept_failed(self):
        client = FakeClient({"/api/v3/klines": fetch.Reply(200, b"<html>not data</html>"),
                             "/fapi/v1/klines": TimeoutError("synthetic timeout")})
        fragment, evidence = collect(client)
        spot, perp = by_id(fragment, "binance_spot_15m"), by_id(fragment, "binance_perp_15m")
        self.assertEqual(spot["status"], "FAILED")
        self.assertEqual(perp["status"], "FAILED")
        self.assertTrue(spot["evidence"][0]["path"].endswith(".raw.body"))
        self.assertTrue(any("synthetic timeout" in body.decode() for key, body in evidence.items() if key.endswith("request.json")))

    def test_gap_response_is_partial_with_usable_rows_and_no_fill(self):
        client = FakeClient({"/api/v3/klines": klines()[1:]})
        fragment, _ = collect(client)
        source = by_id(fragment, "binance_spot_15m")
        self.assertEqual(source["status"], "PARTIAL")
        self.assertEqual(len(source["values"][0]["value"]), 95)
        self.assertEqual(source["settings"]["validation"]["missing_timestamps"], [START])

    def test_existing_preflight_evidence_kept_fragment_schema_compatible(self):
        fragment, evidence = collect()
        import archive_daily
        with tempfile.TemporaryDirectory(prefix="finite_public_test_") as temp:
            outdir = Path(temp)
            (outdir / "evidence").mkdir()
            (outdir / "evidence" / "existing_site.txt").write_text("unchanged", encoding="utf-8")
            target = fetch.write_fragment(outdir, fragment, evidence)
            self.assertEqual(json.loads(target.read_text())["schema"], "daily-as-seen-v1")
            # Scope here is structural compatibility, not a test of timezone logic.
            with patch.object(archive_daily, "warsaw", return_value=timezone(timedelta(hours=2))):
                report, copies = archive_daily.build_report(fragment, fragment["finished_at_ms"] + 1, outdir)
            self.assertEqual(len(report["sources"]), 5)
            self.assertEqual(len(copies), 10)
            self.assertFalse(report["order_permission"])
            self.assertEqual((outdir / "evidence" / "existing_site.txt").read_text(), "unchanged")
            for source in fragment["sources"]:
                for item in source["evidence"]:
                    self.assertEqual(hashlib.sha256((outdir / item["path"]).read_bytes()).hexdigest(), item["sha256"])
            with self.assertRaises(ValueError):
                fetch.write_fragment(outdir, fragment, evidence)

    def test_no_network_without_explicit_flag_or_if_fragment_exists(self):
        with tempfile.TemporaryDirectory(prefix="finite_public_cli_") as temp, patch.object(fetch, "PublicClient") as client:
            with self.assertRaises(SystemExit):
                fetch.main(["--outdir", temp])
            client.assert_not_called()
            (Path(temp) / "public_sources.json").write_text("{}")
            with self.assertRaises(SystemExit):
                fetch.main(["--outdir", temp, "--run-network"])
            client.assert_not_called()

    def test_http_client_allowlist_budget_timeout_and_no_retry(self):
        class Response:
            status = 200
            def read(self, size):
                return b"{}"
            def __enter__(self):
                return self
            def __exit__(self, *_):
                return False
        client = fetch.PublicClient()
        with patch.object(client.opener, "open", return_value=Response()) as opener:
            for _ in range(6):
                client.get(fetch.FUTURES + "/fapi/v1/time")
            self.assertEqual(opener.call_count, 6)
            self.assertEqual(opener.call_args.kwargs["timeout"], 8)
            with self.assertRaises(ValueError):
                client.get(fetch.FUTURES + "/fapi/v1/time")
            self.assertEqual(opener.call_count, 6)
        for target in ("https://fapi.binance.com/fapi/v2/account", "https://evil.example/fapi/v1/time",
                       "http://fapi.binance.com/fapi/v1/time", "https://user:pass@fapi.binance.com/fapi/v1/time"):
            with self.assertRaises(ValueError):
                client.get(target)
        self.assertIsNone(fetch.NoRedirect().redirect_request(None, None, 302, "", {}, "https://example.test"))

    def test_cli_root_or_evidence_resolve_escape_blocks_client_before_GET(self):
        with tempfile.TemporaryDirectory(prefix="finite_public_path_") as temp:
            base = Path(temp).resolve()
            root, outside = base / "safe", base / "outside"
            root.mkdir(); outside.mkdir(); (root / "evidence").mkdir()
            original_resolve = Path.resolve
            for escaping in (root, root / "evidence"):
                def redirected(path, *args, **kwargs):
                    if path == escaping or path.is_relative_to(escaping):
                        return outside / path.relative_to(escaping)
                    return original_resolve(path, *args, **kwargs)
                with patch.object(Path, "resolve", redirected), patch.object(fetch, "PublicClient") as client, patch.object(Path, "open") as opened:
                    with self.assertRaises(SystemExit):
                        fetch.main(["--outdir", str(root), "--run-network"])
                    client.assert_not_called()
                    opened.assert_not_called()

    def test_nested_evidence_escape_rejected_before_any_write(self):
        with tempfile.TemporaryDirectory(prefix="finite_public_nested_") as temp:
            base = Path(temp).resolve()
            root, outside = base / "safe", base / "outside"
            root.mkdir(); outside.mkdir(); (root / "evidence").mkdir()
            escaping = root / "evidence" / "nested"
            original_resolve = Path.resolve
            def redirected(path, *args, **kwargs):
                if path == escaping or path.is_relative_to(escaping):
                    return outside / path.relative_to(escaping)
                return original_resolve(path, *args, **kwargs)
            files = {"evidence/first_safe.json": b"{}", "evidence/nested/escape.json": b"{}"}
            with patch.object(Path, "resolve", redirected), patch.object(Path, "open") as opened:
                with self.assertRaises(ValueError):
                    fetch.write_fragment(root, {}, files)
                opened.assert_not_called()
            self.assertEqual(list(outside.iterdir()), [])
            self.assertFalse((root / "evidence" / "first_safe.json").exists())

    def test_windows_reparse_flags_rejected_even_if_resolve_stays_inside(self):
        with tempfile.TemporaryDirectory(prefix="finite_public_reparse_") as temp:
            root = Path(temp).resolve()
            (root / "evidence").mkdir()
            original_lstat = Path.lstat
            for flagged in (root, root / "evidence", root / "evidence" / "nested"):
                def reparse(path, *args, **kwargs):
                    if path == flagged:
                        return SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
                    return original_lstat(path, *args, **kwargs)
                with patch.object(Path, "lstat", reparse), patch.object(Path, "open") as opened:
                    with self.assertRaises(ValueError):
                        fetch.write_fragment(root, {}, {"evidence/nested/test.json": b"{}"})
                    opened.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
