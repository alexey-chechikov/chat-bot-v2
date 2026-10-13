"""Контроли к sweep_backtest.py (протокол docs/GOLD_LIQUIDITY_SWEEP_PROTOCOL_2026-10-13.md, п.4, п.5, п.7), исправлено
по разбору GPT 13.10 §6 (П8):
  1) LVN против обычных уровней — нулевая гипотеза задана заранее:
     - на каждый день (и окно) ОДНО случайное размещение, общее для всех сигналов этого дня в данном повторе;
     - столько же зон тех же ширин, что у настоящих LVN-зон дня, только в корзинах зоны стоимости вне LVN, без
       пересечений и слияний (между зонами ≥ 1 свободная корзина); зоны ставятся по одной в случайном порядке, начало —
       равновероятно среди допустимых; тупик → до 100 новых попыток, иначе размещение дня НЕВАЛИДНО;
     - каждый контроль заново прогоняется через ту же событийную петлю E (sweep_backtest.simulate, капитал $3 000,
       после расходов): отказ от сигнала освобождает место следующему, как у настоящей E;
     - повтор, где петля спросила день с невалидным размещением, — невалиден; повтор без сделок — без ожидания; оба
       исключаются и считаются; ранг (k+1)/(n+1) по валидным, при n = 0 — NA;
     - 999 повторов, если укладываются в --max-minutes (по умолчанию 20), иначе сколько успело — число печатается;
  2) чувствительность окна LVN: 1 / 70 / 246 дней — E целиком заново (победитель не выбирается);
  3) MGC — только бюджетный фильтр ширины стопа НА ПРОКСИ: (вход − стоп прокси) × 10 + $3 расходов (допущение)
     ≤ 0.25% капитала, по сделкам A PAXG/XAU. Это не бэктест MGC (нет цен, сессий, роллов, шага MGC, маржи).

    .venv/bin/python3 research/gold/sweep_lvn_controls.py PAXG|XAU [--n=999] [--max-minutes=20] [--out=путь.json]
        [--data-root=/Users/alexeychechikov/code/bot7] [--funding=путь.csv]
"""
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sweep_backtest as sb  # noqa: E402

N_CTL = 999
SEED = 11
MAX_MINUTES = 20.0
PLACE_TRIES = 100


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


def place_zones(free: np.ndarray, widths, rng, tries: int = PLACE_TRIES):
    """Маска из len(widths) зон заданных ширин внутри `free`, без пересечений и слияний; None — разместить нельзя."""
    free = np.asarray(free, dtype=bool)
    n = len(free)
    widths = [int(w) for w in widths]
    if not widths:
        return np.zeros(n, dtype=bool)
    for _ in range(tries):
        avail = free.copy()
        ctl = np.zeros(n, dtype=bool)
        for w in rng.permutation(widths):
            w = int(w)
            if w > n:
                break
            c = np.r_[0, np.cumsum(avail)]
            starts = np.flatnonzero(c[w:] - c[:-w] == w)
            if not len(starts):
                break
            s = int(starts[rng.integers(len(starts))])
            ctl[s:s + w] = True
            avail[max(s - 1, 0):min(s + w + 1, n)] = False               # буфер: соседние зоны не сливаются
        else:
            return ctl
    return None


class ControlMarket:
    """Рынок для одного повтора контроля: всё как у настоящего, кроме lvn() — случайное размещение зон дня."""

    def __init__(self, base, rep: int, seed: int = SEED):
        self._base, self._rep, self._seed = base, rep, seed
        self._cache: dict = {}
        self.invalid: set = set()

    def __getattr__(self, name):
        return getattr(self._base, name)

    def lvn(self, day, window=sb.LVN_WINDOW):
        key = (int(day), int(window))
        if key not in self._cache:
            z = self._base.lvn(day, window)
            if z is None:
                out = None                                               # профиля нет — как у настоящей E
            else:
                edges, lvn, va = z
                rng = np.random.default_rng([self._seed, self._rep, key[0] + 10**6, key[1]])
                ctl = place_zones(np.asarray(va) & ~np.asarray(lvn), [w for _, w in runs(lvn)], rng)
                out = (edges, ctl, va) if ctl is not None else "invalid"
            self._cache[key] = out
        out = self._cache[key]
        if isinstance(out, str):
            self.invalid.add(key)
            return None
        return out


def _arg(name: str, default=None):
    return next((x.split("=", 1)[1] for x in sys.argv[1:] if x.startswith(f"--{name}=")), default)


def _mean(tr):
    return float(np.mean([t["R"] for t in tr])) if tr else float("nan")


