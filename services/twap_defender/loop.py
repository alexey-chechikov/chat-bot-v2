"""TWAP defender loop — periodic scan over managed bots.

Каждую минуту (DEFAULT_INTERVAL_SEC=60):
1. Прочитать хвост snapshots.csv (~1MB), сгруппировать по bot_id
2. Для каждого managed бота: current pos vs 30 мин назад
3. detect_bleed → если bleed: проверить active series (не муто, < 30 мин с предыдущего, step < MAX)
4. Emit TG-карточку с inline buttons, лог в journal

Step counter: каждый emit инкрементирует step. Series завершается:
  - step == MAX_STEPS (12) → auto-stop
  - |pos_usd| падает ниже порога между emits → новая серия при следующем bleed
  - User жмёт "muted" → пауза 60 мин (см. journal.mark_user_action)
"""
from __future__ import annotations

import asyncio
import csv
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

from services.twap_defender.journal import (
    JOURNAL_PATH,
    MAX_STEPS,
    STEP_INTERVAL_MIN,
    active_series_for_bot,
    append_alert,
    latest_alert_for_bot,
)
from services.twap_defender.state import detect_bleed, format_tg_card

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOTS_CSV = ROOT / "ginarea_live" / "snapshots.csv"
MARKET_1M_CSV = ROOT / "market_live" / "market_1m.csv"
MANAGED_PATH = ROOT / "state" / "short_bots_managed.json"

DEFAULT_INTERVAL_SEC = 60
SNAPSHOTS_TAIL_BYTES = 1_000_000  # 1MB tail, ~2-3h history across all bots


def _read_managed_bots() -> list[dict]:
    if not MANAGED_PATH.exists():
        return []
    try:
        d = json.loads(MANAGED_PATH.read_text(encoding="utf-8"))
        return d.get("managed_bots", [])
    except (json.JSONDecodeError, OSError):
        logger.exception("twap_defender.managed_read_failed")
        return []


def _read_snapshots_tail() -> list[dict]:
    """Read recent snapshots from tail of CSV. Returns parsed rows in order."""
    if not SNAPSHOTS_CSV.exists():
        return []
    try:
        with SNAPSHOTS_CSV.open("r", encoding="utf-8") as f:
            header = next(csv.reader(f))
        with SNAPSHOTS_CSV.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            chunk = min(size, SNAPSHOTS_TAIL_BYTES)
            f.seek(size - chunk)
            tail = f.read().decode("utf-8", errors="ignore")
        lines = tail.splitlines()
        if lines and size > chunk:
            lines = lines[1:]  # drop possibly-truncated first line
        rows: list[dict] = []
        for row in csv.reader(lines):
            if len(row) != len(header):
                continue
            rows.append(dict(zip(header, row)))
        return rows
    except OSError:
        logger.exception("twap_defender.snapshots_read_failed")
        return []


def _positions_for_bot(snapshots: list[dict], bot_id: str) -> list[tuple[datetime, float]]:
    """Extract (ts, position_btc) pairs for given bot_id, sorted ascending."""
    out: list[tuple[datetime, float]] = []
    for r in snapshots:
        if str(r.get("bot_id", "")).split(".")[0] != str(bot_id):
            continue
        ts_str = r.get("ts_utc", "")
        pos_str = r.get("position", "")
        if not ts_str or not pos_str:
            continue
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            pos = float(pos_str)
        except (ValueError, TypeError):
            continue
        out.append((ts, pos))
    out.sort(key=lambda x: x[0])
    return out


def _position_at_time(trajectory: list[tuple[datetime, float]],
                      target: datetime) -> Optional[float]:
    """Find position closest to target time (earlier or equal)."""
    best: Optional[float] = None
    for ts, pos in trajectory:
        if ts <= target:
            best = pos
        else:
            break
    return best


def _read_btc_mid() -> Optional[float]:
    """Read latest BTC mid from market_1m.csv."""
    if not MARKET_1M_CSV.exists():
        return None
    try:
        with MARKET_1M_CSV.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            chunk = min(size, 4096)
            f.seek(size - chunk)
            tail = f.read().decode("utf-8", errors="ignore")
        lines = [l for l in tail.splitlines() if l.strip()]
        if len(lines) < 2:
            return None
        last_row = lines[-1].split(",")
        # market_1m.csv format: ts_utc,open,high,low,close,volume,...
        # close is index 4
        try:
            return float(last_row[4])
        except (IndexError, ValueError):
            return None
    except OSError:
        return None


