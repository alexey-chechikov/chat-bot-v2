"""Проверка исправлений 03.11 по замечаниям GPT 5bdaa84 (без данных, синтетика).
Запуск: check_fixes.py [<папка с review.py>] — по умолчанию эта папка; на копии review.py из 770f5a6 обязана упасть.
1) период A начинается 01.12.2017 (как в PREREG.md);
2) фандинг: расчёт на границе — до операций: вход на open в момент расчёта не платит, выход на open в момент расчёта
   платит;
3) просадка видит фандинг в момент расчёта, а не только при выходе."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
src = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE
sys.path.insert(0, str(HERE.parents[1] / "research" / "tv_lab_1025"))
sys.path.insert(0, str(src))
import review as R  # noqa: E402

H = 4 * 3600
fail = []

a0 = list(R.PERIODS.values())[0][0]
if a0 != "2017-12-01":
    fail.append(f"период A начинается {a0}, в PREREG — 12.2017")

D = R.Data.__new__(R.Data)
D.t = np.arange(10) * H                                  # бары 00, 04, 08, 12, 16, 20, 24, …
D.c = np.full(10, 100.0)
f = pd.Series([0.001, 0.002, 0.004], index=[8 * 3600, 16 * 3600, 24 * 3600])
D.ft, D.fcs = f.index.to_numpy(), np.r_[0.0, np.cumsum(f.to_numpy())]
got = D.fsum(2, 4)                                       # вход open 08:00, выход open 16:00
if abs(got - 0.002) > 1e-12:                             # платит только 16:00
    fail.append(f"fsum(вход 08:00, выход 16:00) = {got:.4f}, нужно 0.0020 (только расчёт 16:00)")

if hasattr(R, "equity"):
    u = {"j": 2, "k": 7, "side": 1, "px": 100.0, "net": 0.0}
    eq = R.equity(D, [u])                                # цена стоит: на закрытии бара 3 (16:00) уже заплачен 16:00
    want = -R.COST - 0.002
    if abs(eq[3] - want) > 1e-12:
        fail.append(f"переоценка на закрытии 16:00 = {eq[3]:+.4f}, нужно {want:+.4f} (фандинг 16:00 уже списан)")

print("OK" if not fail else "ПАДАЕТ:\n- " + "\n- ".join(fail))
sys.exit(1 if fail else 0)
