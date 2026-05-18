"""Pump-freeze config — sweep-derived (см. scripts/sweep_pump_thresholds.py).

Sweep 2y BTC выбрал ≥1.5% / 30мин one-way:
  - 132 events/год = 2.5/неделя — управляемо
  - 46% trend events = реальная защита от continuing accumulation
  - 35% whipsaw = "бесплатные" паузы (грид окупится)
  - $26k/год saved DD proxy
"""
from pathlib import Path

# ─── Detector thresholds ─────────────────────────────────────────────────────
PUMP_THRESHOLD_PCT = 1.5         # ≥1.5% за окно
PUMP_WINDOW_MIN = 30             # 30-min окно
MIN_PULLBACK_PCT = 0.5           # one-way (no -0.5% retracement during)

# ─── Position filter ─────────────────────────────────────────────────────────
# Фрезим только если бот уже накопил позицию ≥ X BTC — иначе нечего защищать.
MIN_POSITION_BTC_TO_TRIGGER = 0.3

# ─── Resume conditions ──────────────────────────────────────────────────────
RESUME_RETRACEMENT_PCT = 1.0     # цена откатилась -1% от peak → resume
RESUME_TIMEOUT_HOURS = 2         # OR 2h elapsed (раньше — что первое)

# ─── Scope ──────────────────────────────────────────────────────────────────
# Per оператор policy 2026-05-18: pump_freeze применяется ТОЛЬКО к TB.
# После 1-2 недель валидации можно расширить.
APPLIES_TO_BOT_IDS = ("4525648417",)  # TB testbed only

# ─── Loop ───────────────────────────────────────────────────────────────────
TICK_INTERVAL_SEC = 60

# ─── Journal ────────────────────────────────────────────────────────────────
JOURNAL_PATH = Path("state/pump_freeze_events.jsonl")
STATE_PATH = Path("state/pump_freeze_state.json")
