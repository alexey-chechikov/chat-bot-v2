"""Слова оператора целиком: один автомат, все сделки из записок 1–3, без фильтров и отбора. Сделки не выбрасываются: каждый сигнал исполняется.
Закрепление: 4ч — 2 закрытия подряд, 1ч — 3 закрытия подряд. Цель «голубая 4ч» с запасом 0.5% (его 0.39% и 0.47%, позже можно менять только выход).

Под голубой 4ч:
  лонг «к голубой»: 4ч над зелёной и жёлтой, 3 закрытия 1ч над красной. Цель — голубая 4ч минус запас. Не дошли: 4ч под зелёной и жёлтой и 3 закрытия 1ч под красной — перекладка в шорт;
  шорт «от голубой»: после цели лонга первое закрытие 4ч под голубой, стоп — закрытие 4ч над ней, после закрытия под зелёной стоп как у остальных шортов;
  шорт «под голубой»: 4ч под зелёной, жёлтой и обеими голубыми («закрепились под голубой, приоритет шорт»);
  шорт закрывается «далеко» (−5% от зелёной), «снова шорт» — возврат ближе 1% под зелёную без закрытия над ней; закрытие над зелёной — не добирать;
  выход шорта: 4ч над зелёной и жёлтой и 3 закрытия 1ч над красной — перекладка в лонг.
Над голубой 4ч:
  лонг «над голубыми»: над обеими голубыми, зелёная > жёлтая > красная, цена над зелёной и жёлтой. Выход — 2 закрытия 4ч под жёлтой;
  лонг «снова над жёлтой»: первое закрытие 4ч над жёлтой над обеими голубыми. Выход — 2 закрытия 4ч под красной;
  шорт «над голубыми»: 2 закрытия 4ч под красной. Выход — закрытие 4ч над зелёной и 3 закрытия 1ч над голубой 1ч.
Сужение в автомат не входит: в записке два взаимоисключающих варианта, оператор выбор не сделал."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import cw_data as cw  # noqa: E402
import gpt_check as gc  # noqa: E402
import ledger as lg  # noqa: E402
import pos  # noqa: E402

pd.set_option("display.width", 260, "display.max_columns", 40, "display.max_rows", 200)
DEF = dict(k4=2, k1=3, far_g=-5.0, far_b=-10.0, near_g=-1.0, tol=0.5, knot=None, event_short=True)
PER_BS = {"2014": (cw.T("2014-01-01"), cw.T("2015-01-01")), "2015": (cw.T("2015-01-01"), cw.T("2016-01-01")), "2016": (cw.T("2016-01-01"), cw.T("2017-01-01")), "2017": (cw.T("2017-01-01"), cw.T("2018-01-01"))}
PER_X = {"2020–21": (cw.T("2020-07-01"), cw.T("2022-01-01")), "2022–07.24": (cw.T("2022-01-01"), cw.T("2024-08-01")), "08.24–26": (cw.T("2024-08-01"), cw.T("2030-01-01"))}
# Что оператор назвал в записках: (закрытие UTC, действие). L/S — открыть, xL/xS — закрыть
MARKS = [("2025-02-24 16:00", "S", "под зелёной, держать"), ("2025-02-25 08:00", "xS", "далеко, закрыть"), ("2025-02-27 12:00", "S", "возврат к зелёной, снова шорт"), ("2025-02-28 08:00", "xS", "далеко, закрыть"),
         ("2025-03-01 20:00", "L", "над жёлтой и красной 1ч"), ("2025-03-02 18:00", "xL", "цель голубая 4ч"), ("2025-03-03 04:00", "S", "шорт от голубой"), ("2025-03-06 06:00", "xL", "отбитие от голубой, 93 400"),
         ("2025-03-10 00:00", "xS", "далеко, закрыть"), ("2025-03-11 20:00", "L", "над красной 1ч и жёлтой 4ч"), ("2025-03-20 01:00", "xL", "лонг до голубой"), ("2025-03-28 08:00", "S", "закрепились под голубой"),
         ("2025-04-01 16:00", "L", "над жёлтой, цель голубая"), ("2025-04-02 16:00", "xL", "цель голубая"), ("2025-04-09 20:00", "L", "лонг, цель голубая на 83"), ("2025-04-11 18:00", "xL", "цель голубая на 83"),
         ("2025-04-12 16:00", "L", "пересекли голубую, цветные вверх"), ("2025-04-21 04:00", "L", "над голубыми, закрепление"), ("2025-04-27 08:00", "xL", "закрепились под жёлтой"), ("2025-05-04 04:00", "S", "закрепились под красной"),
         ("2025-05-06 20:00", "xS", "над зелёной и голубой 1ч"), ("2025-05-08 04:00", "L", "опять над жёлтой"), ("2025-05-12 20:00", "xL", "закрепились под красной")]


def add_runs(a):
    """Закрытий 4ч подряд за линией, только из почасовых столбцов (работает и на кэше XRP)."""
    ju, first = np.unique(a["j"], return_index=True)
    pos4 = np.searchsorted(ju, a["j"])
    for name, col in (("f_run_R", "f_R"), ("f_run_G", "f_G"), ("f_run_Y", "f_Y"), ("f_run_B", "f_B")):
        a[name] = cw.run_len(np.sign((a["f_close"][first] - a[col][first])))[pos4]
    return a


def run(a, **kw):
    """→ сделки (i0, i1, p0, p1, сторона, тип, причина). Цена входа и выхода — закрытие часа сигнала, цель — уровень или открытие часа."""
    P = {**DEF, **kw}
    t, c, h, o, j = a["t"], a["c"], a["h"], a["o"], a["j"]
    legs, cur, covered, await_blue, in_knot, jp = [], None, False, False, False, -1

    def close(i, px, why):
        legs.append((cur[0], i, cur[1], float(px), cur[2], cur[3], why))

    def opn(i, s, tag):
        return [i, float(c[i]), s, tag]

    for i in range(a["i0"], len(t)):
        new4 = j[i] != jp
        jp = j[i]
        fc, g, y, b, b1 = a["f_close"][i], a["f_G"][i], a["f_Y"][i], a["f_B"][i], a["f_B1"][i]
        over_gy, under_gy = fc > g and fc > y, fc < g and fc < y
        r_over, r_under = a["run_R"][i] >= P["k1"], a["run_R"][i] <= -P["k1"]
        over_bl, under_bl = fc > b and fc > b1, fc < b and fc < b1
        d_g, d_b = a["f_d_G"][i], a["f_d_B"][i]
        ry, rr, rg = a["f_run_Y"][i], a["f_run_R"][i], a["f_run_G"][i]
        if P["knot"] is not None:
            over_all, under_all = fc > max(g, y, a["f_R"][i], b, b1), fc < min(g, y, a["f_R"][i], b, b1)
            if in_knot:
                if new4 and (over_all or under_all):
                    cur = opn(i, 1 if over_all else -1, "над голубыми" if over_all else "под голубой")
                    in_knot = False
                continue
            if new4 and a["f_width_rank"][i] <= P["knot"] and not over_all and not under_all:
                if cur is not None:
                    close(i, c[i], "сужение: закрыть и ждать")
                    cur = None
                in_knot, covered, await_blue = True, False, False
                continue
        if cur is not None and cur[2] == 1:
            tag = cur[3]
            if tag == "к голубой":
                lvl = a["B4p"][i] * (1 - P["tol"] / 100)
                if h[i] >= lvl and cur[1] < lvl:
                    close(i, max(lvl, o[i]), "цель")
                    cur, await_blue = None, True
                    continue
                if under_gy and r_under:
                    close(i, c[i], "под G+Y, 1ч под R")
                    cur = opn(i, -1, "перекладка")
                    continue
            elif tag == "над голубыми" and new4 and ry <= -P["k4"]:
                close(i, c[i], "2 закрытия под жёлтой")
                cur = None
            elif tag == "снова над жёлтой" and new4 and rr <= -P["k4"]:
                close(i, c[i], "2 закрытия под красной")
                cur = None
        elif cur is not None:
            tag = cur[3]
            if tag == "от голубой" and new4 and fc > b:
                close(i, c[i], "стоп над голубой")
                cur, await_blue = None, True
                continue
            if tag == "от голубой" and fc < g:
                cur[3] = tag = "от голубой, под зелёной"
            if tag.startswith("от голубой") and new4 and (d_g <= P["far_g"] or d_b <= P["far_b"]):
                close(i, c[i], "далеко")
                cur, covered = None, True
                continue
            if tag in ("под голубой", "перекладка", "снова шорт", "от голубой, под зелёной"):
                if new4 and d_g <= P["far_g"]:
                    close(i, c[i], "далеко")
                    cur, covered = None, True
                    continue
                if over_gy and r_over:
                    close(i, c[i], "над G+Y, 1ч над R")
                    cur = opn(i, 1, "к голубой" if fc < b else "над голубыми")
                    continue
            if tag == "над голубыми" and new4 and rg >= 1 and a["run_B1"][i] >= P["k1"]:
                close(i, c[i], "над зелёной и голубой 1ч")
                cur = None
        if cur is not None:
            continue
        if await_blue:
            if new4 and fc < b:
                cur, await_blue = opn(i, -1, "от голубой"), False
                continue
            if new4 and (a["f_a_B"][i] > 1 or (over_bl and a["f_stack"][i] == 1 and over_gy)):
                await_blue = False
            else:
                continue
        if fc < b:
            if over_gy and r_over:
                cur, covered = opn(i, 1, "к голубой"), False
            elif new4 and covered and fc < g and d_g > P["near_g"]:
                cur, covered = opn(i, -1, "снова шорт"), False
            elif new4 and covered and fc > g:
                covered = False
            elif new4 and not covered and under_gy and under_bl:
                cur = opn(i, -1, "под голубой")
        elif new4 and ry == 1 and over_bl:
            cur = opn(i, 1, "снова над жёлтой")
        elif new4 and over_bl and a["f_stack"][i] == 1 and over_gy:
            cur = opn(i, 1, "над голубыми")
        elif new4 and (rr == -P["k4"] if P["event_short"] else rr <= -P["k4"]):  # «пробили и закрепились» — событие, а не состояние
            cur = opn(i, -1, "над голубыми")
    if cur is not None:
        close(len(t) - 1, c[-1], "конец")
    return legs


def recall(a, legs, tol_h=8):
    """Совпало ли действие автомата с названным оператором: та же сторона, не дальше tol_h часов. Сделки ищутся и в открытиях, и в закрытиях."""
    t = a["t"]
    rows = []
    for ts, act, word in MARKS:
        x = cw.T(ts)
        side = 1 if act[-1] == "L" else -1
        cand = [(t[le[1] if act.startswith("x") else le[0]], le) for le in legs if le[4] == side]
        best = min(cand, key=lambda z: abs(z[0] - x))
        dh = (best[0] - x) / 3600
        rows.append({"время": ts[5:], "действие": act, "оператор": word, "автомат_ч": round(float(dh), 1), "тип": best[1][5], "совпало": abs(dh) <= tol_h})
    return pd.DataFrame(rows)


def by_type(a, fm, legs, coin):
    rows = [lg.summary(a, fm, [x[:5] for x in legs], "ВСЕ", coin)]
    for s, nm in ((1, "лонг"), (-1, "шорт")):
        rows.append(lg.summary(a, fm, [x[:5] for x in legs if x[4] == s], f"все {nm}", coin))
        for tag in sorted({x[5] for x in legs if x[4] == s}):
            rows.append(lg.summary(a, fm, [x[:5] for x in legs if x[4] == s and x[5] == tag], f"{nm}: {tag}", coin))
    keep = ("монета", "что", "n", "среднее_%", "плюс_%", "сумма_%", "фандинг_%", "A", "B", "C", "ди_низ_сделки", "просадка_часы_%", "под_водой_дней", "блок_низ_%", "блок_верх_%")
    return pd.DataFrame([{k: r[k] for k in keep} for r in rows])


def by_year(a, fm, legs):
    t = a["t"]
    d = pd.DataFrame([{"год": pd.Timestamp(int(t[x[0]]), unit="s").year, "s": x[4], "r": sum(np.array(lg.trade_cash(fm, x[:5])) * (1, -1, -1)) / lg.NOTIONAL * 100} for x in legs])
    g = d.groupby("год")["r"]
    return pd.DataFrame({"сделок": g.size(), "сумма_%": g.sum().round(1), "лонг_%": d[d["s"] == 1].groupby("год")["r"].sum().round(1), "шорт_%": d[d["s"] == -1].groupby("год")["r"].sum().round(1)}).T


def totals(a, fm, legs, coin, lab, per):
    t = a["t"]
    yrs = (t[-1] - t[a["i0"]]) / (365.25 * 86400)
    rows = []
    for nm, sel in (("все", legs), ("лонг", [x for x in legs if x[4] == 1]), ("шорт", [x for x in legs if x[4] == -1])):
        s = lg.summary(a, fm, [x[:5] for x in sel], nm, coin, per)
        rows.append({"ряд": coin, "вариант": lab, "что": nm, "n": s["n"], "в_год": round(s["n"] / yrs), "среднее_%": s["среднее_%"], "плюс_%": s["плюс_%"], "сумма_%": s["сумма_%"], "по_периодам": " / ".join(str(round(s[p])) for p in per),
                     "просадка_часы_%": s["просадка_часы_%"], "под_водой_дней": s["под_водой_дней"], "блок_низ_%": s["блок_низ_%"], "блок_верх_%": s["блок_верх_%"]})
    return rows


def main():
    m, h1, h4, d1, fund = cw.load()
    del m
    a, _ = gc.er.prep(h1, h4, d1, fund)
    add_runs(a)
    fm = lg.funding_marks(a, fund)
    m2, h1e, h4e, d1e, fe = pd.read_pickle(gc.er.ETH_PKL)
    del m2
    h1e, h4e = cw.features(h1e, h4e, 1), cw.features(h4e, h1e, 4)
    e, _ = gc.er.prep(h1e, h4e, d1e, fe)
    add_runs(e)
    fme = lg.funding_marks(e, fe)
    cfgs = (("слова", {}), ("слова + сужение 0.15 закрыть и ждать", {"knot": 0.15}), ("слова + сужение 0.30 закрыть и ждать", {"knot": 0.30}))
    w0, w1 = cw.T("2025-02-15"), cw.T("2025-05-15")
    for lab, kw in cfgs:
        legs = run(a, **kw)
        r = recall(a, legs)
        inw = [x for x in legs if w0 <= a["t"][x[0]] < w1]
        print(lab, "совпало", int(r["совпало"].sum()), "из", len(r), "| сделок на скринах", len(inw), "| не совпали:", r.loc[~r["совпало"], ["время", "оператор", "автомат_ч"]].to_dict("records"), flush=True)
    rows = []
    for lab, kw in cfgs:
        rows += totals(a, fm, run(a, **kw), "BTC", lab, pos.PER) + totals(e, fme, run(e, **kw), "ETH", lab, pos.PER)
    t = pd.DataFrame(rows)
    t.to_csv(pos.OUT / "words_totals.csv", index=False)
    print(t.to_string(index=False), flush=True)
    for x, f, coin in ((a, fm, "BTC"), (e, fme, "ETH")):
        legs = run(x)
        tt = by_type(x, f, legs, coin)
        tt.to_csv(pos.OUT / f"words_types_{coin}.csv", index=False)
        print(tt.to_string(index=False), flush=True)
        print(by_year(x, f, legs).to_string(), flush=True)
    legs = run(a)
    pd.DataFrame(legs, columns=["i0", "i1", "p0", "p1", "s", "тип", "причина"]).assign(t0=lambda d: a["t"][d["i0"]], t1=lambda d: a["t"][d["i1"]]).to_csv(pos.OUT / "words_legs.csv", index=False)
    recall(a, legs).to_csv(pos.OUT / "words_recall.csv", index=False)
    bs, fbs = gc.load_bitstamp()
    add_runs(bs)
    xr, fx = gc.load_xrp()
    add_runs(xr)
    rows = totals(bs, lg.funding_marks(bs, fbs), run(bs), "Bitstamp 2014–17", "слова", PER_BS) + totals(xr, lg.funding_marks(xr, fx), run(xr), "XRP 2020–26", "слова", PER_X)
    t = pd.DataFrame(rows)
    t.to_csv(pos.OUT / "words_new_data.csv", index=False)
    print(t.to_string(index=False), flush=True)
    for x, f, coin, per in ((bs, fbs, "Bitstamp", PER_BS), (xr, fx, "XRP", PER_X)):
        fmx = lg.funding_marks(x, f)
        legs = run(x)
        tags = sorted({(q[4], q[5]) for q in legs})
        print(coin, {f"{'L' if s == 1 else 'S'} {g}": (len([q for q in legs if q[4] == s and q[5] == g]), round(sum((np.array(lg.trade_cash(fmx, q[:5])) * (1, -1, -1)).sum() for q in legs if q[4] == s and q[5] == g) / lg.NOTIONAL * 100, 1)) for s, g in tags}, flush=True)


if __name__ == "__main__":
    main()
