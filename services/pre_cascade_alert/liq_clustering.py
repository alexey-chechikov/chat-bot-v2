"""Liquidation-based pre-cascade signal (Phase-1 R&D, 2026-05-13).

R&D (docs/STRATEGIES/PRE_CASCADE_SIGNAL_R&D.md) показал:
- Перед LONG-каскадом >=5 BTC за 15-20 мин накапливается ~0.44 BTC мелких liq
  на той же стороне (baseline ~0.005 BTC) — z=20, 88× выше нормы.
- SHORT: z=4.2 за 10-15 мин (22× выше baseline).

Live signal (Phase-1, консервативный):
- Окно: последние 5 мин.
- Trigger: на одной стороне >= LIQ_CLUSTER_THRESHOLD_BTC (0.3) накоплено,
  И ни один cascade>=5 BTC ещё не сработал за это окно (иначе тривиально —
  каскад уже идёт), И прошло >= cooldown с прошлого alert этой стороны.
- Side mapping: long-liq кластер → expects LONG cascade (continuation),
                short-liq кластер → expects SHORT cascade.

Цель: оператор получает info-alert "возможен каскад через 10-20 мин"
и не открывает новые позиции на этой стороне.
"""
from __future__ import annotations

import csv
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
LIQ_CSV = ROOT / "market_live" / "liquidations.csv"
STATE_PATH = ROOT / "state" / "liq_pre_cascade_state.json"
JOURNAL_PATH = ROOT / "state" / "liq_pre_cascade_fires.jsonl"

# Tunables (можно править в env позже)
WINDOW_MINUTES = 5
# 2026-05-13: после retro-validation (см. LIQ_CLUSTER_HITRATE_VALIDATION.md)
# поднят с 0.3 до 0.5 BTC: −15% шума (87→75 fires/неделя), recall 78→70%,
# hit rate 24→25%. См. таблицу threshold sensitivity в doc.
LIQ_CLUSTER_THRESHOLD_BTC = 0.5
CASCADE_SUPPRESS_THRESHOLD_BTC = 5.0   # если >=5 BTC уже было — каскад уже идёт
COOLDOWN_SEC = 1800                    # 30 min per (side)
# 2026-06-10 (фидбек Win/оператора): в падающем рынке long/short стороны
# чередуются и спамили 10-20 карточек за ночь, а план у ОБЕИХ сторон один
# (inverted SHORT). Глобальный дебаунс: одна TG-карточка на кластер-событие,
# вторая сторона того же тика и всё в течение 30 мин — только в журнал.
GLOBAL_COOLDOWN_SEC = 1800
POLL_INTERVAL_SEC = 60


def _read_state(path: Path = STATE_PATH) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_state(state: dict, path: Path = STATE_PATH) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        logger.exception("liq_pre_cascade.write_state_failed")


def _append_journal(entry: dict, path: Path = JOURNAL_PATH) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        logger.exception("liq_pre_cascade.journal_failed")


def mark_user_action(signal_id: str, action: str, *,
                     now: Optional[datetime] = None,
                     path: Path = JOURNAL_PATH) -> bool:
    """Mark inline-button choice on offensive plan. action: 'placed' | 'skipped'.
    Returns True if signal found in journal."""
    if now is None:
        now = datetime.now(timezone.utc)
    if not path.exists():
        return False
    rows: list[dict] = []
    found = False
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("signal_id") == signal_id:
                r["user_action"] = action
                if action == "placed":
                    r["placed_at"] = now.isoformat(timespec="seconds")
                found = True
            rows.append(r)
        if found:
            path.write_text(
                "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                encoding="utf-8",
            )
    except OSError:
        logger.exception("liq_pre_cascade.mark_user_action_failed")
    return found


