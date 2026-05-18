"""Market intelligence async loop — runs every 120s.

Integration point for app_runner.py:
    from services.market_intelligence.loop import market_intelligence_loop
    asyncio.create_task(market_intelligence_loop(stop_event, send_fn=send_fn))
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from .mtf_data import MTFDataCache
from .order_blocks import detect_order_blocks
from .msb_detector import detect_msb
from .premium_discount import compute_premium_discount, detect_fvg
from .ict_killzones import get_killzone_state, current_session_from_utc, Session
from .mtf_confluence import compute_confluence
from .telegram_renderer import format_confluence_alert, format_session_brief, format_key_event_alert
from .event_detectors import (
    detect_funding_extreme, FundingBias,
    detect_oi_extreme, OIBias,
    detect_taker_imbalance, TakerBias,
    detect_rsi_divergence, DivType,
    detect_pin_bar, PinBarType,
)

logger = logging.getLogger(__name__)

_LOOP_INTERVAL_SEC = 120
_CONFLUENCE_DEDUP_SEC = 1800    # 30 min dedup for confluence alerts
_EVENT_DEDUP_SEC = 900          # 15 min dedup for key event alerts


async def market_intelligence_loop(
    stop_event: asyncio.Event,
    *,
    send_fn: Any = None,
    interval_sec: float = _LOOP_INTERVAL_SEC,
) -> None:
    """Main market intelligence async loop."""
    cache = MTFDataCache()
    last_confluence_sent: Optional[datetime] = None
    last_event_sent: dict[str, datetime] = {}
    last_session: Optional[Session] = None

    logger.info("market_intelligence_loop.started interval=%ds", interval_sec)

    while not stop_event.is_set():
        try:
            _tick(
                cache=cache,
                send_fn=send_fn,
                last_confluence_sent_holder=[last_confluence_sent],
                last_event_sent=last_event_sent,
                last_session_holder=[last_session],
            )
            last_confluence_sent = _tick.last_confluence_sent if hasattr(_tick, "last_confluence_sent") else last_confluence_sent
            last_session = _tick.last_session if hasattr(_tick, "last_session") else last_session
        except Exception:
            logger.exception("market_intelligence_loop.tick_failed")

        try:
            await asyncio.wait_for(asyncio.shield(stop_event.wait()), timeout=interval_sec)
        except asyncio.TimeoutError:
            pass


def _tick(
    *,
    cache: MTFDataCache,
    send_fn: Any,
    last_confluence_sent_holder: list,
    last_event_sent: dict,
    last_session_holder: list,
) -> None:
    """Single synchronous tick of the market intelligence loop."""
    now = datetime.now(timezone.utc)
    current_price = cache.current_price()

    # Refresh MTF data
    cache.refresh()

    df_15m = cache.get("15m")
    df_1h = cache.get("1h")
    df_4h = cache.get("4h")

    if df_1h is None or df_1h.empty:
        logger.debug("market_intelligence_loop: no 1h data available")
        return

    # Killzone session detection
    kz = get_killzone_state(df_1h, current_price=current_price)
    current_sess = current_session_from_utc(now)

    # Session open alert
    if last_session_holder[0] != current_sess and current_sess != Session.NONE:
        pd_level = compute_premium_discount(df_4h if df_4h is not None else df_1h, current_price)
        msg = format_session_brief(kz, pd_level, current_price)
        _send(msg, send_fn, logger)
    last_session_holder[0] = current_sess
    _tick.last_session = current_sess  # type: ignore[attr-defined]

    # Pattern detection
    obs_1h = detect_order_blocks(df_1h)
    fvgs_1h = detect_fvg(df_1h)
    msb_1h = detect_msb(df_1h)

    pd_level = compute_premium_discount(
        df_4h if df_4h is not None else df_1h,
        current_price,
    )

    # Event detectors
    funding_sig = detect_funding_extreme(df_1h)
    oi_sig = detect_oi_extreme(df_1h)
    taker_sig = detect_taker_imbalance(df_1h)
    rsi_sig = detect_rsi_divergence(df_15m if df_15m is not None else df_1h)
    pin_sig = detect_pin_bar(df_15m if df_15m is not None else df_1h)

    # Key event alerts (deduped per event type)
    for etype, condition, note in [
        ("funding", funding_sig.bias != FundingBias.NEUTRAL, funding_sig.note),
        ("oi", oi_sig.bias != OIBias.NEUTRAL, oi_sig.note),
        ("taker", taker_sig.bias != TakerBias.NEUTRAL, taker_sig.note),
        ("rsi_div", rsi_sig.div_type != DivType.NONE, rsi_sig.note),
        ("pin_bar", pin_sig.pin_type != PinBarType.NONE, pin_sig.note),
    ]:
        if condition:
            last_e = last_event_sent.get(etype)
            if last_e is None or (now - last_e).total_seconds() > _EVENT_DEDUP_SEC:
                msg = format_key_event_alert(etype, note, current_price)
                if _send(msg, send_fn, logger):
                    last_event_sent[etype] = now

    # MTF confluence
    confluence = compute_confluence(
        killzone=kz,
        pd_level=pd_level,
        obs=obs_1h,
        fvgs=fvgs_1h,
        msb_events=msb_1h,
        funding=funding_sig,
        oi=oi_sig,
        taker=taker_sig,
        rsi_div=rsi_sig,
        pin_bar=pin_sig,
    )

    if confluence.alert_worthy:
        last_c = last_confluence_sent_holder[0]
        if last_c is None or (now - last_c).total_seconds() > _CONFLUENCE_DEDUP_SEC:
            msg = format_confluence_alert(confluence, current_price, pd_level, obs_1h, fvgs_1h)
            if msg and _send(msg, send_fn, logger):
                last_confluence_sent_holder[0] = now
                _tick.last_confluence_sent = now  # type: ignore[attr-defined]
            # Paper-trade в направлении confluence bias — независимо от TG send.
            try:
                from services.paper_signal_tracker.journal import record_paper_signal
                bias_str = str(confluence.bias.value)
                if "bull" in bias_str:
                    trade_side = "LONG"
                elif "bear" in bias_str:
                    trade_side = "SHORT"
                else:
                    trade_side = None
                if trade_side and current_price and current_price > 0:
                    record_paper_signal(
                        source="market_intel", side=trade_side,
                        entry=float(current_price),
                        stop_pct=-0.5, tp_pct=0.75, hold_h=4,
                        context=f"confluence_{bias_str}_score{confluence.score:.0f}",
                        now=now,
                    )
            except Exception:
                logger.exception("market_intelligence.paper_signal_failed")


def _send(msg: str, send_fn: Any, log) -> bool:
    """Send message via send_fn. Returns True on success."""
    if not msg or send_fn is None:
        return False
    try:
        if callable(send_fn):
            send_fn(msg)
        return True
    except Exception:
        log.exception("market_intelligence.send_failed")
        return False
