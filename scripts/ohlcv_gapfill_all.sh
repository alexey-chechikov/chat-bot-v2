#!/bin/bash
# Hourly gap-fill: append latest 1m bars from Binance for all tracked symbols.
# Run by LaunchAgent com.bot7.ohlcv-gapfill.
set -euo pipefail

ROOT="/Users/alexeychechikov/code/bot7"
PY="$ROOT/.venv/bin/python"
SCRIPT="$ROOT/scripts/ohlcv_ingest.py"
SYMBOLS=("BTCUSDT" "ETHUSDT" "XRPUSDT")

# Target = open of a minute closed >= 60 s ago (UTC). ohlcv_ingest keeps bars with open <= target; target "now"
# kept the still-forming minute of every run (launchd StartInterval drifts, so any minute of the hour), truncated
# forever — the next run starts at last_ts+60s. 12.10.2026 review: now-2min floored to the minute (now-1min left
# only ~1 s after the bar close when the run started at :00 s; Binance/mac clock skew could still cut it).
TARGET_END="$(date -u -v-2M +%Y-%m-%dT%H:%M:00Z)"

cd "$ROOT"

for sym in "${SYMBOLS[@]}"; do
    echo "=== $sym  target=$TARGET_END ==="
    "$PY" "$SCRIPT" --symbol "$sym" --interval 1m --target-end "$TARGET_END" --workers 4 || {
        echo "FAILED: $sym (continuing with next symbol)"
    }
done

echo "=== gap-fill cycle done $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
