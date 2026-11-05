"""Проверка разбора GPT 5d9e542 на всей истории. Правила не менялись, порядок и критерии — PREREG_gpt_check.md.
Части: учёт и пик сделок (BTC, ETH), контроль сдвигами (A), разложение +595 и −24.3%, окно GPT на Bybit, новые данные. Запуск: nice 20."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parents[1] / "operator_blue_20261103"))
sys.path.insert(0, str(Path(__file__).parents[1] / "tv_lab_1025"))
import cw_data as cw  # noqa: E402
import entry_rules as er  # noqa: E402
import flips_blue as fb  # noqa: E402
import ledger as lg  # noqa: E402
import pos  # noqa: E402

pd.set_option("display.width", 280, "display.max_columns", 40, "display.max_rows", 100)
HD = cw.SCR / "holdout"
FROZEN = cw.HERE.parents[1] / "backtests" / "frozen"


def from_hourly(df, fund, start):
    """Часовые бары стороннего источника → те же столбцы, что у Binance. df: ts (сек), open, high, low, close, volume."""
    h1 = cw.md.add_ind(cw.md.bars(df, 3600))
    h4 = cw.md.add_ind(cw.md.bars(df, 14400))
    d1 = cw.md.bars(df, 86400)
    h1f, h4f = cw.features(h1, h4, 1), cw.features(h4, h1, 4)
    a, _ = er.prep(h1f, h4f, d1, fund)
    a["i0"] = int(np.searchsorted(a["t"], cw.T(start)))
    return a


def load_btc_eth():
    m, h1, h4, d1, fund = cw.load()
    del m
    a, _ = er.prep(h1, h4, d1, fund)
    m2, h1e, h4e, d1e, fe = pd.read_pickle(er.ETH_PKL)
    del m2
    h1e, h4e = cw.features(h1e, h4e, 1), cw.features(h4e, h1e, 4)
    e, _ = er.prep(h1e, h4e, d1e, fe)
    return a, fund, e, fe, h1, h4


def load_xrp():
    p = HD / "xrp.pkl"
    if p.exists():
        return pd.read_pickle(p)
    cw.md.SRC_OLD, cw.md.SRC_NEW, cw.md.SRC_FUND = FROZEN / "XRPUSDT_UM_1m_early.csv", FROZEN / "XRPUSDT_UM_1m.csv", FROZEN / "XRPUSDT_funding_full.csv"
    m, h1, h4, d1, fund = cw.md.build(cache=False)
    del m
    h1f, h4f = cw.features(h1, h4, 1), cw.features(h4, h1, 4)
    a, _ = er.prep(h1f, h4f, d1, fund)
    a["i0"] = int(np.searchsorted(a["t"], cw.T("2020-07-01")))
    pd.to_pickle((a, fund), p)
    return a, fund


def load_bitstamp():
    f = pd.read_csv(HD / "bitstamp_btcusd_1h.csv")
    f["ts"] = f["timestamp"].astype(np.int64)
    fund = pd.Series([0.0], index=[cw.T("2013-01-01")])               # перпов ещё не было
    return from_hourly(f[f["close"] > 0], fund, "2014-01-01"), fund


def load_bybit():
    f = pd.read_csv(HD / "bybit_btcusdt_1h.csv")
    f["ts"] = (f["ms"] // 1000).astype(np.int64)
    r = pd.read_csv(HD / "bybit_btcusdt_funding.csv")
    fund = pd.Series(r["fundingRate"].to_numpy(float), index=(r["fundingRateTimestamp"].to_numpy(np.int64) // 1000))
    return from_hourly(f, fund, "2020-10-01"), fund


def rule_set(a, fm, coin, per=pos.PER, eth=False):
    rows = [lg.summary(a, fm, lg.trades_a(a), "A", coin, per)]
    for f in (0.4, 0.5):
        rows.append(lg.summary(a, fm, lg.trades_b(a, f), f"B{int(f * 100)}", coin, per))
        rows.append(lg.summary(a, fm, lg.trades_b(a, f, single=True), f"B{int(f * 100)} один", coin, per))
    if eth:
        rows.append(lg.summary(a, fm, lg.trades_b(a, 0.5, "S3"), "B50 стоп сутки", coin, per))
        rows.append(lg.summary(a, fm, lg.trades_b(a, 0.5, "S3", single=True), "B50 стоп сутки один", coin, per))
    rows.append(lg.summary(a, fm, lg.trades_c(a), "C", coin, per))
    return rows


def decompose(h1, h4, fund, a):
    """+595 и −24.3%: только лонг, на одном окне и на всей истории, ТФ × правило. Учёт как в study.py."""
    import study as st
    wins = {"окно 15.05.24–31.03.26": ("2024-05-15", "2026-04-01"), "2018–2026": ("2018-01-01", "2026-11-06")}
    rows = []
    for tfn, tf in (("1ч", st.TFD("H1", h1, h4, fund)), ("4ч", st.TFD("H4", h4, h4, fund))):
        sig = tf.signal(1, 0.002, 0.015)
        cell1 = tf.run(1, sig, "X2")

        def no_stop(i):
            e = i + 1
            if e >= tf.n - 1:
                return None
            for j in range(e, tf.n - 1):
                if tf.c[j] / tf.B[j] - 1 < -0.01:
                    return tf._close(1, e, j + 1, tf.o[e], tf.o[j + 1], st.COST_T, "слом")
            return tf._close(1, e, tf.n - 1, tf.o[e], tf.c[-1], st.COST_T, "конец")

        cell2, free = [], 0
        for i in np.flatnonzero(sig):
            if i < free:
                continue
            r = no_stop(int(i))
            if r is not None:
                cell2.append(r)
                free = r[1]
        cell3, on, e0 = [], False, 0
        for i in range(400, tf.n - 1):
            d = tf.c[i] / tf.B[i] - 1
            if not on and d > 0.01:
                on, e0 = True, i + 1
            elif on and d < -0.01:
                cell3.append(tf._close(1, e0, i + 1, tf.o[e0], tf.o[i + 1], st.COST_T, "слом"))
                on = False
        if on:
            cell3.append(tf._close(1, e0, tf.n - 1, tf.o[e0], tf.c[-1], st.COST_T, "конец"))
        for lab, cells in (("откат + наклон + стоп + выход 1%", cell1), ("откат + наклон, без стопа, выход 1%", cell2), ("вход и выход закрытием за 1%", cell3)):
            row = {"ТФ": tfn, "правило": lab}
            for w, (x, y) in wins.items():
                s = st.summ(cells, tf, x, y)
                row[f"{w} n"], row[f"{w} сумма_%"] = s["n"], round(s["sum"], 1)
            rows.append(row)
    d = fb.frame(a, fb.flip_legs(a, 1, 1.0))
    t0 = a["t"][d["i0"]]
    for lab, sel in (("A лонг", d["s"] == 1), ("A обе стороны", d["s"] != 0)):
        row = {"ТФ": "4ч", "правило": lab}
        for w, (x, y) in wins.items():
            m = sel & (t0 >= cw.T(x)) & (t0 < cw.T(y))
            row[f"{w} n"], row[f"{w} сумма_%"] = int(m.sum()), round(float(d.loc[m, "pnl"].sum()), 1)
        rows.append(row)
    return pd.DataFrame(rows)


def window(a, fm, x, y):
    """Окно GPT: старт без позиции, остаток закрывается на конце окна."""
    t = a["t"]
    ie = int(np.searchsorted(t, cw.T(y)))
    w = {k: (v[:ie] if isinstance(v, np.ndarray) and len(v) == len(t) else v) for k, v in a.items()}
    w["i0"] = int(np.searchsorted(t, cw.T(x)))
    fw = fm[:ie]
    per = {"окно": (cw.T(x), cw.T(y))}
    return [lg.summary(w, fw, tr, lab, "окно", per) for lab, tr in (("A", lg.trades_a(w)), ("B40", lg.trades_b(w, 0.4)), ("B50", lg.trades_b(w, 0.5)), ("B40 один", lg.trades_b(w, 0.4, single=True)), ("B50 один", lg.trades_b(w, 0.5, single=True)), ("C", lg.trades_c(w)))]


def holdout():
    bs, fbs = load_bitstamp()
    fmb = lg.funding_marks(bs, fbs)
    xr, fx = load_xrp()
    fmx = lg.funding_marks(xr, fx)
    perb = {"2014": (cw.T("2014-01-01"), cw.T("2015-01-01")), "2015": (cw.T("2015-01-01"), cw.T("2016-01-01")), "2016": (cw.T("2016-01-01"), cw.T("2017-01-01")), "2017": (cw.T("2017-01-01"), cw.T("2018-01-01"))}
    perx = {"2020–21": (cw.T("2020-07-01"), cw.T("2022-01-01")), "2022–07.24": (cw.T("2022-01-01"), cw.T("2024-08-01")), "08.24–26": (cw.T("2024-08-01"), cw.T("2030-01-01"))}
    tb_ = pd.DataFrame(rule_set(bs, fmb, "Bitstamp 2014–17", perb))
    tx = pd.DataFrame(rule_set(xr, fmx, "XRP 2020–26", perx))
    tb_.to_csv(pos.OUT / "gpt_check_holdout_bitstamp.csv", index=False)
    tx.to_csv(pos.OUT / "gpt_check_holdout_xrp.csv", index=False)
    print(tb_.to_string(index=False), flush=True)
    print(tx.to_string(index=False), flush=True)
    for x, fm, coin in ((bs, fmb, "Bitstamp"), (xr, fmx, "XRP")):
        print(coin, "сдвиги A:", lg.shift_rank(x, fm, lg.trades_a(x)), flush=True)


def main():
    lg.self_check()
    if "--holdout" in sys.argv:
        holdout()
        return
    a, fund, e, fe, h1, h4 = load_btc_eth()
    lg.check_same_as_old(a)
    lg.check_same_as_old(e)
    print("сверка со старым кодом: сделки B и C совпали на BTC и ETH", flush=True)
    fma, fme = lg.funding_marks(a, fund), lg.funding_marks(e, fe)
    print("фандинг начинается:", pos.utc_full(fund.index.min()), flush=True)
    t1 = pd.DataFrame(rule_set(a, fma, "BTC") + rule_set(e, fme, "ETH", eth=True))
    t1.to_csv(pos.OUT / "gpt_check_ledger.csv", index=False)
    print(t1.to_string(index=False), flush=True)
    for x, fm, coin in ((a, fma, "BTC"), (e, fme, "ETH")):
        print(coin, "сдвиги A:", lg.shift_rank(x, fm, lg.trades_a(x)), flush=True)
    t2 = decompose(h1, h4, fund, a)
    t2.to_csv(pos.OUT / "gpt_check_decompose.csv", index=False)
    print(t2.to_string(index=False), flush=True)
    by, fby = load_bybit()
    fmy = lg.funding_marks(by, fby)
    tw = pd.DataFrame(window(by, fmy, "2025-02-15", "2025-05-16") + window(a, fma, "2025-02-15", "2025-05-16"))
    tw.insert(0, "источник", ["Bybit"] * 6 + ["Binance"] * 6)
    tw.to_csv(pos.OUT / "gpt_check_window.csv", index=False)
    print(tw[["источник", "что", "n", "сумма_%", "фандинг_%", "издержки_%", "просадка_часы_%", "пик_сделок"]].to_string(index=False), flush=True)
    per0 = {"всё": (cw.T("2020-10-01"), cw.T("2030-01-01"))}
    same = {k: (v if not (isinstance(v, np.ndarray) and len(v) == len(a["t"])) else v) for k, v in a.items()}
    same["i0"] = int(np.searchsorted(a["t"], cw.T("2020-10-01")))
    tv = pd.DataFrame(rule_set(by, fmy, "BTC Bybit", per0) + rule_set(same, fma, "BTC Binance те же годы", per0))
    tv.to_csv(pos.OUT / "gpt_check_venue.csv", index=False)
    print(tv.to_string(index=False), flush=True)
    holdout()


if __name__ == "__main__":
    main()
