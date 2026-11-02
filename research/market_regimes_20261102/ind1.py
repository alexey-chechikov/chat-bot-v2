"""Индикатор-кандидат IND-1 (PREREG.md): 4H зона +1 → лонг-сетка (U1), −1 → шорт-сетка (D1), зона 0 и spread<0.6 →
две сетки (F1), иначе ожидание. Итог = сумма трёх правил (эпизоды не пересекаются по времени между правилами).
Контроль: в каждом из 999 повторов — случайные эпизоды той же длины и стороны для ВСЕХ трёх правил одновременно,
сумма; ранг (k+1)/(n+1). Плюс вариант «выключать в плюсе» (D1+, U1+, F1+) и кривые капитала по дням против
постоянных вариантов (всегда лонг / две сетки / лонг по SMA100 ±2%). Ничего не подбирается."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import gridk  # noqa: E402
import mr_data as md  # noqa: E402
import regime_rules as rr  # noqa: E402

DAY = 86400


def main():
    m, h1, h4, d1, fund = md.build()
    t_end = int(m["ts"].iloc[-1]) + 60
    mk = gridk.Market(m["ts"].to_numpy(), m["open"].to_numpy(), m["high"].to_numpy(), m["low"].to_numpy(),
                      m["close"].to_numpy(), fund)
    E, _ = rr.build_episodes(h1, h4, d1, t_end)
    P = rr.plus_variant(E, h4, t_end)
    lo = rr.PERIODS["A"][0]
    out = {}
    curves = {}
    for tag, parts in (("IND-1", [("U1", E, False), ("D1", E, False), ("F1", E, False)]),
                       ("IND-1+", [("U1+", P, True), ("D1+", P, True), ("F1+", P, True)])):
        rng = np.random.default_rng(20261102)
        real = {p: 0.0 for p in rr.PERIODS}
        halves = {"A1": 0.0, "A2": 0.0, "B1": 0.0, "B2": 0.0}
        ctl = {p: np.zeros(999) for p in rr.PERIODS}
        ep_net, ep_t = [], []
        for nm, src, plus in parts:
            eps = [e for e in src[nm] if e[0] >= lo and e[1] > e[0]]
            cap = rr.CAP2 if nm.startswith("F") else rr.CAP1
            a, on_d, tot_d, s, res = rr.evaluate(mk, eps, cap, None, plus)
            per = np.array([rr.period_of(x) for x in a])
            for p in rr.PERIODS:
                real[p] += float(res[per == p, 0].sum())
            for p, cut in rr.HALF.items():
                halves[f"{p}1"] += float(res[(per == p) & (a < cut), 0].sum())
                halves[f"{p}2"] += float(res[(per == p) & (a >= cut), 0].sum())
            c = rr.control(mk, a, on_d, tot_d, s, cap, plus, None, rng, 999, t_end)
            for p in rr.PERIODS:
                ctl[p] += c[p]
            ep_net += list(res[:, 0])
            ep_t += list(mk.ts[np.minimum(res[:, 10].astype(int), mk.n - 1)])
        ab_real = real["A"] + real["B"]
        ab_ctl = ctl["A"] + ctl["B"]
        out[tag] = {"итог": {p: round(v, 1) for p, v in real.items()}, "половины": {k: round(v, 1) for k, v in halves.items()},
                    "A∪B": round(ab_real, 1),
                    "ранг_A∪B": round((int((ab_ctl >= ab_real).sum()) + 1) / 1000, 3),
                    "контроль_A∪B_медиана": round(float(np.median(ab_ctl)), 1),
                    "контроль_A∪B_10–90": [round(float(np.quantile(ab_ctl, q)), 1) for q in (.1, .9)],
                    "ранги_по_периодам": {p: round((int((ctl[p] >= real[p]).sum()) + 1) / 1000, 3) for p in rr.PERIODS}}
        order = np.argsort(ep_t)
        cum = np.cumsum(np.array(ep_net)[order])
        curves[tag] = (np.array(ep_t)[order], cum)
        dd = float((cum - np.maximum.accumulate(np.r_[0, cum])[1:]).min())
        out[tag]["просадка_по_закрытиям_эпизодов"] = round(dd, 1)
        print(tag, json.dumps(out[tag], ensure_ascii=False), flush=True)
    # постоянные варианты одним эпизодом на всё A∪B∪C — для кривой и просадки
    i0, i1 = mk.idx([lo]), mk.idx([t_end])
    for nm, side, cap in (("всегда лонг", 1, rr.CAP1), ("всегда шорт", -1, rr.CAP1)):
        r = mk.run(i0, i1, side, cap=cap)[0]
        out[nm + " 2018→сейчас"] = {"итог": round(float(r[0]), 1), "просадка": round(float(r[6]), 1),
                                    "мешок": round(float(r[5]), 1)}
        print(nm, out[nm + " 2018→сейчас"])
    (HERE / "out" / "ind1_result.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    try:
        plot(curves, out)
    except Exception as e:                                  # картинка — не обязательна
        print("график не построен:", e)


def plot(curves, out):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(10, 4.5), dpi=110)
    for tag, (t, cum) in curves.items():
        ax.step(pd.to_datetime(t, unit="s"), cum, where="post", label=f"{tag}: {cum[-1]:+.0f}$")
    for x in ("2024-05-15", "2026-05-01"):
        ax.axvline(pd.Timestamp(x), color="#888", lw=0.8, ls="--")
    ax.axhline(0, color="#444", lw=0.6)
    ax.set_title("IND-1 (зоны v11 4H → лонг/шорт/две сетки 0.6/1.4) — полный капитал по закрытию эпизодов, $")
    ax.legend(loc="upper left")
    ax.text(0.99, 0.02, "периоды: A 2018–05.2024 | B 05.2024–04.2026 | C 05–11.2026 (в выборке)",
            transform=ax.transAxes, ha="right", fontsize=8, color="#555")
    fig.tight_layout()
    fig.savefig(HERE / "out" / "ind1_curve.png")


if __name__ == "__main__":
    main()
