"""Cascade-followup signal loop + outcome tracker.

Signal loop:
  - Каждые 60с читает market_live/liquidations.csv (через cascade_alert).
  - Для каждого VARIANTS триггера (qty >= threshold за 5мин) проверяет dedup,
    собирает signal, пишет в journal, шлёт TG-card с [✅ Placed] [⏭ Skip].

Outcome loop:
  - Каждые 15мин ищет placed-signals без realized_4h_pct.
  - Если прошло ≥4h после ts_signal → fill realized_4h_pct из market_1m.csv.
  - Если прошло ≥12h → fill realized_12h_pct + ставит outcome.

Per-variant dedup: 30мин (как cascade_alert).
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

from services.cascade_followup.journal import (
    append_signal as journal_append,
    journal_path_for,
    pending_outcomes,
    update_record,
)
from services.cascade_followup.signal import VARIANTS, build_signal, format_tg_card

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
DEDUP_PATH = ROOT / "state" / "cascade_followup_dedup.json"

POLL_INTERVAL_SEC = 60
OUTCOME_INTERVAL_SEC = 900
WINDOW_MINUTES = 5
DEDUP_COOLDOWN_SEC = 1800


def _build_keyboard(signal_id: str):
    try:
        from telebot import types
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("✅ Placed", callback_data=f"cf:placed:{signal_id}"),
            types.InlineKeyboardButton("⏭ Skip", callback_data=f"cf:skip:{signal_id}"),
        )
        return kb
    except Exception:
        return None


def _load_dedup() -> dict:
    if not DEDUP_PATH.exists():
        return {}
    try:
        return json.loads(DEDUP_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_dedup(d: dict) -> None:
    try:
        DEDUP_PATH.parent.mkdir(parents=True, exist_ok=True)
        DEDUP_PATH.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        logger.exception("cascade_followup.dedup_save_failed")


def _record_to_dict(sig) -> dict:
    return {
        "signal_id": sig.signal_id,
        "ts_signal": sig.ts_signal,
        "variant": sig.variant,
        "liq_side": sig.liq_side,
        "threshold_btc": sig.threshold_btc,
        "qty_btc": round(sig.qty_btc, 4),
        "last_price": sig.last_price,
        "trade_dir": sig.trade_dir,
        "entry": sig.entry,
        "tp1": sig.tp1,
        "tp2": sig.tp2,
        "stop": sig.stop,
        "size_usd": sig.size_usd,
        "size_btc": round(sig.size_btc, 6),
        "predicted_4h_pct": sig.predicted_4h_pct,
        "edge_drift_flag": sig.edge_drift_flag,
        "by_exchange": sig.by_exchange,
        "user_action": None,
        "placed_at": None,
        "decision_latency_sec": None,
        "outcome": None,
        "realized_4h_pct": None,
        "realized_12h_pct": None,
        "realized_at_ts": None,
        "exit_reason": None,
    }


def _detect_triggers(now: datetime) -> list[tuple[str, float, float, dict]]:
    """Returns list of (variant, qty_btc, last_price, by_exchange) for triggered variants.

    Each variant defines its own window_minutes (5 for std tier, 1 for mega tier).
    Window readings are cached per-tick so a single tick can dispatch multi-tier
    variants without re-reading liquidations.csv.
    """
    from services.cascade_alert.loop import _liquidation_window_breakdown
    out: list[tuple[str, float, float, dict]] = []
    readings: dict[int, tuple[float, float, float | None, dict]] = {}
    for v in VARIANTS.values():
        wm = int(getattr(v, "window_minutes", WINDOW_MINUTES) or WINDOW_MINUTES)
        if wm not in readings:
            readings[wm] = _liquidation_window_breakdown(now, wm)
        long_btc, short_btc, last_price, by_exchange = readings[wm]
        if last_price is None or last_price <= 0:
            continue
        qty = long_btc if v.liq_side == "long" else short_btc
        if qty >= v.threshold_btc:
            out.append((v.variant, qty, last_price, by_exchange))
    return out


def _check_edge_drift(liq_side: str, threshold_btc: float) -> bool:
    """Returns True if cascade_alert edge_drift_guard says edge for this bucket
    is drifted on the variant's primary horizon (4h). Defaults False on any error
    (fail-open — better to emit than swallow signal silently)."""
    try:
        from services.cascade_alert.edge_drift_guard import is_drifted
        return bool(is_drifted(liq_side, threshold_btc, horizon="4h"))
    except Exception:
        logger.exception("cascade_followup.drift_check_failed")
        return False


_ACC_PATH = Path("state/cascade_accuracy.jsonl")
_STREAK_N = 3  # 3 consecutive evaluated losses on the variant -> suppress


def _recent_losses_streak(liq_side: str, threshold_btc: float,
                          *, n: int = _STREAK_N,
                          path: Path = _ACC_PATH) -> tuple[bool, int]:
    """Fast circuit-breaker — independent of (lagging) drift accuracy.

    Returns (streak_loss, n_evaluated). True only when the last `n` evaluated
    cascade_accuracy entries matching the variant's bucket are ALL losses for
    the variant's intended trade direction. The drift guard waits for n>=10
    to flip; this catches a sudden regime break in 3 evaluations.

    Bucket match: same liq_side ('long'/'short') AND same mega-ness
    (threshold>=10 BTC). Loss definition (fade-cascade):
      liq_side='short' -> trade LONG  -> loss = realized_4h <= 0
      liq_side='long'  -> trade SHORT -> loss = realized_4h >= 0
    """
    if not path.exists():
        return False, 0
    mega = threshold_btc >= 10.0
    is_loss = (lambda r: r <= 0) if liq_side == "short" else (lambda r: r >= 0)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False, 0
    evaluated: list[float] = []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
            if rec.get("direction") != liq_side:
                continue
            thr = float(rec.get("threshold_btc", 0))
            if mega != (thr >= 10.0):
                continue
            r4h = rec.get("realized_pct_4h")
            if r4h is None:
                continue
            evaluated.append(float(r4h))
            if len(evaluated) >= n:
                break
        except (json.JSONDecodeError, ValueError, TypeError):
            continue
    if len(evaluated) < n:
        return False, len(evaluated)
    return all(is_loss(r) for r in evaluated[:n]), len(evaluated)


async def cascade_followup_signal_loop(stop_event: asyncio.Event, *,
                                        send_fn: Optional[Callable] = None,
                                        interval_sec: int = POLL_INTERVAL_SEC) -> None:
    """Async signal loop. send_fn(text, reply_markup=...) — TG send adapter.

    Edge-drift suppression (2026-05-19): когда is_drifted=True для (liq_side,
    threshold) на 4h horizon — журнал пишется с edge_drift_flag=True для
    forward-stats, но TG-карточка НЕ отправляется. Операторам не нужны кнопки
    на сетап с мёртвым edge'ом.
    """
    logger.info("cascade_followup.signal_loop.start interval=%ds variants=%s",
                interval_sec, list(VARIANTS.keys()))
    while not stop_event.is_set():
        try:
            now = datetime.now(timezone.utc)
            triggers = _detect_triggers(now)
            if triggers:
                dedup = _load_dedup()
                dedup_dirty = False
                for variant, qty_btc, last_price, by_exchange in triggers:
                    last_sent = dedup.get(variant)
                    if last_sent:
                        try:
                            ts_last = datetime.fromisoformat(last_sent.replace("Z", "+00:00"))
                            if (now - ts_last).total_seconds() < DEDUP_COOLDOWN_SEC:
                                continue
                        except ValueError:
                            pass
                    v = VARIANTS[variant]
                    drifted = _check_edge_drift(v.liq_side, v.threshold_btc)
                    streak_loss, n_eval = _recent_losses_streak(
                        v.liq_side, v.threshold_btc)
                    sig = build_signal(variant=variant, qty_btc=qty_btc,
                                        last_price=last_price, by_exchange=by_exchange,
                                        edge_drift_flag=drifted,
                                        now=now)
                    record = _record_to_dict(sig)
                    journal_append(record)
                    if drifted:
                        logger.info(
                            "cascade_followup.suppressed_drift variant=%s qty=%.2f sid=%s "
                            "(edge_drift_guard says short_%s_4h is drifted — no TG send)",
                            variant, qty_btc, sig.signal_id, v.liq_side,
                        )
                    elif streak_loss:
                        logger.info(
                            "cascade_followup.suppressed_streak variant=%s qty=%.2f sid=%s "
                            "(last %d evaluated outcomes for liq_side=%s mega=%s "
                            "all losses — no TG send)",
                            variant, qty_btc, sig.signal_id, _STREAK_N,
                            v.liq_side, v.threshold_btc >= 10.0,
                        )
                    else:
                        # Cross-service dedup: skip if cascade_alert already
                        # fired same side within 10min (operator-confusion).
                        cross_blocked = False
                        cross_who = ""
                        try:
                            from services.cascade_alert.cross_service_dedup import (
                                recently_emitted, mark_emitted,
                            )
                            cross_blocked, cross_who = recently_emitted(v.liq_side, now)
                        except Exception:
                            pass
                        if cross_blocked:
                            logger.info(
                                "cascade_followup.suppressed_cross_service "
                                "variant=%s liq_side=%s by=%s sid=%s",
                                variant, v.liq_side, cross_who, sig.signal_id,
                            )
                        else:
                            logger.info("cascade_followup.signal variant=%s qty=%.2f price=%.0f sid=%s",
                                        variant, qty_btc, last_price, sig.signal_id)
                            # 2026-07-29 (оператор: «это спам, нужен более
                            # надёжный сигнал»): карточка требует решения за
                            # ≤60с — нереалистично для человека; из 269
                            # сигналов исход не записан ни у одного, эдж
                            # семьи не подтверждён живьём. В журнал пишем,
                            # в TG молчим до подтверждения на форварде.
                            from services.common.silent_families import tg_muted
                            if tg_muted("CASCADE_FOLLOWUP"):
                                logger.info("cascade_followup.silent_journal id=%s",
                                            sig.signal_id)
                            elif send_fn is not None:
                                try:
                                    send_fn(format_tg_card(sig), reply_markup=_build_keyboard(sig.signal_id))
                                except TypeError:
                                    try:
                                        send_fn(format_tg_card(sig))
                                    except Exception:
                                        logger.exception("cascade_followup.send_failed_fallback")
                                except Exception:
                                    logger.exception("cascade_followup.send_failed")
                            try:
                                mark_emitted("cascade_followup", v.liq_side, now)
                            except Exception:
                                pass
                    dedup[variant] = now.isoformat(timespec="seconds")
                    dedup_dirty = True
                if dedup_dirty:
                    _save_dedup(dedup)
        except Exception:
            logger.exception("cascade_followup.signal_loop.tick_failed")

        try:
            await asyncio.wait_for(asyncio.shield(stop_event.wait()), timeout=interval_sec)
        except asyncio.TimeoutError:
            continue
    logger.info("cascade_followup.signal_loop.stopped")


def _price_at(target: datetime) -> Optional[float]:
    """Forward to cascade_alert helper which already does ±2min CSV lookup."""
    try:
        from services.cascade_alert.loop import _price_at as _ca_price_at
        return _ca_price_at(target)
    except Exception:
        logger.exception("cascade_followup.price_at_import_failed")
        return None


def _realized_pct(entry: float, exit_px: float, trade_dir: str) -> float:
    if entry <= 0 or exit_px <= 0:
        return 0.0
    raw = (exit_px - entry) / entry * 100.0
    return raw if trade_dir == "LONG" else -raw


async def cascade_followup_outcome_loop(stop_event: asyncio.Event,
                                         interval_sec: int = OUTCOME_INTERVAL_SEC) -> None:
    """Fill realized_4h_pct and realized_12h_pct for placed signals."""
    logger.info("cascade_followup.outcome_loop.start interval=%ds", interval_sec)
    while not stop_event.is_set():
        try:
            now = datetime.now(timezone.utc)
            for variant in VARIANTS:
                path = journal_path_for(variant)
                pendings = pending_outcomes(path=path)
                for r in pendings:
                    try:
                        ts_signal = datetime.fromisoformat(r["ts_signal"])
                    except (KeyError, ValueError):
                        continue
                    elapsed_h = (now - ts_signal).total_seconds() / 3600.0
                    updates: dict = {}
                    if elapsed_h >= 4 and r.get("realized_4h_pct") is None:
                        px_4h = _price_at(ts_signal + timedelta(hours=4))
                        if px_4h is not None:
                            updates["realized_4h_pct"] = round(_realized_pct(
                                float(r["entry"]), float(px_4h), r["trade_dir"]), 4)
                            updates["realized_at_ts"] = now.isoformat(timespec="seconds")
                    if elapsed_h >= 12 and r.get("realized_12h_pct") is None:
                        px_12h = _price_at(ts_signal + timedelta(hours=12))
                        if px_12h is not None:
                            updates["realized_12h_pct"] = round(_realized_pct(
                                float(r["entry"]), float(px_12h), r["trade_dir"]), 4)
                            r4 = updates.get("realized_4h_pct", r.get("realized_4h_pct"))
                            r12 = updates["realized_12h_pct"]
                            if r4 is not None and r12 is not None:
                                if r12 > 0 and r4 > 0:
                                    updates["outcome"] = "win"
                                elif r12 <= 0 and r4 <= 0:
                                    updates["outcome"] = "loss"
                                else:
                                    updates["outcome"] = "mixed"
                    if updates:
                        update_record(r["signal_id"], updates, path=path)
                        logger.info("cascade_followup.outcome sid=%s upd=%s",
                                     r["signal_id"], list(updates.keys()))
        except Exception:
            logger.exception("cascade_followup.outcome_loop.tick_failed")

        try:
            await asyncio.wait_for(asyncio.shield(stop_event.wait()), timeout=interval_sec)
        except asyncio.TimeoutError:
            continue
    logger.info("cascade_followup.outcome_loop.stopped")
