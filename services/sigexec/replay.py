"""Прогон истории через исполнитель на имитаторе: каждый час — нужная позиция движка, бар следующего часа — в
имитатор (стопы, цель, добор срабатывают внутри бара). Итог исполнителя по сделкам сравнивается с итогом движка
(res × база). Это проверка связки «движок → исполнитель → биржа», а не новый бэктест: правила те же.

Позиция движка на часе i восстанавливается из событий полного прогона (движок причинный — служба сверяет журнал
с пересчётом). Тактика входа и выхода — рыночная (как допущение движка); лимитки меряет research/sigexec_20261112."""
from __future__ import annotations

from pathlib import Path

import numpy as np

from services.btc_signals import engine as en

from . import lines
from .exchange.sim import SimExchange
from .executor import Executor
from .strategy import Q432, SYSTEM, Desired, q432_window


def desired_by_hour(a: dict, ev: list[dict], ev432: list[dict], extra: list | None = None) -> tuple[dict, dict]:
    """→ ({слот: {час: (что, позиция)}}, {час: [события часа]}). extra — [(слот, события)] частей ансамбля окон 432."""
    out: dict[str, dict] = {}
    evs: dict[int, list] = {}
    for slot, E in [(SYSTEM, ev), (Q432, ev432)] + list(extra or []):
        cur = None
        add_done_i = None
        for e in E:
            evs.setdefault(e["i"], []).append({"slot": slot, "kind": e["kind"], "t": int(e["t"]), "entry_t": int(e["pos"]["entry_t"]), "px": float(e["px"]),
                                               "why": e.get("why"), "res": e.get("res")})
            if e["kind"] == "вход":
                cur, add_done_i = e, None
                out.setdefault(slot, {})[e["i"]] = ("open", e["pos"])
            elif e["kind"] == "добор":
                add_done_i = e["i"]
                out.setdefault(slot, {})[e["i"]] = ("add", e["pos"])
            elif e["kind"] == "выход":
                out.setdefault(slot, {})[e["i"]] = ("flat", None)
                cur = None
        _ = (cur, add_done_i)
    return out, evs


def to_desired(slot: str, p: dict | None, a: dict, i: int, n_parts: int = 1) -> Desired | None:
    if p is None:
        return None
    if q432_window(slot):
        return Desired(slot=slot, entry_t=int(p["entry_t"]), side=1, tag=en.TAG432, w=1.0, sig_px=float(p["entry"]),
                       main_frac=1.0 if slot == Q432 else 1.0 / n_parts, add_lv=None, add_frac=0.0,
                       add_done=False, target=None, exit_by_t=int(p["exit_by_t"]), exit_text="")
    main = p["tag"] in en.MAIN
    target = None
    if p["tag"] == en.CS:
        lv = float(a["f_B"][i]) * en.CS_TOL
        target = lv if lv < p["entry"] else None
    return Desired(slot=SYSTEM, entry_t=int(p["entry_t"]), side=int(p["side"]), tag=p["tag"], w=float(p["w"]), sig_px=float(p["entry"]),
                   main_frac=float(p["w"]) * (en.FIRST if main else 1.0), add_lv=float(p["add_lv"]) if main else None, add_frac=float(p["w"]) * en.ADD if main else 0.0,
                   add_done=bool(p["add_done"]) if main else False, target=target, exit_by_t=None, exit_text="")


FAULTS = (("place", "reject"), ("place", "unknown_placed"), ("place", "unknown_lost"), ("order", "incomplete"), ("order", "unknown_lost"),
          ("cancel", "unknown_lost"), ("cancel", "unknown_placed"), ("partial", ""))


def replay(t, o, h, l, c, t_from: int, workdir: Path, base: float = 1000.0, slots=(SYSTEM, Q432), chaos: float = 0.0, seed: int = 0,
           steps: int = 3, dt: float = 2.0) -> dict:
    """chaos — вероятность сбоя биржи перед каждым проходом (FAULTS); steps × dt — проходов и секунд внутри часа."""
    rng = np.random.default_rng(seed)
    a, lay = lines.build(t, o, h, l, c, i0_t=int(t[0]))
    ev, _ = en.simulate(a, lay)
    ev4, _, _ = en.simulate432(a)
    parts = [s for s in slots if s != Q432 and q432_window(s)]
    extra = [(s, en.simulate432(a, ch=q432_window(s))[0]) for s in parts]
    marks, evs = desired_by_hour(a, ev if SYSTEM in slots else [], ev4 if Q432 in slots else [], extra)
    i0 = int(np.searchsorted(a["t"], t_from))
    # позиция на старте окна
    state = {s: None for s in slots}
    for s in slots:
        for i in sorted(k for k in marks.get(s, {}) if k < i0):
            kind, p = marks[s][i]
            state[s] = None if kind == "flat" else p
    ex = SimExchange(price=float(a["c"][i0 - 1]), slip=0.0001)
    ex._t = float(a["t"][i0 - 1]) + 5
    cfg = {"enabled": True, "base_usd": base, "cap_usd": base * 10, "slots": list(slots), "max_signal_age_s": 1800, "entry": {"kind": "market"}, "exit": {"kind": "market"},
           "emergency_pct": 12.0}
    workdir.mkdir(parents=True, exist_ok=True)
    for f in ("st.json", "jr.jsonl"):
        (workdir / f).unlink(missing_ok=True)
    exe = Executor(ex, cfg, workdir / "st.json", workdir / "jr.jsonl")
    # эпизоды, открытые до окна, исполнитель не подхватывает (сигнал старый) — сравнение только по входам внутри окна
    for s in slots:
        if state[s]:
            exe.st["slots"][s]["done"].append(int(state[s]["entry_t"]))
    for i in range(i0, len(a["t"]) - 1):
        for s in slots:
            if i in marks.get(s, {}):
                kind, p = marks[s][i]
                state[s] = None if kind == "flat" else p
        desired = {s: to_desired(s, state[s], a, i, max(len(parts), 1)) for s in slots}
        ex._t = float(a["t"][i]) + 5
        ex.move(float(a["c"][i]))
        for k in range(steps):
            ex.faults.clear()                              # сбой действует только на следующий проход — без накопления в очереди
            ex._partial.clear()
            if chaos and rng.random() < chaos:             # сбой биржи перед проходом: отказ, потерянный ответ, неполный поиск, частичное
                op, mode = FAULTS[int(rng.integers(len(FAULTS)))]
                if op == "partial":
                    ex.partial_next(float(rng.uniform(0.2, 0.9)))
                else:
                    ex.fail_next(op, mode)
            exe.step(desired, evs.get(i, []) if k == 0 else [])
            ex.tick_clock(dt)
        nb = i + 1
        ex.bar(float(a["o"][nb]), float(a["h"][nb]), float(a["l"][nb]), float(a["c"][nb]))
    import json
    trades = [json.loads(x) for x in (workdir / "jr.jsonl").read_text().splitlines() if '"сделка"' in x]
    ok = lambda e: e["kind"] == "выход" and e["pos"]["entry_t"] >= t_from and e["t"] < a["t"][-1]  # noqa: E731
    eng = [e for e in ev + ev4 if ok(e)]
    by_slot = {SYSTEM: [e for e in ev if ok(e)], Q432: [e for e in ev4 if ok(e)], **{s: [e for e in E if ok(e)] for s, E in extra}}
    return {"trades": [x for x in trades if x["kind"] == "сделка"], "engine": eng, "engine_by_slot": by_slot, "parts": len(parts), "sim": ex, "exe": exe}
