from __future__ import annotations

import asyncio
import logging
import signal
import sys
from datetime import datetime, timezone
from typing import Callable

from config import (
    KILLSWITCH_DRAWDOWN_THRESHOLD_PCT,
    KILLSWITCH_FLASH_THRESHOLD_PCT,
    KILLSWITCH_INITIAL_BALANCE_USD,
    ORCHESTRATOR_DAILY_REPORT_TIME,
    ORCHESTRATOR_ENABLE_AUTO_ALERTS,
    ORCHESTRATOR_LOOP_INTERVAL_SEC,
)
from core.orchestrator.orchestrator_loop import OrchestratorLoop

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("app_runner")


def _build_orchestrator_config() -> dict:
    return {
        "ORCHESTRATOR_LOOP_INTERVAL_SEC": ORCHESTRATOR_LOOP_INTERVAL_SEC,
        "ORCHESTRATOR_DAILY_REPORT_TIME": ORCHESTRATOR_DAILY_REPORT_TIME,
        "ORCHESTRATOR_ENABLE_AUTO_ALERTS": ORCHESTRATOR_ENABLE_AUTO_ALERTS,
        "KILLSWITCH_INITIAL_BALANCE_USD": KILLSWITCH_INITIAL_BALANCE_USD,
        "KILLSWITCH_DRAWDOWN_THRESHOLD_PCT": KILLSWITCH_DRAWDOWN_THRESHOLD_PCT,
        "KILLSWITCH_FLASH_THRESHOLD_PCT": KILLSWITCH_FLASH_THRESHOLD_PCT,
    }


def _install_signal_handlers(loop: asyncio.AbstractEventLoop, stop_event: asyncio.Event) -> None:
    def _fallback_handler(signum, _frame) -> None:
        logger.info("app_runner.signal_received signum=%s", signum)
        loop.call_soon_threadsafe(stop_event.set)

    try:
        loop.add_signal_handler(signal.SIGINT, stop_event.set)
    except NotImplementedError:
        signal.signal(signal.SIGINT, _fallback_handler)

    if sys.platform != "win32":
        try:
            loop.add_signal_handler(signal.SIGTERM, stop_event.set)
        except NotImplementedError:
            pass


def _log_startup_audit() -> None:
    """Append timestamp + pid to state/app_runner_starts.jsonl. Used by audit
    tooling to detect restart loops."""
    import json
    import os
    from pathlib import Path
    audit = Path("state") / "app_runner_starts.jsonl"
    try:
        audit.parent.mkdir(parents=True, exist_ok=True)
        with audit.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "pid": os.getpid(),
            }) + "\n")
    except OSError:
        pass


async def _run_heartbeat(stop_event: asyncio.Event) -> None:
    """Periodic heartbeat to logs/app.log so watchdog freshness check never
    triggers stale-restart on quiet markets.

    2026-05-10: even with watchdog freshness=15min, app.log can go silent
    longer when smart-pause filters out detector emits + grid_coordinator
    is on cooldown. Heartbeat ensures log mtime is bumped every 60s.
    """
    interval = 60
    while not stop_event.is_set():
        logger.info("heartbeat.tick t=%s", datetime.now(timezone.utc).isoformat(timespec="seconds"))
        try:
            await asyncio.wait_for(asyncio.shield(stop_event.wait()), timeout=interval)
        except asyncio.TimeoutError:
            pass


async def _run_polling_in_executor(app) -> None:
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, app.run_polling_blocking)


async def _run_protection_alerts(stop_event: asyncio.Event) -> None:
    from services.protection_alerts import ProtectionAlerts
    pa = ProtectionAlerts.instance()
    while not stop_event.is_set():
        await pa.tick()
        try:
            await asyncio.wait_for(asyncio.shield(stop_event.wait()), timeout=30.0)
        except asyncio.TimeoutError:
            pass


async def _run_counter_long(stop_event: asyncio.Event) -> None:
    from services.counter_long_manager import CounterLongManager
    mgr = CounterLongManager()
    while not stop_event.is_set():
        await mgr.tick()
        try:
            await asyncio.wait_for(asyncio.shield(stop_event.wait()), timeout=30.0)
        except asyncio.TimeoutError:
            pass


async def _run_boundary_expand(stop_event: asyncio.Event) -> None:
    from services.boundary_expand_manager import BoundaryExpandManager
    mgr = BoundaryExpandManager.instance()
    while not stop_event.is_set():
        await mgr.tick()
        try:
            await asyncio.wait_for(asyncio.shield(stop_event.wait()), timeout=60.0)
        except asyncio.TimeoutError:
            pass


async def _run_adaptive_grid(stop_event: asyncio.Event) -> None:
    from services.adaptive_grid_manager import AdaptiveGridManager
    mgr = AdaptiveGridManager.instance()
    while not stop_event.is_set():
        await mgr.tick()
        try:
            await asyncio.wait_for(asyncio.shield(stop_event.wait()), timeout=300.0)
        except asyncio.TimeoutError:
            pass


async def _run_paper_journal(stop_event: asyncio.Event) -> None:
    from services.advise_v2.paper_journal import paper_journal_loop
    await paper_journal_loop(stop_event=stop_event)


async def _run_weekly_audit(stop_event: asyncio.Event) -> None:
    """Weekly paper_trader filter audit (Mon 10:00 UTC). См. weekly_audit_loop.py.

    Использует scripts/done.py для TG-доставки — это уже отлаженный канал.
    """
    import subprocess
    from services.paper_trader.weekly_audit_loop import weekly_audit_loop

    def _send(text: str) -> None:
        try:
            subprocess.run(
                ["python", "scripts/done.py", text],
                check=False, timeout=10,
            )
        except Exception:
            logger.exception("weekly_audit.done_py_failed")

    await weekly_audit_loop(stop_event=stop_event, send_fn=_send)


async def _run_decision_log(stop_event: asyncio.Event) -> None:
    from services.decision_log import decision_log_loop

    await decision_log_loop(stop_event=stop_event)


async def _run_dashboard(stop_event: asyncio.Event) -> None:
    from services.dashboard import dashboard_state_loop

    await dashboard_state_loop(stop_event=stop_event)


