"""Tests for services.telegram.alert_router (P2 of TZ-DASHBOARD-AND-TELEGRAM-USABILITY-PHASE-1)."""
from __future__ import annotations

from pathlib import Path

import pytest

from services.telegram.alert_router import (
    PRIMARY,
    ROUTINE,
    VERBOSE,
    VerboseSubscriptionRegistry,
    channel_for,
    handle_verbose_command,
    select_recipients,
)


# ── channel_for ─────────────────────────────────────────────────────────────

def test_channel_for_primary_emitters() -> None:
    """2026-07-29 ревизия: в личку только то, что требует решения СЕЙЧАС и
    касается денег. Всё контекстное переведено в ROUTINE."""
    for emitter in ("TREND_SIGNAL", "LIQ_CASCADE", "PNL_EXTREME",
                    "MARGIN_ALERT", "ENGINE_ALERT", "SETUP_ON",
                    "BOT_STATE_CHANGE", "ALT_GUARD"):
        assert channel_for(emitter) == PRIMARY, f"{emitter} should be PRIMARY"


def test_channel_for_routine_emitters() -> None:
    for emitter in ("P15_REENTRY", "P15_HARVEST", "LEVEL_BREAK", "PAPER_TRADE",
                    # переведены из PRIMARY 2026-07-29 — фон, не действие
                    "REGIME_CHANGE", "PARAM_CHANGE", "POSITION_CHANGE",
                    "PNL_EVENT", "BOUNDARY_BREACH", "LIQ_CLUSTER_BUILD",
                    "SETUP_OFF", "GRID_EXHAUSTION", "P15_OPEN", "P15_CLOSE",
                    "MA_CROSS", "SCALP_LIQ"):
        assert channel_for(emitter) == ROUTINE, f"{emitter} should be ROUTINE"


def test_trend_signal_is_primary() -> None:
    """Главный actionable-канал 2026-07: валидированный эдж ETH/XRP."""
    assert channel_for("TREND_SIGNAL") == PRIMARY


def test_channel_for_verbose_emitters() -> None:
    for emitter in ("RSI_EXTREME", "AUTO_EDGE_ALERT", "SETUP_DETECTOR_DEEP"):
        assert channel_for(emitter) == VERBOSE, f"{emitter} should be VERBOSE"


def test_channel_for_unknown_defaults_to_primary() -> None:
    """Unknown emitters fail-safe to PRIMARY (operator never silently misses)."""
    assert channel_for("UNKNOWN_NEW_EMITTER") == PRIMARY


# ── VerboseSubscriptionRegistry ────────────────────────────────────────────

def test_registry_starts_empty(tmp_path: Path) -> None:
    reg = VerboseSubscriptionRegistry(state_path=tmp_path / "subs.json")
    assert not reg.is_subscribed(123)
    assert reg.subscribed_chat_ids() == set()


def test_registry_subscribe_persists_to_disk(tmp_path: Path) -> None:
    state_path = tmp_path / "subs.json"
    reg = VerboseSubscriptionRegistry(state_path=state_path)
    changed = reg.subscribe(123)
    assert changed is True
    assert reg.is_subscribed(123) is True
    # Reload from disk
    reg2 = VerboseSubscriptionRegistry(state_path=state_path)
    assert reg2.is_subscribed(123) is True


def test_registry_subscribe_idempotent(tmp_path: Path) -> None:
    reg = VerboseSubscriptionRegistry(state_path=tmp_path / "subs.json")
    assert reg.subscribe(123) is True
    assert reg.subscribe(123) is False  # already subscribed


def test_registry_unsubscribe(tmp_path: Path) -> None:
    reg = VerboseSubscriptionRegistry(state_path=tmp_path / "subs.json")
    reg.subscribe(123)
    assert reg.unsubscribe(123) is True
    assert reg.is_subscribed(123) is False
    assert reg.unsubscribe(123) is False  # already unsubscribed


