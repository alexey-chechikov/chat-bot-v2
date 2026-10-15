"""Offline whitelist-only export of public WEEX recorder-v2 CSV files.

No network, credentials, account files, collector or trading clients are used.
Python 3.9+ standard library; source CSV files are never changed.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
import zipfile


SYMBOLS = ("BTCUSDT", "ETHUSDT")
HEADERS = {
    "depth": ("kind", "U", "u", "E", "recv_ms", "session", "applied", "b", "a"),
    "trades2": ("t", "T", "E", "recv_ms", "session", "p", "q", "m_raw"),
    "events": ("recv_ms", "session", "event", "detail"),
}
BLOCK = 1024 * 1024


class ExportError(ValueError):
    pass


def checked_path(path: Path, *, directory: bool) -> Path:
    """Do not follow a symlink in the explicit path, including its ancestors."""
    if not path.is_absolute():
        raise ExportError("Use an absolute --source/--outzip path")
    if ".." in path.parts:
        raise ExportError("Parent traversal is not accepted")
    for part in [*reversed(path.parents), path]:
        try:
            info = part.lstat()
        except FileNotFoundError:
            raise ExportError(f"Missing path: {part}") from None
        if stat.S_ISLNK(info.st_mode):
            raise ExportError(f"Symlink is not allowed: {part}")
    info = path.lstat()
    if directory and not stat.S_ISDIR(info.st_mode):
        raise ExportError(f"Not a directory: {path}")
    if not directory and not stat.S_ISREG(info.st_mode):
        raise ExportError(f"Not a regular file: {path}")
    return path


def signature(info: os.stat_result) -> tuple:
    # Windows lstat/fstat disagree on legacy st_ctime semantics in some runtimes.
    # Identity, size, mtime and a second full SHA256 remain checked on all systems.
    changed_ns = info.st_ctime_ns if os.name != "nt" else None
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, changed_ns


def open_regular(path: Path):
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise ExportError(f"Not a regular file (symlinks forbidden): {path.name}")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    fd = os.open(path, flags)
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or signature(before) != signature(opened):
            raise ExportError(f"Source changed while opening: {path.name}")
        return os.fdopen(fd, "rb"), signature(opened)
    except BaseException:
        os.close(fd)
        raise


def assert_unchanged(path: Path, original: tuple) -> None:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or signature(info) != original:
        raise ExportError(f"Source changed during export: {path.name}; retry a stable UTC slice")


def inspect_csv(path: Path, kind: str) -> dict:
    """Validate the exact recorder header/row width; collect bounded metadata."""
    binary, original = open_regular(path)
    digest = hashlib.sha256()
    with binary:
        while True:
            chunk = binary.read(BLOCK)
            if not chunk:
                break
            digest.update(chunk)
        binary.seek(0)
        text = io.TextIOWrapper(binary, encoding="utf-8", newline="")
        try:
            reader = csv.reader(text, strict=True)
            header = next(reader, None)
            if header != list(HEADERS[kind]):
                raise ExportError(f"Unexpected header/columns in {path.name}: {header!r}")
            count = 0
            times = {key: {"min": None, "max": None} for key in ("T", "E", "recv_ms") if key in header}
            sessions: set[str] = set()
            for row in reader:
                if len(row) != len(header):
                    raise ExportError(f"Wrong column count: {path.name}, CSV line {reader.line_num}")
                count += 1
                for key, bounds in times.items():
                    value = row[header.index(key)]
                    if value:
                        try:
                            number = int(value)
                        except ValueError:
                            raise ExportError(f"Invalid {key}: {path.name}, CSV line {reader.line_num}") from None
                        bounds["min"] = number if bounds["min"] is None else min(bounds["min"], number)
                        bounds["max"] = number if bounds["max"] is None else max(bounds["max"], number)
                sessions.add(row[header.index("session")])
            # Detach so the outer binary context remains the single owner.
            text.detach()
        except BaseException:
            if not text.closed:
                try:
                    text.detach()
                except ValueError:
                    pass
            raise
    assert_unchanged(path, original)
    return {"name": path.name, "kind": kind, "bytes": original[2], "sha256": digest.hexdigest(),
            "rows": count, "timestamp_ms_ranges": times, "sessions": sorted(sessions),
            "_signature": original}


def copy_csv(zipped: zipfile.ZipFile, path: Path, meta: dict) -> None:
    """Stream the exact inspected bytes; detect append/rewrite before publication."""
    binary, original = open_regular(path)
    if original != meta["_signature"]:
        binary.close()
        raise ExportError(f"Source changed between validation and copy: {path.name}")
    digest = hashlib.sha256()
    with binary, zipped.open(path.name, "w", force_zip64=True) as target:
        while True:
            chunk = binary.read(BLOCK)
            if not chunk:
                break
            digest.update(chunk)
            target.write(chunk)
    assert_unchanged(path, original)
    if digest.hexdigest() != meta["sha256"]:
        raise ExportError(f"Source content changed during export: {path.name}")


def export(source: Path, start: date, end: date, outzip: Path) -> dict:
    source = checked_path(source, directory=True)
    if start > end:
        raise ExportError("--start-date must be <= --end-date")
    if not outzip.is_absolute() or outzip.suffix.lower() != ".zip":
        raise ExportError("--outzip must be an absolute .zip path")
    checked_path(outzip.parent, directory=True)
    if os.path.lexists(outzip):
        raise ExportError(f"Output already exists; never overwritten: {outzip}")
    selected = []
    missing = []
    day = start
    while day <= end:
        for symbol in SYMBOLS:
            for kind in HEADERS:
                name = f"{symbol}_{day:%Y%m%d}_{kind}.csv"
                path = source / name
                if os.path.lexists(path):
                    checked_path(path, directory=False)
                    meta = inspect_csv(path, kind)
                    meta.update(symbol=symbol, utc_filename_date=day.isoformat())
                    selected.append((path, meta))
                else:
                    missing.append(name)
        day += timedelta(days=1)
    if not selected:
        raise ExportError("No whitelisted public CSV files for the explicit dates")
    manifest = {
        "format": "weex-public-market-export-v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "symbols": list(SYMBOLS), "start_utc_filename_date": start.isoformat(),
        "end_utc_filename_date_inclusive": end.isoformat(),
        "date_selection": "UTC filename date; whole files; not an event-time cutoff",
        "expected_header_source": "services/weex_book/recorder.py v2 (13 October 2026)",
        "files": [{k: v for k, v in meta.items() if not k.startswith("_")} for _, meta in selected],
        "missing_whitelist_filenames": missing,
        "status": "packaging_only_not_execution_admission",
        "not_verified": ["snapshot/delta continuity across the requested boundary", "U/u gaps and trade completeness",
                         "minimum reconstructed book depth, staleness and cross-stream ordering",
                         "clock-domain offset and order submit/ACK/cancel latency", "actual maker fills or FIFO position"],
        "not_in_recorder_or_not_exported": ["native complete OHLCV candles", "mark/index and funding settlements",
                                             "versioned contract filters", "global receive sequence and monotonic time",
                                             "raw tradeSnapshot versus live frame type", "private execution/account data"],
        "notes": ["Missing events file can mean no session event occurred that UTC day; assess alongside depth/trades.",
                  "Include the preceding applied snapshot and complete following delta chain, not just the signal day.",
                  "Stable per-file reads do not establish a globally synchronized cutoff.",
                  "No recursive directory search; files outside the exact whitelist were not opened."]}
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".weex-public-export-", suffix=".tmp", dir=outzip.parent,
                                         delete=False) as temporary:
            temp_name = Path(temporary.name)
            with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6,
                                 allowZip64=True) as zipped:
                for path, meta in selected:
                    copy_csv(zipped, path, meta)
                zipped.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        # Same-directory publication of a completed archive, without overwrite.
        # Windows rename fails if the destination exists; POSIX rename would replace it.
        if os.name == "nt":
            os.rename(temp_name, outzip)
        else:
            os.link(temp_name, outzip)
    finally:
        if temp_name is not None:
            temp_name.unlink(missing_ok=True)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path, help="Absolute recorder market-data directory")
    parser.add_argument("--start-date", required=True, type=date.fromisoformat, help="YYYY-MM-DD, UTC filename date")
    parser.add_argument("--end-date", required=True, type=date.fromisoformat, help="YYYY-MM-DD, inclusive")
    parser.add_argument("--outzip", required=True, type=Path, help="Absolute NEW .zip path; parent must exist")
    args = parser.parse_args()
    try:
        manifest = export(args.source, args.start_date, args.end_date, args.outzip)
    except (ExportError, OSError, csv.Error, UnicodeError) as error:
        print(f"EXPORT FAILED: {error}", file=sys.stderr)
        return 2
    digest = hashlib.sha256()
    with args.outzip.open("rb") as archive:
        for chunk in iter(lambda: archive.read(BLOCK), b""):
            digest.update(chunk)
    print(json.dumps({"archive": str(args.outzip), "sha256": digest.hexdigest(),
                      "files": len(manifest["files"]), "missing_names": len(manifest["missing_whitelist_filenames"]),
                      "status": manifest["status"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
