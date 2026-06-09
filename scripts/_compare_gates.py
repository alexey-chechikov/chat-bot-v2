"""v5.7 (TEMA/price/hold2) vs Win-v2 (EMA/stack/hold5) + поиск баланса — в грид-$.
Вопрос: «чище на глаз» (меньше флипов) стоит ли крах-риска (лаг → больший мешок)?
Меряем: flips (чистота), net в чопе (харвест), max_bag в цикле (крах-риск). LONG-нога.
Бал-кандидат: TEMA/price/hold5 — чистота дебаунса БЕЗ EMA-лага. Reuse Win grid-sim.
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path("/Users/alexeychechikov/code/bot7")
sys.path.insert(0, str(ROOT))
from tools._grid_sim import load_1m, tema, sim, _load

AGG = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}


def _ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def zone_mask(close_1m, side, gate, ma, hold, band, tf="4h"):
    """Per-leg OPEN-STOP allow mask. gate=price|stack, ma=EMA|TEMA. Причинный сдвиг +tf."""
    c = close_1m.resample(tf).last().dropna()
    m100 = (tema(c, 100) if ma == "TEMA" else _ema(c, 100)).to_numpy(float)
    m200 = (tema(c, 200) if ma == "TEMA" else _ema(c, 200)).to_numpy(float)
    cc = c.to_numpy(float)
    if gate == "stack":
        raw_bull = (cc > m100) & (m100 > m200)
        raw_bear = (cc < m100) & (m100 < m200)
    else:  # price vs red(m200) ± band
        raw_bull = cc > m200 * (1 - band / 100)
        raw_bear = cc < m200 * (1 + band / 100)
    bull_only = raw_bull & ~raw_bear
    bear_only = raw_bear & ~raw_bull
    n = len(cc); zone = np.zeros(n, int); bu = be = mx = 0; z = 0
    for i in range(n):
        bu = bu + 1 if bull_only[i] else 0
        be = be + 1 if bear_only[i] else 0
        mx = mx + 1 if (not bull_only[i] and not bear_only[i]) else 0
        if bu >= hold: z = 1
        elif be >= hold: z = -1
        elif mx >= hold: z = 0
        zone[i] = z
    flips = int((np.diff(zone) != 0).sum())
    allow4h = (zone != -1) if side == "long" else (zone != 1)  # OPEN-STOP контр-ноги
    shifted = pd.Series(allow4h, index=c.index + pd.Timedelta(tf))
    mask = shifted.reindex(close_1m.index, method="ffill").fillna(False).astype(bool).to_numpy()
    return mask, flips


CONFIGS = [
    ("v5.7  TEMA/price/h2", "price", "TEMA", 2, 0.3),
    ("Win-v2 EMA/stack/h5", "stack", "EMA",  5, 0.0),
    ("бал   TEMA/price/h5", "price", "TEMA", 5, 0.3),
    ("бал   TEMA/stack/h5", "stack", "TEMA", 5, 0.0),
]


def run(label, a, b):
    ext, inwin = _load(a, b)
    close = ext[inwin]
    print(f"\n=== {label}  {a}→{b}  (LONG-нога, OPEN-STOP) ===")
    print(f"  {'конфиг':22s} {'flips':>6} {'net':>7} {'max_bag':>9}")
    for name, gate, ma, hold, band in CONFIGS:
        mask, flips = zone_mask(ext, "long", gate, ma, hold, band)
        r = sim(close, "long", allow=mask[inwin], close_on_disallow=False, close_mask=None)
        print(f"  {name:22s} {flips:>6} {r['profit']:>7.0f} {r['max_bag']:>9.0f}")


def main():
    run("ЧОП (харвест)", "2024-06-01", "2024-10-01")
    run("ЦИКЛ (крах-риск)", "2025-04-01", "2026-02-15")


if __name__ == "__main__":
    main()
