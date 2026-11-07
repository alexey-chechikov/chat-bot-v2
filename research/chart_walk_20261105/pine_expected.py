"""Сверка индикатора TradingView с автоматом: ожидаемые сделки Binance spot 1ч при настройках индикатора, без фандинга, только закрытые. Запуск: python pine_expected.py [BTC|ETH] [с какой даты] [с какой даты начинать автомат]."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import ledger as lg  # noqa: E402
import pos  # noqa: E402
import state_card as sc  # noqa: E402
import state_map as sm  # noqa: E402
import words2 as w2  # noqa: E402

pd.set_option("display.width", 220, "display.max_columns", 30, "display.max_rows", 100)
CFGS = {"по умолчанию: A + шорт 2/6": w2.MAIN26, "только A": w2.MAIN, "A + 2/6 + X01": {**w2.MAIN26, "xl": True, "x01_all": "add"}}


def table(a, legs, frm, half=True):
    t = a["t"]
    rows = []
    for i0, i1, p0, p1, s, tag, why in legs:
        if t[i0] < frm:
            continue
        net = s * (p1 / p0 - 1) * 100 - lg.SIDE_COST * 100 - lg.SIDE_COST * 100 * (p1 / p0)
        w = 0.5 if half and s == 1 and not w2.in_portrait(a, i0, 1) else 1.0
        rows.append({"вход": sm.utc(t[i0]), "выход": sm.utc(t[i1]), "сторона": "L" if s == 1 else "S", "тип": tag, "причина": why, "p0": round(p0, 2), "p1": round(p1, 2), "net": round(net, 2), "вес": w, "в_итог": net * w})
    return pd.DataFrame(rows)


def main():
    coin = sys.argv[1] if len(sys.argv) > 1 else "BTC"
    frm = sm.T(sys.argv[2] if len(sys.argv) > 2 else "2025-01-01")
    a, fm, h4 = sc.load_coin(coin)
    if len(sys.argv) > 3:
        a["i0"] = int(np.searchsorted(a["t"], sm.T(sys.argv[3])))
    for lab, kw in CFGS.items():
        st = {}
        legs = w2.run(a, **kw, stop_at=len(a["t"]) - 1, out=st)
        d = table(a, legs, frm)
        print(f"{coin} {lab}: закрытых {len(d)}, итог {d['в_итог'].sum():+.1f}%, лонг {d.loc[d['сторона'] == 'L', 'в_итог'].sum():+.1f}, шорт {d.loc[d['сторона'] == 'S', 'в_итог'].sum():+.1f}; открыта: {st['cur'][3] if st['cur'] else 'нет'}", flush=True)
        if lab.startswith("по умолчанию"):
            print(d.drop(columns="в_итог").tail(12).to_string(index=False), flush=True)
            d.drop(columns="в_итог").to_csv(pos.OUT / f"pine_expected_{coin}.csv", index=False)


if __name__ == "__main__":
    main()
