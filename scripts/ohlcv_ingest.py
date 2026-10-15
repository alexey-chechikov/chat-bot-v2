"""OHLCV gap-fill ingest from Binance public REST API.

Fills the gap in existing backtests/frozen/ CSV files from the last stored
timestamp up to a target end time.

Usage:
    python scripts/ohlcv_ingest.py
    python scripts/ohlcv_ingest.py --target-end 2026-04-29T23:00:00Z
    python scripts/ohlcv_ingest.py --symbol BTCUSDT --target-end 2026-04-29T23:00:00Z
    python scripts/ohlcv_ingest.py --dry-run

Output:
    Appends rows to existing backtests/frozen/{SYMBOL}_1m_2y.csv
    Updates backtests/frozen/{SYMBOL}_1h_2y.csv (resample from 1m)
    Appends entry to docs/STATE/ohlcv_ingest_log.jsonl

Lock (GPT review 13.10, Q4): every 1m append and every 1h resample runs under the shared inter-process lock
<frozen_dir>/.ingest.lock (fcntl.flock LOCK_EX) — the same lock research/weex/repair_frozen_1m.py holds over
read -> verify -> replace. Under the lock the CSV path is reopened and its last ts re-read, so an append never lands
in a file that repair has just replaced, and rows already present are not appended twice.

1h (GPT review 15.10, §1 P2): an hour is written only from exactly 60 distinct minutes hour + k*60000, k=0..59, each
a valid OHLCV — the same validator (scripts/ohlc_grid.py) repair_frozen_1m uses. An hour old enough but incomplete
(59 minutes, duplicate + missing, off-grid stamp, invalid OHLC) is not written; it is counted in hours_rejected.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import sys
import time
import urllib.request
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
from pathlib import Path

try:
    import fcntl
except ImportError:  # Windows: no inter-process lock (repair_frozen_1m refuses to run there)
    fcntl = None

# encoding_safety: stdout UTF-8 for Windows terminal
if hasattr(sys.stdout, "buffer") and sys.stdout.encoding and \
        sys.stdout.encoding.lower().replace("-", "") not in ("utf8", "utf8bom"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))      # append, not insert: ROOT's folders must not shadow stdlib/site-packages

from scripts.ohlc_grid import HOUR, full_hours, hour_bar  # noqa: E402  (shared with repair_frozen_1m)

FROZEN_DIR = ROOT / "backtests" / "frozen"
LOG_PATH = ROOT / "docs" / "STATE" / "ohlcv_ingest_log.jsonl"

_API_URL = "https://api.binance.com/api/v3/klines"
_BATCH_BARS = 1000
_INTERVAL_MS: dict[str, int] = {"1s": 1_000, "1m": 60_000}
_SLEEP_BETWEEN_BATCHES = 0.12   # ~8 req/s, well under 1200/min Binance limit

log = logging.getLogger(__name__)

LOCK_NAME = ".ingest.lock"   # shared with research/weex/repair_frozen_1m.py — keep the names in sync


@contextmanager
def _frozen_lock(folder: Path):
    """Exclusive inter-process lock of the frozen dir (same file as repair_frozen_1m.frozen_lock)."""
    if fcntl is None:
        log.warning("fcntl unavailable — appending without the shared lock (do not run repair concurrently)")
        yield
        return
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / LOCK_NAME, "a+b") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def _utc_now_ms() -> int:
    return int(datetime.now(tz=timezone.utc).timestamp() * 1000)


def _ms_to_dt(ms: int) -> datetime:
    return datetime.utcfromtimestamp(ms / 1000).replace(tzinfo=timezone.utc)


def _parse_target(s: str) -> int:
    """Parse ISO-8601 string → epoch ms."""
    s = s.rstrip("Z")
    dt = datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _fetch_klines(symbol: str, start_ms: int, interval: str = "1m",
                  limit: int = _BATCH_BARS, retries: int = 6) -> list:
    url = (
        f"{_API_URL}?symbol={symbol}&interval={interval}"
        f"&startTime={start_ms}&limit={limit}"
    )
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.load(r)
        except Exception as exc:
            if attempt == retries - 1:
                raise RuntimeError(
                    f"Binance fetch failed {symbol} start={start_ms}: {exc}"
                ) from exc
            wait = min(2 ** attempt * 0.5, 30)
            log.warning("Retry %d/%d (%s): %s", attempt + 1, retries, url, exc)
            time.sleep(wait)
    return []


def _read_csv_last_ts(path: Path) -> int | None:
    """Return last ts (ms) in CSV without loading all rows into RAM."""
    if not path.exists():
        return None
    last_line = b""
    with open(path, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        read_back = min(512, size)
        f.seek(-read_back, 2)
        tail = f.read()
    lines = tail.split(b"\n")
    for line in reversed(lines):
        stripped = line.strip()
        if stripped and not stripped.startswith(b"ts"):
            last_line = stripped
            break
    if not last_line:
        return None
    try:
        return int(last_line.split(b",")[0])
    except (IndexError, ValueError):
        return None


def _append_rows_to_csv(path: Path, rows: list[list]) -> None:
    """Append rows [[ts_ms, o, h, l, c, v], ...] to existing CSV."""
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        for row in rows:
            w.writerow(row)


def _validate(path: Path, last_ts_before: int, target_end_ms: int) -> dict:
    """Read CSV, validate continuity/sanity/volume. Return result dict."""
    df = pd.read_csv(path, dtype={"ts": "int64"})
    # Only look at new portion
    new = df[df["ts"] > last_ts_before].copy()
    result: dict = {
        "total_rows": len(df),
        "new_rows": len(new),
        "last_ts": int(df["ts"].iloc[-1]) if len(df) else 0,
        "last_ts_dt": _ms_to_dt(int(df["ts"].iloc[-1])).isoformat() if len(df) else "",
        "pass": True,
        "issues": [],
    }

    if new.empty:
        result["issues"].append("no new rows appended")
        result["pass"] = False
        return result

    # 1. Last bar >= min(target_end, now) - 5min
    # If target_end is in the future, compare against current time instead
    effective_target_ms = min(target_end_ms, _utc_now_ms())
    last_bar_ms = int(new["ts"].iloc[-1])
    if last_bar_ms < effective_target_ms - 5 * 60_000:
        result["issues"].append(
            f"last bar {_ms_to_dt(last_bar_ms).isoformat()} < effective target "
            f"{_ms_to_dt(effective_target_ms).isoformat()} - 5min"
        )
        result["pass"] = False

    # 2. Gaps > 5 min in new portion
    ts_sorted = new["ts"].sort_values()
    diffs = ts_sorted.diff().dropna()
    big_gaps = diffs[diffs > 5 * 60_000]
    if not big_gaps.empty:
        result["issues"].append(
            f"{len(big_gaps)} gap(s) >5min in new bars"
        )
        # Not a hard fail — Binance sometimes returns sparse bars

    # 3. Sanity: no nan, no zero prices
    price_cols = ["open", "high", "low", "close"]
    for col in price_cols:
        if new[col].isna().any() or (new[col] == 0).any():
            result["issues"].append(f"nan/zero in {col}")
            result["pass"] = False

    # 4. Volume not all zero
    if (new["volume"] == 0).all():
        result["issues"].append("volume all zero in new bars — exchange offline?")
        result["pass"] = False

    result["gaps_gt5m"] = len(big_gaps)
    return result


def _fetch_batch_parallel(args: tuple) -> tuple[int, list]:
    """Worker for parallel batch fetching. Returns (start_ms, rows)."""
    symbol, start_ms, interval = args
    raw = _fetch_klines(symbol, start_ms, interval)
    rows = [
        [int(k[0]), float(k[1]), float(k[2]), float(k[3]),
         float(k[4]), float(k[5])]
        for k in raw
    ]
    return start_ms, rows


def fill_gap(
    symbol: str,
    interval: str,
    target_end_ms: int,
    frozen_dir: Path,
    dry_run: bool = False,
    start_ms: int | None = None,
    workers: int = 1,
) -> dict:
    """Fill gap (or initial download) in {symbol}_{interval}_2y.csv.

    start_ms: if provided and file doesn't exist, create file and download
              from start_ms. If None and file doesn't exist, skip.
    workers:  parallel fetch workers (use >1 for large initial downloads).
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    bar_ms = _INTERVAL_MS.get(interval)
    if bar_ms is None:
        raise ValueError(f"Unsupported interval: {interval!r}. Supported: {list(_INTERVAL_MS)}")

    csv_path = frozen_dir / f"{symbol}_{interval}_2y.csv"
    _initial = False

    if not csv_path.exists():
        if start_ms is None:
            log.warning("No file %s — skipping %s %s", csv_path, symbol, interval)
            return {"skipped": True, "reason": "file not found"}
        # Initial download: create file with header
        frozen_dir.mkdir(parents=True, exist_ok=True)
        if not dry_run:
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(["ts", "open", "high", "low", "close", "volume"])
            log.info("Created new file %s", csv_path)
        last_ts = start_ms - bar_ms  # sentinel: no prior data
        _initial = True
    else:
        last_ts = _read_csv_last_ts(csv_path)
        if last_ts is None:
            return {"skipped": True, "reason": "cannot read last ts"}
        if start_ms is not None and start_ms < last_ts:
            log.info("%s %s: file exists, ignoring --start-date (using last ts)", symbol, interval)

    next_start_ms = last_ts + bar_ms
    if next_start_ms >= target_end_ms:
        log.info("%s %s already up to date (last=%s)", symbol, interval,
                 _ms_to_dt(last_ts).isoformat())
        return {"skipped": False, "already_uptodate": True, "bars_fetched": 0}

    gap_bars = (target_end_ms - next_start_ms) // bar_ms
    all_batches = list(range(next_start_ms, target_end_ms, _BATCH_BARS * bar_ms))

    log.info(
        "%s %s: %s %d bars (%d batches) from %s → %s",
        symbol, interval,
        "downloading" if _initial else "filling",
        gap_bars, len(all_batches),
        _ms_to_dt(next_start_ms).isoformat(),
        _ms_to_dt(target_end_ms).isoformat(),
    )

    if dry_run:
        return {"dry_run": True, "expected_bars": gap_bars, "batches": len(all_batches)}

    all_rows: list[list] = []

    if workers > 1 and len(all_batches) > 20:
        # Parallel fetch for large downloads
        _args = [(symbol, b, interval) for b in all_batches]
        t0 = time.time()
        results: dict[int, list] = {}
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(_fetch_batch_parallel, a): a[1] for a in _args}
            done = 0
            for fut in as_completed(futs):
                b_start, rows = fut.result()
                results[b_start] = rows
                done += 1
                if done % 100 == 0 or done == len(all_batches):
                    elapsed = time.time() - t0
                    rate = done / elapsed if elapsed > 0 else 1
                    eta = (len(all_batches) - done) / rate
                    log.info("  %d/%d batches  %.1f b/s  ETA %.0fs",
                             done, len(all_batches), rate, eta)
        # Merge in order
        for b in all_batches:
            all_rows.extend(results.get(b, []))
    else:
        # Sequential fetch
        cursor = next_start_ms
        batch_num = 0
        while cursor < target_end_ms:
            raw = _fetch_klines(symbol, cursor, interval)
            rows = [
                [int(k[0]), float(k[1]), float(k[2]), float(k[3]),
                 float(k[4]), float(k[5])]
                for k in raw
            ]
            all_rows.extend(rows)
            if rows:
                cursor = rows[-1][0] + bar_ms
            else:
                break
            batch_num += 1
            if cursor < target_end_ms:
                time.sleep(_SLEEP_BETWEEN_BATCHES)

    # Filter, deduplicate, sort
    all_rows = [r for r in all_rows if r[0] <= target_end_ms]
    all_rows.sort(key=lambda r: r[0])
    # Dedup by ts
    seen: set[int] = set()
    deduped: list[list] = []
    for r in all_rows:
        if r[0] not in seen:
            seen.add(r[0])
            deduped.append(r)
    all_rows = deduped

    if all_rows:
        with _frozen_lock(frozen_dir):
            # reopen under the lock: repair may have replaced the file, another writer may have appended
            cur_last = _read_csv_last_ts(csv_path)
            if cur_last is not None:
                all_rows = [r for r in all_rows if r[0] > cur_last]
            if all_rows:
                _append_rows_to_csv(csv_path, all_rows)
        log.info("Wrote %d rows to %s", len(all_rows), csv_path)
    else:
        log.warning("No rows returned for %s %s", symbol, interval)

    validation = _validate(csv_path, last_ts, target_end_ms)
    return {
        "bars_fetched": len(all_rows),
        "batches": len(all_batches),
        "validation": validation,
    }


