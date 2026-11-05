"""Шорт и лонг автомата v1 позициями по трём скринам оператора и по периодам истории: чтобы ответить, в минусе ли шорт."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import cw_data as cw  # noqa: E402
import history_v1 as hv  # noqa: E402
import pos  # noqa: E402
import rules  # noqa: E402

a, h1, h4, d1, fund = pos.load()
t_end = int(a["t"][-1])
d = hv.legs_frame(a, rules.run(a, hv.T0, t_end))
for nm, x, z in (("скрин 1, 15.02–15.03.2025", "2025-02-15", "2025-03-15"), ("скрин 2, 15.03–05.05.2025", "2025-03-15", "2025-05-05"), ("скрин 3, 05.05–15.05.2025", "2025-05-05", "2025-05-16"),
                 ("все три", "2025-02-15", "2025-05-16")):
    g = d[(d["t0"] >= cw.T(x)) & (d["t0"] < cw.T(z))]
    for s, lab in ((-1, "шорт"), (1, "лонг")):
        v = g.loc[g["s"] == s, "pnl"].to_numpy()
        print(nm, lab, "сделок", len(v), "сумма_%", round(float(v.sum()), 1) if len(v) else 0, "плюсовых", int((v > 0).sum()))
s = d[d["s"] == -1]
print("история шорт: сделок", len(s), pos.stats(s["pnl"].to_numpy()), {p: round(float(s.loc[s["per"] == p, "pnl"].sum()), 1) for p in pos.PER}, "просадка", pos.max_dd(s["pnl"].to_numpy()))
real = {p: float(s.loc[s["per"] == p, "pnl"].sum()) for p in pos.PER}
print(pos.rank_row(real, pos.control_fixed(a, s["i0"].to_numpy(), (s["i1"] - s["i0"]).to_numpy(), -1))["всё"])
l = d[d["s"] == 1]
print("история лонг: сделок", len(l), pos.stats(l["pnl"].to_numpy()), {p: round(float(l.loc[l["per"] == p, "pnl"].sum()), 1) for p in pos.PER})
