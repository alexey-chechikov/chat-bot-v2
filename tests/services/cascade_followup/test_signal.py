"""Tests for cascade_followup.signal."""
from __future__ import annotations

from datetime import datetime, timezone

from services.cascade_followup.signal import (
    VARIANTS,
    build_signal,
    format_tg_card,
    signal_id_from_ts,
)


def test_signal_id_format() -> None:
    ts = datetime(2026, 5, 19, 18, 46, 12, tzinfo=timezone.utc)
    sid = signal_id_from_ts(ts, "short_5btc")
    assert sid == "cf_20260519_184612_short_5btc"


def test_build_signal_short_5btc() -> None:
    ts = datetime(2026, 5, 19, 18, 46, 12, tzinfo=timezone.utc)
    sig = build_signal(variant="short_5btc", qty_btc=6.5, last_price=81500.0, now=ts)
    assert sig.variant == "short_5btc"
    assert sig.trade_dir == "LONG"
    v = VARIANTS["short_5btc"]
    assert abs(sig.tp1 - 81500.0 * (1 + v.tp1_pct / 100)) < 0.01
    assert abs(sig.stop - 81500.0 * (1 + v.stop_pct / 100)) < 0.01
    assert sig.size_usd == v.size_usd
    assert sig.size_btc == v.size_usd / 81500.0


def test_short_5btc_is_half_size_pending_live_validation() -> None:
    """Until 20+ собственных fills с WR≥60%, short_5btc держим на $2500.
    Fresh re-sweep 2026-05-19: 4h WR 63.6% (n=164), близко к ниже 70.8%."""
    assert VARIANTS["short_5btc"].size_usd == 2500.0


def test_variants_match_fresh_re_sweep_2026_05_19() -> None:
    """После re-sweep cascade_backtest_combined 2026-05-19, числа в edge_note
    должны соответствовать VARIANTS dataclass'ам (защита от regression)."""
    v5 = VARIANTS["short_5btc"]
    assert 60.0 <= v5.backtest_wr_4h_pct <= 70.0  # 63.6% expected
    assert v5.backtest_n_live >= 100  # n=164
    vm = VARIANTS["mega_short_10btc"]
    assert 55.0 <= vm.backtest_wr_4h_pct <= 70.0  # 61.1% expected
    assert vm.backtest_n_live >= 50  # n=75


def test_format_tg_card_contains_essentials() -> None:
    ts = datetime(2026, 5, 19, 18, 46, 12, tzinfo=timezone.utc)
    sig = build_signal(variant="short_5btc", qty_btc=6.5, last_price=81500.0, now=ts)
    card = format_tg_card(sig)
    assert "CASCADE-FOLLOWUP" in card
    assert "LONG" in card
    assert "70.8%" in card
    assert "Решение" in card


def test_format_tg_card_drift_warning() -> None:
    ts = datetime(2026, 5, 19, 18, 46, 12, tzinfo=timezone.utc)
    sig = build_signal(variant="short_5btc", qty_btc=6.5, last_price=81500.0, now=ts,
                        edge_drift_flag=True)
    card = format_tg_card(sig)
    assert "EDGE-DRIFT" in card


def test_mega_short_10btc_variant_present() -> None:
    v = VARIANTS["mega_short_10btc"]
    assert v.threshold_btc == 10.0
    assert v.liq_side == "short"
    assert v.trade_dir == "LONG"
    assert v.window_minutes == 1
    # EV sanity (fresh sweep 2026-05-19, n=75):
    # 0.611 * 0.50 - 0.389 * 0.45 = 0.306 - 0.175 = +0.131% gross
    # After BitMEX taker RT 0.15% → +/-0% net → maker preferred OR skip taker.
    assert v.tp2_pct > 0
    assert v.stop_pct < 0


def test_build_signal_mega_short() -> None:
    ts = datetime(2026, 5, 19, 18, 46, 12, tzinfo=timezone.utc)
    sig = build_signal(variant="mega_short_10btc", qty_btc=15.7, last_price=81500.0, now=ts)
    assert sig.variant == "mega_short_10btc"
    assert sig.trade_dir == "LONG"
    assert sig.tp1 > sig.entry  # LONG → tp above entry
    assert sig.stop < sig.entry  # LONG → stop below entry
    assert sig.size_usd == VARIANTS["mega_short_10btc"].size_usd
