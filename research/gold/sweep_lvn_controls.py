"""Контроли к sweep_backtest.py (протокол docs/GOLD_LIQUIDITY_SWEEP_PROTOCOL_2026-10-13.md, п.4, п.5, п.7):
  1) LVN против обычных уровней: сделки B (после расходов, капитал $3 000), у которых уровень L у LVN-зоны, против
     сделок B у случайных НЕ-LVN корзин зоны стоимости той же ширины и количества; 999 повторов; ранг (k+1)/(n+1);
  2) чувствительность окна LVN: 1 / 70 / 246 дней (как фильтр сделок B; победитель не выбирается);
  3) реализуемость на MGC (10 унций, тик $0.10 = $1): риск контракта = (вход − стоп) × 10 + $2 комиссия круга +
     $1 проскальзывание (допущение) ≤ 0.25% капитала — сколько сделок A исполнимо при $1 000 / $3 000 / $5 000.

    .venv/bin/python3 research/gold/sweep_lvn_controls.py PAXG|XAU
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sweep_backtest as sb  # noqa: E402

N_CTL = 999


def runs(mask: np.ndarray) -> list[tuple[int, int]]:
    out, i = [], 0
    while i < len(mask):
        if mask[i]:
            j = i
            while j < len(mask) and mask[j]:
                j += 1
            out.append((i, j - i))
            i = j
        else:
            i += 1
    return out


def main() -> None:
    inst = next((x for x in sys.argv[1:] if x in sb.INST), "PAXG")
    a, info = sb.load(inst)
    m = sb.Market(a, inst, s1=False)
    base = sb.simulate(m, "B", 3000.0, "net")["trades"]
    print(f"{inst}: сделок B (после расходов, $3 000) {len(base)}")
    # 1) LVN (окно 2) против случайных корзин
    rng = np.random.default_rng(11)
    real_mask, ctl_hits = [], np.zeros((N_CTL, len(base)), dtype=bool)
    for i, t in enumerate(base):
        day = t["sig_ts"] // sb.DAY
        z = m.lvn(day, sb.LVN_WINDOW)
        if z is None:
            real_mask.append(False)
            continue
        edges, lvn, va = z
        real_mask.append(sb.Market.near_zone(t["level"], edges, lvn))
        zones = runs(lvn)
        free = va & ~lvn
        for r in range(N_CTL):
            ctl = np.zeros_like(lvn)
            for _, w in zones:
                starts = [s for s in np.flatnonzero(free) if s + w <= len(free) and free[s:s + w].all()]
                if starts:
                    s = starts[rng.integers(0, len(starts))]
                    ctl[s:s + w] = True
            ctl_hits[r, i] = sb.Market.near_zone(t["level"], edges, ctl)
    R = np.array([t["R"] for t in base])
    real_mask = np.array(real_mask)
    real = R[real_mask].mean() if real_mask.any() else float("nan")
    ctl = np.array([R[h].mean() if h.any() else np.nan for h in ctl_hits])
    ok = ~np.isnan(ctl)
    k = int((ctl[ok] >= real).sum()) if not np.isnan(real) else None
    print(f"LVN (окно 2 дня): у LVN {int(real_mask.sum())} из {len(base)} сделок B, ожидание {real:+.3f}R; случайные "
          f"корзины: медиана {np.nanmedian(ctl):+.3f}R, в среднем сделок {ctl_hits.sum(1).mean():.1f}; не хуже настоящего "
          f"{k}/{int(ok.sum())}, ранг {(k + 1) / (ok.sum() + 1):.3f}" if k is not None else "LVN: сделок у зон нет")
    # 2) окна 1 / 70 / 246
    for w in (1, 70, 246):
        hit = []
        for t in base:
            z = m.lvn(t["sig_ts"] // sb.DAY, w)
            hit.append(z is not None and sb.Market.near_zone(t["level"], z[0], z[1]))
        hit = np.array(hit)
        print(f"LVN окно {w} дн.: у LVN {int(hit.sum())} сделок, ожидание "
              f"{(R[hit].mean() if hit.any() else float('nan')):+.3f}R")
    # 3) MGC
    a_tr = sb.simulate(m, "A", 3000.0, "net")["trades"]
    for cap in sb.CAPITALS:
        budget = sb.RISK * cap
        ok_n = sum(1 for t in a_tr if (t["entry"] - t["stop"]) * 10 + 3.0 <= budget)
        print(f"MGC при ${cap:,.0f} (риск ${budget:.2f}): исполнимо {ok_n} из {len(a_tr)} сигналов A; "
              f"медиана риска контракта ${np.median([(t['entry'] - t['stop']) * 10 + 3 for t in a_tr]):.0f}")


if __name__ == "__main__":
    main()
