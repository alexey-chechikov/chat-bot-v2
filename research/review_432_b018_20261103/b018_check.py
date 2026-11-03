"""Своя проверка отчёта Codex по B018 (6ed5368, docs/WEEX_GPT_B018_SPLIT_EXIT_AND_432_SCOPE_2026-11-03.md). PREREG.md §2.
Код Codex не запускается: его каталоги на маке отсутствуют. Данные — Binance spot (кэш mr_data), у Codex — Bybit perp.
Запуск: b018_check.py --pk-btc=<bars_*.pkl BTC> --doc=<копия отчёта Codex .md>"""
from __future__ import annotations

import io
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "research" / "tv_lab_1025"))
import strategies as S  # noqa: E402
from snap import B018, arg, load, ts  # noqa: E402

OUT = HERE / "out"
MAKER, TAKER, SLIP, THROUGH = 0.00016, 0.00048, 0.0002, 0.0001
RISK, CAP = 3.0, 300.0
H = 3600


# ------------------------------------------------------------------ арифметика таблиц Codex
def csv_block(doc: str, name: str) -> pd.DataFrame:
    m = re.search(rf"<summary>{re.escape(name)}</summary>\s*```csv\n(.*?)```", doc, re.S)
    return pd.read_csv(io.StringIO(m.group(1)))


def arithmetic(doc: str) -> dict:
    tc = csv_block(doc, "all_trade_costs.csv")
    rs = csv_block(doc, "results.csv")
    tc["resid"] = tc["net"] - (tc["gross"] - tc["fees"] + tc["funding"])
    out = {"rows": len(tc), "max_abs_resid_net_eq_gross_minus_fees_plus_funding": float(tc["resid"].abs().max())}
    cont = rs[(rs["period"] == "continuous") & (rs["costs"] == 1.0) & (rs["path"] == "adverse")].set_index("policy")
    for pol, g in tc.groupby("policy"):
        out[pol] = {"sum_cycles": float(g["net"].sum()), "reported": float(cont.loc[pol, "net"]),
                    "fills": int(g["filled"].sum()), "wins": int((g["net"] > 0).sum())}
    b, e = tc[tc.policy == "baseline"].set_index("cycle"), tc[tc.policy == "ema3"].set_index("cycle")
    d = (e["net"] - b["net"]).round(4)
    out["ema3_minus_base_by_cycle"] = {int(k): float(v) for k, v in d[d != 0].items()}
    out["ema3_minus_base_sum"] = float(d.sum())
    out["ema3_without_cycle12"] = float(e["net"].sum() - e.loc[12, "net"])
    out["ema3_without_cycle5_delta"] = float(d.sum() - d.loc[5])
    return out


# ------------------------------------------------------------------ V1/V2 по барам Binance
def h4_frame(h4: pd.DataFrame) -> pd.DataFrame:
    o, h, l, c = (h4[k].to_numpy() for k in ("open", "high", "low", "close"))
    f = pd.DataFrame(index=h4["known"].to_numpy())
    f["open"], f["high"], f["low"], f["close"] = o, h, l, c
    f["ema"] = S.ema(c, 200)
    f["atr"] = S.atr(h, l, c, 14)
    f["adx"] = S.dmi(h, l, c, 14, 14)[2]
    f["hi30"] = pd.Series(h).shift(1).rolling(30).max().to_numpy()
    f["lo30"] = pd.Series(l).shift(1).rolling(30).min().to_numpy()
    f["ret1"] = 100 * (c / o - 1)
    f["ret5"] = 100 * (pd.Series(c) / pd.Series(c).shift(5) - 1).to_numpy()
    above, below = c > f["ema"].to_numpy(), c < f["ema"].to_numpy()
    f["n_above"] = run_len(above)
    f["n_below"] = run_len(below)
    f["swing_hi6"] = pd.Series(h).rolling(6).max().to_numpy()
    f["swing_lo6"] = pd.Series(l).rolling(6).min().to_numpy()
    return f