def test_registry_toggle(tmp_path: Path) -> None:
    reg = VerboseSubscriptionRegistry(state_path=tmp_path / "subs.json")
    assert reg.toggle(123) is True   # was off → now on
    assert reg.is_subscribed(123) is True
    assert reg.toggle(123) is False  # was on → now off
    assert reg.is_subscribed(123) is False


# ── select_recipients ───────────────────────────────────────────────────────

def test_select_recipients_primary_to_all_chats(tmp_path: Path) -> None:
    reg = VerboseSubscriptionRegistry(state_path=tmp_path / "subs.json")
    recipients = select_recipients(
        "LIQ_CASCADE",
        primary_chat_ids=[100, 200, 300],
        verbose_registry=reg,
    )
    assert recipients == [100, 200, 300]


def test_select_recipients_verbose_only_to_subscribed(tmp_path: Path) -> None:
    reg = VerboseSubscriptionRegistry(state_path=tmp_path / "subs.json")
    reg.subscribe(200)
    recipients = select_recipients(
        "RSI_EXTREME",
        primary_chat_ids=[100, 200, 300],
        verbose_registry=reg,
    )
    assert recipients == [200]


def test_select_recipients_verbose_with_no_subs_returns_empty(tmp_path: Path) -> None:
    """No subscribers → VERBOSE event reaches no one."""
    reg = VerboseSubscriptionRegistry(state_path=tmp_path / "subs.json")
    recipients = select_recipients(
        "RSI_EXTREME",
        primary_chat_ids=[100, 200],
        verbose_registry=reg,
    )
    assert recipients == []


def test_select_recipients_verbose_does_not_leak_to_unallowed_chat(tmp_path: Path) -> None:
    """A chat that subscribed but isn't in primary_chat_ids must NOT receive VERBOSE."""
    reg = VerboseSubscriptionRegistry(state_path=tmp_path / "subs.json")
    reg.subscribe(999)  # subscribed but not in primary list
    recipients = select_recipients(
        "RSI_EXTREME",
        primary_chat_ids=[100, 200],
        verbose_registry=reg,
    )
    assert recipients == []


# ── handle_verbose_command ──────────────────────────────────────────────────

def test_verbose_command_status_shows_off_by_default(tmp_path: Path) -> None:
    reg = VerboseSubscriptionRegistry(state_path=tmp_path / "subs.json")
    reply = handle_verbose_command(123, "status", reg)
    assert "ВЫКЛЮЧЕНА" in reply
    assert reg.is_subscribed(123) is False


def test_verbose_command_on_subscribes(tmp_path: Path) -> None:
    reg = VerboseSubscriptionRegistry(state_path=tmp_path / "subs.json")
    reply = handle_verbose_command(123, "on", reg)
    assert "ВКЛЮЧЕНА" in reply
    assert reg.is_subscribed(123) is True


def test_verbose_command_off_unsubscribes(tmp_path: Path) -> None:
    reg = VerboseSubscriptionRegistry(state_path=tmp_path / "subs.json")
    reg.subscribe(123)
    reply = handle_verbose_command(123, "off", reg)
    assert "ВЫКЛЮЧЕНА" in reply
    assert reg.is_subscribed(123) is False


def test_verbose_command_no_arg_toggles(tmp_path: Path) -> None:
    reg = VerboseSubscriptionRegistry(state_path=tmp_path / "subs.json")
    # First call without arg → toggle ON
    reply1 = handle_verbose_command(123, "", reg)
    assert "ВКЛЮЧЕНА" in reply1
    # Second call without arg → toggle OFF
    reply2 = handle_verbose_command(123, "", reg)
    assert "ВЫКЛЮЧЕНА" in reply2


def test_verbose_command_unknown_arg_shows_usage(tmp_path: Path) -> None:
    reg = VerboseSubscriptionRegistry(state_path=tmp_path / "subs.json")
    reply = handle_verbose_command(123, "xyz", reg)
    assert "Использование" in reply
