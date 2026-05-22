"""Phase 0 — download Bybit open-interest history (free) for pump research.

Bybit v5 /market/open-interest gives much deeper history than Binance
(Binance OI hist is ~30d only). intervalTime=5min, 200 pts/call.

Strategy: split the frozen-CSV time range into independent 1000-min windows
(200 pts x 5min) and fetch them in parallel. If Bybit's 5min retention does
not reach 2 years back, the early windows simply return empty — the script
reports the actual covered range so we can decide on a 15m/1h fallback.

Output: data/pump_research/BTCUSDT_oi_5m.csv  (ts,open_interest)

Usage:
    .venv/bin/python3 scripts/pump_research/fetch_bybit_oi.py
    .venv/bin/python3 scripts/pump_research/fetch_bybit_oi.py --interval 15min
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "data" / "pump_research"
FROZEN_1M = ROOT / "backtests" / "frozen" / "BTCUSDT_1m_2y.csv"

OI_URL = "https://api.bybit.com/v5/market/open-interest"
PAGE = 200  # Bybit max points per call

INTERVAL_MS = {"5min": 300_000, "15min": 900_000, "30min": 1_800_000,
               "1h": 3_600_000, "4h": 14_400_000}

log = logging.getLogger("bybit_oi")


def _iso(ms: int) -> str:
    return datetime.utcfromtimestamp(ms / 1000).replace(tzinfo=timezone.utc).isoformat()


def _frozen_range() -> tuple[int, int]:
    with open(FROZEN_1M, "rb") as f:
        f.readline()
        first = f.readline()
        f.seek(0, 2)
        size = f.tell()
        f.seek(-min(512, size), 2)
        tail = f.read().split(b"\n")
    start = int(first.split(b",")[0])
    last = 0
    for line in reversed(tail):
        s = line.strip()
        if s and not s.startswith(b"ts"):
            last = int(s.split(b",")[0])
            break
    return start, last


def _get(url: str, retries: int = 6):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "pump-research"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception as exc:  # noqa: BLE001
            if attempt == retries - 1:
                raise RuntimeError(f"fetch failed {url}: {exc}") from exc
            time.sleep(min(2 ** attempt * 0.5, 30))
    return {}


def _fetch_window(args: tuple) -> list[tuple[int, float]]:
    start_ms, end_ms, interval = args
    url = (f"{OI_URL}?category=linear&symbol=BTCUSDT&intervalTime={interval}"
           f"&startTime={start_ms}&endTime={end_ms}&limit={PAGE}")
    data = _get(url)
    if not data or data.get("retCode") != 0:
        return []
    out = []
    for rec in data.get("result", {}).get("list", []):
        try:
            out.append((int(rec["timestamp"]), float(rec["openInterest"])))
        except (KeyError, ValueError, TypeError):
            continue
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--interval", default="5min", choices=list(INTERVAL_MS))
    p.add_argument("--workers", type=int, default=8)
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    step = INTERVAL_MS[args.interval]
    win = PAGE * step
    start_ms, end_ms = _frozen_range()
    log.info("target range: %s .. %s  interval=%s", _iso(start_ms), _iso(end_ms),
             args.interval)

    windows = [(w, min(w + win, end_ms), args.interval)
               for w in range(start_ms, end_ms, win)]
    log.info("oi: %d windows", len(windows))

    results: list[tuple[int, float]] = []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(_fetch_window, w): w[0] for w in windows}
        done = 0
        empty = 0
        for fut in as_completed(futs):
            rows = fut.result()
            if rows:
                results.extend(rows)
            else:
                empty += 1
            done += 1
            if done % 100 == 0 or done == len(windows):
                rate = done / max(time.time() - t0, 0.01)
                log.info("  oi %d/%d  %.0f w/s  ETA %.0fs  empty=%d",
                         done, len(windows), rate,
                         (len(windows) - done) / rate, empty)

    seen: set[int] = set()
    deduped = []
    for ts, oi in sorted(results, key=lambda x: x[0]):
        if ts not in seen:
            seen.add(ts)
            deduped.append((ts, oi))

    out = OUT_DIR / f"BTCUSDT_oi_{args.interval}.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ts", "open_interest"])
        w.writerows(deduped)

    if deduped:
        cov_lo, cov_hi = deduped[0][0], deduped[-1][0]
        log.info("oi: wrote %d rows -> %s", len(deduped), out)
        log.info("oi: ACTUAL COVERAGE %s .. %s", _iso(cov_lo), _iso(cov_hi))
        depth_days = (end_ms - cov_lo) / 86_400_000
        log.info("oi: depth back from end = %.0f days", depth_days)
        if cov_lo > start_ms + 7 * 86_400_000:
            log.warning("oi: 5m retention SHORT — missing %.0f days at the start; "
                        "consider --interval 15min or 1h",
                        (cov_lo - start_ms) / 86_400_000)
    else:
        log.error("oi: NO DATA returned")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
