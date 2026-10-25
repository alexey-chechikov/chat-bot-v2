"""Полоса (буфер) вокруг SMA100 для выключателя лонг-сеток — 25.10, идея «буфера ребалансировки» Longmore / Robot Wealth
из отчёта GPT docs/WEEX_GPT_X_TRADERS_SCREEN_2026-10-25.md: не перестраивать позицию из-за малого сдвига сигнала.

ПРАВИЛА ДО ПРОГОНА (не менять после):
- режим как у живых сеток: дневки UTC по закрытым минутам (regime_grid.load), SMA100 дневных закрытий, решение на
  закрытии дня d действует в день d+1; полоса b — гистерезис: из ЛОНГА выйти, только если закрытие < SMA×(1−b); в ЛОНГ
  вернуться, только если закрытие > SMA×(1+b); b=0 — живое правило (сверка: совпадает с regime_grid по минутам);
- сетка — regime_grid.run, режим «longflat» (лонг выше, вне рынка ниже, на смене — закрытие по рынку тейкером
  0.048% + 0.02%), мейкер 0.016%, путь минуты path4; живые размеры из state/weex_grid*_config.json на 25.10:
  BTC 0.6/1.4 0.0012 $12 000 50 лотов; B34 0.1/0.34 0.0006 $4 462 61; B49 0.1/0.49 0.0006 $4 361 59;
  B89 0.1/0.89 0.0006 $3 709 56; ETH 0.6/1.4 0.020 $2 500 50;
- полосы — ровно 5 точек: 0, 0.5, 1, 2, 3 %;
- итог — полный капитал (закрыто − комиссии + мешок), без фандинга (лонги платят ≈8% лонгового PnL); половины —
  непрерывно, срез regime_grid; просадка — по закрытиям минут; смен режима.
Запуск: regime_buffer.py BTCUSDT|ETHUSDT --src=<копия frozen>

ПРОВЕРКА НА НОВОМ ПЕРИОДЕ (записано 25.10 ~12:00 CET, ДО прогона; повод — скользящие окна regime_buffer_roll.py:
прокси «держать лонг» с полосой 2% лучше живого в 80% двухлетних окон BTC и 94% ETH, 1% — в 67% / 62%):
- данные: минутки Binance spot 17.08.2017 – 15.05.2024 (backtests/frozen/<SYM>_1m_2017_2024.csv, research/weex/
  fetch_frozen_1m.py --end --out) — на них сетки ещё ни разу не гонялись;
- те же живые размеры в монете, полосы 0 / 1 / 2 % (0.5 и 3 не гоняем — уже видно, что хуже);
- ПРИНЯТЬ полосу, только если и для суммы 4 BTC-сеток, и для ETH: итог лучше полосы 0 И каждая половина периода лучше
  полосы 0 И сумма просадок не глубже полосы 0 больше чем на 10%;
- проходят обе — берём 1% (меньшее изменение); проходит одна — её; ни одна — живое правило не меняем;
- принятая полоса → правка торгового кода в worktree (порог режима с полосой в engine, по умолчанию 0) + тесты, в
  живое — только по «да» оператора."""
from __future__ import annotations

import io
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import regime_grid as rg  # noqa: E402

BANDS = next((tuple(float(x) for x in a.split("=", 1)[1].split(",")) for a in sys.argv[1:] if a.startswith("--bands=")),
             (0.0, 0.5, 1.0, 2.0, 3.0))                     # --bands=0,1,2 — проверка 2017–2024 (правила ниже)
GRIDS = {"BTCUSDT": [("BTC 0.6/1.4", 0.6, 1.4, 0.0012, 12000.0, 50), ("B34", 0.1, 0.34, 0.0006, 4462.0, 61),
                     ("B49", 0.1, 0.49, 0.0006, 4361.0, 59), ("B89", 0.1, 0.89, 0.0006, 3709.0, 56)],
         "ETHUSDT": [("ETH 0.6/1.4", 0.6, 1.4, 0.020, 2500.0, 50)]}


def banded(ts: np.ndarray, band: float) -> np.ndarray:
    """Режим с полосой по минутам ts (секунды), из тех же полных дней, что regime_grid.load."""
    d = pd.read_csv(io.BytesIO(rg.SRC.read_bytes()))
    ms = d["ts"].to_numpy(dtype=np.int64)
    c = d["close"].to_numpy(dtype=float)
    dayi = ms // rg.DAY_MS
    days, first_i, cnt = np.unique(dayi, return_index=True, return_counts=True)
    full = cnt == rg.DAY_MINUTES
    dc = pd.Series(np.nan, index=np.arange(days[0], days[-1] + 1))
    dc.loc[days[full]] = c[(first_i + cnt - 1)[full]]
    sma = dc.rolling(100).mean()
    b = band / 100
    st, out = None, pd.Series(np.nan, index=dc.index)
    for k in dc.index:
        x, s = dc[k], sma[k]
        if np.isnan(x) or np.isnan(s):
            st = None
            continue
        if st is None:
            st = x > s
        elif st and x < s * (1 - b):
            st = False
        elif not st and x > s * (1 + b):
            st = True
        out[k] = float(st)
    reg = out.shift(1).reindex((ts * 1000) // rg.DAY_MS).to_numpy()
    if np.isnan(reg).any():
        sys.exit("режим с полосой неизвестен внутри окна — отказ")
    return reg.astype(bool)


def init(base, regs):
    global BASE, REGS
    BASE, REGS = base, regs


def job(args):
    name, step, tgt, qty, cap, lots, band = args
    rg.MAX_LOTS = lots
    rg.DATA = (*BASE, REGS[band])
    _, _, _, _, _, eq, mid, dd, flips, _ = rg.run((name, "longflat", 0, step, tgt, qty, cap))
    return name, band, eq, mid, dd, flips


def main():
    base = rg.load()
    ts = base[0]
    regs = {b: banded(ts, b) for b in BANDS}
    same = float((regs[0.0] == base[5]).mean())
    print(f"{rg.SYM}: окно {pd.to_datetime(ts[0], unit='s').date()} … {pd.to_datetime(ts[-1], unit='s').date()}, "
          f"срез половин {rg.cut_label(ts)}; полоса 0 совпадает с живым режимом в {same:.4%} минут")
    if same < 0.9999:
        sys.exit("полоса 0 не воспроизводит живой режим — отказ")
    for b in BANDS:
        print(f"  полоса {b:g}%: выше SMA (в рынке) {regs[b].mean():.0%} времени")
    jobs = [(*g, b) for g in GRIDS[rg.SYM] for b in BANDS]
    with ProcessPoolExecutor(max_workers=3, initializer=init, initargs=(base[:5], regs)) as ex:
        res = list(ex.map(job, jobs))
    print(f"{'сетка':>12} {'полоса':>7} | {'итог':>7} {'1-я пол':>8} {'2-я пол':>8} | {'просадка':>9} {'смен':>5}")
    for name, band, eq, mid, dd, flips in res:
        print(f"{name:>12} {band:>6g}% | {eq:>+7.0f} {mid:>+8.0f} {eq - mid:>+8.0f} | {dd:>+9.0f} {flips:>5}")
    for b in BANDS:
        tot = [r for r in res if r[1] == b]
        print(f"{'ВСЕ сетки':>12} {b:>6g}% | {sum(r[2] for r in tot):>+7.0f} {sum(r[3] for r in tot):>+8.0f} "
              f"{sum(r[2] - r[3] for r in tot):>+8.0f} | (сумма просадок {sum(r[4] for r in tot):+.0f})")


if __name__ == "__main__":
    main()
