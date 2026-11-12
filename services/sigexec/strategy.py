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
    boost: float = 1.0    # усиление 432: main_frac и add_frac уже умножены на него

    def to_dict(self) -> dict:
        return asdict(self)


def q432_long_at(ev432: list[dict], pos432: dict | None, t: int) -> bool:
    """432 в лонге на закрытии часа t: вошёл на этом закрытии или раньше и ещё не вышел (выход на t — уже не в лонге).
    Только по событиям не позже t — без заглядывания."""
    entry = None
    for e in ev432:
        if e["t"] > t:
            break
        if e["kind"] == "вход":
            entry = e["t"]
        elif e["kind"] == "выход":
            entry = None
    return entry is not None


def _system(pos: dict | None, a: dict, boost: float = 1.0) -> Desired | None:
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
                   main_frac=float(pos["w"]) * (en.FIRST if main else 1.0) * boost, add_lv=float(pos["add_lv"]) if main else None,
                   add_frac=float(pos["w"]) * en.ADD * boost if main else 0.0, add_done=bool(pos["add_done"]) if main else False,
                   target=target, exit_by_t=None, exit_text=ex, boost=boost)


def _q432(pos: dict | None, lv: dict, slot: str = Q432, frac: float = 1.0) -> Desired | None:
    if not pos:
        return None
    return Desired(slot=slot, entry_t=int(pos["entry_t"]), side=1, tag=en.TAG432 if slot == Q432 else f"432/{slot[4:]}", w=1.0, sig_px=float(pos["entry"]),
                   main_frac=frac, add_lv=None, add_frac=0.0, add_done=False, target=None, exit_by_t=int(pos["exit_by_t"]),
                   exit_text=f"закрытие 4ч ниже {lv['next_lo30']:.0f} или по времени")


def q432_window(slot: str) -> int | None:
    """«432» — окно автора 30; «432wNN» — часть ансамбля окон с окном NN свечей 4ч."""
    if slot == Q432:
        return en.CH432
    if slot.startswith("432w") and slot[4:].isdigit():
        return int(slot[4:])
    return None


def evaluate(t, o, h, l, c, slots=(SYSTEM, Q432), boost_432: float = 1.0) -> dict:
    """Часы (t — закрытие часа) → {"t": последний час, "desired": {слот: Desired|None}, "events": события последнего часа}.

    boost_432 (поручение оператора 12.11): если на закрытии 4ч входа системы 432 в лонге (вошёл тем же закрытием или раньше),
    целевой объём этого эпизода (первый лот и добор) × boost_432. 432 только лонг — шорты системы не усиливаются. Решение
    фиксируется по времени входа и не меняется до конца эпизода. Замер 12.11 (research/sigexec_20261112/NOTES.md): за
    2018–26 такие входы лучше прочих, за последние 2 года — хуже (9 сделок), поэтому по умолчанию 1.0 (выключено)."""
    if not (isinstance(boost_432, (int, float)) and 1.0 <= boost_432 <= 3.0):
        raise ValueError(f"boost_432 {boost_432!r}: допустимо 1.0–3.0")
    a, lay = lines.build(t, o, h, l, c, i0_t=int(np.asarray(t)[0]))
    out = {"t": int(a["t"][-1]), "desired": {}, "events": [], "levels": {}}
    t_last = int(a["t"][-1])
    ev4 = pos4 = lv = None
    if Q432 in slots or boost_432 != 1.0:
        ev4, pos4, lv = en.simulate432(a)
    if SYSTEM in slots:
        ev, pos = en.simulate(a, lay)
        boost = boost_432 if (pos and pos["side"] == 1 and boost_432 != 1.0 and q432_long_at(ev4, pos4, int(pos["entry_t"]))) else 1.0
        out["desired"][SYSTEM] = _system(pos, a, boost)
        out["events"] += [_ev(e, SYSTEM) for e in ev if e["t"] == t_last]
        out["levels"][SYSTEM] = {"G": float(a["f_G"][-1]), "Y": float(a["f_Y"][-1]), "R": float(a["f_R"][-1]), "B": float(a["f_B"][-1])}
    if Q432 in slots:
        out["desired"][Q432] = _q432(pos4, lv)
        out["events"] += [_ev(e, Q432) for e in ev4 if e["t"] == t_last]
        out["levels"][Q432] = lv
    # ансамбль окон 432 (оператор 12.11 «да»; research/sigexec_20261112 §6б): каждое окно — своя часть 1/N базы, свой эпизод
    wins = [s for s in slots if s != Q432 and q432_window(s)]
    for s in wins:
        ew, pw, lw = en.simulate432(a, ch=q432_window(s))
        out["desired"][s] = _q432(pw, lw, slot=s, frac=1.0 / len(wins))
        out["events"] += [_ev(e, s) for e in ew if e["t"] == t_last]
        out["levels"][s] = lw
    return out


ENSEMBLE_432 = tuple(f"432w{w}" for w in (20, 25, 30, 35, 40, 45))   # окна 20–45 шаг 5 — выбор §6б


def _ev(e: dict, slot: str) -> dict:
    return {"slot": slot, "kind": e["kind"], "t": int(e["t"]), "side": int(e["side"]), "tag": e["tag"], "px": float(e["px"]), "why": e.get("why"),
            "res": e.get("res"), "entry_t": int(e["pos"]["entry_t"])}
