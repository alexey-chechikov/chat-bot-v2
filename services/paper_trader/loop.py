"""Paper trader async loop — pulls new setups + tracks open trades.

Runs every 60 seconds:
  1. Read setups.jsonl → find any new OPEN-eligible setups (conf>=60, not yet papered)
  2. Open paper trade if any
  3. Get current BTC price
  4. Update open trades (close TP/SL hits)
  5. Telegram alerts for opens/closes
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from services.paper_trader import journal, trader
from services.paper_trader.streak_notifier import check_and_notify as _streak_check
from services.setup_detector.models import (
    Setup,
    SetupBasis,
    SetupStatus,
    SetupType,
    make_setup,
)

logger = logging.getLogger(__name__)

LOOP_INTERVAL_SEC = 60
SETUPS_PATH = Path("state/setups.jsonl")
DEDUP_PATH = Path("state/paper_trader_dedup.json")  # tracks setup_ids already opened
PENDING_PATH = Path("state/paper_trader_pending.json")  # confirmation-gated setups

# 2026-05-10 SETUP_FILTER_RESEARCH (commit 1434a44): confirmation gate boosted
# long_multi_divergence PF 0.83 -> 1.53 just by waiting and requiring drift.
# Apply globally to all paper trades.
CONFIRMATION_LAG_MIN = 10        # wait 10 min after detection before considering entry
CONFIRMATION_DRIFT_PCT = 0.10    # require 0.1% price move in setup direction
CONFIRMATION_TIMEOUT_MIN = 30    # cancel if no drift within 30 min


def _load_dedup() -> set[str]:
    if not DEDUP_PATH.exists():
        return set()
    try:
        return set(json.loads(DEDUP_PATH.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return set()


def _save_dedup(seen: set[str]) -> None:
    DEDUP_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        DEDUP_PATH.write_text(json.dumps(sorted(seen)), encoding="utf-8")
    except OSError:
        pass


def _load_pending() -> dict:
    """Pending setups awaiting confirmation: setup_id -> {detected_at, side, entry, pair}."""
    if not PENDING_PATH.exists():
        return {}
    try:
        return json.loads(PENDING_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_pending(pending: dict) -> None:
    PENDING_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        PENDING_PATH.write_text(json.dumps(pending, indent=2), encoding="utf-8")
    except OSError:
        pass


def _check_confirmation(pending_entry: dict, current_price: float, now: datetime
                       ) -> tuple[str, str | None]:
    """Decide whether a pending setup is ready / cancelled / still waiting.

    Returns ("ready", None) | ("cancel", reason) | ("wait", reason).
    """
    try:
        detected = datetime.fromisoformat(pending_entry["detected_at"].replace("Z", "+00:00"))
        if detected.tzinfo is None:
            detected = detected.replace(tzinfo=timezone.utc)
    except (KeyError, ValueError, TypeError):
        return ("cancel", "bad-detected-at")

    age_min = (now - detected).total_seconds() / 60
    if age_min < CONFIRMATION_LAG_MIN:
        return ("wait", f"age {age_min:.1f}min < {CONFIRMATION_LAG_MIN}")
    if age_min > CONFIRMATION_TIMEOUT_MIN:
        return ("cancel", f"timeout {age_min:.1f}min")

    entry = float(pending_entry.get("entry", 0))
    side = pending_entry.get("side", "")
    if entry <= 0 or side not in ("long", "short"):
        return ("cancel", "bad-entry-or-side")
    drift_pct = (current_price / entry - 1) * 100
    if side == "long" and drift_pct >= CONFIRMATION_DRIFT_PCT:
        return ("ready", f"drift +{drift_pct:.2f}%")
    if side == "short" and drift_pct <= -CONFIRMATION_DRIFT_PCT:
        return ("ready", f"drift {drift_pct:.2f}%")
    return ("wait", f"drift {drift_pct:+.2f}%")


def _read_recent_setups() -> list[dict]:
    """Read raw setup JSON dicts from setups.jsonl."""
    if not SETUPS_PATH.exists():
        return []
    out: list[dict] = []
    try:
        for line in SETUPS_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError as exc:
        logger.warning("paper_trader.loop.read_setups_failed: %s", exc)
    return out


def _setup_from_dict(d: dict) -> Setup | None:
    """Reconstruct minimal Setup from journal dict.

    setups.jsonl writes a flat dict; we reconstruct just enough fields for
    paper_trader.open_paper_trade().
    """
    try:
        setup_type = SetupType(d["setup_type"])
    except (KeyError, ValueError):
        return None
    try:
        detected_at = datetime.fromisoformat(d.get("detected_at", "").replace("Z", "+00:00"))
        if detected_at.tzinfo is None:
            detected_at = detected_at.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        detected_at = datetime.now(timezone.utc)

    basis_raw = d.get("basis") or []
    basis = []
    for b in basis_raw:
        try:
            basis.append(SetupBasis(label=b["label"], value=b["value"], weight=float(b.get("weight", 0))))
        except (KeyError, TypeError):
            continue

    return make_setup(
        setup_type=setup_type,
        pair=d.get("pair", "BTCUSDT"),
        current_price=float(d.get("current_price", 0)),
        regime_label=d.get("regime_label", "unknown"),
        session_label=d.get("session_label", "unknown"),
        entry_price=d.get("entry_price"),
        stop_price=d.get("stop_price"),
        tp1_price=d.get("tp1_price"),
        tp2_price=d.get("tp2_price"),
        risk_reward=d.get("risk_reward"),
        strength=int(d.get("strength", 0)),
        confidence_pct=float(d.get("confidence_pct", 0)),
        basis=tuple(basis),
        cancel_conditions=tuple(d.get("cancel_conditions") or ()),
        window_minutes=int(d.get("window_minutes", 120)),
        portfolio_impact_note=d.get("portfolio_impact_note", ""),
        detected_at=detected_at,
    )


def _get_current_price() -> float | None:
    """Read latest BTC price from market_live/market_1m.csv (legacy single-price)."""
    p = Path("market_live/market_1m.csv")
    if not p.exists():
        return None
    try:
        with p.open("rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            block = min(2048, size)
            fh.seek(-block, 2)
            data = fh.read().decode("utf-8", errors="replace")
        last_line = None
        for line in data.splitlines():
            if line.strip() and not line.startswith("ts_utc"):
                last_line = line
        if last_line:
            parts = last_line.strip().split(",")
            if len(parts) >= 5:
                return float(parts[4])
    except (OSError, ValueError):
        pass
    return None


def _get_prices_for_symbols(symbols: tuple[str, ...]) -> dict[str, float]:
    """Fetch latest 1m close for each symbol via core.data_loader.

    Returns dict[symbol -> close]. Symbols whose fetch fails are omitted
    (paper_trader.update_open_trades skips trades with missing prices).
    """
    out: dict[str, float] = {}
    try:
        from core.data_loader import load_klines
    except Exception:
        logger.exception("paper_trader.loop.load_klines_unavailable")
        return out
    for sym in symbols:
        try:
            df = load_klines(symbol=sym, timeframe="1m", limit=2)
            if df is None or df.empty:
                continue
            close = float(df["close"].iloc[-1])
            if close > 0:
                out[sym] = close
        except Exception:
            logger.exception("paper_trader.loop.price_fetch_failed sym=%s", sym)
    return out


# Аудит форварда 16.08.2026 по state/setup_outcomes.jsonl (404 закрытых
# сделки, 01.05–14.08). Девять типов из одиннадцати убыточны, суммарно
# −$1 702 на 383 сделках. В TG идут только неотрицательные.
#
#   сетап                    сделок    сумма   винрейт    PF
#   long_pdl_bounce             218  −488.54$      19%  0.49
#   long_multi_divergence        35  −265.39$      26%  0.33
#   short_pdh_rejection          35  −247.15$       9%  0.15
#   long_div_bos_15m             20  −199.56$      10%  0.02
#   short_rally_fade             23  −161.12$       9%  0.01
#   long_mega_dump_bounce        14  −159.54$       0%  0.00
#   long_dump_reversal           11   −81.86$       0%  0.00
#   short_double_top             17   −71.51$      47%  0.09
#   short_div_bos_15m            10   −27.29$      20%  0.10
#   long_double_bottom           17  +116.76$      53% 38.54  ← оставлен
#   long_div_bos_confirmed        4    +0.70$      25%  1.56  ← оставлен
#
# Ранжирование от 21.06 ПЕРЕВЕРНУЛОСЬ: rally_fade был PF 3.13 → стал 0.01,
# dump_reversal 3.05 → 0.00. А double_bottom тогда был «опровергнут по
# точности» и сейчас единственный неотрицательный. Двух месяцев данных
# на ранжирование не хватает — это причина держать журнал и перепроверять.
#
# Журналирование НЕ трогаем: именно оно показало деградацию.
# Вернуть тип в TG — добавить в TG_ALLOWED_SETUPS.
TG_ALLOWED_SETUPS = frozenset({
    "long_double_bottom",
    "long_div_bos_confirmed",
})


def _tg_allowed(setup_type: str | None) -> bool:
    import os
    if os.environ.get("PAPER_TG_ALL_SETUPS", "0") == "1":
        return True
    return str(setup_type or "") in TG_ALLOWED_SETUPS


def _format_open_alert(record: dict) -> str:
    from services.common.humanize import humanize_setup_type, fmt_price_compact
    side = "📈 PAPER LONG" if record["side"] == "long" else "📉 PAPER SHORT"
    entry = record["entry"]
    sl = record["sl"]
    tp1 = record.get("tp1") or "n/a"
    tp2 = record.get("tp2") or "n/a"
    rr = record.get("rr_planned") or "n/a"
    setup_code = record["setup_type"]
    setup_ru = humanize_setup_type(setup_code)
    conf = record["confidence_pct"]
    reason = record.get("reason", "")
    tp1_s = tp1 if isinstance(tp1, str) else fmt_price_compact(tp1)
    tp2_s = tp2 if isinstance(tp2, str) else fmt_price_compact(tp2)
    return (
        f"{side} @ {fmt_price_compact(entry)} | SL {fmt_price_compact(sl)} | TP1 {tp1_s} "
        f"| TP2 {tp2_s} | RR {rr}\n"
        f"сетап: {setup_ru} | conf {conf:.0f}% | {reason}"
    )


def _format_close_alert(event: dict) -> str:
    from services.common.humanize import humanize_setup_type
    action = event["action"]
    pnl = event["realized_pnl_usd"]
    rr = event["rr_realized"]
    hours = event["hours_in_trade"]
    side = event["side"]
    setup_code = event["setup_type"]
    setup_ru = humanize_setup_type(setup_code)
    icon = {"TP1": "✅", "TP2": "🎯", "SL": "🛑", "EXPIRE": "⏱️"}.get(action, "•")
    sign = "+" if pnl > 0 else ""
    return (
        f"{icon} PAPER {action} | {setup_ru} ({side}) | "
        f"{sign}${pnl:.0f} | RR {rr:+.2f} | {hours:.1f}h"
    )


def _format_grouped_alert(events: list[dict]) -> str:
    """Свод по одинаковым закрытиям в одном тике (action+setup+side).

    Появилось 2026-05-09: 37 дубликатов long_multi_divergence закрывались
    одновременно по TP1 и заваливали TG 10+ одинаковыми карточками.
    Теперь группируем: одна карточка на всю группу.
    """
    from services.common.humanize import humanize_setup_type
    if not events:
        return ""
    if len(events) == 1:
        return _format_close_alert(events[0])
    sample = events[0]
    action = sample["action"]
    side = sample["side"]
    setup_code = sample["setup_type"]
    setup_ru = humanize_setup_type(setup_code)
    icon = {"TP1": "✅", "TP2": "🎯", "SL": "🛑", "EXPIRE": "⏱️"}.get(action, "•")
    total_pnl = sum(e["realized_pnl_usd"] for e in events)
    avg_rr = sum(e["rr_realized"] for e in events) / len(events)
    sign = "+" if total_pnl >= 0 else ""
    return (
        f"{icon} PAPER {action} ×{len(events)} | {setup_ru} ({side}) | "
        f"total {sign}${total_pnl:.0f} | avg RR {avg_rr:+.2f}"
    )


async def paper_trader_loop(
    stop_event: asyncio.Event,
    *,
    send_fn: Callable[[str], None] | None = None,
    interval_sec: int = LOOP_INTERVAL_SEC,
) -> None:
    """Main async loop. Runs until stop_event is set."""
    logger.info("paper_trader.loop.start interval=%ds confirm_lag=%dmin drift=%.2f%%",
                interval_sec, CONFIRMATION_LAG_MIN, CONFIRMATION_DRIFT_PCT)
    seen_setup_ids = _load_dedup()
    pending = _load_pending()
    while not stop_event.is_set():
        try:
            # 0. Check streak_guard state transitions → notify operator on pause/resume
            try:
                _streak_check(send_fn)
            except Exception:
                logger.exception("paper_trader.loop.streak_notify_failed")

            # 1a. New setups → enter pending pool (NOT open immediately)
            setups_raw = _read_recent_setups()
            new_setups = [s for s in setups_raw if s.get("setup_id") not in seen_setup_ids]
            for raw in new_setups:
                sid = raw.get("setup_id", "")
                seen_setup_ids.add(sid)
                if not sid: continue
                # Skip P-15 lifecycle setups — they have their own handler
                if str(raw.get("setup_type", "")).startswith("p15_"):
                    continue
                side = "long" if "long" in str(raw.get("setup_type", "")).lower() else "short"
                pending[sid] = {
                    "detected_at": raw.get("detected_at", ""),
                    "side": side,
                    "entry": float(raw.get("entry_price") or raw.get("current_price") or 0),
                    "pair": raw.get("pair", "BTCUSDT"),
                    "raw": raw,  # keep full dict for later open
                }
            if new_setups:
                _save_dedup(seen_setup_ids)
                _save_pending(pending)

            # 1b. Check pending pool for confirmation
            now = datetime.now(timezone.utc)
            ready_ids = []
            cancel_ids = []
            # Group pending by pair for batched price fetch
            pending_pairs = {p.get("pair", "BTCUSDT") for p in pending.values()}
            pending_prices = _get_prices_for_symbols(tuple(sorted(pending_pairs))) if pending_pairs else {}
            for sid, entry in list(pending.items()):
                pair = entry.get("pair", "BTCUSDT")
                cur = pending_prices.get(pair)
                if cur is None: continue
                state, reason = _check_confirmation(entry, cur, now)
                if state == "ready":
                    ready_ids.append((sid, entry, reason))
                elif state == "cancel":
                    cancel_ids.append((sid, entry, reason))
            for sid, entry, reason in ready_ids:
                setup = _setup_from_dict(entry["raw"])
                if setup is None:
                    pending.pop(sid, None); continue
                opened = trader.open_paper_trade(setup)
                pending.pop(sid, None)
                if opened and send_fn and _tg_allowed(opened.get("setup_type")):
                    try:
                        send_fn(f"⏱ confirmed ({reason})\n" + _format_open_alert(opened))
                    except Exception:
                        logger.exception("paper_trader.loop.send_open_failed")
                elif opened:
                    logger.info("paper_trader.loop.tg_suppressed setup=%s "
                                "(отрицательный PF на форварде)",
                                opened.get("setup_type"))
            for sid, entry, reason in cancel_ids:
                pending.pop(sid, None)
                logger.info("paper_trader.loop.confirmation_cancelled sid=%s reason=%s", sid, reason)
            if ready_ids or cancel_ids:
                _save_pending(pending)

            # 2. Update open trades with prices for all relevant symbols.
            # Multi-symbol since 2026-05-08: BTC + ETH paper trades both supported.
            # Build dict of pairs we currently have OPEN trades for, fetch each.
            try:
                open_trades = trader.journal.open_trades()
                pairs_in_use = {t.get("pair") or "BTCUSDT" for t in open_trades}
            except Exception:
                pairs_in_use = {"BTCUSDT"}
            if pairs_in_use:
                prices = _get_prices_for_symbols(tuple(sorted(pairs_in_use)))
                if prices:
                    closes = trader.update_open_trades(prices)
                    if closes and send_fn:
                        # Group identical close events to suppress TG spam.
                        # 2026-05-09 incident: 37 duplicate long_multi_divergence
                        # paper trades hit TP1 in the same tick → 10+ identical
                        # cards in TG. Now: 1 grouped card per (action, setup, side).
                        groups: dict[tuple[str, str, str], list[dict]] = {}
                        for ev in closes:
                            key = (ev.get("action", ""), ev.get("setup_type", ""), ev.get("side", ""))
                            groups.setdefault(key, []).append(ev)
                        for events in groups.values():
                            try:
                                send_fn(_format_grouped_alert(events))
                            except Exception:
                                logger.exception("paper_trader.loop.send_close_failed")
        except Exception:
            logger.exception("paper_trader.loop.iteration_failed")

        try:
            await asyncio.wait_for(asyncio.shield(stop_event.wait()), timeout=interval_sec)
        except asyncio.TimeoutError:
            pass
    logger.info("paper_trader.loop.stopped")