async def _run_dashboard_http(stop_event: asyncio.Event) -> None:
    from services.dashboard.http_server import dashboard_http_server

    await dashboard_http_server(stop_event=stop_event)


async def _run_setup_detector(stop_event: asyncio.Event, *, telegram_app=None) -> None:
    """Setup detector loop with optional Telegram push on new high-confidence
    setups. send_fn signature matches stale_monitor / paper_trader convention.
    Only setups with confidence >= SETUP_PUSH_MIN_CONFIDENCE get pushed —
    avoids spam from low-strength signals.
    """
    from services.setup_detector.loop import setup_detector_loop

    SETUP_PUSH_MIN_CONFIDENCE = 70.0
    # Push priority types — push regardless of confidence (still backtest-validated).
    PRIORITY_TYPES = {
        "long_div_bos_confirmed",   # PF=4.49 hold_1h, walk-forward stable
        "long_div_bos_15m",          # PF=5.01 hold_4h
    }

    send_fn = None
    if telegram_app is not None and getattr(telegram_app, "allowed_chat_ids", None):
        from services.telegram.channel_router import get_routine_chat_ids
        from services.telegram.severity_prefix import classify_severity, with_prefix
        primary_chat_ids = list(telegram_app.allowed_chat_ids)
        routine_chat_ids = get_routine_chat_ids() or primary_chat_ids
        bot = telegram_app.bot

        def _send(card_text: str, setup=None) -> None:
            """Push a setup card to Telegram. Filters + channel routing:
              - priority types (LONG_DIV_BOS_*) → always push
              - other types → only if confidence_pct >= SETUP_PUSH_MIN_CONFIDENCE
              - skip GRID_* and DEFENSIVE_* (operator already sees those in /advise)
              - p15_* lifecycle:
                  OPEN/CLOSE → PRIMARY chat (operator must see cycle boundaries)
                  REENTRY/HARVEST → ROUTINE chat (low-signal layer events)
            """
            stype = ""
            conf = 0.0
            stage = ""
            if setup is not None:
                stype = setup.setup_type.value if hasattr(setup, "setup_type") else ""
                conf = float(getattr(setup, "confidence_pct", 0))
                if stype.startswith("grid_") or stype.startswith("def_"):
                    return
                if stype not in PRIORITY_TYPES and conf < SETUP_PUSH_MIN_CONFIDENCE:
                    # P-15 lifecycle events have no confidence — let them through
                    if not stype.startswith("p15_"):
                        return
                # Decode p15 stage from basis
                if stype.startswith("p15_"):
                    for b in getattr(setup, "basis", []) or []:
                        if getattr(b, "label", "") == "stage":
                            stage = str(getattr(b, "value", ""))
                            break

            # Pick channel
            if stype.startswith("p15_"):
                if stage in {"REENTRY", "HARVEST"}:
                    emitter = "P15_REENTRY" if stage == "REENTRY" else "P15_HARVEST"
                    target_chat_ids = routine_chat_ids
                else:
                    emitter = "P15_OPEN" if stage == "OPEN" else "P15_CLOSE"
                    target_chat_ids = primary_chat_ids
            else:
                emitter = "SETUP_ON"
                target_chat_ids = primary_chat_ids

            try:
                sev = classify_severity(emitter, card_text, {"confidence": conf})
                card_text = with_prefix(sev, card_text)
            except Exception:
                logger.exception("setup_detector.prefix_failed emitter=%s", emitter)

            for cid in target_chat_ids:
                try:
                    bot.send_message(cid, card_text)
                except Exception:
                    logger.exception("setup_detector.telegram_send_failed cid=%s", cid)

        send_fn = _send

    # Multi-symbol detection: BTC + ETH + XRP.
    # ETH-only divergence is the strongest single-asset edge per TZ-3 backtest
    # (PF=7.43 hold_12h vs BTC's 5.36). XRP added 2026-05-09 because P-15
    # validation (BTC/ETH/XRP × LONG/SHORT, 6/6 PF>3) requires XRP coverage —
    # post-14bbd2e diagnosis showed XRP was the only pair with active P-15
    # long_gate while BTC/ETH sat in flat (e50≈e200). Detectors that need
    # data not available for XRP (e.g. ICT) short-circuit on missing inputs.
    await setup_detector_loop(
        stop_event=stop_event,
        send_fn=send_fn,
        pairs=("BTCUSDT", "ETHUSDT", "XRPUSDT"),
    )


async def _run_daily_weekly_reports(stop_event: asyncio.Event, *, telegram_app=None) -> None:
    """Schedule daily (21:00 UTC) and weekly (Sun 21:00 UTC) report posts.

    Polls every 5 min. State (last sent date/week) lives in
    state/_reports_last_sent.json so we don't double-post on restart.
    Cold-start: if started after 21:00 UTC and today's daily wasn't sent,
    send it now.
    """
    import json as _json
    from datetime import datetime, timezone, timedelta
    from pathlib import Path as _Path
    from services.advisor.daily_report import (
        build_daily_report, build_weekly_report,
        save_daily_report, save_weekly_report,
    )

    state_path = _Path("state/_reports_last_sent.json")
    state_path.parent.mkdir(parents=True, exist_ok=True)

    def _read_state() -> dict:
        if not state_path.exists():
            return {}
        try:
            return _json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _write_state(s: dict) -> None:
        try:
            state_path.write_text(_json.dumps(s), encoding="utf-8")
        except Exception:
            logger.exception("daily_report.state_write_failed")

    send_fn = None
    if telegram_app is not None and getattr(telegram_app, "allowed_chat_ids", None):
        chat_ids = list(telegram_app.allowed_chat_ids)
        bot = telegram_app.bot

        def _send(text: str) -> None:
            for cid in chat_ids:
                try:
                    bot.send_message(cid, text)
                except Exception:
                    logger.exception("daily_report.telegram_send_failed cid=%s", cid)

        send_fn = _send

    REPORT_HOUR_UTC = 21
    POLL_INTERVAL = 300   # 5 min

    logger.info("daily_report.scheduler.start (daily 21:00 UTC, weekly Sun 21:00 UTC)")

    while not stop_event.is_set():
        try:
            now = datetime.now(timezone.utc)
            today_str = now.strftime("%Y-%m-%d")
            iso_year, iso_week, weekday_iso = now.isocalendar()
            this_week_str = f"{iso_year}-W{iso_week:02d}"
            state = _read_state()

            # Daily report
            if (
                now.hour >= REPORT_HOUR_UTC
                and state.get("last_daily") != today_str
            ):
                try:
                    text = build_daily_report(now)
                    save_daily_report(text, now)
                    if send_fn:
                        send_fn(text)
                    state["last_daily"] = today_str
                    _write_state(state)
                    logger.info("daily_report.sent date=%s", today_str)
                except Exception:
                    logger.exception("daily_report.daily_failed")

            # Weekly report — Sunday only (isoweekday 7)
            if (
                weekday_iso == 7
                and now.hour >= REPORT_HOUR_UTC
                and state.get("last_weekly") != this_week_str
            ):
                try:
                    text = build_weekly_report(now)
                    save_weekly_report(text, now)
                    if send_fn:
                        send_fn(text)
                    state["last_weekly"] = this_week_str
                    _write_state(state)
                    logger.info("weekly_report.sent week=%s", this_week_str)
                except Exception:
                    logger.exception("daily_report.weekly_failed")
        except Exception:
            logger.exception("daily_report.scheduler.tick_failed")

        try:
            await asyncio.wait_for(asyncio.shield(stop_event.wait()), timeout=POLL_INTERVAL)
        except asyncio.TimeoutError:
            pass


