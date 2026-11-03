"""Широкий поиск улучшений 432 на BTC H4 (подтверждение на ETH): диагностика D1–D3 и 57 вариантов E1–E10, X1–X7 + комбинация
по заранее записанному правилу. Правила — PREREG.md (дописка «широкий поиск», до запуска).
Запуск: deep.py --pk-btc=<pkl> --pk-eth=<pkl>   (nice 20)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import mannwhitneyu

HERE = Path(__file__).parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "research" / "tv_lab_1025"))
import strategies as S  # noqa: E402
from my_rules import eq_stats  # noqa: E402
from review import COST, H4, PERIODS, Data, run, ts  # noqa: E402

OUT = HERE / "out"
PN = list(PERIODS)


class Ctx:
    def __init__(self, pk: Path):
        self.D = D = Data(pk)
        m, h1, h4, d1, fund = pd.read_pickle(pk)
        del m, h1
        c, n = D.c, len(D.c)
        self.n = n
        self.vol = h4["volume"].to_numpy()
        self.hh10 = pd.Series(D.h).rolling(10).max().to_numpy()
        self.low_n = {L: pd.Series(D.l).shift(1).rolling(L).min().to_numpy() for L in (10, 20, 25, 30, 40)}
        self.high_n = {L: pd.Series(D.h).shift(1).rolling(L).max().to_numpy() for L in (20, 25, 30, 40)}
        self.rsi = S.rsi(c, 14)
        self.chw = (D.hi30 - D.lo30) / c
        self.chw_q = {p: pd.Series(self.chw).rolling(2190, min_periods=500).quantile(p).shift(1).to_numpy() for p in (0.3, 0.5, 0.7)}
        self.volr = self.vol / pd.Series(self.vol).rolling(30).mean().shift(1).to_numpy()
        rng = D.h - D.l
        self.cloc = np.where(rng > 0, (c - D.l) / np.where(rng > 0, rng, 1), 0.5)
        dc = d1["close"].where(d1["nmin"] == 1440)
        day_prev = ((D.t + H4) // 86400) * 86400 - 86400
        self.d_above = {}
        for L in (20, 50, 100):
            e = dc.ewm(span=L, adjust=False).mean()
            a = (dc > e).reindex(day_prev).to_numpy()
            self.d_above[L] = np.array([bool(x) if x == x and x is not None else False for x in a])
        f = fund[~fund.index.duplicated(keep="last")]
        k = np.searchsorted(f.index.to_numpy(), D.t + H4, side="right") - 1
        self.fr_last = np.where(k >= 0, f.to_numpy()[np.maximum(k, 0)], np.nan)
        self.dist = c / D.e200 - 1
        atrp = D.atr / c
        med = pd.Series(atrp).rolling(2190, min_periods=500).median().shift(1).to_numpy()
        w = np.clip(med / atrp, 0.5, 2.0)
        self.w_r2 = np.where(np.isfinite(w), w, 1.0)

    def make_ent(self, adx_min=22.0, mag=0.5, L=30):
        D, c = self.D, self.D.c
        hi = self.high_n[L]
        with np.errstate(invalid="ignore", divide="ignore"):
            ent = (c > hi) & (D.adx >= adx_min) & (c > D.e200) & ((c - hi) / D.atr >= mag)
        ent[:300] = False
        return ent


def run2(X: Ctx, ent, exit_len=30, hold=20, ext_k=None, fail=None, be_T=None, trail_k=None, pyr=None, skipW=None, w=None):
    D = X.D
    o, h, c, atr, n = D.o, D.h, D.c, D.atr, X.n
    lo_exit = X.low_n[exit_len]
    legs, trades, pos = [], [], None
    last_win, last_exit = False, None
    for i in range(n - 1):
        if pos is not None:
            pos["maxh"] = max(pos["maxh"], h[i])
            px, a0 = pos["px"], pos["atr"]
            mfe = pos["maxh"] - px
            why = None
            if c[i] < lo_exit[i]:
                why = "канал"
            elif fail is not None and i - pos["j"] + 1 == fail[0] and mfe < fail[1] * a0:
                why = "не пошла"
            elif be_T is not None and mfe >= be_T * a0 and c[i] < px:
                why = "безубыток"
            elif trail_k is not None and mfe >= 2 * a0 and c[i] < pos["maxh"] - trail_k * a0:
                why = "трейл"
            elif i - pos["sig"] >= pos["hold"]:
                if ext_k is not None and pos["ext"] < 3 and c[i] >= X.hh10[i] - ext_k * atr[i]:
                    pos["hold"] += 10
                    pos["ext"] += 1
                else:
                    why = "время"
            if why:
                k = i + 1
                nets = [o[k] / pu - 1 - 2 * COST - D.fsum(ju, k) for ju, pu in pos["units"]]
                if not pos["hyp"]:
                    wt = 1.0 if w is None else w[pos["sig"]]
                    for (ju, pu), nt in zip(pos["units"], nets):
                        legs.append((ju, k, pu, 1, wt, nt))
                    trades.append({"j": pos["j"], "k": k, "sig": pos["sig"], "px": px, "net": nets[0], "why": why,
                                   "units": len(nets)})
                last_win, last_exit = nets[0] > 0, k
                pos = None
                continue
            if pyr is not None and not pos["hyp"] and len(pos["units"]) < pyr and c[i] >= pos["last_add"] + 0.5 * atr[i]:
                pos["units"].append((i + 1, o[i + 1]))
                pos["last_add"] = o[i + 1]
            continue
        if ent[i]:
            hyp = skipW is not None and last_win and (skipW == 0 or (last_exit is not None and i - last_exit <= skipW))
            pos = {"j": i + 1, "sig": i, "px": o[i + 1], "atr": atr[i], "maxh": -np.inf, "hold": hold, "ext": 0,
                   "units": [(i + 1, o[i + 1])], "last_add": o[i + 1], "hyp": hyp}
    if pos is not None and not pos["hyp"]:
        wt = 1.0 if w is None else w[pos["sig"]]
        for ju, pu in pos["units"]:
            legs.append((ju, n - 1, pu, 1, wt, c[-1] / pu - 1 - 2 * COST - D.fsum(ju, n - 1)))
    return legs, trades


def variants(X: Ctx):
    D, base = X.D, X.D.ent[1]
    adx_up = {L: D.adx > np.r_[np.full(L, np.nan), D.adx[:-L]] for L in (1, 3, 6)}
    V = {}
    for p in (0.3, 0.5, 0.7):
        V[f"E1 сжатие ≤ q{p}"] = ("E1", dict(ent=base & (X.chw <= X.chw_q[p])))
    for v in (1.0, 1.5, 2.0):
        V[f"E2 объём ≥ {v}× средн."] = ("E2", dict(ent=base & (X.volr >= v)))
    for q in (0.5, 0.7, 0.85):
        V[f"E3 закрытие в верхних {int(round((1 - q) * 100))}% свечи"] = ("E3", dict(ent=base & (X.cloc >= q)))
    for L in (1, 3, 6):
        V[f"E4 ADX растёт за {L}"] = ("E4", dict(ent=base & adx_up[L]))
    for L in (20, 50, 100):
        V[f"E5 день выше EMA{L}"] = ("E5", dict(ent=base & X.d_above[L]))
    for W, nm in ((60, "60 баров"), (120, "120 баров"), (0, "всегда")):
        V[f"E6 черепахи: пропуск после плюса, {nm}"] = ("E6", dict(ent=base, skipW=W))
    for a in (18.0, 20.0, 25.0):
        V[f"E7a ADX ≥ {a:g}"] = ("E7a", dict(ent=X.make_ent(adx_min=a)))
    for mg in (0.25, 0.75, 1.0):
        V[f"E7b пробой ≥ {mg:g} ATR"] = ("E7b", dict(ent=X.make_ent(mag=mg)))
    for L in (20, 25, 40):
        V[f"E7c канал {L}"] = ("E7c", dict(ent=X.make_ent(L=L), exit_len=L))
    for d in (0.15, 0.25, 0.35):
        V[f"E8 выше EMA200 не больше {int(d * 100)}%"] = ("E8", dict(ent=base & (X.dist <= d)))
    for r in (75, 80, 85):
        V[f"E9 RSI ≤ {r}"] = ("E9", dict(ent=base & ~(X.rsi > r)))
    for fr in (0.0003, 0.0005, 0.001):
        V[f"E10 фандинг < {fr * 100:.2f}%"] = ("E10", dict(ent=base & ~(X.fr_last >= fr)))
    for k in (0.5, 1.0, 2.0):
        V[f"X1 продление у максимумов, k {k:g}"] = ("X1", dict(ent=base, ext_k=k))
    for N, mm in ((4, 0.5), (6, 0.5), (8, 1.0)):
        V[f"X2 не пошла: бар {N}, ход < {mm:g} ATR"] = ("X2", dict(ent=base, fail=(N, mm)))
    for T in (2, 3, 4):
        V[f"X3 безубыток после +{T} ATR"] = ("X3", dict(ent=base, be_T=T))
    for k in (2.0, 2.75, 4.0):
        V[f"X4 трейлинг {k:g} ATR после +2 ATR"] = ("X4", dict(ent=base, trail_k=k))
    for L in (10, 20, 40):
        V[f"X5 выход по каналу {L}"] = ("X5", dict(ent=base, exit_len=L))
    for H in (15, 25, 30):
        V[f"X6 удержание {H} баров"] = ("X6", dict(ent=base, hold=H))
    for u in (2, 3, 4):
        V[f"X7 докупка +0.5 ATR, до {u} ед."] = ("X7", dict(ent=base, pyr=u))
    return V


def better(r, b):
    return all(r[p]["ratio"] is not None and b[p]["ratio"] is not None and r[p]["ratio"] > b[p]["ratio"] for p in PN)


def diagnostics(X: Ctx, trades):
    D = X.D
    o, c = D.o, D.c
    feats = {"сила пробоя, ATR": D.mag[1], "ADX": D.adx, "ADX за 3 бара": D.adx - np.r_[np.full(3, np.nan), D.adx[:-3]],
             "выше EMA200, %": 100 * X.dist, "ширина канала, %": 100 * X.chw, "объём / средний": X.volr,
             "закрытие в свече (0–1)": X.cloc, "RSI14": X.rsi, "фандинг, %": 100 * X.fr_last, "ATR, %": 100 * D.atr / c,
             "ход за 30 баров, %": 100 * (c / np.r_[np.full(30, np.nan), c[:-30]] - 1)}
    win = [t for t in trades if t["net"] > 0]
    los = [t for t in trades if t["net"] <= 0]
    d1 = {}
    for nm, arr in feats.items():
        a = np.array([arr[t["sig"]] for t in win], float)
        b = np.array([arr[t["sig"]] for t in los], float)
        a, b = a[np.isfinite(a)], b[np.isfinite(b)]
        p = float(mannwhitneyu(a, b).pvalue) if len(a) > 3 and len(b) > 3 else None
        d1[nm] = {"плюс": float(np.median(a)), "минус": float(np.median(b)), "p": p}
    # D2: пропущенные движения
    n = X.n
    inpos = np.zeros(n, bool)
    entries = np.zeros(n, bool)
    for t in trades:
        inpos[t["j"]:t["k"]] = True
        entries[t["j"]] = True
    fwd = np.full(n, np.nan)
    fwd[:-21] = o[21:] / o[1:-20] - 1
    big = np.flatnonzero((fwd >= 0.10) & (D.t >= ts("2018-01-01")))
    starts, last = [], -10 ** 9
    for i in big:
        if i - last >= 20:
            starts.append(i)
        last = i
    hi30, ent = D.hi30, D.ent[1]
    cls = {"уже в позиции": 0, "вошли поздно (≤10 баров)": 0, "пропуск: цена ниже EMA200": 0,
           "пропуск: нет нового максимума 30": 0, "пропуск: ADX < 22": 0, "пропуск: пробой < 0.5 ATR": 0, "пропуск: занят/другое": 0}
    late_cost = []
    for s in starts:
        if inpos[s]:
            cls["уже в позиции"] += 1
            continue
        ej = [j for j in range(s + 1, min(s + 12, n)) if entries[j]]
        if ej:
            cls["вошли поздно (≤10 баров)"] += 1
            late_cost.append(o[ej[0]] / o[s + 1] - 1)
            continue
        win_ = range(s, min(s + 11, n))
        brk = [i for i in win_ if c[i] > hi30[i]]
        if not any(c[i] > D.e200[i] for i in win_):
            cls["пропуск: цена ниже EMA200"] += 1
        elif not brk:
            cls["пропуск: нет нового максимума 30"] += 1
        else:
            fails = {"пропуск: цена ниже EMA200": sum(c[i] <= D.e200[i] for i in brk),
                     "пропуск: ADX < 22": sum(D.adx[i] < 22 for i in brk),
                     "пропуск: пробой < 0.5 ATR": sum(D.mag[1][i] < 0.5 for i in brk)}
            key = max(fails, key=fails.get) if max(fails.values()) > 0 else "пропуск: занят/другое"
            cls[key] += 1
    d2 = {"движений_≥10%_за_20_H4": len(starts), "классы": cls,
          "поздний вход: уже прошло, медиана %": 100 * float(np.median(late_cost)) if late_cost else None}
    # D3: ранние выходы
    rows = []
    for t in trades:
        if t["why"] != "время" or t["k"] + 20 >= n:
            continue
        k, i = t["k"], t["k"] - 1
        rows.append({"после": o[k + 20] / o[k] - 1, "у максимумов (≤1 ATR от max 10)": float(c[i] >= X.hh10[i] - D.atr[i]),
                     "ADX растёт за 3": float(D.adx[i] > D.adx[i - 3]), "выше EMA200, %": 100 * X.dist[i],
                     "итог сделки, %": 100 * t["net"]})
    r = pd.DataFrame(rows)
    grp = np.where(r["после"] >= 0.05, "дальше рост ≥5%", np.where(r["после"] <= -0.05, "дальше падение ≥5%", "середина"))
    d3 = r.groupby(grp).agg(["count", "mean"]).round(3)
    return d1, d2, d3


def main():
    args = dict(a.lstrip("-").split("=", 1) for a in sys.argv[1:])
    res = {}
    for sym in ("BTC", "ETH"):
        X = Ctx(Path(args[f"pk-{sym.lower()}"]))
        legs0, tr0 = run2(X, X.D.ent[1])
        ref = run(X.D, 1)
        assert [(t["j"], t["k"]) for t in tr0] == [(u["j"], u["k"]) for u in ref], "run2 ≠ 432"
        b = eq_stats(X.D, legs0)
        out = {"L0": b, "variants": {}}
        V = variants(X)
        for nm, (fam, kw) in V.items():
            lg, tr = run2(X, **kw)
            r = eq_stats(X.D, lg)
            out["variants"][nm] = {"fam": fam, "stats": r, "better_all3": better(r, b),
                                   "c_sum_ok": r["C 08.2024–2026"]["sum"] >= 0.8 * b["C 08.2024–2026"]["sum"],
                                   "better_n": sum(r[p]["ratio"] is not None and r[p]["ratio"] > b[p]["ratio"] for p in PN)}
        out["R2"] = eq_stats(X.D, run2(X, X.D.ent[1], w=X.w_r2)[0])
        if sym == "BTC":
            d1, d2, d3 = diagnostics(X, tr0)
            out["D1"], out["D2"] = d1, d2
            print("\n== D1 плюсовые против минусовых (медианы на сигнале, Манн–Уитни p):")
            for k_, v in d1.items():
                print(f"  {k_}: плюс {v['плюс']:.3f} / минус {v['минус']:.3f}, p {v['p']:.3f}")
            print("\n== D2 пропущенные движения:", json.dumps(d2, ensure_ascii=False))
            print("\n== D3 ранние выходы по времени:\n", d3.to_string())
        res[sym] = out
        X_last = X
    # отбор по семействам
    fams = {}
    for nm, v in res["BTC"]["variants"].items():
        fams.setdefault(v["fam"], []).append(nm)
    passed = {}
    for fam, names in fams.items():
        ok = [nm for nm in names if res["BTC"]["variants"][nm]["better_all3"] and res["BTC"]["variants"][nm]["c_sum_ok"]]
        eth_ok = [nm for nm in names if res["ETH"]["variants"][nm]["better_n"] >= 2]
        if len(ok) >= 2:
            passed[fam] = {"middle": names[1], "btc_pass": ok, "eth_2of3": eth_ok}
    n_pass = sum(1 for v in res["BTC"]["variants"].values() if v["better_all3"] and v["c_sum_ok"])
    print(f"\nвариантов {len(res['BTC']['variants'])}; лучше L0 во всех трёх периодах при C ≥ 80%: {n_pass} "
          f"(случайно ожидалось бы ≈ {len(res['BTC']['variants']) / 8:.0f})")
    print("прошедшие семейства:", json.dumps(passed, ensure_ascii=False))
    print("\n| Вариант | BTC A итог · итог/просадка | B | C | лучше во всех 3 | ETH лучше в периодах из 3 |")
    print("|---|---|---|---|---|---|")
    b = res["BTC"]["L0"]
    print("| L0 исходная | " + " | ".join(f"{b[p]['sum']:+.1f} · {b[p]['ratio']:.2f}" for p in PN) + " | — | — |")
    for nm, v in res["BTC"]["variants"].items():
        r = v["stats"]
        cells = [f"{r[p]['sum']:+.1f} · {r[p]['ratio']:.2f}" if r[p]["ratio"] is not None else f"{r[p]['sum']:+.1f} · —" for p in PN]
        mark = "**да**" if v["better_all3"] and v["c_sum_ok"] else ("да, но C < 80%" if v["better_all3"] else "нет")
        print(f"| {nm} | " + " | ".join(cells) + f" | {mark} | {res['ETH']['variants'][nm]['better_n']} |")
    (OUT / "deep_result.json").write_text(json.dumps({**res, "passed": passed}, ensure_ascii=False, indent=1, default=float))
    return res, passed


if __name__ == "__main__":
    main()
