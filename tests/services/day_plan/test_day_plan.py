"""«ПЛАН ДНЯ»: арсенал под текущий режим + контртренд-флаг + честный грид-день."""
from __future__ import annotations

from services.day_plan import plan
from services.setup_detector import edge_stats


def test_grid_day_when_no_armed(monkeypatch):
    monkeypatch.setattr(plan, "current_regime_label", lambda: "range_tight")
    monkeypatch.setattr(edge_stats, "armed_setups_for_regime", lambda reg: [])
    monkeypatch.setattr(edge_stats, "btc_3state", lambda: "MARKDOWN")
    out = "\n".join(plan.build_day_plan_lines())
    assert "ПЛАН ДНЯ" in out
    assert "грид-день" in out and "входов не жди" in out


def test_arsenal_with_countertrend_flag(monkeypatch):
    monkeypatch.setattr(plan, "current_regime_label", lambda: "range_wide")
    monkeypatch.setattr(edge_stats, "btc_3state", lambda: "MARKDOWN")
    monkeypatch.setattr(edge_stats, "armed_setups_for_regime", lambda reg: [
        ("short_rally_fade", {"regime_pf": 7.3}),
        ("long_pdl_bounce", {"regime_pf": 1.95}),
    ])
    out = "\n".join(plan.build_day_plan_lines())
    assert "BTC 4h MARKDOWN" in out and "интрадей range_wide" in out
    assert "🔴 PF 7.3" in out and "шорт" in out
    # лонг в MARKDOWN = контртренд
    assert "🟢 PF 1.9" in out and "⚠️контртренд" in out
    # шорт в MARKDOWN не контртренд
    rally_line = [l for l in plan.build_day_plan_lines() if "7.3" in l][0]
    assert "контртренд" not in rally_line


def test_current_regime_label_reads_last(monkeypatch, tmp_path):
    p = tmp_path / "setups.jsonl"
    p.write_text(
        '{"setup_type":"x","regime_label":"trend_up"}\n'
        '{"setup_type":"y","regime_label":"range_wide"}\n',
        encoding="utf-8")
    monkeypatch.setattr(plan, "SETUPS", p)
    assert plan.current_regime_label() == "range_wide"


def test_current_regime_label_missing_file(monkeypatch, tmp_path):
    monkeypatch.setattr(plan, "SETUPS", tmp_path / "nope.jsonl")
    assert plan.current_regime_label() is None
