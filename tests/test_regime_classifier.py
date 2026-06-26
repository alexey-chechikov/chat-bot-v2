from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

from core.orchestrator.regime_classifier import (
    MODIFIER_BLACKOUT,
    MODIFIER_HUGE_DOWN_GAP,
    MODIFIER_POST_FUNDING,
    MODIFIER_TREND_UP_SUSPECTED,
    MODIFIER_WEEKEND_GAP,
    MODIFIER_WEEKEND_LOW_VOL,
    ModifierState,
    RegimeMetrics,
    RegimeState,
    RegimeStateStore,
    apply_hysteresis,
    calc_bias_score,
    classify,
    detect_blackout,
    detect_huge_down_gap,
    detect_post_funding,
)
from tests.fixtures.candle_generators import (
    gen_cascade_down_candles,
    gen_compression_candles,
    gen_range_candles,
    gen_trend_down_candles,
    gen_trend_up_candles,
)


def _store(tmp_path):
    return RegimeStateStore(str(tmp_path / "state" / "regime_state.json"))


def _resample_every(src: list[dict], step: int) -> list[dict]:
    return src[::step]


def _weekend_gap_candles(gap_pct: float) -> list[dict]:
    start = datetime(2026, 4, 17, 0, 0, tzinfo=timezone.utc)
    candles = []
    price = 100.0
    for i in range(100):
        ts = start + timedelta(hours=i)
        close = price * 1.0005
        candles.append(
            {
                "open_time": int(ts.timestamp() * 1000),
                "open": price,
                "high": max(price, close) + 0.2,
                "low": min(price, close) - 0.2,
                "close": close,
                "volume": 100.0,
                "close_time": int((ts + timedelta(hours=1)).timestamp() * 1000),
            }
        )
        price = close
    for candle in candles:
        ts = datetime.fromtimestamp(candle["open_time"] / 1000, tz=timezone.utc)
        if ts.weekday() == 4 and ts.hour == 22:
            candle["close"] = 100.0
        if ts.weekday() == 6 and ts.hour == 23:
            candle["open"] = 100.0
            candle["close"] = round(100.0 * (1.0 + gap_pct / 100.0), 6)
            candle["high"] = max(candle["open"], candle["close"]) + 0.1
            candle["low"] = min(candle["open"], candle["close"]) - 0.1
    return candles


def _classify(store, ts, candles_1h, funding_rate=0.0, blackout=None):
    candles_15m = _resample_every(candles_1h, 1)[-100:]
    candles_4h = _resample_every(candles_1h, 4)[-100:]
    candles_1m = _resample_every(candles_1h, 1)[-120:]
    return classify(
        symbol="BTCUSDT",
        ts=ts,
        candles_1m=candles_1m,
        candles_15m=candles_15m,
        candles_1h=candles_1h,
        candles_4h=candles_4h,
        funding_rate=funding_rate,
        manual_blackout_until=blackout,
        state_store=store,
    )


def _base_metrics(**overrides) -> RegimeMetrics:
    base = RegimeMetrics(
        atr_pct_1h=1.0,
        atr_pct_4h=1.2,
        atr_pct_5m=0.4,
        bb_width_pct_1h=1.8,
        bb_upper_1h=102.0,
        bb_mid_1h=100.0,
        bb_lower_1h=98.0,
        adx_1h=28.0,
        adx_slope_1h=2.0,
        ema20_1h=101.0,
        ema50_1h=100.0,
        ema200_1h=95.0,
        ema_stack_1h=2,
        dist_to_ema200_pct=3.0,
        ema50_slope_1h=0.5,
        range_position=0.8,
        last_move_pct_5m=0.4,
        last_move_pct_15m=0.8,
        last_move_pct_1h=1.3,
        last_move_pct_4h=2.0,
        funding_rate=0.0,
        volume_ratio_24h=1.0,
        weekday=2,
        hour_utc=0,
        minute_in_hour=15,
        close=101.0,
    )
    return replace(base, **overrides)


def test_detect_range(tmp_path):
    store = _store(tmp_path)
    ts = datetime(2026, 4, 14, 12, tzinfo=timezone.utc)
    snapshot = _classify(store, ts, gen_range_candles())
    assert snapshot.primary_regime == "RANGE"


