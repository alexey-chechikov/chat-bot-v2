"""Smart resume logic — проверяет реальные условия рынка перед resume.

Timer-based resume (просто N часов) — глупый: если рынок продолжает движение
против бота, resume приведёт к новому drawdown сразу. Здесь — направление-
зависимая проверка регима + свежих cascade fire'ов.

Source of truth:
- state/regime_v2_state.json — per-TF state (4h/1h/15m): STRONG_UP / SLOW_UP /
  RANGE / COMPRESSION / SLOW_DOWN / STRONG_DOWN
- state/cascade_alert_dedup.json — последние cascade fire'ы по типам
- services.volatility_regime.current_regime — текущий vol regime

Логика:
- SHORT bot (paused after cascade_short = price went UP):
  Safe resume если 1h state НЕ в (STRONG_UP, SLOW_UP) И 4h state НЕ MARKUP И
  нет fresh cascade_short в последние 20 мин.

- LONG bot (paused after cascade_long = price went DOWN):
  Safe resume если 1h state НЕ в (STRONG_DOWN, SLOW_DOWN) И 4h state НЕ
  MARKDOWN И нет fresh cascade_long в последние 20 мин.

Если небезопасно — extend pause на EXTEND_BLOCK_MIN минут. Max total — MAX_PAUSE_HOURS.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
REGIME_PATH = ROOT / "state" / "regime_v2_state.json"
CASCADE_DEDUP = ROOT / "state" / "cascade_alert_dedup.json"

EXTEND_BLOCK_MIN = 60       # если небезопасно — продлеваем на час
MAX_PAUSE_HOURS = 12        # макс total пауза — потом resume принудительно
ADVERSE_CASCADE_AGE_MIN = 20  # cascade в последние 20 мин = pause продолжаем


def _read_regime() -> dict:
    if not REGIME_PATH.exists():
        return {}
    try:
        return json.loads(REGIME_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _read_cascade_dedup() -> dict:
    if not CASCADE_DEDUP.exists():
        return {}
    try:
        return json.loads(CASCADE_DEDUP.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _has_fresh_cascade(side: str, *, now: datetime,
                       max_age_min: int = ADVERSE_CASCADE_AGE_MIN,
                       dedup_path: Path = CASCADE_DEDUP) -> tuple[bool, Optional[str]]:
    """Check if any cascade fire of given side happened within max_age_min.
    side: 'long' or 'short'."""
    dedup = _read_cascade_dedup()
    keys_to_check = [k for k in dedup.keys() if k.startswith(f"{side}_") and not k.endswith("_mega")]
    for key in keys_to_check:
        ts_str = dedup.get(key)
        if not ts_str:
            continue
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue
        age_min = (now - ts).total_seconds() / 60.0
        if 0 <= age_min <= max_age_min:
            return True, f"{key}@{ts.strftime('%H:%M')}"
    return False, None


def is_safe_to_resume(side: str, *, now: Optional[datetime] = None,
                       regime_path: Path = REGIME_PATH,
                       dedup_path: Path = CASCADE_DEDUP) -> tuple[bool, list[str]]:
    """Возвращает (safe, reasons). reasons — список факторов почему safe или нет."""
    if now is None:
        now = datetime.now(timezone.utc)
    reasons = []

    # 1. Regime per TF check
    regime = _read_regime()
    btc = regime.get("BTCUSDT", {}) if regime else {}
    state_4h = (btc.get("4h", {}) or {}).get("state")
    state_1h = (btc.get("1h", {}) or {}).get("state")
    state3_4h = (btc.get("4h", {}) or {}).get("state_3state")

    if side == "short":
        # SHORT-bot opens after up-moves. Safe to resume when up-momentum gone.
        adverse_1h = state_1h in ("STRONG_UP", "SLOW_UP")
        adverse_4h = state3_4h == "MARKUP"
        if adverse_1h:
            reasons.append(f"⚠ 1h={state_1h} (рост продолжается — SHORT-bot будет в squeeze)")
        if adverse_4h:
            reasons.append(f"⚠ 4h MARKUP")
        if not adverse_1h and not adverse_4h:
            reasons.append(f"✓ regime OK: 1h={state_1h}, 4h={state_4h}")
    else:  # long
        # LONG-bot opens after down-moves. Safe when down-momentum gone.
        adverse_1h = state_1h in ("STRONG_DOWN", "SLOW_DOWN")
        adverse_4h = state3_4h == "MARKDOWN"
        if adverse_1h:
            reasons.append(f"⚠ 1h={state_1h} (падение продолжается — LONG-bot в drawdown)")
        if adverse_4h:
            reasons.append(f"⚠ 4h MARKDOWN")
        if not adverse_1h and not adverse_4h:
            reasons.append(f"✓ regime OK: 1h={state_1h}, 4h={state_4h}")

    # 2. Fresh adverse cascade check
    has_fresh, cascade_key = _has_fresh_cascade(side, now=now, dedup_path=dedup_path)
    if has_fresh:
        reasons.append(f"⚠ Свежий {cascade_key} (<{ADVERSE_CASCADE_AGE_MIN}мин)")
    else:
        reasons.append(f"✓ нет fresh cascade_{side} за {ADVERSE_CASCADE_AGE_MIN}мин")

    # 3. Vol regime check (any direction — high vol = pause)
    try:
        from services.volatility_regime import current_regime
        vol_regime, vol_pct = current_regime("BTCUSDT")
        if vol_regime == "high":
            reasons.append(f"⚠ Vol regime HIGH ({vol_pct:.0f}% ann) — общая нестабильность")
        else:
            reasons.append(f"✓ Vol regime {vol_regime}")
    except Exception:
        pass

    # Decision: safe iff нет ни одного ⚠
    has_warning = any(r.startswith("⚠") for r in reasons)
    safe = not has_warning
    return safe, reasons


def decide_resume_action(bot_pause_info: dict, side: str, *,
                          now: Optional[datetime] = None,
                          ) -> tuple[str, datetime, list[str]]:
    """Decide whether to resume bot now or extend pause.

    Returns (action, new_until_ts, reasons):
      action: "resume_safe" | "extend_pause" | "resume_max_cap"
      new_until_ts: новое until_ts (если extend) или now (если resume)
    """
    if now is None:
        now = datetime.now(timezone.utc)

    try:
        original_until = datetime.fromisoformat(bot_pause_info["until_ts"])
        # Compute how long bot has been paused (use original until - pause_hours backward)
        # We don't have started_at, so estimate from until - assumed pause_hours
        # Simpler: track 'extends' counter in pause_info
        extends = bot_pause_info.get("extends", 0)
    except (KeyError, ValueError, TypeError):
        return "resume_safe", now, ["⚠ corrupted state, resume forced"]

    safe, reasons = is_safe_to_resume(side, now=now)

    # Max cap: после 12h принудительный resume
    total_extended_hours = extends * EXTEND_BLOCK_MIN / 60.0
    if total_extended_hours >= MAX_PAUSE_HOURS - 4:  # минус initial 4h
        reasons.append(f"⚠ MAX_PAUSE_HOURS={MAX_PAUSE_HOURS}h hit — принудительный resume")
        return "resume_max_cap", now, reasons

    if safe:
        return "resume_safe", now, reasons
    else:
        new_until = now + timedelta(minutes=EXTEND_BLOCK_MIN)
        return "extend_pause", new_until, reasons
