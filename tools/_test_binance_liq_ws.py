"""Test Binance liquidation WS endpoints — find which one actually delivers.

Tries 2 streams for 60 seconds each, prints what's received.

Stream 1: per-symbol force order (current code)
  wss://fstream.binance.com/market/ws/btcusdt@forceOrder

Stream 2: all-market force orders (suspected correct)
  wss://fstream.binance.com/market/ws/!forceOrder@arr
"""
from __future__ import annotations

import json
import sys
import time

import websocket  # websocket-client

STREAMS = [
    ("per-symbol", "wss://fstream.binance.com/market/ws/btcusdt@forceOrder"),
    ("all-market", "wss://fstream.binance.com/market/ws/!forceOrder@arr"),
]
DURATION_SEC = 45


def test_stream(name: str, url: str) -> None:
    print(f"\n=== Testing {name} ===", flush=True)
    print(f"URL: {url}", flush=True)
    try:
        ws = websocket.WebSocket()
        ws.connect(url, timeout=10)
        ws.settimeout(3)  # short — so we can check loop deadline regularly
        print(f"[{name}] connected", flush=True)
    except Exception as exc:
        print(f"[{name}] connect failed: {exc}", flush=True)
        return

    start = time.time()
    msg_count = 0
    ping_count = 0
    btc_count = 0
    last_msg_time = start
    last_status = start

    while time.time() - start < DURATION_SEC:
        # Periodic status so we know it's alive
        if time.time() - last_status > 10:
            elapsed = int(time.time() - start)
            print(f"[{name}] {elapsed}s elapsed: msgs={msg_count} btc={btc_count} pings={ping_count}", flush=True)
            last_status = time.time()
        try:
            opcode, frame_data = ws.recv_data()
        except (websocket.WebSocketTimeoutException, TimeoutError, OSError):
            # short recv timeout — continue loop (re-check deadline + status)
            continue

        if opcode == 0x9:  # ping
            ping_count += 1
            try:
                ws.pong(frame_data)
            except Exception as exc:
                print(f"[{name}] pong failed: {exc}")
                break
            continue

        if opcode != 0x1 and opcode != 0x2:
            continue

        msg_count += 1
        last_msg_time = time.time()
        try:
            data = json.loads(frame_data)
        except Exception:
            continue

        # For both streams, data shape: {"e": "forceOrder", "o": {"s": "BTCUSDT", "S": "SELL", "q": "0.5", ...}}
        order = data.get("o", {})
        symbol = order.get("s", "?")
        side = order.get("S", "?")
        qty = order.get("q", "?")
        price = order.get("p", "?")
        if symbol == "BTCUSDT":
            btc_count += 1
            print(f"[{name}] BTCUSDT liq: side={side} qty={qty} price={price}")
        else:
            # All-market stream — log every 10th non-BTC to confirm stream alive
            if msg_count % 10 == 0:
                print(f"[{name}] (other) {symbol} {side} qty={qty}")

    elapsed = time.time() - start
    print(f"\n[{name}] DONE in {elapsed:.0f}s")
    print(f"  total messages: {msg_count}")
    print(f"  BTCUSDT liquidations: {btc_count}")
    print(f"  ping events: {ping_count}")
    print(f"  silence since last msg: {time.time() - last_msg_time:.0f}s")

    try:
        ws.close()
    except Exception:
        pass


def main() -> int:
    for name, url in STREAMS:
        test_stream(name, url)
    print("\n=== Summary ===")
    print("Stream which delivered BTCUSDT events = correct endpoint")
    return 0


if __name__ == "__main__":
    sys.exit(main())