def run_len(x: np.ndarray) -> np.ndarray:
    out = np.zeros(len(x), dtype=int)
    k = 0
    for i, v in enumerate(x):
        k = k + 1 if v else 0
        out[i] = k
    return out


CONF = [  # Codex ema3_confirmation_candles.csv: цикл, сторона, номер, закрытие H4, close, ema
    (3, -1, 1, "2026-07-10 04:00", 63929.4, 63754.09), (3, -1, 2, "2026-07-10 08:00", 63966.0, 63756.20),
    (3, -1, 3, "2026-07-10 12:00", 64408.2, 63762.69), (5, 1, 1, "2026-07-29 16:00", 63941.4, 64278.30),
    (5, 1, 2, "2026-07-29 20:00", 63556.1, 64271.11), (5, 1, 3, "2026-07-30 00:00", 63952.6, 64267.94),
    (11, 1, 1, "2026-10-16 16:00", 81308.6, 82015.45), (11, 1, 2, "2026-10-16 20:00", 81548.4, 82010.80),
    (11, 1, 3, "2026-10-17 00:00", 81581.2, 82006.53)]
IMP = [(3, -1, "2026-07-09 08:00", 1.6689, 1.1229), (11, 1, "2026-10-16 16:00", -1.5607, -1.2664),
       (12, -1, "2026-10-29 16:00", 2.0301, 0.2451)]


def v1(f: pd.DataFrame) -> list:
    rows = []
    for cyc, side, num, t, c_cx, e_cx in CONF:
        r = f.loc[ts(t)]
        n = r["n_below"] if side == 1 else r["n_above"]
        rows.append({"cycle": cyc, "n": num, "t": t, "close_bn": r["close"], "close_cx": c_cx, "ema_bn": round(r["ema"], 2),
                     "ema_cx": e_cx, "side_ok": bool((r["close"] < r["ema"]) if side == 1 else (r["close"] > r["ema"])),
                     "run_bn": int(n)})
    for cyc, side, t, r1, r5 in IMP:
        r = f.loc[ts(t)]
        rows.append({"cycle": cyc, "impulse_t": t, "ret1_bn": round(r["ret1"], 4), "ret1_cx": r1, "ret5_bn": round(r["ret5"], 4),
                     "ret5_cx": r5, "impulse_bn": bool(max(-side * r["ret1"], -side * r["ret5"]) >= 1.5)})
    return rows


def v2(f: pd.DataFrame) -> list:
    rows = []
    for i, (te, side, *_r) in enumerate(B018, 1):
        r = f.loc[ts(te)]
        if side == 1:
            ok = r["close"] > r["hi30"] and r["adx"] >= 22 and r["close"] > r["ema"] and (r["close"] - r["hi30"]) / r["atr"] >= 0.5
        else:
            ok = r["close"] < r["lo30"] and r["adx"] >= 22 and r["close"] < r["ema"] and (r["lo30"] - r["close"]) / r["atr"] >= 0.5
        rows.append({"cycle": i, "entry": te, "side": side, "close": r["close"], "ema": round(r["ema"], 2), "adx": round(r["adx"], 2),
                     "lo30": r["lo30"], "hi30": r["hi30"], "atr": round(r["atr"], 2), "is_432_breakout": bool(ok)})
    return rows


# ------------------------------------------------------------------ V4: свой пересчёт 12 циклов
class Ctx:
    """Массивы и словари для быстрого прогона (контроль — 24 000 циклов)."""

    def __init__(self, h1: pd.DataFrame, f: pd.DataFrame, fund: pd.Series):
        self.t1 = h1.index.to_numpy()
        self.o1, self.hh, self.ll = h1["open"].to_numpy(), h1["high"].to_numpy(), h1["low"].to_numpy()
        self.cl = h1["close"].to_numpy()
        k = f.index.to_numpy().tolist()
        self.cut = dict(zip(k, zip(f["ret1"], f["ret5"], f["n_below"], f["n_above"])))
        self.row = dict(zip(k, zip(f["atr"], f["close"], f["swing_lo6"], f["swing_hi6"], f["ema"])))
        self.fund = dict(zip(fund.index.to_numpy().tolist(), fund.to_numpy().tolist()))


