"""Флет словами оператора (записки 06.11): три цветные близко, синяя почти горизонтальна; конец — цветные выстроены и смотрят в одну сторону, цена закрепилась за зелёной и синей (2 закрытия 4ч).
Порядок, записан до прогона денег: порог (X, Z) выбирается ПО ЕГО ОКНАМ по правилу ниже, деньги считаются после, соседи — точным списком (±1 шаг по X и Z).
Правило выбора: максимум (доля флета в его окнах флета − доля в его окнах тренда) при доле всех часов BTC ≤ 40%.
Что считается внутри флета, BTC и ETH, периоды A 2018–21, B 2022–07.24, C 08.24–11.26:
  две сетки без стопа, закрытие по рынку в конце флета; шаг/цель 0.6/1.4, 0.3/0.7, 0.2/0.5, 0.15/0.3; $100 на ордер, потолок $3000 на сторону, ядро gridk (мейкер 0.016%, выход тейкер 0.048% + 0.02%);
  отмена ноги: на выходе из флета закрывается нога против выхода, другая дорабатывает до закрепления за зелёной в обратную сторону;
  контроль сеток: 199 наборов случайных эпизодов той же длины в том же периоде, ранг (k+1)/(n+1);
  позиции $1000: от синей к красной, от красной, пробитие зелёной, пробитие зелёной в обе стороны, сделки A + 2/6 и простого правила, открытые во флете."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parents[1] / "market_regimes_20261102"))
import cw_data as cw  # noqa: E402
import entry_rules as er  # noqa: E402
import gridk  # noqa: E402
import pos  # noqa: E402
import state_map as sm  # noqa: E402
import words2 as w2  # noqa: E402
import words3 as w3  # noqa: E402
import words3_look as wl  # noqa: E402

pd.set_option("display.width", 260, "display.max_columns", 40, "display.max_rows", 300)
RNG = np.random.default_rng(20261106)
REPS = 199
X_G, Z_G = (1.0, 1.5, 2.0, 2.5, 3.0, 4.0), (1.0, 2.0, 3.0, 4.0, 6.0)
HIS_FLAT = (("2024-12-01", "2024-12-31"), ("2025-08-14", "2025-09-10"), ("2026-02-23", "2026-04-06"), ("2026-07-10", "2026-07-21"))
HIS_TREND = (("2024-10-14", "2024-11-25"), ("2025-01-31", "2025-02-27"), ("2026-01-16", "2026-02-20"))
PER = {"A": ("2018-01-01", "2022-01-01"), "B": ("2022-01-01", "2024-08-01"), "C": ("2024-08-01", "2026-11-07")}
GRIDS = ((0.6, 1.4), (0.3, 0.7), (0.2, 0.5), (0.15, 0.3))


def episodes(a, X, Z):
    """Эпизоды флета (i начала, i конца, направление выхода). Решение на закрытии 4ч, только закрытые данные."""
    G, Y, R, B, atr, sb, j, rG, rB = a["f_G"], a["f_Y"], a["f_R"], a["f_B"], a["atr4"], a["s_b4"], a["j"], a["f_run_G"], a["f_run_B"]
    on, jp, st, out = False, -1, 0, []
    n = len(G)
    for i in range(a["i0"], n):
        if j[i] == jp:
            continue
        jp = j[i]
        z = max(i - 24, 0)
        up = G[i] > Y[i] > R[i] and G[i] > G[z] and Y[i] > Y[z] and R[i] > R[z] and rG[i] >= 2 and rB[i] >= 2
        dn = G[i] < Y[i] < R[i] and G[i] < G[z] and Y[i] < Y[z] and R[i] < R[z] and rG[i] <= -2 and rB[i] <= -2
        if on and (up or dn):
            out.append((st, i, 1 if up else -1))
            on = False
        elif not on and not (up or dn) and (max(G[i], Y[i], R[i]) - min(G[i], Y[i], R[i])) <= X * atr[i] and abs(sb[i]) <= Z:
            on, st = True, i
    if on:
        out.append((st, n - 1, 0))
    return out


def mask(a, ep):
    m = np.zeros(len(a["t"]), dtype=bool)
    for x, y, _ in ep:
        m[x:y] = True
    return m


def share(a, m, wins):
    t = a["t"]
    v = [m[(t >= sm.T(x)) & (t < sm.T(z))].mean() for x, z in wins]
    return float(np.mean(v)), [round(q * 100) for q in v]


def choose(a):
    rows = []
    b = a["i0"]
    for X in X_G:
        for Z in Z_G:
            ep = episodes(a, X, Z)
            m = mask(a, ep)
            cf, vf = share(a, m, HIS_FLAT)
            ct, vt = share(a, m, HIS_TREND)
            rows.append({"X": X, "Z": Z, "доля_всех_%": round(m[b:].mean() * 100, 1), "его_флет_%": round(cf * 100), "окна_флета": vf, "его_тренд_%": round(ct * 100), "окна_тренда": vt, "эпизодов": len(ep), "счёт": round((cf - ct) * 100, 1)})
    d = pd.DataFrame(rows)
    d.to_csv(pos.OUT / "flat_words_choose.csv", index=False)
    print(d.sort_values("счёт", ascending=False).head(14).to_string(index=False), flush=True)
    ok = d[d["доля_всех_%"] <= 40].sort_values("счёт", ascending=False).iloc[0]
    print("выбрано по правилу: X", ok["X"], "Z", ok["Z"], flush=True)
    return float(ok["X"]), float(ok["Z"])


def pos_in_flat(a, ep, kind, tol=0.5):
    """Позиции внутри эпизодов флета. Сделки закрываются не позже конца эпизода."""
    t, c, h, l, o, j = a["t"], a["c"], a["h"], a["l"], a["o"], a["j"]
    G, R, B, atr, Rp = a["f_G"], a["f_R"], a["f_B"], a["atr4"], np.r_[a["f_R"][0], a["f_R"][:-1]]
    rG, rR, rB = a["f_run_G"], a["f_run_R"], a["f_run_B"]
    legs = []
    for st, en, _ in ep:
        cur, jp = None, j[st]
        for i in range(st + 1, en + 1):
            new4 = j[i] != jp
            jp = j[i]
            if cur is not None:
                i0, p0, s, lvl = cur
                if lvl is not None and h[i] >= lvl and p0 < lvl:
                    legs.append((i0, i, p0, float(max(lvl, o[i])), s, kind, "цель"))
                    cur = None
                    continue
                stop = False
                if new4:
                    if kind == "от синей":
                        stop = rB[i] <= -2
                    elif kind == "от красной":
                        stop = rR[i] <= -2
                    else:
                        stop = (rG[i] <= -2) if s == 1 else (rG[i] >= 2)
                if stop or i == en:
                    legs.append((i0, i, p0, float(c[i]), s, kind, "конец флета" if i == en else "стоп"))
                    cur = None
                    if not stop or kind not in ("зелёная", "зелёная 2"):
                        continue
            if cur is not None or i == en:
                continue
            if kind == "от синей" and l[i] <= B[i] + 0.25 * atr[i] and c[i] > B[i] and R[i] * (1 - tol / 100) > c[i]:
                cur = (i, float(c[i]), 1, Rp[i] * (1 - tol / 100))
            elif kind == "от красной" and l[i] <= R[i] + 0.25 * atr[i] and c[i] > R[i]:
                cur = (i, float(c[i]), 1, None)
            elif kind in ("зелёная", "зелёная 2") and new4 and rG[i] == 2:
                cur = (i, float(c[i]), 1, None)
            elif kind == "зелёная 2" and new4 and rG[i] == -2:
                cur = (i, float(c[i]), -1, None)
    return legs


def split(a, fm, legs):
    t = a["t"]
    out = {}
    for p, (x, z) in PER.items():
        v = [w2.net(fm, q) for q in legs if sm.T(x) <= t[q[0]] < sm.T(z)]
        out[p] = round(float(np.sum(v)), 1)
    return out


def grid_eps(mk, a, ep, side, step, tgt, leg_keep=False):
    t = a["t"]
    i0, i1 = [], []
    rG, j = a["f_run_G"], a["j"]
    for st, en, d in ep:
        e = en
        if leg_keep and d == side:
            for q in range(en + 1, min(en + 24 * 90, len(t))):
                if j[q] != j[q - 1] and side * rG[q] <= -2:
                    e = q
                    break
            else:
                e = min(en + 24 * 90, len(t) - 1)
        i0.append(int(t[st]))
        i1.append(int(t[e]))
    return mk.run(mk.idx(i0), mk.idx(i1), side, step=step, tgt=tgt, cap=3000.0), np.array(i0)


def grid_block(lab, mk, a, ep):
    rows = []
    for step, tgt in GRIDS:
        for keep in (False, True):
            r1, t1 = grid_eps(mk, a, ep, 1, step, tgt, keep)
            r2, t2 = grid_eps(mk, a, ep, -1, step, tgt, keep)
            row = {"ряд": lab, "сетка": f"{step}/{tgt}", "нога": "дорабатывает" if keep else "закрыть обе", "эп": len(ep), "лонг": round(float(r1[:, 0].sum())), "шорт": round(float(r2[:, 0].sum())), "итог": round(float(r1[:, 0].sum() + r2[:, 0].sum()))}
            for p, (x, z) in PER.items():
                m1, m2 = (t1 >= sm.T(x)) & (t1 < sm.T(z)), (t2 >= sm.T(x)) & (t2 < sm.T(z))
                row[p] = round(float(r1[m1, 0].sum() + r2[m2, 0].sum()))
            net = np.r_[r1[:, 0], r2[:, 0]]
            ord_ = np.argsort(np.r_[t1, t2])
            cum = np.cumsum(net[ord_])
            row["просадка_по_эп"] = round(float((cum - np.maximum.accumulate(np.r_[0, cum])[1:]).min()))
            row["плюс_эп_%"] = round(float(((r1[:, 0] + r2[:, 0]) > 0).mean() * 100))
            rows.append(row)
    return rows


def control(mk, a, ep, step, tgt):
    """Случайные эпизоды той же длины внутри того же периода."""
    t = a["t"]
    res = {}
    for p, (x, z) in PER.items():
        X, Z = sm.T(x), sm.T(z)
        lens = [int(t[e] - t[s]) for s, e, _ in ep if X <= t[s] < Z]
        if not lens:
            continue
        lens = np.array(lens)
        ta, tb = max(X, int(t[a["i0"]])), min(Z, int(t[-1]))
        real_i0 = [int(t[s]) for s, e, _ in ep if X <= t[s] < Z]
        real_i1 = [int(t[e]) for s, e, _ in ep if X <= t[s] < Z]
        real = sum(float(mk.run(mk.idx(real_i0), mk.idx(real_i1), sd, step=step, tgt=tgt, cap=3000.0)[:, 0].sum()) for sd in (1, -1))
        ctl = []
        for _ in range(REPS):
            st = RNG.integers(ta, np.maximum(tb - lens, ta + 1))
            en = st + lens
            ctl.append(sum(float(mk.run(mk.idx(st), mk.idx(en), sd, step=step, tgt=tgt, cap=3000.0)[:, 0].sum()) for sd in (1, -1)))
        ctl = np.array(ctl)
        res[p] = {"настоящие": round(real), "медиана_случайных": round(float(np.median(ctl))), "лучше_случайных_%": round(float((ctl < real).mean() * 100)), "ранг": round(float(((ctl >= real).sum() + 1) / (REPS + 1)), 3)}
    return res


def main():
    S = wl.series()
    btc, fb = S[0][1], S[0][2]
    eth, fe = S[1][1], S[1][2]
    X, Z = choose(btc)
    neigh = [(X, Z)] + [(x, z) for x, z in ((X_G[max(X_G.index(X) - 1, 0)], Z), (X_G[min(X_G.index(X) + 1, len(X_G) - 1)], Z), (X, Z_G[max(Z_G.index(Z) - 1, 0)]), (X, Z_G[min(Z_G.index(Z) + 1, len(Z_G) - 1)])) if (x, z) != (X, Z)]
    print("соседи:", neigh, flush=True)
    m, _, _, _, fund = cw.load()
    mkb = gridk.Market(m["ts"].to_numpy(), m["open"].to_numpy(), m["high"].to_numpy(), m["low"].to_numpy(), m["close"].to_numpy(), fund)
    del m
    m2, _, _, _, fund2 = pd.read_pickle(er.ETH_PKL)
    mke = gridk.Market(m2["ts"].to_numpy(), m2["open"].to_numpy(), m2["high"].to_numpy(), m2["low"].to_numpy(), m2["close"].to_numpy(), fund2)
    del m2
    g_rows, p_rows, c_rows = [], [], []
    for lab, a, fm, mk in (("BTC", btc, fb, mkb), ("ETH", eth, fe, mke)):
        ep = episodes(a, X, Z)
        dur = np.array([(a["t"][e] - a["t"][s]) / 86400 for s, e, _ in ep])
        print(lab, "эпизодов", len(ep), "доля", round(mask(a, ep)[a["i0"]:].mean() * 100, 1), "% медиана дней", round(float(np.median(dur)), 1), "вверх", sum(1 for x in ep if x[2] == 1), "вниз", sum(1 for x in ep if x[2] == -1), flush=True)
        g_rows += grid_block(lab, mk, a, ep)
        for kind in ("от синей", "от красной", "зелёная", "зелёная 2"):
            legs = pos_in_flat(a, ep, kind)
            p_rows.append({"ряд": lab, "что": kind, **w3.stats(a, fm, legs), **split(a, fm, legs)})
        fl = mask(a, ep)
        for nm, legs in (("A+2/6 входы во флете", w2.run(a, **w2.MAIN26)), ("простое правило, входы во флете", w3.run(a, l_align=False, s_align=False))):
            legs = [q for q in legs if fl[q[0]]]
            p_rows.append({"ряд": lab, "что": nm, **w3.stats(a, fm, legs), **split(a, fm, legs)})
        for step, tgt in GRIDS:
            for p, v in control(mk, a, ep, step, tgt).items():
                c_rows.append({"ряд": lab, "сетка": f"{step}/{tgt}", "период": p, **v})
        print(lab, "готово", flush=True)
    for x, z in neigh[1:]:
        ep = episodes(btc, x, z)
        for r in grid_block(f"BTC сосед X{x} Z{z}", mkb, btc, ep):
            g_rows.append(r)
        legs = [q for q in pos_in_flat(btc, ep, "от синей")]
        p_rows.append({"ряд": f"BTC сосед X{x} Z{z}", "что": "от синей", **w3.stats(btc, fb, legs), **split(btc, fb, legs)})
    gd, pd_, cd = pd.DataFrame(g_rows), pd.DataFrame(p_rows), pd.DataFrame(c_rows)
    gd.to_csv(pos.OUT / "flat_words_grids.csv", index=False)
    pd_.to_csv(pos.OUT / "flat_words_pos.csv", index=False)
    cd.to_csv(pos.OUT / "flat_words_ctl.csv", index=False)
    print(gd.to_string(index=False), flush=True)
    print(pd_.to_string(index=False), flush=True)
    print(cd.to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
