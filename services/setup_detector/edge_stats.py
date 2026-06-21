"""Валидные входные эджи + режим-условный гейт.

2026-06-21: оператор «вижу только жди/закрывай, реальных входов не вижу».
Корень: app_runner пушил в личку только conf≥70 или 2 priority-типа, а
rally_fade/dump_reversal/pdl_bounce (PF 1.6–3.1) молча резались.

Числа из state/setup_precision_outcomes.jsonl (точные TP/SL, all-time):
один и тот же сетап в разных режимах = разный эдж, поэтому гейт режим-условный.
Пушим вход ТОЛЬКО если PF в ТЕКУЩЕМ режиме > MIN_REGIME_PF — это и есть
«качество с балансом»: в плохом режиме сетап молчит сам.

Словарь режимов (regime_label на сетапе) совпадает с regime в outcomes:
range_wide / consolidation / trend_up / trend_down / range_tight.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REGIME_V2_PATH = ROOT / "state" / "regime_v2_state.json"

MIN_REGIME_PF = 1.2   # ниже — эдж в этом режиме не пушим

# Общая статистика (all-regime) — для отображения «как тип в среднем».
# pf / wr% / rr / exp%(ожидание на сделку) / n
EDGE_OVERALL: dict[str, dict] = {
    "short_rally_fade":    {"pf": 3.13, "wr": 62, "rr": 1.96, "exp": 0.303, "n": 91},
    "long_dump_reversal":  {"pf": 3.05, "wr": 54, "rr": 2.63, "exp": 0.280, "n": 82},
    "long_div_bos_15m":    {"pf": 1.93, "wr": 50, "rr": 1.93, "exp": 0.294, "n": 26},
    "long_div_bos_confirmed": {"pf": 4.49, "wr": 60, "rr": 2.5, "exp": 0.30, "n": 20},
    "long_pdl_bounce":     {"pf": 1.63, "wr": 41, "rr": 2.34, "exp": 0.138, "n": 229},
}

# Режим-условный PF/WR/n (cell). Отсутствие пары (тип,режим) = нет данных →
# не угадываем, не пушим (кроме always-armed ниже).
EDGE_BY_REGIME: dict[tuple[str, str], dict] = {
    ("short_rally_fade", "range_wide"):    {"pf": 7.3,  "wr": 60, "n": 20},
    ("short_rally_fade", "consolidation"): {"pf": 18.0, "wr": 95, "n": 20},  # PF=187, капнут для отображения
    ("short_rally_fade", "trend_up"):      {"pf": 2.2,  "wr": 43, "n": 30},
    ("short_rally_fade", "range_tight"):   {"pf": 0.6,  "wr": 57, "n": 21},  # ТЕРЯЕТ
    ("long_dump_reversal", "trend_down"):  {"pf": 3.3,  "wr": 53, "n": 49},
    ("long_dump_reversal", "range_wide"):  {"pf": 2.8,  "wr": 56, "n": 32},
    ("long_pdl_bounce", "range_wide"):     {"pf": 2.0,  "wr": 43, "n": 89},
    ("long_pdl_bounce", "consolidation"):  {"pf": 1.6,  "wr": 43, "n": 30},
    ("long_pdl_bounce", "trend_down"):     {"pf": 1.4,  "wr": 39, "n": 109},
}

# Типы, которые armed в любом режиме (walk-forward стабильные, мало режим-зависимы).
ALWAYS_ARMED = {"long_div_bos_15m", "long_div_bos_confirmed"}


def direction_of(setup_type: str) -> str:
    return "SHORT" if setup_type.startswith("short_") else "LONG"


def edge_for(setup_type: str, regime_label: str | None) -> dict | None:
    """Вернуть статистику эджа, если тип ВАЛИДЕН в текущем режиме, иначе None.

    Решение:
      - тип не в списке валидных → None
      - always-armed тип → отдаём (overall)
      - есть cell (тип,режим): armed только если cell PF > MIN_REGIME_PF
      - нет cell, но режим неизвестен/нет данных → None (не угадываем)
    """
    base = EDGE_OVERALL.get(setup_type)
    if base is None:
        return None
    if setup_type in ALWAYS_ARMED:
        return {**base, "regime_pf": base["pf"], "regime": regime_label, "regime_known": False}
    cell = EDGE_BY_REGIME.get((setup_type, regime_label or ""))
    if cell is None:
        return None  # нет данных по этому режиму — молчим
    if cell["pf"] <= MIN_REGIME_PF:
        return None  # эдж в этом режиме отрицательный/слабый — молчим
    return {**base, "regime_pf": cell["pf"], "regime_wr": cell["wr"],
            "regime_n": cell["n"], "regime": regime_label, "regime_known": True}


def btc_3state() -> str | None:
    """BTC 4h MARKUP/MARKDOWN/RANGE — для пометки контртренда."""
    try:
        d = json.loads(REGIME_V2_PATH.read_text(encoding="utf-8"))
        return (d.get("BTCUSDT", {}).get("4h", {}) or {}).get("state_3state")
    except Exception:
        return None


def is_countertrend(setup_type: str, btc4: str | None) -> bool:
    """LONG в MARKDOWN или SHORT в MARKUP = против 4h-тренда."""
    d = direction_of(setup_type)
    return (d == "LONG" and btc4 == "MARKDOWN") or (d == "SHORT" and btc4 == "MARKUP")
