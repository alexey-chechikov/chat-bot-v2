"""Only fabricated manual-card inputs; no market/website/account access."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

from scenario_card import MINUTE, M15


BASE = int(datetime(2026, 10, 16, tzinfo=timezone.utc).timestamp() * 1000)


def sample_input():
    rows = [{"ts_ms": ts, "open": "100", "high": "100.2", "low": "99.8", "close": "100"}
            for ts in range(BASE - 300 * MINUTE, BASE + 30 * MINUTE, M15)]
    rows[-1].update(low="96", high="101")
    return {
        "schema_version": "cg-manual-scenario-v1", "synthetic": True,
        "data_asof_ms": BASE + 30 * MINUTE, "attempt_state": "unused",
        "atr_seed_start_ms": BASE - 300 * MINUTE,
        "price_source": {"exchange": "Binance", "symbol": "BTCUSDT", "market": "perpetual", "timezone": "UTC"},
        "snapshot": {"snapshot_id": "SYNTHETIC-NOT-A-WEBSITE-CAPTURE", "capture_ms": BASE,
                     "annotation_lock_ms": BASE, "source_asof_ms": BASE - 10_000, "lag_status": "known",
                     "source_record_complete": True, "source_record_fresh": True, "annotation_frozen": True,
                     "settings": {"provider": "CoinGlass", "product": "liquidation_heatmap", "model": "model1",
                                  "exchange": "Binance", "symbol": "BTCUSDT", "market": "perpetual", "lookback": "24h", "threshold": "0.85"},
                     "frozen_spot": "100", "lower_zone": {"low": "97", "high": "98"},
                     "upper_zone": {"low": "120", "high": "122"}},
        "contract": {"exchange": "Binance", "symbol": "BTCUSDT", "market": "perpetual",
                     "tick_size": "0.1", "quantity_step": "0.001", "min_quantity": "0.001", "min_notional": "5", "verified": True,
                     "verified_at_ms": BASE - 600 * MINUTE,
                     "verification_source": "SYNTHETIC CONTRACT ONLY; not an actual exchange specification"},
        "ohlc_15m": rows, "ohlc_1m": [],
        "next_available_quote": {"price": "100", "received_ms": BASE + 30 * MINUTE,
                                 "signal_close_ms": BASE + 30 * MINUTE, "exchange": "Binance", "symbol": "BTCUSDT",
                                 "market": "perpetual", "side": "BUY", "executable": True,
                                 "first_available_after_close": True},
        "note": "EVERY VALUE IS FABRICATED. This is not an observed map or backtest.",
    }


def examples():
    ready = sample_input()
    waiting = deepcopy(ready)
    waiting.update(data_asof_ms=BASE + 15 * MINUTE, next_available_quote=None)
    waiting["ohlc_15m"] = waiting["ohlc_15m"][:-1]
    conditional = deepcopy(ready); conditional["next_available_quote"] = None
    unknown = deepcopy(ready)
    unknown["snapshot"].update(source_asof_ms=None, lag_status="unknown", source_record_fresh=None)
    refused = deepcopy(ready); refused["next_available_quote"]["price"] = "110"
    return {"wait": waiting, "conditional": conditional, "ready_research": ready,
            "unknown_lag": unknown, "no_trade": refused}


def main():
    target = Path(__file__).parent / "synthetic_inputs"
    target.mkdir(exist_ok=True)
    for name, data in examples().items():
        with (target / f"{name}.json").open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    print("Wrote 5 explicitly SYNTHETIC inputs; no source was accessed.")


if __name__ == "__main__":
    main()