def plan(cx: Ctx, T: int, side: int, open1: float) -> dict:
    atr, c, slo, shi, _e = cx.row[T]
    stop = slo - 0.25 * atr if side == 1 else shi + 0.25 * atr
    p1 = open1 * (1 + side * SLIP)
    prices = [p1, c - side * 0.375 * atr, c - side * 0.75 * atr]
    stop_x = stop * (1 - side * SLIP)
    unit = sum(abs(stop_x - p) / p for p in prices) + TAKER + 2 * MAKER + sum(TAKER * stop_x / p for p in prices)
    notional = min(RISK / unit, CAP / 3)
    avg = 3 / sum(1 / p for p in prices)
    tgt = avg + side * 2 * abs(avg - stop)
    return {"stop": stop, "target": tgt, "prices": prices, "qty": [notional / p for p in prices], "avg": avg,
            "notional_total": 3 * notional, "atr": atr}


def simulate(cx: Ctx, T0: int, side: int, policy: str) -> dict:
    t1, o1, hh, ll = cx.t1, cx.o1, cx.hh, cx.ll
    i0 = int(np.searchsorted(t1, T0))
    pl = plan(cx, T0, side, o1[i0])
    filled = [False, False, False]
    pending = [False, True, True]
    cash = fees = funding = 0.0
    due = None
    path = []                                   # (конец часа, переоценка цикла по close H1) — для плавающей просадки

    def pos_qty():
        return sum(q for q, fl in zip(pl["qty"], filled) if fl)

    def close_all(px, fee_rate, t, why):
        nonlocal cash, fees
        for k in range(3):
            if filled[k]:
                cash += side * pl["qty"][k] * (px - pl["prices"][k])
                fees += pl["qty"][k] * px * fee_rate
        path.append((t + H, cash - fees + funding))
        return {"exit": str(pd.to_datetime(t, unit="s")), "reason": why, "fills": sum(filled),
                "net": cash - fees + funding, "stop": pl["stop"], "target": pl["target"], "notional": pl["notional_total"],
                "path": path}

    for i in range(i0, len(t1)):
        t, o = int(t1[i]), o1[i]
        if i > i0 and t in cx.fund and pos_qty() > 0:
            funding += -side * pos_qty() * o * cx.fund[t]
        if i > i0:
            if side * (o - pl["stop"]) <= 0:
                return close_all(o * (1 - side * SLIP), TAKER, t, "stop_gap")
            if due is not None and t >= due:
                return close_all(o * (1 - side * SLIP), TAKER, t, "condition_change")
            if t - T0 >= 80 * H:
                return close_all(o * (1 - side * SLIP), TAKER, t, "time")
        else:
            filled[0] = True
            fees += pl["qty"][0] * pl["prices"][0] * TAKER
        if t - T0 >= 12 * H:
            pending[1] = pending[2] = False
        new_fill = False
        for k in (1, 2):           # неблагоприятный порядок: добор раньше стопа в том же часе
            if pending[k] and ((side == 1 and ll[i] <= pl["prices"][k] * (1 - THROUGH)) or
                               (side == -1 and hh[i] >= pl["prices"][k] * (1 + THROUGH))):
                pending[k], filled[k], new_fill = False, True, True
                fees += pl["qty"][k] * pl["prices"][k] * MAKER
        if (side == 1 and ll[i] <= pl["stop"]) or (side == -1 and hh[i] >= pl["stop"]):
            return close_all(pl["stop"] * (1 - side * SLIP), TAKER, t, "stop")
        if not new_fill and ((side == 1 and hh[i] >= pl["target"] * (1 + THROUGH)) or
                             (side == -1 and ll[i] <= pl["target"] * (1 - THROUGH))):
            return close_all(pl["target"], MAKER, t, "target")
        unreal = sum(side * pl["qty"][k] * (cx.cl[i] - pl["prices"][k]) for k in range(3) if filled[k])
        path.append((t + H, unreal - fees + funding))
        tk = t + H
        if tk in cx.cut:
            r1, r5, nb, na = cx.cut[tk]
            imp = max(-side * r1, -side * r5) >= 1.5
            n_opp = nb if side == 1 else na
            if imp or n_opp >= 3:
                pending[1] = pending[2] = False
            if policy == "ema3" and n_opp >= 3 and due is None:
                due = tk
    return close_all(o1[-1], TAKER, int(t1[-1]), "terminal")


