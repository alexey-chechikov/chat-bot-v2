"""Независимая сверка research/manual_pullback/replay.py на тех же CSV: свечи через pandas.resample, ADX/ATR —
сглаживание Уайлдера суммами (а не средними), EMA — своим циклом, машина отката — по массиву 16 свечей, выход —
построчным циклом по минутам, фандинг — перебором начислений. Сравнивает исходы КАЖДОГО 4h-события и каждую сделку
прогонов по одному символу (S и C2, базовые издержки).

    .venv/bin/python3 research/manual_pullback/audit.py
"""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("/Users/alexeychechikov/code/bot7")
FROZEN = ROOT / "backtests" / "frozen"
OUT = Path(__file__).resolve().parent / "out"
START = 1715731200000
MIN = 60_000
TAKER, MAKER, SLIP = 0.00048, 0.00016, 0.0002
SPEC = {"ETHUSDT": (0.01, 0.001), "XRPUSDT": (0.0001, 1.0), "BTCUSDT": (0.1, 0.001)}


def bars(df: pd.DataFrame, rule: str, per: int) -> pd.DataFrame:
    g = df.resample(rule, label="left", closed="left")
    b = pd.DataFrame({"o": g.o.first(), "h": g.h.max(), "l": g.l.min(), "c": g.c.last(), "n": g.o.count()})
    b["ok"] = b.n == per
    return b


def wilder_sum_adx(h, l, c, n=14):
    m = len(h)
    out = [math.nan] * m
    trs = pdms = mdms = 0.0
    dxs = []
    adx = None
    for i in range(1, m):
        tr = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
        up, dn = h[i] - h[i - 1], l[i - 1] - l[i]
        p = up if up > dn and up > 0 else 0.0
        q = dn if dn > up and dn > 0 else 0.0
        if i <= n:
            trs, pdms, mdms = trs + tr, pdms + p, mdms + q
            if i < n:
                continue
        else:
            trs, pdms, mdms = trs - trs / n + tr, pdms - pdms / n + p, mdms - mdms / n + q
        pdi, mdi = 100 * pdms / trs, 100 * mdms / trs
        dx = 100 * abs(pdi - mdi) / (pdi + mdi) if pdi + mdi > 0 else 0.0
        if adx is None:
            dxs.append(dx)
            if len(dxs) == n:
                adx = sum(dxs) / n
                out[i] = adx
        else:
            adx = (adx * (n - 1) + dx) / n
            out[i] = adx
    return np.array(out)


def wilder_sum_atr(h, l, c, n=14):
    out = np.full(len(h), np.nan)
    s = 0.0
    for i in range(1, len(h)):
        tr = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
        if i <= n:
            s += tr
            if i == n:
                out[i] = s / n
        else:
            s = s - s / n + tr
            out[i] = s / n
    return out


def ema_loop(c, n=20):
    out = np.full(len(c), np.nan)
    a = 2 / (n + 1)
    for i in range(n - 1, len(c)):
        out[i] = sum(c[:n]) / n if i == n - 1 else out[i - 1] * (1 - a) + c[i] * a
    return out


