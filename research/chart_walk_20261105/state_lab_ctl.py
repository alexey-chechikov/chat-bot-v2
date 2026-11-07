"""Контроль описания шортов с пересчётом потока: настоящая метка часов против той же метки, сдвинутой по кругу. Те же доля и длительность разрешённых часов, автомат прогоняется заново на каждый сдвиг."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import entry_common as ec  # noqa: E402
import pos  # noqa: E402
import words2 as w2  # noqa: E402

REPS = 199


def label(a):
    fc, g, y, r, b, b1 = a["f_close"], a["f_G"], a["f_Y"], a["f_R"], a["f_B"], a["f_B1"]
    rising = b > np.r_[np.full(120, b[0]), b[:-120]]
    up, down = (g > y) & (y > r), (g < y) & (y < r)
    return (~up & ~down) | (up & (fc < b) & (fc < b1) & ~rising)


def main():
    rows = []
    rng = np.random.default_rng(20261105)
    for k, a, f in ec.load_all():
        L = label(a)
        real = w2.run(a, gate="lab", lab=L)
        base = w2.run(a, **w2.MAIN)
        assert [x[:5] for x in real] == [x[:5] for x in base], "метка обязана дать вариант A"
        tot = sum(w2.net(f, x) for x in real)
        sh = sum(w2.net(f, x) for x in real if x[4] == -1)
        b = a["i0"]
        N = len(L) - b
        ctl = []
        for _ in range(REPS):
            s = int(rng.integers(90 * 24, N - 90 * 24))
            Lk = L.copy()
            Lk[b:] = np.roll(L[b:], s)
            legs = w2.run(a, gate="lab", lab=Lk)
            ctl.append((sum(w2.net(f, x) for x in legs), sum(w2.net(f, x) for x in legs if x[4] == -1)))
        c = np.array(ctl)
        rows.append({"ряд": k, "A": round(tot), "A_шорт": round(sh), "сдвиги_медиана": round(float(np.median(c[:, 0]))), "сдвиги_95": round(float(np.quantile(c[:, 0], .95))), "лучше_%": round(float((c[:, 0] < tot).mean() * 100), 1), "шорт_медиана": round(float(np.median(c[:, 1]))), "шорт_95": round(float(np.quantile(c[:, 1], .95))), "шорт_лучше_%": round(float((c[:, 1] < sh).mean() * 100), 1)})
        print(rows[-1], flush=True)
    pd.DataFrame(rows).to_csv(pos.OUT / "state_lab_ctl.csv", index=False)


if __name__ == "__main__":
    main()