async def _run_decision_layer_emitter(stop_event: asyncio.Event, *, telegram_app=None) -> None:
    """Push Decision Layer PRIMARY events from decisions.jsonl to Telegram.

    Closes the gap from DECISION_LAYER_v1 §2 (TZ-DECISION-LAYER-TELEGRAM,
    step 4 of 7) which never landed. The layer has been emitting PRIMARY
    events to decisions.jsonl since Apr-May 2026 but operator never saw
    them. Cold-start safe: skips backlog, only pushes events going forward.
    """
    from services.decision_layer.telegram_emitter import decision_layer_telegram_loop

    send_fn = None
    if telegram_app is not None and getattr(telegram_app, "allowed_chat_ids", None):
        chat_ids = list(telegram_app.allowed_chat_ids)
        bot = telegram_app.bot

        def _send(text: str) -> None:
            for cid in chat_ids:
                try:
                    bot.send_message(cid, text)
                except Exception:
                    logger.exception("decision_layer.telegram_send_failed cid=%s", cid)

        send_fn = _send

    await decision_layer_telegram_loop(stop_event=stop_event, send_fn=send_fn)


async def _run_stale_monitor(stop_event: asyncio.Event, *, telegram_app=None) -> None:
    """Stale data monitor — alerts via Telegram when critical sources go stale."""
    from services.stale_monitor import stale_monitor_loop

    send_fn = None
    if telegram_app is not None and getattr(telegram_app, "allowed_chat_ids", None):
        chat_ids = list(telegram_app.allowed_chat_ids)
        bot = telegram_app.bot

        def _send(text: str) -> None:
            for cid in chat_ids:
                try:
                    bot.send_message(cid, text)
                except Exception:
                    logger.exception("stale_monitor.telegram_send_failed cid=%s", cid)

        send_fn = _send

    await stale_monitor_loop(stop_event=stop_event, send_fn=send_fn)


async def _run_paper_trader(stop_event: asyncio.Event, *, telegram_app=None) -> None:
    """Paper trader v0.1 (TZ-PAPER-TRADER 2026-05-07).

    Reads setups.jsonl + current price, opens/closes paper trades, sends
    Telegram alerts via the SHARED bot instance (no second polling client).
    """
    from services.paper_trader.loop import paper_trader_loop

    send_fn = None
    if telegram_app is not None and getattr(telegram_app, "allowed_chat_ids", None):
        chat_ids = list(telegram_app.allowed_chat_ids)
        bot = telegram_app.bot

        def _send(text: str) -> None:
            for cid in chat_ids:
                try:
                    bot.send_message(cid, text)
                except Exception:
                    logger.exception("paper_trader.telegram_send_failed cid=%s", cid)

        send_fn = _send

    await paper_trader_loop(stop_event=stop_event, send_fn=send_fn)


async def _run_setup_tracker(stop_event: asyncio.Event) -> None:
    from services.setup_detector.tracker import setup_tracker_loop

    await setup_tracker_loop(stop_event=stop_event)


async def _run_exit_advisor(stop_event: asyncio.Event, *, telegram_app=None) -> None:
    """Exit advisory for live SHORT/LONG positions.

    2026-05-07 morning: ОПАСНЫЙ модуль (operator complaint 14:56). Шлёт 'EMERGENCY:
    Close ALL SHORT' с EV +$2 одинаковым для всех вариантов — scoring сломан.

    2026-05-07 evening: переписан honest_renderer без fake EV. Только факты +
    playbook context + HARD BAN list. Включён по умолчанию.
    Чтобы выключить (если что-то опять не так): EXIT_ADVISOR_SEND_TELEGRAM=0
    """
    import os as _os
    from services.exit_advisor.loop import exit_advisor_loop

    send_fn = None
    enable_telegram = _os.environ.get("EXIT_ADVISOR_SEND_TELEGRAM", "1") == "1"
    if enable_telegram and telegram_app is not None and getattr(telegram_app, "allowed_chat_ids", None):
        chat_ids = list(telegram_app.allowed_chat_ids)
        bot = telegram_app.bot

        def _send(text: str) -> None:
            for cid in chat_ids:
                try:
                    bot.send_message(cid, text)
                except Exception:
                    logger.exception("exit_advisor.telegram_send_failed cid=%s", cid)

        send_fn = _send
    else:
        logger.warning("exit_advisor.telegram_disabled (set EXIT_ADVISOR_SEND_TELEGRAM=1 to enable)")

    await exit_advisor_loop(stop_event=stop_event, send_fn=send_fn)


async def _run_market_intelligence(stop_event: asyncio.Event) -> None:
    from services.market_intelligence.loop import market_intelligence_loop

    await market_intelligence_loop(stop_event=stop_event)


