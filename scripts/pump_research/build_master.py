"""Phase 0 — build the joined pump-feature master CSV.

Left-joins everything onto the 1m OHLCV grid by timestamp:
  - backtests/frozen/BTCUSDT_1m_2y.csv      OHLC + volume   (canonical 1m grid)
  - data/pump_research/BTCUSDT_taker_1m.csv  taker buy split, quote vol, trades
  - data/pump_research/BTCUSDT_funding.csv   8h funding   -> forward-filled to 1m
  - data/pump_research/BTCUSDT_oi_*.csv      5m open interest -> forward-filled

Output: data/pump_research/BTCUSDT_pump_features_1m.csv
Columns: ts,open,high,low,close,volume,quote_volume,trades,
         taker_buy_volume,taker_buy_pct,funding_rate,open_interest

This is the Phase-0 hand-off file for the colleague's Phase 1-4 work.

Usage:
    .venv/bin/python3 scripts/pump_research/build_master.py
"""
from __future__ import annotations

import glob
import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
PR = ROOT / "data" / "pump_research"
FROZEN_1M = ROOT / "backtests" / "frozen" / "BTCUSDT_1m_2y.csv"

log = logging.getLogger("build_master")


def _iso(ms: int) -> str:
    return datetime.utcfromtimestamp(ms / 1000).replace(tzinfo=timezone.utc).isoformat()


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S")

    # --- 1m OHLCV (canonical grid) ---
    ohlc = pd.read_csv(FROZEN_1M, dtype={"ts": "int64"})
    ohlc = ohlc.sort_values("ts").drop_duplicates("ts").reset_index(drop=True)
    log.info("ohlc: %d rows  %s .. %s", len(ohlc),
             _iso(int(ohlc.ts.iloc[0])), _iso(int(ohlc.ts.iloc[-1])))

    # --- taker (exact 1m join) ---
    taker = pd.read_csv(PR / "BTCUSDT_taker_1m.csv", dtype={"ts": "int64"})
    taker = taker.sort_values("ts").drop_duplicates("ts")
    taker = taker.rename(columns={"volume": "volume_taker"})
    m = ohlc.merge(taker[["ts", "quote_volume", "trades", "taker_buy_volume"]],
                   on="ts", how="left")
    log.info("taker: matched %d / %d 1m bars",
             m["taker_buy_volume"].notna().sum(), len(m))

    # --- funding (8h -> ffill) ---
    funding = pd.read_csv(PR / "BTCUSDT_funding.csv", dtype={"funding_time": "int64"})
    funding = funding.sort_values("funding_time").drop_duplicates("funding_time")
    funding = funding.rename(columns={"funding_time": "ts"})
    m = pd.merge_asof(m, funding, on="ts", direction="backward")
    log.info("funding: %d 8h points -> ffilled", len(funding))

    # --- open interest (5m -> ffill) ---
    oi_files = sorted(glob.glob(str(PR / "BTCUSDT_oi_*.csv")))
    if oi_files:
        oi = pd.read_csv(oi_files[-1], dtype={"ts": "int64"})
        oi = oi.sort_values("ts").drop_duplicates("ts")
        m = pd.merge_asof(m, oi, on="ts", direction="backward")
        cov = m["open_interest"].notna()
        first_oi = int(m.loc[cov, "ts"].iloc[0]) if cov.any() else 0
        log.info("oi: %s (%d points), 1m coverage from %s",
                 Path(oi_files[-1]).name, len(oi),
                 _iso(first_oi) if first_oi else "NONE")
    else:
        m["open_interest"] = pd.NA
        log.warning("oi: no BTCUSDT_oi_*.csv yet — column left empty")

    # --- derived ---
    m["taker_buy_pct"] = (m["taker_buy_volume"] / m["volume"]).round(4)

    cols = ["ts", "open", "high", "low", "close", "volume",
            "quote_volume", "trades", "taker_buy_volume", "taker_buy_pct",
            "funding_rate", "open_interest"]
    m = m[cols]

    out = PR / "BTCUSDT_pump_features_1m.csv"
    m.to_csv(out, index=False)
    log.info("MASTER: wrote %d rows x %d cols -> %s", len(m), len(cols), out)

    # coverage report
    for c in ["taker_buy_volume", "funding_rate", "open_interest"]:
        pct = 100.0 * m[c].notna().sum() / len(m)
        log.info("  coverage %-18s %.1f%%", c, pct)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
