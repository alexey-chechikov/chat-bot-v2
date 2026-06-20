"""TV webhook HTTP receiver (stdlib http.server).

POST /tv/<token>/alert
  Content-Type: application/json (or plain text — best-effort parse)
  Body example (from Pine alert message field):
    {"ticker": "BTCUSDT", "indicator": "liq_cluster_confirmer",
     "direction": "short", "price": 78400, "cvd_div": "bullish",
     "ts_pine": "{{timenow}}", "extra": "..."}

Token:
  Auto-generated on first run, stored in state/tv_webhook_token.txt (gitignored).
  Each TV alert must POST to /tv/<that_token>/alert — wrong token = 403.

Persistence:
  Every accepted alert appended to state/tv_alerts.jsonl with our-side
  ingest_ts (UTC) for downstream rules (e.g. R7_tv_confirmed_setup).

Port:
  Binds 0.0.0.0:8770 by default (env: TV_WEBHOOK_PORT). Externally exposed
  via ngrok or cloudflared tunnel — see docs/TV_WEBHOOK_SETUP_2026-05-17.md.
"""
from __future__ import annotations

import asyncio
import http.server
import json
import logging
import os
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2]
_TOKEN_PATH = _ROOT / "state" / "tv_webhook_token.txt"
_ALERTS_PATH = _ROOT / "state" / "tv_alerts.jsonl"
_DEFAULT_PORT = 8770
_BIND_HOST = "0.0.0.0"  # tunnel exposes — accept from anywhere (token-gated)


def _get_or_create_token() -> str:
    """Token persists in state/tv_webhook_token.txt. Created if missing."""
    if _TOKEN_PATH.exists():
        try:
            t = _TOKEN_PATH.read_text(encoding="utf-8").strip()
            if t:
                return t
        except OSError:
            pass
    # Generate URL-safe 32-byte token
    token = secrets.token_urlsafe(32)
    try:
        _TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        _TOKEN_PATH.write_text(token, encoding="utf-8")
        os.chmod(_TOKEN_PATH, 0o600)
    except OSError:
        logger.exception("tv_webhook.token_write_failed")
    return token


# Dedup window: same (indicator, direction, ticker) фильтруется в течение этого периода.
# Защита от Pine alert "once per bar close" который шлёт каждую минуту пока условие TRUE.
_DEDUP_WINDOW_SEC = 30 * 60  # 30 минут
_recent_dedup: dict[tuple, float] = {}  # in-memory; persisted only via journal


def _is_duplicate(payload: dict, now_ts: float) -> bool:
    """Check if (indicator, direction, ticker) was seen within DEDUP_WINDOW."""
    key = (
        str(payload.get("indicator", "")),
        str(payload.get("direction", "")),
        str(payload.get("ticker", "")),
    )
    if not any(key):
        return False
    last = _recent_dedup.get(key)
    if last is not None and (now_ts - last) < _DEDUP_WINDOW_SEC:
        return True
    _recent_dedup[key] = now_ts
    # GC old entries (keep cache small)
    if len(_recent_dedup) > 100:
        for k, ts in list(_recent_dedup.items()):
            if (now_ts - ts) > _DEDUP_WINDOW_SEC * 2:
                _recent_dedup.pop(k, None)
    return False


def _append_alert(record: dict) -> None:
    try:
        _ALERTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _ALERTS_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except OSError:
        logger.exception("tv_webhook.alert_write_failed")


def _make_handler(token: str) -> type[http.server.BaseHTTPRequestHandler]:
    expected_path = f"/tv/{token}/alert"

    class _Handler(http.server.BaseHTTPRequestHandler):
        # quiet — we have our own logging
        def log_message(self, fmt, *args):
            logger.info("tv_webhook.access %s", fmt % args)

        def do_POST(self) -> None:
            url_path = self.path.split("?")[0]
            # Token check
            if url_path != expected_path:
                self.send_error(403, "forbidden")
                return
            # Read body
            length = int(self.headers.get("Content-Length") or 0)
            if length > 16 * 1024:
                self.send_error(413, "payload too large")
                return
            body = self.rfile.read(length).decode("utf-8", errors="ignore") if length else ""
            # Try JSON parse; fallback to raw text
            payload: dict
            try:
                payload = json.loads(body) if body.strip().startswith("{") else {"raw": body.strip()}
            except json.JSONDecodeError:
                payload = {"raw": body.strip()}

            now_dt = datetime.now(timezone.utc)
            if _is_duplicate(payload, now_dt.timestamp()):
                logger.info("tv_webhook.deduped indicator=%s direction=%s ticker=%s (within %dmin)",
                            payload.get("indicator"), payload.get("direction"),
                            payload.get("ticker"), _DEDUP_WINDOW_SEC // 60)
            else:
                record = {
                    "ingest_ts": now_dt.isoformat(timespec="seconds"),
                    "remote_addr": self.client_address[0],
                    "headers_ua": self.headers.get("User-Agent"),
                    "payload": payload,
                }
                _append_alert(record)
                logger.info("tv_webhook.alert_received indicator=%s direction=%s ticker=%s",
                            payload.get("indicator"), payload.get("direction"),
                            payload.get("ticker"))
                try:
                    from .dispatcher import dispatch
                    dispatch(payload, record)
                except Exception:
                    logger.exception("tv_webhook.dispatch_failed")

            # Respond OK quickly — TV doesn't care about body
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')

        def do_GET(self) -> None:
            # Healthcheck (no token leak)
            if self.path == "/health":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"status":"alive","service":"tv_webhook"}')
                return
            self.send_error(404)

    return _Handler


class _ThreadedServer(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def _start_server(token: str, port: int) -> Optional[_ThreadedServer]:
    try:
        srv = _ThreadedServer((_BIND_HOST, port), _make_handler(token))
    except OSError as e:
        logger.error("tv_webhook.bind_failed port=%d err=%s", port, e)
        return None
    t = threading.Thread(target=srv.serve_forever, name="tv_webhook_http", daemon=True)
    t.start()
    return srv


async def tv_webhook_loop(stop_event: asyncio.Event,
                          port: Optional[int] = None) -> None:
    """Async wrapper: starts threaded HTTP server, waits for stop_event."""
    port = port or int(os.getenv("TV_WEBHOOK_PORT", str(_DEFAULT_PORT)))
    token = _get_or_create_token()
    srv = _start_server(token, port)
    if srv is None:
        logger.error("tv_webhook.start_failed")
        return
    logger.info("tv_webhook.start port=%d token_path=%s endpoint=/tv/<token>/alert",
                port, _TOKEN_PATH)
    try:
        await stop_event.wait()
    finally:
        try:
            srv.shutdown()
        except Exception:
            logger.exception("tv_webhook.shutdown_failed")
        logger.info("tv_webhook.stopped")
