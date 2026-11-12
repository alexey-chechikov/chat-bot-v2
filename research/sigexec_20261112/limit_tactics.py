"""Как ставить ордера системы и 432 (оператор 12.11: «я бы рассмотрел разные варианты кидания лимиток»).

Каждое исполнение по закрытию 4ч (вход; выход по 4ч) проигрывается на минутках Binance spot BTCUSDT по вариантам:
  MKT       — рыночный в первую минуту после закрытия часа (тейкер + проскальзывание);
  MKT+L     — рыночный с задержкой L минут (живая служба сейчас ≈17 мин);
  PO        — post-only по цене сигнала, ждать W минут; не налилось → рыночный на минуте W;
  PO-x      — post-only лучше сигнала на x б.п., то же ожидание и добивка;
  CHASE     — post-only по закрытию прошлой минуты, переставлять каждую минуту N минут, потом рыночный;
  LADDER    — 3 части: сигнал, −5, −10 б.п., ждать W, остаток рыночным;
  PO-skip   — post-only по сигналу W минут, не налилось — ВХОД ПРОПУЩЕН (только для входов; итог сделки теряется).
Исполнение лимитки консервативно: только если цена прошла СКВОЗЬ уровень (минимум минуты < уровня − 1 тик для покупки).
Цель шорта под жёлтой и добор — заявки на уровне (лимит/стоп), здесь не играются; цель отдельно: мейкер вместо тейкера.

Итог — $ при базе $1000 с весом движка против допущения бэктеста (0.068% на сторону), окна: 3 года и 2 года.
Комиссии WEEX: мейкер 0.016%, тейкер 0.048%, проскальзывание рыночного 0.01% (BTC, $100–2 000, стакан ~2.5 BTC на лучшей).
Запуск: limit_tactics.py [минутки_2y.csv]"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

MAIN = Path("/Users/alexeychechikov/code/bot7")
sys.path.insert(0, str(MAIN))
from services.btc_signals import engine as en  # noqa: E402
from services.btc_signals import run as rn  # noqa: E402

FROZEN = MAIN / "backtests" / "frozen"
SRC2 = Path(sys.argv[1]) if len(sys.argv) > 1 else FROZEN / "BTCUSDT_1m_2y.csv"
MAKER, TAKER, SLIP = 0.016, 0.048, 0.010  # %
BASE = 1000.0
TICK = 0.1
T3 = 1699488000  # 09.11.2023
T2 = 1731110400  # 09.11.2024


def load_minutes(t_from: int):
    parts = []
    for p in (FROZEN / "BTCUSDT_1m_2017_2024.csv", SRC2):
        d = pd.read_csv(p, usecols=["ts", "open", "high", "low", "close"])
        parts.append(d[d["ts"] // 1000 >= t_from - 86400])
    d = pd.concat(parts, ignore_index=True).drop_duplicates("ts").sort_values("ts")
    return (d["ts"].to_numpy(np.int64) // 1000, d["open"].to_numpy(float), d["high"].to_numpy(float), d["low"].to_numpy(float),
            d["close"].to_numpy(float))


def executions(R):
    """(время, цена сигнала, сторона ордера +1 покупка/−1 продажа, доля базы, что: вход/выход, стратегия, итог сделки %)."""
    out = []
    for name, ev in (("система", R["ev"]), ("432", R["ev432"])):
        res_by_entry = {e["pos"]["entry_t"]: e["res"] for e in ev if e["kind"] == "выход"}
        for e in ev:
            p = e["pos"]
            main = e["tag"] in en.MAIN
            if e["kind"] == "вход":
                w = p["w"] * (en.FIRST if main else 1.0)
                out.append((e["t"], e["px"], e["side"], w, "вход", name, res_by_entry.get(p["entry_t"])))
            elif e["kind"] == "выход" and not e["why"].startswith("цель"):
                w = p["w"] * ((en.FIRST + (en.ADD if p["add_done"] else 0.0)) if main else 1.0)
                out.append((e["t"], e["px"], -e["side"], w, "выход", name, None))
    return out


def fill_po(k0, n, lvl, s, h, l):
    """Первая минута в [k0, k0+n), где цена прошла сквозь лимит; −1 — не налилось."""
    seg = l[k0:k0 + n] < lvl - TICK if s > 0 else h[k0:k0 + n] > lvl + TICK
    hit = np.flatnonzero(seg)
    return k0 + int(hit[0]) if len(hit) else -1


def cost_pct(s, px, P, fee):
    """Издержка исполнения в % от цены сигнала (плюс — хуже сигнала)."""
    return s * (px / P - 1) * 100 + fee


def run_variant(name, X, mins, skip=False):
    t, o, h, l, c = mins
    rows = []
    for (T, P, s, w, kind, strat, res) in X:
        k0 = int(np.searchsorted(t, T))
        if k0 + 120 >= len(t) or t[k0] != T:
            continue
        mk = lambda k: cost_pct(s, o[k] * (1 + s * SLIP / 100), P, TAKER)  # noqa: E731
        lost = 0.0
        if name == "MKT":
            cst, wait = mk(k0), 0
        elif name.startswith("MKT+"):
            L = int(name[4:])
            cst, wait = mk(k0 + L), L
        elif name.startswith("PO") or name.startswith("POskip"):
            W, off = (int(x) for x in name.split("_")[1:3])
            lvl = P * (1 - s * off / 10000)
            k = fill_po(k0, W, lvl, s, h, l)
            if k >= 0:
                cst, wait = cost_pct(s, lvl, P, MAKER), k - k0
            elif skip and kind == "вход":
                cst, wait = 0.0, W
                lost = res if res is not None else 0.0
                rows.append((T, kind, strat, w, None, wait, lost))
                continue
            else:
                cst, wait = mk(k0 + W), W
        elif name.startswith("CHASE"):
            N = int(name.split("_")[1])
            cst, wait = None, N
            for k in range(k0, k0 + N):
                lvl = c[k - 1]  # цена прошлой минуты = лучшая цена своей стороны
                if (s > 0 and l[k] < lvl - TICK) or (s < 0 and h[k] > lvl + TICK):
                    cst, wait = cost_pct(s, lvl, P, MAKER), k - k0
                    break
            if cst is None:
                cst = mk(k0 + N)
        elif name.startswith("LADDER"):
            W = int(name.split("_")[1])
            parts = []
            for off in (0, 5, 10):
                lvl = P * (1 - s * off / 10000)
                k = fill_po(k0, W, lvl, s, h, l)
                parts.append(cost_pct(s, lvl, P, MAKER) if k >= 0 else mk(k0 + W))
            cst, wait = float(np.mean(parts)), W
        else:
            raise ValueError(name)
        rows.append((T, kind, strat, w, cst, wait, lost))
    return rows


def summarize(name, rows, t_from):
    r = [x for x in rows if x[0] >= t_from]
    out = {"вариант": name}
    for kind in ("вход", "выход"):
        z = [x for x in r if x[1] == kind]
        filled = [x for x in z if x[4] is not None]
        base_cost = sum(x[3] * BASE * 0.068 / 100 for x in z)
        cost = sum(x[3] * BASE * x[4] / 100 for x in filled)
        lost = sum(BASE * x[6] / 100 for x in z if x[4] is None and x[6])  # итог движка уже с весом и долей лота
        out[f"{kind}: n"] = len(z)
        out[f"{kind}: $ против бэктеста"] = round(base_cost - cost - lost, 1)
        out[f"{kind}: средн. издержка б.п."] = round(float(np.mean([x[4] for x in filled])) * 100, 1) if filled else None
        out[f"{kind}: пропущено"] = sum(1 for x in z if x[4] is None)
        if any(x[4] is None for x in z):
            out[f"{kind}: потеряно итога $"] = round(-sum((x[6] or 0) / 100 * BASE for x in z if x[4] is None), 1)
    out["итого $"] = round(out["вход: $ против бэктеста"] + out["выход: $ против бэктеста"], 1)
    return out


def main():
    R = rn.compute()
    X = executions(R)
    mins = load_minutes(T3)
    variants = (["MKT", "MKT+1", "MKT+2", "MKT+17"] + [f"PO_{W}_0" for W in (1, 3, 5, 15, 60)] + [f"PO_{W}_{x}" for W in (5, 15) for x in (5, 10)]
                + [f"CHASE_{N}" for N in (3, 5, 10)] + [f"LADDER_{W}" for W in (5, 15)])
    res = {v: run_variant(v, X, mins) for v in variants}
    for W in (5, 15, 60):
        v = f"POskip_{W}_0"
        res[v] = run_variant(v, X, mins, skip=True)
    for lab, t0 in (("3 года (с 09.11.2023)", T3), ("2 года (с 09.11.2024)", T2)):
        df = pd.DataFrame([summarize(k, v, t0) for k, v in res.items()]).set_index("вариант")
        pd.set_option("display.width", 250, "display.max_columns", 20)
        print(f"\n=== {lab}, база ${BASE:.0f}, плюс — экономия против бэктеста (0.068%/сторону) ===")
        print(df.to_string())
    # цель под жёлтой: лимитка (мейкер) вместо допущения тейкера
    tg = [e for e in R["ev"] if e["kind"] == "выход" and e["why"].startswith("цель")]
    for lab, t0 in (("3 года", T3), ("2 года", T2)):
        z = [e for e in tg if e["t"] >= t0]
        sv = sum(e["pos"]["w"] * BASE * (0.068 - MAKER) / 100 for e in z)
        print(f"цель под жёлтой лимиткой, {lab}: {len(z)} выходов, экономия ${sv:.1f}")
    # время ожидания для PO по сигналу
    for W in (5, 15, 60):
        r = [x for x in res[f"PO_{W}_0"] if x[0] >= T2]
        wt = [x[5] for x in r]
        print(f"PO {W} мин, 2 года: налилось лимиткой {np.mean([x[5] < W for x in r]) * 100:.0f}%, медиана ожидания {np.median(wt):.0f} мин")


if __name__ == "__main__":
    main()