def test_detect_trend_up(tmp_path):
    store = _store(tmp_path)
    ts = datetime(2026, 4, 14, 12, tzinfo=timezone.utc)
    candles = gen_trend_up_candles()
    _classify(store, ts, candles)
    snapshot = _classify(store, ts + timedelta(minutes=15), candles)
    assert snapshot.primary_regime == "TREND_UP"


def test_detect_trend_down(tmp_path):
    store = _store(tmp_path)
    ts = datetime(2026, 4, 14, 12, tzinfo=timezone.utc)
    candles = gen_trend_down_candles()
    _classify(store, ts, candles)
    snapshot = _classify(store, ts + timedelta(minutes=15), candles)
    assert snapshot.primary_regime == "TREND_DOWN"


def test_trend_flip_suppressed_when_lowvol_young(tmp_path):
    # Win 25.06 whipsaw: молодой боковик (30мин) не должен флипать в тренд —
    # min-dwell гасит, BTC-LONG не дёргается.
    store = _store(tmp_path)
    ts = datetime(2026, 4, 14, 12, tzinfo=timezone.utc)
    st = store.get_state("BTCUSDT")
    st.current_primary = "RANGE"
    st.pending_primary = "TREND_DOWN"
    st.hysteresis_counter = 1
    st.primary_since = ts - timedelta(minutes=30)
    store.save_state("BTCUSDT", st)
    snapshot = _classify(store, ts, gen_trend_down_candles())
    assert snapshot.primary_regime == "RANGE"  # подавлено dwell'ом


def test_trend_flip_allowed_when_lowvol_old(tmp_path):
    # устойчивый боковик (100мин) → настоящий тренд коммитится (dwell пройден)
    store = _store(tmp_path)
    ts = datetime(2026, 4, 14, 12, tzinfo=timezone.utc)
    st = store.get_state("BTCUSDT")
    st.current_primary = "RANGE"
    st.pending_primary = "TREND_DOWN"
    st.hysteresis_counter = 1
    st.primary_since = ts - timedelta(minutes=100)
    store.save_state("BTCUSDT", st)
    snapshot = _classify(store, ts, gen_trend_down_candles())
    assert snapshot.primary_regime == "TREND_DOWN"  # dwell пройден


def test_detect_cascade_down_immediate(tmp_path):
    store = _store(tmp_path)
    ts = datetime(2026, 4, 14, 12, tzinfo=timezone.utc)
    candles_1h = gen_range_candles()
    candles_15m = gen_range_candles(100)
    last_15m_prev = candles_15m[-2]["close"]
    candles_15m[-1]["open"] = last_15m_prev
    candles_15m[-1]["close"] = round(last_15m_prev * 0.959, 6)
    candles_15m[-1]["high"] = round(last_15m_prev * 1.001, 6)
    candles_15m[-1]["low"] = round(candles_15m[-1]["close"] * 0.998, 6)
    candles_1m = gen_range_candles(120)
    candles_4h = _resample_every(candles_1h, 4)[-100:]
    snapshot = classify(
        symbol="BTCUSDT",
        ts=ts,
        candles_1m=candles_1m,
        candles_15m=candles_15m,
        candles_1h=candles_1h,
        candles_4h=candles_4h,
        funding_rate=0.0,
        manual_blackout_until=None,
        state_store=store,
    )
    assert snapshot.primary_regime == "CASCADE_DOWN"


def test_detect_compression(tmp_path):
    store = _store(tmp_path)
    ts = datetime(2026, 4, 14, 12, tzinfo=timezone.utc)
    candles = gen_compression_candles()
    store.save_state(
        "BTCUSDT",
        RegimeState(
            atr_history_1h=[0.5, 0.6, 0.7, 0.65, 0.55, 0.45],
            bb_width_history_1h=[0.9] * 50 + [2.0] * 50,
        ),
    )
    _classify(store, ts, candles)
    snapshot = _classify(store, ts + timedelta(minutes=15), candles)
    assert snapshot.primary_regime == "COMPRESSION"


def test_hysteresis_requires_2_bars():
    current, pending, counter = apply_hysteresis("RANGE", "TREND_UP", None, 0, False)
    assert (current, pending, counter) == ("RANGE", "TREND_UP", 1)
    current, pending, counter = apply_hysteresis(current, "TREND_UP", pending, counter, False)
    assert (current, pending, counter) == ("TREND_UP", None, 0)


