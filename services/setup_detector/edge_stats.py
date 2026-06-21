"""Валидные входные эджи + режим-условный гейт (data-driven из матрицы).

2026-06-21: оператор «один сетап в разном режиме = разный эдж → не убивать,
найти нишу и пускать только в нужном режиме». Гейт грузит матрицу
state/setup_regime_edge.json (генерит scripts/setup_regime_matrix.py из точных
TP/SL исходов). Пушим вход ТОЛЬКО если (тип,режим) помечен ARMED.

Не убиваем по общему PF: double_top ВСЕГО 0.73, но range_wide 1.62 = ARMED;
pdh_rejection ВСЕГО 0.54, но trend_up 2.43 = ARMED. WATCH-ниши (PF>1.2 но n мал)
НЕ пушим — дозреют и авто-промоутятся в ARMED на следующей регенерации.

Hardcoded fallback на случай отсутствия артефакта.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REGIME_V2_PATH = ROOT / "state" / "regime_v2_state.json"
ARTIFACT_PATH = ROOT / "state" / "setup_regime_edge.json"

MIN_REGIME_PF = 1.2

# ── Fallback (используется ТОЛЬКО если артефакт отсутствует/битый) ──
_FB_OVERALL: dict[str, dict] = {
    "short_rally_fade":   {"pf": 3.13, "wr": 62, "rr": 1.96, "exp": 0.303, "n": 91},
    "long_dump_reversal": {"pf": 3.05, "wr": 54, "rr": 2.63, "exp": 0.280, "n": 82},
    "long_div_bos_15m":   {"pf": 1.93, "wr": 50, "rr": 1.93, "exp": 0.294, "n": 26},
    "long_pdl_bounce":    {"pf": 1.63, "wr": 41, "rr": 2.34, "exp": 0.138, "n": 229},
}
_FB_REGIME: dict[str, dict[str, dict]] = {
    "short_rally_fade":   {"range_wide": {"pf": 7.3, "wr": 60, "n": 20, "tier": "ARMED"},
                           "trend_up":   {"pf": 2.2, "wr": 43, "n": 30, "tier": "ARMED"}},
    "long_dump_reversal": {"trend_down": {"pf": 3.3, "wr": 53, "n": 49, "tier": "ARMED"},
                           "range_wide": {"pf": 2.8, "wr": 56, "n": 32, "tier": "ARMED"}},
    "long_pdl_bounce":    {"range_wide": {"pf": 2.0, "wr": 43, "n": 89, "tier": "ARMED"},
                           "trend_down": {"pf": 1.4, "wr": 39, "n": 109, "tier": "ARMED"}},
}
_FB_ALWAYS = {"long_div_bos_15m", "long_div_bos_confirmed"}


def _load() -> dict:
    try:
        d = json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))
        if d.get("overall") and d.get("regime_edge") is not None:
            return d
    except Exception:
        pass
    return {"overall": _FB_OVERALL, "regime_edge": _FB_REGIME,
            "always_armed": sorted(_FB_ALWAYS)}


_ART = _load()
EDGE_OVERALL: dict[str, dict] = _ART["overall"]          # все известные типы (для membership-чека)
ALWAYS_ARMED: set[str] = set(_ART.get("always_armed", _FB_ALWAYS))


def direction_of(setup_type: str) -> str:
    return "SHORT" if setup_type.startswith("short_") else "LONG"


def edge_for(setup_type: str, regime_label: str | None) -> dict | None:
    """Статистика эджа если (тип,режим) ARMED, иначе None.
    always-armed типы отдаются в любом режиме. WATCH/dead → None."""
    base = EDGE_OVERALL.get(setup_type)
    if base is None:
        return None
    if setup_type in ALWAYS_ARMED:
        return {**base, "regime_pf": base["pf"], "regime": regime_label, "regime_known": False}
    cell = (_ART.get("regime_edge", {}).get(setup_type, {}) or {}).get(regime_label or "")
    if not cell or cell.get("tier") != "ARMED" or cell.get("pf", 0) <= MIN_REGIME_PF:
        return None
    return {**base, "regime_pf": cell["pf"], "regime_wr": cell.get("wr", base["wr"]),
            "regime_n": cell.get("n", base["n"]), "regime": regime_label, "regime_known": True}


def armed_setups_for_regime(regime_label: str | None) -> list[tuple[str, dict]]:
    """Все ARMED-сетапы для режима — для утреннего «План дня». Сорт по regime_pf."""
    out: list[tuple[str, dict]] = []
    for st in EDGE_OVERALL:
        e = edge_for(st, regime_label)
        if e is not None:
            out.append((st, e))
    out.sort(key=lambda x: -x[1].get("regime_pf", 0))
    return out


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
