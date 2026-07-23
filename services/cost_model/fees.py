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
    # 2026-07-23: BitMEX закрывается, гриды переехали на OKX (exchangeId=3).
    # База VIP0 perp: мейкер 0.02% / тейкер 0.05%; у оператора скидка 20%
    # (OKX_FEE_DISCOUNT_PCT) → 0.016% / 0.04%.
    # ГЛАВНОЕ ОТЛИЧИЕ ОТ BITMEX: там мейкер получал РЕБЕЙТ (−0.025%), здесь
    # мейкер ПЛАТИТ. Для грида, живущего лимитками, это ≈ −0.082% на полный
    # оборот in→out даже со скидкой.
    "okx_linear": {
        "maker_fee_pct": 0.016,
        "taker_fee_pct": 0.04,
    },
    "okx_inverse": {
        "maker_fee_pct": 0.016,
        "taker_fee_pct": 0.04,
    },
}

# скидка оператора на OKX, % от базовой ставки (2026-07-23)
OKX_FEE_DISCOUNT_PCT = 20.0
OKX_BASE = {"maker_fee_pct": 0.02, "taker_fee_pct": 0.05}


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
