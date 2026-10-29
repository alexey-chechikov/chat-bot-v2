"""Переписывает ли CoinGlass историю задним числом (GPT a7d799b §6.2 «доступность данных по времени»).

Правило (до прогона, 28.10.2026): для BTCUSDT и ETHUSDT каждый бар, который есть и в глубокой выгрузке
research/coinglass_compare/data/<SYM>_1h.csv, и в живом журнале state/coinglass/tv/<SYM>_1h.jsonl (только чтение),
сравнивается по каждому столбцу: значение ПЕРВОЙ записи журнала с closed=true против значения выгрузки. Расхождение —
относительная разница > 1e-6 (или одно из значений пустое, другое нет). Отдельно — бары, у которых первая закрытая
запись сделана меньше чем через 2 ч после конца бара (последний закрытый час выгрузки), и остальные.

    .venv/bin/python3 research/indicator_atlas/revision_audit.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from services.coinglass_web import tv_export  # noqa: E402

DATA = ROOT / "research" / "coinglass_compare" / "data"
TV = ROOT / "state" / "coinglass" / "tv"
OUT = Path(__file__).resolve().parent / "revision_audit_result.json"


def differs(a, b) -> bool:
    if a is None or (isinstance(a, float) and pd.isna(a)):
        return not (b is None or (isinstance(b, float) and pd.isna(b)))
    if b is None or (isinstance(b, float) and pd.isna(b)):
        return True
    a, b = float(a), float(b)
    return abs(a - b) > 1e-6 * max(1.0, abs(a), abs(b))


def main() -> None:
    res = {}
    for sym in ("BTCUSDT", "ETHUSDT"):
        deep = pd.read_csv(DATA / f"{sym}_1h.csv")
        deep.index = pd.to_datetime(deep.pop("bar_utc"), utc=True)
        first: dict = {}
        for line in open(TV / f"{sym}_1h.jsonl", encoding="utf-8"):
            r = json.loads(line)
            if r.get("closed") and r["bar"] not in first:
                first[r["bar"]] = r
        out = {"fresh": {}, "old": {}}
        absent = {"fresh": {}, "old": {}}
        rel = {"fresh": {}, "old": {}}
        n = {"fresh": 0, "old": 0}
        for bar, r in first.items():
            t = pd.Timestamp(bar)
            if t not in deep.index:
                continue
            lag_h = (datetime.fromisoformat(r["obs"]) - t.to_pydatetime()).total_seconds() / 3600
            grp = "fresh" if lag_h < 2 else "old"
            n[grp] += 1
            for c in tv_export.COLUMNS:
                if c not in r:                                   # столбца ещё не было в выгрузке (индикатор добавлен позже)
                    absent[grp][c] = absent[grp].get(c, 0) + 1
                    continue
                if differs(r.get(c), deep.at[t, c]):
                    out[grp][c] = out[grp].get(c, 0) + 1
                    a, b = r.get(c), deep.at[t, c]
                    if a is not None and not pd.isna(b) and b != 0:
                        rel[grp].setdefault(c, []).append(abs(float(a) - float(b)) / abs(float(b)))
        med = {g: {c: float(pd.Series(v).median()) for c, v in d.items()} for g, d in rel.items()}
        res[sym] = {"bars": n, "differs": out, "absent_in_first_record": absent, "median_rel_diff": med}
        print(sym, "баров:", n)
        for grp in ("fresh", "old"):
            bad = {c: f"{k}/{n[grp]} (медиана отн. разницы {med[grp].get(c, float('nan')):.1%})"
                   for c, k in sorted(out[grp].items(), key=lambda x: -x[1])}
            print(f"  {grp}: расходятся", bad or "ничего", "| столбца не было в первой записи:", absent[grp] or "—")
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
