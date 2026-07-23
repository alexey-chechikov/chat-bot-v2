"""WebSocket liquidation streams — Bybit + Binance + OKX, multi-symbol.

2026-05-13: расширено на ETH/XRP. Каждый символ пишется в свой CSV
(liquidations.csv = BTC legacy, liquidations_ETHUSDT.csv etc.).
"""
from __future__ import annotations

import csv
import json
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from market_collector.config import (
    BINANCE_WS_URL,
    BYBIT_WS_URL,
    LIQ_HEARTBEAT_PATH,
    LIQUIDATIONS_CSV,
    LIQ_SYMBOLS,
    OKX_INST_MAP,
    OKX_WS_URL,
    WS_RECONNECT_BASE_SEC,
    WS_RECONNECT_MAX_SEC,
    liq_csv_for,
)

logger = logging.getLogger(__name__)
LIQ_HEADERS = ["ts_utc", "exchange", "side", "qty", "price"]
_lock = threading.Lock()

# Heartbeat троттлится: пишем не чаще раза в 20с (3 потока стучат на каждом
# recv-таймауте). Файл стареет ТОЛЬКО если все WS легли в reconnect-цикл.
_HB_MIN_INTERVAL_SEC = 20.0
_hb_lock = threading.Lock()
_hb_last_write = 0.0


def _touch_heartbeat() -> None:
    global _hb_last_write
    now = time.time()
    with _hb_lock:
        if now - _hb_last_write < _HB_MIN_INTERVAL_SEC:
            return
        _hb_last_write = now
    try:
        LIQ_HEARTBEAT_PATH.parent.mkdir(parents=True, exist_ok=True)
        LIQ_HEARTBEAT_PATH.write_text(
            json.dumps({"ts": _ts_utc_now()}), encoding="utf-8")
    except OSError:
        logger.warning("liq.heartbeat_write_failed", exc_info=True)

# OKX *-USDT-SWAP contract sizes (per OKX docs).
# Native qty = contracts × contract_size.
OKX_CONTRACT_SIZE = {
    "BTC-USDT-SWAP": 0.01,
    "ETH-USDT-SWAP": 0.1,
    "XRP-USDT-SWAP": 100.0,
}
OKX_INST_REVERSE = {v: k for k, v in OKX_INST_MAP.items()}

# Legacy var kept for downstream compat (cascade_filter probably reads it)
OKX_CONTRACT_SIZE_BTC = OKX_CONTRACT_SIZE["BTC-USDT-SWAP"]


def _ts_utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _write_liq(symbol: str, row: dict) -> None:
    """Append liq row to per-symbol CSV. BTCUSDT keeps legacy file path."""
    csv_path = liq_csv_for(symbol)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        is_new = not csv_path.exists()
        with csv_path.open("a", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=LIQ_HEADERS, extrasaction="ignore")
            if is_new:
                writer.writeheader()
            writer.writerow(row)
            fh.flush()


