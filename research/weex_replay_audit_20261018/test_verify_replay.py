"""Synthetic data-quality regressions; no release download or production imports."""
import csv
import hashlib
import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import verify_replay as v


class ReplayQualityTests(unittest.TestCase):
    def setUp(self):
        self.temp_root = (Path(__file__).parent / "local" / "synthetic").resolve()
        if not self.temp_root.is_relative_to(Path(__file__).parent.resolve()):
            raise ValueError("Synthetic temporary path escaped task folder")
        self.temp_root.mkdir(parents=True, exist_ok=True)

    def write_csv(self, folder, kind, rows):
        name = "BTCUSDT_20261016_" + kind + ".csv"
        with (folder/name).open("w", encoding="utf-8", newline="") as f:
            out = csv.writer(f)
            out.writerow(v.HEADERS[kind])
            out.writerows(rows)
        return {"symbol": "BTCUSDT", "utc_day": "20261016", "kind": kind, "file": name, "rows": len(rows)}

    def test_depth_gap_resnapshot_staleness_and_new_session(self):
        a = v.epoch("2026-10-16T00:00:00")
        with tempfile.TemporaryDirectory(dir=self.temp_root) as td:
            folder = Path(td)
            depth = []
            for offset, kind, U, u, session, applied in [
                (-1000, "snapshot", "", 1, "s1", 1), (0, "delta", 1, 2, "s1", 1),
                (500, "delta", 2, 3, "s1", 1), (1000, "delta", 999, 4, "s1", 0),
                (1200, "snapshot", "", 5, "s1", 1), (1700, "delta", 5, 6, "s1", 1),
                (5000, "delta", 6, 7, "s1", 1), (6000, "delta", 7, 8, "s2", 0),
                (6500, "snapshot", "", 9, "s2", 1), (7000, "delta", 9, 10, "s2", 1),
            ]:
                depth.append([kind, U, u, a+offset, a+offset, session, applied, '[["100","1"]]', '[["101","1"]]'])
            entries = [self.write_csv(folder, "depth", depth),
                self.write_csv(folder, "events", [[a+1000, "s1", "gap", "bad U"],
                    [a+1000, "s1", "resync", ""], [a+6000, "s2", "connect", ""]]),
                self.write_csv(folder, "trades2", [["1", a, a, a, "s1", "100", "1", "True"],
                    ["1", a+1, a+1, a+1, "s1", "100", "1", "False"]])]
            report = v.audit_symbol("BTCUSDT", entries, folder, [])
            spans = report["valid_depth_spans"]
            self.assertEqual([s["duration_ms"] for s in spans], [2000, 2500, 1000, 500])
            day = report["primary_windows"]["2026-10-16"]
            self.assertEqual(day["valid_depth_ms"], 5000)
            self.assertTrue(day["start_prewarmed"])
            self.assertEqual(report["depth"]["applied_flag_disagreements"], 0)
            self.assertEqual(report["trades"]["duplicate_id_rows"], 1)
            self.assertEqual(report["depth"]["applied_0"], 2)
            self.assertEqual(report["depth"]["stale_gaps_over_2s"], 1)

    def test_missing_initial_snapshot_is_excluded_without_false_recorder_failure(self):
        a = v.epoch("2026-10-16T00:00:00")
        with tempfile.TemporaryDirectory(dir=self.temp_root) as td:
            folder = Path(td)
            entries = [self.write_csv(folder, "depth", [
                ["delta", 1, 2, a, a, "old", 1, '[["100","1"]]', '[["101","1"]]'],
                ["snapshot", "", 3, a+500, a+500, "old", 1, '[["100","1"]]', '[["101","1"]]'],
                ["delta", 3, 4, a+1000, a+1000, "old", 1, '[]', '[]']]),
                self.write_csv(folder, "events", []), self.write_csv(folder, "trades2", [
                    ["a", a, a, a, "old", "100", "1", "True"]])]
            report = v.audit_symbol("BTCUSDT", entries, folder, [])
            self.assertEqual(report["depth"]["applied_1_unreplayable_without_snapshot_context"], 1)
            self.assertEqual(report["depth"]["applied_flag_disagreements"], 0)
            self.assertEqual(report["primary_windows"]["2026-10-16"]["valid_depth_ms"], 500)
            self.assertFalse(report["primary_windows"]["2026-10-16"]["start_prewarmed"])

    def test_json_levels_reject_nonfinite_negative_quantity_or_wrong_shape(self):
        for value in ['[["100","NaN"]]', '[["100","-1"]]', '[["100"]]', '{}']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                v.level_rows(value)

    def test_span_clipping_preserves_half_open_day_boundary(self):
        spans = [[-5, 5], [7, 10], [10, 12]]
        self.assertEqual(v.clip(spans, 0, 10), [[0, 5], [7, 10]])
        self.assertEqual(v.complement(spans, 0, 10), [[5, 7]])

    def check_unsafe_archive(self, member):
        with tempfile.TemporaryDirectory(dir=self.temp_root) as td:
            folder = Path(td)
            files = [{"file": f"{symbol}_202610{day}_{kind}.csv", "bytes": 0, "rows": 0,
                      "sha256": hashlib.sha256(b"").hexdigest()}
                     for symbol in ("BTCUSDT", "ETHUSDT") for day in (15, 16, 17, 18)
                     for kind in ("depth", "trades2", "events")]
            (folder/v.MANIFEST).write_text(json.dumps({"files":files}), encoding="utf-8")
            with tarfile.open(folder/v.ARCHIVE, "w:xz") as archive:
                archive.addfile(member)
            with patch.multiple(v, ARCHIVE_SHA=v.sha256(folder/v.ARCHIVE), MANIFEST_SHA=v.sha256(folder/v.MANIFEST)):
                with self.assertRaises(ValueError):
                    v.extract_verified(folder)
            self.assertEqual(list((folder/"verified_members").glob("*.csv")), [])

    def test_archive_rejects_parent_path(self):
        self.check_unsafe_archive(tarfile.TarInfo("../escape.csv"))

    def test_archive_rejects_symlink(self):
        member = tarfile.TarInfo("weex_book_v2/BTCUSDT_20261015_depth.csv")
        member.type, member.linkname = tarfile.SYMTYPE, "../outside"
        self.check_unsafe_archive(member)


if __name__ == "__main__":
    unittest.main()