CODEX = {  # цикл: (выход/причина/частей/net исходный, то же EMA3) — из all_trade_costs.csv
    1: (("06-13 21:00", "stop", 1, -1.5255), ("06-13 21:00", "stop", 1, -1.5255)),
    2: (("07-06 13:00", "target", 1, 1.5365), ("07-06 13:00", "target", 1, 1.5365)),
    3: (("07-10 16:00", "time", 3, -1.2504), ("07-10 12:00", "condition_change", 3, -1.9864)),
    4: (("07-26 22:00", "target", 1, 1.2852), ("07-26 22:00", "target", 1, 1.2852)),
    5: (("07-31 14:00", "stop", 3, -3.0433), ("07-30 00:00", "condition_change", 3, -0.6268)),
    6: (("08-31 16:00", "target", 1, 1.3099), ("08-31 16:00", "target", 1, 1.3099)),
    7: (("09-09 08:00", "target", 1, 1.3704), ("09-09 08:00", "target", 1, 1.3704)),
    8: (("09-14 20:00", "target", 1, 1.5185), ("09-14 20:00", "target", 1, 1.5185)),
    9: (("09-18 08:00", "target", 1, 1.4853), ("09-18 08:00", "target", 1, 1.4853)),
    10: (("10-11 15:00", "target", 1, 1.5794), ("10-11 15:00", "target", 1, 1.5794)),
    11: (("10-19 04:00", "time", 2, 0.1649), ("10-17 00:00", "condition_change", 2, -0.5322)),
    12: (("10-30 18:00", "target", 3, 5.7539), ("10-30 18:00", "target", 3, 5.7539)),
}


def v4(cx: Ctx) -> tuple[list, dict]:
    rows = []
    paths = {"base": [], "ema3": []}
    for i, (te, side, *_r) in enumerate(B018, 1):
        for pol, k in (("base", 0), ("ema3", 1)):
            s = simulate(cx, ts(te), side, pol)
            paths[pol].append(s["path"])
            ref = CODEX[i][k]
            rows.append({"cycle": i, "policy": pol, "side": side, "exit_bn": s["exit"][5:16], "exit_cx": ref[0],
                         "reason_bn": s["reason"], "reason_cx": ref[1], "fills_bn": s["fills"], "fills_cx": ref[2],
                         "net_bn": round(s["net"], 4), "net_cx": ref[3], "stop_bn": round(s["stop"], 2),
                         "target_bn": round(s["target"], 2), "notional_bn": round(s["notional"], 2)})
    df = pd.DataFrame(rows)
    summ = {}
    for pol, g in df.groupby("policy"):
        summ[pol] = {"net_bn": float(g["net_bn"].sum()), "net_cx": float(g["net_cx"].sum()),
                     "same_reason": int((g["reason_bn"].str.replace("_gap", "") == g["reason_cx"]).sum()),
                     "same_fills": int((g["fills_bn"] == g["fills_cx"]).sum()),
                     "same_sign": int((np.sign(g["net_bn"]) == np.sign(g["net_cx"])).sum()),
                     "wins_bn": int((g["net_bn"] > 0).sum()), "fills_total_bn": int(g["fills_bn"].sum())}
    b, e = df[df.policy == "base"].set_index("cycle"), df[df.policy == "ema3"].set_index("cycle")
    summ["ema3_minus_base_bn"] = {int(k): round(float(v), 4) for k, v in (e["net_bn"] - b["net_bn"]).items() if abs(v) > 1e-9}
    b4 = df[df.policy == "base"]
    single = []
    for i, (te, side, *_r) in enumerate(B018, 1):        # фактическое R:R первой части (если добор не исполнился)
        pl = plan(cx, ts(te), side, cx.o1[int(np.searchsorted(cx.t1, ts(te)))])
        p1 = pl["prices"][0]
        single.append(abs(pl["target"] - p1) / abs(p1 - pl["stop"]))
    summ["single_fill_reward_to_risk"] = [round(x, 2) for x in single]
    for pol, ps in paths.items():           # циклы не пересекаются: кривая = закрытое прежних + переоценка текущего
        realized, peak, dd, at = 0.0, 0.0, 0.0, None
        for p in ps:
            for t, v in p:
                eq = realized + v
                if eq > peak:
                    peak = eq
                if peak - eq > dd:
                    dd, at = peak - eq, t
            realized += p[-1][1]
        summ[pol]["dd_h1_bn"] = round(dd, 4)
        summ[pol]["dd_trough_bn"] = str(pd.to_datetime(at, unit="s"))
    summ["single_fill_trades"] = int((b4["fills_bn"] == 1).sum())
    summ["single_fill_wins"] = int(((b4["fills_bn"] == 1) & (b4["net_bn"] > 0)).sum())
    return rows, summ