def _run_bybit_ws(stop_event: threading.Event) -> None:
    """Bybit liquidation WS с keepalive ping каждые 20с (per Bybit docs)."""
    import websocket  # websocket-client

    backoff = WS_RECONNECT_BASE_SEC
    while not stop_event.is_set():
        try:
            ws = websocket.WebSocket()
            ws.connect(BYBIT_WS_URL, timeout=10)
            # Read timeout — без него recv() блокируется навсегда, idle connection
            # закрывается сервером и наша сторона не узнаёт.
            ws.settimeout(30)
            sub_args = [f"allLiquidation.{s}" for s in LIQ_SYMBOLS]
            ws.send(json.dumps({"op": "subscribe", "args": sub_args}))
            backoff = WS_RECONNECT_BASE_SEC
            last_ping = time.time()
            logger.info("bybit_ws.connected")
            while not stop_event.is_set():
                _touch_heartbeat()  # WS жив, даже если ликвидаций нет
                # Keepalive: Bybit требует ping каждые 20s, иначе закрывает.
                if time.time() - last_ping >= 20:
                    try:
                        ws.send(json.dumps({"op": "ping"}))
                        last_ping = time.time()
                    except Exception:
                        logger.warning("bybit_ws.ping_failed", exc_info=True)
                        break
                try:
                    msg = ws.recv()
                except (websocket.WebSocketTimeoutException, TimeoutError, OSError):
                    # Read timeout — норма, продолжаем (даём шанс отправить ping).
                    # OSError ловит низкоуровневые SSL timeouts.
                    continue
                if not msg:
                    continue
                try:
                    data = json.loads(msg)
                    # Pong от Bybit на наш ping — пропускаем тихо.
                    if data.get("op") == "pong" or data.get("ret_msg") == "pong":
                        continue
                    topic = data.get("topic", "")
                    if topic.startswith("allLiquidation."):
                        symbol = topic.split(".", 1)[1]
                        if symbol not in LIQ_SYMBOLS:
                            continue
                        liq_data = data.get("data", [])
                        if isinstance(liq_data, dict):
                            liq_data = [liq_data]
                        for liq in liq_data:
                            if not isinstance(liq, dict):
                                continue
                            # 2026-07-23: у топика allLiquidation поле S — это
                            # сторона ПОЗИЦИИ, а не ордера. Прежний маппинг
                            # (sell→long, как для старого топика liquidation)
                            # переворачивал метки. Проверено на 7д/150ч: с ним
                            # метка «long» доминировала на РОСТЕ цены (+0.167%),
                            # хотя лонги выносит на падении; у okx (корректный
                            # маппинг) — ровно наоборот (−0.186%).
                            raw_side = liq.get("S") or liq.get("side", "")
                            side = "short" if str(raw_side).lower() == "sell" else "long"
                            qty = liq.get("v") or liq.get("size", "")
                            price = liq.get("p") or liq.get("price", "")
                            _write_liq(symbol, {
                                "ts_utc": _ts_utc_now(),
                                "exchange": "bybit",
                                "side": side,
                                "qty": qty,
                                "price": price,
                            })
                except Exception:
                    logger.warning("bybit_ws.parse_error", exc_info=True)
                    continue  # parse-ошибка не должна закрывать соединение
            try:
                ws.close()
            except Exception:
                pass
        except Exception:
            logger.warning("bybit_ws.connect_failed backoff=%.1fs", backoff, exc_info=True)
            stop_event.wait(backoff)
            backoff = min(backoff * 2, WS_RECONNECT_MAX_SEC)


def _run_binance_ws(stop_event: threading.Event) -> None:
    """Binance forceOrder WS — отвечаем pong на их ping (per Binance docs)."""
    import websocket  # websocket-client

    backoff = WS_RECONNECT_BASE_SEC
    while not stop_event.is_set():
        try:
            ws = websocket.WebSocket()
            ws.connect(BINANCE_WS_URL, timeout=10)
            ws.settimeout(190)  # Binance ping interval ≈ 3 min
            backoff = WS_RECONNECT_BASE_SEC
            logger.info("binance_ws.connected")
            while not stop_event.is_set():
                _touch_heartbeat()  # WS жив, даже если ликвидаций нет
                try:
                    opcode, frame_data = ws.recv_data()
                except (websocket.WebSocketTimeoutException, TimeoutError, OSError):
                    # Read timeout — норма (даём шанс отправить pong/продолжить).
                    # OSError ловит низкоуровневые SSL timeouts на Windows.
                    continue
                # Binance шлёт ping (opcode 0x9) — отвечаем pong (opcode 0xA)
                if opcode == 0x9:
                    try:
                        ws.pong(frame_data)
                    except Exception:
                        logger.warning("binance_ws.pong_failed", exc_info=True)
                        break
                    continue
                if opcode != 0x1 and opcode != 0x2:  # not text/binary
                    continue
                if not frame_data:
                    continue
                try:
                    data = json.loads(frame_data)
                    order = data.get("o", {})
                    symbol = order.get("s")
                    if symbol not in LIQ_SYMBOLS:
                        continue
                    side = "long" if order.get("S") == "SELL" else "short"
                    _write_liq(symbol, {
                        "ts_utc": _ts_utc_now(),
                        "exchange": "binance",
                        "side": side,
                        "qty": order.get("q", ""),
                        "price": order.get("p", ""),
                    })
                except Exception:
                    logger.warning("binance_ws.parse_error", exc_info=True)
                    continue
            try:
                ws.close()
            except Exception:
                pass
        except Exception:
            logger.warning("binance_ws.connect_failed backoff=%.1fs", backoff, exc_info=True)
            stop_event.wait(backoff)
            backoff = min(backoff * 2, WS_RECONNECT_MAX_SEC)


