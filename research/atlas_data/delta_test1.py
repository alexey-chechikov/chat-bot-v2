"""ATLAS 14.10, тест 1: «расхождение дельты агрессора и свечи» на 15m — самостоятельный сигнал.

Правила — docs/ATLAS_DELTA_PROTOCOL_2026-10-14.md (опубликован ДО расчётов, коммит 715a2de). Здесь только реализация;
параметры не подбирались. Свечи, nd и пороги — те же, что у версии Cn теста 2 (research/gold/sweep_backtest.Market).

  - 15m UTC-свечи только из полных 15-минутных групп; nd = (2·taker_buy − объём) / объём свечи (NA при нуле);
  - P10/P90 nd — по всем 15m-свечам 20 предыдущих полных UTC-дней (1440 минут), строго до дня свечи;
  - «div» (протокол): LONG — nd ≤ P10 и close ≥ open; SHORT — nd ≥ P90 и close ≤ open;
    «same» (сравнение): LONG — nd ≤ P10 и close < open; SHORT — nd ≥ P90 и close > open;
  - вход — open минуты начала следующей свечи (рыночный), выход — open минуты начала свечи через 4 после входа (1 ч);
    одна позиция на символ: сигнальная свеча, начавшаяся раньше выхода прошлой сделки, пропускается;
  - расходы WEEX: тейкер 0.048% на обе стороны + проскальзывание 0.02% на каждое рыночное исполнение (×2 — 0.04%);
    результат — доля цены входа (печать — в %);
  - контроль: на каждую сделку — случайная свеча той же 6-ч корзины UTC (по началу свечи) и терциля волатильности
    (диапазон 20 свечей до неё / close предыдущей), торгуется в ту же сторону с тем же входом/выходом; 999 повторов;
    ранг (k+1)/(n+1) среднего после расходов (k — повторов со средним ≥ настоящего);
  - разрез 70/30 по календарю файла (по времени входа); ДИ среднего — бутстрап блоками ISO-недель, 9 999
    (sweep_backtest.week_ci, seed 7); статусы — по протоколу.

    .venv/bin/python3 research/atlas_data/delta_test1.py [BTC] [ETH] [--out=путь.json] [--n-ctl=999]
        [--data-root=/Users/alexeychechikov/code/bot7]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "gold"))
import sweep_backtest as sb  # noqa: E402

SYMS = {"BTC": "BTCUSDT_UM", "ETH": "ETHUSDT_UM"}
TAKER = 0.00048
SLIP = 0.0002
SLIP2 = 2 * SLIP
HOLD = 4                          # свечей удержания: вход open s+1, выход open s+1+HOLD
Q_LO, Q_HI = 0.10, 0.90
VOL_BARS = 20
BUCKET_MS = 6 * sb.HOUR
N_CTL, SEED_CTL, SEED_CI = 999, 21, 7
RANK_MAX, N_MIN = 0.05, 100
RULES = {"div": "расхождение дельты и свечи (протокол)", "same": "крайняя дельта по направлению (сравнение)"}


def thresholds(m):
    """(P10, P90) nd для каждой свечи — по 20 предыдущим полным UTC-дням (только прошлое)."""
    return m.nd_quantile(Q_LO), m.nd_quantile(Q_HI)


def signal_side(m, p10, p90, rule: str = "div"):
    """+1 LONG, −1 SHORT, 0 — нет сигнала (и если свеча попала в оба условия сразу, что возможно лишь при P10 = P90)."""
    nd = m.nd
    fin = np.isfinite(nd)
    with np.errstate(invalid="ignore"):
        lo = fin & np.isfinite(p10) & (nd <= p10)
        hi = fin & np.isfinite(p90) & (nd >= p90)
    if rule == "div":
        lng, sht = lo & (m.b_c >= m.b_o), hi & (m.b_c <= m.b_o)
    elif rule == "same":
        lng, sht = lo & (m.b_c < m.b_o), hi & (m.b_c > m.b_o)
    else:
        raise ValueError(f"неизвестное правило {rule}")
    return lng.astype(np.int8) - sht.astype(np.int8)


def entry_exit(m, hold: int = HOLD):
    """Индексы минут входа (начало свечи s+1) и выхода (начало свечи s+1+hold); −1 — такой минуты в данных нет."""
    ts = m.a["ts"]

    def at(t):
        i = np.searchsorted(ts, t)
        ok = i < len(ts)
        ok[ok] = ts[i[ok]] == t[ok]
        return np.where(ok, i, -1)

    bid = m.b_id.astype(np.int64)
    return at((bid + 1) * sb.BAR), at((bid + 1 + hold) * sb.BAR)


def trade_return(px_in, px_out, side, slip: float = 0.0, taker: float = 0.0):
    """Доля цены входа: исполнения in·(1 + side·slip), out·(1 − side·slip); тейкер с номинала обеих сторон."""
    px_in, px_out, side = (np.asarray(x, dtype=float) for x in (px_in, px_out, side))
    f_in = px_in * (1 + side * slip)
    f_out = px_out * (1 - side * slip)
    return (side * (f_out - f_in) - taker * (f_in + f_out)) / px_in


def run_events(m, side, i_in, i_out, hold: int = HOLD):
    """Одна позиция на символ. Возвращает (индексы свечей сделок, пропущено из-за позиции, пропущено без минут)."""
    taken, busy, no_fill = [], 0, 0
    free_id = None
    for s in np.flatnonzero(side != 0).tolist():
        if free_id is not None and int(m.b_id[s]) < free_id:
            busy += 1
            continue
        if i_in[s] < 0 or i_out[s] < 0:
            no_fill += 1
            continue
        taken.append(s)
        free_id = int(m.b_id[s]) + 1 + hold                          # свеча, начавшаяся в момент выхода, — уже можно
    return np.array(taken, dtype=np.int64), busy, no_fill


def vol_feature(m, n: int = VOL_BARS):
    """(max high − min low) свечей s−n…s−1 / close свечи s−1; NaN, если эти n свечей не идут подряд прямо перед s."""
    h = pd.Series(m.b_h).rolling(n).max().shift(1).to_numpy()
    lo = pd.Series(m.b_l).rolling(n).min().shift(1).to_numpy()
    c = pd.Series(m.b_c).shift(1).to_numpy()
    bid = m.b_id.astype(np.int64)
    contiguous = np.zeros(len(bid), dtype=bool)
    if len(bid) > n:
        contiguous[n:] = (bid[n:] - bid[:-n]) == n
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(contiguous, (h - lo) / c, np.nan)


def bucket6h(m):
    """6-часовая корзина UTC по началу свечи: 0 = 00–06, 1 = 06–12, 2 = 12–18, 3 = 18–24."""
    return ((m.b_id.astype(np.int64) * sb.BAR) % sb.DAY) // BUCKET_MS


def tercile_cuts(vol, mask):
    """Границы терцилей волатильности по свечам `mask` с известной волатильностью (весь период символа)."""
    v = np.asarray(vol, dtype=float)[np.asarray(mask, dtype=bool) & np.isfinite(vol)]
    return np.quantile(v, [1 / 3, 2 / 3])


def tercile(vol, cuts):
    """0/1/2 — терциль; −1 — волатильность неизвестна."""
    vol = np.asarray(vol, dtype=float)
    t = np.searchsorted(np.asarray(cuts, dtype=float), np.where(np.isfinite(vol), vol, 0.0), side="right")
    return np.where(np.isfinite(vol), t, -1)


def matched_means(pool_key, pool_val, target_key, n_ctl: int = N_CTL, seed: int = SEED_CTL):
    """Средние контроля в n_ctl повторах: на каждую цель — случайный элемент пула той же страты (без возвращения внутри
    повтора; если в страте элементов меньше, чем целей, — с возвращением, страта попадает в `thin`)."""
    pool_key = np.asarray(pool_key)
    pool_val = np.asarray(pool_val, dtype=float)
    target_key = np.asarray(target_key)
    if not len(target_key):
        return np.array([]), {}
    rng = np.random.default_rng(seed)
    sums = np.zeros(n_ctl)
    thin = {}
    for k in np.unique(target_key).tolist():
        cnt = int(np.sum(target_key == k))
        vals = pool_val[pool_key == k]
        if not len(vals):
            raise ValueError(f"страта {k}: в пуле контроля нет кандидатов")
        repl = cnt > len(vals)
        if repl:
            thin[int(k)] = [cnt, int(len(vals))]
        for r in range(n_ctl):
            sums[r] += vals[rng.choice(len(vals), size=cnt, replace=repl)].sum()
    return sums / len(target_key), thin


def ctl_rank(real_mean: float, ctl):
    """Ранг (k+1)/(n+1), k — повторов контроля со средним ≥ настоящего; (None, None) — контроля нет."""
    ctl = np.asarray(ctl, dtype=float)
    if not len(ctl) or real_mean is None or not np.isfinite(real_mean):
        return None, None
    k = int(np.sum(ctl >= real_mean))
    return (k + 1) / (len(ctl) + 1), k


def atlas_status(n: int, mean, hold_mean, ci_lo, mean2x, rank) -> tuple[str, str]:
    """Статусы протокола; (статус, причина). Случаи, которых протокол не называет (×2 проскальзывание ≤ 0, ранг > 0.05
    или контроля нет при остальных условиях), — «Недостаточно данных» с причиной, как в коде золота."""
    if not n:
        return "Недостаточно данных", "сделок нет"
    if mean <= 0:
        return "Отвергнута", "после расходов ≤ 0 на всём периоде"
    if hold_mean is not None and hold_mean <= 0:
        return "Отвергнута", "после расходов ≤ 0 на контрольной части"
    if n < N_MIN:
        return "Недостаточно данных", f"n {n} < {N_MIN}"
    if ci_lo is None or ci_lo <= 0:
        return "Недостаточно данных", "ДИ включает 0"
    if hold_mean is None:
        return "Недостаточно данных", "на контрольной части сделок нет"
    if mean2x is None or mean2x <= 0:
        return "Недостаточно данных", "≤ 0 при удвоенном проскальзывании (случай протоколом не назван)"
    if rank is None or rank > RANK_MAX:
        return "Недостаточно данных", "ранг контроля > 0.05 или контроля нет (случай протоколом не назван)"
    return "Кандидат на малый тест исполнения", "все условия выполнены"


def _part(x: list) -> dict:
    if not x:
        return {"n": 0, "gross": None, "net": None, "net2": None}
    return {"n": len(x), "gross": float(np.mean([t["gross"] for t in x])),
            "net": float(np.mean([t["net"] for t in x])), "net2": float(np.mean([t["net2"] for t in x])),
            "wr": float(np.mean([t["net"] > 0 for t in x]))}


def summarize(rec: list, split_ts: int) -> dict:
    if not rec:
        return {"n": 0}
    return {**_part(rec), "ci_net": sb.week_ci(rec, "net", seed=SEED_CI),
            "ci_gross": sb.week_ci(rec, "gross", seed=SEED_CI),
            "n_weeks": len({sb._iso_week(t["entry_ts"]) for t in rec}),
            "dev": _part([t for t in rec if t["entry_ts"] < split_ts]),
            "holdout": _part([t for t in rec if t["entry_ts"] >= split_ts]),
            "by_side": {"LONG": _part([t for t in rec if t["side"] > 0]),
                        "SHORT": _part([t for t in rec if t["side"] < 0])}}


class Prepared:
    """Всё, что нужно обоим тестам по одному символу: свечи, nd, пороги, волатильность, страты, минуты входа/выхода."""

    def __init__(self, a: dict, info: dict, inst: str):
        self.a, self.info, self.inst = a, info, inst
        self.m = m = sb.Market(a, inst, s1=False)
        self.split_ts = int(info["first"] + 0.7 * (info["last"] - info["first"]))
        self.p10, self.p90 = thresholds(m)
        self.i_in, self.i_out = entry_exit(m)
        self.vol = vol_feature(m)
        self.has_thr = np.isfinite(self.p10) & np.isfinite(self.p90)
        self.cuts = tercile_cuts(self.vol, self.has_thr)
        self.terc = tercile(self.vol, self.cuts)
        self.bkt = bucket6h(m)
        self.pool = np.flatnonzero(self.has_thr & (self.terc >= 0) & (self.i_in >= 0) & (self.i_out >= 0))

    def strata(self, idx):
        return self.bkt[idx] * 10 + self.terc[idx]

    def prices(self, idx):
        o = self.a["open"]
        return o[self.i_in[idx]], o[self.i_out[idx]]


def run_rule(p: Prepared, rule: str, n_ctl: int = N_CTL, seed: int = SEED_CTL) -> dict:
    m, ts = p.m, p.a["ts"]
    side = signal_side(m, p.p10, p.p90, rule)
    taken, busy, no_fill = run_events(m, side, p.i_in, p.i_out)
    px_in, px_out = p.prices(taken)
    sd = side[taken].astype(float)
    g = trade_return(px_in, px_out, sd)
    n1 = trade_return(px_in, px_out, sd, SLIP, TAKER)
    n2 = trade_return(px_in, px_out, sd, SLIP2, TAKER)
    rec = [{"sig_ts": int(m.b_id[s] * sb.BAR), "entry_ts": int(ts[p.i_in[s]]), "exit_ts": int(ts[p.i_out[s]]),
            "side": int(side[s]), "entry": float(px_in[j]), "exit": float(px_out[j]), "nd": float(m.nd[s]),
            "p10": float(p.p10[s]), "p90": float(p.p90[s]), "bucket": int(p.bkt[s]), "tercile": int(p.terc[s]),
            "gross": float(g[j]), "net": float(n1[j]), "net2": float(n2[j])} for j, s in enumerate(taken.tolist())]
    st = summarize(rec, p.split_ts)
    # контроль: та же сторона, та же страта (6-ч корзина × терциль), тот же вход/выход
    ok = p.terc[taken] >= 0
    tkey = sd[ok].astype(int) * 100 + p.strata(taken[ok])
    pin, pout = p.prices(p.pool)
    pkey = np.r_[100 + p.strata(p.pool), -100 + p.strata(p.pool)]
    pval = np.r_[trade_return(pin, pout, 1.0, SLIP, TAKER), trade_return(pin, pout, -1.0, SLIP, TAKER)]
    ctl, thin = matched_means(pkey, pval, tkey, n_ctl, seed)
    real_mean = float(np.mean(n1[ok])) if ok.any() else None
    rank, k = ctl_rank(real_mean, ctl)
    control = {"n_real": int(ok.sum()), "no_vol": int((~ok).sum()), "real_mean": real_mean, "done": int(len(ctl)),
               "k": k, "rank": rank, "thin": thin, "pool": int(len(p.pool)),
               "ctl_median": float(np.median(ctl)) if len(ctl) else None,
               "ctl_q05_q95": [float(x) for x in np.percentile(ctl, [5, 95])] if len(ctl) else None}
    if st["n"]:
        stat, why = atlas_status(st["n"], st["net"], st["holdout"]["net"], st["ci_net"][0], st["net2"], rank)
    else:
        stat, why = atlas_status(0, None, None, None, None, None)
    return {"rule": rule, "signals": {"all": int((side != 0).sum()), "LONG": int((side > 0).sum()),
                                      "SHORT": int((side < 0).sum()), "busy": busy, "no_fill": no_fill},
            "stats": st, "control": control, "status": stat, "status_why": why, "trades": rec}


def _pct(x, nd: int = 3) -> str:
    return "—" if x is None else f"{100 * x:+.{nd}f}%"


def _rank(x) -> str:
    return "NA" if x is None else f"{x:.3f}"


def _arg(name: str, default=None):
    return next((x.split("=", 1)[1] for x in sys.argv[1:] if x.startswith(f"--{name}=")), default)


def main() -> None:
    syms = [s for s in sys.argv[1:] if s in SYMS] or list(SYMS)
    root = Path(_arg("data-root", str(sb.ROOT)))
    n_ctl = int(_arg("n-ctl", N_CTL))
    out = _arg("out")
    res = {"protocol": "docs/ATLAS_DELTA_PROTOCOL_2026-10-14.md@715a2de", "taker": TAKER, "slip": SLIP, "slip2": SLIP2,
           "hold_bars": HOLD, "n_ctl": n_ctl, "seed_ctl": SEED_CTL, "seed_ci": SEED_CI, "symbols": {}}
    for sym in syms:
        inst = SYMS[sym]
        a, info = sb.load(inst, root)
        p = Prepared(a, info, inst)
        thr = p.has_thr
        print(f"{sym}: {info['file']} строк {info['rows']}, {pd.Timestamp(info['first'], unit='ms')} … "
              f"{pd.Timestamp(info['last'], unit='ms')} UTC, пропусков минут {info['missing_minutes']}, sha256 "
              f"{info['sha256']}; 15m свечей {len(p.m.b_id)}, с порогами {int(thr.sum())} (с "
              f"{pd.Timestamp(int(p.m.b_id[np.argmax(thr)] * sb.BAR), unit='ms'):%Y-%m-%d}); медиана P10 "
              f"{np.nanmedian(p.p10):+.3f}, P90 {np.nanmedian(p.p90):+.3f}; терцили волатильности "
              f"{p.cuts[0]:.4f}/{p.cuts[1]:.4f}; пул контроля {len(p.pool)}; контрольная часть с "
              f"{pd.Timestamp(p.split_ts, unit='ms'):%Y-%m-%d %H:%M}")
        sres = res["symbols"][sym] = {"info": info, "split_ts": p.split_ts, "cuts": [float(x) for x in p.cuts],
                                      "bars": int(len(p.m.b_id)), "bars_with_thr": int(thr.sum()),
                                      "median_p10": float(np.nanmedian(p.p10)), "median_p90": float(np.nanmedian(p.p90)),
                                      "rules": {}}
        for rule in RULES:
            r = sres["rules"][rule] = run_rule(p, rule, n_ctl)
            st, c, sg = r["stats"], r["control"], r["signals"]
            if not st.get("n"):
                print(f"  {rule}: сделок нет → {r['status']}")
                continue
            bs = st["by_side"]
            print(f"  {rule} ({RULES[rule]}): сигналов {sg['all']} (L {sg['LONG']} / S {sg['SHORT']}), пропущено "
                  f"позицией {sg['busy']}, без минут {sg['no_fill']}; n {st['n']}, WR {st['wr']:.0%}; до расходов "
                  f"{_pct(st['gross'])} [ДИ {_pct(st['ci_gross'][0])}…{_pct(st['ci_gross'][1])}], после "
                  f"{_pct(st['net'])} [ДИ {_pct(st['ci_net'][0])}…{_pct(st['ci_net'][1])}], ×2 проск. {_pct(st['net2'])}; "
                  f"разработка {_pct(st['dev']['net'])} (n {st['dev']['n']}), контроль {_pct(st['holdout']['net'])} "
                  f"(n {st['holdout']['n']}); LONG n {bs['LONG']['n']} до {_pct(bs['LONG']['gross'])} после "
                  f"{_pct(bs['LONG']['net'])}, SHORT n {bs['SHORT']['n']} до {_pct(bs['SHORT']['gross'])} после "
                  f"{_pct(bs['SHORT']['net'])}; случайные свечи: медиана {_pct(c['ctl_median'])}, не хуже "
                  f"{c['k']}/{c['done']}, ранг {_rank(c['rank'])}; недель {st['n_weeks']} → {r['status']} ({r['status_why']})")
        d = sb.paired_week_diff(sres["rules"]["same"]["trades"], sres["rules"]["div"]["trades"], "net")
        sres["div_minus_same"] = d
        if d["diff"] is not None:
            print(f"  div − same (общие ISO-недели {d['weeks']}): {_pct(d['diff'])} "
                  f"[ДИ {_pct(d['ci'][0])}…{_pct(d['ci'][1])}]")
    if out:
        Path(out).write_text(json.dumps(res, ensure_ascii=False, default=float), encoding="utf-8")


if __name__ == "__main__":
    main()