def main() -> None:
    inst = next((x for x in sys.argv[1:] if x in sb.INST), "PAXG")
    n_ctl = int(_arg("n", N_CTL))
    max_min = float(_arg("max-minutes", MAX_MINUTES))
    out_path = _arg("out")
    root = Path(_arg("data-root", str(sb.ROOT)))
    a, info = sb.load(inst, root)
    funding = None
    if sb.INST[inst].get("funding_file"):
        fpath = Path(_arg("funding", str(root / sb.INST[inst]["funding_file"])))
        if not fpath.exists():
            sys.exit(f"{inst}: нет истории фандинга {fpath} — research/gold/fetch_xau_funding.py")
        funding, _ = sb.load_funding(fpath)
    m = sb.Market(a, inst, s1=False, funding=funding)
    res = {"inst": inst, "data_sha256": info.get("sha256"), "seed": SEED, "n_requested": n_ctl}
    # 1) настоящая E и контроли через ту же петлю
    real = sb.simulate(m, "E", 3000.0, "net")["trades"]
    real_mean = _mean(real)
    print(f"{inst}: E по-настоящему (окно 2 дня, после расходов, $3 000): n {len(real)}, ожидание {real_mean:+.3f}R")
    t0 = time.monotonic()
    means, ns = [], []
    done = invalid_reps = invalid_days = empty_reps = 0
    for r in range(n_ctl):
        if time.monotonic() - t0 > max_min * 60:
            break
        cm = ControlMarket(m, r)
        tr = sb.simulate(cm, "E", 3000.0, "net")["trades"]
        done += 1
        if cm.invalid:
            invalid_reps += 1
            invalid_days += len(cm.invalid)
            continue
        if not tr:
            empty_reps += 1
            continue
        means.append(_mean(tr))
        ns.append(len(tr))
    valid = len(means)
    if valid and np.isfinite(real_mean):
        k = int(np.sum(np.array(means) >= real_mean))
        rank = f"{(k + 1) / (valid + 1):.3f}"
    else:
        k, rank = None, "NA"
    med = f"{np.median(means):+.3f}R" if valid else "—"
    med_n = f"{np.median(ns):.0f}" if valid else "—"
    print(f"Контроль LVN: повторов {done} из {n_ctl} за {(time.monotonic() - t0) / 60:.1f} мин; невалидных (день без "
          f"допустимого размещения) {invalid_reps} (таких дней {invalid_days}), без сделок {empty_reps}, валидных "
          f"{valid}; медиана контроля {med}, сделок в контроле медиана {med_n}; не хуже настоящего "
          f"{k if k is not None else '—'}/{valid}, ранг {rank}")
    res["lvn_control"] = {"real_n": len(real), "real_mean_R": real_mean, "done": done, "invalid_reps": invalid_reps,
                          "invalid_days": invalid_days, "empty_reps": empty_reps, "valid": valid, "k": k, "rank": rank,
                          "ctl_median_R": float(np.median(means)) if valid else None,
                          "ctl_median_n": float(np.median(ns)) if valid else None,
                          "ctl_q05_q95_R": [float(x) for x in np.percentile(means, [5, 95])] if valid else None}
    # 2) окна LVN — E заново
    res["windows"] = {}
    for w in (1, 70, 246):
        tr = sb.simulate(m, "E", 3000.0, "net", lvn_window=w)["trades"]
        res["windows"][w] = {"n": len(tr), "mean_R": _mean(tr)}
        print(f"E окно {w} дн.: n {len(tr)}, среднее {_mean(tr):+.3f}R")
    # 3) MGC — бюджетный фильтр на прокси
    a_tr = sb.simulate(m, "A", 3000.0, "net")["trades"]
    res["mgc_proxy"] = {}
    for cap in sb.CAPITALS:
        budget = sb.RISK * cap
        risk = [(t["entry"] - t["stop"]) * 10 + 3.0 for t in a_tr]
        ok_n = sum(1 for x in risk if x <= budget)
        res["mgc_proxy"][int(cap)] = {"fit": ok_n, "n": len(a_tr), "median_risk": float(np.median(risk)) if risk else None}
        print(f"MGC-прокси при ${cap:,.0f} (бюджет ${budget:.2f}): укладываются {ok_n} из {len(a_tr)} сделок A; "
              f"медиана риска контракта на прокси ${(np.median(risk) if risk else float('nan')):.0f}")
    if out_path:
        Path(out_path).write_text(json.dumps(res, ensure_ascii=False, default=float), encoding="utf-8")


if __name__ == "__main__":
    main()
