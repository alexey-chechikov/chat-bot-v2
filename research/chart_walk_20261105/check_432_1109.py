"""09.11: (1) 432 службы (engine.simulate432 на frozen-минутках) против разбора btc_vs_432.s432 (часы spot Вина) — сделка в сделку;
(2) два контура исполнения для 432 (как maker_exec2: лимитка по закрытию 4ч, не исполнилась за k минут — рынок)."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("/Users/alexeychechikov/code/bot7")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))
import btc_vs_432 as bv  # noqa: E402
import lab_core as lc  # noqa: E402
import maker_exec2 as mx  # noqa: E402
import state_card as sc  # noqa: E402
from services.btc_signals import engine as en  # noqa: E402

pd.set_option("display.width", 220, "display.max_columns", 30)


def main():
    a, _, _ = sc.load_coin("BTC")
    ev, pos, lv = en.simulate432(a)
    mine = [(e["pos"]["entry_t"], e["t"], e["pos"]["entry"], e["px"], e["res"]) for e in ev if e["kind"] == "выход"]
    S = lc.load("BTC")
    ref = [(int(S.t[x[0]]), int(S.t[x[1]]), x[2], x[3]) for x in bv.s432(S) if x[7] == "выход"]
    r_ref = lc.nets(S, [x for x in bv.s432(S) if x[7] == "выход"])
    print(f"служба: сделок {len(mine)}, итог {sum(x[4] for x in mine):+.1f}; разбор: сделок {len(ref)}, итог {r_ref.sum():+.1f} (с фандингом)", flush=True)
    me = {x[0]: x for x in mine}
    rf = {x[0]: x for x in ref}
    both = sorted(set(me) & set(rf))
    only_me, only_ref = sorted(set(me) - set(rf)), sorted(set(rf) - set(me))
    same_exit = sum(me[k][1] == rf[k][1] for k in both)
    dpx = [abs(me[k][2] / rf[k][2] - 1) * 100 for k in both]
    print(f"совпали входы {len(both)}, из них выход в тот же час {same_exit}; только служба {len(only_me)}, только разбор {len(only_ref)}; расхождение цены входа медиана {np.median(dpx):.3f}%, макс {max(dpx):.3f}%", flush=True)
    for k in only_me[:10]:
        print("  только служба:", pd.Timestamp(k, unit="s"), me[k][2:], flush=True)
    for k in only_ref[:10]:
        print("  только разбор:", pd.Timestamp(k, unit="s"), rf[k][2:], flush=True)
    print("позиция 432 сейчас:", pos, "\nуровни:", lv, flush=True)

    M = mx.Mins(int(a["t"][a["i0"]]))
    t0 = int(M.ts[0])
    X = [e for e in ev if e["kind"] == "выход" and e["pos"]["entry_t"] >= t0]
    base = sum(e["res"] for e in X)
    rows = []
    for k in (1, 3, 5, 15, 60):
        for m in (0.0, 0.0002, 0.0005, 10.0):
            tot = t25 = 0.0
            fills = n = 0
            for e in X:
                p = e["pos"]
                q0, f0, ok0, _ = M.fill(p["entry_t"], True, p["entry"], k, m)
                q1, f1, ok1, _ = M.fill(e["t"], False, e["px"], k, m)
                v = mx.leg(1, q0, q1, f0, f1)
                tot += v
                t25 += v if p["entry_t"] >= mx.T25 else 0.0
                fills += ok0 + ok1
                n += 2
            rows.append({"ждём, мин": k, "сквозь, %": "никогда (всё рынок)" if m > 1 else m * 100, "исполнено %": round(fills / n * 100), "итог": round(tot, 1), "с 2025": round(t25, 1)})
    print(f"\n432, два контура (сделок {len(X)} с {pd.Timestamp(t0, unit='s'):%d.%m.%Y}, учёт по закрытию 4ч {base:+.1f}):", flush=True)
    print(pd.DataFrame(rows).to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
