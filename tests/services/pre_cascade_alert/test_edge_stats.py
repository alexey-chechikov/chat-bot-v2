"""edge_stats: живая 60д статистика из журналов fires + 1m свечей.

Синтетика: цена 100 → 95 → 98 ступенями по суткам; фиксированные fires
с известными исходами. Проверяем подсчёт, дедуп двойных fires,
исключение недозревших горизонтов и гейт 60%/n>=30.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from services.pre_cascade_alert import edge_stats as es

NOW = datetime(2026, 7, 18, 0, 0, tzinfo=timezone.utc)


def _price_at(dt: datetime) -> float:
    if dt < NOW - timedelta(days=2):
        return 100.0
    if dt < NOW - timedelta(days=1):
        return 95.0
    return 98.0


def _write_candles(path: Path) -> None:
    lines = ["ts,open,high,low,close,volume"]
    t = NOW - timedelta(days=4)
    while t <= NOW:
        px = _price_at(t)
        lines.append(f"{int(t.timestamp() * 1000)},{px},{px},{px},{px},1")
        t += timedelta(minutes=1)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def test_compute_stats_counts_and_dedup(tmp_path: Path) -> None:
    candles = tmp_path / "candles.csv"
    _write_candles(candles)

    # PC: A(now-3d): 100 -> 95 = DOWN; B(now-2d): 95 -> 98 = UP;
    # дубль B той же секунды (double-fire) не считается дважды;
    # C(now-1h) — горизонт 24ч не дозрел, исключается.
    pc = tmp_path / "pc.jsonl"
    pc.write_text("\n".join([
        json.dumps({"ts": _iso(NOW - timedelta(days=3)), "side": "long"}),
        json.dumps({"ts": _iso(NOW - timedelta(days=2)), "side": "long"}),
        json.dumps({"ts": _iso(NOW - timedelta(days=2)), "side": "short"}),
        json.dumps({"ts": _iso(NOW - timedelta(hours=1)), "side": "long"}),
    ]) + "\n", encoding="utf-8")

    # GC down: D(now-3d, ref 101): +4h close 100 < 101 = LOWER;
    # E(now-1d, ref 97): +4h close 98 > 97 = не lower;
    # up-fire игнорируется; свежий (2ч) — исключается.
    gc = tmp_path / "gc.jsonl"
    gc.write_text("\n".join([
        json.dumps({"ts": _iso(NOW - timedelta(days=3)).replace("+00:00", "Z"),
                    "direction": "down", "details": {"btc_close": 101.0}}),
        json.dumps({"ts": _iso(NOW - timedelta(days=1)),
                    "direction": "down", "details": {"btc_close": 97.0}}),
        json.dumps({"ts": _iso(NOW - timedelta(days=1)),
                    "direction": "up", "details": {"btc_close": 97.0}}),
        json.dumps({"ts": _iso(NOW - timedelta(hours=2)),
                    "direction": "down", "details": {"btc_close": 98.0}}),
    ]) + "\n", encoding="utf-8")

    stats = es.compute_stats(NOW, candles_path=candles, pc_path=pc, gc_path=gc)
    assert stats["pre_cascade_24h"] == {"n": 2, "p_down_pct": 50.0}
    assert stats["gc_down_4h"] == {"n": 2, "p_lower_pct": 50.0}


def test_gate_ok_thresholds() -> None:
    assert es.gate_ok({"n": 30, "p_down_pct": 60.0})
    assert not es.gate_ok({"n": 29, "p_down_pct": 99.0})   # мало событий
    assert not es.gate_ok({"n": 468, "p_lower_pct": 48.5}) # живой GC = монетка
    assert not es.gate_ok({"n": 0, "p_down_pct": None})
    assert not es.gate_ok(None)


def test_format_line() -> None:
    stats = {"gc_down_4h": {"n": 468, "p_lower_pct": 48.5}}
    line = es.format_line(stats, "gc_down_4h", "P(ниже 4ч)")
    assert "48%" in line and "n=468" in line and "60д" in line
    assert es.format_line(None, "gc_down_4h", "P(ниже 4ч)") == "P(ниже 4ч): нет данных"
