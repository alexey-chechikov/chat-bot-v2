"""Pump-freeze service — авто-пауза SHORT-bot при сильном one-way pump.

Replaces noisy cascade_short_5.0 (5 BTC liq triggers даже на 1% движениях).
Triggers по PRICE move, not liquidations.

Architecture:
  config.py   — thresholds, applies-to bot list
  detector.py — pure pump detection (на 1m bars)
  freezer.py  — apply pause via BotsAPI + journal + TG notify
  loop.py     — async tick every 60s, detector + freezer + resume check
"""
