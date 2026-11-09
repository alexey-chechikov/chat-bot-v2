"""Сборка только по биткоину из того, что выжило: синяя EMA200 или EMA150; выход лонга 2 или 1 закрытие под красной; выход шорта над зелёной (2) или над TEMA75 (2 или 3); шорт под жёлтой вес 1; фандинг для основного шорта от 0.5; добор 0.5+0.5 на +2 ATR. Всего 2×2×3×2×2×2 = 96 сочетаний, все на слое Простое+. Данные и движок линий Вина, логика потока своя.
Мера: итог/просадка в 2018–22 и 2023–07.11.2026, Bitstamp 2014–17 (фандинга там нет). Для каждого выключателя — средняя прибавка по всем сочетаниям в каждой части: так видно, что добавляет само, а не в удачной связке."""
from __future__ import annotations

import itertools
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

WIN = Path("/private/tmp/claude-501/-Users-alexeychechikov/279942d8-034f-4a29-bc43-ed7d07642e98/scratchpad/win/research/indicator_lab_win")
os.environ["LAB_DATA"] = str(WIN.parent.parent / "data")
sys.path.insert(0, str(WIN))
import candidate as cd  # noqa: E402
import lab_core as lc  # noqa: E402

pd.set_option("display.width", 240, "display.max_columns", 30, "display.max_rows", 120, "display.max_colwidth", 60)
OUT = Path(__file__).parent / "out"
CUT = lc.T("2023-01-01")
G, Y, R = lc.G, lc.Y, lc.R
T75 = ("T", 75)


def fund_rank(S):
    if "frk" not in S.cache:
        fs = pd.Series(S.fund_rate.to_numpy(float))
        rk = fs.rolling(9, min_periods=3).mean().rolling(1096, min_periods=270).rank(pct=True).to_numpy()
        idx = np.searchsorted(S.fund_rate.index.to_numpy(np.int64), S.t, side="right") - 1
        S.cache["frk"] = np.where(idx >= 0, rk[np.clip(idx, 0, None)], np.nan)
    return S.cache["frk"]


def run(S, reg, klx, sx, ksx, cs, fund, cut=None, lok=None, sok=None):
    """lok, sok: булевы массивы по барам 4ч — разрешён ли основной лонг и основной шорт (внешние данные). None — без фильтра."""
    t, o, h, l, c, j, is4 = S.t, S.o, S.h, S.l, S.c, S.j, S.is4
    F = S.h4["c"]
    Bv = S.line4(reg)
    rG, rY, rR, rS = S.run4(G), S.run4(Y), S.run4(R), S.run4(sx)
    rk = cd.atr_rank(S, 365, 100)
    W = cd.weights(S, 100, 365, 0.5, 2.0) / 1.18
    jp = np.clip(np.searchsorted(S.h4["known"], t - 3600, side="right") - 1, 0, None)
    Bp = Bv[jp]
    fr = fund_rank(S) if fund is not None else None
    legs, side, ie, pe, we, tag = [], 0, -1, 0.0, 1.0, ""

    def close(i, px, why):
        nonlocal side, tag
        legs.append((ie, i, pe, float(px), side, we, tag, why))
        side, tag = 0, ""

    for i in range(S.i0, len(t)):
        q = j[i]
        if side == -1 and tag == "cs":
            lv = Bp[i] * 1.005
            if l[i] <= lv < pe:
                close(i, min(lv, o[i]), "цель")
        if not is4[i]:
            continue
        if side == 1 and rR[q] <= -klx:
            close(i, c[i], "выход")
        elif side == -1 and tag == "S" and rS[q] >= ksx:
            close(i, c[i], "выход")
        elif side == -1 and tag == "cs" and rY[q] >= 2:
            close(i, c[i], "отмена")
        if side != 0:
            continue
        if F[q] > Bv[q]:
            if rG[q] >= 2 and rR[q] > -klx and (lok is None or lok[q]):
                side, ie, pe, we, tag = 1, i, float(c[i]), float(W[q]), "L"
            elif cs and rY[q] == -2 and c[i] > Bv[q] * 1.005:
                side, ie, pe, we, tag = -1, i, float(c[i]), float(W[q]), "cs"
        elif rG[q] <= -2 and rS[q] < ksx and not rk[q] > 0.6 and (fr is None or not fr[i] < fund) and (sok is None or sok[q]):
            side, ie, pe, we, tag = -1, i, float(c[i]), float(W[q]), "S"
    if side != 0:
        close(len(t) - 1, c[-1], "конец")
    return legs


def pyramid(S, legs, x=2.0, first=0.5, add=0.5):
    h, l, o, j = S.h, S.l, S.o, S.j
    atr = S.atr4()
    out = []
    for z in legs:
        i0, i1, p0, p1, s, w, tag, why = z
        if tag == "cs":
            out.append(z)
            continue
        out.append((i0, i1, p0, p1, s, w * first, tag, why))
        lv = p0 + s * x * atr[j[i0]]
        rng = np.arange(i0 + 1, i1)
        if len(rng):
            hit = (h[rng] >= lv) if s == 1 else (l[rng] <= lv)
            if hit.any():
                k = int(rng[int(np.argmax(hit))])
                out.append((k, i1, float(max(lv, o[k]) if s == 1 else min(lv, o[k])), p1, s, w * add, tag + " добор", why))
    return out


