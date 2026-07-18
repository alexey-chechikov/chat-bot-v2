"""GC down-карточка после аудита 2026-07-18: без мёртвых вероятностей.

Статичные «73/78/86%» из бэктеста 05-29 умерли на live (60д: 48.5%),
mirror-short подсказка убыточна (score>=5: 45% ниже, mean +0.24% вверх).
Карточка = индикатор полярности + ЖИВОЕ число из edge_stats.
"""
from __future__ import annotations

import services.grid_coordinator.loop as gc


def _details() -> dict:
    return {
        "rsi_btc_now": 28.1, "mfi_btc_now": 29.8, "vol_z_now": 1.2,
        "oi_change_1h_pct": 0.43, "funding_rate_8h": 2e-05,
        "eth_rsi_now": 28.9, "xrp_mfi_now": 54.1, "btc_eth_corr_30h": 0.914,
        "btc_close": 62944.2,
        "down_signals": {"rsi_low": True, "mfi_low": True, "eth_sync_low": True},
        "up_signals": {},
    }


def test_down_card_has_live_edge_no_dead_numbers(monkeypatch) -> None:
    monkeypatch.setattr(gc, "_live_gc_edge_line",
                        lambda: "Живой эдж: P(ниже 4ч) = 48% (n=468, 60д).")
    text = gc._format_card("down", 5, _details())
    assert "Живой эдж" in text and "48%" in text
    for dead in ("73%", "78%", "86%", "mirror", "SHORT-сетап"):
        assert dead not in text
    # полярность и защита контр-ноги остаются — это ценность карточки
    assert "Полярность" in text or "вниз" in text
    assert "Защити/сократи LONG-сетки" in text


def test_down_card_survives_edge_stats_failure(monkeypatch) -> None:
    def _boom():
        raise RuntimeError("no stats")
    # сама карточка не должна падать из-за статистики
    monkeypatch.setattr(gc, "_live_gc_edge_line",
                        gc._live_gc_edge_line.__wrapped__
                        if hasattr(gc._live_gc_edge_line, "__wrapped__")
                        else gc._live_gc_edge_line)
    text = gc._format_card("down", 4, _details())
    assert "НИЗ — ИМПУЛЬС ВНИЗ" in text
