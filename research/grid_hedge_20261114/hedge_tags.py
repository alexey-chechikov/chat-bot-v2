"""Шаг 6 (14.11): какие шорты системы нести в страховку — на исправленной механике (overlay2, «от всего», k=1, сетки ×1).

ПРАВИЛА (до прогона): A — оба тега (как сейчас); B — только «под синей»; C — только «под жёлтой»; D — оба тега, но
шорт держится до следующего ВХОДА системы в лонг (а не до выхода из шорта). Метрики против сеток без страховки:
прибавка итога, изменение просадки — вся история, 3 года, 2 года. Контроль — те же сделки, 999 круговых сдвигов
(≥30 сут), ранг (k+1)/(n+1)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import overlay2 as o2  # noqa: E402

T, n, EQ = o2.T, o2.n, o2.EQ
y3, y2 = o2.y3, o2.y2
rows = o2._Rows(T)
ev = json.load(open(HERE / "ev.json", encoding="utf-8"))


def trades(tags, hold_to_long=False):
    out, cur = [], None
    longs = sorted(i for i in (rows.get(int(e["t"])) for e in ev if e.get("side") == 1 and e["kind"] == "вход") if i is not None)
    for e in ev:
        if e.get("side") != -1 or e.get("tag") not in tags:
            continue
        i = rows.get(int(e["t"]))
        if i is None:
            continue
        if e["kind"] == "вход":
            cur = [i, None, None]
        elif e["kind"] == "добор" and cur:
            cur[1] = i
        elif e["kind"] == "выход" and cur:
            x = i
            if hold_to_long:
                j = int(np.searchsorted(longs, i))
                x = longs[j] if j < len(longs) else n - 1
            cur[2] = max(x, cur[0] + 1)
            out.append(tuple(cur))
            cur = None
    if cur:
        out.append((cur[0], cur[1], n - 1))
    # «держать до лонга» может перекрыть следующий шорт — пересечения сливаются (позиция не удваивается)
    out.sort()
    merged = []
    for a, b, x in out:
        if merged and a < merged[-1][2]:
            pa, pb, px = merged[-1]
            merged[-1] = (pa, pb, max(px, x))
        else:
            merged.append((a, b, x))
    return merged


def met(tt):
    return {"итог": tt[-1] - EQ[-1], "просадка": o2.dd(tt) - o2.dd(EQ),
            "3 года итог": (tt[-1] - tt[y3]) - (EQ[-1] - EQ[y3]), "3 года просадка": o2.dd(tt[y3:]) - o2.dd(EQ[y3:]),
            "2 года итог": (tt[-1] - tt[y2]) - (EQ[-1] - EQ[y2])}


def main():
    rng = np.random.default_rng(20261114)
    shifts = rng.integers(30 * 24, n - 30 * 24, 999)
    variants = (("A оба тега (сейчас)", ("под синей", "под жёлтой"), False), ("B только под синей", ("под синей",), False),
                ("C только под жёлтой", ("под жёлтой",), False), ("D оба, держать до входа в лонг", ("под синей", "под жёлтой"), True))
    for name, tags, hold in variants:
        o2.TR = trades(tags, hold)
        real, hq = o2.total(1.0, "всё")
        m = met(real)
        ctrl = [met(o2.total(1.0, "всё", 1.0, int(s))[0]) for s in shifts]
        print(f"\n{name}: сделок {len(o2.TR)}, в шорте {(hq > 0).mean():.0%} часов")
        for key, v in m.items():
            arr = np.array([c[key] for c in ctrl])
            rank = (np.sum(arr >= v) + 1) / (len(arr) + 1)
            print(f"   {key:16s} {v:+9,.0f}$ · случайные: медиана {np.median(arr):+9,.0f}$ · ранг {rank:.3f}", flush=True)


if __name__ == "__main__":
    main()
