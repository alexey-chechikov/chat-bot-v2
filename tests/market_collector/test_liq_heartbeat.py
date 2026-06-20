"""WS liveness-heartbeat: пишется на тике + троттлится.
2026-06-20: stale_monitor смотрит heartbeat, а не mtime liquidations.csv —
на тихих выходных ликвидаций нет, csv стареет, но WS живы (ложный STALE)."""
from __future__ import annotations

import json

from market_collector import liquidations as liq


def test_touch_writes_fresh_heartbeat(tmp_path, monkeypatch):
    hb = tmp_path / "liq_stream_heartbeat.json"
    monkeypatch.setattr(liq, "LIQ_HEARTBEAT_PATH", hb)
    monkeypatch.setattr(liq, "_hb_last_write", 0.0)
    liq._touch_heartbeat()
    assert hb.exists()
    assert "ts" in json.loads(hb.read_text())


def test_touch_throttles_within_interval(tmp_path, monkeypatch):
    hb = tmp_path / "liq_stream_heartbeat.json"
    monkeypatch.setattr(liq, "LIQ_HEARTBEAT_PATH", hb)
    monkeypatch.setattr(liq, "_hb_last_write", 0.0)
    monkeypatch.setattr(liq, "_HB_MIN_INTERVAL_SEC", 9999.0)
    liq._touch_heartbeat()           # первый — пишет
    first = hb.read_text()
    monkeypatch.setattr(liq, "_ts_utc_now", lambda: "DIFFERENT")
    liq._touch_heartbeat()           # второй внутри окна — НЕ пишет
    assert hb.read_text() == first   # не перезаписан
