"""Collector configuration — reads from environment variables."""
from __future__ import annotations

import os
from pathlib import Path

# ── Output path ───────────────────────────────────────────────────────────────
# Default = <repo_root>/market_live (cross-platform). Override via env on
# Windows-only deployments where repo lives elsewhere.

_REPO_ROOT = Path(__file__).resolve().parents[1]
LIVE_PATH = Path(os.environ.get("BOT7_LIVE_PATH", str(_REPO_ROOT / "market_live")))

# ── Symbols ───────────────────────────────────────────────────────────────────

SYMBOLS = ["BTCUSDT", "ETHUSDT", "XRPUSDT"]

# Hyperliquid uses coin names, not trading pair names
HL_SYMBOL_MAP: dict[str, str] = {
    "BTC": "BTCUSDT",
    "ETH": "ETHUSDT",
    "XRP": "XRPUSDT",
}
HL_COINS = list(HL_SYMBOL_MAP.keys())

# ── WebSocket URLs ────────────────────────────────────────────────────────────

BINANCE_WS_BASE = "wss://fstream.binance.com/market/stream"
BYBIT_WS_URL = "wss://stream.bybit.com/v5/public/linear"
HL_WS_URL = "wss://api.hyperliquid.xyz/ws"
BITMEX_WS_URL = "wss://ws.bitmex.com/realtime"
OKX_WS_URL = "wss://ws.okx.com:8443/ws/v5/public"

# ── Reconnect / backoff ───────────────────────────────────────────────────────

BACKOFF_MIN_S: float = 1.0
BACKOFF_MAX_S: float = 60.0
BACKOFF_FACTOR: float = 2.0
BACKOFF_JITTER: float = 0.20   # ±20% of computed delay

# ── Parquet buffer ────────────────────────────────────────────────────────────

BUFFER_MAX_EVENTS: int = 1000
FLUSH_INTERVAL_S: float = 60.0
PARQUET_COMPRESSION = "zstd"
PARQUET_COMPRESSION_LEVEL = 3
PARQUET_ROW_GROUP_SIZE = 50_000

# Writer rotation — prevents linear C++ heap growth from PyArrow row group metadata
# accumulation when a ParquetWriter is kept open for hours (TZ-048 root cause).
WRITER_MAX_ROWS: int = 100_000      # rows written before forced rotation
WRITER_MAX_BYTES: int = 50 * 1024 * 1024  # 50 MB file size before forced rotation
WRITER_MAX_AGE_S: float = 30 * 60.0       # 30 min before forced rotation

# BitMEX inverse contracts — only XBTUSD for now
BITMEX_SYMBOL_MAP: dict[str, str] = {
    "XBTUSD": "BTCUSDT",
}
BITMEX_TOPICS = [f"liquidation:{sym}" for sym in BITMEX_SYMBOL_MAP]

# OKX SWAP instruments → normalized symbol
OKX_SYMBOL_MAP: dict[str, str] = {
    "BTC-USDT-SWAP": "BTCUSDT",
    "ETH-USDT-SWAP": "ETHUSDT",
    "XRP-USDT-SWAP": "XRPUSDT",
}
OKX_INSTRUMENTS = list(OKX_SYMBOL_MAP.keys())

# ── Bybit / BitMEX ping interval ─────────────────────────────────────────────

BYBIT_PING_INTERVAL_S: float = 20.0
BITMEX_PING_INTERVAL_S: float = 25.0
