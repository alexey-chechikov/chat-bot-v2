"""Где расходятся моя сетка и GinArea в годовом окне (13.11.2025–13.11.2026): история теста GinArea (statHistory —
позиция, входы, тейки, закрыто по точкам) против моей по тем же точкам. Гипотеза: на потолке 50 ордеров GinArea
ведёт себя иначе (у меня нижний лот крутится: тейк → снова вход на том же уровне)."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ga_compare as gc  # noqa: E402

recs = [json.loads(x) for x in (HERE / "ga_validate.jsonl").read_text(encoding="utf-8").splitlines()]
data = gc.load()
for r in recs:
    if not r["label"].startswith("год"):
        continue
    hist = r["hist"]
    print(f"\n{r['gs']}/{r['tog']}: точек истории {len(hist)}; поля: {sorted(hist[0].keys())[:12]}")
    ts = [h.get("updatedAt") for h in hist]
    print("метки времени:", ts[:2], "…", ts[-2:])
    pos = np.array([h["position"] for h in hist])
    ins = np.array([h["inFilledCount"] for h in hist])
    outs = np.array([h["outFilledCount"] for h in hist])
    prof = np.array([h["profit"] for h in hist])
    cap = pos >= 0.05 - 1e-9
    print(f"на потолке 0.05: {cap.mean():.0%} точек; входов за точки на потолке {np.diff(ins)[cap[1:]].sum()}, "
          f"тейков {np.diff(outs)[cap[1:]].sum()}; вне потолка входов {np.diff(ins)[~cap[1:]].sum()}, "
          f"тейков {np.diff(outs)[~cap[1:]].sum()}")
    # моя сетка: те же счётчики по равным долям окна (истории GinArea — равномерные точки по окну)
    a = int(datetime.fromisoformat(r["from"]).timestamp() * 1000)
    b = int(datetime.fromisoformat(r["to"]).timestamp() * 1000)
    edges = np.linspace(a, b, len(hist) + 1)[1:]
    mine = [gc.sim(data, a, int(e), r["gs"], r["tog"]) for e in edges[:: max(1, len(edges) // 12)]]
    ga_pts = hist[:: max(1, len(edges) // 12)]
    print("доля окна | GA позиция / мои · GA входов / мои · GA тейков / мои · GA закрыто / моё валовое")
    for k, (g, m) in enumerate(zip(ga_pts, mine)):
        print(f"  {k:2d} | {g['position']:.3f} / {m['позиция']:.3f} · {g['inFilledCount']} / {m['входов']} · "
              f"{g['outFilledCount']} / {m['тейков']} · {g['profit']:+.0f} / {m['закрыто']:+.0f}")
