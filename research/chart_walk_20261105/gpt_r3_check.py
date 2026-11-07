"""Проверка цифр и контрпримеров разборов GPT 37233f5 и b4359fe своим кодом. Только расчёт, автомат не меняется."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import cw_data as cw  # noqa: E402
import entry_common as ec  # noqa: E402
import fetch_coins as fc  # noqa: E402
import ledger as lg  # noqa: E402
import portrait_holdout as ph  # noqa: E402
import portrait_holdout2 as p2  # noqa: E402
import pos  # noqa: E402
import words as wd  # noqa: E402
import words2 as w2  # noqa: E402

pd.set_option("display.width", 240, "display.max_columns", 30, "display.max_rows", 80)
A5 = {"gate": "shorts"}
OLD = cw.T("2025-01-01")


def zero_shift(coin, a, fm, legs):
    b = a["i0"]
    c0, f0 = a["c"][b:], fm[b:]
    tot = 0.0
    for i0, i1, p0, p1, s, *_ in legs:
        p1c = c0[i1 - b]
        tot += (s * (p1c / p0 - 1) - lg.SIDE_COST - (p1c / p0) * lg.SIDE_COST - s * (f0[i1 - b] - f0[i0 - b]) / p0) * 100
    real = sum(w2.net(fm, x) for x in legs)
    tgt = sum(1 for x in legs if abs(x[3] - a["c"][x[1]]) > 1e-9)
    return {"ряд": coin, "сделок": len(legs), "сделок_не_по_закрытию": tgt, "учёт": round(real, 1), "ноль_сдвига": round(tot, 1), "разница": round(real - tot, 1)}


def paired(a, fm, legs):
    """Каждый лонговый вход: прежний выход против первого подтверждения G4/R1 раньше него."""
    rows = []
    for x in legs:
        i0, i1, p0, p1, s, tag, why = x
        if s != 1:
            continue
        k = np.where((a["f_run_G"][i0 + 1:i1] <= -2) & (a["run_R"][i0 + 1:i1] <= -3))[0]
        new = (i0, i0 + 1 + int(k[0]), p0, float(a["c"][i0 + 1 + int(k[0])]), 1) if len(k) else x[:5]
        rising = a["f_B"][i0] > a["f_B"][max(i0 - 120, 0)]
        g, y, r = a["f_G"][i0], a["f_Y"][i0], a["f_R"][i0]
        rows.append({"t0": a["t"][i0], "тип": tag, "рост_B4": rising, "вниз": g < y < r, "вверх": g > y > r, "портрет": w2.in_portrait(a, i0, 1), "старый": w2.net(fm, x), "новый": w2.net(fm, new), "раньше": len(k) > 0})
    return pd.DataFrame(rows)


def label_ctl(a, fm, legs, reps=1999, seed=20261105):
    sh = [x for x in legs if x[4] == -1]
    r = np.array([w2.net(fm, x) for x in sh])
    lab = np.array([w2.in_portrait(a, x[0], -1) for x in sh])
    yrs = np.array([pd.Timestamp(int(a["t"][x[0]]), unit="s").year for x in sh])
    rng = np.random.default_rng(seed)
    out = np.zeros(reps)
    for k in range(reps):
        m = lab.copy()
        for y in np.unique(yrs):
            w = np.where(yrs == y)[0]
            m[w] = rng.permutation(lab[w])
        out[k] = r[m].sum()
    return {"описано": int(lab.sum()), "из": len(sh), "сумма": round(float(r[lab].sum()), 2), "медиана": round(float(np.median(out)), 2), "низ": round(float(np.quantile(out, .025)), 2), "верх": round(float(np.quantile(out, .975)), 2), "лучше_%": round(float((out < r[lab].sum()).mean() * 100), 1)}


def contexts(a, fm, legs):
    rows = []
    for x in legs:
        if x[4] != 1 or a["t"][x[0]] < OLD:
            continue
        i0 = x[0]
        g, y, r = a["f_G"][i0], a["f_Y"][i0], a["f_R"][i0]
        if x[5] == "к голубой":
            k = "восстановление"
        elif w2.in_portrait(a, i0, 1) and g > y > r:
            k = "сформированный"
        else:
            k = "раннее"
        rows.append({"к": k, "r": w2.net(fm, x)})
    d = pd.DataFrame(rows)
    return d.groupby("к")["r"].agg(["size", "sum"]).round(2)


def half_full(a, fm, legs):
    out = [x for x in legs if x[4] == 1 and not w2.in_portrait(a, x[0], 1)]
    keep = [x for x in legs if not (x[4] == 1 and not w2.in_portrait(a, x[0], 1))]
    e1 = lg.equity(a, fm, [x[:5] for x in keep])
    e2 = lg.equity(a, fm, [x[:5] for x in out])
    b, t = a["i0"], a["t"]
    res = {}
    for lab, w in (("полный", 1.0), ("половина", 0.5)):
        eq, worst = e1[0] + w * e2[0], e1[1] + w * e2[1]
        res[lab] = (round(float(sum(w2.net(fm, x) for x in keep) + w * sum(w2.net(fm, x) for x in out)), 2), round(lg.drawdown(eq[b:], worst[b:], t[b:])[0] / lg.NOTIONAL * 100, 2))
    return res


def daily(a, fm, legs, days):
    eq = lg.equity(a, fm, [x[:5] for x in legs])[0] / lg.NOTIONAL * 100
    d = pd.Series(eq, index=pd.to_datetime(a["t"], unit="s")).resample("1D").last().ffill()
    return d.reindex(days).ffill().diff().fillna(0.0).to_numpy()


def factors():
    start, end = "2021-04-14", "2026-11-04"
    days = pd.date_range(start, end, freq="1D")
    diffs, px = {}, {}
    for c in p2.COINS2:
        a, fm = ph.load(c + "USDT")
        diffs[c] = daily(a, fm, w2.run(a, **A5), days) - daily(a, fm, wd.run(a), days)
        px[c] = pd.Series(a["c"], index=pd.to_datetime(a["t"], unit="s")).resample("1D").last().ffill().reindex(days).ffill().pct_change().fillna(0.0).to_numpy()
    D = pd.DataFrame(diffs, index=days)
    P = pd.DataFrame(px, index=days)
    corr = P.corr().to_numpy()
    avg = corr[np.triu_indices(10, 1)].mean()
    ev = np.linalg.eigvalsh(corr)[::-1]
    m = D.mean(axis=1).to_numpy()
    res = {"корр_цен": round(float(avg), 3), "первый_фактор_%": round(float(ev[0] / 10 * 100), 1), "сумма_A−v1_на_монету": round(float(m.sum()), 2)}
    rng = np.random.default_rng(20261105)
    for lab, mm in (("всё", m), ("с2025", m[days >= pd.Timestamp("2025-01-01")])):
        n, bl = len(mm), 30
        cs = np.r_[0.0, np.cumsum(np.r_[mm, mm])]
        k = int(np.ceil(n / bl))
        st = rng.integers(0, n, size=(1999, k))
        tot = (cs[st + bl] - cs[st]).sum(axis=1) * (n / (k * bl))
        res[lab] = (round(float(mm.sum()), 2), round(float(np.quantile(tot, .025)), 2), round(float(np.quantile(tot, .975)), 2))
    return res


def flat_shares(a):
    ec.extras(a)
    c, atr = a["c"], a["atr4"]
    g, y, b1 = a["f_G"], a["f_Y"], a["B1h"]
    comp = (np.abs(g - y) <= 0.75 * atr) & (a["x_cross"] > 0)
    dg = np.abs(g - np.r_[np.full(24, np.nan), g[:-24]]) <= 0.5 * atr
    dy = np.abs(y - np.r_[np.full(24, np.nan), y[:-24]]) <= 0.5 * atr
    s = pd.Series(c)
    er = (s - s.shift(24)).abs() / s.diff().abs().rolling(24).sum()
    hi, lo = pd.Series(a["h"]).rolling(24).max().shift(1).to_numpy(), pd.Series(a["l"]).rolling(24).min().shift(1).to_numpy()
    inside = (c <= hi + 0.25 * atr) & (c >= lo - 0.25 * atr)
    loc = comp & dg & dy & (er.to_numpy() <= 0.35) & (np.abs(c - b1) <= 1.5 * atr) & inside
    t = a["t"]
    rows = []
    for x, z in (("2025-12-05", "2026-01-04"), ("2025-12-22", "2026-01-04"), ("2026-07-01", "2026-07-06"), ("2026-07-10", "2026-07-22")):
        m = (t >= cw.T(x)) & (t < cw.T(z))
        rows.append({"окно": f"{x} — {z}", "сжатие_%": round(float(comp[m].mean() * 100), 1), "диапазон_%": round(float(loc[m].mean() * 100), 1)})
    return pd.DataFrame(rows)


def main():
    series = ec.load_all()
    S = {k: (a, f) for k, a, f in series}
    print("== нулевой сдвиг против учёта", flush=True)
    print(pd.DataFrame([zero_shift(k, a, f, wd.run(a)) for k, a, f in series] + [zero_shift(k + " A", a, f, w2.run(a, **A5)) for k, a, f in series]).to_string(index=False), flush=True)
    print("== пропуски часов и выплаты после конца", flush=True)
    rows = []
    for k, a, f in series:
        dt = np.diff(a["t"])
        rows.append({"ряд": k, "разрывов": int((dt != 3600).sum()), "наибольший_ч": int(dt.max() // 3600)})
    print(pd.DataFrame(rows).to_string(index=False), flush=True)
    n_late = []
    for c in fc.COINS + p2.COINS2:
        r = pd.read_csv(fc.DIR / f"{c}USDT_funding.csv")
        b = pd.read_csv(fc.DIR / f"{c}USDT_1h.csv")
        late = r[r["ms"] >= b["ms"].iloc[-1] + 3600_000]
        n_late.append({"монета": c, "выплат_после_конца": len(late), "ставка_сумма_%": round(float(late["rate"].sum() * 100), 4)})
    print(pd.DataFrame(n_late).to_string(index=False), flush=True)
    print("== половина в полной книге: BTC +217.80→+230.13, −102.45→−73.07; ETH +284.82→+269.82, −182.99→−133.80", flush=True)
    for k in ("BTC", "ETH"):
        print(k, half_full(*S[k][:2], wd.run(S[k][0])), flush=True)
    print("== контексты A 2025–26: сформированный BTC 14/+11.66 ETH 9/+22.84; восстановление 87/−16.78 75/−97.98; раннее 43/−37.56 51/−14.19", flush=True)
    for k in ("BTC", "ETH"):
        print(k, contexts(*S[k], w2.run(S[k][0], **A5)).to_dict("index"), flush=True)
    print("== метка на замороженных шортах: BTC 330/551 +131.56 медиана +27.71 −62.20…+121.58; ETH 336/557 +75.79 +2.17 −110.89…+116.68", flush=True)
    for k in ("BTC", "ETH"):
        print(k, label_ctl(*S[k], wd.run(S[k][0])), flush=True)
    print("== пара выходов на тех же входах", flush=True)
    rows = []
    for k, a, f in series:
        d = paired(a, f, wd.run(a))
        new = d["t0"] >= OLD
        for lab, m in (("к B4, B4 падает, G<Y<R", (d["тип"] == "к голубой") & ~d["рост_B4"] & d["вниз"]), ("к B4, остальные", (d["тип"] == "к голубой") & ~(~d["рост_B4"] & d["вниз"])), ("портрет", d["портрет"]), ("над голубыми, цветные вверх, B4 падает", (d["тип"] != "к голубой") & d["вверх"] & ~d["рост_B4"])):
            for per, mm in (("до 2025", ~new), ("2025–26", new)):
                g = d[m & mm]
                rows.append({"ряд": k, "контекст": lab, "период": per, "n": len(g), "старый": round(g["старый"].sum(), 2), "новый": round(g["новый"].sum(), 2), "разница": round((g["новый"] - g["старый"]).sum(), 2)})
    t = pd.DataFrame(rows)
    t.to_csv(pos.OUT / "gpt_r3_paired.csv", index=False)
    print(t.to_string(index=False), flush=True)
    print("== флет, BTC: 54.4/30.0, 98.7/60.6, 53.3/12.5, 70.8/8.7", flush=True)
    print(flat_shares(S["BTC"][0]).to_string(index=False), flush=True)
    print("== общие факторы вторая партия: корр 0.617, фактор 65.6%, +62.41 −18.31…+149.47, с2025 −1.29 −46.06…+39.14", flush=True)
    print(factors(), flush=True)
    d2 = pd.read_csv(pos.OUT / "portrait_holdout2.csv")
    print("== счёт сделок вторая партия", d2[["монета", "v1_n", "A_n", "A_итог"]].to_dict("records"), flush=True)


if __name__ == "__main__":
    main()
