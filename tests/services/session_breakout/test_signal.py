"""Tests for session_breakout.signal — session boundary + breakout logic."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from services.session_breakout.signal import (
    DEFAULT_PARAMS,
    PRIOR_OF,
    SessionBreakoutParams,
    compute_signal,
    format_tg_card,
    prior_session_ohlc,
    prior_session_window,
    session_at,
    session_start_for,
)


def _ts(hour, minute=0, day=18):
    return datetime(2026, 5, day, hour, minute, tzinfo=timezone.utc)


# ─── session_at ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("h,m,expected_sess,expected_tis", [
    (0, 0, "asia", 0),
    (4, 30, "asia", 4 * 60 + 30),
    (7, 59, "asia", 7 * 60 + 59),
    (8, 0, "london", 0),
    (12, 59, "london", 4 * 60 + 59),
    (13, 0, "ny_am", 0),
    (16, 30, "ny_am", 3 * 60 + 30),
    (17, 0, "ny_lunch", 0),
    (18, 59, "ny_lunch", 1 * 60 + 59),
    (19, 0, "ny_pm", 0),
    (22, 30, "ny_pm", 3 * 60 + 30),
    (23, 59, "ny_pm", 4 * 60 + 59),
])
def test_session_at(h, m, expected_sess, expected_tis):
    sess, tis = session_at(_ts(h, m))
    assert sess == expected_sess
    assert tis == expected_tis


# ─── prior_session_window ───────────────────────────────────────────────────

def test_prior_of_asia_is_yesterday_ny_pm():
    ts = _ts(2, 30)  # asia of day 18
    start, end = prior_session_window(ts, "asia")
    # Should be day 17 19:00 to day 18 00:00
    assert start == _ts(19, 0, day=17)
    assert end == _ts(0, 0, day=18)


def test_prior_of_london_is_today_asia():
    ts = _ts(9, 30)
    start, end = prior_session_window(ts, "london")
    assert start == _ts(0, 0)
    assert end == _ts(8, 0)


def test_prior_of_ny_am_is_today_london():
    ts = _ts(14, 0)
    start, end = prior_session_window(ts, "ny_am")
    assert start == _ts(8, 0)
    assert end == _ts(13, 0)


def test_prior_of_ny_pm_is_today_ny_lunch():
    ts = _ts(20, 0)
    start, end = prior_session_window(ts, "ny_pm")
    assert start == _ts(17, 0)
    assert end == _ts(19, 0)


# ─── prior_session_ohlc ─────────────────────────────────────────────────────

def _df_from_prices(prices_by_hour: dict[int, tuple[float, float, float]],
                     day=18):
    """Build df with hour-based fake 1m bars. Each hour gets one bar at h:00."""
    rows = []
    for h, (hi, lo, cl) in prices_by_hour.items():
        rows.append({"ts": _ts(h, 0, day=day), "high": hi, "low": lo, "close": cl})
    df = pd.DataFrame(rows).set_index("ts")
    return df


def test_prior_session_ohlc_london_uses_asia_high_low():
    # Asia 0-8h: highs 80100, 80200, 80300, 80250, 80400, 80350, 80100, 80050.
    # Min low = 79800 (h=5), max high = 80400 (h=4).
    df = _df_from_prices({
        0: (80100, 80000, 80050),
        1: (80200, 80100, 80150),
        2: (80300, 80150, 80250),
        3: (80250, 80100, 80200),
        4: (80400, 80200, 80300),
        5: (80350, 79800, 79900),
        6: (80100, 79850, 80000),
        7: (80050, 79900, 80000),
    })
    ohlc = prior_session_ohlc(df, _ts(9, 0), "london")
    assert ohlc is not None
    high, low = ohlc
    assert high == 80400
    assert low == 79800


def test_prior_session_ohlc_returns_none_on_empty_window():
    df = pd.DataFrame({"high": [], "low": [], "close": []},
                       index=pd.DatetimeIndex([], tz="UTC"))
    assert prior_session_ohlc(df, _ts(9, 0), "london") is None


# ─── compute_signal ─────────────────────────────────────────────────────────

def test_compute_signal_long_when_break_above_prior_high():
    # Asia high = 80400, low = 79800.
    # London opens at 8h, by 8:10 price = 80500 → breaks asia high → LONG
    df = _df_from_prices({
        0: (80100, 80000, 80050),
        4: (80400, 80200, 80300),  # asia high
        5: (80350, 79800, 79900),  # asia low
        7: (80050, 79900, 80000),
        8: (80500, 80050, 80450),  # london open, breaks asia high 80400
    })
    sig = compute_signal(df, now=_ts(8, 10))
    assert sig is not None
    assert sig.side == "long"
    assert sig.transition == "asia_to_london"
    assert sig.prior_high == 80400
    assert sig.prior_low == 79800
    assert sig.entry == 80450  # close of last bar (h=8)
    # SL = entry * (1 - 0.006) = 80450 * 0.994
    assert abs(sig.stop - 80450 * 0.994) < 0.5


def test_compute_signal_short_when_break_below_prior_low():
    df = _df_from_prices({
        4: (80400, 80200, 80300),
        5: (80350, 79800, 79900),  # asia low 79800
        7: (80050, 79900, 80000),
        8: (80100, 79700, 79750),  # london breaks below 79800
    })
    sig = compute_signal(df, now=_ts(8, 10))
    assert sig is not None
    assert sig.side == "short"


def test_compute_signal_none_outside_entry_window():
    df = _df_from_prices({
        4: (80400, 80200, 80300),
        5: (80350, 79800, 79900),
        8: (80500, 80050, 80450),
    })
    # 8:30 = 30 minutes into london, ENTRY_WINDOW_MIN = 15 → too late
    sig = compute_signal(df, now=_ts(8, 30))
    assert sig is None


def test_compute_signal_none_when_no_breakout():
    # London hovering inside asia range [79800, 80400] → no break
    df = _df_from_prices({
        4: (80400, 80200, 80300),
        5: (80350, 79800, 79900),
        7: (80050, 79900, 80000),
        8: (80200, 80000, 80100),  # inside range
    })
    sig = compute_signal(df, now=_ts(8, 10))
    assert sig is None


def test_compute_signal_default_params_match_backtest():
    p = DEFAULT_PARAMS
    assert p.entry_window_min == 15
    assert p.buffer_pct == 0.0
    assert p.hold_h == 3
    assert p.stop_loss_pct == 0.6
    assert p.tp_ratio == 1.5


# ─── prior mapping completeness ─────────────────────────────────────────────

def test_prior_map_covers_all_sessions():
    assert set(PRIOR_OF.keys()) == {"asia", "london", "ny_am", "ny_lunch", "ny_pm"}
    assert PRIOR_OF["asia"] == "ny_pm"
    assert PRIOR_OF["london"] == "asia"


def test_format_tg_card_contains_key_fields(monkeypatch):
    df = _df_from_prices({
        4: (80400, 80200, 80300),
        5: (80350, 79800, 79900),
        7: (80050, 79900, 80000),
        8: (80500, 80050, 80450),
    })
    sig = compute_signal(df, now=_ts(8, 10))
    # 2026-07-21: карточка печатает ЖИВОЙ эдж из своего журнала вместо мёртвой
    # строки «Backtest PF 1.85» — изолируем от боевого журнала
    import services.session_breakout.stats as sb_stats
    monkeypatch.setattr(sb_stats, "live_line",
                        lambda t, **kw: f"📊 Живой эдж [{t}]: WR 69%, PF 1.86 (n=13)")
    text = format_tg_card(sig)
    assert "SESSION BREAKOUT" in text
    assert "asia_to_london" in text
    assert "BUY" in text  # long
    assert "$80,450" in text or "$80,400" in text
    assert "Живой эдж" in text and "n=13" in text
    assert "Backtest" not in text      # мёртвая строка удалена
