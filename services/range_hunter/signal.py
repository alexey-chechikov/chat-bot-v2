"""Range Hunter signal detection — pure, тестируемая логика.

Соответствует scripts/range_hunter_backtest.py (мак-колега), но переписана
под live use:
- работает на DataFrame с 1m OHLCV (можно скармливать market_live/market_1m.csv)
- compute_signal(window, params) → bool (тот же контракт)
- build_signal_card(...) — собирает payload для TG/journal
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class RangeHunterParams:
    """Фильтры ренжа + параметры сделки."""
    # Фильтр-индикаторы
    lookback_h: int = 4            # окно для range/ATR/trend
    range_max_pct: float = 0.70    # max-min за lookback < этого %
    atr_pct_max: float = 0.10      # средний 1m TR в % < этого
    trend_max_pct_per_h: float = 0.10  # |slope| < этого %/час
    cooldown_h: int = 2            # после сигнала пауза N часов

    # Параметры размещения (вшиваются в карточку)
    width_pct: float = 0.10        # ±0.10% от mid
    hold_h: int = 6                # окно жизни сделки
    stop_loss_pct: float = 0.20    # SL при single-leg
    size_usd: float = 5_000.0      # размер каждой ноги. Снижен с 10K → 5K
                                   # (Kelly-консервативный, защита от tail risk
                                   # на первые 2 недели live; см. analysis в
                                   # scripts/derivatives_edge_studies.py).
                                   # Если empirical DD < $300 за 14 дней — поднимем.
    contract: str = "XBTUSDT"      # linear

    # Symbol для multi-asset support. Default BTCUSDT.
    # ETH/XRP backtest показал ещё лучше WR (73-77%) при меньшей выборке —
    # три независимых эмиттера дают ~3× signal flow на тех же $15K капитала.
    symbol: str = "BTCUSDT"

    # Timeframe variant: bar_minutes = размер бара. По умолчанию 1m, можно 5m.
    # 5m даёт wider levels + longer hold для более крупного edge per trade.
    # Walk-forward 2y BTC:
    #   bar=1, lookback=4h, hold=6h, width=0.10%:  2066 trades, 68% WR, +$17.9K, DD -$283
    #   bar=5, lookback=12h, hold=24h, width=0.30%: 3097 trades, 70% WR, +$80.7K, DD -$1533
    # variant_name — суффикс для журнала (state/range_hunter_signals_<SYMBOL>_<variant>.jsonl)
    bar_minutes: int = 1
    variant_name: str = "1m"

    # Time-of-day filter (опциональный). По умолчанию пусто = торгуем все часы.
    # После 2 недель live данных оператор включит фильтры на bad windows:
    # paper_trader_long_multi_divergence показал Friday 95% WR vs Mon/Wed/Sat
    # в минусе. Для RH такого распределения пока нет — собираем данные.
    skip_weekdays: tuple[str, ...] = ()         # ("Monday", "Wednesday", "Saturday")
    skip_hours_utc: tuple[int, ...] = ()        # tuple of hour ints to skip

    # Volatility regime filter (опционально). Если True, Range Hunter сигналит
    # ТОЛЬКО при vol_regime == 'low' (рынок спокойный — mean reversion работает).
    # Defaults: 1m baseline = False (let edge naturally self-select),
    #           5m wider = True (защита от каскадных событий в hold-окне 24ч).
    require_low_vol: bool = False


@dataclass
class RangeHunterSignal:
    """Подготовленный сигнал для TG-карточки и журнала."""
    ts: str                        # ISO ts when computed
    mid: float                     # current BTC price
    buy_level: float               # mid * (1 - width_pct/100)
    sell_level: float              # mid * (1 + width_pct/100)
    stop_loss_pct: float           # 0.20%
    hold_h: int                    # 6h
    size_usd: float                # 10000
    contract: str                  # XBTUSDT (BitMEX linear) / ETHUSDT / XRPUSDT

    # Фильтр-показатели в момент сигнала (для журнала)
    range_4h_pct: float
    atr_pct: float
    trend_pct_per_h: float

    # Размеры в native (для удобства копи-паста)
    size_btc: float                # size_usd / mid

    # Underlying symbol для label resolution в format_tg_card
    symbol: str = "BTCUSDT"

    def to_dict(self) -> dict:
        return asdict(self)


DEFAULT_PARAMS = RangeHunterParams()


def _trend_pct_per_h(window: pd.DataFrame) -> float:
    """Linear-regression slope, нормализован к %/час.

    Возвращает signed slope (положительный = вверх).
    """
    if len(window) < 2:
        return 0.0
    closes = window["close"].values.astype(float)
    x = np.arange(len(closes), dtype=float)
    slope = np.polyfit(x, closes, 1)[0]  # USD per minute
    mid = float(closes[-1])
    return float(slope * 60.0 / mid * 100.0)  # convert to %/hr


def _range_pct(window: pd.DataFrame) -> float:
    """(high.max - low.min) / mid * 100"""
    hi = float(window["high"].max())
    lo = float(window["low"].min())
    mid = float(window["close"].iloc[-1])
    if mid <= 0:
        return float("inf")
    return (hi - lo) / mid * 100.0


def _atr_pct(window: pd.DataFrame) -> float:
    """Mean (high - low) / mid * 100. Дешёвая прокси ATR на 1m."""
    mid = float(window["close"].iloc[-1])
    if mid <= 0:
        return float("inf")
    tr = (window["high"] - window["low"]).values.astype(float)
    return float(np.mean(tr) / mid * 100.0)


def compute_signal(window: pd.DataFrame, params: RangeHunterParams = DEFAULT_PARAMS
                   ) -> Optional[RangeHunterSignal]:
    """Проверяет фильтры на хвосте окна. Возвращает Signal или None.

    window: DataFrame с колонками [high, low, close], индекс monotonically.
    Минимальная длина — lookback_h * 60 баров (4h × 60 = 240).
    """
    needed = params.lookback_h * 60
    if len(window) < needed:
        return None
    tail = window.iloc[-needed:]

    # Time-of-day filter — отсекаем сигналы в bad weekdays/hours если задано
    last_ts_pd = pd.Timestamp(tail.index[-1])
    if last_ts_pd.tz is None:
        last_ts_pd = last_ts_pd.tz_localize("UTC")
    weekday_name = last_ts_pd.strftime("%A")
    hour_utc = last_ts_pd.hour
    if params.skip_weekdays and weekday_name in params.skip_weekdays:
        return None
    if params.skip_hours_utc and hour_utc in params.skip_hours_utc:
        return None

    # Volatility regime filter (optional)
    if params.require_low_vol:
        try:
            from services.volatility_regime import current_regime
            regime, _ = current_regime(getattr(params, "symbol", "BTCUSDT"))
            if regime != "low":
                return None
        except Exception:
            pass  # graceful fallback if module missing

    range_pct = _range_pct(tail)
    if range_pct > params.range_max_pct:
        return None

    atr_pct = _atr_pct(tail)
    if atr_pct > params.atr_pct_max:
        return None

    trend = _trend_pct_per_h(tail)
    if abs(trend) > params.trend_max_pct_per_h:
        return None

    mid = float(tail["close"].iloc[-1])
    if mid <= 0:
        return None

    # Default: симметричные уровни ±width% от mid
    buy_level = mid * (1.0 - params.width_pct / 100.0)
    sell_level = mid * (1.0 + params.width_pct / 100.0)
    levels_source = "mid_symmetric"

    # VPVR override: если TV/local volume profile дал свежие VAL/VAH
    # И они находятся в "разумной близости" от mid (max 2× ширины grid от mid)
    # — используем их вместо симметричных, fill rate должен подняться.
    # Per-symbol lookup: BTCUSDT→BTCUSD storage key, ETH/XRP — as-is.
    proximity_score = 0.0  # 0.0 = mid_symmetric, 1.0 = exact snap to VAL & VAH
    try:
        from services.manual_levels import get_levels
        from services.volume_nodes import SYMBOL_STORAGE_MAP
        storage_sym = SYMBOL_STORAGE_MAP.get(params.symbol.upper(), params.symbol.upper())
        lv = get_levels(storage_sym)
        if lv:
            max_offset = mid * params.width_pct * 2 / 100.0  # 2× width до VAL/VAH
            val = lv.get("val")
            vah = lv.get("vah")
            new_buy = buy_level
            new_sell = sell_level
            snaps = 0
            if val and abs(mid - val) <= max_offset and val < mid:
                new_buy = float(val)
                snaps += 1
            if vah and abs(vah - mid) <= max_offset and vah > mid:
                new_sell = float(vah)
                snaps += 1
            if new_buy != buy_level or new_sell != sell_level:
                buy_level = new_buy
                sell_level = new_sell
                levels_source = "vpvr_snap"
                proximity_score = snaps / 2.0  # 0.5 = one-sided, 1.0 = both VAL+VAH
    except Exception:
        pass  # graceful fallback

    size_btc = params.size_usd / mid

    last_ts = tail.index[-1]
    if isinstance(last_ts, (pd.Timestamp, datetime)):
        ts_iso = pd.Timestamp(last_ts).tz_localize("UTC").isoformat() \
            if pd.Timestamp(last_ts).tz is None else pd.Timestamp(last_ts).isoformat()
    else:
        ts_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # Resolve BitMEX contract name per underlying symbol
    bitmex_contract = {
        "BTCUSDT": "XBTUSDT",
        "ETHUSDT": "ETHUSDT",
        "XRPUSDT": "XRPUSDT",
    }.get(params.symbol.upper(), params.contract)

    sig = RangeHunterSignal(
        ts=ts_iso,
        mid=round(mid, 2),
        buy_level=round(buy_level, 2),
        sell_level=round(sell_level, 2),
        stop_loss_pct=params.stop_loss_pct,
        hold_h=params.hold_h,
        size_usd=params.size_usd,
        contract=bitmex_contract,
        symbol=params.symbol.upper(),
        range_4h_pct=round(range_pct, 4),
        atr_pct=round(atr_pct, 4),
        trend_pct_per_h=round(trend, 4),
        size_btc=round(size_btc, 6),
    )
    # Прикрепляем источник уровней (динамическое поле, не ломает dataclass)
    object.__setattr__(sig, "levels_source", levels_source)
    object.__setattr__(sig, "proximity_score", proximity_score)
    return sig


def format_tg_card(sig: RangeHunterSignal, *, expected_pair_win: float = 0.685,
                   avg_win: float = 24.0, avg_loss: float = -25.5,
                   expiry_ts: Optional[datetime] = None) -> str:
    """Строит готовый текст TG-сообщения для копи-паста в BitMEX.

    expected_pair_win/avg_win/avg_loss — из walk-forward (68.5% WR).
    """
    if expiry_ts is None:
        expiry_ts = datetime.now(timezone.utc) + pd.Timedelta(hours=sig.hold_h)
    expiry_str = expiry_ts.strftime("%H:%M UTC")

    sl_usd = sig.size_usd * sig.stop_loss_pct / 100.0
    ev = expected_pair_win * avg_win + (1 - expected_pair_win) * avg_loss

    # Symbol display: BTCUSDT → "BTC", ETHUSDT → "ETH", XRPUSDT → "XRP"
    symbol_short = getattr(sig, "symbol", "BTCUSDT").upper().replace("USDT", "")
    if not symbol_short or symbol_short == sig.symbol.upper():
        symbol_short = "BTC"  # fallback

    lines = [
        f"🎯 RANGE HUNTER signal [{getattr(sig, 'symbol', 'BTCUSDT')}]",
        f"{symbol_short} mid: ${sig.mid:,.2f}",
        "Условия выполнены:",
        f"  range_4h: {sig.range_4h_pct:.2f}% (порог ≤{0.70:.2f}%)",
        f"  ATR_1m:   {sig.atr_pct:.2f}% (порог ≤{0.10:.2f}%)",
        f"  trend:    {sig.trend_pct_per_h:+.2f}%/ч (порог ≤{0.10:.2f}%)",
        "",
        f"📋 Ставь 2 лимитки (post-only) на {sig.contract}:",
        f"  BUY:  ${sig.buy_level:,.2f}   (-{0.10:.2f}%)",
        f"  SELL: ${sig.sell_level:,.2f}   (+{0.10:.2f}%)",
        f"  Размер: ${sig.size_usd:,.0f} (≈{sig.size_btc:.4f} {symbol_short}) каждая",
        "",
        f"⏱️ Окно жизни: до {expiry_str} (+{sig.hold_h}h)",
        f"🛑 Stop: при единичном fill — закрыть при ходе {sig.stop_loss_pct:.2f}% против (≈${sl_usd:.0f})",
        "",
        f"Ожидание:",
        f"  {expected_pair_win*100:.0f}% оба fill = +${avg_win:.1f}",
        f"  {(1-expected_pair_win)*100:.0f}% single → SL = ${avg_loss:.1f}",
        f"EV: ${ev:+.2f} на сигнал",
    ]
    return "\n".join(lines)