def test_cascade_bypasses_hysteresis():
    current, pending, counter = apply_hysteresis("RANGE", "CASCADE_DOWN", None, 0, True)
    assert (current, pending, counter) == ("CASCADE_DOWN", None, 0)


def test_weekend_gap_detection(tmp_path):
    store = _store(tmp_path)
    ts = datetime(2026, 4, 19, 23, 15, tzinfo=timezone.utc)
    snapshot = _classify(store, ts, _weekend_gap_candles(2.0))
    assert MODIFIER_WEEKEND_GAP in snapshot.modifiers


def test_huge_down_gap(tmp_path):
    store = _store(tmp_path)
    ts = datetime(2026, 4, 19, 23, 15, tzinfo=timezone.utc)
    snapshot = _classify(store, ts, _weekend_gap_candles(-6.0))
    assert MODIFIER_HUGE_DOWN_GAP in snapshot.modifiers


def test_trend_up_suspected(tmp_path):
    store = _store(tmp_path)
    ts = datetime(2026, 4, 19, 23, 15, tzinfo=timezone.utc)
    candles = _weekend_gap_candles(-2.0)
    store.save_state("BTCUSDT", RegimeState(current_primary="TREND_UP"))
    snapshot = _classify(store, ts, candles)
    assert MODIFIER_TREND_UP_SUSPECTED in snapshot.modifiers


def test_blackout():
    now = datetime(2026, 4, 14, 12, tzinfo=timezone.utc)
    assert detect_blackout(now + timedelta(hours=2), now) is True


def test_post_funding():
    assert detect_post_funding(_base_metrics()) is True


def test_fallback_on_first_run(tmp_path):
    store = _store(tmp_path)
    ts = datetime(2026, 4, 14, 12, tzinfo=timezone.utc)
    short_candles = gen_range_candles(50)
    snapshot = _classify(store, ts, short_candles)
    assert snapshot.primary_regime == "RANGE"
    assert snapshot.metrics.ema200_1h is None


def test_state_persistence(tmp_path):
    store = _store(tmp_path)
    state = RegimeState(current_primary="TREND_DOWN", regime_age_bars=7)
    store.save_state("BTCUSDT", state)
    loaded = store.get_state("BTCUSDT")
    assert loaded.current_primary == "TREND_DOWN"
    assert loaded.regime_age_bars == 7


def test_modifier_ttl_expiry(tmp_path):
    store = _store(tmp_path)
    ts = datetime(2026, 4, 19, 23, 15, tzinfo=timezone.utc)
    candles = _weekend_gap_candles(-6.0)
    _classify(store, ts, candles)
    snapshot = _classify(store, ts + timedelta(hours=49), gen_range_candles())
    assert MODIFIER_HUGE_DOWN_GAP not in snapshot.modifiers


def test_modifier_order(tmp_path):
    store = _store(tmp_path)
    ts = datetime(2026, 4, 19, 23, 15, tzinfo=timezone.utc)
    snapshot = _classify(store, ts, _weekend_gap_candles(-6.0), blackout=ts + timedelta(hours=2))
    assert snapshot.modifiers.index(MODIFIER_BLACKOUT) < snapshot.modifiers.index(MODIFIER_HUGE_DOWN_GAP)
    assert snapshot.modifiers.index(MODIFIER_HUGE_DOWN_GAP) < snapshot.modifiers.index(MODIFIER_WEEKEND_GAP)


def test_snapshot_metrics_complete(tmp_path):
    store = _store(tmp_path)
    ts = datetime(2026, 4, 14, 12, tzinfo=timezone.utc)
    snapshot = _classify(store, ts, gen_trend_up_candles())
    assert snapshot.metrics.close > 0
    assert snapshot.metrics.ema20_1h > 0
    assert snapshot.metrics.bb_mid_1h > 0
    assert snapshot.metrics.volume_ratio_24h > 0


def test_bias_score_range():
    assert -100 <= calc_bias_score(_base_metrics()) <= 100
    assert -100 <= calc_bias_score(_base_metrics(ema_stack_1h=-2, dist_to_ema200_pct=-9.0, last_move_pct_4h=-11.0)) <= 100