async def _run_market_forward_analysis(stop_event: asyncio.Event) -> None:
    from services.market_forward_analysis.loop import market_forward_analysis_loop

    await market_forward_analysis_loop(stop_event=stop_event)


async def _run_deriv_live(stop_event: asyncio.Event) -> None:
    """Live OI/funding poll every 5 min — fixes P0 #3 (deriv data was stale 4+ days)."""
    from services.deriv_live import deriv_live_loop

    await deriv_live_loop(stop_event=stop_event)


async def _run_cascade_alert(stop_event: asyncio.Event, *, telegram_app=None) -> None:
    """Live cascade alert — активация post-cascade edge (TZ 2026-05-07).

    Каждые 60 сек проверяет market_live/liquidations.csv. Если long/short
    cascade ≥5 BTC за 5 мин → push в Telegram с историческими цифрами edge.
    """
    from services.cascade_alert import cascade_alert_loop
    from services.telegram.channel_router import build_send_fn

    send_fn = build_send_fn(telegram_app, "LIQ_CASCADE")
    await cascade_alert_loop(stop_event=stop_event, send_fn=send_fn)


async def _run_cascade_accuracy_eval(stop_event: asyncio.Event, *, telegram_app=None) -> None:
    """KPI feedback-loop: каждый час evaluate_pending заполняет realized_pct
    для прогнозов где прошло >=4/12/24h. Раз в сутки evaluate_drift —
    если accuracy <60% при n>=10, шлёт TG-warning + помечает edge stale."""
    from services.cascade_alert.loop import cascade_accuracy_eval_loop
    from services.telegram.channel_router import build_send_fn
    drift_send_fn = build_send_fn(telegram_app, "ENGINE_ALERT") if telegram_app else None
    await cascade_accuracy_eval_loop(stop_event=stop_event, drift_send_fn=drift_send_fn)


async def _run_liq_pre_cascade(stop_event: asyncio.Event, *, telegram_app=None) -> None:
    """Phase-1 pre-cascade signal по кластеризации мелких liq (R&D 2026-05-13).
    Если >=0.3 BTC liq на одной стороне за 5 мин (и нет уже >=5 BTC) — TG-alert
    'возможен каскад через 10-20 мин'. Cooldown 30 мин/сторона."""
    from services.pre_cascade_alert.liq_clustering import liq_pre_cascade_loop
    from services.telegram.channel_router import build_send_fn
    send_fn = build_send_fn(telegram_app, "LIQ_CLUSTER_BUILD") if telegram_app else None
    await liq_pre_cascade_loop(stop_event=stop_event, send_fn=send_fn)


async def _run_weekly_self_report(stop_event: asyncio.Event, *, telegram_app=None) -> None:
    """Weekly self-report (вс 18:00 UTC): cascade KPI + edge drift + risk-limit violations."""
    from services.reports.weekly_self_report import maybe_send_weekly
    from services.cascade_alert.accuracy_tracker import summary as kpi_summary
    from services.cascade_alert.edge_drift_guard import get_status_summary as drift_summary
    from services.telegram.channel_router import build_send_fn

    send_fn = build_send_fn(telegram_app, "ENGINE_ALERT") if telegram_app else None
    interval_sec = 600  # 10 min poll; actual send happens once/week
    logger.info("weekly_self_report.start interval=%ds", interval_sec)
    while not stop_event.is_set():
        try:
            if send_fn is not None:
                sent = maybe_send_weekly(
                    send_fn=send_fn,
                    summary_fn=kpi_summary,
                    drift_summary_fn=drift_summary,
                )
                if sent:
                    logger.info("weekly_self_report.sent")
        except Exception:
            logger.exception("weekly_self_report.tick_failed")
        try:
            await asyncio.wait_for(asyncio.shield(stop_event.wait()), timeout=interval_sec)
        except asyncio.TimeoutError:
            continue
    logger.info("weekly_self_report.stopped")


def _build_rh_send_fn(telegram_app):
    """Build send_fn that supports reply_markup for inline keyboards."""
    from services.telegram.channel_router import build_send_fn
    raw_send = build_send_fn(telegram_app, "SETUP_ON") if telegram_app else None

    def _send_with_kb(text, reply_markup=None, **kwargs):
        if telegram_app is None or raw_send is None:
            return
        if reply_markup is None:
            raw_send(text)
            return
        try:
            for cid in telegram_app.allowed_chat_ids:
                telegram_app.bot.send_message(cid, text, reply_markup=reply_markup)
        except Exception:
            logger.exception("range_hunter.send_with_kb_failed")
    return _send_with_kb


def _rh_params_for(variant: str, symbol: str):
    """Build params for 1m baseline or 5m second-tier variant."""
    from services.range_hunter.signal import RangeHunterParams
    if variant == "5m":
        # Walk-forward 2y: 70.6% WR, +$80.7K, DD per fold -$1533
        # DD в 5× больше baseline → size = $2.5K (vs $5K на 1m).
        # require_low_vol=True: защита от каскадных событий в hold-окне 24ч.
        return RangeHunterParams(
            symbol=symbol,
            lookback_h=12, range_max_pct=2.50, atr_pct_max=0.25,
            trend_max_pct_per_h=0.20, cooldown_h=4,
            width_pct=0.30, hold_h=24, stop_loss_pct=0.60,
            size_usd=2500.0, contract="XBTUSDT",
            bar_minutes=5, variant_name="5m",
            require_low_vol=True,
        )
    # default 1m
    return RangeHunterParams(symbol=symbol)


async def _run_range_hunter_signal(stop_event: asyncio.Event, *, telegram_app=None,
                                    symbol: str = "BTCUSDT", variant: str = "1m") -> None:
    """Range Hunter — TG-эмиттер semi-manual mean-revert стратегии.
    Multi-asset (BTC/ETH/XRP) × Multi-TF (1m / 5m).
    Walk-forward 2y backtests:
      1m baseline: BTC 68%, ETH 74%, XRP 77% WR
      5m champion: 70% WR, $26/trade (vs $9 на 1m), 4.5× больше PnL"""
    from services.range_hunter.loop import range_hunter_signal_loop
    params = _rh_params_for(variant, symbol)
    await range_hunter_signal_loop(stop_event=stop_event,
                                    send_fn=_build_rh_send_fn(telegram_app),
                                    params=params)


