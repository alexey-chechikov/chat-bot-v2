"""Win-аудит 21.06: level_break убит по своему правилу (WR 17%, −830/нед)."""
from __future__ import annotations

from pathlib import Path

from services.paper_signal_tracker import journal as J


def test_level_break_not_recorded(tmp_path: Path):
    p = tmp_path / "paper_signals.jsonl"
    sid = J.record_paper_signal(source="level_break", side="LONG", entry=64000.0,
                                stop_pct=-0.5, tp_pct=0.75, hold_h=2, path=p)
    assert sid == ""
    assert not p.exists() or p.read_text() == ""   # ничего не записано


def test_live_source_still_recorded(tmp_path: Path):
    p = tmp_path / "paper_signals.jsonl"
    sid = J.record_paper_signal(source="cascade_alert", side="LONG", entry=64000.0,
                                stop_pct=-0.5, tp_pct=0.75, hold_h=2, path=p)
    assert sid.startswith("ca_") or sid != ""
    assert p.exists() and "cascade_alert" in p.read_text()
