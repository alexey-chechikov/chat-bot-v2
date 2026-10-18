"""Synthetic fixtures only; no network, live source, account or collector access."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import archive_daily as daily


def ms(text):
    return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp() * 1000)


NOW = ms("2026-10-16T12:00:00Z")


def fixture():
    return {"schema": "daily-as-seen-v1", "timezone": "Europe/Warsaw", "synthetic": True,
            "collected_at_ms": NOW - 60000, "finished_at_ms": NOW - 1000, "quality_flags": [],
            "sources": [{"id": "synthetic_book", "status": "OK", "url": "https://example.test/public",
                         "event_asof_ms": NOW - 2000, "lag_status": "known", "provider_lag_ms": 0,
                         "settings": {"symbol": "SYNTHETIC", "window": "1d"}, "market_scope": "futures",
                         "aggregation": "BBO", "forming_bar": False, "quality_flags": [],
                         "values": [{"name": "observed_value", "type": "number", "value": 12.5, "unit": "USD"}]}]}


class DailyArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix=".synthetic_test_", dir=Path(__file__).resolve().parent)
        self.base = Path(self.temp.name)
        self.input = self.base / "input.json"
        self.out = self.base / "local"

    def tearDown(self):
        self.temp.cleanup()

    def save(self, data):
        self.input.write_text(json.dumps(data), encoding="utf-8")

    def report(self, data):
        return daily.build_report(data, NOW, self.base)[0]

    def test_complete_atomic_bundle_and_synthetic_namespace(self):
        data = fixture(); self.save(data)
        target, report = daily.archive_file(self.input, self.out, _clock=lambda: NOW)
        self.assertEqual(target, self.out / "synthetic" / "2026-10-16" / f"run_{NOW}")
        self.assertEqual((target / "input.json").read_bytes(), self.input.read_bytes())
        self.assertTrue((target / "report.json").is_file())
        self.assertTrue((target / "summary.md").is_file())
        self.assertEqual(report["archived_at_ms"], NOW)
        self.assertEqual(report["status"], "OK")
        self.assertFalse(any("staging" in p.name or "reserve" in p.name for p in self.out.rglob("*")))

    def test_no_overwrite_even_same_run_millisecond(self):
        data = fixture(); self.save(data)
        target, _ = daily.archive_file(self.input, self.out, _clock=lambda: NOW)
        original = (target / "input.json").read_bytes()
        data["sources"][0]["values"][0]["value"] = 99; self.save(data)
        with self.assertRaises(FileExistsError):
            daily.archive_file(self.input, self.out, _clock=lambda: NOW)
        self.assertEqual((target / "input.json").read_bytes(), original)

    def test_publish_failure_leaves_no_half_archive(self):
        self.save(fixture())
        original = daily.write_new
        def fail_report(path, body):
            if path.name == "report.json":
                raise OSError("synthetic disk failure")
            original(path, body)
        with patch.object(daily, "write_new", side_effect=fail_report):
            with self.assertRaises(OSError):
                daily.archive_file(self.input, self.out, _clock=lambda: NOW)
        self.assertFalse(any(p.is_file() for p in self.out.rglob("*")))
        self.assertFalse(any("run_" in p.name for p in self.out.rglob("*")))

    def test_day_uses_collected_warsaw_not_utc_or_finished(self):
        data = fixture()
        data["collected_at_ms"] = ms("2026-10-15T22:30:00Z")
        data["finished_at_ms"] = ms("2026-10-16T00:00:00Z")
        self.assertEqual(self.report(data)["daily_date"], "2026-10-16")
        data["daily_date"] = "2026-10-15"
        with self.assertRaises(ValueError): self.report(data)

    def test_real_backdating_refused_without_writing_real_archive(self):
        data = fixture(); data["synthetic"] = False
        data["collected_at_ms"] = NOW - 2 * daily.DAY_MS
        data["finished_at_ms"] = NOW - daily.DAY_MS
        with self.assertRaisesRegex(ValueError, "backfill/backdating"):
            self.report(data)
        self.assertFalse(self.out.exists())

    def test_supplied_fake_archive_identity_refused(self):
        for key in ("run_id", "archived_at_ms", "archive_date", "output_path"):
            data = fixture(); data[key] = "old"
            with self.assertRaises(ValueError): self.report(data)

    def test_future_event_asof_flagged_not_rewritten(self):
        data = fixture(); data["sources"][0]["event_asof_ms"] = NOW + 5000
        report = self.report(data)
        self.assertIn("future_asof", report["sources"][0]["quality_flags"])
        self.assertEqual(report["sources"][0]["event_asof_ms"], NOW + 5000)
        self.assertEqual(report["status"], "PARTIAL")

    def test_stale_asof_and_unknown_asof_are_distinct(self):
        data = fixture(); source = data["sources"][0]
        source["event_asof_ms"] = NOW - 10000; source["stale_after_ms"] = 1000
        self.assertIn("stale_asof", self.report(data)["sources"][0]["quality_flags"])
        source["event_asof_ms"] = None
        report = self.report(data)
        self.assertIn("asof_unknown", report["sources"][0]["quality_flags"])
        self.assertIsNone(report["sources"][0]["event_age_at_finish_ms"])

    def test_asof_age_never_invents_known_provider_lag(self):
        data = fixture(); source = data["sources"][0]
        source["lag_status"] = "unknown"; source["provider_lag_ms"] = None
        result = self.report(data)["sources"][0]
        self.assertEqual(result["lag_status"], "unknown")
        self.assertIsNone(result["provider_lag_ms"])
        self.assertEqual(result["event_age_at_finish_ms"], 1000)
        source["provider_lag_ms"] = 1000
        with self.assertRaises(ValueError): self.report(data)

    def test_missing_is_none_not_zero_and_all_failed_is_failed(self):
        data = fixture(); source = data["sources"][0]
        source["status"] = "MISSING"; source["values"][0]["value"] = None; source["event_asof_ms"] = None
        report = self.report(data)
        self.assertEqual(report["status"], "FAILED")
        self.assertIsNone(report["sources"][0]["values"][0]["value"])
        self.assertIn("нет данных", daily.summary(report))
        source["values"][0]["value"] = 0
        with self.assertRaises(ValueError): self.report(data)

    def test_failed_missing_sources_do_not_produce_success(self):
        data = fixture()
        data["sources"][0].update(status="FAILED", values=None, event_asof_ms=None)
        second = deepcopy(data["sources"][0]); second.update(id="also_missing", status="MISSING")
        data["sources"].append(second)
        self.assertEqual(self.report(data)["status"], "FAILED")

    def test_literal_observed_zero_is_valid_for_ok_source(self):
        data = fixture(); data["sources"][0]["values"][0]["value"] = 0
        self.assertEqual(self.report(data)["status"], "OK")

    def test_partial_source_means_partial_not_ok(self):
        data = fixture(); data["sources"][0]["status"] = "PARTIAL"
        self.assertEqual(self.report(data)["status"], "PARTIAL")

    def test_spot_futures_group_aggregate_forming_bar_remain_explicit(self):
        data = fixture(); first = data["sources"][0]
        first.update(aggregation="group_aggregate", forming_bar=True)
        second = deepcopy(first); second.update(id="spot", market_scope="spot", event_asof_ms=NOW - 3000)
        data["sources"].append(second)
        report = self.report(data)
        self.assertEqual(report["source_groups"], {"futures": ["synthetic_book"], "spot": ["spot"]})
        self.assertIn("mixed_asof", report["quality_flags"])
        self.assertIn("forming_bar", report["sources"][0]["quality_flags"])
        self.assertIn("group_aggregate_not_bbo", report["sources"][0]["quality_flags"])
        self.assertIn("не BBO", daily.summary(report))

    def test_never_auto_allow_primary_or_order_permission(self):
        report = self.report(fixture())
        self.assertFalse(report["order_permission"])
        self.assertFalse(report["trade_primary_labels_created"])
        self.assertFalse(report["predictions_created"])
        for key in ("order_permission", "trade_primary", "auto_allowed_primary"):
            data = fixture(); data[key] = True
            with self.assertRaises(ValueError): self.report(data)

    def test_evidence_copy_hash_match_and_original_provenance(self):
        data = fixture(); evidence = self.base / "evidence"; evidence.mkdir()
        body = b"synthetic public DOM text"; (evidence / "page.txt").write_bytes(body)
        data["sources"][0]["evidence"] = [{"kind": "dom_text", "path": "evidence/page.txt", "sha256": hashlib.sha256(body).hexdigest()}]
        self.save(data); target, report = daily.archive_file(self.input, self.out, _clock=lambda: NOW)
        record = report["sources"][0]["evidence"][0]
        self.assertEqual(record["integrity"], "matched")
        self.assertEqual((target / record["path"]).read_bytes(), body)

    def test_missing_or_hash_mismatched_evidence_is_partial(self):
        data = fixture(); source = data["sources"][0]
        source["evidence"] = [{"kind": "site_export", "path": "evidence/absent.json", "sha256": None}]
        report = self.report(data)
        self.assertEqual(report["status"], "PARTIAL")
        self.assertIn("evidence_missing", report["sources"][0]["quality_flags"])
        (self.base / "evidence").mkdir(); (self.base / "evidence" / "absent.json").write_text('{}')
        source["evidence"][0]["sha256"] = "0" * 64
        self.assertIn("evidence_hash_mismatch", self.report(data)["sources"][0]["quality_flags"])

    def test_evidence_cannot_escape_to_private_paths(self):
        for path in ("../.env", "C:/private/.env", "evidence/../../.env"):
            data = fixture(); data["sources"][0]["evidence"] = [{"kind": "dom_text", "path": path, "sha256": None}]
            with self.assertRaises(ValueError): self.report(data)

    def test_evidence_root_junction_escape_rejected_before_file_access(self):
        data = fixture()
        data["sources"][0]["evidence"] = [{"kind": "dom_text", "path": "evidence/page.txt", "sha256": None}]
        ordinary_resolve = Path.resolve
        outside = self.base.parent / "invented_outside_evidence"
        def junction_resolve(path, *args, **kwargs):
            if path == self.base / "evidence":
                return outside
            if path == self.base / "evidence" / "page.txt":
                return outside / "page.txt"
            return ordinary_resolve(path, *args, **kwargs)
        with patch.object(Path, "resolve", autospec=True, side_effect=junction_resolve):
            with self.assertRaisesRegex(ValueError, "evidence root escapes"):
                self.report(data)

    def test_nested_evidence_symlink_escape_still_rejected(self):
        data = fixture()
        data["sources"][0]["evidence"] = [{"kind": "dom_text", "path": "evidence/nested.txt", "sha256": None}]
        ordinary_resolve = Path.resolve
        outside = self.base.parent / "invented_outside_file.txt"
        def nested_resolve(path, *args, **kwargs):
            if path == self.base / "evidence" / "nested.txt":
                return outside
            return ordinary_resolve(path, *args, **kwargs)
        with patch.object(Path, "resolve", autospec=True, side_effect=nested_resolve):
            with self.assertRaisesRegex(ValueError, "evidence path escapes"):
                self.report(data)

    def test_typed_values_nonfinite_and_collection_future_refused(self):
        data = fixture(); data["sources"][0]["values"][0]["value"] = True
        with self.assertRaises(ValueError): self.report(data)
        data = fixture(); data["sources"][0]["values"][0]["value"] = float('nan')
        with self.assertRaises(ValueError): self.report(data)
        data = fixture(); data["finished_at_ms"] = NOW + 10000
        with self.assertRaises(ValueError): self.report(data)


if __name__ == "__main__":
    unittest.main()
