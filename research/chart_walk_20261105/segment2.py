"""Участок 2 (BTC 06.03–05.05.2025). Сначала правила участка 1 БЕЗ изменений (записаны до просмотра этих данных), потом опции из записки 2.
Окна: A 15.02–15.03 (участок 1), B 15.03–05.05 (новое). Нога относится к окну по времени открытия. Прогон непрерывный 15.02–05.05."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import cw_data as cw  # noqa: E402
import rules  # noqa: E402

gridk = cw.gridk
OUT = cw.HERE / "out"
T0, TM, T1 = cw.T("2025-02-15"), cw.T("2025-03-15"), cw.T("2025-05-05")
pd.set_option("display.width", 250, "display.max_columns", 50, "display.max_rows", 200)

VARIANTS = [
    ("правила участка 1 без изменений", {}),
    ("+ цель с допуском 0.5%", {"tol": 0.5}),
    ("+ допуск, шорт от голубой до красной 1ч", {"tol": 0.5, "blue_tp_r1": True}),
    ("+ допуск, над голубыми без цели", {"tol": 0.5, "long_hold": True}),
    ("+ допуск, над голубыми без цели, лонг от сужения", {"tol": 0.5, "long_hold": True, "mirror_narrow": True}),
    ("+ то же, без «далеко»", {"tol": 0.5, "long_hold": True, "mirror_narrow": True, "far": False}),
    ("+ то же, далеко от красной −12% вместо зелёной", {"tol": 0.5, "long_hold": True, "mirror_narrow": True, "far_g": -99.0, "far_r": -12.0}),
    ("кагал: всё закрыть и ждать выхода", {"tol": 0.5, "long_hold": True, "knot": "flat"}),
    ("кагал: две сетки до выхода", {"tol": 0.5, "long_hold": True, "knot": "two"}),
]


def split(tbl):
    a = tbl[tbl["t0"] < TM]
    b = tbl[tbl["t0"] >= TM]
    return rules.summary(a), rules.summary(b), rules.summary(tbl)


def main():
    m, h1, h4, d1, fund = cw.load()
    mk = gridk.Market(m["ts"].to_numpy(), m["open"].to_numpy(), m["high"].to_numpy(), m["low"].to_numpy(), m["close"].to_numpy(), fund)
    a = rules.prepare(h1, h4)
    # сверка с автоматом участка 1
    old = pd.read_csv(OUT / "segment1_legs_далеко_закрывать.csv")
    new = rules.grid_legs(mk, rules.run(a, T0, TM), cw.utc)
    same = len(old) == len(new) and (old["сетка_$"].round(2).to_numpy() == new["сетка_$"].round(2).to_numpy()).all()
    print("сверка с segment1:", "совпало" if same else "РАСХОЖДЕНИЕ", len(old), len(new), round(float(old["сетка_$"].sum()), 2), round(float(new["сетка_$"].sum()), 2))
    res, rows = {}, []
    for nm, kw in VARIANTS:
        tbl = rules.grid_legs(mk, rules.run(a, T0, T1, **kw), cw.utc)
        tbl.to_csv(OUT / f"segment2_legs_{nm.replace(' ', '_').replace('«', '').replace('»', '').replace('%', '').replace(',', '').replace('−', '-')}.csv", index=False)
        sa, sb, sall = split(tbl)
        res[nm] = {"A": sa, "B": sb, "всё": sall}
        rows.append({"вариант": nm, "A_$": sa["итог_$"], "B_$": sb["итог_$"], "всё_$": sall["итог_$"], "просадка": sall["просадка_от_пика_$"], "ног": sall["ног"],
                     "B_шорт": sb["шорт_$"], "B_лонг": sb["лонг_$"], "B_две": sb["две_$"], "поз_$1000_B": sb.get("позиция_$1000_$", 0)})
    print(pd.DataFrame(rows).to_string(index=False))
    for nm in (VARIANTS[0][0], VARIANTS[1][0], VARIANTS[4][0]):
        tbl = rules.grid_legs(mk, rules.run(a, T0, T1, **dict(VARIANTS)[nm]), cw.utc)
        print("\n", nm)
        print(tbl[tbl["t1"] >= cw.T("2025-03-04")].drop(columns=["t0", "t1", "почему_открыта", "пик_номинал_$"]).to_string(index=False))
    base = {}
    for tag, (x, z) in (("A", (T0, TM)), ("B", (TM, T1)), ("всё", (T0, T1))):
        i0, i1 = mk.idx([x + 3600])[0], mk.idx([z])[0]
        base[tag] = {}
        for nm, side in (("лонг всё время", 1), ("шорт всё время", -1)):
            r = mk.run(np.array([i0]), np.array([i1]), side)[0]
            base[tag][nm] = {"итог_$": round(float(r[0]), 2), "просадка_$": round(float(r[6]), 2), "мешок_$": round(float(r[5]), 2)}
        for nm, col in (("перекладка по голубой 4ч", "B"), ("перекладка по зелёной 4ч", "G"), ("перекладка по жёлтой 4ч", "Y")):
            base[tag][nm] = rules.summary(rules.grid_legs(mk, rules.flips(h4, x, z, col), cw.utc))
    print(json.dumps(base, ensure_ascii=False, indent=0))
    res["контроли"] = base
    # сужения: серии ранга ≤ 0.30 и сторона голубых, 5 дней вперёд
    s = h4[(h4["known"] > T0) & (h4["known"] <= T1)]
    mask = (s["width_rank"] <= 0.30).to_numpy()
    pos = np.where(mask)[0]
    groups = np.split(pos, np.where(np.diff(pos) > 2)[0] + 1)
    knots = []
    for g in groups:
        f, l = g[0], g[-1]
        sub = s.iloc[f:l + 1]
        side = np.sign(((sub["close"] > sub["B"]) & (sub["close"] > sub["B1"])).astype(int) - ((sub["close"] < sub["B"]) & (sub["close"] < sub["B1"])).astype(int))
        after = h4[(h4["known"] > int(sub["known"].iloc[-1]))].iloc[:30]
        cl = float(sub["close"].iloc[-1])
        # первый выход за все линии после начала серии
        all_lines = h4[["G", "Y", "R", "B", "B1"]]
        w = h4[(h4["known"] > int(sub["known"].iloc[0])) & (h4["known"] <= int(sub["known"].iloc[-1]) + 30 * 14400)]
        over = w["close"] > all_lines.loc[w.index].max(axis=1)
        under = w["close"] < all_lines.loc[w.index].min(axis=1)
        first = None
        for kt, ov, un, px in zip(w["known"], over, under, w["close"]):
            if ov or un:
                first = (cw.utc(int(kt)), "вверх" if ov else "вниз", round(float(px)))
                break
        knots.append({"с": cw.utc(int(sub["known"].iloc[0])), "по": cw.utc(int(sub["known"].iloc[-1])), "баров": len(sub), "ранг_мин": round(float(sub["width_rank"].min()), 2),
                      "ширина_мин": round(float(sub["width"].min()), 2), "над_голубыми": int((side > 0).sum()), "под_голубыми": int((side < 0).sum()), "цена_конец": round(cl),
                      "5д_вверх_%": round((float(after["high"].max()) / cl - 1) * 100, 1), "5д_вниз_%": round((float(after["low"].min()) / cl - 1) * 100, 1),
                      "первый_выход": first})
    print(pd.DataFrame(knots).to_string(index=False))
    res["сужения"] = knots
    (OUT / "segment2.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
