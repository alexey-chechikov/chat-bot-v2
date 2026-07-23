from __future__ import annotations

VENUES: dict[str, dict[str, float]] = {
    "bitmex_inverse": {
        "maker_fee_pct": -0.025,
        "taker_fee_pct": 0.075,
    },
    "binance_usdt_m": {
        "maker_fee_pct": 0.02,
        "taker_fee_pct": 0.05,
    },
    "ginarea_inverse": {
        "maker_fee_pct": -0.025,
        "taker_fee_pct": 0.075,
    },
    "ginarea_linear": {
        "maker_fee_pct": 0.02,
        "taker_fee_pct": 0.05,
    },
    # 2026-07-23: БАЗОВЫЕ СТАВКИ ВЫШЕ — СПРАВОЧНЫЕ. Реальность меряем по полю
    # fee закрытых ордеров GinArea (см. measured_* ниже): для гридов оператора
    # на BitMEX через GinArea (рыночные ордера) фактически платилось
    # 0.035% с нотионала за ПОЛНЫЙ цикл (in+out), т.е. 0.0175% от оборота
    # обеих сторон. Сверено на 846 ордерах трёх ботов; tradeVolume бота
    # совпал с двусторонним нотионалом ($235 052 против $235 260).
    # Прежние −0.025% мейкер-ребейта в "ginarea_*" — из общего прайса, к
    # фактическим счетам оператора отношения не имели.
    "okx_linear": {
        "maker_fee_pct": 0.016,
        "taker_fee_pct": 0.04,
    },
    "okx_inverse": {
        "maker_fee_pct": 0.016,
        "taker_fee_pct": 0.04,
    },
}

# ── ИЗМЕРЕННОЕ (не из прайса) ────────────────────────────────────────────────
# ключ: площадка → фактическая комиссия за ПОЛНЫЙ цикл грида, % от нотионала
# позиции (именно это оператор видит в отчётах биржи).
MEASURED_CYCLE_FEE_PCT: dict[str, float | None] = {
    "bitmex_ginarea": 0.035,   # 846 ордеров, 2026-05..07, разброс нулевой
    "okx_ginarea": None,       # ЗАМЕРИТЬ, когда закроются первые ордера
}
# скидка оператора на OKX, % от базовой ставки (2026-07-23)
OKX_FEE_DISCOUNT_PCT = 20.0
OKX_BASE = {"maker_fee_pct": 0.02, "taker_fee_pct": 0.05}


def cycle_fee_pct(venue: str) -> float | None:
    """Фактическая комиссия за полный цикл грида, % от нотионала.
    None = ещё не замеряли на этой площадке — НЕ подставлять прайс."""
    return MEASURED_CYCLE_FEE_PCT.get(venue)


def compute_fee(venue: str, side: str, notional_usd: float, is_maker: bool) -> float:
    """Return fee in USD. Negative = rebate to operator."""
    if venue not in VENUES:
        raise ValueError(f"Unknown venue: {venue}")
    if side not in {"long", "short"}:
        raise ValueError(f"Unknown side: {side}")
    if notional_usd <= 0:
        return 0.0
    fee_pct = VENUES[venue]["maker_fee_pct" if is_maker else "taker_fee_pct"]
    return notional_usd * fee_pct / 100.0
