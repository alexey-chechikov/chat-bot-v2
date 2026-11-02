"""Окна «флета» оператора: две сетки 0.6/1.4 ($100 ордер, $3 000 + $3 000), полный капитал, издержки живые.
(а) всегда обе в окне; (б) по правилу F1 (зона 4H = 0 и spread < 0.6) внутри окна; (в) лонг и шорт отдельно.
Окна: 16.06–02.07 (контрпример GPT), 02.07–16.08 (его «идеально для двух сеток»), 08.10–29.10 (у синей ~82k).
Описание отдельных окон в выборке — не проверка правила (её делает regime_rules.py)."""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import gridk  # noqa: E402
import mr_data as md  # noqa: E402
from regime_rules import runs  # noqa: E402

T = lambda s: int(pd.Timestamp(s, tz="UTC").timestamp())  # noqa: E731


def main():
    m, h1, h4, d1, fund = md.build()
    mk = gridk.Market(m["ts"].to_numpy(), m["open"].to_numpy(), m["high"].to_numpy(), m["low"].to_numpy(),
                      m["close"].to_numpy(), fund)
    k4 = h4["known"].to_numpy()
    f1 = (h4["zone"].to_numpy() == 0) & (h4["spread"].to_numpy() < 0.6)
    eps = runs(k4, f1, int(m["ts"].iloc[-1]) + 60)
    out = {}
    for nm, a, b in (("16.06–02.07", "2026-06-16", "2026-07-02"), ("02.07–16.08", "2026-07-02", "2026-08-16"),
                     ("08.10–29.10", "2026-10-08", "2026-10-29")):
        ta, tb = T(a), T(b)
        L = mk.run(mk.idx([ta]), mk.idx([tb]), 1, cap=3000.0)[0]
        S = mk.run(mk.idx([ta]), mk.idx([tb]), -1, cap=3000.0)[0]
        sub = [(max(x, ta), min(y, tb)) for x, y in eps if y > ta and x < tb]
        if sub:
            i0, i1 = mk.idx([x for x, _ in sub]), mk.idx([y for _, y in sub])
            fl = mk.run(i0, i1, 1, cap=3000.0)[:, 0].sum() + mk.run(i0, i1, -1, cap=3000.0)[:, 0].sum()
            hrs = sum(y - x for x, y in sub) / 3600
        else:
            fl, hrs = 0.0, 0.0
        out[nm] = {"всегда обе": round(float(L[0] + S[0]), 1), "лонг": round(float(L[0]), 1),
                   "шорт": round(float(S[0]), 1), "мешок лонга": round(float(L[5]), 1),
                   "мешок шорта": round(float(S[5]), 1), "тейки лонг+шорт": round(float(L[1] + S[1]), 1),
                   "по F1": round(float(fl), 1), "F1 эпизодов": len(sub), "F1 часов": round(hrs)}
        print(nm, json.dumps(out[nm], ensure_ascii=False))
    (HERE / "out" / "flat_windows_result.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
