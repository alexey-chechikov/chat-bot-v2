"""Проверка правила «фактический шаг = шаг + динамический сдвиг» ВНЕ выборки (10.10).

Правило найдено на клоне 5678633257 (шаг 0.1 + ioo 0.06 → 0.16): оборот по месяцам 8/12 в ±15%, сумма месяцев
$1 520 против $1 471. Независимая проверка — другой клон 6227907209 (so 0.75, ioo 0.1 → шаг 0.2) и его развёртка
по 12 целям за год 25.09.2025–17.09.2026 (tools/eth_auto_sim.SWEEP, движок GinArea), которую 01.10 не повторил ни
один вариант (ошибка +135…−2400%). Механика — eth_auto_sim2 вариант «bar=False trail=none reset=both»."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))
from eth_auto_sim2 import bars, load, run  # noqa: E402
from tools.eth_auto_sim import SWEEP  # noqa: E402

P = bars(load("2025-09-25", "2026-09-17 09:20"), mode="ohlc")
print("клон 6227907209: so 0.75, ioo 0.1, шаг 0.1 → фактический 0.2; год 25.09.2025–17.09.2026")
for step in (0.1, 0.2):
    errs = []
    print(f"\nшаг в модели {step}:")
    for tgt, ga in SWEEP:
        r = run(P, target=tgt, step=step, so=0.75, ioo=0.1, per_bar=False, trail="none", reset="both")
        e = r["net"] / ga - 1
        errs.append(e)
        print(f"  цель {tgt:>4}: модель {r['net']:>+7,.0f}  GinArea {ga:>+7,.0f}  ({e:+.0%})  закрыто {r['closed']:>6,.0f} "
              f"оборот {r['turnover']:>8,.0f}  позиция {r['pos']:+.2f}")
    errs.sort()
    print(f"  медиана ошибки {errs[len(errs) // 2]:+.0%}; в ±15%: {sum(abs(x) <= 0.15 for x in errs)}/12; "
          f"в ±25%: {sum(abs(x) <= 0.25 for x in errs)}/12")
