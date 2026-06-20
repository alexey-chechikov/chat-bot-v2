"""TV webhook signal type constants + per-type config."""
from __future__ import annotations

# ── Signal type identifiers (set by Pine script in JSON payload) ──────────────

EXHAUSTION_TOP    = "exhaustion_top"      # истощение вверху → шорт-разворот
EXHAUSTION_BOTTOM = "exhaustion_bottom"   # истощение внизу → лонг-разворот
SQUEEZE_UP        = "squeeze_breakout_up"   # пробой сжатия вверх → импульс лонг
SQUEEZE_DOWN      = "squeeze_breakout_down" # пробой сжатия вниз → импульс шорт
SPX_DROP          = "spx_drop"            # S&P 500 резко падает → давление на BTC
SPX_PUMP          = "spx_pump"            # S&P 500 растёт → BTC аппетит к риску
BOS_BULLISH       = "bos_bullish"         # break of structure вверх (1H)
BOS_BEARISH       = "bos_bearish"         # break of structure вниз (1H)
LIQ_CASCADE       = "liq_cascade"         # всплеск ликвидаций
VOL_REJECTION     = "vol_rejection"       # объёмное отбитие на ключевом уровне
RANGE_BOUNDARY    = "range_boundary"      # у границы недельного диапазона
CVD_DIVERGENCE    = "cvd_divergence"      # legacy (текущий пайн-скрипт)

# ── Dedup cooldown per signal type (seconds) ──────────────────────────────────
# Повторный сигнал того же типа игнорируется в течение этого окна.

COOLDOWN_SEC: dict[str, int] = {
    EXHAUSTION_TOP:    45 * 60,   # 45 мин — топы/боттомы редкие события
    EXHAUSTION_BOTTOM: 45 * 60,
    SQUEEZE_UP:        60 * 60,   # 1 час — один импульс в окне
    SQUEEZE_DOWN:      60 * 60,
    SPX_DROP:          20 * 60,   # 20 мин — macro события могут идти волнами
    SPX_PUMP:          20 * 60,
    BOS_BULLISH:       90 * 60,   # 1.5 часа — структурный пробой
    BOS_BEARISH:       90 * 60,
    LIQ_CASCADE:       10 * 60,   # 10 мин — каскады кластерятся
    VOL_REJECTION:     30 * 60,   # 30 мин
    RANGE_BOUNDARY:    120 * 60,  # 2 часа — граница диапазона редко меняется
    CVD_DIVERGENCE:    30 * 60,   # legacy
}

DEFAULT_COOLDOWN_SEC = 30 * 60

# ── Which signal types trigger immediate TG notification ──────────────────────

NOTIFY_IMMEDIATELY: set[str] = {
    EXHAUSTION_TOP,
    EXHAUSTION_BOTTOM,
    SQUEEZE_UP,
    SQUEEZE_DOWN,
    SPX_DROP,
    BOS_BULLISH,
    LIQ_CASCADE,
}

# ── Human labels for TG messages ──────────────────────────────────────────────

SIGNAL_LABEL: dict[str, str] = {
    EXHAUSTION_TOP:    "ИСТОЩЕНИЕ ↑ | шорт-разворот",
    EXHAUSTION_BOTTOM: "ИСТОЩЕНИЕ ↓ | лонг-разворот",
    SQUEEZE_UP:        "ИМПУЛЬС ▲ | пробой сжатия вверх",
    SQUEEZE_DOWN:      "ИМПУЛЬС ▼ | пробой сжатия вниз",
    SPX_DROP:          "SPX ПАДАЕТ | давление на крипту",
    SPX_PUMP:          "SPX РАСТЁТ | риск-аппетит",
    BOS_BULLISH:       "BOS ВВЕРХ | структурный разворот ↑",
    BOS_BEARISH:       "BOS ВНИЗ | структурный разворот ↓",
    LIQ_CASCADE:       "КАСКАД ЛИКВИДАЦИЙ",
    VOL_REJECTION:     "ОБЪЁМНОЕ ОТБИТИЕ",
    RANGE_BOUNDARY:    "ГРАНИЦА ДИАПАЗОНА",
    CVD_DIVERGENCE:    "CVD дивергенция",
}

SIGNAL_EMOJI: dict[str, str] = {
    EXHAUSTION_TOP:    "🔴",
    EXHAUSTION_BOTTOM: "🟢",
    SQUEEZE_UP:        "⚡",
    SQUEEZE_DOWN:      "⚡",
    SPX_DROP:          "🌐",
    SPX_PUMP:          "🌐",
    BOS_BULLISH:       "📈",
    BOS_BEARISH:       "📉",
    LIQ_CASCADE:       "💥",
    VOL_REJECTION:     "📊",
    RANGE_BOUNDARY:    "📐",
    CVD_DIVERGENCE:    "〰️",
}
