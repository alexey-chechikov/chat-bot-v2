"""Состязательная самопроверка основной реализации research/trend_recheck (не замена независимой реализации §7).

  .venv/bin/python3 research/trend_recheck/selfcheck.py      → out/selfcheck.json

1) 4h-свечи и индикаторы — через pandas resample + dropna, как tools/trend_state.load_4h, против replay.Series
   (побитовое равенство OHLC, ATR14, ADX14);
2) машина сигналов на закрытых свечах — отдельный цикл по pandas-кадру против replay.live_episodes;
3) выходы ВСЕХ сделок базы — поминутный перебор (медленный путь: стоп по каждой минуте, закрытие и храповик на
   последней минуте свечи) против быстрого пути по 4h-массивам;
4) C1: кандидат на свече сигнала стратегии даёт ту же сделку (тот же R и свеча выхода);
5) фандинг — перебор строк файла против Series.funding (каждая 7-я сделка);
6) net, R, проскальзывание входа и qty — пересчёт по формулам протокола;
7) заглядывание вперёд — ряд, обрезанный в трёх точках (треть ряда, граница P1/P2, 5/6 ряда), даёт те же закрытые
   до обрезки сделки до последнего знака.
Всё — по трём символам основного расчёта и по ряду XRP §7а (xrp_fill).
"""
from __future__ import annotations

import json
import math
import sys
import time

import numpy as np
import pandas as pd

import replay as rp
import xrp_fill
from tools.trend_state import _adx, _atr

BASE = rp.BASE


