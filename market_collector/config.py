from __future__ import annotations
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]

MARKET_LIVE_DIR: Path = _ROOT / "market_live"
SIGNALS_CSV: Path = MARKET_LIVE_DIR / "signals.csv"
OHLCV_1M_CSV: Path = MARKET_LIVE_DIR / "market_1m.csv"
OHLCV_15M_CSV: Path = MARKET_LIVE_DIR / "market_15m.csv"
OHLCV_1H_CSV: Path = MARKET_LIVE_DIR / "market_1h.csv"
LIQUIDATIONS_CSV: Path = MARKET_LIVE_DIR / "liquidations.csv"  # legacy: BTCUSDT only
# WS liveness beat — пишется на КАЖДОМ тике loop'а (даже когда ликвидаций нет).
# stale_monitor смотрит сюда, а не на mtime liquidations.csv: на тихом рынке
# ликвидаций нет → csv стареет → ложный STALE при живых WS (флап 19–20.06).
LIQ_HEARTBEAT_PATH: Path = _ROOT / "state" / "liq_stream_heartbeat.json"
PID_DIR: Path = _ROOT / "market_collector" / "run"

SYMBOL = "BTCUSDT"
# 2026-05-13: multi-asset liq collection. Каждый символ в отдельном CSV
# (liquidations.csv остаётся BTCUSDT для backwards-compat). Доп. символы —
# liquidations_ETHUSDT.csv, liquidations_XRPUSDT.csv и т.д.
LIQ_SYMBOLS: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "XRPUSDT")
# OKX uses different naming convention (dashes + -SWAP suffix).
OKX_INST_MAP = {
    "BTCUSDT": "BTC-USDT-SWAP",
    "ETHUSDT": "ETH-USDT-SWAP",
    "XRPUSDT": "XRP-USDT-SWAP",
}


def liq_csv_for(symbol: str) -> Path:
    """Per-symbol liquidations CSV. BTCUSDT keeps the legacy name."""
    if symbol == "BTCUSDT":
        return LIQUIDATIONS_CSV
    return MARKET_LIVE_DIR / f"liquidations_{symbol}.csv"
BYBIT_KLINE_URL = "https://api.bybit.com/v5/market/kline"
BYBIT_WS_URL = "wss://stream.bybit.com/v5/public/linear"
# 2026-05-12: switched from per-symbol `btcusdt@forceOrder` to all-market
# `!forceOrder@arr`. Per-symbol stream is too quiet (~0 msgs/45s in tests).
# All-market delivers thousands of events per hour across all pairs;
# liquidations._run_binance_ws filters symbol=BTCUSDT client-side.
# Historical evidence: bybit_ws populated 2195 rows over 24h, binance_ws 0 rows.
BINANCE_WS_URL = "wss://fstream.binance.com/ws/!forceOrder@arr"

# 2026-05-12 (Phase 1.1b): OKX public WebSocket for liquidation orders.
# Subscribe to liquidation-orders channel with instType=SWAP, filter
# instId="BTC-USDT-SWAP" client-side.
OKX_WS_URL = "wss://ws.okx.com:8443/ws/v5/public"

# (label, bybit_interval_str, cycle_sec, csv_path)
OHLCV_INTERVALS = [
    ("1m",  "1",  60,  OHLCV_1M_CSV),
    ("15m", "15", 300, OHLCV_15M_CSV),
    ("1h",  "60", 900, OHLCV_1H_CSV),
]
OHLCV_BACKFILL_CANDLES = 200

# Trigger thresholds
LIQ_CASCADE_BTC_THRESHOLD: float = 10.0  # ASSUMPTION: tune by observation
LIQ_CASCADE_WINDOW_SEC: int = 60
RSI_1H_OVERBOUGHT: float = 70.0
RSI_1H_OVERSOLD:   float = 30.0
RSI_15M_OVERBOUGHT: float = 75.0
RSI_15M_OVERSOLD:   float = 25.0
LEVEL_LOOKBACK: int = 20
ROUND_STEP: int = 1000
SIGNAL_DEDUP_SEC: int = 900  # 15 min

# WebSocket reconnect backoff
WS_RECONNECT_BASE_SEC: float = 1.0
WS_RECONNECT_MAX_SEC: float = 60.0