async def _run_range_hunter_outcome(stop_event: asyncio.Event, *, telegram_app=None,
                                     symbol: str = "BTCUSDT", variant: str = "1m") -> None:
    """Outcome tracker: следит за placed signals, симулирует fill BUY/SELL/SL/timeout
    на свежих данных, пишет результат в journal. Hedge advisor."""
    from services.range_hunter.loop import range_hunter_outcome_loop
    from services.telegram.channel_router import build_send_fn
    hedge_send = build_send_fn(telegram_app, "SETUP_ON") if telegram_app else None
    params = _rh_params_for(variant, symbol)
    await range_hunter_outcome_loop(stop_event=stop_event,
                                     hedge_send_fn=hedge_send,
                                     params=params)


async def _run_cliff_monitor(stop_event: asyncio.Event, *, telegram_app=None) -> None:
    """Cliff monitor: каждые 5 мин проверяет SHORT-T2 боты + bag aggregate.
    Per-bot пороги: WARNING −$1500, DANGER −$3000. Bag: суммы по всем SHORT."""
    import csv as _csv
    from pathlib import Path as _Path
    from services.ginarea_api.cliff_monitor import (
        check_short_t2_bots,
        check_short_bag_aggregate,
    )
    from services.telegram.channel_router import build_send_fn

    send_fn = build_send_fn(telegram_app, "MARGIN_ALERT") if telegram_app else None

    snapshots_csv = _Path("ginarea_live/snapshots.csv")
    interval_sec = 300  # 5 min

    def _latest_bots() -> list[dict]:
        if not snapshots_csv.exists():
            return []
        latest: dict[str, dict] = {}
        try:
            with snapshots_csv.open(newline="", encoding="utf-8") as fh:
                for row in _csv.DictReader(fh):
                    bid = row.get("bot_id", "").strip()
                    if not bid:
                        continue
                    latest[bid] = row
        except OSError:
            return []
        bots = []
        for bid, row in latest.items():
            try:
                position_btc = float(row.get("position") or 0.0)
                unrealized = float(row.get("current_profit") or 0.0)
            except ValueError:
                continue
            bots.append({
                "bot_id": bid,
                "alias": row.get("alias", "") or row.get("bot_name", ""),
                "position_btc": position_btc,
                "unrealized_usd": unrealized,
            })
        return bots

    logger.info("cliff_monitor.start interval=%ds", interval_sec)
    while not stop_event.is_set():
        try:
            bots = _latest_bots()
            if bots and send_fn is not None:
                check_short_t2_bots(bots, send_fn=send_fn)
                check_short_bag_aggregate(bots, send_fn=send_fn)
        except Exception:
            logger.exception("cliff_monitor.tick_failed")
        try:
            await asyncio.wait_for(asyncio.shield(stop_event.wait()), timeout=interval_sec)
        except asyncio.TimeoutError:
            continue
    logger.info("cliff_monitor.stopped")


async def _run_spike_alert(stop_event: asyncio.Event, *, telegram_app=None) -> None:
    """Spike-defensive alert (2026-05-09 operator request).

    |move 5m| >= 1.5%, taker dominant >= 75%, OI not bleeding off → TG alert
    "spike! close SHORT-bags" (or LONG-bags on downspike). Doesn't trade.
    Goal: prevent $4-7k drawdown when 3 SHORT bots take a +3% spike together.
    """
    from services.spike_alert import spike_alert_loop
    from services.telegram.channel_router import build_send_fn

    send_fn = build_send_fn(telegram_app, "GRID_EXHAUSTION")
    await spike_alert_loop(stop_event=stop_event, send_fn=send_fn)


async def _run_grid_coordinator(stop_event: asyncio.Event, *, telegram_app=None) -> None:
    """Grid Coordinator — индикатор истощения движения для grid-ботов оператора.

    Каждые 5 мин проверяет 5 сигналов истощения (RSI/MFI/volume/OI/ETH-sync).
    Если 3+ совпадают — TG-алерт. Не торгует, не управляет ботами через API
    (пока). По задаче оператора 2026-05-09: «нужно понимать когда движение
    заканчивается, закрыть SHORT-сетку наверху, перезайти на откате».
    """
    from services.grid_coordinator import grid_coordinator_loop
    from services.telegram.channel_router import build_send_fn

    send_fn = build_send_fn(telegram_app, "GRID_EXHAUSTION")
    await grid_coordinator_loop(stop_event=stop_event, send_fn=send_fn)


async def _run_grid_coordinator_intraday(stop_event: asyncio.Event, *, telegram_app=None) -> None:
    """15m parallel grid_coordinator — downside-only intraday flush detector.

    Catches fast capitulation lows (e.g. 21 Apr 19:46, 29 Apr 18:10 in
    operator's referenced extrema) that the 1h main loop misses. Score>=4
    threshold, 15-min cooldown.
    """
    from services.grid_coordinator.loop import grid_coordinator_intraday_loop

    from services.telegram.channel_router import build_send_fn

    send_fn = build_send_fn(telegram_app, "GRID_EXHAUSTION")
    await grid_coordinator_intraday_loop(stop_event=stop_event, send_fn=send_fn)


async def _run_pre_cascade_alert(stop_event: asyncio.Event, *, telegram_app=None) -> None:
    """Stage B4 — pre-cascade liquidation prediction (2026-05-09 roadmap).

    Fires 10-30 min BEFORE a likely cascade based on OI+funding+LS-ratio
    crowding signature. TG-only, no trading.
    """
    from services.pre_cascade_alert import pre_cascade_alert_loop
    from services.telegram.channel_router import build_send_fn

    send_fn = build_send_fn(telegram_app, "LIQ_CLUSTER_BUILD")
    await pre_cascade_alert_loop(stop_event=stop_event, send_fn=send_fn)


