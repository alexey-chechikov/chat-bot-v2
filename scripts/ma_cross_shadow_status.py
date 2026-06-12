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
    oc = r.get("outcomes", {})
    oc_s = " ".join(f"{h}:{v:+.1f}%" for h, v in oc.items()) or "(ждём)"
    tag = "✅H5" if r.get("passed_h5") else "✗" + (";".join(r.get("skip_reasons", []))[:30])
    print(f"{r['bar_ts_utc'][:16]} {r['symbol']:8} {r['dir']:5} {tag:34} entry {r['entry']} → {oc_s}")

# сводка по прошедшим H5 с готовым 24h-исходом
done = [r for r in passed if "24h" in r.get("outcomes", {})]
if done:
    import statistics
    rets = [r["outcomes"]["24h"] for r in done]
    wr = 100 * sum(1 for x in rets if x > 0) / len(rets)
    print(f"\nH5 с готовым 24h-исходом: n={len(done)} hit {wr:.0f}% mean {statistics.mean(rets):+.2f}%")
    print("(бэктест-ожидание: трендследящий, win ~40-50%, профит на PF; n<30 = рано судить)")
else:
    print("\n24h-исходов по H5 ещё нет — копим.")
