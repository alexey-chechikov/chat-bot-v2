"""Smoke tests for main keyboard layout."""
from __future__ import annotations

from telegram_ui.keyboards import build_main_keyboard


def test_keyboard_has_no_duplicates():
    """Сlassic bug: /advise + /advisor as two separate buttons."""
    kb = build_main_keyboard()
    texts = []
    for row in kb.keyboard:
        for btn in row:
            texts.append(btn["text"] if isinstance(btn, dict) else btn.text)
    assert len(texts) == len(set(texts)), f"Duplicates: {[t for t in texts if texts.count(t) > 1]}"


def test_keyboard_essential_buttons_present():
    """Daily snapshot + key insight commands should be in the keyboard."""
    kb = build_main_keyboard()
    texts = set()
    for row in kb.keyboard:
        for btn in row:
            texts.add(btn["text"] if isinstance(btn, dict) else btn.text)
    essentials = {"/status", "/setups", "/ginarea", "/card", "/morning_brief", "HELP"}
    missing = essentials - texts
    assert not missing, f"Missing essential buttons: {missing}"


def test_keyboard_excludes_debug_commands():
    """Debug-only commands shouldn't be on the keyboard."""
    kb = build_main_keyboard()
    texts = set()
    for row in kb.keyboard:
        for btn in row:
            texts.add(btn["text"] if isinstance(btn, dict) else btn.text)
    # /pipeline /precision /histogram /inspect /cron — debug observability,
    # available via text but not on the keyboard.
    debug = {"/regime_v2", "/pipeline", "/precision", "/histogram",
             "/inspect", "/cron"}
    leaked = debug & texts
    assert not leaked, f"Debug commands on keyboard: {leaked}"
