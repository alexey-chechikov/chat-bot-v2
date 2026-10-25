"""Контроль полосы режима SMA100 по протоколу перепроверки GPT 25.10 (docs/WEEX_REGIME_BAND_ANSWERS_2026-10-25.md §8).

ПРАВИЛА ДО ПРОГОНА (записаны 25.10 до расчёта; живая полоса 2% включена 25.10 13:40 — этот прогон решает, остаётся ли):
- данные: один непрерывный ряд минуток Binance spot 17.08.2017 – 24.10.2026 (`--combine`: 2017–2024 после
  fill_outages.py со столбцом filled + копия frozen 2024–26); в заполненные минуты остановок биржи нет исполнений,
  входов и закрытий (regime_grid.run, маска остановки), граница режима — на первой торговой минуте;
- фандинг: Binance USDⓈ-M с 10.09.2019 (backtests/frozen/<SYM>_funding_full.csv), лонг платит ставку × номинал лотов
  по open минуты расчёта; до 10.09.2019 перпетуала не было — фандинг 0 (сказать в отчёте);
- пять живых лонг-сеток вместе, живые размеры (как regime_buffer.GRIDS); режим longflat; полосы — ВСЕ просмотренные:
  0 / 0.5 / 1 / 2 / 3 %; издержки ×1 для всех, ×2 (мейкер, тейкер и проскальзывание) — для 0 и 2 %;
- статистика: дневной PnL портфеля пяти сеток (BTC и ETH синхронно по дням UTC); D_k = PnL(полоса k) − PnL(0) по дням;
  S_k = сумма D_k за период;
- 10 000 круговых блочных повторов по дням, блок 30 дней, сид 20261025, ОДНИ И ТЕ ЖЕ индексы для всех полос;
  поправка на просмотр 4 полос — максимум-статистика: p_adj_k = (1 + #{max_j (S*_j − S_j) ≥ S_k}) / (1 + 10 000);
- ОТКАЗ полосе 2% (вернуть 0), если хоть одно: p_adj(2%) > 0.05; нижняя 95% граница S*_2 (2.5% квантиль) ≤ 0;
  максимальная просадка портфеля с полосой 2% глубже, чем без полосы, больше чем на 10%; S_2 при издержках ×2 ≤ 0.
  Пройдено — полоса остаётся, но история просмотрена: результат исследовательский, не новое подтверждение.
Запуск: --combine <2017_filled.csv> <frozen_2y.csv> <out.csv>; затем <SYM> --src=<out.csv> --out=<папка>;
затем --stats <папка>."""
from __future__ import annotations

import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

BANDS = (0.0, 0.5, 1.0, 2.0, 3.0)
STRESS = (0.0, 2.0)
REPS, BLOCK, SEED = 10_000, 30, 20261025
ROOT = Path(__file__).resolve().parents[2]


def combine(a: str, b: str, out: str) -> None:
    x = pd.read_csv(a)
    y = pd.read_csv(b)
    if "filled" not in x.columns:
        sys.exit(f"{a}: нет столбца filled — прогнать fill_outages.py заново")
    y["filled"] = 0
    if int(y["ts"].iloc[0]) - int(x["ts"].iloc[-1]) != 60_000:
        sys.exit(f"ряды не стыкуются: {x['ts'].iloc[-1]} → {y['ts'].iloc[0]}")
    z = pd.concat([x[["ts", "open", "high", "low", "close", "volume", "filled"]],
                   y[["ts", "open", "high", "low", "close", "volume", "filled"]]], ignore_index=True)
    z.to_csv(out, index=False)
    print(f"{out}: {len(z)} минут, заполнено остановок {int(z['filled'].sum())}")


