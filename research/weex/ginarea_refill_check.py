"""Где GinArea ставит следующий вход после тейка (шортовый бот, выход по ордерам).
Цена каждого входа восстанавливается из изменения позиции и средней:
  цена = (|поз1|·ср1 − |поз0|·ср0) / (|поз1| − |поз0|).
Закрытые тейком входы — по той же формуле (снятая стоимость / снятый объём).
Для каждого входа после тейка сравниваем: от какого уровня он отсчитан —
  A) от последнего исполненного входа (даже закрытого) или
  B) от самого верхнего ещё ОТКРЫТОГО входа (уровень заполняется снова)."""
import csv
import sys
from pathlib import Path

BOT = sys.argv[1] if len(sys.argv) > 1 else "5021652508"
f = Path(__file__).with_name(f"ginarea_dyn_{BOT}.csv")
rows = list(csv.DictReader(f.open()))

stack: list[float] = []         # открытые входы (восстановленные)
last_in = None
prev = None
after_out = False
tests = []
for r in rows:
    pos, avg = abs(float(r["position"] or 0)), float(r["avg"] or 0)
    ic, oc = int(r["in_cnt"] or 0), int(r["out_cnt"] or 0)
    if prev is None or r["status"] != "2":
        prev = (pos, avg, ic, oc)
        continue
    p0, a0, ic0, oc0 = prev
    gs = float(r["gs"] or 0) / 100
    if oc > oc0 and pos < p0 - 1e-9:
        q = p0 - pos
        px = (p0 * a0 - pos * avg) / q if q else 0
        print(f"{r['ts']} ТЕЙК  снято {q:.4f} по средней входа {px:,.1f} | цена {float(r['close']):,.1f}")
        # снимаем из стека самые верхние входы на этот объём (у шорта первыми закрываются верхние)
        stack.sort()
        while stack and q > 1e-9:
            stack.pop()
            q -= float(r.get("q") or 0) or 0.01
        after_out = True
    elif ic > ic0 and pos > p0 + 1e-9:
        q = pos - p0
        px = (pos * avg - p0 * a0) / q
        top = max(stack) if stack else None
        exp_a = last_in * (1 + gs) if last_in else None
        exp_b = top * (1 + gs) if top else None
        tag = ""
        if after_out and exp_a and exp_b:
            da, db = abs(px / exp_a - 1) * 100, abs(px / exp_b - 1) * 100
            tag = f"  ← после тейка: A ждал {exp_a:,.1f} ({da:.2f}%), B ждал {exp_b:,.1f} ({db:.2f}%)"
            tests.append("A" if da < db else "B")
        print(f"{r['ts']} ВХОД  {q:.4f} по {px:,.1f} (шаг {gs * 100:.2f}%) | открытых было {len(stack)}{tag}")
        stack.append(px)
        last_in = px
        after_out = False
    prev = (pos, avg, ic, oc)
print(f"\nпроверок после тейка: {len(tests)}; ближе к A (от последнего исполненного): {tests.count('A')}, "
      f"к B (от верхнего открытого): {tests.count('B')}")
