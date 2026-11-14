"""Шаг 1 «сетки + система как страховка»: выгрузить события системы оператора и 432 (BTC, Binance 1h с 2017)."""
import json
import sys

sys.path.insert(0, "/Users/alexeychechikov/code/bot7")
from services.btc_signals import run  # noqa: E402

R = run.compute()
a = R["a"]
print("часов", len(a["t"]), "с", a["t"][0], "по", a["t"][-1])


def clean(e):
    out = {}
    for k, v in e.items():
        if k == "pos" and isinstance(v, dict):
            out["pos"] = {kk: (float(vv) if hasattr(vv, "__float__") and not isinstance(vv, (str, bool)) else vv)
                          for kk, vv in v.items() if isinstance(vv, (int, float, str, bool)) or hasattr(vv, "__float__")}
        elif isinstance(v, (int, float, str, bool)) or hasattr(v, "__float__"):
            out[k] = float(v) if hasattr(v, "__float__") and not isinstance(v, (str, bool, int)) else v
    return out


for name in ("ev", "ev432"):
    ev = [clean(e) for e in R[name]]
    print(name, len(ev), "пример:", json.dumps(ev[:3], ensure_ascii=False, default=str)[:900])
    with open(f"/Users/alexeychechikov/code/bot7/research/grid_hedge_20261114/{name}.json",
              "w", encoding="utf-8") as f:
        json.dump(ev, f, ensure_ascii=False, default=str)
print("pos now", json.dumps(R["pos"], ensure_ascii=False, default=str)[:400])
