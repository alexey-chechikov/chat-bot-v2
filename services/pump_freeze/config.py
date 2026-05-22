"""Pump-freeze config — bidirectional version.

SHORT bots (inverse XBTUSD): freeze на UP-pump (≥1.5%/30m one-way вверх)
LONG bots (linear XBTUSDT):  freeze на DOWN-dump (≤-1.5%/30m one-way вниз)

T2/T3 — sacred (отдельный фильтр позже, см. project_t2_t3_separate_filter.md).
"""
from pathlib import Path

# ─── Detector thresholds ────────────────────────────────────────────────────
# 2026-05-18 update после Win-колегиной верификации:
#   - Removed one-way pullback filter (whipsaw events тоже нужно паузить)
#   - Convergence: my 132 events/yr (с filter) → 177/yr (без filter) = match
PUMP_THRESHOLD_PCT = 1.5         # abs move ≥1.5% за окно
PUMP_WINDOW_MIN = 30             # 30-min окно
# MIN_PULLBACK_PCT removed — was 0.5; cutting whipsaws was incorrect

# ─── Re-freeze gate (после resume — когда снова можно freeze) ───────────────
# 2026-05-22 pullback research (674 events): time-based cooldown заменён на
# price-based re-freeze. Бот «дышит» в такт движению — пауза на росте к hi,
# resume на откате. На тренде это даёт ~107мин паузы за 4ч (несколько циклов),
# на whipsaw ~40мин (один цикл). Time-cooldown душил это дыхание.
PUMP_COOLDOWN_MIN = 0            # отключён — re-freeze управляется ценой, не временем
REFREEZE_RETURN_PCT = 1.0        # после resume: freeze заново когда цена вернулась
                                 # ≥1% к extreme стороны движения (возврат к hi/lo)

# ─── Position filter (USD-equivalent для обеих сторон) ─────────────────────
# SHORT: |pos_btc| × mid_btc; LONG: |pos_usdt|. Threshold ≈ 0.3 BTC × $80k.
MIN_POSITION_USD_TO_TRIGGER = 24_000

# ─── Resume conditions ──────────────────────────────────────────────────────
# 2026-05-22 research: откат 1% ловит 88% выносов за ~38мин (med). Это рабочий
# механизм. Таймаут — только дальняя страховка от зависшего state, не рабочий
# путь (был 4ч → 12ч: не давать таймауту опережать откат-условие).
RESUME_RETRACEMENT_PCT = 1.0     # |price retracement| ≥ 1% от extreme → resume
RESUME_TIMEOUT_HOURS = 12        # safety net only (был 4 — опережал откат)

# Stall-resume (2026-05-22): движение может встать в боковик под hi —
# не откатывает на 1%, но и не обновляет hi. Раньше бот стоял до таймаута
# (день простоя!). Теперь: N минут без нового extreme → движение выдохлось →
# resume, бот работает в диапазоне и подтягивает среднюю точку входа.
# N=45: ранний false-resume на тренде самоисправляется re-freeze gate.
RESUME_STALL_MIN = 45            # минут без нового extreme → resume по stall

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