def main() -> int:
    bad: list[str] = []

    def check(cond, msg):
        if not cond:
            bad.append(msg)

    per = {}
    jobs = []
    for sym in rp.SYMBOLS:
        m = rp.read_minutes(sym)
        jobs.append((sym, sym, m))
        if sym == "XRPUSDT":
            jobs.append(("XRPUSDT_filled7a", sym, xrp_fill.fill(m)[0]))       # чувствительность §7а
    for key, sym, m in jobs:
        S = rp.load_series(sym, 0, m)
        n = S.n_min
        d = pd.DataFrame({"open": m["o"][:n], "high": m["h"][:n], "low": m["l"][:n], "close": m["c"][:n]},
                         index=pd.to_datetime(m["ts"][:n], unit="ms", utc=True))
        r = d.resample("4h").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
        check(len(r) == S.nb, f"{sym} bars {len(r)} vs {S.nb}")
        check(np.array_equal(np.asarray(r.index.asi8) // 1_000_000, S.bstart), f"{sym} bar starts")
        for col, arr in (("open", S.bo), ("high", S.bh), ("low", S.bl), ("close", S.bc)):
            check(np.array_equal(r[col].to_numpy(), arr), f"{sym} bar {col}")
        atr = _atr(r).to_numpy()
        adx = _adx(r)[0].to_numpy()
        check(np.array_equal(np.isnan(atr), np.isnan(S.atr)) and np.array_equal(atr[~np.isnan(atr)], S.atr[~np.isnan(atr)]),
              f"{sym} atr")
        check(np.array_equal(np.isnan(adx), np.isnan(S.adx)) and np.array_equal(adx[~np.isnan(adx)], S.adx[~np.isnan(adx)]),
              f"{sym} adx")
        hh = r["high"].rolling(30).max().shift(1).to_numpy()
        ll = r["low"].rolling(30).min().shift(1).to_numpy()
        eps, pos = [], None
        for i in range(len(r)):
            if pos:
                pos[2] = max(pos[2], r["high"].iat[i]) if pos[1] == 1 else min(pos[2], r["low"].iat[i])
                stop = pos[2] - 3 * atr[i] if pos[1] == 1 else pos[2] + 3 * atr[i]
                if S.complete[i] and ((r["close"].iat[i] < stop) if pos[1] == 1 else (r["close"].iat[i] > stop)):
                    eps.append((pos[0], pos[1], i))
                    pos = None
                continue
            if i < 120 or not S.complete[i]:
                continue
            if r["close"].iat[i] > hh[i] and adx[i] >= 20:
                pos = [i, 1, r["high"].iat[i]]
            elif r["close"].iat[i] < ll[i] and adx[i] >= 20:
                pos = [i, -1, r["low"].iat[i]]
        if pos:
            eps.append((pos[0], pos[1], -1))
        check(eps == rp.live_episodes(S, BASE), f"{sym} live episodes")
        tr = rp.run(S, BASE)["trades"]
        bar_of = np.searchsorted(S.mi0, np.arange(S.n_min), "right") - 1
        kinds = {"close_exit": 0, "emergency_stop": 0, "gap_through_stop": 0, "censored": 0}
        for t in tr:
            dd = t["d"]
            k = int(np.searchsorted(S.ts, t["entry_ts"])) + 1
            peak = S.bh[t["signal_bar_idx"]] if dd > 0 else S.bl[t["signal_bar_idx"]]
            last, trig, res = t["ch0"], t["trig0"], None
            while k < S.n_min:
                j = bar_of[k]
                op = S.o[k]
                if dd > 0 and S.l[k] <= trig:
                    res = ("gap_through_stop" if op < trig else "emergency_stop", min(trig, op), k)
                    break
                if dd < 0 and S.h[k] >= trig:
                    res = ("gap_through_stop" if op > trig else "emergency_stop", max(trig, op), k)
                    break
                if k + 1 == S.n_min or bar_of[k + 1] != j:
                    peak = max(peak, S.bh[j]) if dd > 0 else min(peak, S.bl[j])
                    ch = peak - dd * 3 * S.atr[j]
                    if S.complete[j] and dd * (S.bc[j] - ch) < 0:
                        if k + 1 < S.n_min:
                            res = ("close_exit", S.o[k + 1], k + 1)
                        break
                    if dd * (ch - last) / last * 100 >= 0.2:
                        last = ch
                        trig = rp.round_away(ch * (1 - dd * 0.015), S.tick, dd)
                k += 1
            if res is None:
                kinds["censored"] += 1
                check(t["kind"] == "censored", f"{sym} {rp.iso(t['entry_ts'])} ожидался censored")
                continue
            kind, px, kx = res
            kinds[kind] += 1
            check(t["kind"] == kind and t["exit_raw"] == px and t["exit_ts"] == int(S.ts[kx]),
                  f"{sym} {rp.iso(t['entry_ts'])}: быстрый {t['kind']} {t['exit_raw']} / медленный {kind} {px}")
        cand = rp.c1_candidates(S, BASE)["rows"]
        idx = {(int(a[0]), int(a[1])): a for a in cand}
        for t in tr:
            a = idx.get((t["signal_bar_idx"], t["d"]))
            check(a is not None and a[3] == t["R"] and int(a[2]) == t["exit_bar"], f"{sym} C1 {rp.iso(t['entry_ts'])}")
        f = rp.read_funding(sym)
        ft = (f["fundingTime"].to_numpy() // rp.MIN) * rp.MIN
        nf = 0
        for t in tr[::7]:
            s = 0.0
            for T, rate, mark in zip(ft, f["fundingRate"], f["markPrice"]):
                if t["entry_ts"] < T <= t["exit_ts"]:
                    if not (mark == mark) or mark <= 0:
                        mark = S.c[int(np.searchsorted(S.ts, T, "right")) - 1]
                    s += -t["d"] * t["qty"] * mark * rate
            nf += 1
            check(abs(s - t["funding"]) < 1e-9, f"{sym} funding {rp.iso(t['entry_ts'])} {s} {t['funding']}")
        for t in tr:
            net = t["d"] * t["qty"] * (t["exit_fill"] - t["entry_fill"]) - t["fee_in"] - t["fee_out"] + t["funding"]
            check(abs(net - t["net"]) < 1e-9, f"{sym} net")
            check(abs(t["R"] - t["net"] / (t["qty"] * (abs(t["E"] - t["trig0"]) + 0.001 * t["E"]))) < 1e-12, f"{sym} R")
            check(t["entry_fill"] == t["E"] * (1 + t["d"] * 0.0002), f"{sym} slip")
            q = min(50 / (abs(t["E"] - t["trig0"]) + 0.001 * t["E"]), 3000 / t["E"])
            check(t["qty"] == round(math.floor(q / S.step + 1e-9) * S.step, 8), f"{sym} qty")
        # 7) заглядывание вперёд: ряд, обрезанный на cut, обязан дать те же сделки, закрытые до cut (индикаторы,
        #    канал, сигналы, стоп и фандинг — только из прошлого); открытая на cut — та же по входу, но censored
        trunc = 0
        fund = rp.read_funding(sym)
        for cut in (int(S.bstart[S.nb // 3]), rp.P1_END, int(S.bstart[(5 * S.nb) // 6])):
            S2 = rp.Series(sym, m["ts"], m["o"], m["h"], m["l"], m["c"], m["v"], funding=fund, end_ms=cut)
            tr2 = rp.run(S2, BASE)["trades"]
            full = {t["entry_ts"]: t for t in tr}
            for t2 in tr2:
                t1 = full.get(t2["entry_ts"])
                if t2["censored"]:
                    check(t1 is not None and (t1["exit_ts"] >= S2.data_end or t1["censored"]),
                          f"{sym} cut {rp.iso(cut)}: censored {rp.iso(t2['entry_ts'])} нет в полном ряду открытой")
                    continue
                check(t1 is not None and all(t1[k] == t2[k] for k in ("exit_ts", "kind", "exit_raw", "qty", "net", "R")),
                      f"{sym} cut {rp.iso(cut)}: сделка {rp.iso(t2['entry_ts'])} зависит от будущего")
                trunc += 1
            n_before = sum(1 for t in tr if t["exit_ts"] < S2.data_end and not t["censored"])
            check(n_before == sum(1 for t in tr2 if not t["censored"]),
                  f"{sym} cut {rp.iso(cut)}: закрытых до обрезки {n_before} ≠ {sum(1 for t in tr2 if not t['censored'])}")
        per[key] = {"bars": int(S.nb), "episodes": len(eps), "trades": len(tr), "exits_brute_force": kinds,
                    "funding_trades_checked": nf, "truncation_trades_checked": trunc}
        print(key, per[key], flush=True)
    out = {"generated_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()), "mismatches": len(bad),
           "first_mismatches": bad[:30], "per_symbol": per}
    (rp.OUT / "selfcheck.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("MISMATCHES:", len(bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
