"""Где Win-v3 (TEMA/stack/hold5) даёт ПЛОХОЙ OPEN-сигнал на BTC 4h — спорные окна оператору.
Слабость = лаг (hold5+стек): «ОТКР ЛОНГ» у вершины перед сливом / «ОТКР ШОРТ» у дна перед ралли.
Метрика: forward-доход в сторону сигнала за ~3 дня + худшая просадка по ходу. Худшие = спорные окна.
"""
import sys
from pathlib import Path
import numpy as np

ROOT = Path("/Users/alexeychechikov/code/bot7")
sys.path.insert(0, str(ROOT))
from tools._grid_sim import load_1m, tema

HOLD, FWD = 5, 18


def zone_series(c4h, use_tema=True):
    m100 = (tema(c4h, 100) if use_tema else c4h.ewm(span=100, adjust=False).mean()).to_numpy(float)
    m200 = (tema(c4h, 200) if use_tema else c4h.ewm(span=200, adjust=False).mean()).to_numpy(float)
    cc = c4h.to_numpy(float)
    bull = (cc > m100) & (m100 > m200)
    bear = (cc < m100) & (m100 < m200)
    n = len(cc); zone = np.zeros(n, int); br = sr = mr = 0; z = 0
    for i in range(n):
        br = br + 1 if bull[i] else 0
        sr = sr + 1 if bear[i] else 0
        mr = mr + 1 if (not bull[i] and not bear[i]) else 0
        if br >= HOLD: z = 1
        elif sr >= HOLD: z = -1
        elif mr >= HOLD: z = 0
        zone[i] = z
    return zone


def main():
    df = load_1m("2024-01-01", "2026-12-31")
    c = df["close"].resample("4h").last().dropna()
    idx = c.index; cc = c.to_numpy(float)
    zone = zone_series(c, use_tema=True)
    rows = []
    for i in range(1, len(cc) - FWD):
        oL = zone[i] == 1 and zone[i - 1] != 1
        oS = zone[i] == -1 and zone[i - 1] != -1
        if oL or oS:
            d = 1 if oL else -1
            fwd = (cc[i + FWD] / cc[i] - 1) * 100 * d
            seg = (cc[i + 1:i + FWD + 1] / cc[i] - 1) * 100 * d
            rows.append((i, idx[i], "ЛОНГ" if oL else "ШОРТ", cc[i], round(fwd, 1), round(float(seg.min()), 1)))
    rows.sort(key=lambda r: r[4])
    # дедуп: отдельные окна (>40 баров = >6 дней друг от друга)
    picked = []
    for r in rows:
        if all(abs(r[0] - p[0]) > 40 for p in picked):
            picked.append(r)
        if len(picked) >= 8:
            break
    print("=== Win-v3 (TEMA/stack/hold5) — ХУДШИЕ OPEN-сигналы BTC 4h (forward 3 дня) ===")
    print(f"{'дата (UTC)':17s} {'сигнал':6s} {'цена':>9} {'fwd 3д %':>9} {'худшая %':>9}")
    for _, ts, sig, px, fwd, mae in picked:
        print(f"{str(ts)[:16]:17s} {sig:6s} {px:>9.0f} {fwd:>9.1f} {mae:>9.1f}")
    print("\n(fwd<0 = сигнал пошёл ПРОТИВ; худшая = просадка по ходу. Это окна-лаг: открыл у разворота.)")


if __name__ == "__main__":
    main()
