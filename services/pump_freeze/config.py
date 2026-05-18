"""Pump-freeze config — bidirectional version.

SHORT bots (inverse XBTUSD): freeze на UP-pump (≥1.5%/30m one-way вверх)
LONG bots (linear XBTUSDT):  freeze на DOWN-dump (≤-1.5%/30m one-way вниз)

T2/T3 — sacred (отдельный фильтр позже, см. project_t2_t3_separate_filter.md).
"""
from pathlib import Path

# ─── Detector thresholds (одни и те же для обеих сторон) ────────────────────
PUMP_THRESHOLD_PCT = 1.5         # abs move ≥1.5% за окно
PUMP_WINDOW_MIN = 30             # 30-min окно
MIN_PULLBACK_PCT = 0.5           # one-way (no opposite-side retracement)

# ─── Position filter (USD-equivalent для обеих сторон) ─────────────────────
# SHORT: |pos_btc| × mid_btc; LONG: |pos_usdt|. Threshold ≈ 0.3 BTC × $80k.
MIN_POSITION_USD_TO_TRIGGER = 24_000

# ─── Resume conditions ──────────────────────────────────────────────────────
RESUME_RETRACEMENT_PCT = 1.0     # |price retracement| ≥ 1% от extreme → resume
RESUME_TIMEOUT_HOURS = 2

# ─── Scope (per оператор 2026-05-18b: T1+TB SHORT + LONG-D/V5 LONG) ────────
# bot_id → side ("short" | "long")
APPLIES_TO_BOTS = {
    "4525648417": "short",   # TB testbed
    "4729923198": "short",   # T1 SHORT (production)
    "5154651487": "long",    # LONG-D хедж
    "4979458320": "long",    # LONG-V5 хедж
    # T2 (6287583200) — EXCLUDED, sacred
    # T3 (5736281160) — EXCLUDED, sacred
}

# ─── Loop ───────────────────────────────────────────────────────────────────
TICK_INTERVAL_SEC = 60

# ─── Journal ────────────────────────────────────────────────────────────────
JOURNAL_PATH = Path("state/pump_freeze_events.jsonl")
STATE_PATH = Path("state/pump_freeze_state.json")
