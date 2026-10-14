"""ATLAS 14.10, footprint: правило F «дельта агрессора в фитиле» на 15m + диагностика против теста 1.

Правила — docs/ATLAS_FOOTPRINT_PROTOCOL_2026-10-14.md (дополнение, коммит 18bc3db) к docs/ATLAS_DELTA_PROTOCOL_2026-10-14.md
(715a2de, исполнение/контроль/статусы — как тест 1). Здесь только реализация; параметры не подбирались.

  - свечи — backtests/aggtrades/<SYM>_15m_footprint.csv (research/atlas_data/footprint_bars.py, сверка пройдена);
  - wl = (покупки − продажи агрессоров с ценой ≤ min(open, close)) / объём свечи, wu — то же для ≥ max(open, close);
    фитиль пустой (сигнала нет, в пороги не входит), если сделок строго за краем тела нет, т. е. low = min(open, close)
    (high = max(open, close)) [формализация: по букве «≤» фитиль никогда не пуст — в нём всегда сделка open или close];
  - P10 wl / P90 wu — по всем свечам с непустым фитилём 20 предыдущих полных UTC-дней (96 свечей), строго до дня свечи;
  - LONG: wl ≤ P10 и close ≥ open; SHORT: wu ≥ P90 и close ≤ open; свеча в обоих условиях — без сигнала (как тест 1);
  - сигналы — свечи 2026-09-08 … 2026-10-13 UTC; вход — open свечи s+1 (из сделок), выход — open свечи s+5 (1 ч);
    нет такой свечи — сигнал пропускается; одна позиция на символ (delta_test1.run_events);
  - расходы, контроль (999, 6-ч корзина × терциль волатильности 20 прошлых свечей; терцили — по свечам окна сигналов),
    ДИ по ISO-неделям (9 999), разрез 70/30 по календарю окна сигналов, статусы — функции delta_test1;
  - диагностика (без статусов): корреляция wl/wu с nd всей свечи (минутные свечи, как тест 1), доля сигналов F,
    совпавших с сигналами теста 1 (та же свеча и сторона), тест 1 (div и same) на том же окне сигналов.

    .venv/bin/python3 -I research/atlas_data/footprint_test.py [BTC] [ETH] [--out=путь.json] [--n-ctl=999]
        [--data-root=/Users/alexeychechikov/code/bot7]
"""
from __future__ import annotations

