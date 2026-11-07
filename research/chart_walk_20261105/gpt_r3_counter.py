"""Контрпримеры разбора GPT 37233f5 на чистых функциях ledger: падают на 578ce3e, проходят после правки. Запуск: python gpt_r3_counter.py"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import ledger as lg  # noqa: E402


def zero_shift_equals_ledger():
    """Покупка 100, тейк 110, закрытие выходного часа 80: контроль обязан считать от той же сделки, что и учёт."""
    n = 6000
    c = np.full(n, 100.0)
    c[10] = 80.0
    a = {"i0": 0, "c": c}
    fm = np.zeros(n)
    tr = (5, 10, 100.0, 110.0, 1)
    led = sum(np.array(lg.trade_cash(fm, tr)) * (1, -1, -1)) / lg.NOTIONAL * 100
    out = lg.shift_rank(a, fm, [tr])
    assert abs(out["всё"]["сумма_%"] - round(float(led), 1)) < 0.11, f"нулевой сдвиг {out['всё']['сумма_%']} против учёта {led:.2f}"


def funding_after_end_ignored():
    """Выплата после последнего бара не должна попасть в последний бар."""
    a = {"t": np.array([3600, 7200, 10800]), "c": np.array([100.0, 100.0, 100.0])}
    fund = pd.Series([0.01, 0.5], index=[7200, 90000])
    fm = lg.funding_marks(a, fund)
    assert abs(fm[-1] - 1.0) < 1e-9, f"накоплено {fm[-1]}, ожидалось 1.0"


def main():
    fails = 0
    for f in (zero_shift_equals_ledger, funding_after_end_ignored):
        try:
            f()
            print("OK", f.__name__, flush=True)
        except AssertionError as e:
            fails += 1
            print("FAIL", f.__name__, e, flush=True)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