def scan(sym: str, end: int) -> dict:
    d = pd.read_csv(FROZEN / f"{sym}_UM_1m.csv", usecols=["ts", "open", "high", "low", "close"])
    d = d[(d.ts >= START) & (d.ts < end)].rename(columns={"open": "o", "high": "h", "low": "l", "close": "c"})
    mts = d.ts.to_numpy()
    mo, mh, ml = d.o.to_numpy(), d.h.to_numpy(), d.l.to_numpy()
    d.index = pd.to_datetime(d.ts, unit="ms", utc=True)
    b15 = bars(d, "15min", 15)
    b4 = bars(d, "4h", 240)
    b15 = b15.iloc[:-1] if not b15.ok.iloc[-1] else b15        # хвост выгрузки — незавершённая свеча
    b4 = b4.iloc[:-1] if not b4.ok.iloc[-1] else b4
    assert b15.ok.all() and b4.ok.all(), "дыры — аудит рассчитан на полные данные"
    H4, L4, C4 = (b4[k].to_numpy() for k in "hlc")
    adx = wilder_sum_adx(H4, L4, C4)
    H, L, C, O = (b15[k].to_numpy() for k in "hlco")
    ema, atr = ema_loop(C), wilder_sum_atr(H, L, C)
    t15 = (b15.index.astype("int64") // 1_000_000).to_numpy()
    t4 = (b4.index.astype("int64") // 1_000_000).to_numpy()
    f = pd.read_csv(FROZEN / f"{sym}_funding.csv")
    fund = [((int(t) // MIN) * MIN, float(r), float(mk)) for t, r, mk in zip(f.fundingTime, f.fundingRate, f.markPrice)]
    tick, step = SPEC[sym]
    res = {}
    for need_adx in (True, False):
        events, outcomes = [], {}
        for i in range(31, len(C4)):
            hh, ll = H4[i - 30:i].max(), L4[i - 30:i].min()
            up = C4[i] > hh and not C4[i - 1] > H4[i - 31:i - 1].max()
            dn = C4[i] < ll and not C4[i - 1] < L4[i - 31:i - 1].min()
            if (up or dn) and (not need_adx or adx[i] >= 20):
                events.append((int(t4[i]) + 4 * 3_600_000, 1 if up else -1, i))
        trades = []
        busy_until = -1
        for T, side, i in events:
            eid = f"{T}-{side}"
            if T < busy_until:
                outcomes[eid] = "ignored_in_position"
                continue
            k1 = int(np.searchsorted(t15, T))
            w = slice(k1, k1 + 16)
            hi, lo, cl = H[w], L[w], C[w]
            lo4, hi4 = L4[i], H4[i]
            beyond = (cl < lo4) if side > 0 else (cl > hi4)
            touch_ok = (lo <= ema[w]) & (ema[w] <= hi)
            touch_ok[:3] = False
            outcome, tk, ck = None, None, None
            for k in range(16):
                if beyond[k]:
                    outcome = "cancel_close_beyond_4h"
                    break
                if tk is None:
                    if touch_ok[k]:
                        tk = k
                        ext = lo[:k + 1].min() if side > 0 else hi[:k + 1].max()
                        if k == 15:
                            outcome = "expire_confirm"
                            break
                    elif k == 15:
                        outcome = "expire_touch"
                        break
                    continue
                if (side > 0 and lo[k] < ext) or (side < 0 and hi[k] > ext):
                    outcome = "cancel_new_extreme"
                    break
                if (side > 0 and cl[k] > max(hi[k - 1], hi[k - 2])) or (side < 0 and cl[k] < min(lo[k - 1], lo[k - 2])):
                    outcome, ck = "confirm", k
                    break
                if k - tk >= 3 or k == 15:
                    outcome = "expire_confirm"
                    break
            if outcome != "confirm":
                outcomes[eid] = outcome
                continue
            A = atr[k1 + tk]
            t_in = int(t15[k1 + ck]) + 15 * MIN
            i0 = int(np.searchsorted(mts, t_in))
            raw = mo[i0]
            if abs(raw - cl[ck]) > 0.1 * A:
                outcomes[eid] = "cancel_drift"
                continue
            E = raw * (1 + side * SLIP)
            S = ext - side * 0.1 * A
            wd = side * (E - S) / E
            if not (0.007 <= wd <= 0.02):
                outcomes[eid] = "skip_width"
                continue
            TP = E + 2 * (E - S)
            kind = None
            for k in range(480):
                j = i0 + k
                if k > 0 and ((side > 0 and mo[j] <= S) or (side < 0 and mo[j] >= S)):
                    kind, xr, xt = "SL_GAP", mo[j], mts[j]
                    break
                if (side > 0 and ml[j] <= S) or (side < 0 and mh[j] >= S):
                    kind, xr, xt = "SL", S, mts[j] + MIN - 1
                    break
                if (side > 0 and mh[j] >= TP + tick) or (side < 0 and ml[j] <= TP - tick):
                    kind, xr, xt = "TP", TP, mts[j] + MIN - 1
                    break
            if kind is None:
                kind, xr, xt = "TIME", mo[i0 + 480], mts[i0 + 480]
            X = xr if kind == "TP" else xr * (1 - side * SLIP)
            Ss = S * (1 - side * SLIP)
            per = abs(E - Ss) + TAKER * E + TAKER * Ss
            q = math.floor(7.5 / per / step + 1e-9) * step        # B на капитал 3000 — для сверки цен и R
            fu = sum(mk * r for ft, r, mk in fund if t_in < ft <= xt)
            pnl = side * (X - E) * q - TAKER * E * q - (MAKER if kind == "TP" else TAKER) * X * q - side * q * fu
            trades.append({"eid": eid, "entry_ts": t_in, "side": side, "raw": raw, "S": S, "TP": TP, "kind": kind,
                           "exit_ts": int(xt), "exit_raw": float(xr), "R": pnl / (q * per), "touch": tk + 1,
                           "confirm": ck + 1})
            outcomes[eid] = "entered"
            busy_until = int(xt) + (1 if kind in ("SL", "TP") else 0)
        res["S" if need_adx else "C2"] = {"events": len(events), "outcomes": outcomes, "trades": trades}
    return res


def main() -> None:
    summ = json.loads((OUT / "summary.json").read_text(encoding="utf-8"))
    end_iso = summ["manifest"]["end_exclusive"]
    end = int(pd.Timestamp(end_iso, tz="UTC").value // 1_000_000)
    report = {}
    for sym, scope in (("ETHUSDT", "ETH"), ("XRPUSDT", "XRP"), ("BTCUSDT", "BTC")):
        res = scan(sym, end)
        for var in ("S", "C2"):
            key = f"{var}_{scope}_base"
            led = list(csv.DictReader((OUT / f"ledger_{key}.csv").open()))
            ev = list(csv.DictReader((OUT / f"events_{key}.csv").open()))
            mine = res[var]
            # исходы событий: replay пишет eid как SYM-ISO-L/S и время T в UTC-строке
            got = {}
            for e in ev:
                T = int(pd.Timestamp(e["T_utc"], tz="UTC").value // 1_000_000)
                got[f"{T}-{int(e['side'])}"] = e["outcome"]
            diff_out = {k: (v, got.get(k)) for k, v in mine["outcomes"].items() if got.get(k) != v}
            extra = sorted(set(got) - set(mine["outcomes"]))
            tr_diff = []
            by_entry = {int(x["entry_ts"]): x for x in led}
            for t in mine["trades"]:
                x = by_entry.get(t["entry_ts"])
                if x is None:
                    tr_diff.append(("нет в ledger", t["eid"]))
                    continue
                checks = [x["kind"] == t["kind"], int(x["exit_ts"]) == t["exit_ts"],
                          math.isclose(float(x["exit_raw"]), t["exit_raw"], rel_tol=1e-12),
                          math.isclose(float(x["S"]), t["S"], rel_tol=1e-9),
                          math.isclose(float(x["TP"]), t["TP"], rel_tol=1e-9),
                          int(x["touch"]) == t["touch"], int(x["confirm"]) == t["confirm"],
                          abs(float(x["R"]) - t["R"]) < 0.02]
                if not all(checks):
                    tr_diff.append((t["eid"], checks, x["kind"], t["kind"], x["R"], t["R"]))
            report[key] = {"events_audit": mine["events"], "events_replay": len(got),
                           "outcome_mismatches": len(diff_out), "examples": list(diff_out.items())[:5],
                           "replay_only_events": extra[:5], "trades_audit": len(mine["trades"]),
                           "trades_replay": len(led), "trade_mismatches": tr_diff[:5],
                           "max_abs_R_diff": max([abs(float(by_entry[t["entry_ts"]]["R"]) - t["R"])
                                                  for t in mine["trades"] if t["entry_ts"] in by_entry] or [0.0])}
            print(key, json.dumps(report[key], ensure_ascii=False, default=str), flush=True)
    (OUT / "audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
