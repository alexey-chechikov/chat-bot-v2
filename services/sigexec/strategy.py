"""Нужная позиция по каждой стратегии на текущий час — из того же движка, что служба сигналов
(services/btc_signals/engine.py: simulate — система «Простое+, шорт под жёлтой, добор», simulate432 — 432).

Движок пересчитывает историю целиком: позиция «сейчас» не зависит от того, когда запущен исполнитель. Исполнитель
приводит биржу к этой позиции (вход, добор, цель, выход) и не решает ничего сам."""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

from services.btc_signals import engine as en

from . import lines

SYSTEM, Q432 = "system", "432"


@dataclass(frozen=True)
class Desired:
    slot: str
    entry_t: int          # закрытие часа сигнала входа (сек UTC) — номер эпизода
    side: int             # +1 лонг / −1 шорт
    tag: str
    w: float              # вес движка (доля базы)
    sig_px: float         # цена сигнала (закрытие 4ч)
    main_frac: float      # доля базы на первый лот
    add_lv: float | None  # уровень добора (стоп на бирже)
    add_frac: float
    add_done: bool        # движок уже засчитал добор
    target: float | None  # цель шорта под жёлтой на следующий час (лимитка reduceOnly)
    exit_by_t: int | None
    exit_text: str

    def to_dict(self) -> dict:
        return asdict(self)


def _system(pos: dict | None, a: dict) -> Desired | None:
    if not pos:
        return None
    main = pos["tag"] in en.MAIN
    target = None
    if pos["tag"] == en.CS:
        lv = float(a["f_B"][-1]) * en.CS_TOL   # B4p следующего часа = синяя последней закрытой 4ч
        target = lv if lv < pos["entry"] else None
    if pos["side"] == 1:
        ex = f"2 закрытия 4ч под красной ({a['f_R'][-1]:.0f})"
    elif pos["tag"] == en.CS:
        ex = f"2 закрытия 4ч над жёлтой ({a['f_Y'][-1]:.0f})"
    else:
        ex = f"2 закрытия 4ч над зелёной ({a['f_G'][-1]:.0f})"
    return Desired(slot=SYSTEM, entry_t=int(pos["entry_t"]), side=int(pos["side"]), tag=pos["tag"], w=float(pos["w"]), sig_px=float(pos["entry"]),
                   main_frac=float(pos["w"]) * (en.FIRST if main else 1.0), add_lv=float(pos["add_lv"]) if main else None,
                   add_frac=float(pos["w"]) * en.ADD if main else 0.0, add_done=bool(pos["add_done"]) if main else False,
                   target=target, exit_by_t=None, exit_text=ex)


def _q432(pos: dict | None, lv: dict) -> Desired | None:
    if not pos:
        return None
    return Desired(slot=Q432, entry_t=int(pos["entry_t"]), side=1, tag=en.TAG432, w=1.0, sig_px=float(pos["entry"]), main_frac=1.0, add_lv=None,
                   add_frac=0.0, add_done=False, target=None, exit_by_t=int(pos["exit_by_t"]),
                   exit_text=f"закрытие 4ч ниже {lv['next_lo30']:.0f} или по времени")


def evaluate(t, o, h, l, c, slots=(SYSTEM, Q432)) -> dict:
    """Часы (t — закрытие часа) → {"t": последний час, "desired": {слот: Desired|None}, "events": события последнего часа}."""
    a, lay = lines.build(t, o, h, l, c, i0_t=int(np.asarray(t)[0]))
    out = {"t": int(a["t"][-1]), "desired": {}, "events": [], "levels": {}}
    t_last = int(a["t"][-1])
    if SYSTEM in slots:
        ev, pos = en.simulate(a, lay)
        out["desired"][SYSTEM] = _system(pos, a)
        out["events"] += [_ev(e, SYSTEM) for e in ev if e["t"] == t_last]
        out["levels"][SYSTEM] = {"G": float(a["f_G"][-1]), "Y": float(a["f_Y"][-1]), "R": float(a["f_R"][-1]), "B": float(a["f_B"][-1])}
    if Q432 in slots:
        ev4, pos4, lv = en.simulate432(a)
        out["desired"][Q432] = _q432(pos4, lv)
        out["events"] += [_ev(e, Q432) for e in ev4 if e["t"] == t_last]
        out["levels"][Q432] = lv
    return out


def _ev(e: dict, slot: str) -> dict:
    return {"slot": slot, "kind": e["kind"], "t": int(e["t"]), "side": int(e["side"]), "tag": e["tag"], "px": float(e["px"]), "why": e.get("why"),
            "res": e.get("res"), "entry_t": int(e["pos"]["entry_t"])}
