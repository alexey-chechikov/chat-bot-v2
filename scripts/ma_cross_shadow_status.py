"""Статус форвард-сбора MA-cross H5: сколько сигналов, как идут исходы.
Запуск: .venv/bin/python3 scripts/ma_cross_shadow_status.py"""
import json
from pathlib import Path

J = Path("/Users/alexeychechikov/code/bot7/state/ma_cross_shadow.jsonl")
if not J.exists():
    print("Журнал пуст — сигналов ещё не было (кросс ~1.7/мес на символ).")
    raise SystemExit(0)

recs = []
for ln in J.read_text(encoding="utf-8").splitlines():
    try:
        recs.append(json.loads(ln))
    except json.JSONDecodeError:
        pass

passed = [r for r in recs if r.get("passed_h5")]
print(f"Всего сигналов: {len(recs)}  ·  прошли H5: {len(passed)}  ·  skip: {len(recs)-len(passed)}\n")

for r in recs[-20:]:
    xc = r.get("outcome_cross")
    xc_s = f"cross→{xc:+.1f}%" if xc is not None else "cross:откр"
    tag = "✅H5" if r.get("passed_h5") else "✗" + (";".join(r.get("skip_reasons", []))[:28])
    print(f"{r['bar_ts_utc'][:16]} {r['symbol']:8} {r['dir']:5} {tag:32} entry {r['entry']} → {xc_s}")

# ГЛАВНАЯ метрика (ревью Вина): cross-to-cross = тот же бенчмарк, что +117пп/PF 2.5
def _summ(rows, label):
    xs = [r["outcome_cross"] for r in rows if r.get("outcome_cross") is not None]
    if not xs:
        print(f"\n{label}: закрытых cross-to-cross ещё нет — копим.")
        return
    wins = [x for x in xs if x > 0]
    loss = [x for x in xs if x <= 0]
    pf = (sum(wins) / abs(sum(loss))) if loss else float("inf")
    print(f"\n{label}: n={len(xs)} net {sum(xs):+.1f}пп win {100*len(wins)/len(xs):.0f}% PF {pf:.2f}")

_summ(passed, "H5 (cross-to-cross — СРАВНИВАТЬ с бэктестом +117пп/PF 2.5)")
_summ(recs, "БАЗА все кроссы (бэктест +102пп/PF 1.73)")
print("(n<20 закрытых = рано судить; кросс ~1.7/мес на символ → ~10 закрытых/мес на 3 символах)")
