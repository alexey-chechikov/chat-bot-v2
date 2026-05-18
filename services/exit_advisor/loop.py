"""Exit advisor async loop — runs every 60-300s, sends Telegram advisory alerts.

Integration point for app_runner.py:
    from services.exit_advisor.loop import exit_advisor_loop
    asyncio.create_task(exit_advisor_loop(stop_event, send_fn=send_fn))

Alert dedup:
  - Same scenario_class + side: 30 min window
  - Re-fires on severity escalation (scenario_class upgrade)
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .margin_calculator import MarginCalculator
from .outcome_tracker import OutcomeTracker
from .position_state import ScenarioClass, build_position_state
from .strategy_ranker import StrategyRanker
from .telegram_renderer import format_advisory_alert
from .honest_renderer import format_compact_advisory, format_honest_advisory

logger = logging.getLogger(__name__)

_LOOP_INTERVAL_SEC = 120          # 2-min default tick
_DEDUP_WINDOW_SEC = 7200          # 2h dedup per scenario_class — reduced spam after operator complaint 2026-05-07
_ROOT = Path(__file__).resolve().parents[2]

# Severity ordering for escalation detection
_SEVERITY_ORDER = {
    ScenarioClass.MONITORING: 0,
    ScenarioClass.EARLY_INTERVENTION: 1,
    ScenarioClass.CYCLE_DEATH: 2,
    ScenarioClass.MODERATE: 3,
    ScenarioClass.SEVERE: 4,
    ScenarioClass.CRITICAL: 5,
    ScenarioClass.URGENT_PROTECTION: 6,
}


async def exit_advisor_loop(
    stop_event: asyncio.Event,
    *,
    send_fn: Any = None,
    interval_sec: float = _LOOP_INTERVAL_SEC,
    regime_fn: Any = None,       # optional: () -> str
    session_fn: Any = None,      # optional: () -> str
) -> None:
    """Main exit advisor loop."""
    import json as _json
    from pathlib import Path as _Path

    ranker = StrategyRanker()
    margin_calc = MarginCalculator()
    tracker = OutcomeTracker()

    last_severity: int = 0

    # 2026-05-07: persist dedup_cache + dd_onset_cache между рестартами app_runner.
    # Без этого: каждый рестарт обнуляет dedup → шлёт alert повторно. Сегодня
    # был spam ~3 раза за 7 минут потому что app_runner рестартал каждые 5 мин
    # (баг в supervisor cmdline_must_contain — пофиксен отдельно).
    _DD_CACHE_PATH = _Path("data/exit_advisor/dd_onset_cache.json")
    _DEDUP_CACHE_PATH = _Path("data/exit_advisor/dedup_cache.json")

    def _load_ts_dict(path: _Path) -> dict:
        try:
            if path.exists():
                raw = _json.loads(path.read_text(encoding="utf-8"))
                out = {}
                for k, v in raw.items():
                    try:
                        out[k] = datetime.fromisoformat(v)
                    except Exception:
                        continue
                return out
        except Exception:
            logger.exception("exit_advisor.cache_load_failed path=%s", path)
        return {}

    def _save_ts_dict(path: _Path, d: dict) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {k: v.isoformat() for k, v in d.items()}
            path.write_text(_json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            logger.exception("exit_advisor.cache_save_failed path=%s", path)

    dd_onset_cache: dict[str, datetime] = _load_ts_dict(_DD_CACHE_PATH)
    dedup_cache: dict[str, datetime] = _load_ts_dict(_DEDUP_CACHE_PATH)
    if dd_onset_cache:
        logger.info("exit_advisor.dd_onset_cache.loaded n=%d", len(dd_onset_cache))
    if dedup_cache:
        logger.info("exit_advisor.dedup_cache.loaded n=%d", len(dedup_cache))

    def _save_dd_cache() -> None:
        _save_ts_dict(_DD_CACHE_PATH, dd_onset_cache)

    def _save_dedup_cache() -> None:
        _save_ts_dict(_DEDUP_CACHE_PATH, dedup_cache)

    logger.info("exit_advisor_loop.started interval=%ds send_fn=%s", interval_sec, "wired" if send_fn else "missing")

    while not stop_event.is_set():
        try:
            _tick(
                ranker=ranker,
                margin_calc=margin_calc,
                tracker=tracker,
                send_fn=send_fn,
                dedup_cache=dedup_cache,
                last_severity_holder=[last_severity],
                dd_onset_cache=dd_onset_cache,
                regime_fn=regime_fn,
                session_fn=session_fn,
            )
            last_severity = _tick.last_severity if hasattr(_tick, "last_severity") else last_severity
            # Persist DD onset + dedup cache между рестартами
            _save_dd_cache()
            _save_dedup_cache()
        except Exception:
            logger.exception("exit_advisor_loop.tick_failed")

        try:
            await asyncio.wait_for(asyncio.shield(stop_event.wait()), timeout=interval_sec)
        except asyncio.TimeoutError:
            pass


def _build_exit_keyboard(alert_id: str):
    """Exit advisor inline buttons: [A: Hedge] [B: Close 25%] [C: Hold].

    Кнопки записывают operator decision в state/exit_advisor_decisions.jsonl
    для последующего outcome filling (4h/24h post-decision PnL change)."""
    try:
        from telebot import types
        kb = types.InlineKeyboardMarkup(row_width=3)
        kb.add(
            types.InlineKeyboardButton("A: Hedge", callback_data=f"exit:hedge:{alert_id}"),
            types.InlineKeyboardButton("B: Close 25%", callback_data=f"exit:close25:{alert_id}"),
            types.InlineKeyboardButton("C: Hold", callback_data=f"exit:hold:{alert_id}"),
        )
        return kb
    except Exception:
        return None


def _tick(
    *,
    ranker: StrategyRanker,
    margin_calc: MarginCalculator,
    tracker: OutcomeTracker,
    send_fn: Any,
    dedup_cache: dict[str, datetime],
    last_severity_holder: list[int],
    dd_onset_cache: dict[str, datetime],
    regime_fn: Any,
    session_fn: Any,
) -> None:
    """Single synchronous tick of the exit advisor."""
    # 1. Build position state
    current_price = _get_current_price()
    state = build_position_state(current_price=current_price, dd_onset_cache=dd_onset_cache)

    # Track followup outcomes
    fired = tracker.tick(state)
    for outcome in fired:
        logger.info("exit_advisor.followup: %s", outcome)

    # Nothing to do if monitoring
    if not state.has_active_position:
        return
    if state.scenario_class == ScenarioClass.MONITORING:
        return

    # 2. Dedup check.
    # 2026-05-07: убрал escalated-обход (was: alert проходил каждый рестарт
    # потому что last_severity in-memory обнулялся → 0→6 = escalation).
    # Теперь dedup_window=2h применяется СТРОГО, без escalation override.
    # Если scenario действительно ухудшился (CYCLE_DEATH → SEVERE → CRITICAL)
    # — для каждого свой sc_key → каждый получит свой alert.
    now = state.captured_at
    sc_key = state.scenario_class.value
    last_sent = dedup_cache.get(sc_key)
    current_severity = _SEVERITY_ORDER.get(state.scenario_class, 0)
    within_window = last_sent is not None and (now - last_sent) < timedelta(seconds=_DEDUP_WINDOW_SEC)

    if within_window:
        ago_min = (now - last_sent).total_seconds() / 60
        logger.info(
            "exit_advisor.dedup_suppressed scenario=%s last_sent_ago=%.0fmin window=%dmin",
            sc_key, ago_min, _DEDUP_WINDOW_SEC // 60,
        )
        last_severity_holder[0] = current_severity
        return

    # 3. Get regime + session
    regime = regime_fn() if callable(regime_fn) else "unknown"
    session = session_fn() if callable(session_fn) else "NONE"

    # 4. Rank strategies
    strategies = ranker.rank(
        state,
        regime=regime,
        session=session,
        max_results=6,
        min_free_margin_usd=state.free_margin_usd,
    )

    if not strategies:
        last_severity_holder[0] = current_severity
        return

    # 5. Compute margins
    short_btc = abs(state.short_side.total_position_btc)
    margin_reqs = margin_calc.compute_all(
        strategies,
        current_price=state.current_price,
        free_margin_usd=state.free_margin_usd,
        total_balance_usd=state.total_balance_usd,
        short_position_btc=short_btc,
    )

    # 6. Format and send.
    # 2026-05-12: switched to compact renderer + dedup. Operator feedback:
    # 30-line message every hour with identical playbook = visual spam.
    # Compact renderer skips if no material change since last hour (uPnL ±$50,
    # DD age ≥1h, liq_dist ≥1% drop). Critical conditions (liq≤10%, DD≥8h,
    # margin<70%) always fire. Full playbook moved to /playbook on-demand.
    card, is_critical = format_compact_advisory(state)
    if card and send_fn is not None:
        try:
            alert_id = f"exit_{sc_key}_{now.strftime('%Y%m%d_%H%M%S')}"
            kb = _build_exit_keyboard(alert_id)
            try:
                send_fn(card, reply_markup=kb)
            except TypeError:
                if callable(send_fn):
                    send_fn(card)
            dedup_cache[sc_key] = now
            logger.info(
                "exit_advisor.alert_sent scenario=%s severity=%d critical=%s",
                sc_key, current_severity, is_critical,
            )
        except Exception:
            logger.exception("exit_advisor.send_failed")

    last_severity_holder[0] = current_severity


def _get_current_price() -> float:
    """Get current BTC price.

    Priority: state/deriv_live.json (mark_price, обновляется каждые 5 мин)
    → market_live/market_1m.csv last bar close → 0.
    Раньше читалось storage/market_state.json но там нет поля price (бага в alert).
    """
    import json
    # 1) deriv_live (freshest, includes mark_price from Binance perp)
    try:
        p = _ROOT / "state" / "deriv_live.json"
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            btc = data.get("BTCUSDT", {}) or {}
            mp = float(btc.get("mark_price", 0) or 0)
            if mp > 0:
                return mp
    except Exception:
        pass
    # 2) market_1m last close
    try:
        import csv
        p = _ROOT / "market_live" / "market_1m.csv"
        if p.exists():
            last_close = 0.0
            with p.open(newline="", encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    try:
                        last_close = float(row.get("close") or 0)
                    except (KeyError, ValueError):
                        pass
            if last_close > 0:
                return last_close
    except Exception:
        pass
    return 0.0
