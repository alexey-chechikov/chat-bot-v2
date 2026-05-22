"""Backfill 2-year pump-research feature data from Binance public REST (free).

Two outputs, both into data/pump_research/:
  1. BTCUSDT_taker_1m.csv  — per-minute volume / taker-buy split / trades.
     Binance spot kline field [9] = taker buy base asset volume. The frozen
     OHLCV CSV (backtests/frozen/BTCUSDT_1m_2y.csv) dropped this column;
     here we recover it so the pump catalog can compute taker imbalance.
  2. BTCUSDT_funding.csv    — 8h funding rate history (Binance USDM futures).

Range matches the frozen 1m CSV: 2024-05-15 .. 2026-05-22 (~1.06M minutes).

Usage:
    .venv/bin/python3 scripts/pump_research/backfill_features.py
    .venv/bin/python3 scripts/pump_research/backfill_features.py --skip-taker
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

SPOT_KLINES = "https://api.binance.com/api/v3/klines"
FUT_FUNDING = "https://fapi.binance.com/fapi/v1/fundingRate"

BATCH = 1000
MINUTE_MS = 60_000

log = logging.getLogger("backfill")


def _now_ms() -> int:
    return int(datetime.now(tz=timezone.utc).timestamp() * 1000)


def _iso(ms: int) -> str:
    return datetime.utcfromtimestamp(ms / 1000).replace(tzinfo=timezone.utc).isoformat()


def _get(url: str, retries: int = 6):
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.load(r)
        except Exception as exc:  # noqa: BLE001
            if attempt == retries - 1:
                raise RuntimeError(f"fetch failed {url}: {exc}") from exc
            time.sleep(min(2 ** attempt * 0.5, 30))
    return []


def _frozen_range() -> tuple[int, int]:
    """First and last ts (ms) of the frozen 1m CSV."""
    with open(FROZEN_1M, "rb") as f:
        first = f.readline()  # header
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


# --------------------------------------------------------------------------
# Taker volume (1m klines, spot)
# --------------------------------------------------------------------------
def _fetch_kline_batch(args: tuple) -> tuple[int, list]:
    start_ms, symbol = args
    url = f"{SPOT_KLINES}?symbol={symbol}&interval=1m&startTime={start_ms}&limit={BATCH}"
    raw = _get(url)
    rows = [
        # ts, volume, quote_volume, trades, taker_buy_volume
        [int(k[0]), float(k[5]), float(k[7]), int(k[8]), float(k[9])]
        for k in raw
    ]
    return start_ms, rows


def backfill_taker(symbol: str, start_ms: int, end_ms: int, workers: int) -> dict:
    batches = list(range(start_ms, end_ms + MINUTE_MS, BATCH * MINUTE_MS))
    log.info("taker: %d batches (%s .. %s)", len(batches), _iso(start_ms), _iso(end_ms))
    results: dict[int, list] = {}
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_fetch_kline_batch, (b, symbol)): b for b in batches}
        done = 0
        for fut in as_completed(futs):
            b_start, rows = fut.result()
            results[b_start] = rows
            done += 1
            if done % 100 == 0 or done == len(batches):
                rate = done / max(time.time() - t0, 0.01)
                log.info("  taker %d/%d  %.0f b/s  ETA %.0fs",
                         done, len(batches), rate, (len(batches) - done) / rate)
    all_rows: list[list] = []
    for b in batches:
        all_rows.extend(results.get(b, []))
    # dedup + sort + clip
    seen: set[int] = set()
    deduped: list[list] = []
    for r in sorted(all_rows, key=lambda x: x[0]):
        if r[0] not in seen and start_ms <= r[0] <= end_ms:
            seen.add(r[0])
            deduped.append(r)
    out = OUT_DIR / f"{symbol}_taker_1m.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ts", "volume", "quote_volume", "trades", "taker_buy_volume"])
        w.writerows(deduped)
    log.info("taker: wrote %d rows -> %s", len(deduped), out)
    return {"rows": len(deduped), "path": str(out)}


# --------------------------------------------------------------------------
# Funding rate (8h, USDM futures)
# --------------------------------------------------------------------------
def backfill_funding(symbol: str, start_ms: int, end_ms: int) -> dict:
    rows: list[list] = []
    cursor = start_ms
    while cursor < end_ms:
        url = (f"{FUT_FUNDING}?symbol={symbol}&startTime={cursor}"
               f"&endTime={end_ms}&limit={BATCH}")
        raw = _get(url)
        if not raw:
            break
        for rec in raw:
            rows.append([int(rec["fundingTime"]), float(rec["fundingRate"])])
        last_ft = int(raw[-1]["fundingTime"])
        if len(raw) < BATCH or last_ft >= end_ms:
            break
        cursor = last_ft + 1
        time.sleep(0.15)
    seen: set[int] = set()
    deduped = []
    for r in sorted(rows, key=lambda x: x[0]):
        if r[0] not in seen:
            seen.add(r[0])
            deduped.append(r)
    out = OUT_DIR / f"{symbol}_funding.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["funding_time", "funding_rate"])
        w.writerows(deduped)
    log.info("funding: wrote %d rows -> %s", len(deduped), out)
    return {"rows": len(deduped), "path": str(out)}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--symbol", default="BTCUSDT")
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--skip-taker", action="store_true")
    p.add_argument("--skip-funding", action="store_true")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    start_ms, end_ms = _frozen_range()
    log.info("frozen 1m range: %s .. %s", _iso(start_ms), _iso(end_ms))

    summary: dict = {}
    if not args.skip_funding:
        summary["funding"] = backfill_funding(args.symbol, start_ms, end_ms)
    if not args.skip_taker:
        summary["taker"] = backfill_taker(args.symbol, start_ms, end_ms, args.workers)

    log.info("DONE %s", json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
