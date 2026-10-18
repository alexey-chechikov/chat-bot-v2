"""Статистика для research/trend_recheck по протоколу docs/TREND_4H_RECHECK_PROTOCOL_2026-10-15.md §3, §6:
периоды, трети P1, бутстрап блоками по ISO-неделям, совместная кривая капитала, ворота и статус. Чистые функции."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

import numpy as np

DAY = 86_400_000
SEED = 20261015
DRAWS = 9999
P1_START = 1577836800000          # 2020-01-01 00:00 UTC
P1_END = 1715731200000            # 2024-05-15 00:00 UTC
THIRD = (P1_END - P1_START) // 3  # 532 дня ровно
THIRDS = [(P1_START, P1_START + THIRD), (P1_START + THIRD, P1_START + 2 * THIRD), (P1_START + 2 * THIRD, P1_END)]


def iso_week(ts: int) -> str:
    return datetime.fromtimestamp(int(ts) / 1000, timezone.utc).strftime("%G-W%V")


def jsonable(x):
    if isinstance(x, dict):
        return {str(k): jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [jsonable(v) for v in x]
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, np.bool_):
        return bool(x)
    if isinstance(x, (np.floating, float)):
        x = float(x)
        return x if np.isfinite(x) else None
    return x


def done(trades: list[dict]) -> list[dict]:
    return [t for t in trades if not t["censored"]]


def in_period(trades: list[dict], period: str) -> list[dict]:
    if period == "full":
        return list(trades)
    return [t for t in trades if t["period"] == period]


def block(trades: list[dict]) -> dict:
    """Сводка по сделкам (censored показываются отдельно и в средние не входят)."""
    d = done(trades)
    cens = [t for t in trades if t["censored"]]
    out = {"n": len(d), "censored": len(cens), "censored_net": float(sum(t["net"] for t in cens))}
    if not d:
        out.update(mean_R=None, median_R=None, WR=None, PF=None, sum_net=0.0, sum_R=0.0, R50=0.0, mean_R_gross=None,
                   fees=0.0, funding=0.0, long_n=0, short_n=0, long_mean_R=None, short_mean_R=None)
        return out
    R = np.array([t["R"] for t in d])
    net = np.array([t["net"] for t in d])
    wins, losses = net[net > 0].sum(), -net[net < 0].sum()
    lo = [t["R"] for t in d if t["d"] > 0]
    sh = [t["R"] for t in d if t["d"] < 0]
    out.update(mean_R=float(R.mean()), median_R=float(np.median(R)), WR=float((net > 0).mean()),
               PF=float(wins / losses) if losses > 0 else None, sum_net=float(net.sum()), sum_R=float(R.sum()),
               R50=float(50 * R.sum()), mean_R_gross=float(np.mean([t["R_gross"] for t in d])),
               fees=float(sum(t["fee_in"] + t["fee_out"] for t in d)), funding=float(sum(t["funding"] for t in d)),
               long_n=len(lo), short_n=len(sh), long_mean_R=float(np.mean(lo)) if lo else None,
               short_mean_R=float(np.mean(sh)) if sh else None)
    return out


def exits(trades: list[dict]) -> dict:
    c = Counter(t["kind"] for t in trades)
    out = {}
    for k in ("close_exit", "emergency_stop", "gap_through_stop", "censored"):
        sel = [t for t in trades if t["kind"] == k]
        out[k] = {"n": c.get(k, 0), "mean_R": float(np.mean([t["R"] for t in sel])) if sel else None,
                  "sum_net": float(sum(t["net"] for t in sel))}
    return out


def weekly_ci(entry_ts, R, start: int, end: int, draws: int = DRAWS, seed: int = SEED) -> dict:
    """R15: блоки — все календарные ISO-недели [start, end) (пустые тоже); среднее повтора = ΣR/Σn."""
    days = np.arange(start - start % DAY, end, DAY)
    weeks = sorted({iso_week(d) for d in days})
    tot = {w: [0.0, 0.0] for w in weeks}
    for t, r in zip(entry_ts, R):
        w = iso_week(t)
        tot.setdefault(w, [0.0, 0.0])
        tot[w][0] += float(r)
        tot[w][1] += 1
    vals = np.asarray(list(tot.values()), float)
    nonempty = vals[vals[:, 1] > 0]
    out = {"weeks_all": int(len(vals)), "weeks_nonempty": int(len(nonempty)), "draws": draws, "seed": seed}
    for key, pool in (("all", vals), ("nonempty", nonempty)):
        if len(nonempty) < 2:
            out[key] = None
            continue
        rng = np.random.default_rng(seed)
        smp = pool[rng.integers(0, len(pool), size=(draws, len(pool)))].sum(axis=1)
        smp = smp[smp[:, 1] > 0]
        means = smp[:, 0] / smp[:, 1]
        out[key] = [float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))]
        out[f"{key}_draws_used"] = int(len(means))
    return out


def thirds(trades: list[dict]) -> list[dict]:
    d = done(trades)
    out = []
    for a, b in THIRDS:
        sel = [t for t in d if a <= t["entry_ts"] < b]
        blk = block(sel)
        out.append({"from": a, "to": b, "n": blk["n"], "mean_R": blk["mean_R"], "sum_net": blk["sum_net"]})
    return out


def equity_curve(trades: list[dict], mk: dict[str, dict]) -> tuple[np.ndarray, np.ndarray]:
    """R17: ось — объединение закрытий 4h-свечей символов; закрытые сделки (net) + плавающий результат открытых по
    close с комиссией входа и начисленным к метке фандингом. mk[sym] = {bend, bc, f_t, f_cum}, f_cum[i] = Σ_{<i}
    mark·rate."""
    grid = np.unique(np.concatenate([mk[s]["bend"] for s in mk]))
    eq = np.zeros(len(grid))
    step = np.zeros(len(grid) + 1)
    for t in trades:
        m = mk[t["sym"]]
        g0 = int(np.searchsorted(grid, t["entry_ts"], "right"))     # первая метка строго после входа
        g1 = len(grid) if t["censored"] else int(np.searchsorted(grid, t["exit_ts"], "left"))
        if g1 > g0:
            gt = grid[g0:g1]
            bi = np.searchsorted(m["bend"], gt, "right") - 1
            px = m["bc"][np.clip(bi, 0, None)]
            a = int(np.searchsorted(m["f_t"], t["entry_ts"], "right"))
            b = np.searchsorted(m["f_t"], gt, "right")
            fund = -t["d"] * t["qty"] * (m["f_cum"][b] - m["f_cum"][a])
            eq[g0:g1] += t["d"] * t["qty"] * (px - t["entry_fill"]) - t["fee_in"] + fund
        if not t["censored"]:
            step[g1] += t["net"]
    eq += np.cumsum(step)[:-1]
    return grid, eq


def max_dd(grid: np.ndarray, eq: np.ndarray) -> dict:
    if len(eq) == 0:
        return {"max_dd": 0.0, "final": 0.0, "trough_ts": None, "peak_ts": None}
    curve = np.concatenate([[0.0], eq])
    peak = np.maximum.accumulate(curve)
    dd = curve - peak
    i = int(np.argmin(dd))
    ip = int(np.argmax(curve[: i + 1])) if i > 0 else 0
    ts = np.concatenate([[grid[0]], grid])
    return {"max_dd": float(dd[i]), "final": float(curve[-1]), "trough_ts": int(ts[i]), "peak_ts": int(ts[ip])}


def _gt0(x) -> bool:
    return x is not None and x > 0


def gates(g: dict) -> list[dict]:
    """§6. g — словарь значений по портфелю ETH+XRP на P1 (собирается в run.py)."""
    ci = g["ci_all"]
    rows = [
        (1, "Среднее R после расходов > 0 и при ×2 проскальзывании > 0",
         _gt0(g["mean_R"]) and _gt0(g["mean_R_slip2"]), f"{_f(g['mean_R'])} / ×2: {_f(g['mean_R_slip2'])}"),
        (2, "Завершённых сделок ≥ 100, непустых ISO-недель ≥ 30",
         g["n"] >= 100 and g["weeks_nonempty"] >= 30, f"n = {g['n']}, недель {g['weeks_nonempty']}"),
        (3, "Нижняя граница 95% ДИ среднего R > 0 (блоки ISO-недель, 9 999, seed 20261015)",
         ci is not None and ci[0] > 0, f"[{_f(ci[0])}; {_f(ci[1])}]" if ci else "нет"),
        (4, "Последняя треть P1 > 0 и P2 > 0", _gt0(g["third3_mean_R"]) and _gt0(g["p2_mean_R"]),
         f"треть 3: {_f(g['third3_mean_R'])} (n {g['third3_n']}); P2: {_f(g['p2_mean_R'])} (n {g['p2_n']})"),
        (5, "Соседи (20,3), (45,3), (30,2.5), (30,4) — все > 0 на P1", all(_gt0(v) for v in g["neighbors"].values()),
         "; ".join(f"{k}: {_f(v)}" for k, v in g["neighbors"].items())),
        (6, "Все 4 смещения якоря > 0 на P1", all(_gt0(v) for v in g["offsets"].values()),
         "; ".join(f"{k}: {_f(v)}" for k, v in g["offsets"].items())),
        (7, "Ранг C1 ≤ 0.05", g["c1_rank"] is not None and g["c1_rank"] <= 0.05, f"{_f(g['c1_rank'], 3)}"),
    ]
    return [{"gate": n, "text": t, "pass": bool(p), "value": v} for n, t, p, v in rows]


def status(mean_R, n: int, gate_rows: list[dict]) -> str:
    if mean_R is None or mean_R <= 0:
        s = "Отвергнута"
    elif all(g["pass"] for g in gate_rows):
        s = "Квалифицирована"
    else:
        s = "Не квалифицирована"
    if n < 100:
        s += " (n < 100)"
    return s


def _f(x, nd: int = 4) -> str:
    return "—" if x is None else f"{x:+.{nd}f}" if nd == 4 else f"{x:.{nd}f}"