async def _run_regime_narrator(stop_event: asyncio.Event, *, telegram_app=None) -> None:
    """Stage E2 — LLM regime narrator (Anthropic Haiku 4.5).

    Hourly briefing TG card with derived market state + LLM analysis.
    Idle if ANTHROPIC_API_KEY unset or REGIME_NARRATOR_ENABLED=0.
    """
    from services.regime_narrator import regime_narrator_loop

    send_fn = None
    if telegram_app is not None and getattr(telegram_app, "allowed_chat_ids", None):
        chat_ids = list(telegram_app.allowed_chat_ids)
        bot = telegram_app.bot

        def _send(text: str) -> None:
            for cid in chat_ids:
                try:
                    bot.send_message(cid, text)
                except Exception:
                    logger.exception("regime_narrator.telegram_send_failed cid=%s", cid)

        send_fn = _send

    await regime_narrator_loop(stop_event=stop_event, send_fn=send_fn)


async def _run_regime_shadow(stop_event: asyncio.Event) -> None:
    """Stage B3 — ML regime classifier shadow mode (2026-05-09 roadmap).

    Observation-only: parallel to Classifier A. Logs verdicts of both for
    30d offline comparison. Switch decision is operator-driven later.
    """
    from services.regime_shadow import regime_shadow_loop
    await regime_shadow_loop(stop_event=stop_event)


# 2026-05-11 TZ-B10: test3_tpflat simulators retired. Both wired
# 2026-05-09 to do a 7d paper run of TP=$10 / TP=$5 SHORT-fade strategies.
# After 2 days neither produced a single CLOSE event — gate fires, position
# opens, market trends up, TP never hit. Simulator essentially stalled.
# Decision: retire. The strategy itself is salvageable but needs a
# revised gate / TP architecture; rebuilding from scratch is cheaper than
# debugging the current loops. Service code preserved on disk in case
# we want to reference it; tasks below removed from all_tasks.
# See docs/STRATEGIES/TEST3_TPFLAT_RETIRED.md.


async def _run_watchlist(stop_event: asyncio.Event, *, telegram_app=None) -> None:
    """Watchlist — оператор задаёт правила (/watch add ...), бот алертит при срабатывании."""
    from services.watchlist import watchlist_loop

    send_fn = None
    if telegram_app is not None and getattr(telegram_app, "allowed_chat_ids", None):
        chat_ids = list(telegram_app.allowed_chat_ids)
        bot = telegram_app.bot

        def _send(text: str) -> None:
            for cid in chat_ids:
                try:
                    bot.send_message(cid, text)
                except Exception:
                    logger.exception("watchlist.telegram_send_failed cid=%s", cid)

        send_fn = _send

    await watchlist_loop(stop_event=stop_event, send_fn=send_fn)


async def _run_play_outcome(stop_event: asyncio.Event) -> None:
    """Forward-test outcome evaluator: каждые 30 мин проходит по play_journal,
    проставляет realized_4h_pct и realized_24h_pct + TP/SL hit flags.
    Без него все derivative watchlist plays слепые."""
    from services.watchlist.loop import play_outcome_loop
    await play_outcome_loop(stop_event=stop_event)


async def _run_short_bots_guard(stop_event: asyncio.Event, *, telegram_app=None) -> None:
    """SHORT bots auto-pause при cascade_short triggers (validated edge 2026:
    70% pct_up 4h после short-cascade → grid SHORT в риске).
    Управляет через GinArea API set_params(p=false/true) для bot_ids из
    state/short_bots_managed.json. Audit в state/short_bots_audit.jsonl."""
    from services.short_bots_guard.loop import short_bots_guard_loop
    from services.telegram.channel_router import build_send_fn
    send_fn = build_send_fn(telegram_app, "MARGIN_ALERT") if telegram_app else None
    await short_bots_guard_loop(stop_event=stop_event, send_fn=send_fn)


async def _run_volume_nodes_refresh(stop_event: asyncio.Event) -> None:
    """Раз в час пересчитывает local volume profile (POC/VAH/VAL/HVN/LVN) из
    24h 1m OHLCV → пишет в state/manual_levels.json. TV-уровни приоритетнее
    (не перезаписываются). Range Hunter snap'ится к VAL/VAH при отсутствии TV."""
    from services.volume_nodes import refresh_local_levels
    interval_sec = 3600
    logger.info("volume_nodes.start interval=%ds", interval_sec)
    while not stop_event.is_set():
        try:
            r = refresh_local_levels()
            if r:
                logger.info("volume_nodes.refreshed POC=%.0f VAH=%.0f VAL=%.0f",
                            r['poc'], r['vah'], r['val'])
        except Exception:
            logger.exception("volume_nodes.tick_failed")
        try:
            await asyncio.wait_for(asyncio.shield(stop_event.wait()), timeout=interval_sec)
        except asyncio.TimeoutError:
            continue


async def _run_daily_report(stop_event: asyncio.Event, *, telegram_app=None) -> None:
    """Daily self-report (21:00 UTC): 24h digest BitMEX + RH + watchlist +
    confluence + vol regime + edge drift. Между weekly чтобы не летаешь
    слепым 7 дней."""
    from services.reports.daily_self_report import maybe_send_daily
    from services.telegram.channel_router import build_send_fn
    send_fn = build_send_fn(telegram_app, "ENGINE_ALERT") if telegram_app else None
    interval_sec = 600  # 10 min poll; actual send 1×/day
    while not stop_event.is_set():
        try:
            if send_fn is not None:
                sent = maybe_send_daily(send_fn=send_fn)
                if sent:
                    logger.info("daily_self_report.sent")
        except Exception:
            logger.exception("daily_self_report.tick_failed")
        try:
            await asyncio.wait_for(asyncio.shield(stop_event.wait()), timeout=interval_sec)
        except asyncio.TimeoutError:
            continue


async def _run_confluence(stop_event: asyncio.Event, *, telegram_app=None) -> None:
    """Confluence detector: раз в минуту смотрит play_journal + cascade_alerts,
    при 2+ сигналов в одну сторону за 5 мин — шлёт high-conviction карточку
    с 2× size recommendation. Dedup 30 мин per direction."""
    from services.watchlist.loop import confluence_loop
    from services.telegram.channel_router import build_send_fn
    send_fn = build_send_fn(telegram_app, "SETUP_ON") if telegram_app else None
    await confluence_loop(stop_event=stop_event, send_fn=send_fn)


