from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from .models import SetupStatus
from .outcomes import OutcomesWriter, check_setup_progress
from .storage import SetupStorage
from .telegram_card import format_followup_card

logger = logging.getLogger(__name__)

_TRACKER_INTERVAL_SEC = 60
_TERMINAL_STATUSES = {
    SetupStatus.TP1_HIT,
    SetupStatus.TP2_HIT,
    SetupStatus.STOP_HIT,
    SetupStatus.EXPIRED,
    SetupStatus.INVALIDATED,
}
_NOTIFY_STATUSES = {SetupStatus.TP1_HIT, SetupStatus.TP2_HIT, SetupStatus.STOP_HIT, SetupStatus.EXPIRED}


async def _get_current_price(pair: str) -> float | None:
    """Fetch live price from core pipeline. Returns None on failure."""
    try:
        from core.pipeline import build_full_snapshot

        loop = asyncio.get_running_loop()
        snapshot = await loop.run_in_executor(None, lambda: build_full_snapshot(symbol=pair))
        price = float(snapshot.get("price", 0.0))
        return price if price > 0.0 else None
    except Exception:
        logger.exception("setup_tracker.get_price_failed pair=%s", pair)
        return None


async def setup_tracker_loop(
    stop_event: asyncio.Event,
    *,
    storage: SetupStorage | None = None,
    outcomes: OutcomesWriter | None = None,
    send_fn: object = None,
    interval_sec: float = _TRACKER_INTERVAL_SEC,
) -> None:
    """60-second loop checking all active setups for status transitions."""
    store = storage or SetupStorage()
    writer = outcomes or OutcomesWriter()

    while not stop_event.is_set():
        try:
            active = store.list_active()
            if not active:
                pass
            else:
                pairs = list({s.pair for s in active})
                prices: dict[str, float] = {}
                for pair in pairs:
                    price = await _get_current_price(pair)
                    if price is not None:
                        prices[pair] = price

                now = datetime.now(timezone.utc)
                for setup in active:
                    price = prices.get(setup.pair)
                    if price is None:
                        continue
                    result = check_setup_progress(setup, price, now=now)
                    if not result.status_changed:
                        continue

                    store.update_status(setup.setup_id, result.new_status)
                    writer.write_outcome_event(setup, result)

                    if result.new_status in _NOTIFY_STATUSES and callable(send_fn):
                        card = format_followup_card(
                            setup,
                            result.new_status.value,
                            result.hypothetical_pnl_usd,
                            result.time_to_outcome_min,
                        )
                        try:
                            # передаём setup — получатель гейтит по реестру пушнутых
                            try:
                                send_fn(card, setup)  # type: ignore[call-arg]
                            except TypeError:
                                send_fn(card)  # type: ignore[operator]
                        except Exception:
                            logger.exception("setup_tracker.send_failed id=%s", setup.setup_id)

        except Exception:
            logger.exception("setup_tracker.loop_failed")

        try:
            await asyncio.wait_for(asyncio.shield(stop_event.wait()), timeout=interval_sec)
        except asyncio.TimeoutError:
            pass
