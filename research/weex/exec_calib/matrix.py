"""Матрица «шаг × цель» лонг-сетки с режимом SMA100 (полоса 2%) — разделить влияние шага и цели (задача 29.10; разбор GPT
docs/WEEX_GPT_CRITICAL_REVIEW_2026-10-28.md §1, §4.3 п.2–3 и п.6, §8).

ПРАВИЛА (записаны ДО прогона 29.10; под результат не меняются; всё, что не здесь, — чувствительность с пометкой).
1. Движок — ОДИН для всех ячеек, правила week_reconcile.sim(): следующий вход от НИЖНЕГО открытого лота на шаг ниже
   (округление вниз к тику); без лотов — вход от максимума цены после последнего лота / начала лонга (подтяжка);
   лимитка исполняется по своей цене при касании; тейк каждого лота по его цели (округление вверх к тику); потолок
   max(себестоимость, объём×цена уровня) + вход ≤ cap; мейкер 0.016% на каждое исполнение; на точку — тейки, затем не
   больше одного входа. Путь минуты — 4 точки O, L/H, H/L, C (M1). Тик: BTC 0.1, ETH 0.01 (state/weex_grid*_config.json).
   Лимит числа лотов — не ограничивает (держит только потолок $), а максимум одновременно стоящих заявок (лоты + 1)
   печатается для бюджета счёта 185. Чувствительность: N2 с лимитом 50 лотов (max_lots_per_side живых BTC/ETH).
2. Режим как у живых сеток: дневки UTC по закрытиям 1m (только полные дни, 1440 минут), SMA100 дневных закрытий,
   полоса 2% — гистерезис: из ЛОНГА выйти, только если закрытие дня < SMA·0.98; в ЛОНГ — только если > SMA·1.02; первое
   известное состояние — закрытие > SMA; решение на закрытии дня d действует весь день d+1. Нет 100 полных дней прогрева
   или неизвестный режим внутри окна — отказ. Выход из лонга — на open первой минуты дня: все лоты по рынку
   open·(1 − 0.02%) тейкером 0.048%, опорная цена сбрасывается. Вне лонга входов нет. Только лонг, пустой старт.
3. Фандинг Binance (backtests/frozen/<SYM>_funding_full.csv): расчёт в минуте, содержащей fundingTime, на её open —
   лонг платит объём лотов × open × ставка (до закрытия по режиму той же минуты). Где ставок нет (после последней
   записи файла) — фандинг 0, срок без ставок печатается.
4. Ячейки: шаг ∈ {0.1, 0.2, 0.3, 0.6}% × цель ∈ {0.34, 0.49, 0.89, 1.4}% — 16 ячеек, BTCUSDT; те же 16 — ETHUSDT.
5. Нормировки:
   N1 (механика) — плотность $160 на 1% хода: ордер в монете = 160·шаг%/цена уровня, вниз к 0.0001 BTC / 0.001 ETH, не
      меньше минимума (минимум = шаг объёма 0.0001 / 0.001 из конфига; биржевой minimum WEEX не запрашивался); потолок
      $6 000. Фактическая средняя плотность входов ($ на 1% = объём·цена/шаг%) печатается — округление её искажает,
      правило из-за этого не меняется.
   N2 (портфель) — одинаковый ордер 0.0012 BTC / 0.020 ETH, потолок $12 000 / $2 500.
6. Данные: копии scratchpad wk1028/BTCUSDT_1m_2y.csv и ETHUSDT_1m_2y.csv (печатаются строки, первый/последний бар, sha256,
   пропуски минут); метки обязаны быть на минутной сетке и строго возрастать, OHLC конечные и > 0, иначе отказ.
   1s: прогон N1 на секундах делается, только если в calib_result.json сумма относительных ошибок по тейкам у S1 или
   S1L40 меньше, чем у M1. В файле, прочитанном до прогона: M1 0.3274, S1 0.3281, S1L40 0.4513 → условие не выполнено,
   1s не прогоняется (скрипт проверяет это по файлу и пишет решение в результат).
7. Метрики ячейки: итог = закрыто (тейки + закрытия по режиму) − комиссии − фандинг + мешок на конце (по закрытию
   последней минуты); макс. просадка — по кривой капитала на закрытии каждой минуты (закрытое − комиссии − фандинг +
   мешок), пик от 0; итог/|просадка|; оборот $ (все исполнения: входы, тейки, закрытия по режиму) и число тейков; часы у
   потолка — минуты в режиме лонг, на закрытии которых есть лоты и следующий вход не помещается под потолок (или упёрся в
   лимит лотов), /60; максимум одновременно стоящих заявок = максимум лотов + 1; половины — срез на минуте n//2 ряда
   после прогрева: 1-я = капитал на закрытии минуты перед срезом (до её операций), 2-я непрерывно = итог − 1-я, 2-я с
   нуля = отдельный прогон с пустым учётом от минуты среза (режим тот же, ссылка сброшена).
8. Разница ячейки против 0.6/1.4 той же нормировки и монеты — парный блочный бутстреп по неделям: недели = 7-суточные
   блоки от первой минуты ряда после прогрева (последний неполный — свой блок); приращение капитала каждой ячейки за
   неделю (по полной непрерывной кривой, с мешком); разность приращений; 2000 повторов выборки недель с возвращением
   (одни и те же индексы для всех ячеек, seed 20261029); ДИ 95% — перцентили 2.5/97.5 суммы. «Различаются» — ДИ не
   включает 0. Чувствительность: скользящие блоки по 4 недели (те же 2000 повторов).
9. Ответы: при цели 1.4 — шаги 0.1/0.2/0.3 против 0.6 (ДИ разницы включает 0?); при шаге 0.6 — цели 0.34/0.49/0.89
   против 1.4; «плоско» — ячейки, у которых ДИ разницы против 0.6/1.4 включает 0, и ворота 4 CLAUDE.md: знаки итога
   у соседей (шаг ±1 позиция, цель ±1 позиция) по обе стороны нуля.
10. Проверка кода до чтения результатов: движок с «всегда лонг», без фандинга и с N2-ордером обязан дать то же, что
   week_reconcile.sim() на первых 200 000 минутах (входы, тейки, лоты точно; закрыто/комиссии/объём/мешок до 1e-6) —
   BTC 0.1/0.34, BTC 0.6/1.4, ETH 0.2/0.89; синтетика закрытия по режиму и фандинга — до 1e-9. Не совпало — отказ.
Запуск: OMP_NUM_THREADS=2 nice -n 20 <venv>/python3 -I research/weex/exec_calib/matrix.py [--check-only]
→ matrix_result.json. Один процесс, без пула.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import os
import sys
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd

sys.path.insert(0, "/Users/alexeychechikov/code/bot7/research/weex")
import week_reconcile as wr  # noqa: E402

HERE = "/Users/alexeychechikov/code/bot7/research/weex/exec_calib/"
OUT = HERE + "matrix_result.json"
CALIB = HERE + "calib_result.json"
SCR = "/private/tmp/claude-501/-Users-alexeychechikov/1447ae84-81fe-465b-ad50-d8cc845df051/scratchpad/wk1028/"
SRC = {"BTCUSDT": SCR + "BTCUSDT_1m_2y.csv", "ETHUSDT": SCR + "ETHUSDT_1m_2y.csv"}
FUND = {s: f"/Users/alexeychechikov/code/bot7/backtests/frozen/{s}_funding_full.csv" for s in SRC}
TICK = {"BTCUSDT": 0.1, "ETHUSDT": 0.01}
QSTEP = {"BTCUSDT": 0.0001, "ETHUSDT": 0.001}
STEPS = (0.1, 0.2, 0.3, 0.6)
TGTS = (0.34, 0.49, 0.89, 1.4)
BASE = (0.6, 1.4)
NORMS = {"N1": {"BTCUSDT": (None, 6000.0), "ETHUSDT": (None, 6000.0)},
         "N2": {"BTCUSDT": (0.0012, 12000.0), "ETHUSDT": (0.020, 2500.0)}}
SENS = "N2 лотов≤50 (чувствительность)"
DENS = 160.0                                       # $ на 1% хода (N1)
MAKER, TAKER, SLIP = wr.MAKER, 0.00048, 0.0002
BAND = 0.02
DAY_MS, DAY_MIN = 86_400_000, 1440
WEEK = 7 * 86400
NBOOT, SEED = 2000, 20261029
BIG = 10 ** 9


def log(*a) -> None:
    print(*a, flush=True)


def sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha_file(path: str) -> str:
    return sha_bytes(open(path, "rb").read())


def git_head() -> str:
    root = "/Users/alexeychechikov/code/bot7/.git/"
    head = open(root + "HEAD", encoding="utf-8").read().strip()
    if not head.startswith("ref: "):
        return head
    ref = head[5:]
    if os.path.exists(root + ref):
        return open(root + ref, encoding="utf-8").read().strip()
    for line in open(root + "packed-refs", encoding="utf-8"):
        if line.strip().endswith(" " + ref):
            return line.split()[0]
    return head


def iso(sec: float) -> str:
    return datetime.fromtimestamp(int(sec), timezone.utc).strftime("%Y-%m-%d %H:%M")


def load(sym: str) -> tuple[dict, dict]:
    """Минутки копии → ряд после прогрева с режимом (полоса 2%) и фандингом. Правила 2, 3, 6."""
    raw = open(SRC[sym], "rb").read()
    d = pd.read_csv(io.BytesIO(raw))
    ms = d["ts"].to_numpy(np.int64)
    info = {"file": SRC[sym], "sha256": sha_bytes(raw), "rows": int(len(d)),
            "first_bar": iso(ms[0] // 1000), "last_bar": iso(ms[-1] // 1000),
            "missing_minutes": int((ms[-1] - ms[0]) // 60_000 + 1 - len(d))}
    if (ms % 60_000).any() or (np.diff(ms) <= 0).any():
        sys.exit(f"{sym}: метки не на минутной сетке или не строго возрастают — отказ")
    o, h, l, c = (d[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    if not (np.isfinite(np.c_[o, h, l, c]).all() and (l > 0).all() and (h >= l).all()):
        sys.exit(f"{sym}: битые OHLC — отказ")
    dayi = ms // DAY_MS
    days, first_i, cnt = np.unique(dayi, return_index=True, return_counts=True)
    full = cnt == DAY_MIN
    dc = pd.Series(np.nan, index=np.arange(days[0], days[-1] + 1))
    dc.loc[days[full]] = c[(first_i + cnt - 1)[full]]
    sma = dc.rolling(100).mean()
    st, out = None, pd.Series(np.nan, index=dc.index)
    for k in dc.index:                              # копия regime_buffer.banded
        x, s = dc[k], sma[k]
        if np.isnan(x) or np.isnan(s):
            st = None
            continue
        if st is None:
            st = x > s
        elif st and x < s * (1 - BAND):
            st = False
        elif not st and x > s * (1 + BAND):
            st = True
        out[k] = float(st)
    reg = out.shift(1).reindex(dayi).to_numpy()
    valid = ~np.isnan(reg)
    if not valid.any():
        sys.exit(f"{sym}: нет 100 полных дней прогрева — отказ")
    i0 = int(np.argmax(valid))
    if not valid[i0:].all():
        sys.exit(f"{sym}: режим неизвестен внутри окна — отказ")
    ts = ms[i0:] // 1000
    o, h, l, c, reg = o[i0:], h[i0:], l[i0:], c[i0:], reg[i0:].astype(bool)
    up = c >= o
    pts = np.c_[o, np.where(up, l, h), np.where(up, h, l), c].tolist()
    fr = pd.read_csv(FUND[sym])
    ft = fr["fundingTime"].to_numpy(np.int64) // 1000
    idx = np.searchsorted(ts, ft, side="right") - 1
    ok = (idx >= 0) & (ft >= ts[0]) & (ft < ts[-1] + 60)
    fund = {int(i): float(r) for i, r in zip(idx[ok], fr["fundingRate"].to_numpy(float)[ok])}
    wk = (ts - ts[0]) // WEEK
    wend = np.r_[wk[1:] != wk[:-1], True]
    n = len(ts)
    exits = int(((~reg[1:]) & reg[:-1]).sum())
    info.update({"window_after_warmup": [iso(ts[0]), iso(ts[-1])], "minutes": int(n),
                 "cut_half": iso(ts[n // 2]), "weeks": int(wk[-1] + 1), "long_share": round(float(reg.mean()), 4),
                 "regime_exits": exits, "regime_entries": int((reg[1:] & ~reg[:-1]).sum()),
                 "funding_settlements": len(fund), "funding_sha256": sha_file(FUND[sym]),
                 "funding_last": iso(int(ft[ok][-1])) if ok.any() else None,
                 "days_without_funding_at_end": round((ts[-1] + 60 - int(ft[ok][-1])) / 86400, 2) if ok.any() else None,
                 "funding_mean_rate_pct": round(float(np.mean(list(fund.values()))) * 100, 5)})
    D = {"sym": sym, "ts": ts.tolist(), "o": o.tolist(), "c": c.tolist(), "pts": pts, "reg": reg.tolist(),
         "fund": fund, "wend": wend.tolist(), "tick": TICK[sym], "qs": QSTEP[sym]}
    return D, info


def run(D: dict, step_pct: float, tgt_pct: float, fixed: float | None, cap: float, mx: int = BIG, i0: int = 0,
        force_long: bool = False, use_fund: bool = True, weeks: bool = False) -> dict:
    """Одна ячейка. Правила 1–3, 7. Лоты — стек [вход, объём, цель], последний — нижний (новый всегда ниже)."""
    o, c, pts, reg, wend = D["o"], D["c"], D["pts"], D["reg"], D["wend"]
    F = D["fund"] if use_fund else {}
    tick, qs = D["tick"], D["qs"]
    g, t = step_pct / 100, tgt_pct / 100
    dens = DENS * step_pct
    floor, ceil = math.floor, math.ceil
    lots: list = []
    Q = QE = real = fee = fund = 0.0
    vol = vol_close = flip_pnl = 0.0
    ent = tk = closes = 0
    ref = None
    prev = None
    peak = dd = 0.0
    atcap = mxl = 0
    dsum = 0.0                                       # Σ объём·цена входов — для фактической плотности
    n = len(o)
    mid = n // 2
    eq_mid = None
    wk = []
    eq = 0.0
    for i in range(i0, n):
        if i == mid and i0 == 0:
            eq_mid = real - fee - fund + Q * c[i - 1] - QE
        r = F.get(i)
        if r is not None and Q:
            fund += Q * o[i] * r
        act = True if force_long else reg[i]
        if prev and not act:                         # выход из лонга по режиму — всё по рынку
            if lots:
                px = o[i] * (1 - SLIP)
                pnl = Q * px - QE
                real += pnl
                flip_pnl += pnl
                fee += Q * px * TAKER
                vol_close += Q * px
                closes += 1
            lots = []
            Q = QE = 0.0
            ref = None
        prev = act
        for p in pts[i]:
            if lots and p >= lots[-1][2]:
                while lots and p >= lots[-1][2]:
                    e, q, tp = lots.pop()
                    real += q * (tp - e)
                    fee += q * tp * MAKER
                    vol += q * tp
                    Q -= q
                    QE -= q * e
                    tk += 1
                if not lots:
                    Q = QE = 0.0
            if not act:
                continue
            if lots:
                ref = lots[-1][0]
            elif ref is None or p > ref:
                ref = p
            lvl = floor(ref * (1 - g) / tick + 1e-9) * tick
            if p <= lvl:
                q = fixed if fixed else max(floor(dens / lvl / qs + 1e-9), 1) * qs
                if len(lots) < mx and max(QE, Q * lvl) + q * lvl <= cap:
                    lots.append([lvl, q, ceil(lvl * (1 + t) / tick - 1e-9) * tick])
                    fee += q * lvl * MAKER
                    vol += q * lvl
                    dsum += q * lvl
                    Q += q
                    QE += q * lvl
                    ent += 1
                    if len(lots) > mxl:
                        mxl = len(lots)
        eq = real - fee - fund + Q * c[i] - QE
        if eq > peak:
            peak = eq
        elif eq - peak < dd:
            dd = eq - peak
        if act and lots:
            lv = floor(lots[-1][0] * (1 - g) / tick + 1e-9) * tick
            qn = fixed if fixed else max(floor(dens / lv / qs + 1e-9), 1) * qs
            if len(lots) >= mx or max(QE, Q * lv) + qn * lv > cap:
                atcap += 1
        if weeks and wend[i]:
            wk.append(eq)
    bag = Q * c[-1] - QE
    res = {"total": real - fee - fund + bag, "real": real, "fee": fee, "fund": fund, "bag": bag, "lots_end": len(lots),
           "qty_end": Q, "dd": dd, "ent": ent, "tk": tk, "vol": vol, "turnover": vol + vol_close,
           "regime_closes": closes, "regime_close_pnl": flip_pnl, "hours_at_cap": atcap / 60,
           "max_orders": mxl + 1, "density_eff": (dsum / ent / step_pct) if ent else None}
    if i0 == 0:
        res["eq_mid"] = eq_mid
    if weeks:
        res["weekly_eq"] = wk
    return res


def check_sim(D: dict) -> list:
    """Правило 10: движок = week_reconcile.sim() на первых 200 000 минутах, всегда лонг, без фандинга, N2-ордер."""
    out = []
    k = 200_000
    S = dict(D, o=D["o"][:k], c=D["c"][:k], pts=D["pts"][:k], reg=D["reg"][:k], wend=D["wend"][:k], fund={})
    cells = [(0.1, 0.34), (0.6, 1.4)] if D["sym"] == "BTCUSDT" else [(0.2, 0.89)]
    fixed, cap = NORMS["N2"][D["sym"]]
    for s, t in cells:
        wr.SCHEDULE["CHK"] = [(0.0, str(fixed), cap, BIG)]
        g = {"sides": {"LONG": {"lots": [], "entry_order": None}}}
        cfg = {"step_pct": s, "target_pct": t, "price_tick": D["tick"]}
        ref = wr.sim("CHK", g, cfg, D["ts"][:k], S["pts"], S["c"], {})
        me = run(S, s, t, fixed, cap, force_long=True, use_fund=False)
        same = ref["ent"] == me["ent"] and ref["tk"] == me["tk"] and ref["lots"] == me["lots_end"]
        md = max(abs(ref["real"] - me["real"]), abs(ref["fee"] - me["fee"]), abs(ref["vol"] - me["vol"]),
                 abs(ref["bag"] - me["bag"]), abs(ref["qty"] - me["qty_end"]))
        ok = bool(same and md < 1e-6)
        out.append({"sym": D["sym"], "cell": f"{s:g}/{t:g}", "ok": ok, "max_abs_diff": md,
                    "sim": {x: ref[x] for x in ("ent", "tk", "lots")}, "engine": {"ent": me["ent"], "tk": me["tk"],
                                                                                 "lots": me["lots_end"]}})
        log(f"сверка с sim() {D['sym']} {s:g}/{t:g}: входы {ref['ent']}/{me['ent']}, тейки {ref['tk']}/{me['tk']}, "
            f"лотов {ref['lots']}/{me['lots_end']}, макс. расхождение $ {md:.2e} → {'совпало' if ok else 'НЕ СОВПАЛО'}")
    return out


def check_synthetic() -> dict:
    """Правило 10: закрытие по режиму и фандинг на трёх минутах."""
    S = {"sym": "BTCUSDT", "o": [100000.0, 99400.0, 99000.0], "c": [100000.0, 99400.0, 99000.0],
         "pts": [[100000.0] * 4, [99400.0] * 4, [99000.0] * 4], "reg": [True, True, False],
         "fund": {2: 0.001}, "wend": [False, False, True], "tick": 0.1, "qs": 0.0001}
    r = run(S, 0.6, 1.4, 0.0012, 12000.0)
    lvl = 99400.0
    px = 99000.0 * (1 - SLIP)
    want = {"real": 0.0012 * (px - lvl), "fee": 0.0012 * lvl * MAKER + 0.0012 * px * TAKER,
            "fund": 0.0012 * 99000.0 * 0.001}
    want["total"] = want["real"] - want["fee"] - want["fund"]
    diff = max(abs(r[k] - v) for k, v in want.items())
    ok = bool(diff < 1e-9 and r["ent"] == 1 and r["lots_end"] == 0 and r["regime_closes"] == 1)
    log(f"синтетика закрытия по режиму и фандинга: расхождение {diff:.1e} → {'совпало' if ok else 'НЕ СОВПАЛО'}")
    return {"ok": ok, "max_abs_diff": diff}


def one_second_decision() -> dict:
    cal = json.load(open(CALIB, encoding="utf-8"))["closeness_sum_rel_err"]["tk"]
    m1, s1, s1l = cal["M1"], cal["S1"], cal["S1L40"]
    need = s1 < m1 or s1l < m1
    return {"M1": m1, "S1": s1, "S1L40": s1l, "run_1s": bool(need),
            "decision": "условие выполнено — нужен прогон 1s" if need else
            "S1 и S1L40 не ближе к бирже, чем M1 — 1s не прогоняется (правило 6)"}


def pack(r: dict, half0: dict | None) -> dict:
    d = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items() if k != "weekly_eq"}
    tot, dd = r["total"], r["dd"]
    d["total_over_dd"] = round(tot / -dd, 3) if dd < 0 else None
    if "eq_mid" in r and r["eq_mid"] is not None:
        d["half1"] = round(r["eq_mid"], 2)
        d["half2_continuous"] = round(tot - r["eq_mid"], 2)
    if half0 is not None:
        d["half2_from_zero"] = round(half0["total"], 2)
        d["half2_from_zero_dd"] = round(half0["dd"], 2)
    return d


def boot(cells: dict, idx: np.ndarray, blocks4: np.ndarray, W: int) -> dict:
    """Правило 8: разность недельных приращений против 0.6/1.4."""
    inc = {k: np.diff(np.r_[0.0, np.asarray(v["weekly_eq"], float)]) for k, v in cells.items()}
    base = inc[f"{BASE[0]:g}/{BASE[1]:g}"]
    out = {}
    for k, x in inc.items():
        if len(x) != W:
            sys.exit(f"недель {len(x)} ≠ {W} — отказ")
        d = x - base
        obs = float(d.sum())
        bs = d[idx].sum(axis=1)
        b4 = d[blocks4].sum(axis=1)
        lo, hi = np.percentile(bs, [2.5, 97.5])
        lo4, hi4 = np.percentile(b4, [2.5, 97.5])
        out[k] = {"diff": round(obs, 2), "ci95": [round(float(lo), 2), round(float(hi), 2)],
                  "includes_zero": bool(lo <= 0 <= hi),
                  "ci95_4w_blocks (чувствительность)": [round(float(lo4), 2), round(float(hi4), 2)],
                  "includes_zero_4w": bool(lo4 <= 0 <= hi4)}
    return out


def neighbors_flat(cells: dict) -> dict:
    """Ворота 4: для каждой ячейки — соседи (шаг ±1, цель ±1) и есть ли знаки по обе стороны нуля."""
    out = {}
    for i, s in enumerate(STEPS):
        for j, t in enumerate(TGTS):
            nb = [(STEPS[a], TGTS[b]) for a, b in ((i - 1, j), (i + 1, j), (i, j - 1), (i, j + 1))
                  if 0 <= a < len(STEPS) and 0 <= b < len(TGTS)]
            signs = [cells[f"{x:g}/{y:g}"]["total"] > 0 for x, y in nb + [(s, t)]]
            out[f"{s:g}/{t:g}"] = {"neighbors": [f"{x:g}/{y:g}" for x, y in nb], "both_signs": len(set(signs)) > 1}
    return out


def main() -> None:
    t_start = time.time()
    check_only = "--check-only" in sys.argv
    res = {"rules_doc": "см. docstring matrix.py (записан до прогона)",
           "created_utc": datetime.now(timezone.utc).isoformat(), "git_head": git_head(),
           "inputs": {"matrix.py": sha_file(__file__),
                      "week_reconcile.py": sha_file("/Users/alexeychechikov/code/bot7/research/weex/week_reconcile.py"),
                      "calib_result.json": sha_file(CALIB)},
           "one_second": one_second_decision(), "data": {}, "checks": {"sim": [], "synthetic": None},
           "cells": {}, "bootstrap": {}, "flat_neighbors": {}}
    log("1s:", res["one_second"]["decision"])
    res["checks"]["synthetic"] = check_synthetic()
    if not res["checks"]["synthetic"]["ok"]:
        sys.exit("синтетика не совпала — отказ")
    for sym in SRC:
        tt = time.time()
        D, info = load(sym)
        res["data"][sym] = info
        log(f"{sym}: {json.dumps(info, ensure_ascii=False)} (загрузка {time.time() - tt:.0f} с)")
        chk = check_sim(D)
        res["checks"]["sim"] += chk
        if not all(x["ok"] for x in chk):
            json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            sys.exit("движок ≠ week_reconcile.sim() — отказ")
        if check_only:
            tt = time.time()
            run(D, 0.1, 0.34, None, 6000.0, weeks=True)
            log(f"проба времени одной ячейки 0.1/0.34 N1: {time.time() - tt:.1f} с (результат не печатается)")
            continue
        mid = len(D["o"]) // 2
        W = info["weeks"]
        rng = np.random.default_rng(SEED)
        idx = rng.integers(0, W, size=(NBOOT, W))
        nb = math.ceil(W / 4)
        starts = rng.integers(0, W - 3, size=(NBOOT, nb))
        blocks4 = (starts[:, :, None] + np.arange(4)[None, None, :]).reshape(NBOOT, -1)[:, :W]
        res["cells"][sym], res["bootstrap"][sym], res["flat_neighbors"][sym] = {}, {}, {}
        for norm in ("N1", "N2", SENS):
            fixed, cap = NORMS["N2" if norm == SENS else norm][sym]
            mx = 50 if norm == SENS else BIG
            raw = {}
            for s in STEPS:
                for t in TGTS:
                    tt = time.time()
                    full = run(D, s, t, fixed, cap, mx=mx, weeks=True)
                    half0 = run(D, s, t, fixed, cap, mx=mx, i0=mid) if norm != SENS else None
                    raw[f"{s:g}/{t:g}"] = (full, half0)
                    log(f"{sym} {norm} {s:g}/{t:g}: {time.time() - tt:.0f} с")
            cells = {k: pack(f, h) for k, (f, h) in raw.items()}
            res["cells"][sym][norm] = cells
            res["bootstrap"][sym][norm] = boot({k: f for k, (f, _) in raw.items()}, idx, blocks4, W)
            res["flat_neighbors"][sym][norm] = neighbors_flat(cells)
            with open(OUT, "w", encoding="utf-8") as f:
                json.dump(res, f, ensure_ascii=False, indent=1)
        del D
    res["runtime_sec"] = round(time.time() - t_start, 1)
    if check_only:
        log(f"проверки пройдены за {res['runtime_sec']} с; матрица не считалась")
        return
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    for sym in res["cells"]:
        for norm, cells in res["cells"][sym].items():
            log(f"\n=== {sym} {norm} ===")
            log(f"{'ячейка':>9} | {'итог':>7} {'1-я':>7} {'2-я неп':>7} {'2-я с 0':>7} | {'просадка':>8} {'итог/пр':>7} | "
                f"{'тейков':>6} {'оборот $':>10} {'комисс':>7} {'фандинг':>7} {'закр.реж':>8} | {'ч у потолка':>11} "
                f"{'заявок':>6} {'$/1%':>5} | {'Δ к 0.6/1.4':>11} {'ДИ 95%':>19}")
            bs = res["bootstrap"][sym][norm]
            for k, x in cells.items():
                b = bs[k]
                h2 = x.get("half2_from_zero")
                log(f"{k:>9} | {x['total']:+7.0f} {x.get('half1', 0):+7.0f} {x.get('half2_continuous', 0):+7.0f} "
                    f"{h2 if h2 is not None else float('nan'):+7.0f} | {x['dd']:+8.0f} "
                    f"{x['total_over_dd'] if x['total_over_dd'] is not None else float('nan'):7.2f} | {x['tk']:6d} "
                    f"{x['turnover']:10,.0f} {-x['fee']:+7.0f} {-x['fund']:+7.0f} {x['regime_close_pnl']:+8.0f} | "
                    f"{x['hours_at_cap']:11.0f} {x['max_orders']:6d} {x['density_eff'] or 0:5.0f} | {b['diff']:+11.0f} "
                    f"[{b['ci95'][0]:+8.0f};{b['ci95'][1]:+8.0f}]{'' if b['includes_zero'] else ' ≠0'}")
    log(f"\nготово за {res['runtime_sec']} с → {OUT}")


if __name__ == "__main__":
    main()