def _liq_window_sums(now_utc: datetime, window_min: int,
                     liq_csv: Path = LIQ_CSV) -> tuple[float, float]:
    """Sum liq qty per side in [now-window, now]."""
    if not liq_csv.exists():
        return 0.0, 0.0
    cutoff = now_utc - timedelta(minutes=window_min)
    long_btc = 0.0
    short_btc = 0.0
    try:
        with liq_csv.open(newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                try:
                    ts = datetime.fromisoformat(r["ts_utc"])
                except (ValueError, KeyError):
                    continue
                if ts < cutoff or ts > now_utc:
                    continue
                try:
                    qty = float(r.get("qty") or 0.0)
                except ValueError:
                    continue
                if qty <= 0:
                    continue
                side = (r.get("side") or "").lower()
                if side == "long":
                    long_btc += qty
                elif side == "short":
                    short_btc += qty
    except OSError:
        logger.exception("liq_pre_cascade.read_failed")
    return long_btc, short_btc


def _read_last_btc_price() -> Optional[float]:
    """Read latest close from market_live/market_1m.csv."""
    market_1m = ROOT / "market_live" / "market_1m.csv"
    if not market_1m.exists():
        return None
    last_close = None
    try:
        with market_1m.open(encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    last_close = float(row["close"])
                except (ValueError, KeyError):
                    continue
    except OSError:
        pass
    return last_close


# Entry plans для pre-cascade clusters.
# Re-validation 2026-05-19 на n=63 SHORT fires + n=60 LONG fires
# (state/liq_pre_cascade_fires.jsonl против market_live/market_1m.csv):
#   SHORT pre-cluster → LONG @ 4h:  44.4% UP, mean +0.025%  → −EV after fees
#   SHORT pre-cluster → LONG @ 24h: 36.0% UP, mean −0.468%  → INVERTED edge!
#   LONG pre-cluster → LONG @ 4h:   46.7% UP, mean +0.028%  → −EV
#   LONG pre-cluster → LONG @ 24h:  29.2% UP, mean −0.728%  → strong INVERTED
# Старый hardcoded "75% n=20 1 неделя" — устарел/cherry-picked.
# Сейчас живой edge — inverted SHORT с 24h hold.
PRE_CASCADE_ENTRY_PLANS = {
    "short": {
        "dir": "SHORT",  # inverted from old "LONG continuation"
        "edge_note": "Re-validated 2026-05-19 (n=63 live fires): @ 4h 44.4% UP (мёртв), "
                     "@ 24h 36.0% UP = 64% DOWN, mean −0.468% / median −0.928%. "
                     "Inverted SHORT с 24h hold — после fees ~+0.32% net/trade.",
        "tp1_pct": -0.45,
        "tp2_pct": -0.90,
        "stop_pct": +0.50,
        "exit_after_h": 24,
        "size_usd": 2500,   # half-size до 30+ собственных fills
    },
    "long": {
        "dir": "SHORT",  # inverted from "no validated edge"
        "edge_note": "Re-validated 2026-05-19 (n=48 live fires): @ 24h 29.2% UP = "
                     "70.8% DOWN, mean −0.728% / median −0.898%. Сильнейшая inversion.",
        "tp1_pct": -0.45,
        "tp2_pct": -0.90,
        "stop_pct": +0.50,
        "exit_after_h": 24,
        "size_usd": 2500,
    },
}


def _format_alert(side: str, qty_btc: float,
                  long_btc: float = 0.0, short_btc: float = 0.0,
                  now: Optional[datetime] = None) -> tuple[str, dict]:
    """Build TG card text + structured plan dict.

    Returns (text, plan_info). plan_info has:
      - 'actionable': bool — есть ли trade plan (для inline buttons)
      - 'trade_dir': 'LONG' | 'SHORT' | None
      - 'entry', 'stop', 'tp1', 'tp2', 'exit_by_ts' (if actionable)
      - 'has_conflict': bool
    """
    direction_word = "LONG" if side == "long" else "SHORT"
    now_utc = now or datetime.now(timezone.utc)
    window_end = now_utc + timedelta(minutes=20)
    lines = [
        f"🔍 PRE-CASCADE liq cluster: {direction_word}",
        f"За последние {WINDOW_MINUTES} мин: {qty_btc:.2f} BTC ликвидировано (baseline ~0.01)",
        "",
    ]
    confidence = "MED"
    try:
        from services.pre_cascade_alert.multi_feature_score import (
            compute_score, is_high_confidence,
        )
        score = compute_score(
            liq_long_5min=long_btc, liq_short_5min=short_btc, now=now,
        )
        confidence = "HIGH" if is_high_confidence(score) else "MED"
    except Exception:
        logger.exception("liq_pre_cascade.score_failed")

    # 2026-06-10: окно и план ссылаются на ОДНУ границу времени — раньше
    # «не открывать 20 мин» + «offensive entry» в одной карточке путали.
    lines.append(f"⚠ Каскад-окно до {window_end.strftime('%H:%M')} UTC — внутри окна НЕ входить")
    lines.append("")

    # Validated offensive entry: SHORT pre-cluster → LONG continuation
    plan = PRE_CASCADE_ENTRY_PLANS.get(side)
    last_price = _read_last_btc_price()

    # Conflict check: if an OPPOSITE cascade fired recently, the validated edge
    # is suspect — they predict opposite directions. Read cascade_alert_dedup.
    # For SHORT-side cluster (predicts UP): conflict if cascade_long fired
    # within last 60 min (2026 inverted edge predicts DOWN).
    conflict_event: Optional[str] = None
    try:
        dedup_path = ROOT / "state" / "cascade_alert_dedup.json"
        if dedup_path.exists():
            dedup = json.loads(dedup_path.read_text(encoding="utf-8"))
            opposite_prefix = "long_" if side == "short" else "short_"
            for cascade_type, ts_iso in dedup.items():
                if not isinstance(ts_iso, str) or not cascade_type.startswith(opposite_prefix):
                    continue
                try:
                    ts = datetime.fromisoformat(ts_iso.replace("Z", "+00:00"))
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                except ValueError:
                    continue
                age_min = (now_utc - ts).total_seconds() / 60.0
                if 0 <= age_min <= 60.0:
                    conflict_event = f"{cascade_type} ({age_min:.0f} мин назад)"
                    break
    except (OSError, json.JSONDecodeError):
        pass

    plan_info: dict = {"actionable": False, "trade_dir": None,
                        "has_conflict": bool(conflict_event),
                        "confidence": confidence}

    if plan and last_price and last_price > 0:
        tp1 = last_price * (1 + plan["tp1_pct"] / 100)
        tp2 = last_price * (1 + plan["tp2_pct"] / 100)
        stop = last_price * (1 + plan["stop_pct"] / 100)
        risk = abs(plan["stop_pct"])
        rr1 = abs(plan["tp1_pct"]) / risk if risk else 0
        rr2 = abs(plan["tp2_pct"]) / risk if risk else 0
        from datetime import timedelta as _td
        exit_at = (now or datetime.now(timezone.utc)) + _td(hours=plan["exit_after_h"])
        if conflict_event:
            lines.append(f"⚠ Offensive option — CONFLICT с {conflict_event}, SKIP")
            lines.append(f"  (оба сигнала за <60 мин = whipsaw, edge не работает)")
        else:
            lines.append(f"💰 План — вход ПОСЛЕ {window_end.strftime('%H:%M')} UTC, maker-limit [{confidence}]:")
            lines.append(f"  {plan['dir']}  entry ~${last_price:,.0f}")
            lines.append(f"  Stop: ${stop:,.0f} ({plan['stop_pct']:+.2f}%)")
            lines.append(f"  TP1:  ${tp1:,.0f} (R:R 1:{rr1:.1f})")
            lines.append(f"  TP2:  ${tp2:,.0f} (R:R 1:{rr2:.1f})")
            lines.append(f"  Exit by {exit_at.strftime('%H:%M UTC')} (+{plan['exit_after_h']}h)")
            lines.append(f"  Edge: {plan['edge_note']}")
            plan_info.update({
                "actionable": True,
                "trade_dir": plan["dir"],
                "entry": round(last_price, 2),
                "stop": round(stop, 2),
                "tp1": round(tp1, 2),
                "tp2": round(tp2, 2),
                "exit_by_ts": exit_at.isoformat(timespec="seconds"),
                "edge_note": plan["edge_note"],
            })
    elif side == "long":
        lines.append("ℹ️ LONG cluster: defensive only (edge инвертировался в 2026)")

    return "\n".join(lines), plan_info


def _build_keyboard(signal_id: str):
    """Inline buttons for actionable pre-cascade offensive plan."""
    try:
        from telebot import types
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("✅ Placed", callback_data=f"pc:placed:{signal_id}"),
            types.InlineKeyboardButton("⏭ Skip", callback_data=f"pc:skip:{signal_id}"),
        )
        return kb
    except Exception:
        return None


def check_and_alert(
    *,
    send_fn: Callable,
    now: Optional[datetime] = None,
    state_path: Path = STATE_PATH,
    journal_path: Path = JOURNAL_PATH,
    liq_csv: Path = LIQ_CSV,
    window_min: int = WINDOW_MINUTES,
    cluster_threshold: float = LIQ_CLUSTER_THRESHOLD_BTC,
    cascade_suppress: float = CASCADE_SUPPRESS_THRESHOLD_BTC,
    cooldown_sec: int = COOLDOWN_SEC,
) -> list[dict]:
    """One tick of pre-cascade liq-cluster check.

    Returns list of fired-alert dicts (empty if nothing fired).
    """
    if now is None:
        now = datetime.now(timezone.utc)
    long_btc, short_btc = _liq_window_sums(now, window_min, liq_csv=liq_csv)

    state = _read_state(state_path)
    fired: list[dict] = []

    # стороны, прошедшие per-side кулдаун
    candidates: list[tuple[str, float]] = []
    for side, qty in (("long", long_btc), ("short", short_btc)):
        # Suppress если уже каскад
        if qty >= cascade_suppress:
            continue
        if qty < cluster_threshold:
            continue
        # Cooldown (per side)
        last_iso = state.get(f"last_alert_{side}")
        if last_iso:
            try:
                last_alert = datetime.fromisoformat(last_iso)
                if (now - last_alert).total_seconds() < cooldown_sec:
                    continue
            except ValueError:
                pass
        candidates.append((side, qty))

    # глобальный дебаунс (2026-06-10): одна TG-карточка на кластер-событие.
    # План у обеих сторон один (inverted SHORT) — шлём сторону с бОльшим qty,
    # остальное только в журнал. Повтор в течение GLOBAL_COOLDOWN_SEC — журнал.
    global_ok = True
    last_any = state.get("last_alert_any")
    if last_any:
        try:
            if (now - datetime.fromisoformat(last_any)).total_seconds() < GLOBAL_COOLDOWN_SEC:
                global_ok = False
        except ValueError:
            pass
    send_side = max(candidates, key=lambda x: x[1])[0] if candidates else None

    for side, qty in candidates:
        text, plan_info = _format_alert(side, qty, long_btc=long_btc,
                                          short_btc=short_btc, now=now)
        signal_id = f"pc_{now.strftime('%Y%m%d_%H%M%S')}_{side}"
        # 2026-05-18: TG send ТОЛЬКО для actionable plans (defensive-only
        # и conflict cases — silent, только в journal). Оператор:
        # "сколько текста, и каждое надо анализировать на адекватность".
        if plan_info.get("actionable") and global_ok and side == send_side:
            kb = _build_keyboard(signal_id)
            try:
                try:
                    send_fn(text, reply_markup=kb)
                except TypeError:
                    send_fn(text)
            except Exception:
                logger.exception("liq_pre_cascade.send_failed side=%s", side)
                continue
            state["last_alert_any"] = now.isoformat(timespec="seconds")
        else:
            if plan_info.get("has_conflict"):
                reason = "conflict"
            elif not plan_info.get("actionable"):
                reason = "defensive_only"
            elif not global_ok:
                reason = "global_cooldown"
            else:
                reason = "dup_side_same_tick"
            logger.info("liq_pre_cascade.silent_journal side=%s reason=%s", side, reason)

        entry = {
            "signal_id": signal_id,
            "ts": now.isoformat(timespec="seconds"),
            "side": side,
            "qty_btc": round(qty, 4),
            "window_min": window_min,
            "threshold_btc": cluster_threshold,
            "actionable": plan_info.get("actionable", False),
            "confidence": plan_info.get("confidence"),
            "has_conflict": plan_info.get("has_conflict", False),
            "trade_dir": plan_info.get("trade_dir"),
            "entry": plan_info.get("entry"),
            "stop": plan_info.get("stop"),
            "tp1": plan_info.get("tp1"),
            "tp2": plan_info.get("tp2"),
            "exit_by_ts": plan_info.get("exit_by_ts"),
            "user_action": None,
            "placed_at": None,
        }
        _append_journal(entry, journal_path)
        fired.append(entry)
        state[f"last_alert_{side}"] = now.isoformat(timespec="seconds")

    if fired:
        _write_state(state, state_path)
    return fired


async def liq_pre_cascade_loop(stop_event, *, send_fn=None,
                               interval_sec: int = POLL_INTERVAL_SEC) -> None:
    import asyncio
    if send_fn is None:
        logger.warning("liq_pre_cascade.no_send_fn — alerts будут только в логе")
    logger.info("liq_pre_cascade.start interval=%ds threshold=%.2fBTC window=%dmin",
                interval_sec, LIQ_CLUSTER_THRESHOLD_BTC, WINDOW_MINUTES)
    while not stop_event.is_set():
        try:
            if send_fn is not None:
                fired = check_and_alert(send_fn=send_fn)
                for entry in fired:
                    logger.info("liq_pre_cascade.fired side=%s qty=%.2f",
                                entry["side"], entry["qty_btc"])
        except Exception:
            logger.exception("liq_pre_cascade.tick_failed")
        try:
            await asyncio.wait_for(asyncio.shield(stop_event.wait()), timeout=interval_sec)
        except asyncio.TimeoutError:
            continue
    logger.info("liq_pre_cascade.stopped")