def fill_1h_from_1m(symbol: str, frozen_dir: Path, dry_run: bool = False) -> dict:
    """Resample 1m CSV → 1h, append missing hours to 1h CSV (under the shared frozen lock).
    Creates 1h file from scratch if it doesn't exist yet.
    """
    with (nullcontext() if dry_run else _frozen_lock(frozen_dir)):
        return _fill_1h_from_1m(symbol, frozen_dir, dry_run)


def _fill_1h_from_1m(symbol: str, frozen_dir: Path, dry_run: bool) -> dict:
    csv_1m = frozen_dir / f"{symbol}_1m_2y.csv"
    csv_1h = frozen_dir / f"{symbol}_1h_2y.csv"
    if not csv_1m.exists():
        return {"skipped": True, "reason": "1m file not found"}

    last_1m_ts = _read_csv_last_ts(csv_1m)
    if last_1m_ts is None:
        return {"skipped": True, "reason": "cannot read 1m timestamp"}

    _1h_new_file = not csv_1h.exists()
    last_1h_ts = _read_csv_last_ts(csv_1h) if not _1h_new_file else None

    if _1h_new_file:
        resample_from_ms = 0  # resample all 1m data
        log.info("%s 1h: creating from scratch (full resample)", symbol)
    else:
        # Need to resample from last_1h_ts + 1h onward
        resample_from_ms = last_1h_ts + 3_600_000  # type: ignore[operator]

    if not _1h_new_file and resample_from_ms > last_1m_ts:
        log.info("%s 1h already up to date", symbol)
        return {"skipped": False, "already_uptodate": True, "hours_added": 0}

    log.info("%s 1h: resampling from %s", symbol,
             _ms_to_dt(resample_from_ms).isoformat())

    df_1m = pd.read_csv(csv_1m, dtype={"ts": "int64"})
    df_new = df_1m[df_1m["ts"] >= resample_from_ms]
    if df_new.empty:
        return {"skipped": False, "hours_added": 0, "note": "no new 1m data"}

    # exact UTC grid (shared validator): 60 distinct minutes hour+k*60000, valid OHLCV; garbage -> NaN -> invalid
    ohlcv = df_new[["open", "high", "low", "close", "volume"]].apply(pd.to_numeric, errors="coerce")
    full, rejected = full_hours(zip(df_new["ts"].tolist(), ohlcv.to_numpy(dtype=float).tolist()), resample_from_ms)

    # age: an hour is closed once a minute >= hour + 1h exists (the last 1h may still be filling)
    cutoff_ms = last_1m_ts - HOUR
    ready = [h for h in sorted(full) if h <= cutoff_ms]
    rejected = [h for h in rejected if h <= cutoff_ms]
    if rejected:
        log.warning("%s 1h: %d hour(s) without exactly 60 valid minutes not written (first %s)",
                    symbol, len(rejected), _ms_to_dt(rejected[0]).isoformat())
    rej_info = {"hours_rejected": len(rejected),
                "rejected_sample": [_ms_to_dt(h).isoformat() for h in rejected[:5]]}

    if dry_run:
        return {"dry_run": True, "hours_to_add": len(ready), **rej_info}

    rows = [[h, *hour_bar(full[h])] for h in ready]
    if rows:
        if _1h_new_file:
            with open(csv_1h, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["ts", "open", "high", "low", "close", "volume"])
                w.writerows(rows)
            log.info("Created %s with %d 1h rows", csv_1h, len(rows))
        else:
            _append_rows_to_csv(csv_1h, rows)
            log.info("Appended %d 1h rows to %s", len(rows), csv_1h)

    return {"hours_added": len(rows), "last_1h_ts": _ms_to_dt(rows[-1][0]).isoformat() if rows else "", **rej_info}


