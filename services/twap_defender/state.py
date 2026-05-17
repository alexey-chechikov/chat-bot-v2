"""Pure detector — определяет, нужен ли TWAP alert для бота.

Не делает I/O, не шлёт TG. Принимает текущий снап + историю 30 мин назад.
Возвращает dict с предложением, или None.
"""
from __future__ import annotations

from typing import Optional

# Порог |pos_usd|, после которого считаем что бот "bleed"
BLEED_THRESHOLD_USD = 50_000.0

# Шаг TWAP — фиксированный $1k за emit
STEP_QTY_USD = 1_000.0

# Минимальный 30-мин рост позиции, чтобы считать "growing"
MIN_GROWTH_30MIN_USD = 1_000.0


def _position_to_usd(position: float, side: str, btc_mid: float) -> float:
    """Convert raw GinArea position to absolute USD notional.

    SHORT bots — inverse XBTUSD: position is in BTC → usd = |pos| × mid.
    LONG bots — linear XBTUSDT: position is already in USDT → usd = |pos|.
    """
    if side == "short":
        return abs(position) * btc_mid
    return abs(position)


def detect_bleed(bot_state: dict, position_30min_ago_btc: Optional[float],
                 btc_mid: Optional[float]) -> Optional[dict]:
    """Bot in bleed state? Return alert payload, otherwise None.

    bot_state: dict from bot_brain._read_bots() — must have keys:
        bot_id, alias, tier, side, position_btc

    position_30min_ago_btc: raw position 30 min ago (BTC for short, USDT for long).
        None if no history.
    btc_mid: current BTC mid in USD

    Returns dict with proposed action OR None if condition not met.
    """
    pos = bot_state.get("position_btc")
    side = bot_state.get("side", "short")
    if pos is None or btc_mid is None or btc_mid <= 0:
        return None

    pos_usd_abs = _position_to_usd(pos, side, btc_mid)
    if pos_usd_abs < BLEED_THRESHOLD_USD:
        return None

    if position_30min_ago_btc is None:
        # No history → can't confirm "growing". Skip.
        return None
    pos_30_usd_abs = _position_to_usd(position_30min_ago_btc, side, btc_mid)
    delta_usd = pos_usd_abs - pos_30_usd_abs
    if delta_usd < MIN_GROWTH_30MIN_USD:
        return None  # not growing

    # Direction of compensating trade: opposite of bot's position sign
    side = bot_state.get("side", "short")
    suggested_side = "buy" if side == "short" else "sell"

    return {
        "bot_id": bot_state.get("bot_id"),
        "alias": bot_state.get("alias"),
        "tier": bot_state.get("tier"),
        "side": side,
        "position_btc": round(pos, 4),
        "position_usd_abs": round(pos_usd_abs, 0),
        "delta_30min_usd": round(delta_usd, 0),
        "btc_mid": round(btc_mid, 2),
        "suggested_qty_usd": STEP_QTY_USD,
        "suggested_side": suggested_side,
    }


def format_tg_card(alert: dict, *, step: int, max_steps: int) -> str:
    """Build TG message text for alert."""
    side_emoji = "🟥" if alert["side"] == "short" else "🟩"
    contract = "XBTUSD"  # inverse SHORT bots; для linear LONG будет XBTUSDT
    if alert["side"] == "long":
        contract = "XBTUSDT"

    action_word = "BUY" if alert["suggested_side"] == "buy" else "SELL"
    qty_btc = alert["suggested_qty_usd"] / alert["btc_mid"]

    lines = [
        f"🛡 TWAP DEFENDER {side_emoji} [{alert['tier']}] step {step}/{max_steps}",
        f"  bot: {alert['alias']} (id {alert['bot_id']})",
        f"  pos: {alert['position_btc']:+.4f} BTC ≈ ${alert['position_usd_abs']:,.0f}",
        f"  Δ 30мин: +${alert['delta_30min_usd']:,.0f} (растёт против рынка)",
        f"  BTC mid: ${alert['btc_mid']:,.2f}",
        "",
        f"📋 Suggested: market {action_word} ${alert['suggested_qty_usd']:,.0f} {contract}",
        f"  ≈ {qty_btc:.5f} BTC, taker fee ≈ ${alert['suggested_qty_usd'] * 0.00075:.2f}",
        "",
        f"💡 Цель: разгрузить позицию через TWAP (max {max_steps} шагов по 5 мин).",
        f"   Защита от bleed на одностороннем движении.",
    ]
    return "\n".join(lines)
