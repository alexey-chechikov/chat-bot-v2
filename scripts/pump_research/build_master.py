"""Phase 0 — build the joined pump-feature master CSV for `--symbol`.

Left-joins onto the 1m OHLCV grid by timestamp:
  - backtests/frozen/{SYMBOL}_1m_2y.csv      OHLC + volume   (canonical 1m grid)
  - data/pump_research/{SYMBOL}_taker_1m.csv  taker buy split, quote vol, trades
  - data/pump_research/{SYMBOL}_funding.csv   8h funding   -> forward-filled to 1m
  - data/pump_research/{SYMBOL}_oi_*.csv      5m open interest -> forward-filled

Output: data/pump_research/{SYMBOL}_pump_features_1m.csv
Columns: ts, open, high, low, close, volume, quote_volume, trades,
         taker_buy_volume, taker_buy_pct, funding_rate, open_interest

Usage:
    .venv/bin/python3 scripts/pump_research/build_master.py
    .venv/bin/python3 scripts/pump_research/build_master.py --symbol ETHUSDT
"""
from __future__ import annotations

import argparse
import glob
import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
PR = ROOT / "data" / "pump_research"

log = logging.getLogger("build_master")


def _iso(ms: int) -> str:
    return datetime.utcfromtimestamp(ms / 1000).replace(tzinfo=timezone.utc).isoformat()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="BTCUSDT")
    args = ap.parse_args()
    sym = args.symbol

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S")

    frozen_1m = ROOT / "backtests" / "frozen" / f"{sym}_1m_2y.csv"

    ohlc = pd.read_csv(frozen_1m, dtype={"ts": "int64"})
    ohlc = ohlc.sort_values("ts").drop_duplicates("ts").reset_index(drop=True)
    log.info("%s ohlc: %d rows  %s .. %s", sym, len(ohlc),
             _iso(int(ohlc.ts.iloc[0])), _iso(int(ohlc.ts.iloc[-1])))

    taker = pd.read_csv(PR / f"{sym}_taker_1m.csv", dtype={"ts": "int64"})
    taker = taker.sort_values("ts").drop_duplicates("ts")
    taker = taker.rename(columns={"volume": "volume_taker"})
    m = ohlc.merge(taker[["ts", "quote_volume", "trades", "taker_buy_volume"]],
                   on="ts", how="left")
    log.info("%s taker: matched %d / %d 1m bars", sym,
             m["taker_buy_volume"].notna().sum(), len(m))

    funding = pd.read_csv(PR / f"{sym}_funding.csv", dtype={"funding_time": "int64"})
    funding = funding.sort_values("funding_time").drop_duplicates("funding_time")
    funding = funding.rename(columns={"funding_time": "ts"})
    m = pd.merge_asof(m, funding, on="ts", direction="backward")
    log.info("%s funding: %d 8h points -> ffilled", sym, len(funding))

    oi_files = sorted(glob.glob(str(PR / f"{sym}_oi_*.csv")))
    if oi_files:
        oi = pd.read_csv(oi_files[-1], dtype={"ts": "int64"})
        oi = oi.sort_values("ts").drop_duplicates("ts")
        m = pd.merge_asof(m, oi, on="ts", direction="backward")
        cov = m["open_interest"].notna()
        first_oi = int(m.loc[cov, "ts"].iloc[0]) if cov.any() else 0
        log.info("%s oi: %s (%d points), 1m coverage from %s", sym,
                 Path(oi_files[-1]).name, len(oi),
                 _iso(first_oi) if first_oi else "NONE")
    else:
        m["open_interest"] = pd.NA
        log.warning("%s oi: no %s_oi_*.csv yet — column left empty", sym, sym)

    m["taker_buy_pct"] = (m["taker_buy_volume"] / m["volume"]).round(4)

    cols = ["ts", "open", "high", "low", "close", "volume",
            "quote_volume", "trades", "taker_buy_volume", "taker_buy_pct",
            "funding_rate", "open_interest"]
    m = m[cols]

    out = PR / f"{sym}_pump_features_1m.csv"
    m.to_csv(out, index=False)
    log.info("%s MASTER: wrote %d rows x %d cols -> %s", sym, len(m), len(cols), out)

    for c in ["taker_buy_volume", "funding_rate", "open_interest"]:
        pct = 100.0 * m[c].notna().sum() / len(m)
        log.info("  %s coverage %-18s %.1f%%", sym, c, pct)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