def _signal_id(now: datetime, bot_id: str) -> str:
    return f"td_{now.strftime('%Y%m%d_%H%M%S')}_{bot_id}"


def _series_id(now: datetime, bot_id: str) -> str:
    return f"td_series_{bot_id}_{now.strftime('%Y%m%d_%H%M%S')}"


def _build_keyboard(alert_id: str):
    try:
        from telebot import types
        kb = types.InlineKeyboardMarkup(row_width=3)
        kb.add(
            types.InlineKeyboardButton("✅ Executed", callback_data=f"td:exec:{alert_id}"),
            types.InlineKeyboardButton("⏭ Skip", callback_data=f"td:skip:{alert_id}"),
            types.InlineKeyboardButton("🔕 Mute 1h", callback_data=f"td:mute:{alert_id}"),
        )
        return kb
    except Exception:
        return None


def tick(*, send_fn: Optional[Callable] = None,
         now: Optional[datetime] = None,
         journal_path: Path = JOURNAL_PATH) -> list[dict]:
    """One scan over all managed bots. Returns list of emitted alert records."""
    if now is None:
        now = datetime.now(timezone.utc)

    managed = _read_managed_bots()
    if not managed:
        return []

    btc_mid = _read_btc_mid()
    if btc_mid is None:
        logger.warning("twap_defender.no_btc_mid")
        return []

    snapshots = _read_snapshots_tail()
    if not snapshots:
        return []

    emitted: list[dict] = []
    cutoff_30min = now - timedelta(minutes=30)

    for entry in managed:
        bot_id = str(entry.get("bot_id"))
        traj = _positions_for_bot(snapshots, bot_id)
        if not traj:
            continue
        current_ts, current_pos = traj[-1]
        # Stale snapshot guard: if latest snap older than 10 min, skip
        if (now - current_ts).total_seconds() > 600:
            continue

        pos_30 = _position_at_time(traj, cutoff_30min)
        if pos_30 is None:
            continue

        bot_state = {
            "bot_id": bot_id,
            "alias": entry.get("alias"),
            "tier": entry.get("tier"),
            "side": entry.get("side"),
            "position_btc": current_pos,
        }
        alert = detect_bleed(bot_state, position_30min_ago_btc=pos_30, btc_mid=btc_mid)
        if alert is None:
            continue

        series_id, last_step = active_series_for_bot(bot_id, now=now, path=journal_path)
        if series_id is None:
            series_id = _series_id(now, bot_id)
            step = 1
        else:
            # Enforce STEP_INTERVAL_MIN between consecutive TWAP steps
            latest = latest_alert_for_bot(bot_id, path=journal_path)
            if latest:
                try:
                    last_ts = datetime.fromisoformat(latest["ts_alert"])
                    if (now - last_ts).total_seconds() / 60.0 < STEP_INTERVAL_MIN:
                        continue
                except (KeyError, ValueError):
                    pass
            step = last_step + 1
            if step > MAX_STEPS:
                continue

        record = {
            "alert_id": _signal_id(now, bot_id),
            "series_id": series_id,
            "step": step,
            "ts_alert": now.isoformat(timespec="seconds"),
            **alert,
            "user_action": None,
            "user_action_ts": None,
            "muted_until": None,
        }
        append_alert(record, path=journal_path)

        if send_fn is not None:
            try:
                text = format_tg_card(alert, step=step, max_steps=MAX_STEPS)
                send_fn(text, reply_markup=_build_keyboard(record["alert_id"]))
            except Exception:
                logger.exception("twap_defender.send_failed")

        logger.info("twap_defender.alert bot=%s tier=%s step=%d pos=$%.0fk delta=$%.0fk",
                    bot_id, alert["tier"], step,
                    alert["position_usd_abs"] / 1000, alert["delta_30min_usd"] / 1000)
        emitted.append(record)

    return emitted


async def run_loop(stop_event: asyncio.Event, *,
                   send_fn: Optional[Callable] = None,
                   interval_sec: int = DEFAULT_INTERVAL_SEC) -> None:
    logger.info("twap_defender.loop_start interval=%ds tg=%s",
                interval_sec, "on" if send_fn else "off")
    while not stop_event.is_set():
        try:
            tick(send_fn=send_fn)
        except Exception:
            logger.exception("twap_defender.tick_failed")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_sec)
        except asyncio.TimeoutError:
            pass
    logger.info("twap_defender.loop_stop")
