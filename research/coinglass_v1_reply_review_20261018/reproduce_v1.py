"""Offline synthetic reproductions against CoinGlass v1, commit 3db1d5e.

PASS means that the reported defect was reproduced, not that v1 is correct.
No market data, credentials, account state, collectors, or network calls are used.
The only output file is REPRODUCTIONS_V1.json next to this script.

Usage:
    python -B reproduce_v1.py
    python -B reproduce_v1.py --source /path/to/exact/outcomes.py

The exact source file is required and its SHA-256 is checked before execution.
NumPy and the Europe/Warsaw time-zone database are runtime dependencies of the
reviewed source, as they are in the original application.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys
import types
import urllib.request


COMMIT = "3db1d5eddbef5702f8ef7589d2436161c85f3d61"
SOURCE_SHA256 = "5aba15be7b7bd14401ad2d2d4aeead44f043d977c6107b8be4d2511ae5462978"
SOURCE_RELATIVE = "services/coinglass_web/outcomes.py"
SYNTHETIC_BASE = {
    "n": 100,
    "upper": 0.25,
    "lower": 0.25,
    "both": 0.25,
    "none": 0.25,
}


def _no_network(*args, **kwargs):
    raise AssertionError("Network access is forbidden in these reproductions")


@contextmanager
def reviewed_module(source: Path):
    """Execute only the verified source, with collector import and network stubbed."""
    raw = source.read_bytes()
    actual_sha = hashlib.sha256(raw).hexdigest()
    if actual_sha != SOURCE_SHA256:
        raise ValueError(f"Source SHA-256 mismatch: expected {SOURCE_SHA256}, got {actual_sha}")
    collector_key = "services.coinglass_web.collector"
    previous_collector = sys.modules.get(collector_key)
    previous_urlopen = urllib.request.urlopen
    collector = types.ModuleType(collector_key)
    # Merely constructs a Path; nothing is created or read at this location.
    collector.DIR = Path("__synthetic_state_never_accessed__")
    sys.modules[collector_key] = collector
    urllib.request.urlopen = _no_network
    module = types.ModuleType("coinglass_v1_under_review")
    module.__file__ = str(source.resolve())
    try:
        exec(compile(raw, str(source), "exec"), module.__dict__)
        yield module
    finally:
        urllib.request.urlopen = previous_urlopen
        if previous_collector is None:
            sys.modules.pop(collector_key, None)
        else:
            sys.modules[collector_key] = previous_collector


def reproduce_missing_morning(source: Path) -> dict:
    """The actual table() replaces a missing first morning by a later valid one."""
    records = [
        {
            "ts": "2026-10-18T05:00:00+00:00",
            "captured": "2026-10-18T05:00:30+00:00",
            "rules": "v1-2026-10-18",
            "outcome": "missing",
            "base": None,
        },
        {
            "ts": "2026-10-18T05:20:00+00:00",
            "captured": "2026-10-18T05:20:30+00:00",
            "rules": "v1-2026-10-18",
            "outcome": "upper",
            "base": SYNTHETIC_BASE,
        },
    ]

    class MemoryFile:
        def exists(self):
            return True

        def read_text(self, **kwargs):
            return "\n".join(json.dumps(row) for row in records)

    class MemoryDirectory:
        def __truediv__(self, filename):
            if filename != "outcomes.jsonl":
                raise AssertionError(f"Unexpected synthetic file access: {filename}")
            return MemoryFile()

    with reviewed_module(source) as module:
        module.DIR = MemoryDirectory()
        observed = module.table()
    assert observed["n"] == 1, observed
    assert observed["obs"]["upper"] == 1.0, observed
    assert observed["obs"]["none"] == 0.0, observed
    return {
        "id": "missing_first_morning_replaced",
        "status": "PASS",
        "meaning": "DEFECT_REPRODUCED",
        "source_lines": [214, 218],
        "input": {
            "first_capture_warsaw": "2026-10-18T07:00:30+02:00",
            "first_outcome": "missing",
            "later_capture_warsaw": "2026-10-18T07:20:30+02:00",
            "later_outcome": "upper",
        },
        "actual_table": observed,
        "required_behavior": (
            "Fix the first scheduled morning ID before quality/outcome filtering; "
            "record it as missing and do not replace it with the later capture."
        ),
    }


def reproduce_future_hour_atr(source: Path) -> dict:
    """Only a post-capture high changes; the actual evaluate() changes its ATR."""
    snapshot = {
        "ts": "2026-10-18T07:00:00+00:00",
        "levels_captured": "2026-10-18T07:00:23+00:00",
        "levels": {
            "price": 100.0,
            "zones_short": [{"lo": 110.0, "strength": 1}],
            "zones_long": [{"hi": 90.0, "strength": 1}],
        },
    }
    captured = datetime.fromisoformat(snapshot["levels_captured"])
    first_minute = (int(captured.timestamp()) // 60 + 1) * 60_000
    future_hour_open = first_minute // 3_600_000 * 3_600_000
    assert future_hour_open <= int(captured.timestamp() * 1000)
    assert future_hour_open + 3_600_000 > int(captured.timestamp() * 1000)
    future_high = 100.1
    requests = []

    def synthetic_klines(interval, start_ms, end_ms):
        requests.append({"interval": interval, "start_ms": start_ms, "end_ms": end_ms})
        if interval == "1m":
            return [
                [t, 100.0, 100.1, 99.9, 100.0, 0, t + 59_999]
                for t in range(start_ms, end_ms, 60_000)
            ]
        if interval != "1h":
            raise AssertionError(f"Unexpected interval: {interval}")
        # Reproduce the endpoint contract implied by _klines: inclusion is by
        # bar open time. The row also carries its later close time in column 6.
        first_open = (start_ms + 3_599_999) // 3_600_000 * 3_600_000
        return [
            [t, 100.0, future_high if t == future_hour_open else 100.1,
             99.9, 100.0, 0, t + 3_599_999]
            for t in range(first_open, end_ms, 3_600_000)
        ]

    with reviewed_module(source) as module:
        module._klines = synthetic_klines
        module.baseline = lambda *args, **kwargs: dict(SYNTHETIC_BASE)
        now = captured + timedelta(days=1, minutes=4)
        first_result = module.evaluate(snapshot, now)
        future_high = 1000.0
        changed_result = module.evaluate(snapshot, now)
    before = first_result["atr_1h"]
    after = changed_result["atr_1h"]
    assert abs(before - 0.2) < 1e-10, before
    assert abs(after - 64.47857142857141) < 1e-10, after
    assert after > before, (before, after)
    hourly_requests = [row for row in requests if row["interval"] == "1h"]
    assert hourly_requests and hourly_requests[0]["end_ms"] == first_minute
    assert future_hour_open < first_minute < future_hour_open + 3_600_000
    return {
        "id": "future_hour_changes_snapshot_atr",
        "status": "PASS",
        "meaning": "DEFECT_REPRODUCED",
        "source_lines": [48, 53, 174, 176],
        "input": {
            "captured_utc": captured.isoformat(),
            "evaluated_utc": now.isoformat(),
            "future_hour_open_utc": datetime.fromtimestamp(
                future_hour_open / 1000, timezone.utc).isoformat(),
            "future_hour_close_exclusive_utc": datetime.fromtimestamp(
                (future_hour_open + 3_600_000) / 1000, timezone.utc).isoformat(),
            "all_pre_capture_data_identical": True,
            "only_changed_field": "high of the still-open-at-capture hourly bar",
            "hourly_high_before": 100.1,
            "hourly_high_after": 1000.0,
        },
        "actual_atr_before": before,
        "actual_atr_after": after,
        "actual_du_atr_before": first_result["du_atr"],
        "actual_du_atr_after": changed_result["du_atr"],
        "required_behavior": (
            "Use only hourly bars closed no later than the capture cutoff; "
            "changing post-capture data must not change the snapshot ATR or baseline."
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parent
                        / "source_snapshot" / SOURCE_RELATIVE)
    args = parser.parse_args()
    results = [reproduce_missing_morning(args.source), reproduce_future_hour_atr(args.source)]
    payload = {
        "commit": COMMIT,
        "source_path": SOURCE_RELATIVE,
        "source_sha256": SOURCE_SHA256,
        "scope": "local synthetic only; no market data or network calls",
        "interpretation": "PASS means the defect is reproduced in the reviewed v1 source.",
        "passed": len(results),
        "failed": 0,
        "reproductions": results,
    }
    output = Path(__file__).resolve().with_name("REPRODUCTIONS_V1.json")
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": len(results), "failed": 0,
                      "meaning": "DEFECTS_REPRODUCED", "output": output.name}, ensure_ascii=False))


if __name__ == "__main__":
    main()
