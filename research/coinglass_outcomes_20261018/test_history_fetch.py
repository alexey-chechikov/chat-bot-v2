"""Synthetic-only collection QA. No sockets, real market inputs or old archive writes."""
from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import history_fetch as h

NOW = 1_800_000_000_000 + 12_345
END = NOW // h.STEP * h.STEP


@contextmanager
def workspace_temp():
    base = Path(__file__).resolve().parent / "local" / "test_temp"
    base.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=base, prefix="fetch_synthetic_") as name:
        if Path(name).resolve().parent != base.resolve():
            raise RuntimeError("synthetic cleanup target escaped test base")
        try:
            yield name
        finally:
            if Path(name).resolve().parent != base.resolve():
                raise RuntimeError("synthetic cleanup target escaped test base")


def bar(t, *, zero=False):
    return [t, "100", "102", "99", "101", "0" if zero else "10", t + h.STEP - 1,
            "0" if zero else "1000", 0 if zero else 10, "0" if zero else "6", "0" if zero else "600", "0"]


class FakeClient:
    def __init__(self, *, server=NOW, modify=None, fail=None, zero=False):
        self.server, self.modify, self.fail, self.zero = server, modify, fail, zero
        self.urls = []

    def get(self, target):
        self.urls.append(target)
        parts = urlsplit(target)
        q = {key: values[0] for key, values in parse_qs(parts.query).items()}
        if self.fail == parts.path:
            raise OSError("synthetic unavailable")
        if parts.path == "/fapi/v1/time":
            payload = {"serverTime": self.server}
        elif parts.path in ("/api/v3/klines", "/fapi/v1/klines"):
            payload = [bar(t, zero=self.zero) for t in range(int(q["startTime"]), int(q["endTime"]) + 1, h.STEP)]
        elif parts.path == "/futures/data/openInterestHist":
            payload = [{"symbol": "BTCUSDT", "timestamp": t, "sumOpenInterest": "1000", "sumOpenInterestValue": "100000"}
                       for t in range(int(q["startTime"]), int(q["endTime"]) + 1, h.STEP)]
        elif parts.path == "/fapi/v1/fundingRate":
            payload = [{"symbol": "BTCUSDT", "fundingTime": int(q["startTime"]) + 1,
                        "fundingRate": "0.0001", "markPrice": "100"}]
        elif parts.path == "/fapi/v1/premiumIndex":
            payload = {"symbol": "BTCUSDT", "time": self.server, "markPrice": "100", "indexPrice": "100",
                       "lastFundingRate": "0.0001", "nextFundingTime": self.server + 28_800_000}
        else:
            raise AssertionError("unexpected endpoint: " + target)
        if self.modify:
            payload = self.modify(parts.path, payload)
        return h.Reply(200, h.dumps(payload))


def source(document, sid):
    return next(s for s in document["sources"] if s["id"] == sid)


def rows(document, sid):
    values = source(document, sid)["values"]
    return values[0]["value"] if values else None


def collect(client=None, *, local=NOW, include_premium=True):
    return h.collect(client or FakeClient(), include_premium=include_premium, clock=lambda: local, synthetic=True)