def seg(eq, x, y):
    e = eq[x:y + 1] - eq[x]
    d = float((e - np.maximum.accumulate(e)).min())
    return round(float(e[-1]), 1), round(d, 1), round(float(e[-1]) / max(abs(d), 1.0), 2)


def measure(S, Bs, kw, pyr):
    la = run(S, **kw)
    lb = run(Bs, **{**kw, "fund": None})
    if pyr:
        la, lb = pyramid(S, la), pyramid(Bs, lb)
    eq = lc.equity(S, la)
    k = int(np.searchsorted(S.t, CUT))
    n = len(S.t) - 1
    a, p1, p2 = seg(eq, S.i0, n), seg(eq, S.i0, k), seg(eq, k, n)
    r = lc.nets(S, la)
    t0 = S.t[np.array([x[0] for x in la])]
    b = seg(lc.equity(Bs, lb), Bs.i0, len(Bs.t) - 1)
    return {"итог": a[0], "просадка": a[1], "отн": a[2], "с2025": round(float(r[t0 >= lc.CUT25].sum()), 1), "итог1": p1[0], "отн1": p1[2], "итог2": p2[0], "пр2": p2[1], "отн2": p2[2], "Bs": b[0], "Bs_пр": b[1], "Bs_отн": b[2]}


def main():
    S, Bs = lc.load("BTC"), lc.load("Bitstamp")
    rows = []
    SX = {"над G, 2": (G, 2), "над T75, 2": (T75, 2), "над T75, 3": (T75, 3)}
    for bb, klx, sxn, cs, fund, pyr in itertools.product(("E200", "E150"), (2, 1), SX, (False, True), (None, 0.5), (False, True)):
        kw = dict(reg=("E", int(bb[1:])), klx=klx, sx=SX[sxn][0], ksx=SX[sxn][1], cs=cs, fund=fund)
        rows.append({"синяя": bb, "лонг_закрытий": klx, "выход_шорта": sxn, "шорт_под_Y": cs, "фандинг": fund is not None, "добор": pyr, **measure(S, Bs, kw, pyr)})
    d = pd.DataFrame(rows)
    d.to_csv(OUT / "btc_combo.csv", index=False)
    show = ["синяя", "лонг_закрытий", "выход_шорта", "шорт_под_Y", "фандинг", "добор", "итог", "просадка", "отн", "с2025", "отн1", "отн2", "итог2", "пр2", "Bs", "Bs_отн"]
    base = d[(d["синяя"] == "E200") & (d["лонг_закрытий"] == 2) & (d["выход_шорта"] == "над G, 2") & (~d["шорт_под_Y"]) & (~d["фандинг"]) & (~d["добор"])]
    print("== Простое+", flush=True)
    print(base[show].to_string(index=False), flush=True)
    print("== лучшие 10 по итог/просадка в 2018–22; что они дали потом", flush=True)
    print(d.sort_values("отн1", ascending=False).head(10)[show].to_string(index=False), flush=True)
    print("== лучшие 8 по меньшей из двух частей", flush=True)
    d["мин"] = d[["отн1", "отн2"]].min(axis=1)
    print(d.sort_values("мин", ascending=False).head(8)[show].to_string(index=False), flush=True)
    print("== что добавляет каждый выключатель сам: средняя разница по всем сочетаниям", flush=True)
    rows = []
    for col, a_, b_ in (("синяя", "E150", "E200"), ("лонг_закрытий", 1, 2), ("выход_шорта", "над T75, 2", "над G, 2"), ("выход_шорта", "над T75, 3", "над G, 2"), ("шорт_под_Y", True, False), ("фандинг", True, False), ("добор", True, False)):
        x, y = d[d[col] == a_], d[d[col] == b_]
        keys = [c for c in ("синяя", "лонг_закрытий", "выход_шорта", "шорт_под_Y", "фандинг", "добор") if c != col]
        m = x.merge(y, on=keys, suffixes=("_a", "_b"))
        rows.append({"что": f"{col}: {a_} против {b_}", "сочетаний": len(m), "итог": round((m["итог_a"] - m["итог_b"]).mean(), 1), "просадка": round((m["просадка_a"] - m["просадка_b"]).mean(), 1), "отн1": round((m["отн1_a"] - m["отн1_b"]).mean(), 2), "отн2": round((m["отн2_a"] - m["отн2_b"]).mean(), 2), "Bs_отн": round((m["Bs_отн_a"] - m["Bs_отн_b"]).mean(), 2), "лучше_в_обеих_%": round(float(((m["отн1_a"] > m["отн1_b"]) & (m["отн2_a"] > m["отн2_b"])).mean() * 100))})
    print(pd.DataFrame(rows).to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
