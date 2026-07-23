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
    # fee ордеров GinArea (см. MEASURED_* ниже): у оператора на BitMEX через
    # GinArea (рыночные ордера) — 0.035% с нотионала ЗА СТОРОНУ, т.е. 0.070%
    # за полный цикл. Прежние −0.025% мейкер-ребейта в "ginarea_*" — из
    # общего прайса, к фактическим счетам оператора отношения не имели.
    #
    # OKX (ответ поддержки оператору 2026-07-23): списывается ПОЛНАЯ ставка
    # 0.05% (тейкер), а 20% возвращаются КЕШБЭКОМ на ФАНДИНГОВЫЙ аккаунт
    # раз в час. Это НЕ скидка на ставку: торговый счёт и PnL бота видят
    # полные 0.05%, кешбэк приходит отдельно и в торговле не участвует.
    # Поэтому ставки тут — полные; кешбэк учитывается через
    # OKX_FEE_CASHBACK_PCT только в оценке ИТОГОВОЙ стоимости.
    "okx_linear": {
        "maker_fee_pct": 0.02,
        "taker_fee_pct": 0.05,
    },
    "okx_inverse": {
        "maker_fee_pct": 0.02,
        "taker_fee_pct": 0.05,
    },
}

# ── ИЗМЕРЕННОЕ (не из прайса) ────────────────────────────────────────────────
# Поле fee ордера GinArea = комиссия ОДНОЙ стороны. Доказательство: у
# ОТКРЫТОГО ордера (исполнен только вход) fee уже равна 0.035% нотионала —
# значит выход тарифицируется отдельно, и полный цикл стоит вдвое.
MEASURED_SIDE_FEE_PCT: dict[str, float | None] = {
    "bitmex_ginarea": 0.035,   # 846 ордеров, 2026-05..07, разброс нулевой
    "okx_ginarea": None,       # ЗАМЕРИТЬ, когда закроются первые ордера
}
# комиссия за ПОЛНЫЙ цикл грида (вход + выход) = 2 × сторона, СПИСАННАЯ
MEASURED_CYCLE_FEE_PCT: dict[str, float | None] = {
    "bitmex_ginarea": 0.070,
    "okx_ginarea": None,
}
# Кешбэк OKX: 20% от УПЛАЧЕННЫХ комиссий, ежечасно на ФАНДИНГОВЫЙ аккаунт.
# Ставку не уменьшает: торговый счёт и PnL бота видят полную комиссию,
# возврат приходит отдельным потоком и в торговом балансе не появляется,
# пока оператор не переведёт его руками.
OKX_FEE_CASHBACK_PCT = 20.0


def cycle_fee_pct(venue: str, *, net_of_cashback: bool = False) -> float | None:
    """Комиссия за полный цикл грида, % от нотионала.

    net_of_cashback=False (по умолчанию) — то, что реально спишется со
    ТОРГОВОГО счёта и попадёт в PnL бота.
    net_of_cashback=True — итоговая стоимость с учётом кешбэка (для оценки
    экономики, НЕ для расчёта PnL бота).
    None = на этой площадке ещё не замеряли — НЕ подставлять прайс.
    """
    v = MEASURED_CYCLE_FEE_PCT.get(venue)
    if v is None or not net_of_cashback:
        return v
    if venue.startswith("okx"):
        return v * (1 - OKX_FEE_CASHBACK_PCT / 100.0)
    return v


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