async def _run_bitmex_account(stop_event: asyncio.Event) -> None:
    """BitMEX read-only account poll: auto-update margin (TZ-BITMEX-AUTO-MARGIN 2026-05-07).

    Заменяет ручной /margin command. Каждые 60 секунд polling БитМЕКС API
    (margin balance, available, positions, liquidation prices) → запись в
    state/margin_automated.jsonl. read_latest_margin() сам выберет более
    свежий между manual override и auto.

    Если ключ не настроен в .env.local — loop тихо завершается.
    """
    from services.bitmex_account import bitmex_poll_loop

    await bitmex_poll_loop(stop_event=stop_event)


async def _shutdown_task(task: asyncio.Task, *, timeout: float) -> None:
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
    except asyncio.CancelledError:
        return
    except asyncio.TimeoutError:
        logger.warning("app_runner.task_timeout name=%s, cancelling", task.get_name())
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass


async def main(
    *,
    stop_event: asyncio.Event | None = None,
    signal_handler_installer: Callable[[asyncio.AbstractEventLoop, asyncio.Event], None] = _install_signal_handlers,
    shutdown_timeout: float = 10,
) -> int:
    # 2026-05-10 TZ#10: log app_runner startup to audit file for restart-frequency
    # alerts. If >5 restarts/hour observed, watchdog config is too aggressive
    # OR app_runner crashes for legit reason — investigate.
    _log_startup_audit()

    from services.telegram_runtime import TelegramBotApp

    try:
        app = TelegramBotApp()
    except Exception:
        logger.exception("app_runner.telegram_init_failed")
        return 1

    orchestrator = OrchestratorLoop(_build_orchestrator_config())
    loop = asyncio.get_running_loop()
    stop_event = stop_event or asyncio.Event()
    signal_handler_installer(loop, stop_event)

    polling_task = asyncio.create_task(_run_polling_in_executor(app), name="telegram_polling")
    orchestrator_task = asyncio.create_task(orchestrator.start(), name="orchestrator_loop")
    protection_task = asyncio.create_task(_run_protection_alerts(stop_event), name="protection_alerts")
    counter_long_task = asyncio.create_task(_run_counter_long(stop_event), name="counter_long")
    boundary_expand_task = asyncio.create_task(_run_boundary_expand(stop_event), name="boundary_expand")
    adaptive_grid_task = asyncio.create_task(_run_adaptive_grid(stop_event), name="adaptive_grid")
    paper_journal_task = asyncio.create_task(_run_paper_journal(stop_event), name="paper_journal")
    weekly_audit_task = asyncio.create_task(_run_weekly_audit(stop_event), name="weekly_audit")
    decision_log_task = asyncio.create_task(_run_decision_log(stop_event), name="decision_log")
    dashboard_task = asyncio.create_task(_run_dashboard(stop_event), name="dashboard")
    dashboard_http_task = asyncio.create_task(_run_dashboard_http(stop_event), name="dashboard_http")
    setup_detector_task = asyncio.create_task(_run_setup_detector(stop_event, telegram_app=app), name="setup_detector")
    paper_trader_task = asyncio.create_task(_run_paper_trader(stop_event, telegram_app=app), name="paper_trader")
    stale_monitor_task = asyncio.create_task(_run_stale_monitor(stop_event, telegram_app=app), name="stale_monitor")
    decision_layer_emitter_task = asyncio.create_task(_run_decision_layer_emitter(stop_event, telegram_app=app), name="decision_layer_emitter")
    daily_reports_task = asyncio.create_task(_run_daily_weekly_reports(stop_event, telegram_app=app), name="daily_reports")
    setup_tracker_task = asyncio.create_task(_run_setup_tracker(stop_event), name="setup_tracker")
    exit_advisor_task = asyncio.create_task(_run_exit_advisor(stop_event, telegram_app=app), name="exit_advisor")
    market_intelligence_task = asyncio.create_task(_run_market_intelligence(stop_event), name="market_intelligence")
    market_forward_task = asyncio.create_task(_run_market_forward_analysis(stop_event), name="market_forward_analysis")
    deriv_live_task = asyncio.create_task(_run_deriv_live(stop_event), name="deriv_live")
    bitmex_account_task = asyncio.create_task(_run_bitmex_account(stop_event), name="bitmex_account")
    cascade_alert_task = asyncio.create_task(_run_cascade_alert(stop_event, telegram_app=app), name="cascade_alert")
    cascade_accuracy_task = asyncio.create_task(_run_cascade_accuracy_eval(stop_event, telegram_app=app), name="cascade_accuracy_eval")
    cliff_monitor_task = asyncio.create_task(_run_cliff_monitor(stop_event, telegram_app=app), name="cliff_monitor")
    weekly_report_task = asyncio.create_task(_run_weekly_self_report(stop_event, telegram_app=app), name="weekly_self_report")
    range_hunter_signal_task = asyncio.create_task(_run_range_hunter_signal(stop_event, telegram_app=app, symbol="BTCUSDT", variant="1m"), name="range_hunter_signal_btc")
    range_hunter_outcome_task = asyncio.create_task(_run_range_hunter_outcome(stop_event, telegram_app=app, symbol="BTCUSDT", variant="1m"), name="range_hunter_outcome_btc")
    range_hunter_signal_eth_task = asyncio.create_task(_run_range_hunter_signal(stop_event, telegram_app=app, symbol="ETHUSDT", variant="1m"), name="range_hunter_signal_eth")
    range_hunter_outcome_eth_task = asyncio.create_task(_run_range_hunter_outcome(stop_event, telegram_app=app, symbol="ETHUSDT", variant="1m"), name="range_hunter_outcome_eth")
    range_hunter_signal_xrp_task = asyncio.create_task(_run_range_hunter_signal(stop_event, telegram_app=app, symbol="XRPUSDT", variant="1m"), name="range_hunter_signal_xrp")
    range_hunter_outcome_xrp_task = asyncio.create_task(_run_range_hunter_outcome(stop_event, telegram_app=app, symbol="XRPUSDT", variant="1m"), name="range_hunter_outcome_xrp")
    # 5m second-tier: champion из multi-TF walkforward (+$80K за 2y vs $17K на 1m).
    # Параллельно с 1m, не конкурирует. Size $2.5K (DD в 5× больше чем 1m → меньше size).
    range_hunter_signal_5m_task = asyncio.create_task(_run_range_hunter_signal(stop_event, telegram_app=app, symbol="BTCUSDT", variant="5m"), name="range_hunter_signal_btc_5m")
    range_hunter_outcome_5m_task = asyncio.create_task(_run_range_hunter_outcome(stop_event, telegram_app=app, symbol="BTCUSDT", variant="5m"), name="range_hunter_outcome_btc_5m")
    range_hunter_signal_eth_5m_task = asyncio.create_task(_run_range_hunter_signal(stop_event, telegram_app=app, symbol="ETHUSDT", variant="5m"), name="range_hunter_signal_eth_5m")
    range_hunter_outcome_eth_5m_task = asyncio.create_task(_run_range_hunter_outcome(stop_event, telegram_app=app, symbol="ETHUSDT", variant="5m"), name="range_hunter_outcome_eth_5m")
    range_hunter_signal_xrp_5m_task = asyncio.create_task(_run_range_hunter_signal(stop_event, telegram_app=app, symbol="XRPUSDT", variant="5m"), name="range_hunter_signal_xrp_5m")
    range_hunter_outcome_xrp_5m_task = asyncio.create_task(_run_range_hunter_outcome(stop_event, telegram_app=app, symbol="XRPUSDT", variant="5m"), name="range_hunter_outcome_xrp_5m")
    liq_pre_cascade_task = asyncio.create_task(_run_liq_pre_cascade(stop_event, telegram_app=app), name="liq_pre_cascade")
    spike_alert_task = asyncio.create_task(_run_spike_alert(stop_event, telegram_app=app), name="spike_alert")
    # test3_tpflat and test3_tpflat_b retired 2026-05-11 — see TZ-B10
    regime_shadow_task = asyncio.create_task(_run_regime_shadow(stop_event), name="regime_shadow")
    regime_narrator_task = asyncio.create_task(_run_regime_narrator(stop_event, telegram_app=app), name="regime_narrator")
    pre_cascade_task = asyncio.create_task(_run_pre_cascade_alert(stop_event, telegram_app=app), name="pre_cascade_alert")
    grid_coordinator_task = asyncio.create_task(_run_grid_coordinator(stop_event, telegram_app=app), name="grid_coordinator")
    grid_coordinator_intraday_task = asyncio.create_task(_run_grid_coordinator_intraday(stop_event, telegram_app=app), name="grid_coordinator_intraday")
    heartbeat_task = asyncio.create_task(_run_heartbeat(stop_event), name="heartbeat")
    watchlist_task = asyncio.create_task(_run_watchlist(stop_event, telegram_app=app), name="watchlist")
    play_outcome_task = asyncio.create_task(_run_play_outcome(stop_event), name="play_outcome")
    confluence_task = asyncio.create_task(_run_confluence(stop_event, telegram_app=app), name="confluence")
    daily_report_task = asyncio.create_task(_run_daily_report(stop_event, telegram_app=app), name="daily_self_report")
    volume_nodes_task = asyncio.create_task(_run_volume_nodes_refresh(stop_event), name="volume_nodes")
    short_bots_guard_task = asyncio.create_task(_run_short_bots_guard(stop_event, telegram_app=app), name="short_bots_guard")
    stop_task = asyncio.create_task(stop_event.wait(), name="stop_event")

    # Critical tasks: their failure forces full shutdown.
    # Non-critical tasks: log error but keep running (telegram bot must stay live).
    critical_tasks = {polling_task, orchestrator_task, stop_task}
    all_tasks = {
        polling_task, orchestrator_task, protection_task, counter_long_task,
        boundary_expand_task, adaptive_grid_task, paper_journal_task,
        weekly_audit_task,
        decision_log_task, dashboard_task, dashboard_http_task, setup_detector_task,
        setup_tracker_task, exit_advisor_task, market_intelligence_task,
        market_forward_task, deriv_live_task, bitmex_account_task, cascade_alert_task, cascade_accuracy_task, cliff_monitor_task, weekly_report_task,
        range_hunter_signal_task, range_hunter_outcome_task,
        range_hunter_signal_eth_task, range_hunter_outcome_eth_task,
        range_hunter_signal_xrp_task, range_hunter_outcome_xrp_task,
        range_hunter_signal_5m_task, range_hunter_outcome_5m_task,
        range_hunter_signal_eth_5m_task, range_hunter_outcome_eth_5m_task,
        range_hunter_signal_xrp_5m_task, range_hunter_outcome_xrp_5m_task,
        liq_pre_cascade_task, spike_alert_task, regime_shadow_task, regime_narrator_task, pre_cascade_task, grid_coordinator_task, grid_coordinator_intraday_task, heartbeat_task, watchlist_task, play_outcome_task, confluence_task, daily_report_task, volume_nodes_task, short_bots_guard_task, paper_trader_task, stale_monitor_task, stop_task,
    }

    exit_code = 0
    pending = set(all_tasks)
    while True:
        done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
        # Collect crashes; only critical task failure ends the loop.
        critical_completed = False
        for task in done:
            if task is stop_task:
                logger.info("app_runner.shutdown_requested_by_signal")
                critical_completed = True
                continue
            exc = task.exception() if not task.cancelled() else None
            if exc:
                logger.error("app_runner.subtask_crashed name=%s exc=%s", task.get_name(), exc, exc_info=exc)
            else:
                logger.warning("app_runner.subtask_finished_unexpectedly name=%s", task.get_name())
            if task in critical_tasks:
                logger.error("app_runner.critical_task_down name=%s — initiating shutdown", task.get_name())
                exit_code = 1
                critical_completed = True
            # Non-critical: just log and let other tasks continue
        if critical_completed:
            break

    logger.info("app_runner.shutting_down")
    orchestrator.stop()
    try:
        app.bot.stop_polling()
    except Exception:
        logger.exception("app_runner.stop_polling_failed")

    for task in pending:
        if task is stop_task:
            task.cancel()
            continue
        await _shutdown_task(task, timeout=shutdown_timeout)

    logger.info("app_runner.stopped exit_code=%d", exit_code)
    return exit_code


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        logger.info("app_runner.interrupted")
        raise SystemExit(130)
