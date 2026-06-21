"""Матрица сетап × режим: где какой эдж. Источник истины — точные TP/SL исходы.

2026-06-21: оператор «один сетап в разном режиме = разный эдж → не убивать,
найти нишу каждого и пускать только в нужном режиме». Этот скрипт:
  1) считает per-(тип,режим): n, WR, PF, RR, ожидание;
  2) помечает ARMED (PF>MIN_PF & n>=MIN_N) / WATCH (PF>MIN_PF но n мал) / dead;
  3) пишет state/setup_regime_edge.json — его грузит edge_stats (data-driven гейт).

Регенерится по мере накопления исходов → гейт остаётся актуальным.
"""
from __future__ import annotations

import json
import pathlib
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parents[1]
PREC = ROOT / "state" / "setup_precision_outcomes.jsonl"
OUT = ROOT / "state" / "setup_regime_edge.json"

MIN_PF = 1.2     # порог положительного эджа в режиме
MIN_N = 15       # для ARMED; меньше → WATCH (ниша есть, но мало данных)

# Общая статистика по типу (для отображения «в среднем» + fallback always-armed).
ALWAYS_ARMED = {"long_div_bos_15m", "long_div_bos_confirmed"}


def _metrics(pnls: list[float]) -> dict:
    n = len(pnls)
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    wr = 100 * len(wins) / n if n else 0.0
    aw = sum(wins) / len(wins) if wins else 0.0
    al = sum(losses) / len(losses) if losses else 0.0
    rr = aw / abs(al) if al < 0 else (99.0 if wins else 0.0)
    pf = sum(wins) / abs(sum(losses)) if (losses and sum(losses) != 0) else (99.0 if wins else 0.0)
    exp = sum(pnls) / n if n else 0.0
    return {"n": n, "wr": round(wr, 1), "pf": round(pf, 2),
            "rr": round(rr, 2), "exp": round(exp, 3)}


def main() -> None:
    by_type: dict[str, list] = defaultdict(list)
    by_cell: dict[tuple[str, str], list] = defaultdict(list)
    for ln in PREC.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            r = json.loads(ln)
        except json.JSONDecodeError:
            continue
        st, pnl, reg = r.get("setup_type"), r.get("pnl_pct"), r.get("regime")
        if st is None or pnl is None:
            continue
        by_type[st].append(pnl)
        if reg:
            by_cell[(st, reg)].append(pnl)

    armed: dict[str, dict] = {}      # пишем в json только ARMED+WATCH ниши
    print(f"{'тип':<24}{'режим':<16}{'n':>4}{'WR%':>6}{'PF':>7}{'RR':>6}{'ожид%':>8}  флаг")
    print("-" * 78)
    for st in sorted(by_type, key=lambda k: -_metrics(by_type[k])["pf"]):
        ov = _metrics(by_type[st])
        if ov["n"] < 10:
            continue
        # строка «всего»
        print(f"{st:<24}{'ВСЕГО':<16}{ov['n']:>4}{ov['wr']:>6}{ov['pf']:>7}{ov['rr']:>6}{ov['exp']:>+8.3f}")
        cells = {reg: _metrics(p) for (t, reg), p in by_cell.items() if t == st}
        for reg, m in sorted(cells.items(), key=lambda x: -x[1]["pf"]):
            if m["pf"] > MIN_PF and m["n"] >= MIN_N:
                flag = "✅ARMED"
                armed.setdefault(st, {})[reg] = {**m, "tier": "ARMED"}
            elif m["pf"] > MIN_PF:
                flag = "🟡WATCH"
                armed.setdefault(st, {})[reg] = {**m, "tier": "WATCH"}
            else:
                flag = "·"
            print(f"{'':<24}{reg:<16}{m['n']:>4}{m['wr']:>6}{m['pf']:>7}{m['rr']:>6}{m['exp']:>+8.3f}  {flag}")
        print()

    payload = {
        "computed_from": str(PREC.name),
        "min_pf": MIN_PF, "min_n": MIN_N,
        "always_armed": sorted(ALWAYS_ARMED),
        "overall": {st: _metrics(p) for st, p in by_type.items() if _metrics(p)["n"] >= 10},
        "regime_edge": armed,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    n_armed = sum(1 for v in armed.values() for c in v.values() if c["tier"] == "ARMED")
    n_watch = sum(1 for v in armed.values() for c in v.values() if c["tier"] == "WATCH")
    print(f"→ {OUT.name}: {n_armed} ARMED-ниш, {n_watch} WATCH-ниш, {len(payload['overall'])} типов")


if __name__ == "__main__":
    main()