def pinned_module(name, filename, expected):
    path = Path(__file__).resolve().parent.parent / "coinglass_daily_context_20261016" / filename
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise AssertionError("pinned legacy helper SHA changed: " + filename)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class HistoryCollectionTests(unittest.TestCase):
    def test_full_six_gets_extended_and_daily_tail(self):
        client = FakeClient()
        history, daily, evidence = collect(client)
        self.assertEqual(history["schema"], "coinglass-outcome-history-v1")
        self.assertEqual(daily["schema"], "daily-as-seen-v1")
        self.assertEqual(history["cutoff_ms"], END)
        self.assertEqual(history["collected_at_ms"], NOW)
        self.assertEqual(len(client.urls), 6)
        self.assertEqual(len(evidence), 12)
        self.assertEqual(history["fetch_summary"]["attempted_GETs"], 6)
        for sid in ("binance_spot_15m", "binance_perp_15m"):
            self.assertEqual(len(rows(history, sid)), 384)
            self.assertEqual(len(rows(daily, sid)), 96)
            self.assertEqual(rows(daily, sid), rows(history, sid)[-96:])
            self.assertEqual(source(history, sid)["settings"]["requested_closed_bars"], 384)
            self.assertEqual(source(daily, sid)["settings"]["requested_closed_bars"], 96)
        self.assertEqual(len(rows(history, "binance_oi_15m")), 385)
        self.assertEqual(len(rows(daily, "binance_oi_15m")), 97)
        self.assertIs(history["order_permission"], False)
        for s in history["sources"]:
            for e in s["evidence"]:
                self.assertEqual(e["sha256"], hashlib.sha256(evidence[e["path"]]).hexdigest())

    def test_optional_premium_is_fifth_or_sixth_not_extra(self):
        client = FakeClient()
        history, daily, _ = collect(client, include_premium=False)
        self.assertEqual(len(client.urls), 5)
        self.assertEqual(history["fetch_summary"]["attempted_GETs"], 5)
        self.assertNotIn("binance_premium_current", [s["id"] for s in daily["sources"]])

    def test_plan_limits_and_one_common_closed_window(self):
        client = FakeClient()
        collect(client)
        parsed = [(urlsplit(u), parse_qs(urlsplit(u).query)) for u in client.urls]
        for parts, q in parsed:
            if parts.path.endswith("/klines"):
                self.assertEqual(q["limit"], ["384"])
                self.assertEqual(q["startTime"], [str(END - h.HISTORY)])
                self.assertEqual(q["endTime"], [str(END - 1)])
            if parts.path.endswith("openInterestHist"):
                self.assertEqual(q["limit"], ["385"])
                self.assertEqual(q["endTime"], [str(END)])
        self.assertEqual(len({u for u in client.urls}), 6)

    def test_failed_clock_skips_all_dependent_gets(self):
        client = FakeClient(fail="/fapi/v1/time")
        history, daily, _ = collect(client)
        self.assertEqual(len(client.urls), 1)
        self.assertIsNone(history["cutoff_ms"])
        for s in history["sources"][1:]:
            self.assertEqual(s["status"], "MISSING")
            self.assertIsNone(s["values"])
            self.assertTrue(s["settings"]["request_not_attempted"])
        self.assertEqual(len(daily["sources"]), 6)

    def test_malformed_or_excess_skew_clock_is_unavailable(self):
        for server in (NOW + 300_001, NOW - 300_001, True, "1800000000000"):
            with self.subTest(server=server):
                client = FakeClient(server=server)
                history, _, _ = collect(client)
                self.assertEqual(len(client.urls), 1)
                self.assertIsNone(history["cutoff_ms"])

    def test_ahead_server_does_not_allow_local_forming_bar(self):
        local = END + h.STEP - 100
        history, _, _ = collect(FakeClient(server=local + 2000), local=local)
        self.assertEqual(history["cutoff_ms"], END)
        self.assertLessEqual(rows(history, "binance_spot_15m")[-1]["bar_end_ms"], local)
        transport = source(history, "binance_spot_15m")["settings"]["transport"]
        self.assertEqual(transport["known_clock_skew_server_minus_local_ms"], 2000)
        self.assertTrue(transport["skew_is_not_provider_lag"])

    def test_behind_server_is_the_conservative_boundary(self):
        local = END + 1000
        history, _, _ = collect(FakeClient(server=END - 1000), local=local)
        self.assertEqual(history["cutoff_ms"], END - h.STEP)

    def test_exact_closed_boundary_retained(self):
        history, _, _ = collect(FakeClient(server=END), local=END)
        last = rows(history, "binance_spot_15m")[-1]
        self.assertEqual(last["bar_end_ms"], END)
        self.assertEqual(last["provider_close_time_ms"], END - 1)
        self.assertTrue(last["closed"])

    def test_forming_extra_row_rejected(self):
        def modify(path, payload):
            return payload + [bar(END)] if path == "/api/v3/klines" else payload
        history, daily, _ = collect(FakeClient(modify=modify))
        self.assertEqual(len(rows(history, "binance_spot_15m")), 384)
        self.assertNotIn(END, [r["bar_start_ms"] for r in rows(history, "binance_spot_15m")])
        self.assertTrue(source(history, "binance_spot_15m")["settings"]["validation"]["rejected_rows"])
        self.assertEqual(len(rows(daily, "binance_spot_15m")), 96)

    def test_old_gap_does_not_corrupt_complete_daily_tail(self):
        def modify(path, payload):
            return payload[1:] if path == "/api/v3/klines" else payload
        history, daily, _ = collect(FakeClient(modify=modify))
        self.assertEqual(source(history, "binance_spot_15m")["status"], "PARTIAL")
        self.assertEqual(source(daily, "binance_spot_15m")["status"], "OK")
        self.assertEqual(len(rows(daily, "binance_spot_15m")), 96)

    def test_tail_gap_remains_missing_not_zero(self):
        def modify(path, payload):
            return payload[:-1] if path == "/api/v3/klines" else payload
        _, daily, _ = collect(FakeClient(modify=modify))
        s = source(daily, "binance_spot_15m")
        self.assertEqual(s["status"], "PARTIAL")
        self.assertEqual(s["settings"]["validation"]["missing_timestamps"], [END - h.STEP])
        self.assertEqual(len(rows(daily, "binance_spot_15m")), 95)

    def test_equivalent_duplicate_is_deduplicated(self):
        def modify(path, payload):
            if path == "/api/v3/klines":
                extra = copy.deepcopy(payload[-1]); extra[1] = "100.0"
                return payload + [extra]
            return payload
        history, _, _ = collect(FakeClient(modify=modify))
        self.assertEqual(len(rows(history, "binance_spot_15m")), 384)
        self.assertEqual(source(history, "binance_spot_15m")["conflicting_timestamps"], [])
        self.assertIn("equivalent_duplicates_deduplicated", source(history, "binance_spot_15m")["quality_flags"])

    def test_conflicting_duplicate_all_versions_excluded(self):
        def modify(path, payload):
            if path == "/api/v3/klines":
                extra = copy.deepcopy(payload[-1]); extra[4] = "102"
                return payload + [extra, copy.deepcopy(payload[-1])]
            return payload
        history, daily, _ = collect(FakeClient(modify=modify))
        self.assertEqual(len(rows(history, "binance_spot_15m")), 383)
        self.assertEqual(source(history, "binance_spot_15m")["conflicting_timestamps"], [END - h.STEP])
        self.assertEqual(source(daily, "binance_spot_15m")["conflicting_timestamps"], [END - h.STEP])
        self.assertEqual(len(rows(daily, "binance_spot_15m")), 95)

    def test_zero_volume_has_null_F(self):
        history, daily, _ = collect(FakeClient(zero=True))
        for document in (history, daily):
            for row in rows(document, "binance_spot_15m"):
                self.assertIsNone(row["F"])
                self.assertIsNone(row["buy_share"])
                self.assertIsNone(row["sell_share"])

    def test_bad_volume_rejected_without_retry(self):
        def modify(path, payload):
            if path == "/api/v3/klines":
                payload[-1][9] = "11"
            return payload
        client = FakeClient(modify=modify)
        history, _, _ = collect(client)
        self.assertEqual(len(client.urls), 6)
        self.assertEqual(len(rows(history, "binance_spot_15m")), 383)

    def test_network_exception_is_not_retried_and_other_sources_continue(self):
        client = FakeClient(fail="/api/v3/klines")
        history, daily, _ = collect(client)
        self.assertEqual(len(client.urls), 6)
        self.assertEqual(source(history, "binance_spot_15m")["status"], "FAILED")
        self.assertIsNone(rows(daily, "binance_spot_15m"))
        self.assertEqual(len(rows(daily, "binance_perp_15m")), 96)

    def test_error_object_is_not_zero_observations(self):
        def modify(path, payload):
            return {"code": -1, "msg": "synthetic failure"} if path == "/api/v3/klines" else payload
        history, _, _ = collect(FakeClient(modify=modify))
        self.assertEqual(source(history, "binance_spot_15m")["status"], "FAILED")
        self.assertIsNone(rows(history, "binance_spot_15m"))

    def test_clock_rollback_is_not_accepted(self):
        ticks = iter((NOW, NOW + 10, NOW + 5, NOW + 15))
        client = FakeClient()
        history, _, _ = h.collect(client, clock=lambda: next(ticks), synthetic=True)
        self.assertEqual(len(client.urls), 1)
        self.assertIsNone(history["cutoff_ms"])
        self.assertIn("local_wall_clock_non_monotonic", source(history, "binance_public_clock")["quality_flags"])

    def test_finish_before_start_refused(self):
        ticks = iter((NOW, NOW, NOW, NOW - 1))
        with self.assertRaises(ValueError):
            h.collect(FakeClient(fail="/fapi/v1/time"), clock=lambda: next(ticks), synthetic=True)


class LegacyCompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.analytics = pinned_module("pinned_legacy_analytics_for_history_test", "analytics_daily.py",
                                      "2a71c2e64294b23b7e4efc7234dc76c959d82afcd5b7793b0710670978c51050")
        cls.fetch = pinned_module("pinned_legacy_fetch_for_history_test", "fetch_public_context.py",
                                  "74c979e12c7ac095053120be5b71a000650ab58dcb29f652e6c9b19fed495e98")

    def test_daily_semantics_exactly_match_pinned_legacy(self):
        history, daily, _ = collect()
        old, _ = self.fetch.collect_context(FakeClient(), include_premium=True, clock=lambda: NOW, synthetic=True)
        for old_source in old["sources"]:
            current = source(daily, old_source["id"])
            self.assertEqual(self.analytics.semantics(current), self.analytics.semantics(old_source))
            self.assertEqual(self.analytics.semantic_hash(current), self.analytics.semantic_hash(old_source))
            if current["id"] != "binance_oi_15m":
                self.assertEqual(source(history, current["id"])["legacy_definition"], self.analytics.semantics(old_source))

    def test_old_metrics_accept_current_tail_and_known_three_hashes(self):
        history, daily, _ = collect()
        hashes = {"binance_spot_15m": "b576a4dd667ad619a72606e23e3ad53494f007e95dc3c7f60eecaa4552cf3276",
                  "binance_perp_15m": "c308f0be9199023e25abc619ef7f2c22d2dab60e5d60fb01471bfd7a512e7bc0",
                  "binance_oi_15m": "98406a1e14641a0352c0549efaee345e9085ea26e1c046053e6c549ead8e4d06"}
        perp, _ = self.analytics.market_metrics(source(daily, "binance_perp_15m"), NOW)
        for sid in ("binance_spot_15m", "binance_perp_15m"):
            group, _ = self.analytics.market_metrics(source(daily, sid), NOW)
            self.assertTrue(group["coverage"]["complete_96_closed"])
            self.assertEqual(group["semantic_hash"], hashes[sid])
        oi = self.analytics.oi_metrics(source(daily, "binance_oi_15m"), perp, NOW)
        self.assertEqual(oi["semantic_hash"], hashes["binance_oi_15m"])
        self.assertEqual(json.loads(json.dumps(oi["semantics"])), source(history, "binance_oi_15m")["legacy_definition"])


