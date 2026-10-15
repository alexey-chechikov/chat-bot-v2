"""Статистика для research/manual_pullback/replay.py по протоколу docs/PULLBACK_4H_PROTOCOL_2026-10-15.md:
сводка прогона, разрез 70/30 по календарю, месяцы, бутстрап блоками по ISO-неделям, статус по §«Проверка и статусы».
Чистые функции, без чтения файлов."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

import numpy as np

DAY = 86_400_000
SEED = 20261015
DRAWS = 9999


def iso_week(ts: int) -> str:
    return datetime.fromtimestamp(int(ts) / 1000, timezone.utc).strftime("%G-W%V")


def month(ts: int) -> str:
    return datetime.fromtimestamp(int(ts) / 1000, timezone.utc).strftime("%Y-%m")


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


def weekly_ci(entry_ts, R, start: int, end: int, draws: int = DRAWS, seed: int = SEED) -> dict:
    """Бутстрап блоками по ISO-неделям: кластеры — все календарные недели [start, end) (пустые тоже), в повторе
    среднее R = Σ R / Σ n выбранных недель; ДИ 95% — перцентили. Отдельно — только по непустым неделям."""
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
    return out


def _block(tr: list[dict]) -> dict:
    if not tr:
        return {"n": 0, "mean_R": None, "sum_pnl": 0.0, "WR": None}
    R = np.array([x["R"] for x in tr], float)
    pnl = np.array([x["pnl"] for x in tr], float)
    return {"n": len(tr), "mean_R": float(R.mean()), "sum_pnl": float(pnl.sum()), "WR": float((pnl > 0).mean())}


def max_drawdown(capital: float, pnl_in_exit_order) -> tuple[float, float]:
    eq = capital + np.concatenate([[0.0], np.cumsum(np.asarray(pnl_in_exit_order, float))])
    peak = np.maximum.accumulate(eq)
    dd = eq - peak
    i = int(np.argmin(dd))
    return float(dd[i]), float(dd[i] / peak[i]) if peak[i] else 0.0


def summarize(trades: list[dict], start: int, end: int, capital: float, counts: dict | None = None) -> dict:
    done = [x for x in trades if not x["censored"]]
    out = {"counts": dict(counts or {}), "censored": len(trades) - len(done), **_block(done)}
    if not done:
        out.update(weekly_ci=weekly_ci([], [], start, end), dev=_block([]), holdout=_block([]), monthly={},
                   exits={}, funding_total=0.0, mean_R_gross=None)
        return out
    R = np.array([x["R"] for x in done], float)
    pnl = np.array([x["pnl"] for x in done], float)
    cut = start + int(0.7 * (end - start))
    by_exit = sorted(done, key=lambda x: x["exit_ts"])
    dd_usd, dd_pct = max_drawdown(capital, [x["pnl"] for x in by_exit])
    wins, losses = pnl[pnl > 0].sum(), -pnl[pnl < 0].sum()
    months: dict[str, list] = {}
    for x in done:
        months.setdefault(month(x["entry_ts"]), []).append(x)
    out.update(
        median_R=float(np.median(R)),
        mean_R_gross=float(np.mean([x["R_gross"] for x in done])),
        PF=float(wins / losses) if losses > 0 else None,
        final_equity=float(capital + pnl.sum()),
        max_dd_usd=dd_usd, max_dd_pct=dd_pct,
        funding_total=float(sum(x["funding"] for x in done)),
        funding_events=int(sum(x["funding_n"] for x in done)),
        fees_total=float(sum(x["fee_in"] + x["fee_out"] for x in done)),
        exits=dict(Counter(x["kind"] for x in done)),
        exits_mean_R={k: float(np.mean([x["R"] for x in done if x["kind"] == k]))
                      for k in sorted({x["kind"] for x in done})},
        median_width=float(np.median([x["width"] for x in done])),
        mean_hold_min=float(np.mean([(x["exit_ts"] - x["entry_ts"]) / 60_000 for x in done])),
        split_cut=cut,
        dev=_block([x for x in done if x["entry_ts"] < cut]),
        holdout=_block([x for x in done if x["entry_ts"] >= cut]),
        long=_block([x for x in done if x["side"] > 0]),
        short=_block([x for x in done if x["side"] < 0]),
        by_symbol={s: _block([x for x in done if x["sym"] == s]) for s in sorted({x["sym"] for x in done})},
        monthly={m: _block(v) for m, v in sorted(months.items())},
        weekly_ci=weekly_ci([x["entry_ts"] for x in done], R, start, end),
    )
    return out


def _gt(a, b) -> bool:
    return a is not None and b is not None and a > b


def status(summary: dict, scope: str) -> dict:
    """Статус по протоколу. Кандидат — все ворота; Отвергнута — среднее после расходов ≤ 0 на всём периоде или на
    контрольной части; Недостаточно данных — n < 100 или ДИ включает 0 при оценке > 0; иначе — не прошла ворота."""
    runs = summary["runs"]
    s, s2 = runs[f"S_{scope}_base"], runs[f"S_{scope}_slip2"]
    c1, c2, c3 = runs[f"C1_{scope}_base"], runs[f"C2_{scope}_base"], summary["c3"].get(scope, {})
    ci = (s.get("weekly_ci") or {}).get("all")
    m = s.get("mean_R")
    gates = [
        ("завершённых сделок ≥ 100", s["n"] >= 100, s["n"]),
        ("непустых недель ≥ 20", (s.get("weekly_ci") or {}).get("weeks_nonempty", 0) >= 20,
         (s.get("weekly_ci") or {}).get("weeks_nonempty", 0)),
        ("среднее R после расходов > 0", _gt(m, 0), m),
        ("нижняя граница ДИ > 0", ci is not None and ci[0] > 0, ci),
        ("контрольная часть (последние 30%) > 0", _gt(s["holdout"]["mean_R"], 0), s["holdout"]["mean_R"]),
        ("> 0 при ×2 проскальзывании", _gt(s2.get("mean_R"), 0), s2.get("mean_R")),
        ("ранг C3 ≤ 0.05", c3.get("rank") is not None and c3["rank"] <= 0.05, c3.get("rank")),
        ("среднее выше C1", _gt(m, c1.get("mean_R")), c1.get("mean_R")),
        ("среднее выше C2", _gt(m, c2.get("mean_R")), c2.get("mean_R")),
    ]
    failed = [g[0] for g in gates if not g[1]]
    hold = s["holdout"]["mean_R"]
    if m is None:
        label = "Недостаточно данных (сделок нет)"
    elif m <= 0 or (hold is not None and hold <= 0):
        label = "Отвергнута"
        if s["n"] < 100:
            label += " (и n < 100)"
    elif not failed:
        label = "Кандидат на бумажный forward"
    elif s["n"] < 100 or ci is None or ci[0] <= 0 or hold is None:
        label = "Недостаточно данных"
    else:
        label = "Не квалифицирована"
    return {"label": label, "gates": [{"gate": g, "pass": bool(p), "value": v} for g, p, v in gates], "failed": failed}
