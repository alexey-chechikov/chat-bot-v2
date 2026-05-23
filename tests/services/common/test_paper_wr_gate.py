"""Tests for the universal paper-WR gate."""
import json
from pathlib import Path

from services.common import paper_wr_gate as g


def _write_jsonl(p: Path, records: list) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")


def _psig(source: str, side: str, pnls: list, exit_base="2026-05-23T") -> list:
    """Generate paper_signals.jsonl-shaped records, chronological."""
    out = []
    for i, p in enumerate(pnls):
        out.append({
            "signal_id": f"sig_{i}",
            "source": source,
            "ts_signal": f"{exit_base}{i:02d}:00:00+00:00",
            "exit_ts":   f"{exit_base}{i:02d}:30:00+00:00",
            "side": side,
            "outcome": "tp_hit" if p > 0 else "sl_hit",
            "pnl_usd": p,
        })
    return out


def test_unhealthy_bucket_blocks(tmp_path):
    """WR < 40% over n>=20 → block."""
    g.STATE_PATH = tmp_path / "wr_gate.json"
    g.PSIG = tmp_path / "psig.jsonl"
    g.PTRD = tmp_path / "ptrd.jsonl"
    g.P15  = tmp_path / "p15.jsonl"
    pnls = [-1.0] * 18 + [+1.0] * 2  # 2/20 = 10% WR
    _write_jsonl(g.PSIG, _psig("badboi", "LONG", pnls))
    state = g._compute_state()
    ok, reason = g.should_emit("badboi", "LONG", state=state)
    assert ok is False
    assert "unhealthy" in reason.lower()


def test_healthy_bucket_allows(tmp_path):
    """WR >= 40% over n>=20 → allow."""
    g.STATE_PATH = tmp_path / "wr_gate.json"
    g.PSIG = tmp_path / "psig.jsonl"
    g.PTRD = tmp_path / "ptrd.jsonl"
    g.P15  = tmp_path / "p15.jsonl"
    pnls = [+1.0] * 15 + [-1.0] * 5   # 15/20 = 75% WR
    _write_jsonl(g.PSIG, _psig("goodboi", "SHORT", pnls))
    state = g._compute_state()
    ok, reason = g.should_emit("goodboi", "SHORT", state=state)
    assert ok is True
    assert "healthy" in reason.lower()


def test_small_sample_allows(tmp_path):
    """n < MIN_N → allow (fail-open until we have data)."""
    g.STATE_PATH = tmp_path / "wr_gate.json"
    g.PSIG = tmp_path / "psig.jsonl"
    g.PTRD = tmp_path / "ptrd.jsonl"
    g.P15  = tmp_path / "p15.jsonl"
    pnls = [-1.0] * 5  # all losses but only n=5
    _write_jsonl(g.PSIG, _psig("newboi", "LONG", pnls))
    state = g._compute_state()
    ok, reason = g.should_emit("newboi", "LONG", state=state)
    assert ok is True
    assert "small sample" in reason.lower()


def test_unknown_bucket_allows(tmp_path):
    """No bucket data → allow (don't block unknown emitters)."""
    g.STATE_PATH = tmp_path / "wr_gate.json"
    g.PSIG = tmp_path / "psig.jsonl"
    g.PTRD = tmp_path / "ptrd.jsonl"
    g.P15  = tmp_path / "p15.jsonl"
    state = g._compute_state()
    ok, reason = g.should_emit("brand_new", "LONG", state=state)
    assert ok is True


def test_rolling_window_uses_only_last_n(tmp_path):
    """Old losses outside ROLLING_N must not poison a recovered bucket."""
    g.STATE_PATH = tmp_path / "wr_gate.json"
    g.PSIG = tmp_path / "psig.jsonl"
    g.PTRD = tmp_path / "ptrd.jsonl"
    g.P15  = tmp_path / "p15.jsonl"
    # 25 ancient losses + 30 recent wins → rolling 30 = all wins → healthy
    pnls = [-1.0] * 25 + [+1.0] * 30
    _write_jsonl(g.PSIG, _psig("recovered", "LONG", pnls))
    state = g._compute_state()
    b = state["buckets"]["recovered::LONG"]
    assert b["n"] == g.ROLLING_N
    assert b["wr_pct"] == 100.0
    ok, _ = g.should_emit("recovered", "LONG", state=state)
    assert ok is True


def test_setup_detector_bucket_keyed_by_setup_type(tmp_path):
    """paper_trades.jsonl closes form their own setup_detector::<type> bucket."""
    g.STATE_PATH = tmp_path / "wr_gate.json"
    g.PSIG = tmp_path / "psig.jsonl"
    g.PTRD = tmp_path / "ptrd.jsonl"
    g.P15  = tmp_path / "p15.jsonl"
    # 20 losses on short_double_top → unhealthy
    ptrd = []
    for i in range(20):
        ptrd.append({
            "ts": f"2026-05-23T{i:02d}:00:00",
            "action": "SL",
            "setup_type": "short_double_top",
            "realized_pnl_usd": -50.0,
        })
    _write_jsonl(g.PTRD, ptrd)
    state = g._compute_state()
    ok, reason = g.should_emit("setup_detector", "short_double_top", state=state)
    assert ok is False


def test_p15_bucket(tmp_path):
    """p15 closes form p15::<side> buckets."""
    g.STATE_PATH = tmp_path / "wr_gate.json"
    g.PSIG = tmp_path / "psig.jsonl"
    g.PTRD = tmp_path / "ptrd.jsonl"
    g.P15  = tmp_path / "p15.jsonl"
    p15 = []
    for i in range(22):
        p15.append({
            "ts": f"2026-05-23T{i:02d}:00:00",
            "action": "CLOSE",
            "side": "long",
            "realized_pnl_usd": -25.0,
        })
    _write_jsonl(g.P15, p15)
    state = g._compute_state()
    ok, reason = g.should_emit("p15", "long", state=state)
    assert ok is False