def v5(cx: Ctx, f: pd.DataFrame, own_sum: float, reps: int = 2000) -> dict:
    rng = np.random.default_rng(20261103)
    known = f.index.to_numpy()
    pool = known[(known >= ts("2026-05-01")) & (known <= ts("2026-10-28"))]
    ema_side = {}
    for k in pool.tolist():
        _a, c, _l, _h, e = cx.row[k]
        ema_side[k] = 1 if c > e else -1
    sides = [s for _te, s, *_r in B018]
    def valid(T: int, s: int) -> bool:          # как у Codex: стоп по нужную сторону всех входов, иначе плана нет
        pl = plan(cx, T, s, cx.o1[int(np.searchsorted(cx.t1, T))])
        return all(s * (p - pl["stop"]) > 0 for p in pl["prices"])

    out = {}
    for name in ("C1_sides_as_B018", "C2_side_by_EMA200"):
        tot = np.empty(reps)
        for r in range(reps):
            acc = 0.0
            for k in range(12):
                while True:
                    T = int(rng.choice(pool))
                    s = sides[k] if name.startswith("C1") else ema_side[T]
                    if valid(T, s):
                        break
                acc += simulate(cx, T, s, "base")["net"]
            tot[r] = acc
        out[name] = {"median": float(np.median(tot)), "p90": float(np.quantile(tot, 0.9)),
                     "share_positive": float((tot > 0).mean()), "rank_of_B018": float((1 + (tot >= own_sum).sum()) / (reps + 1)),
                     "own_sum": own_sum}
    return out


def main():
    OUT.mkdir(exist_ok=True)
    doc = arg("doc").read_text()
    h1, h4, fund = load(arg("pk-btc"))
    f = h4_frame(h4)
    fund = fund[~fund.index.duplicated(keep="last")]
    res = {"arithmetic": arithmetic(doc), "v1": v1(f), "v2": v2(f)}
    cx = Ctx(h1, f, fund)
    rows, summ = v4(cx)
    res["v4_rows"], res["v4_summary"] = rows, summ
    res["v5_random_entries"] = v5(cx, f, summ["base"]["net_bn"])
    print(json.dumps(res["v5_random_entries"], ensure_ascii=False, indent=1))
    (OUT / "b018_check.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float))
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)
    print(json.dumps(res["arithmetic"], ensure_ascii=False, indent=1))
    print(pd.DataFrame(res["v1"]).to_string())
    print(pd.DataFrame(res["v2"]).to_string())
    print(pd.DataFrame(rows).to_string())
    print(json.dumps(summ, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
