"""Живая статистика SESSION BREAKOUT из журнала исходов.

Карточка два месяца печатала статичное «PF 1.85, WR 56% (N=1833 за 2y)»
как живой эдж — тот же паттерн мёртвой строки, что у PRE-CASCADE/GC
([[project-edge-gate]]). Аудит 2026-07-21 на 40 живых сигналах: WR 48%,
PF 1.21, +$19 брутто — ниже комиссий (~$60), нетто ≈ −$41. Живым
оказался только london_to_ny_am (13 сделок, WR 69%, +$26 нетто).

Все числа тут — НЕТТО (pnl_usd в журнале уже за вычетом тейкер-комиссий).
"""
from __future__ import annotations

import logging
from pathlib import Path

from services.session_breakout.journal import JOURNAL_PATH, read_all

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "state" / "session_breakout_config.json"
# оператор 2026-07-21: «оставляй лондон» — остальные переходы в тихий журнал
DEFAULT_TG_TRANSITIONS = ["london_to_ny_am"]


def tg_transitions() -> list[str]:
    """Переходы, которым разрешена TG-карточка. Остальные — молча в журнал."""
    import json
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return list(DEFAULT_TG_TRANSITIONS)
    except Exception:
        logger.exception("session_breakout.config_read_failed")
        return list(DEFAULT_TG_TRANSITIONS)
    val = cfg.get("tg_transitions")
    if val is None:
        return list(DEFAULT_TG_TRANSITIONS)
    if val == "all":
        return []          # пустой список = без фильтра
    return list(val)


def tg_allowed(transition: str) -> bool:
    allowed = tg_transitions()
    return not allowed or transition in allowed


def summarize(transition: str | None = None, *,
              path: Path = JOURNAL_PATH) -> dict:
    """{n, wr_pct, pf, total_usd} по закрытым сигналам (нетто)."""
    rows = [r for r in read_all(path=path)
            if r.get("exit_reason") and r.get("pnl_usd") is not None]
    if transition:
        rows = [r for r in rows if r.get("transition") == transition]
    n = len(rows)
    if not n:
        return {"n": 0, "wr_pct": None, "pf": None, "total_usd": 0.0}
    pnls = [float(r["pnl_usd"]) for r in rows]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    loss_sum = abs(sum(losses))
    maker = [float(r["pnl_maker_usd"]) for r in rows
             if r.get("pnl_maker_usd") is not None]
    # честная мейкер-симуляция: сделки, где лимитку РЕАЛЬНО налили
    real = [float(r["pnl_maker_real_usd"]) for r in rows
            if r.get("maker_filled") and r.get("pnl_maker_real_usd") is not None]
    n_eval = sum(1 for r in rows if r.get("maker_filled") is not None)
    return {
        "n": n,
        "wr_pct": round(len(wins) / n * 100, 0),
        "pf": round(sum(wins) / loss_sum, 2) if loss_sum else None,
        "total_usd": round(sum(pnls), 1),
        # «если бы те же сделки шли мейкером» — верхняя граница, риск
        # неисполнения лимитки не учтён
        "total_maker_usd": round(sum(maker), 1) if maker else None,
        "n_maker": len(maker),
        # честно: только реально налитые лимитки
        "n_maker_filled": len(real),
        "maker_fill_rate_pct": (round(len(real) / n_eval * 100, 0)
                                if n_eval else None),
        "total_maker_real_usd": round(sum(real), 1) if real else None,
        "maker_wr_pct": (round(sum(1 for p in real if p > 0) / len(real) * 100, 0)
                         if real else None),
    }


def live_line(transition: str, *, path: Path = JOURNAL_PATH) -> str:
    """Строка живого эджа для карточки — только собственные исходы."""
    s = summarize(transition, path=path)
    if not s["n"]:
        return f"📊 Живой эдж [{transition}]: данных пока нет (копим)"
    pf = f"PF {s['pf']}" if s["pf"] is not None else "PF —"
    return (f"📊 Живой эдж [{transition}]: WR {s['wr_pct']:.0f}%, {pf}, "
            f"{s['total_usd']:+.0f}$ нетто (n={s['n']}, свои сделки)")
