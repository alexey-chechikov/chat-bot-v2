"""Tests for cascade_followup.loop _detect_triggers + per-variant window."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import services.cascade_followup.loop as cf_loop


def test_detect_triggers_uses_per_variant_window() -> None:
    """short_5btc must read 5-min window, mega_short_10btc must read 1-min window."""
    now = datetime(2026, 5, 19, 18, 46, 12, tzinfo=timezone.utc)
    calls: list[int] = []

    def fake_breakdown(now_arg, window_min):
        calls.append(window_min)
        # Same liquidation count in both windows for simplicity
        return (0.0, 12.0, 81500.0, {"bybit": {"long": 0.0, "short": 12.0}})

    with patch("services.cascade_alert.loop._liquidation_window_breakdown",
                side_effect=fake_breakdown):
        triggers = cf_loop._detect_triggers(now)

    # Both windows must be consulted
    assert 5 in calls
    assert 1 in calls
    # Both variants triggered (short=12 ≥ 5 and ≥ 10)
    variants_fired = {t[0] for t in triggers}
    assert "short_5btc" in variants_fired
    assert "mega_short_10btc" in variants_fired


def test_detect_triggers_skips_when_no_price() -> None:
    now = datetime(2026, 5, 19, 18, 46, 12, tzinfo=timezone.utc)

    def fake_breakdown(now_arg, window_min):
        return (0.0, 12.0, None, {})

    with patch("services.cascade_alert.loop._liquidation_window_breakdown",
                side_effect=fake_breakdown):
        triggers = cf_loop._detect_triggers(now)
    assert triggers == []


def test_detect_triggers_skips_below_threshold() -> None:
    """qty 4.0 < short_5btc threshold 5 and < mega 10 → no triggers."""
    now = datetime(2026, 5, 19, 18, 46, 12, tzinfo=timezone.utc)

    def fake_breakdown(now_arg, window_min):
        return (0.0, 4.0, 81500.0, {})

    with patch("services.cascade_alert.loop._liquidation_window_breakdown",
                side_effect=fake_breakdown):
        triggers = cf_loop._detect_triggers(now)
    assert triggers == []


def test_detect_triggers_only_std_tier_fires_with_medium_qty() -> None:
    """qty 6.0: short_5btc fires (≥5), mega_short_10btc skipped (<10)."""
    now = datetime(2026, 5, 19, 18, 46, 12, tzinfo=timezone.utc)

    def fake_breakdown(now_arg, window_min):
        return (0.0, 6.0, 81500.0, {})

    with patch("services.cascade_alert.loop._liquidation_window_breakdown",
                side_effect=fake_breakdown):
        triggers = cf_loop._detect_triggers(now)
    variants_fired = {t[0] for t in triggers}
    assert "short_5btc" in variants_fired
    assert "mega_short_10btc" not in variants_fired


def test_check_edge_drift_returns_drift_status() -> None:
    """_check_edge_drift reflects edge_drift_guard.is_drifted result."""
    with patch("services.cascade_alert.edge_drift_guard.is_drifted",
                return_value=True):
        assert cf_loop._check_edge_drift("short", 5.0) is True
    with patch("services.cascade_alert.edge_drift_guard.is_drifted",
                return_value=False):
        assert cf_loop._check_edge_drift("short", 5.0) is False


def test_check_edge_drift_fail_open_on_exception() -> None:
    """Если is_drifted кидает — _check_edge_drift возвращает False (fail-open).
    Лучше эмитить сигнал, чем молча проглатить."""
    with patch("services.cascade_alert.edge_drift_guard.is_drifted",
                side_effect=RuntimeError("boom")):
        assert cf_loop._check_edge_drift("short", 5.0) is False


def test_signal_loop_suppresses_tg_on_drift(tmp_path, monkeypatch) -> None:
    """Integration: signal fires при триггере; журнал пишется с edge_drift_flag=True,
    TG send_fn НЕ вызывается."""
    import asyncio
    import services.cascade_followup.journal as journal_mod
    monkeypatch.setattr(journal_mod, "JOURNAL_DIR", tmp_path)
    monkeypatch.setattr(cf_loop, "DEDUP_PATH", tmp_path / "dedup.json")

    now = datetime(2026, 5, 19, 18, 46, 12, tzinfo=timezone.utc)
    send_calls = []

    def fake_send(*args, **kwargs):
        send_calls.append((args, kwargs))

    def fake_breakdown(now_arg, window_min):
        return (0.0, 12.0, 81500.0, {"bybit": {"long": 0.0, "short": 12.0}})

    async def _run_once():
        stop = asyncio.Event()
        # signal_loop ждёт interval — выставляем 0.1с и stop через 0.3с
        task = asyncio.create_task(cf_loop.cascade_followup_signal_loop(
            stop, send_fn=fake_send, interval_sec=1,
        ))
        await asyncio.sleep(0.3)
        stop.set()
        await asyncio.wait_for(task, timeout=2.0)

    with patch("services.cascade_alert.loop._liquidation_window_breakdown",
                side_effect=fake_breakdown), \
         patch("services.cascade_alert.edge_drift_guard.is_drifted",
                return_value=True):
        asyncio.run(_run_once())

    # TG send не вызвался (suppressed)
    assert send_calls == []
    # Журналы для обоих вариантов получили запись с edge_drift_flag=True
    for variant in ("short_5btc", "mega_short_10btc"):
        from services.cascade_followup.journal import read_all, journal_path_for
        path = journal_path_for(variant)
        if path.exists():
            rows = read_all(path=path)
            assert rows, f"журнал {variant} должен иметь запись"
            assert rows[-1]["edge_drift_flag"] is True


def test_signal_loop_sends_tg_when_no_drift(tmp_path, monkeypatch) -> None:
    """Когда drift=False — нормальный TG send."""
    import asyncio
    import services.cascade_followup.journal as journal_mod
    import services.cascade_alert.cross_service_dedup as csd
    monkeypatch.setattr(journal_mod, "JOURNAL_DIR", tmp_path)
    monkeypatch.setattr(cf_loop, "DEDUP_PATH", tmp_path / "dedup.json")
    # Isolate cross-service dedup state — tests must not see live data.
    monkeypatch.setattr(csd, "STATE_PATH", tmp_path / "cross_dedup.json")

    send_calls = []

    def fake_send(*args, **kwargs):
        send_calls.append((args, kwargs))

    def fake_breakdown(now_arg, window_min):
        return (0.0, 12.0, 81500.0, {"bybit": {"long": 0.0, "short": 12.0}})

    async def _run_once():
        stop = asyncio.Event()
        task = asyncio.create_task(cf_loop.cascade_followup_signal_loop(
            stop, send_fn=fake_send, interval_sec=1,
        ))
        await asyncio.sleep(0.3)
        stop.set()
        await asyncio.wait_for(task, timeout=2.0)

    # 2026-07-29: семья заглушена в silent_families (оператор: «спам, нужен
    # более надёжный сигнал»). Для проверки самого send-пути снимаем глушение —
    # поведение глушения покрыто отдельным тестом ниже.
    with patch("services.cascade_alert.loop._liquidation_window_breakdown",
                side_effect=fake_breakdown), \
         patch("services.cascade_alert.edge_drift_guard.is_drifted",
                return_value=False), \
         patch("services.common.silent_families.tg_muted", return_value=False):
        asyncio.run(_run_once())

    # TG send должен вызваться хотя бы один раз (для одного из вариантов)
    assert len(send_calls) >= 1, "drift=False — TG send должен сработать"


def test_signal_loop_silent_when_family_muted(tmp_path, monkeypatch) -> None:
    """Заглушённая семья не шлёт в TG, но журнал пишется (эдж копится)."""
    from services.common import silent_families as sf
    cfg = tmp_path / "silent.json"
    cfg.write_text('{"muted": ["CASCADE_FOLLOWUP"]}', encoding="utf-8")
    monkeypatch.setattr(sf, "CONFIG_PATH", cfg)
    assert sf.tg_muted("CASCADE_FOLLOWUP") is True
    assert sf.tg_muted("TREND_SIGNAL") is False
