"""SHORT bots guard — авто-пауза SHORT GinArea ботов при adverse событиях.

Триггеры pause:
- cascade_short_5btc / cascade_short_2btc — shorts массово ликвидируются →
  70% pct_up 4h (combined backtest 2024+2026). Grid SHORT в это время
  накапливает unrealized минус. Пауза на 4ч.
- vol_regime → HIGH (если переход LOW→HIGH в течение часа)
- 4h regime → STRONG_UP (явный bull breakout)

Триггеры resume:
- Прошло N часов после pause (default 4h) И ни одного нового trigger event

Управление через GinArea API: set_params с p=false (pause) / p=true (resume).
"""
from .control import (
    pause_bot, resume_bot, is_paused, get_bot_state,
)
from .config import load_managed_bots, ManagedBot
from .watchdog import (
    check_and_act, evaluate_triggers, AUTO_PAUSE_PATH,
)