def _write_log(entry: dict) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="OHLCV gap-fill / initial ingest")
    p.add_argument("--symbol", default="BTCUSDT")
    p.add_argument("--interval", "--resolution", default="1m",
                   choices=list(_INTERVAL_MS.keys()),
                   help="Bar resolution: 1s or 1m (default 1m)")
    p.add_argument("--target-end", default="2026-04-29T23:00:00Z",
                   help="ISO-8601 UTC end timestamp")
    p.add_argument("--start-date", default=None,
                   help="ISO-8601 UTC start for initial download (e.g. 2024-01-01). "
                        "Required for 1s if file doesn't exist (default 30 days back).")
    p.add_argument("--frozen-dir", default=str(FROZEN_DIR))
    p.add_argument("--workers", type=int, default=4,
                   help="Parallel fetch workers for large downloads (default 4)")
    p.add_argument("--dry-run", action="store_true",
                   help="Simulate only, do not write files")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    frozen_dir = Path(args.frozen_dir)
    target_end_ms = _parse_target(args.target_end)
    start_ms = _parse_target(args.start_date) if args.start_date else None
    symbol = args.symbol
    interval = args.interval

    # 1s downloads: 86,400 bars/day. 30 days ≈ 2.6M bars. Default to 30d if no start.
    if interval == "1s" and start_ms is None:
        default_start_ms = target_end_ms - 30 * 86_400_000
        start_ms = default_start_ms
        print(f"[1s] no --start-date given, defaulting to 30 days back: "
              f"{_ms_to_dt(start_ms).isoformat()}")

    print(f"OHLCV ingest: {symbol} {interval} → {args.target_end}")
    if start_ms:
        print(f"start_date:   {_ms_to_dt(start_ms).isoformat()}")
    print(f"frozen_dir:   {frozen_dir}")
    print(f"workers:      {args.workers}")
    if args.dry_run:
        print("DRY RUN — no files will be modified")

    ts_run = datetime.now(tz=timezone.utc).isoformat()

    # Fill primary interval gap (or initial download)
    result_1m = fill_gap(symbol, interval, target_end_ms, frozen_dir,
                         args.dry_run, start_ms, args.workers)
    print(f"\n{interval} result: {result_1m}")

    # Derive 1h from 1m (only when primary interval is 1m)
    if interval == "1m":
        result_1h = fill_1h_from_1m(symbol, frozen_dir, args.dry_run)
        print(f"1h result: {result_1h}")
    else:
        result_1h = {"skipped": True, "reason": f"interval={interval}, 1h derive only from 1m"}
        print(f"1h result: skipped (interval={interval})")

    # Validation summary
    val = result_1m.get("validation", {})
    if val:
        if val["pass"]:
            print(f"\nVALIDATION PASS  last bar: {val.get('last_ts_dt', '?')}  "
                  f"new_rows: {val.get('new_rows', '?')}  gaps>5m: {val.get('gaps_gt5m', 0)}")
        else:
            print(f"\nVALIDATION FAIL  issues: {val.get('issues', [])}")

    # Log
    if not args.dry_run:
        log_entry = {
            "ts_run": ts_run,
            "source": "binance_public_rest",
            "symbol": symbol,
            "target_end": args.target_end,
            "result_1m": result_1m,
            "result_1h": result_1h,
        }
        if val:
            log_entry["range_filled"] = {
                "from": _ms_to_dt(_read_csv_last_ts(frozen_dir / f"{symbol}_{interval}_2y.csv") or 0
                                   - (result_1m.get("bars_fetched", 0) * _INTERVAL_MS[interval])).isoformat(),
                "to": val.get("last_ts_dt", ""),
            }
            log_entry["bars_count"] = val.get("new_rows", 0)
            log_entry["gaps_found"] = val.get("gaps_gt5m", 0)
        _write_log(log_entry)
        print(f"\nLogged to {LOG_PATH}")

    return 0 if (not val or val.get("pass")) else 1


if __name__ == "__main__":
    sys.exit(main())