class PublicClientTests(unittest.TestCase):
    def test_allowlist_refuses_accounts_credentials_ports_and_http(self):
        client = h.PublicClient()
        for target in ("https://fapi.binance.com/fapi/v2/account", "https://u:p@fapi.binance.com/fapi/v1/time",
                       "http://fapi.binance.com/fapi/v1/time", "https://fapi.binance.com:443/fapi/v1/time",
                       "https://evil.invalid/fapi/v1/time", "https://fapi.binance.com/fapi/v1/time#x"):
            with self.subTest(target=target), self.assertRaises(ValueError):
                client.get(target)
        self.assertEqual(client.get_count, 0)

    def test_client_enforces_six_gets_without_socket(self):
        class Response:
            status = 200
            def read(self, limit):
                return b"{}"
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return None
        client = h.PublicClient()
        with patch.object(client.opener, "open", return_value=Response()) as opened:
            for _ in range(6):
                client.get(h.FUTURES + "/fapi/v1/time")
            with self.assertRaises(ValueError):
                client.get(h.FUTURES + "/fapi/v1/time")
            self.assertEqual(opened.call_count, 6)

    def test_redirect_handler_never_creates_followup_request(self):
        self.assertIsNone(h.NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://other.invalid"))


class OutputTests(unittest.TestCase):
    def test_immutable_bundle_and_evidence(self):
        history, daily, evidence = collect()
        with workspace_temp() as temp:
            outdir = Path(temp) / "unique"
            result = h.write_bundle(outdir, history, daily, evidence)
            before = hashlib.sha256(result.read_bytes()).hexdigest()
            self.assertEqual(json.loads(result.read_bytes()), history)
            for rel, body in evidence.items():
                self.assertEqual((outdir / rel).read_bytes(), body)
            with self.assertRaises(FileExistsError):
                h.write_bundle(outdir, history, daily, evidence)
            self.assertEqual(hashlib.sha256(result.read_bytes()).hexdigest(), before)
            self.assertFalse((outdir / ".history.reserve").exists())

    def test_path_traversal_and_relative_outdir_refused(self):
        with workspace_temp() as temp:
            for rel in ("../escape", "evidence/../../escape", "evidence/a/b", "C:/escape", "evidence/a:b"):
                with self.subTest(rel=rel), self.assertRaises(ValueError):
                    h.validate_output(Path(temp) / "safe", [rel])
        with self.assertRaises(ValueError):
            h.validate_output(Path("relative"))

    def test_symlink_outdir_refused_if_supported(self):
        with workspace_temp() as temp:
            root = Path(temp); target = root / "target"; target.mkdir()
            link = root / "redirect"
            try:
                link.symlink_to(target, target_is_directory=True)
            except OSError:
                self.skipTest("symlink creation not permitted on this Windows host")
            with self.assertRaises(ValueError):
                h.validate_output(link)

    def test_windows_reparse_guard_without_symlink_privilege(self):
        metadata = SimpleNamespace(st_mode=h.stat.S_IFDIR, st_file_attributes=0x400)
        with workspace_temp() as temp, patch.object(Path, "lstat", return_value=metadata):
            with self.assertRaises(ValueError):
                h.validate_output(Path(temp) / "out")

    def test_concurrent_bundle_writers_have_one_immutable_winner(self):
        history, daily, evidence = collect()
        with workspace_temp() as temp:
            out = Path(temp) / "out"
            def write():
                try:
                    return str(h.write_bundle(out, history, daily, evidence))
                except FileExistsError:
                    return None
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: write(), range(2)))
            self.assertEqual(sum(value is not None for value in results), 1)
            self.assertEqual(json.loads((out / "history.json").read_bytes()), history)

    def test_failed_write_never_creates_success_history_marker(self):
        history, daily, evidence = collect()
        with workspace_temp() as temp:
            original = h._write_new
            def fail_daily(path, body):
                if path.name == "public_sources.json":
                    raise OSError("synthetic disk failure")
                return original(path, body)
            with patch.object(h, "_write_new", side_effect=fail_daily), self.assertRaises(OSError):
                h.write_bundle(Path(temp) / "out", history, daily, evidence)
            self.assertFalse((Path(temp) / "out" / "history.json").exists())
            self.assertFalse((Path(temp) / "out" / ".history.reserve").exists())

    def test_cli_without_explicit_activation_performs_no_network(self):
        with workspace_temp() as temp, patch.object(h, "PublicClient") as client, patch("sys.stderr", new_callable=io.StringIO):
            with self.assertRaises(SystemExit):
                h.main(["--outdir", str(Path(temp) / "out")])
            client.assert_not_called()

    def test_cli_existing_bundle_refused_before_constructing_client(self):
        with workspace_temp() as temp:
            root = Path(temp); (root / "history.json").write_text("{}", encoding="utf-8")
            with patch.object(h, "PublicClient") as client, patch("sys.stderr", new_callable=io.StringIO):
                with self.assertRaises(SystemExit):
                    h.main(["--run-network", "--outdir", str(root)])
                client.assert_not_called()

    def test_cli_busy_namespace_refused_before_network(self):
        with workspace_temp() as temp:
            root = Path(temp); (root / ".collection.reserve").write_text("busy", encoding="utf-8")
            with patch.object(h, "PublicClient") as client, patch("sys.stderr", new_callable=io.StringIO):
                with self.assertRaises(SystemExit):
                    h.main(["--run-network", "--outdir", str(root)])
                client.assert_not_called()


if __name__ == "__main__":
    unittest.main()