def _run_okx_ws(stop_event: threading.Event) -> None:
    """OKX liquidation-orders WS (perpetual swaps).

    Subscribes to liquidation-orders channel with instType=SWAP, filters
    instId=BTC-USDT-SWAP client-side (single-symbol CSV schema).

    OKX side convention (per docs):
      - side="sell" → liquidation of LONG (exchange selling longs to close them)
      - side="buy"  → liquidation of SHORT
    Matches Binance/Bybit semantics where side stored in CSV is the
    direction of the LIQUIDATED position (long/short), not the order side.

    Keepalive: OKX disconnects after 30s idle. Send literal "ping" every 20s,
    expect literal "pong" back.
    """
    import websocket  # websocket-client

    backoff = WS_RECONNECT_BASE_SEC
    while not stop_event.is_set():
        try:
            ws = websocket.WebSocket()
            ws.connect(OKX_WS_URL, timeout=10)
            # Short recv timeout so we wake up regularly and can send keepalive
            # pings. OKX closes connection after 30s of silence; we need to
            # tick at least every 25s. With 5s timeout we wake up 6x per ping
            # cycle — plenty of headroom.
            ws.settimeout(5)
            ws.send(json.dumps({
                "op": "subscribe",
                "args": [{"channel": "liquidation-orders", "instType": "SWAP"}],
            }))
            backoff = WS_RECONNECT_BASE_SEC
            last_ping = time.time()
            logger.info("okx_ws.connected")
            while not stop_event.is_set():
                _touch_heartbeat()  # WS жив, даже если ликвидаций нет
                if time.time() - last_ping >= 20:
                    try:
                        ws.send("ping")
                        last_ping = time.time()
                    except Exception:
                        logger.warning("okx_ws.ping_failed", exc_info=True)
                        break
                try:
                    msg = ws.recv()
                except (websocket.WebSocketTimeoutException, TimeoutError, OSError):
                    # Normal recv-idle path: loop back to top, send ping if due.
                    continue
                except websocket.WebSocketConnectionClosedException:
                    # OKX dropped us (e.g. 24h cycle, maintenance). Break to
                    # outer loop for clean reconnect — log as info, not error,
                    # this is expected periodic behavior.
                    logger.info("okx_ws.connection_closed_reconnecting")
                    break
                if not msg:
                    continue
                # OKX sends literal "pong" string in response to "ping"
                if msg == "pong":
                    continue
                try:
                    data = json.loads(msg)
                except Exception:
                    continue
                # Subscription confirmation or other meta — skip
                if "data" not in data:
                    continue
                # data[] contains one or more events; each event has details[]
                for event in data.get("data", []) or []:
                    inst_id = event.get("instId") or event.get("instFamily")
                    if inst_id and inst_id not in OKX_CONTRACT_SIZE:
                        continue
                    for d in event.get("details", []) or []:
                        d_inst = d.get("instId") or inst_id
                        if not d_inst or d_inst not in OKX_CONTRACT_SIZE:
                            continue
                        symbol = OKX_INST_REVERSE.get(d_inst)
                        if symbol not in LIQ_SYMBOLS:
                            continue
                        try:
                            side_raw = d.get("side", "")
                            side = "long" if side_raw == "sell" else "short"
                            sz_raw = d.get("sz", "")
                            contract_size = OKX_CONTRACT_SIZE[d_inst]
                            try:
                                qty_native = float(sz_raw) * contract_size
                                qty_out = f"{qty_native:.6f}"
                            except (TypeError, ValueError):
                                qty_out = sz_raw
                            _write_liq(symbol, {
                                "ts_utc": _ts_utc_now(),
                                "exchange": "okx",
                                "side": side,
                                "qty": qty_out,
                                "price": d.get("bkPx", ""),
                            })
                        except Exception:
                            logger.warning("okx_ws.parse_error", exc_info=True)
                            continue
            try:
                ws.close()
            except Exception:
                pass
        except Exception:
            logger.warning("okx_ws.connect_failed backoff=%.1fs", backoff, exc_info=True)
            stop_event.wait(backoff)
            backoff = min(backoff * 2, WS_RECONNECT_MAX_SEC)


def start_liquidation_streams(stop_event: threading.Event) -> list[threading.Thread]:
    threads: list[threading.Thread] = []
    for name, target in [
        ("liq-bybit", _run_bybit_ws),
        ("liq-binance", _run_binance_ws),
        ("liq-okx", _run_okx_ws),
    ]:
        t = threading.Thread(target=target, args=(stop_event,), daemon=True, name=name)
        t.start()
        threads.append(t)
    return threads
