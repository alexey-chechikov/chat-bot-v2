"""Tests for POS-card thresholds after 2026-05-19 spam-fix.

Operator feedback: POS-card шёл каждый час с 🔴 critical потому что:
  - _is_critical порог DD>=8h всегда true для grid bot в боковике (норма 3+ дней DD)
  - _significant_change порог DD-age >= +1h всегда true (DD = elapsed time)
  - uPnL threshold $50 слишком чувствительный
"""
from __future__ import annotations

from types import SimpleNamespace

from services.exit_advisor.honest_renderer import (
    _is_critical,
    _significant_change,
)


def _state(*, dist_liq: float = 100.0, dd_h: float = 0.0,
            free_margin: float = 100.0, upnl: float = 0.0):
    """Minimal fake PositionStateSnapshot."""
    worst = SimpleNamespace(distance_to_liq_pct=dist_liq, duration_in_dd_h=dd_h)
    return SimpleNamespace(
        worst_bot=worst,
        free_margin_pct=free_margin,
        total_unrealized_usd=upnl,
    )


def test_long_dd_no_longer_critical_alone() -> None:
    """DD=83h при здоровом margin/liq не должен быть critical (was: DD>=8h critical)."""
    s = _state(dist_liq=36.0, dd_h=83.0, free_margin=90.0)
    assert _is_critical(s) is False


def test_low_dist_liq_is_critical() -> None:
    """Real emergency: дистанция до liquidation <=10%."""
    s = _state(dist_liq=8.0, dd_h=10.0, free_margin=90.0)
    assert _is_critical(s) is True


def test_tight_free_margin_is_critical() -> None:
    """Free margin < 70% — tight reserve."""
    s = _state(dist_liq=50.0, dd_h=10.0, free_margin=65.0)
    assert _is_critical(s) is True


def test_dd_age_no_longer_triggers_significant_change() -> None:
    """DD elapsed time не считается significant change (раньше каждый час trip)."""
    s = _state(dist_liq=36.0, dd_h=83.0, upnl=1144.0)
    prev = {"upnl": 1170.0, "dd_h": 81.0, "liq_dist": 35.3}
    # uPnL change |1144-1170|=26 < 200, liq drop 35.3-36.0=−0.7 < 1 → False
    assert _significant_change(s, prev) is False


def test_upnl_threshold_raised_to_200() -> None:
    """uPnL change $50 → не triggered (was raised from $50 to $200)."""
    s = _state(dist_liq=36.0, dd_h=10.0, upnl=1200.0)
    prev = {"upnl": 1150.0, "dd_h": 9.0, "liq_dist": 36.0}
    assert _significant_change(s, prev) is False  # delta $50 < $200


def test_upnl_big_change_triggers() -> None:
    """uPnL change $300 — significant."""
    s = _state(dist_liq=36.0, dd_h=10.0, upnl=850.0)
    prev = {"upnl": 1150.0, "dd_h": 9.0, "liq_dist": 36.0}
    assert _significant_change(s, prev) is True  # delta $300 > $200


def test_liq_dist_drop_triggers() -> None:
    """Distance to liq упала на >=1pp — реальное risk movement."""
    s = _state(dist_liq=15.0, dd_h=10.0, upnl=1000.0)
    prev = {"upnl": 1010.0, "dd_h": 9.0, "liq_dist": 17.0}
    assert _significant_change(s, prev) is True  # 17→15 = 2pp drop


def test_no_prev_snapshot_treated_as_significant() -> None:
    """Первый запуск — нет prev — считаем significant (один раз пройдёт)."""
    s = _state(dist_liq=36.0, dd_h=10.0, upnl=1000.0)
    assert _significant_change(s, {}) is True