import hashlib
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
for _p in (HERE, HERE.parent / "gold"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import delta_test1 as d1  # noqa: E402
import sweep_backtest as sb  # noqa: E402

SYMS = {"BTC": ("BTCUSDT", "BTCUSDT_UM"), "ETH": ("ETHUSDT", "ETHUSDT_UM")}
SIG_FROM, SIG_TO = "2026-09-08", "2026-10-13"       # дни сигнальных свечей UTC, включительно
N_DAYS, BARS_PER_DAY = 20, 96
Q_LO, Q_HI = d1.Q_LO, d1.Q_HI
HOLD = d1.HOLD
TAKER, SLIP, SLIP2 = d1.TAKER, d1.SLIP, d1.SLIP2
N_CTL, SEED_CTL, SEED_CI = d1.N_CTL, d1.SEED_CTL, d1.SEED_CI


def day_of(s: str) -> int:
    return int(pd.Timestamp(s, tz="UTC").value // 10 ** 6) // sb.DAY


def window_split(first: str = SIG_FROM, last: str = SIG_TO) -> int:
    """Граница 70/30 по календарю окна сигналов (как в тесте 1: первая минута + 0.7 × (последняя − первая))."""
    t0 = day_of(first) * sb.DAY
    t1 = (day_of(last) + 1) * sb.DAY - sb.MIN
    return int(t0 + 0.7 * (t1 - t0))


class FootBars:
    """15m-свечи из сделок: wl / wu, пустые фитили, пороги P10 / P90 только по прошлому."""

    def __init__(self, df: pd.DataFrame, n_days: int = N_DAYS):
        df = df.sort_values("bar_ts").reset_index(drop=True)
        self.df = df
        self.b_id = df["bar_ts"].to_numpy(dtype=np.int64) // sb.BAR
        if len(self.b_id) > 1 and np.any(np.diff(self.b_id) <= 0):
            raise ValueError("свечи повторяются")
        f = {k: df[k].to_numpy(dtype=float) for k in ("o", "h", "l", "c", "volume", "buy", "sell", "lw_buy",
                                                         "lw_sell", "uw_buy", "uw_sell")}
        self.b_o, self.b_h, self.b_l, self.b_c, self.v = f["o"], f["h"], f["l"], f["c"], f["volume"]
        lo_e, hi_e = np.minimum(self.b_o, self.b_c), np.maximum(self.b_o, self.b_c)
        self.lw_ok = df["lw_strict_n"].to_numpy() > 0
        self.uw_ok = df["uw_strict_n"].to_numpy() > 0
        if np.any(self.lw_ok != (self.b_l < lo_e)) or np.any(self.uw_ok != (self.b_h > hi_e)):
            raise ValueError("число сделок за краем тела не согласуется с low/high")
        pos = self.v > 0
        with np.errstate(invalid="ignore", divide="ignore"):
            den = np.where(pos, self.v, 1.0)
            self.wl = np.where(self.lw_ok & pos, (f["lw_buy"] - f["lw_sell"]) / den, np.nan)
            self.wu = np.where(self.uw_ok & pos, (f["uw_buy"] - f["uw_sell"]) / den, np.nan)
            self.nd_tr = np.where(pos, (f["buy"] - f["sell"]) / den, np.nan)
        self.bar_day = (self.b_id * sb.BAR) // sb.DAY
        days, cnt = np.unique(self.bar_day, return_counts=True)
        self.complete_days = days[cnt == BARS_PER_DAY].tolist()
        self.p10 = sb.prior_days_quantile(self.bar_day, self.wl, self.complete_days, Q_LO, n_days)
        self.p90 = sb.prior_days_quantile(self.bar_day, self.wu, self.complete_days, Q_HI, n_days)
        self.has_thr = np.isfinite(self.p10) & np.isfinite(self.p90)


def f_signal(fb: FootBars):
    """+1 LONG, −1 SHORT, 0 — нет; второе значение — маска свечей в обоих условиях сразу (сигнала не дают)."""
    with np.errstate(invalid="ignore"):
        lo = np.isfinite(fb.wl) & np.isfinite(fb.p10) & (fb.wl <= fb.p10)
        hi = np.isfinite(fb.wu) & np.isfinite(fb.p90) & (fb.wu >= fb.p90)
    lng, sht = lo & (fb.b_c >= fb.b_o), hi & (fb.b_c <= fb.b_o)
    return lng.astype(np.int8) - sht.astype(np.int8), lng & sht


def open_at(b_id, b_o, k: int):
    """open свечи b_id + k; NaN, если такой свечи нет."""
    b_id = np.asarray(b_id, dtype=np.int64)
    tgt = b_id + k
    i = np.searchsorted(b_id, tgt)
    ok = i < len(b_id)
    ok[ok] = b_id[i[ok]] == tgt[ok]
    return np.where(ok, np.asarray(b_o, dtype=float)[np.clip(i, 0, max(len(b_id) - 1, 0))], np.nan)


def evaluate(b_id, side, px_in, px_out, vol, window, has_thr, split_ts: int, value=None,
             n_ctl: int = N_CTL, seed: int = SEED_CTL) -> dict:
    """Одна позиция, расходы, сводка, контроль по стратам и статус — общий путь для F и теста 1 на одном окне.
    side — по всем свечам, сигналы вне `window` обнуляются; px_in/px_out — цены входа/выхода по свечам (NaN — нет)."""
    b_id = np.asarray(b_id, dtype=np.int64)
    window = np.asarray(window, dtype=bool)
    side = np.where(window, np.asarray(side), 0).astype(np.int8)
    px_in, px_out = np.asarray(px_in, dtype=float), np.asarray(px_out, dtype=float)
    ok_in, ok_out = np.isfinite(px_in), np.isfinite(px_out)
    taken, busy, no_fill = d1.run_events(SimpleNamespace(b_id=b_id), side, np.where(ok_in, 0, -1),
                                         np.where(ok_out, 0, -1), HOLD)
    pi, po = px_in[taken], px_out[taken]
    sd = side[taken].astype(float)
    g = d1.trade_return(pi, po, sd)
    n1 = d1.trade_return(pi, po, sd, SLIP, TAKER)
    n2 = d1.trade_return(pi, po, sd, SLIP2, TAKER)
    cuts = d1.tercile_cuts(vol, window & has_thr)
    terc = d1.tercile(vol, cuts)
    bkt = ((b_id * sb.BAR) % sb.DAY) // d1.BUCKET_MS
    val = np.full(len(b_id), np.nan) if value is None else np.asarray(value, dtype=float)
    rec = [{"sig_ts": int(b_id[s] * sb.BAR), "entry_ts": int((b_id[s] + 1) * sb.BAR),
            "exit_ts": int((b_id[s] + 1 + HOLD) * sb.BAR), "side": int(side[s]), "entry": float(pi[j]),
            "exit": float(po[j]), "value": float(val[s]), "bucket": int(bkt[s]), "tercile": int(terc[s]),
            "gross": float(g[j]), "net": float(n1[j]), "net2": float(n2[j])} for j, s in enumerate(taken.tolist())]
    st = d1.summarize(rec, split_ts)
    pool = np.flatnonzero(window & has_thr & (terc >= 0) & ok_in & ok_out)
    strata = bkt * 10 + terc
    ok = terc[taken] >= 0
    tkey = sd[ok].astype(int) * 100 + strata[taken[ok]]
    pkey = np.r_[100 + strata[pool], -100 + strata[pool]]
    pval = np.r_[d1.trade_return(px_in[pool], px_out[pool], 1.0, SLIP, TAKER),
                 d1.trade_return(px_in[pool], px_out[pool], -1.0, SLIP, TAKER)]
    ctl, thin = d1.matched_means(pkey, pval, tkey, n_ctl, seed)
    real_mean = float(np.mean(n1[ok])) if ok.any() else None
    rank, k = d1.ctl_rank(real_mean, ctl)
    control = {"n_real": int(ok.sum()), "no_vol": int((~ok).sum()), "real_mean": real_mean, "done": int(len(ctl)),
               "k": k, "rank": rank, "thin": thin, "pool": int(len(pool)), "cuts": [float(x) for x in cuts],
               "ctl_median": float(np.median(ctl)) if len(ctl) else None,
               "ctl_q05_q95": [float(x) for x in np.percentile(ctl, [5, 95])] if len(ctl) else None}
    if st["n"]:
        stat, why = d1.atlas_status(st["n"], st["net"], st["holdout"]["net"], st["ci_net"][0], st["net2"], rank)
    else:
        stat, why = d1.atlas_status(0, None, None, None, None, None)
    return {"signals": {"all": int((side != 0).sum()), "LONG": int((side > 0).sum()), "SHORT": int((side < 0).sum()),
                        "busy": busy, "no_fill": no_fill},
            "stats": st, "control": control, "status": stat, "status_why": why, "trades": rec}


def corr(x, y) -> dict:
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    ok = np.isfinite(x) & np.isfinite(y)
    if ok.sum() < 3:
        return {"n": int(ok.sum()), "pearson": None, "spearman": None}
    xs, ys = pd.Series(x[ok]), pd.Series(y[ok])
    return {"n": int(ok.sum()), "pearson": float(xs.corr(ys)), "spearman": float(xs.rank().corr(ys.rank()))}


def map_by_bar(src_id, src_val, dst_id, fill=np.nan):
    """Значения src (по свечам src_id) на свечи dst_id; нет свечи — fill."""
    src_id = np.asarray(src_id, dtype=np.int64)
    dst_id = np.asarray(dst_id, dtype=np.int64)
    i = np.searchsorted(src_id, dst_id)
    ok = i < len(src_id)
    ok[ok] = src_id[i[ok]] == dst_id[ok]
    out = np.full(len(dst_id), fill, dtype=float)
    out[ok] = np.asarray(src_val, dtype=float)[i[ok]]
    return out


def overlap(f_side, t_side, color_up, color_dn) -> dict:
    """Доля сигналов F, совпавших с сигналами теста 1 той же стороны на той же свече; ожидание при независимости —
    nF × доля сигналов теста 1 среди свечей окна того же цвета (≥ / ≤)."""
    out = {}
    for name, sg, col in (("LONG", 1, color_up), ("SHORT", -1, color_dn)):
        f, t = f_side == sg, t_side == sg
        n_f, n_t, both = int(f.sum()), int(t.sum()), int((f & t).sum())
        rate = float(t.sum() / max(int(col.sum()), 1))
        out[name] = {"F": n_f, "T1": n_t, "both": both, "share_of_F": both / n_f if n_f else None,
                     "share_of_T1": both / n_t if n_t else None, "expected_if_indep": n_f * rate}
    n_f = out["LONG"]["F"] + out["SHORT"]["F"]
    both = out["LONG"]["both"] + out["SHORT"]["both"]
    out["all"] = {"F": n_f, "T1": out["LONG"]["T1"] + out["SHORT"]["T1"], "both": both,
                  "share_of_F": both / n_f if n_f else None,
                  "expected_if_indep": out["LONG"]["expected_if_indep"] + out["SHORT"]["expected_if_indep"]}
    return out


def _pct(x, nd: int = 3) -> str:
    return "—" if x is None else f"{100 * x:+.{nd}f}%"


def _line(tag: str, r: dict) -> str:
    st, c, sg = r["stats"], r["control"], r["signals"]
    if not st.get("n"):
        return f"  {tag}: сигналов {sg['all']}, сделок нет → {r['status']}"
    bs = st["by_side"]
    return (f"  {tag}: сигналов {sg['all']} (L {sg['LONG']} / S {sg['SHORT']}), пропущено позицией {sg['busy']}, без "
            f"свечи выхода {sg['no_fill']}; n {st['n']}, WR {st['wr']:.0%}; до {_pct(st['gross'])} [ДИ "
            f"{_pct(st['ci_gross'][0])}…{_pct(st['ci_gross'][1])}], после {_pct(st['net'])} [ДИ "
            f"{_pct(st['ci_net'][0])}…{_pct(st['ci_net'][1])}], ×2 {_pct(st['net2'])}; разработка "
            f"{_pct(st['dev']['net'])} (n {st['dev']['n']}), контрольная часть {_pct(st['holdout']['net'])} "
            f"(n {st['holdout']['n']}); LONG n {bs['LONG']['n']} до {_pct(bs['LONG']['gross'])} после "
            f"{_pct(bs['LONG']['net'])}, SHORT n {bs['SHORT']['n']} до {_pct(bs['SHORT']['gross'])} после "
            f"{_pct(bs['SHORT']['net'])}; контроль медиана {_pct(c['ctl_median'])}, не хуже {c['k']}/{c['done']}, "
            f"ранг {d1._rank(c['rank'])}, тонких страт {len(c['thin'])}; недель {st['n_weeks']} → {r['status']} "
            f"({r['status_why']})")


def _arg(name: str, default=None):
    return next((x.split("=", 1)[1] for x in sys.argv[1:] if x.startswith(f"--{name}=")), default)


def run_symbol(sym: str, root: Path, n_ctl: int = N_CTL) -> dict:
    tsym, inst = SYMS[sym]
    fp = root / "backtests" / "aggtrades" / f"{tsym}_15m_footprint.csv"
    integ = json.loads((root / "backtests" / "aggtrades" / f"{tsym}_footprint_integrity.json").read_text(encoding="utf-8"))
    raw = fp.read_bytes()
    fb = FootBars(pd.read_csv(io.BytesIO(raw)))
    split_ts = window_split()
    d_lo, d_hi = day_of(SIG_FROM), day_of(SIG_TO)
    win = (fb.bar_day >= d_lo) & (fb.bar_day <= d_hi)
    side, both_cond = f_signal(fb)
    vol = d1.vol_feature(SimpleNamespace(b_id=fb.b_id, b_h=fb.b_h, b_l=fb.b_l, b_c=fb.b_c))
    px_in, px_out = open_at(fb.b_id, fb.b_o, 1), open_at(fb.b_id, fb.b_o, 1 + HOLD)
    res_f = evaluate(fb.b_id, side, px_in, px_out, vol, win, fb.has_thr, split_ts,
                     value=np.where(side > 0, fb.wl, fb.wu), n_ctl=n_ctl)
    thr_days = sorted({int(x) for x in fb.bar_day[fb.has_thr]})
    info_f = {"file": str(fp.relative_to(root)), "sha256": hashlib.sha256(raw).hexdigest(), "bars": int(len(fb.b_id)),
              "complete_days": len(fb.complete_days), "first_thr_day": str(pd.Timestamp(thr_days[0] * sb.DAY, unit="ms").date())
              if thr_days else None, "window_bars": int(win.sum()), "window_bars_thr": int((win & fb.has_thr).sum()),
              "lw_empty_share": float(np.mean(~fb.lw_ok[win])), "uw_empty_share": float(np.mean(~fb.uw_ok[win])),
              "both_conditions": int(np.sum(both_cond & win)),
              "doji_signals": int(np.sum(win & (side != 0) & (fb.b_c == fb.b_o))),
              "median_p10_wl": float(np.nanmedian(fb.p10[win])), "median_p90_wu": float(np.nanmedian(fb.p90[win])),
              "median_wl": float(np.nanmedian(fb.wl[win])), "median_wu": float(np.nanmedian(fb.wu[win])),
              "split_ts": split_ts, "integrity_minute_gate_ok": bool(integ["integrity"]["ok"]),
              "integrity_override": bool(integ.get("override_minute_gate", False))}
    # тест 1 на том же окне (минутные свечи с taker_buy, пороги nd по 20 прошлым полным дням — как в протоколе)
    a, info_k = sb.load(inst, root)
    p = d1.Prepared(a, info_k, inst)
    m = p.m
    o = a["open"]
    k_in = np.where(p.i_in >= 0, o[np.clip(p.i_in, 0, None)], np.nan)
    k_out = np.where(p.i_out >= 0, o[np.clip(p.i_out, 0, None)], np.nan)
    win_k = (m.bar_day >= d_lo) & (m.bar_day <= d_hi)
    t1 = {}
    t1_side = {}
    for rule in d1.RULES:
        s1 = d1.signal_side(m, p.p10, p.p90, rule)
        t1_side[rule] = np.where(win_k, s1, 0)
        t1[rule] = evaluate(m.b_id, s1, k_in, k_out, p.vol, win_k, p.has_thr, split_ts, value=m.nd, n_ctl=n_ctl)
    # диагностика: nd всей свечи (минутные свечи) на свечи из сделок
    nd_k = map_by_bar(m.b_id, m.nd, fb.b_id)
    diag = {"corr_window": {"wl_nd": corr(fb.wl[win], nd_k[win]), "wu_nd": corr(fb.wu[win], nd_k[win]),
                            "nd_trades_vs_klines": corr(fb.nd_tr[win], nd_k[win])},
            "corr_all": {"wl_nd": corr(fb.wl, nd_k), "wu_nd": corr(fb.wu, nd_k)},
            "nd_trades_vs_klines_max_abs": float(np.nanmax(np.abs(fb.nd_tr - nd_k))),
            "bars_without_kline_nd": int(np.sum(~np.isfinite(nd_k)))}
    t1_on_f = map_by_bar(m.b_id, t1_side["div"], fb.b_id, fill=0).astype(int)
    f_win = np.where(win, side, 0)
    diag["overlap_div"] = overlap(f_win, np.where(win, t1_on_f, 0), win & (fb.b_c >= fb.b_o), win & (fb.b_c <= fb.b_o))
    # справочно: F − тест 1 (div) после расходов, парный бутстрап по общим ISO-неделям
    diag["f_minus_t1div"] = sb.paired_week_diff(t1["div"]["trades"], res_f["trades"], "net")
    return {"info_footprint": info_f, "info_klines": info_k, "F": res_f, "test1_window": t1, "diag": diag}


def main() -> None:
    syms = [s for s in sys.argv[1:] if s in SYMS] or list(SYMS)
    root = Path(_arg("data-root", str(sb.ROOT)))
    n_ctl = int(_arg("n-ctl", N_CTL))
    out = _arg("out")
    res = {"protocol": "docs/ATLAS_FOOTPRINT_PROTOCOL_2026-10-14.md@18bc3db + ATLAS_DELTA_PROTOCOL@715a2de",
           "window": [SIG_FROM, SIG_TO], "taker": TAKER, "slip": SLIP, "slip2": SLIP2, "hold_bars": HOLD,
           "n_ctl": n_ctl, "seed_ctl": SEED_CTL, "seed_ci": SEED_CI, "split_ts": window_split(), "symbols": {}}
    for sym in syms:
        r = res["symbols"][sym] = run_symbol(sym, root, n_ctl)
        fi, dg = r["info_footprint"], r["diag"]
        print(f"{sym}: {fi['file']} sha256 {fi['sha256'][:16]}…, свечей {fi['bars']}, полных дней {fi['complete_days']}, "
              f"пороги с {fi['first_thr_day']}; окно {fi['window_bars']} свечей (с порогами {fi['window_bars_thr']}); "
              f"пустой нижний фитиль {fi['lw_empty_share']:.1%}, верхний {fi['uw_empty_share']:.1%}; "
              f"медиана P10 wl {fi['median_p10_wl']:+.4f}, P90 wu {fi['median_p90_wu']:+.4f}; в обоих условиях "
              f"{fi['both_conditions']}, доджи-сигналов {fi['doji_signals']}; контрольная часть с "
              f"{pd.Timestamp(fi['split_ts'], unit='ms'):%Y-%m-%d %H:%M}")
        print(_line("F", r["F"]))
        for rule in d1.RULES:
            print(_line(f"тест 1 {rule} (то же окно)", r["test1_window"][rule]))
        cw = dg["corr_window"]
        print(f"  корр. wl~nd: Пирсон {cw['wl_nd']['pearson']:+.3f}, Спирмен {cw['wl_nd']['spearman']:+.3f} "
              f"(n {cw['wl_nd']['n']}); wu~nd: {cw['wu_nd']['pearson']:+.3f} / {cw['wu_nd']['spearman']:+.3f}; "
              f"nd сделок ~ nd свечей {cw['nd_trades_vs_klines']['pearson']:.6f}, макс |Δ| "
              f"{dg['nd_trades_vs_klines_max_abs']:.2e}")
        ov = dg["overlap_div"]
        print(f"  совпадение F с тестом 1 div: L {ov['LONG']['both']}/{ov['LONG']['F']} (ожид. "
              f"{ov['LONG']['expected_if_indep']:.1f}), S {ov['SHORT']['both']}/{ov['SHORT']['F']} (ожид. "
              f"{ov['SHORT']['expected_if_indep']:.1f}); тест 1 div в окне L {ov['LONG']['T1']} / S {ov['SHORT']['T1']}")
        d = dg["f_minus_t1div"]
        if d["diff"] is not None:
            print(f"  F − тест 1 div (после расходов, общие недели {d['weeks']}): {_pct(d['diff'])} "
                  f"[ДИ {_pct(d['ci'][0])}…{_pct(d['ci'][1])}]")
    if out:
        Path(out).write_text(json.dumps(res, ensure_ascii=False, default=float), encoding="utf-8")


if __name__ == "__main__":
    main()
