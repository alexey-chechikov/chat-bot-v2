"""Только биткоин (оператор 07.11: «сделать идеально биткоин, под другие будем смотреть после»). Монеты здесь не судья. Судья: Binance BTC 2018–2026 по трём периодам и Bitstamp BTC 2014–17 как тот же актив на независимых годах.
Поток: основная пара как в plus.py и добавочные правила из записок оператора, каждое включается весом. Слот один: пока сделка открыта, новых нет. Основные правила проверяются первыми.
Добавочные правила:
  cs   шорт над синей: второе закрытие под жёлтой, цена выше синей на 0.5%; цель синяя, отмена 2 закрытия над жёлтой;
  csyr шорт над синей: жёлтая ниже красной, цветные не все вверх, 2 закрытия под зелёной; цель синяя, отмена 2 закрытия над зелёной;
  lbg  лонг под синей: 2 закрытия над зелёной; цель синяя, отмена 2 закрытия под зелёной;
  lby  лонг под синей: 2 закрытия над жёлтой; цель синяя, отмена 2 закрытия под жёлтой;
  fbl  лонг от синей: час коснулся синей сверху и закрылся над ней, красная выше цены; цель красная, отмена 2 закрытия под синей;
  fbs  шорт от синей: час коснулся синей снизу и закрылся под ней, красная ниже цены; цель красная, отмена 2 закрытия над синей.
Сделка: (i0, i1, p0, p1, сторона, тип, причина, вес)."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import plus as pl  # noqa: E402
import state_card as sc  # noqa: E402
import state_map as sm  # noqa: E402
import words3_look as wl  # noqa: E402

pd.set_option("display.width", 240, "display.max_columns", 40, "display.max_rows", 200, "display.max_colwidth", 60)
OUT = Path(__file__).parent / "out"
CUT = sm.T("2026-11-07")
PER = (("18–21", "2018-01-01", "2022-01-01"), ("22–07.24", "2022-01-01", "2024-08-01"), ("08.24–26", "2024-08-01", "2027-01-01"))


def load():
    a, f, _ = sc.load_coin("BTC")
    bs = [x for x in wl.series() if x[0] == "Bitstamp"][0]
    return (a, f, pl.layer(a)), (bs[1], bs[2], pl.layer(bs[1]))


def run(a, lay, lx="R", sx="G", rank_th=0.6, size=True, rules=None, cut=None, lx_yg=False, tol=0.005, sok=None, lw=None, no_s_after_win=False, cs_yg=False, cs_after=None):
    """sok: булев массив по часам, разрешён ли основной шорт. lw: множитель веса основного лонга по часам. no_s_after_win: нет основного шорта сразу после плюсовой сделки.
    cs_yg: шорт под жёлтой только при жёлтой выше зелёной. cs_after: только если основной лонг закрылся не больше cs_after дней назад (записка оператора: шорт от лонга)."""
    rules = rules or {}
    last_win = False
    last_long = -10 ** 9
    t, c, h, l, o, j = a["t"], a["c"], a["h"], a["l"], a["o"], a["j"]
    F, G, Y, R, B = a["f_close"], a["f_G"], a["f_Y"], a["f_R"], a["f_B"]
    Bp, Rp = a["B4p"], np.r_[R[0], R[:-1]]
    rG, rY, rR, rB = a["f_run_G"], a["f_run_Y"], a["f_run_R"], a["f_run_B"]
    runs = {"G": rG, "Y": rY, "R": rR}
    rex, rsx = runs[lx], runs[sx]
    rk, W = lay
    n = len(t) if cut is None else int(np.searchsorted(t, cut, side="right"))
    legs, side, i_e, p_e, w_e, tag, tgt, jp, last_fb = [], 0, -1, 0.0, 1.0, "", None, -1, -10 ** 9
    need_h = any(k in rules for k in ("fbl", "fbs"))

    def close(i, px, why):
        nonlocal side, tag, tgt, last_win, last_long
        last_win = side * (px / p_e - 1) > 0.00136
        if tag == "L над синей":
            last_long = i
        legs.append((i_e, i, p_e, float(px), side, tag, why, w_e))
        side, tag, tgt = 0, "", None

    def opn(i, s, tg, frac=1.0, target=None):
        nonlocal side, i_e, p_e, w_e, tag, tgt
        side, i_e, p_e, tag, tgt = s, i, float(c[i]), tg, target
        w_e = (W[i] / pl.DIV if size else 1.0) * frac

    for i in range(a["i0"], n):
        new4 = j[i] != jp
        jp = j[i]
        if side != 0 and tgt is not None:
            base = Bp[i] if tgt == "B" else Rp[i]
            lv = base * (1 - side * tol)
            if (side == 1 and h[i] >= lv > p_e) or (side == -1 and l[i] <= lv < p_e):
                close(i, max(lv, o[i]) if side == 1 else min(lv, o[i]), "цель")
                if not new4:
                    continue
        if new4 and side != 0:
            if tag == "L над синей":
                ex = (Y[i] > G[i] and rY[i] <= -2) or rR[i] <= -2 if lx_yg else rex[i] <= -2
                if ex:
                    close(i, c[i], "выход")
            elif tag == "S под синей":
                if rsx[i] >= 2:
                    close(i, c[i], "выход")
            elif tag == "S cs":
                if rY[i] >= 2:
                    close(i, c[i], "отмена")
            elif tag == "S csyr":
                if rG[i] >= 2:
                    close(i, c[i], "отмена")
            elif tag == "L lbg":
                if rG[i] <= -2:
                    close(i, c[i], "отмена")
            elif tag == "L lby":
                if rY[i] <= -2:
                    close(i, c[i], "отмена")
            elif tag == "L fbl":
                if rB[i] <= -2:
                    close(i, c[i], "отмена")
            elif tag == "S fbs":
                if rB[i] >= 2:
                    close(i, c[i], "отмена")
        if side != 0:
            continue
        if new4:
            z = max(i - 24, 0)
            above = F[i] > B[i]
            if above:
                lgo = (rG[i] >= 2 and rR[i] > -2 and not (Y[i] > G[i] and rY[i] <= -2)) if lx_yg else (rG[i] >= 2 and rex[i] > -2)
                if lgo:
                    opn(i, 1, "L над синей", 1.0 if lw is None else float(lw[i]))
                    continue
                if "cs" in rules and rY[i] == -2 and c[i] > B[i] * (1 + tol) and (not cs_yg or Y[i] > G[i]) and (cs_after is None or i - last_long <= cs_after * 24):
                    opn(i, -1, "S cs", rules["cs"], "B")
                    continue
                if "csyr" in rules and Y[i] < R[i] and not (G[i] > G[z] and Y[i] > Y[z] and R[i] > R[z]) and rG[i] == -2 and c[i] > B[i] * (1 + tol):
                    opn(i, -1, "S csyr", rules["csyr"], "B")
                    continue
            else:
                if rG[i] <= -2 and rsx[i] < 2 and (rank_th is None or not rk[i] > rank_th) and (sok is None or sok[i]) and not (no_s_after_win and last_win):
                    opn(i, -1, "S под синей")
                    continue
                if "lby" in rules and rY[i] == 2 and c[i] < B[i] * (1 - tol):
                    opn(i, 1, "L lby", rules["lby"], "B")
                    continue
                if "lbg" in rules and rG[i] == 2 and c[i] < B[i] * (1 - tol):
                    opn(i, 1, "L lbg", rules["lbg"], "B")
                    continue
        if need_h and i - last_fb >= 24:
            if "fbl" in rules and F[i] > B[i] and l[i] <= Bp[i] * (1 + tol) and c[i] > Bp[i] and Rp[i] > c[i] * (1 + tol):
                opn(i, 1, "L fbl", rules["fbl"], "R")
                last_fb = i
            elif "fbs" in rules and F[i] <= B[i] and h[i] >= Bp[i] * (1 - tol) and c[i] < Bp[i] and Rp[i] < c[i] * (1 - tol):
                opn(i, -1, "S fbs", rules["fbs"], "R")
                last_fb = i
    if side != 0:
        close(n - 1, c[n - 1], "конец")
    return legs


def row(a, f, legs):
    st = pl.stats(a, f, legs)
    r, w = pl.unit(f, legs)
    v = r * w
    t0 = a["t"][np.array([x[0] for x in legs])]
    out = {k: st[k] for k in ("n", "итог", "просадка", "с2025", "отн")}
    for lab, x, z in PER:
        out[lab] = round(float(v[(t0 >= sm.T(x)) & (t0 < sm.T(z))].sum()))
    return out


def tag_table(a, f, legs):
    r, w = pl.unit(f, legs)
    v = r * w
    t0 = pd.to_datetime(a["t"][np.array([x[0] for x in legs])], unit="s").year
    tags = np.array([x[5] for x in legs])
    why = np.array([x[6] for x in legs])
    rows = []
    for tg in sorted(set(tags)):
        m = tags == tg
        y = pd.Series(v[m]).groupby(t0[m]).sum()
        rows.append({"правило": tg, "сделок": int(m.sum()), "плюс_%": round(float((v[m] > 0).mean() * 100)), "на_сделку": round(float(v[m].mean()), 2), "сумма": round(float(v[m].sum()), 1), "цель_%": round(float((why[m] == "цель").mean() * 100)), "лет_плюс": f"{int((y > 0).sum())} из {len(y)}", "по_годам": " ".join(f"{str(k)[2:]}:{q:+.0f}" for k, q in y.items())})
    return pd.DataFrame(rows)


def main():
    (a, f, lay), (b, fb, layb) = load()
    V = {"Простое+": {}, "выход шорта над Y": dict(sx="Y"), "выход лонга под Y": dict(lx="Y"), "выход лонга под Y только при Y>G": dict(lx_yg=True), "выход лонга под G": dict(lx="G")}
    for k, wt in (("cs", 0.5), ("cs", 1.0), ("csyr", 0.5), ("csyr", 1.0), ("lbg", 1.0), ("lby", 1.0), ("fbl", 1.0), ("fbs", 1.0)):
        V[f"{k} вес {wt}"] = dict(rules={k: wt})
    V["cs 0.5 и выход шорта над Y"] = dict(sx="Y", rules={"cs": 0.5})
    V["cs 1 и выход шорта над Y"] = dict(sx="Y", rules={"cs": 1.0})
    V["cs 0.5, lby, выход шорта над Y"] = dict(sx="Y", rules={"cs": 0.5, "lby": 1.0})
    V["все правила записок вес 1"] = dict(sx="Y", rules={"cs": 1.0, "csyr": 1.0, "lby": 1.0, "lbg": 1.0, "fbl": 1.0, "fbs": 1.0})
    rows, rows0, tabs = [], [], []
    for lab, kw in V.items():
        legs = run(a, lay, cut=CUT, **kw)
        lb = run(b, layb, **kw)
        s = row(a, f, legs)
        sb = pl.stats(b, fb, lb)
        rows.append({"вариант": lab, **s, "Bitstamp": sb["итог"], "Bs_просадка": sb["просадка"]})
        k0 = {**kw, "rank_th": None, "size": False}
        s0 = row(a, f, run(a, lay, cut=CUT, **k0))
        sb0 = pl.stats(b, fb, run(b, layb, **k0))
        rows0.append({"вариант": lab, **s0, "Bitstamp": sb0["итог"], "Bs_просадка": sb0["просадка"]})
        t = tag_table(a, f, legs)
        t.insert(0, "вариант", lab)
        tabs.append(t)
    d, d0, tb = pd.DataFrame(rows), pd.DataFrame(rows0), pd.concat(tabs)
    d.to_csv(OUT / "btc_lab_plus.csv", index=False)
    d0.to_csv(OUT / "btc_lab_const.csv", index=False)
    tb.to_csv(OUT / "btc_lab_rules.csv", index=False)
    print("== слой Простое+ (размер и фильтр шорта)", flush=True)
    print(d.to_string(index=False), flush=True)
    print("== без слоя: постоянный размер, все шорты", flush=True)
    print(d0.to_string(index=False), flush=True)
    print("== каждое правило само по себе: все случаи на BTC", flush=True)
    keep = tb[tb["вариант"].isin(["Простое+", "cs вес 1.0", "csyr вес 1.0", "lbg вес 1.0", "lby вес 1.0", "fbl вес 1.0", "fbs вес 1.0"]) & (~tb["правило"].isin(["L над синей", "S под синей"]) | (tb["вариант"] == "Простое+"))]
    print(keep.drop(columns="вариант").to_string(index=False), flush=True)
    paired(a, f)


def first_exit(a, i0, cond, n):
    j = a["j"]
    for q in range(i0 + 1, n):
        if j[q] != j[q - 1] and cond(q):
            return q
    return n - 1


def paired(a, f):
    """Те же входы, разный выход, сделка за сделкой, вес 1. Поток не пересчитывается: это сравнение выхода на одних и тех же случаях."""
    n = int(np.searchsorted(a["t"], CUT, side="right"))
    c, Y, G = a["c"], a["f_Y"], a["f_G"]
    rG, rY, rR = a["f_run_G"], a["f_run_Y"], a["f_run_R"]
    lay = pl.layer(a)
    legs = run(a, lay, rank_th=None, size=False, cut=CUT)

    def net(i0, i1, s):
        from words2 import net as nt
        return nt(f, (i0, i1, float(c[i0]), float(c[i1]), s))

    rows = []
    for x in legs:
        i0, s = x[0], x[4]
        if s == 1:
            e = {"R": first_exit(a, i0, lambda q: rR[q] <= -2, n), "Y": first_exit(a, i0, lambda q: rY[q] <= -2, n), "G": first_exit(a, i0, lambda q: rG[q] <= -2, n), "Y при Y>G": first_exit(a, i0, lambda q: (Y[q] > G[q] and rY[q] <= -2) or rR[q] <= -2, n)}
        else:
            e = {"G": first_exit(a, i0, lambda q: rG[q] >= 2, n), "Y": first_exit(a, i0, lambda q: rY[q] >= 2, n), "R": first_exit(a, i0, lambda q: rR[q] >= 2, n)}
        row_ = {"t0": sm.utc(a["t"][i0]), "год": pd.Timestamp(int(a["t"][i0]), unit="s").year, "s": s}
        for k, q in e.items():
            row_[k] = round(net(i0, q, s), 2)
        rows.append(row_)
    d = pd.DataFrame(rows)
    d.to_csv(OUT / "btc_paired_exits.csv", index=False)
    for s, nm, base, alts in ((1, "ЛОНГ", "R", ("Y", "Y при Y>G", "G")), (-1, "ШОРТ", "G", ("Y", "R"))):
        g = d[d["s"] == s]
        print(f"== {nm}: те же {len(g)} входов, выход {base} против других", flush=True)
        for alt in alts:
            df = g[alt] - g[base]
            y = df.groupby(g["год"]).sum()
            print(f"{alt}: сумма {g[alt].sum():+.0f} против {g[base].sum():+.0f}, разница {df.sum():+.0f}; лучше в {int((df > 0.001).sum())} случаях, хуже в {int((df < -0.001).sum())}, поровну {int((df.abs() <= 0.001).sum())}; лучшая {df.max():+.1f}, худшая {df.min():+.1f}; годы " + " ".join(f"{str(k)[2:]}:{v:+.0f}" for k, v in y.items()), flush=True)


if __name__ == "__main__":
    main()