def run_symbol() -> None:
    import regime_buffer as rb                              # читает символ и --src из argv (как regime_grid)
    rg = rb.rg
    out = Path(next(a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--out=")))
    out.mkdir(parents=True, exist_ok=True)
    base = rg.load()
    ts = base[0]
    raw = pd.read_csv(rg.SRC, usecols=["ts", "filled"])
    ms = raw["ts"].to_numpy(dtype=np.int64)
    halt = raw["filled"].to_numpy(dtype=bool)[np.searchsorted(ms, ts * 1000)]
    fr = pd.read_csv(ROOT / "backtests" / "frozen" / f"{rg.SYM}_funding_full.csv")
    ft = fr["fundingTime"].to_numpy(dtype=np.int64) // 1000
    pos = np.searchsorted(ts, ft)
    ok = (pos < len(ts)) & (ts[np.minimum(pos, len(ts) - 1)] == ft)
    fund = {int(p): float(r) for p, r in zip(pos[ok], fr["fundingRate"].to_numpy(float)[ok])}
    regs = {b: rb.banded(ts, b) for b in BANDS}
    print(f"{rg.SYM}: минут {len(ts)}, остановок {int(halt.sum())}, расчётов фандинга {len(fund)}")
    jobs = [(g, b, 1.0) for g in rb.GRIDS[rg.SYM] for b in BANDS] + \
           [(g, b, 2.0) for g in rb.GRIDS[rg.SYM] for b in STRESS]
    # готовые прогоны не пересчитываются (прогон можно прервать ради живых сеток и продолжить)
    jobs = [j for j in jobs if not (out / f"{j[0][0].split()[0]}_{j[1]:g}_x{j[2]:g}.json").exists()]
    print(f"осталось прогонов: {len(jobs)}", flush=True)
    workers = int(next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--workers=")), "5"))
    with ProcessPoolExecutor(max_workers=workers, initializer=_init, initargs=(base[:5], regs, halt, fund)) as ex:
        for (name, band, k), (eq, mid, dd, flips, daily) in zip(jobs, ex.map(_job, jobs)):
            f = out / f"{name[0].split()[0]}_{band:g}_x{k:g}.json"
            f.write_text(json.dumps({"grid": name[0], "band": band, "cost": k, "eq": eq, "mid": mid, "dd": dd,
                                     "flips": flips, "daily": daily}))
            print(f"  {name[0]:>12} полоса {band:g}% издержки ×{k:g}: итог {eq:+.0f}, просадка {dd:+.0f}, смен {flips}",
                  flush=True)


def _init(base, regs, halt, fund):
    global BASE, REGS, HALT, FUND
    BASE, REGS, HALT, FUND = base, regs, halt, fund


def _job(args):
    import regime_buffer as rb
    (name, step, tgt, qty, cap, lots), band, k = args
    rb.rg.MAX_LOTS = lots
    rb.rg.DATA = (*BASE, REGS[band], None, HALT, FUND)
    r = rb.rg.run((name, "longflat", 0, step, tgt, qty, cap, k, True))
    return r[5], r[6], r[7], r[8], r[10]


def stats(folder: str) -> None:
    runs = [json.loads(p.read_text()) for p in Path(folder).glob("*.json")]
    days = sorted({d for r in runs for d, _ in r["daily"]})
    idx = {d: i for i, d in enumerate(days)}

    def curve(band, k):
        e = np.zeros(len(days))
        sel = [r for r in runs if r["band"] == band and r["cost"] == k]
        for r in sel:
            v = np.full(len(days), np.nan)
            for d, x in r["daily"]:
                v[idx[d]] = x
            v = pd.Series(v).ffill().fillna(0.0).to_numpy()  # до старта сетки — 0
            e += v
        return e, len(sel)

    eq = {b: curve(b, 1.0) for b in BANDS}
    n_grids = {b: n for b, (_, n) in eq.items()}
    if len(set(n_grids.values())) != 1:
        sys.exit(f"не все прогоны на месте: {n_grids}")
    pnl = {b: np.diff(np.r_[0.0, e]) for b, (e, _) in eq.items()}
    D = {b: pnl[b] - pnl[0.0] for b in BANDS if b}
    S = {b: float(D[b].sum()) for b in D}
    n = len(days)
    rng = np.random.Generator(np.random.PCG64(SEED))
    star = {b: np.empty(REPS) for b in D}
    for r in range(REPS):
        st = rng.integers(0, n, size=-(-n // BLOCK))
        ii = ((st[:, None] + np.arange(BLOCK)[None, :]) % n).ravel()[:n]
        for b in D:
            star[b][r] = D[b][ii].sum()
    mx = np.max(np.vstack([star[b] - S[b] for b in D]), axis=0)
    dd = {b: float((e - np.maximum.accumulate(e)).min()) for b, (e, _) in eq.items()}
    half = n // 2
    print(f"дней {n} ({pd.to_datetime(days[0], unit='D').date()} … {pd.to_datetime(days[-1], unit='D').date()}), "
          f"сеток {n_grids[0.0]}, повторов {REPS}, блок {BLOCK} дн.")
    print(f"{'полоса':>7} | {'итог портфеля':>13} {'прибавка S':>11} {'1-я / 2-я половина':>20} | {'p':>6} {'p_adj':>6} "
          f"{'нижн.95%':>9} | {'просадка':>9}")
    for b in BANDS:
        e = eq[b][0]
        if b == 0:
            print(f"{b:>6g}% | {e[-1]:>+13.0f} {'—':>11} {'—':>20} | {'—':>6} {'—':>6} {'—':>9} | {dd[b]:>+9.0f}")
            continue
        p = (1 + int((star[b] - S[b] >= S[b]).sum())) / (1 + REPS)
        padj = (1 + int((mx >= S[b]).sum())) / (1 + REPS)
        lo = float(np.quantile(star[b], 0.025))
        h1, h2 = D[b][:half].sum(), D[b][half:].sum()
        print(f"{b:>6g}% | {e[-1]:>+13.0f} {S[b]:>+11.0f} {h1:>+9.0f} / {h2:>+8.0f} | {p:>6.4f} {padj:>6.4f} "
              f"{lo:>+9.0f} | {dd[b]:>+9.0f}")
    s2x, _ = curve(2.0, 2.0)
    s0x, _ = curve(0.0, 2.0)
    stress = float(s2x[-1] - s0x[-1])
    print(f"издержки ×2: без полосы {s0x[-1]:+.0f}, полоса 2% {s2x[-1]:+.0f} → прибавка {stress:+.0f}")
    padj2 = (1 + int((mx >= S[2.0]).sum())) / (1 + REPS)
    lo2 = float(np.quantile(star[2.0], 0.025))
    why = []
    if padj2 > 0.05:
        why.append(f"p_adj {padj2:.4f} > 0.05")
    if lo2 <= 0:
        why.append(f"нижняя 95% граница прибавки {lo2:+.0f} ≤ 0")
    if dd[2.0] < dd[0.0] * 1.10:
        why.append(f"просадка {dd[2.0]:+.0f} глубже {dd[0.0]:+.0f} больше чем на 10%")
    if stress <= 0:
        why.append(f"при издержках ×2 прибавка {stress:+.0f} ≤ 0")
    print("РЕШЕНИЕ: " + ("ОТКАЗ полосе 2% — " + "; ".join(why) if why else
                         "полоса 2% прошла все четыре условия (история просмотрена — исследовательский результат)"))


if __name__ == "__main__":
    if sys.argv[1] == "--combine":
        combine(*sys.argv[2:5])
    elif sys.argv[1] == "--stats":
        stats(sys.argv[2])
    else:
        sys.path.insert(0, str(Path(__file__).parent))
        run_symbol()
