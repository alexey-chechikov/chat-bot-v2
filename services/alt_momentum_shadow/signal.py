"""Чистая логика отбора: ранжирование по excess vs BTC → лонг топ-K / шорт низ-K."""
from __future__ import annotations


def select(excess: dict[str, float], k: int = 4) -> tuple[list[str], list[str]]:
    """excess: {sym: доход_24ч_альта − доход_24ч_BTC, %}. → (лонги топ-K, шорты низ-K).
    Лонг — обогнавшие BTC (моментум продолжается вверх); шорт — отставшие."""
    ranked = sorted(excess.items(), key=lambda x: -x[1])
    if len(ranked) < 2 * k:
        return [], []
    longs = [s for s, _ in ranked[:k]]
    shorts = [s for s, _ in ranked[-k:]]
    return longs, shorts


def portfolio_return(long_excess: list[float], short_excess: list[float],
                     fee_bp_leg: float = 10.0) -> dict:
    """Доход market-neutral портфеля: avg(forward excess лонгов) − avg(шортов),
    минус комиссия (fee_bp_leg на ногу, ×2 вход+выход). Win: +70% при 10bp."""
    if not long_excess or not short_excess:
        return {}
    gross = sum(long_excess) / len(long_excess) - sum(short_excess) / len(short_excess)
    fee = 2 * fee_bp_leg / 100.0   # вход+выход, % (на усреднённую ногу)
    return {"gross_pct": round(gross, 3), "net_pct": round(gross - fee, 3)}
