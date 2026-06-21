"""«ПЛАН ДНЯ» — утром (и на каждом брифе) показывает арсенал под ТЕКУЩИЙ режим.

2026-06-21: оператор «утром выбирал направление работы и видел весь арсенал
под сегодняшний режим». Берёт живой regime_label (последний из setups.jsonl —
та же таксономия, что у гейта) + BTC 4h 3-state, и через
edge_stats.armed_setups_for_regime() выдаёт armed-сетапы с PF режима и подсказкой
куда смотреть. Нет armed → честно «грид-день, входов не жди».
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SETUPS = ROOT / "state" / "setups.jsonl"

# Куда смотреть по каждому типу (направление зашито в префиксе short_/long_).
SETUP_HINT = {
    "short_rally_fade":       "отскок вверх к сопротивлению/PDH → шорт",
    "short_double_top":       "двойная вершина на краю флэта → шорт",
    "short_pdh_rejection":    "отбой от PDH → шорт",
    "short_div_bos_15m":      "медвежья дивергенция+слом 15m → шорт",
    "long_pdl_bounce":        "провал к PDL → лонг от поддержки",
    "long_dump_reversal":     "разворот после импульсного дампа → лонг",
    "long_double_bottom":     "двойное дно → лонг",
    "long_div_bos_15m":       "бычья дивергенция+слом 15m → лонг",
    "long_div_bos_confirmed": "подтверждённый div+BOS → лонг",
    "long_multi_divergence":  "мульти-дивергенция → лонг",
    "long_mega_dump_bounce":  "отскок после мега-дампа → лонг",
}

_BIAS = {
    "MARKDOWN": "вниз ↓ — шорты по тренду, лонги только контртренд-нишами",
    "MARKUP":   "вверх ↑ — лонги по тренду, шорты только контртренд-нишами",
    "RANGE":    "боковик ↔ — обе стороны от краёв диапазона",
}


def current_regime_label() -> str | None:
    """Последний regime_label из setups.jsonl = текущий режим (детектор тикает 5мин)."""
    if not SETUPS.exists():
        return None
    try:
        size = SETUPS.stat().st_size
        with SETUPS.open("rb") as fh:
            if size > 8000:
                fh.seek(size - 8000)
                fh.readline()
            lines = fh.read().decode("utf-8", errors="replace").splitlines()
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                lab = json.loads(line).get("regime_label")
            except json.JSONDecodeError:
                continue
            if lab:
                return lab
    except OSError:
        pass
    return None


def build_day_plan_lines() -> list[str]:
    from services.setup_detector.edge_stats import (
        armed_setups_for_regime, btc_3state, is_countertrend)
    from services.common.humanize import humanize_setup_type

    reg = current_regime_label()
    btc4 = btc_3state()
    bias = _BIAS.get(btc4 or "", "боковик ↔ — обе стороны от краёв")
    L = ["━ 📋 ПЛАН ДНЯ"]
    L.append(f"режим: BTC 4h {btc4 or '?'} · интрадей {reg or 'неизвестен'} → {bias}")

    armed = armed_setups_for_regime(reg)
    if not armed:
        L.append("направленного эджа в этом режиме нет → грид-день, новых входов не жди")
        return L

    L.append("arsenal (armed под текущий режим):")
    for st, e in armed:
        icon = "🔴" if st.startswith("short_") else "🟢"
        ct = " ⚠️контртренд" if is_countertrend(st, btc4) else ""
        hint = SETUP_HINT.get(st, humanize_setup_type(st))
        L.append(f"{icon} PF {e['regime_pf']:.1f} · {hint}{ct}")
    L.append("стрельнёт сетап → прилетит 🎯 ОТКРОЙ с entry/SL/TP")
    return L
