import csv
from datetime import date
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import export_public_market as exporter


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="synthetic_", dir=Path(__file__).resolve().parent)
        self.root = Path(self.temp.name).absolute()
        self.source = self.root / "public"
        self.source.mkdir()
        self.day = date(2026, 10, 14)
        self.out = self.root / "public.zip"

    def tearDown(self):
        self.temp.cleanup()

    def write(self, symbol="ETHUSDT", kind="depth", header=None):
        path = self.source / f"{symbol}_20261014_{kind}.csv"
        row = {"kind": "snapshot", "U": "", "u": "3", "E": "1792022400000",
               "recv_ms": "1792022400010", "session": "s1", "applied": "1",
               "b": '[["2500","1"]]', "a": '[["2501","2"]]', "t": "100",
               "T": "1792022400000", "p": "2500", "q": "0.1", "m_raw": "True",
               "event": "snapshot", "detail": "a, b"}
        cols = list(header or exporter.HEADERS[kind])
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(cols)
            writer.writerow([row.get(col, "extra") for col in cols])
        return path

    def run_export(self):
        return exporter.export(self.source, self.day, self.day, self.out)

    def test_exact_six_csv_whitelist_and_manifest_hashes(self):
        paths = [self.write(symbol, kind) for symbol in exporter.SYMBOLS for kind in exporter.HEADERS]
        (self.source / ".env").write_text("NEVER READ", encoding="utf-8")
        (self.source / "ETHUSDT_20261014_book.csv").write_text("legacy", encoding="utf-8")
        nested = self.source / "nested"
        nested.mkdir()
        (nested / paths[0].name).write_text("not traversed", encoding="utf-8")
        manifest = self.run_export()
        self.assertEqual(len(manifest["files"]), 6)
        self.assertEqual(manifest["missing_whitelist_filenames"], [])
        with zipfile.ZipFile(self.out) as archive:
            self.assertEqual(set(archive.namelist()), {p.name for p in paths} | {"manifest.json"})
            for meta in manifest["files"]:
                raw = archive.read(meta["name"])
                self.assertEqual(raw, (self.source / meta["name"]).read_bytes())
                self.assertEqual(hashlib.sha256(raw).hexdigest(), meta["sha256"])
                self.assertEqual(meta["rows"], 1)
            self.assertEqual(json.loads(archive.read("manifest.json")), manifest)

    def test_unknown_column_fails_without_archive(self):
        self.write(header=(*exporter.HEADERS["depth"], "account_id"))
        with self.assertRaisesRegex(exporter.ExportError, "header/columns"):
            self.run_export()
        self.assertFalse(self.out.exists())

    def test_existing_output_never_overwritten(self):
        self.write()
        self.out.write_bytes(b"prior")
        with self.assertRaisesRegex(exporter.ExportError, "never overwritten"):
            self.run_export()
        self.assertEqual(self.out.read_bytes(), b"prior")

    def test_partial_package_marks_missing_not_fabricated(self):
        self.write()
        manifest = self.run_export()
        self.assertEqual(len(manifest["missing_whitelist_filenames"]), 5)
        self.assertEqual(manifest["status"], "packaging_only_not_execution_admission")
        self.assertTrue(manifest["not_verified"])

    def test_mutation_between_validation_and_copy_rejected(self):
        path = self.write()
        original_copy = exporter.copy_csv
        def changed(archive, selected, meta):
            with path.open("a", encoding="utf-8") as handle:
                handle.write("changed\n")
            return original_copy(archive, selected, meta)
        with patch.object(exporter, "copy_csv", changed):
            with self.assertRaisesRegex(exporter.ExportError, "changed"):
                self.run_export()
        self.assertFalse(self.out.exists())
        self.assertEqual(list(self.root.glob(".weex-public-export-*.tmp")), [])

    def test_selected_symlink_rejected(self):
        external = self.root / "external.csv"
        external.write_text("do not read", encoding="utf-8")
        link = self.source / "ETHUSDT_20261014_depth.csv"
        try:
            link.symlink_to(external)
        except OSError:
            self.skipTest("OS does not permit unprivileged symlinks")
        with self.assertRaisesRegex(exporter.ExportError, "Symlink"):
            self.run_export()
        self.assertFalse(self.out.exists())

    def test_bad_row_width_rejected(self):
        path = self.write()
        with path.open("a", encoding="utf-8") as handle:
            handle.write("one,two\n")
        with self.assertRaisesRegex(exporter.ExportError, "column count"):
            self.run_export()
        self.assertFalse(self.out.exists())


if __name__ == "__main__":
    unittest.main()
