"""ATLAS 14.10, тест 2: ценовой сетап + добавки на BTCUSDT/ETHUSDT UM (протокол docs/ATLAS_DELTA_PROTOCOL_2026-10-14.md,
коммит 715a2de). Механика — research/gold/sweep_backtest.py без изменений (сетап A протокола золота §3: ложный пробой
минимума прошлого полного UTC-дня на 15m, LONG, подтверждение ≤ 3 свечей, стоп = low сигнальной − 2 тика, цель 2R,
≤ 4 ч, риск 0.25% капитала $3 000, дневной лимит 0.75%), комиссии WEEX, проскальзывание 0.02% (×2 — 0.04%).

Версии: A; B = A + close подтверждающей > дневного VWAP; Cn = B + nd сигнальной свечи ≤ P10 (20 предыдущих полных
UTC-дней, как в тесте 1); En = B + LVN (протокол золота п.4; в коде — версия "E").
Контроль Cn: случайные подвыборки сделок B (тот же прогон: $3 000, после расходов) того же размера, что Cn, с тем же
составом по 6-ч корзинам UTC (начало сигнальной свечи) и терцилям волатильности сигнальной свечи (как в тесте 1:
диапазон 20 свечей до неё / close предыдущей; границы терцилей те же); 999 повторов; ранг (k+1)/(n+1) среднего R.
Статусы — по протоколу ATLAS (delta_test1.atlas_status) в бюджетных R после расходов.

    .venv/bin/python3 research/atlas_data/delta_test2.py [BTC] [ETH] [--out=путь.json] [--n-ctl=999]
        [--data-root=/Users/alexeychechikov/code/bot7]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import delta_test1 as d1  # noqa: E402

sb = d1.sb
VERSIONS = ("A", "B", "Cn", "E")
LABEL = {"A": "A", "B": "B", "Cn": "Cn", "E": "En"}
CAP = 3000.0
SEED_CTL = 31


def sig_index(m, trades: list):
    """Индексы сигнальных свечей сделок (по sig_ts)."""
    want = np.array([t["sig_ts"] // sb.BAR for t in trades], dtype=np.int64)
    idx = np.searchsorted(m.b_id, want)
    if len(idx) and not np.array_equal(m.b_id[np.clip(idx, 0, len(m.b_id) - 1)], want):
        raise ValueError("сигнальная свеча сделки не найдена среди полных свечей")
    return idx


def cn_control(p: d1.Prepared, tr_b: list, tr_c: list, n_ctl: int = d1.N_CTL, seed: int = SEED_CTL) -> dict:
    """Случайные подвыборки ledger B того же размера и состава (6-ч корзина × терциль), что Cn; ранг среднего R Cn."""
    if not tr_c:
        return {"n_real": 0, "rank": None, "k": None, "done": 0}
    ib, ic = sig_index(p.m, tr_b), sig_index(p.m, tr_c)
    okb, okc = p.terc[ib] >= 0, p.terc[ic] >= 0
    kb, kc = p.strata(ib[okb]), p.strata(ic[okc])
    rb = np.array([t["R"] for t in tr_b])[okb]
    rc = np.array([t["R"] for t in tr_c])[okc]
    ctl, thin = d1.matched_means(kb, rb, kc, n_ctl, seed)
    real = float(rc.mean()) if len(rc) else None
    rank, k = d1.ctl_rank(real, ctl)
    b_entries = {t["entry_ts"] for t in tr_b}
    return {"n_real": int(okc.sum()), "no_vol": int((~okc).sum()), "real_mean_R": real, "done": int(len(ctl)), "k": k,
            "rank": rank, "thin": thin, "cn_in_b": int(sum(t["entry_ts"] in b_entries for t in tr_c)),
            "ctl_median_R": float(np.median(ctl)) if len(ctl) else None,
            "ctl_q05_q95_R": [float(x) for x in np.percentile(ctl, [5, 95])] if len(ctl) else None,
            "composition": {int(k_): int(v) for k_, v in zip(*np.unique(kc, return_counts=True))}}


def run_symbol(p: d1.Prepared, n_ctl: int = d1.N_CTL) -> dict:
    m = p.m
    out = {}
    for ver in VERSIONS:
        r = sb.simulate(m, ver, CAP, "net")
        r2 = sb.simulate(m, ver, CAP, "net_2slip")
        st, st2 = sb.stats(r["trades"], CAP, p.split_ts), sb.stats(r2["trades"], CAP, p.split_ts)
        out[ver] = {"stats": st, "stats_2slip": st2, "skipped_min": r["skipped_min"], "capped": r["capped"],
                    "censored": r["censored"], "trades": r["trades"]}
    out["Cn"]["control"] = cn_control(p, out["B"]["trades"], out["Cn"]["trades"], n_ctl)
    for ver in VERSIONS:
        st, st2 = out[ver]["stats"], out[ver]["stats_2slip"]
        rank = out["Cn"]["control"]["rank"] if ver == "Cn" else None
        if st.get("n"):
            s, why = d1.atlas_status(st["n"], st["exp_R"], st["holdout"]["exp_R"], st["ci_R"][0],
                                     st2.get("exp_R"), rank)
        else:
            s, why = d1.atlas_status(0, None, None, None, None, None)
        out[ver]["status"], out[ver]["status_why"] = s, why
    out["cn_minus_b"] = sb.paired_week_diff(out["B"]["trades"], out["Cn"]["trades"], "R")
    out["b_minus_a"] = sb.paired_week_diff(out["A"]["trades"], out["B"]["trades"], "R")
    return out


def _f(x, fmt="+.3f") -> str:
    return "—" if x is None else format(x, fmt)


def _arg(name: str, default=None):
    return next((x.split("=", 1)[1] for x in sys.argv[1:] if x.startswith(f"--{name}=")), default)


def main() -> None:
    syms = [s for s in sys.argv[1:] if s in d1.SYMS] or list(d1.SYMS)
    root = Path(_arg("data-root", str(sb.ROOT)))
    n_ctl = int(_arg("n-ctl", d1.N_CTL))
    path = _arg("out")
    res = {"protocol": "docs/ATLAS_DELTA_PROTOCOL_2026-10-14.md@715a2de", "capital": CAP, "n_ctl": n_ctl,
           "seed_ctl": SEED_CTL, "symbols": {}}
    for sym in syms:
        inst = d1.SYMS[sym]
        a, info = sb.load(inst, root)
        p = d1.Prepared(a, info, inst)
        print(f"{sym}: {info['file']} строк {info['rows']}, sha256 {info['sha256'][:16]}…, контрольная часть с "
              f"{pd.Timestamp(p.split_ts, unit='ms'):%Y-%m-%d %H:%M}; кандидатов (low < L < close) {len(p.m.cand)}")
        out = run_symbol(p, n_ctl)
        res["symbols"][sym] = {"info": info, "split_ts": p.split_ts, **out}
        for ver in VERSIONS:
            v = out[ver]
            st, st2 = v["stats"], v["stats_2slip"]
            if not st.get("n"):
                print(f"  {LABEL[ver]}: сделок нет → {v['status']}")
                continue
            ex = st["exits"]
            print(f"  {LABEL[ver]}: n {st['n']}, WR {st['wr']:.0%}, R после {st['exp_R']:+.3f} "
                  f"[ДИ {st['ci_R'][0]:+.3f}…{st['ci_R'][1]:+.3f}], до расходов {st['exp_R_gross']:+.3f}, ×2 проск. "
                  f"{_f(st2.get('exp_R'))}; ценовой R до {_f(st['exp_pR_gross'])}; разработка {_f(st['dev']['exp_R'])} "
                  f"(n {st['dev']['n']}), контроль {_f(st['holdout']['exp_R'])} (n {st['holdout']['n']}); выходы "
                  f"цель/стоп/время {ex['цель']}/{ex['стоп']}/{ex['время']}; медиана стопа {st['median_stop_pct']:.2%}; "
                  f"$3 000 → ${st['end_eq']:,.0f}; пропущено (мин.) {v['skipped_min']}, урезано {v['capped']} → "
                  f"{v['status']} ({v['status_why']})")
        c = out["Cn"]["control"]
        if c.get("done"):
            print(f"  контроль Cn: подвыборки B того же состава, {c['done']} повторов; Cn {c['real_mean_R']:+.3f}R, "
                  f"медиана контроля {c['ctl_median_R']:+.3f}R, не хуже {c['k']}/{c['done']}, ранг {c['rank']:.3f}; "
                  f"сделок Cn, совпавших со сделками B, {c['cn_in_b']} из {out['Cn']['stats']['n']}; страты с "
                  f"возвращением {c['thin']}")
        for key, lab in (("b_minus_a", "B−A"), ("cn_minus_b", "Cn−B")):
            d = out[key]
            if d["diff"] is not None:
                print(f"  {lab} (общие ISO-недели {d['weeks']}): {d['diff']:+.3f}R [ДИ {d['ci'][0]:+.3f}…{d['ci'][1]:+.3f}]")
    if path:
        Path(path).write_text(json.dumps(res, ensure_ascii=False, default=float), encoding="utf-8")


if __name__ == "__main__":
    main()
