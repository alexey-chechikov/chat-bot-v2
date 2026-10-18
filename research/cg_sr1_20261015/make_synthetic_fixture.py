"""Write explicitly synthetic schema examples, not market observations."""
import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path

from cg_sr1 import MINUTE, SERIES


def build_example():
    base = int(datetime(2026, 10, 16, tzinfo=timezone.utc).timestamp() * 1000)
    metadata = {
        "schema_version": "cg-sr1-input-v0", "series_id": SERIES,
        "collection_role": "prospective-forward-v2", "synthetic": True,
        "provider": "CoinGlass", "model": "model1", "exchange": "Binance",
        "symbol": "BTCUSDT", "instrument": "perpetual", "lookback": "24h", "threshold": "0.85",
        "data_as_of_ms": base + 300 * MINUTE, "atr_seed_start_ms": base - 300 * MINUTE,
        "price_source": {"exchange": "Binance", "symbol": "BTCUSDT", "instrument": "perpetual",
                         "interval": "1m", "timezone": "UTC", "closed_only": True},
        "contract": {"tick_size": "0.1", "quantity_step": "0.001", "verified": True,
                     "verification_source": "SYNTHETIC CONTRACT ONLY; not an exchange specification",
                     "verified_at_ms": base - 600 * MINUTE},
    }
    snapshot = {
        "snapshot_id": "SYNTHETIC-example-A", "series_id": SERIES, "synthetic": True,
        "slot_ms": base, "capture_ms": base, "annotation_lock_ms": base, "status": "frozen",
        "source_record_complete": True, "source_record_fresh": True,
        "settings_match": True, "annotation_frozen": True, "frozen_spot": "100",
        "lower_zone": {"low": "97", "high": "98"},
        "upper_zone": {"low": "120", "high": "122"},
        "provenance_note": "Fabricated fixture. Not a website capture; never use as forward evidence.",
    }
    missed = {"snapshot_id": "SYNTHETIC-example-missed", "series_id": SERIES, "synthetic": True,
              "slot_ms": base - 360 * MINUTE, "status": "missed", "reason": "Fabricated missed-attempt example"}
    rows = [{"ts_ms": ts, "open": "100", "high": "100.2", "low": "99.8", "close": "100"}
            for ts in range(base - 300 * MINUTE, base + 300 * MINUTE, MINUTE)]
    for row in rows:
        if row["ts_ms"] == base + 15 * MINUTE:
            row.update(low="96", high="101")
    return metadata, [snapshot, missed], rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    metadata, snapshots, prices = build_example()
    names = [args.output_dir / name for name in ("metadata.synthetic.json", "snapshots.synthetic.json", "prices.synthetic.csv")]
    if any(path.exists() for path in names):
        parser.error("refusing to overwrite an existing fixture")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for path, value in zip(names[:2], (metadata, snapshots)):
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    with names[2].open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["ts_ms", "open", "high", "low", "close"])
        writer.writeheader()
        writer.writerows(prices)
    print("Wrote explicitly SYNTHETIC fixtures; no market or account data was used.")


if __name__ == "__main__":
    main()
