"""Теневой учёт исходов + TG-фильтр переходов + живая статистика.

Оператор 2026-07-21: «оставляй лондон», «веди статистику таких закрытий —
накопишь, потом подведём итоги». До этого исход считался только для
user_action=='placed' (кнопки не жмут) → за 2 мес ноль записанных исходов.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

import services.session_breakout.stats as sb_stats
from services.session_breakout.loop import evaluate_outcome

T0 = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)


def _bars(prices):
    """prices: [(minute, high, low, close)] → df 1m."""
    idx = [T0 + timedelta(minutes=m) for m, _, _, _ in prices]
    return pd.DataFrame(
        {"high": [h for _, h, _, _ in prices],
         "low": [l for _, _, l, _ in prices],
         "close": [c for _, _, _, c in prices]}, index=pd.DatetimeIndex(idx))


def _rec(**over):
    r = {"signal_id": "sb_x", "ts_signal": T0.isoformat(), "side": "short",
         "transition": "ny_pm_to_asia", "entry": 65000.0, "stop": 65390.0,
         "tp": 64415.0, "size_usd": 1000.0, "hold_h": 3, "user_action": None,
         "placed_at": None, "exit_reason": None}
    r.update(over)
    return r


def test_outcome_tracked_without_placed_button():
    """Ключевой фикс: исход считается и БЕЗ нажатия «Placed»."""
    df = _bars([(1, 65100, 64300, 64415)])          # шорт дошёл до TP
    upd = evaluate_outcome(_rec(), df, now=T0 + timedelta(hours=1))
    assert upd is not None
    assert upd["exit_reason"] == "tp_hit"
    assert upd["tracked_as"] == "shadow"
    assert upd["pnl_usd"] < upd["gross_usd"]        # комиссии вычтены
    assert upd["fees_usd"] > 0


def test_placed_signal_marked_as_placed():
    df = _bars([(1, 65100, 64300, 64415)])
    upd = evaluate_outcome(_rec(user_action="placed"), df,
                           now=T0 + timedelta(hours=1))
    assert upd["tracked_as"] == "placed"


def test_outcome_none_while_in_progress():
    df = _bars([(1, 65050, 64950, 65000)])          # ни TP, ни SL
    assert evaluate_outcome(_rec(), df, now=T0 + timedelta(minutes=30)) is None


def test_pnl_is_net_of_fees():
    """Стоп на шорте: брутто −$6, комиссии 2×0.075% = $1.5 → нетто −$7.5."""
    df = _bars([(1, 65390, 65000, 65390)])
    upd = evaluate_outcome(_rec(), df, now=T0 + timedelta(hours=1))
    assert upd["exit_reason"] == "sl_hit"
    assert abs(upd["gross_usd"] - (-6.0)) < 0.01
    assert abs(upd["fees_usd"] - 1.5) < 0.01
    assert abs(upd["pnl_usd"] - (-7.5)) < 0.01


def test_tg_filter_keeps_london_only(monkeypatch, tmp_path):
    cfg = tmp_path / "sb.json"
    cfg.write_text(json.dumps({"tg_transitions": ["london_to_ny_am"]}),
                   encoding="utf-8")
    monkeypatch.setattr(sb_stats, "CONFIG_PATH", cfg)
    assert sb_stats.tg_allowed("london_to_ny_am")
    for t in ("ny_pm_to_asia", "asia_to_london", "ny_am_to_ny_lunch",
              "ny_lunch_to_ny_pm"):
        assert not sb_stats.tg_allowed(t)


def test_tg_filter_all_disables_gate(monkeypatch, tmp_path):
    cfg = tmp_path / "sb.json"
    cfg.write_text(json.dumps({"tg_transitions": "all"}), encoding="utf-8")
    monkeypatch.setattr(sb_stats, "CONFIG_PATH", cfg)
    assert sb_stats.tg_allowed("ny_pm_to_asia")


def test_tg_filter_defaults_to_london_without_config(monkeypatch, tmp_path):
    monkeypatch.setattr(sb_stats, "CONFIG_PATH", tmp_path / "нет.json")
    assert sb_stats.tg_allowed("london_to_ny_am")
    assert not sb_stats.tg_allowed("ny_pm_to_asia")


@pytest.fixture
def journal(tmp_path):
    p = tmp_path / "j.jsonl"
    rows = [
        {"signal_id": "a", "transition": "london_to_ny_am",
         "exit_reason": "tp_hit", "pnl_usd": 7.5},
        {"signal_id": "b", "transition": "london_to_ny_am",
         "exit_reason": "sl_hit", "pnl_usd": -7.5},
        {"signal_id": "c", "transition": "london_to_ny_am",
         "exit_reason": "tp_hit", "pnl_usd": 7.5},
        {"signal_id": "d", "transition": "ny_pm_to_asia",
         "exit_reason": "sl_hit", "pnl_usd": -7.5},
        {"signal_id": "e", "transition": "london_to_ny_am",
         "exit_reason": None, "pnl_usd": None},      # ещё в процессе
    ]
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return p


def test_summarize_counts_only_closed(journal):
    s = sb_stats.summarize("london_to_ny_am", path=journal)
    assert s["n"] == 3                    # незакрытый не считается
    assert s["wr_pct"] == 67.0
    assert s["pf"] == 2.0                 # 15 / 7.5
    assert abs(s["total_usd"] - 7.5) < 1e-9


def test_summarize_whole_family(journal):
    s = sb_stats.summarize(path=journal)
    assert s["n"] == 4 and s["total_usd"] == 0.0


def test_live_line_reports_no_data(tmp_path):
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    line = sb_stats.live_line("london_to_ny_am", path=empty)
    assert "данных пока нет" in line
