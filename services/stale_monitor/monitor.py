"""Stale data monitor — checks critical sources, alerts on Telegram if stale.

Critical sources + max age:
  market_live/market_1m.csv      — 5 min   (live BTC price feed)
  ginarea_live/snapshots.csv     — 10 min  (bot states)
  state/regime_state.json        — 15 min  (Classifier A live)

Per-source alert dedup: re-alert at most once per hour for the same source.
Recovery alert when source returns to fresh.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SEC = 300  # 5 min
ALERT_REPEAT_INTERVAL_SEC = 3600  # 1 hour between repeat alerts for same source
GRACE_PERIOD_AFTER_START_SEC = 900  # 15 min — не алертим первые 15 мин после старта монитора (post-restart warmup)

CRITICAL_SOURCES = {
    "market_1m": {
        "path": "market_live/market_1m.csv",
        "max_age_min": 5,
        "label": "Live BTC price (1m)",
    },
    "ginarea_snapshots": {
        "path": "ginarea_live/snapshots.csv",
        "max_age_min": 10,
        "label": "GinArea bot snapshots",
    },
    "regime_state": {
        "path": "state/regime_state.json",
        "max_age_min": 15,
        "label": "Classifier A regime state",
    },
    "liquidations_stream": {
        "path": "market_live/liquidations.csv",
        "max_age_min": 60,  # liquidations sparse — даже спокойный рынок 1+ event/hr
        "label": "Liquidation stream (Bybit+Binance WS)",
    },
    "setup_detector_heartbeat": {
        # 2026-05-23: switched from setups.jsonl mtime to a dedicated
        # heartbeat file written EVERY tick (independent of whether any
        # setup actually got emitted). Catches the real 2026-05-07
        # incident class (wedged loop) at 10-min granularity without the
        # false-positive avalanche from quiet-market periods where the
        # loop is healthy but filters block every candidate.
        "path": "state/setup_detector_heartbeat.json",
        "max_age_min": 10,
        "label": "Setup detector heartbeat (loop liveness)",
    },
    "state_latest_json": {
        # 2026-05-07: state_snapshot moved from scheduled task to supervisor.
        # paper_journal и decision_log зависят от свежести.
        "path": "docs/STATE/state_latest.json",
        "max_age_min": 15,  # state_snapshot interval = 5 min, threshold с запасом
        "label": "State snapshot (paper_journal/decision_log input)",
    },
}

STATE_PATH = Path("state/stale_monitor_state.json")


def _file_age_min(p: Path) -> Optional[float]:
    if not p.exists():
        return None
    try:
        return (datetime.now().timestamp() - p.stat().st_mtime) / 60
    except OSError:
        return None


def _load_state() -> dict:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except OSError:
        pass


def check_once(send_fn: Optional[Callable[[str], None]] = None, monitor_started_ts: Optional[float] = None) -> dict:
    """One check pass. Returns state dict. Sends alert via send_fn if available.

    monitor_started_ts: epoch when monitor loop started. Если задано и
    прошло меньше GRACE_PERIOD_AFTER_START_SEC — alerts не отправляются
    (используется чтобы не спамить после рестарта app_runner — sources
    могут быть stale пока сами не перезапустились).
    """
    state = _load_state()
    now_ts = datetime.now(timezone.utc).timestamp()
    alerts = []
    recoveries = []
    in_grace = (
        monitor_started_ts is not None
        and (now_ts - monitor_started_ts) < GRACE_PERIOD_AFTER_START_SEC
    )

    for source_id, cfg in CRITICAL_SOURCES.items():
        path = Path(cfg["path"])
        age_min = _file_age_min(path)
        max_age = cfg["max_age_min"]
        is_stale = age_min is None or age_min > max_age
        prev = state.get(source_id, {})
        was_stale = bool(prev.get("stale", False))
        last_alert_ts = prev.get("last_alert_ts", 0)

        if is_stale:
            if not was_stale:
                # New stale event — alert
                alerts.append((cfg["label"], age_min, max_age))
                state[source_id] = {"stale": True, "last_alert_ts": now_ts, "since_ts": now_ts}
            elif now_ts - last_alert_ts > ALERT_REPEAT_INTERVAL_SEC:
                # Repeat alert (still stale after 1h)
                alerts.append((cfg["label"], age_min, max_age))
                state[source_id]["last_alert_ts"] = now_ts
        else:
            if was_stale:
                # Recovered
                recoveries.append((cfg["label"], age_min))
                state[source_id] = {"stale": False, "last_alert_ts": 0}

    if alerts and send_fn and not in_grace:
        for label, age, threshold in alerts:
            age_str = f"{age:.0f}min" if age is not None else "MISSING"
            try:
                send_fn(f"⚠️ STALE DATA: {label} | age {age_str} (threshold {threshold}min)")
            except Exception:
                logger.exception("stale_monitor.send_alert_failed")
    elif alerts and in_grace:
        labels = ", ".join(a[0] for a in alerts)
        logger.info("stale_monitor.in_grace alerts_suppressed=%d sources=%s", len(alerts), labels)
    if recoveries and send_fn:
        for label, age in recoveries:
            try:
                send_fn(f"✅ RECOVERED: {label} | age {age:.0f}min (back to fresh)")
            except Exception:
                logger.exception("stale_monitor.send_recovery_failed")

    _save_state(state)
    return state


async def stale_monitor_loop(
    stop_event: asyncio.Event,
    *,
    send_fn: Optional[Callable[[str], None]] = None,
    interval_sec: int = CHECK_INTERVAL_SEC,
) -> None:
    """Async loop. Run every interval_sec until stop_event.

    Grace period: первые GRACE_PERIOD_AFTER_START_SEC секунд после старта
    цикла — alerts не отправляются (suppressed). Это защита от спама
    'STALE DATA' после рестарта app_runner — источники данных могут
    быть оффлайн пока их собственные сервисы не запустились.
    """
    monitor_started_ts = datetime.now(timezone.utc).timestamp()
    logger.info("stale_monitor.loop.start interval=%ds grace=%ds", interval_sec, GRACE_PERIOD_AFTER_START_SEC)
    while not stop_event.is_set():
        try:
            check_once(send_fn=send_fn, monitor_started_ts=monitor_started_ts)
        except Exception:
            logger.exception("stale_monitor.check_failed")
        try:
            await asyncio.wait_for(asyncio.shield(stop_event.wait()), timeout=interval_sec)
        except asyncio.TimeoutError:
            pass
    logger.info("stale_monitor.loop.stopped")
