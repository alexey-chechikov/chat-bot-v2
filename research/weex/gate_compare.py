"""Выключатель режима по SMA100 на сетке WEEX (живой конфиг BTC 0.2/0.21, 0.0012 BTC, $4 000, 50 ордеров).
Гейт новых входов (существующие лоты закрываются своими тейками):
  шорт — только когда вчерашнее закрытие дня НИЖЕ вчерашней SMA100 (проверен на 2 годах, CLAUDE.md);
  лонг (зеркало, не проверялось) — только когда ВЫШЕ.
Контроль (CLAUDE.md): тот же гейт, сдвинутый по кругу на случайное число дней — то же время в рынке и
то же число переключений, но не привязанный к цене. Гейт должен быть лучше почти всех сдвигов.
Запуск: gate_compare.py [SYM] [qty] [step] [target] [n_shifts]"""
import csv
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fast_grid as fg  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SYM = sys.argv[1] if len(sys.argv) > 1 else "BTCUSDT"
QTY = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0012
STEP = float(sys.argv[3]) if len(sys.argv) > 3 else 0.2
TGT = float(sys.argv[4]) if len(sys.argv) > 4 else 0.21
NSHIFT = int(sys.argv[5]) if len(sys.argv) > 5 else 0
CAP = 4000.0


def daily_regime():
    rows = list(csv.DictReader((ROOT / "data" / "historical" / f"daily_{SYM}.csv").open()))
    day = np.array([int(r["ts_ms"]) // 86_400_000 for r in rows])
    close = np.array([float(r["close"]) for r in rows])
    sma = np.convolve(close, np.ones(100) / 100, mode="full")[:len(close)]
    sma[:99] = np.nan
    above = close > sma                                  # режим по закрытию дня D
    return dict(zip(day.tolist(), above.tolist())), dict(zip(day.tolist(), (~np.isnan(sma)).tolist()))


def minute_gate(ts, shift_days=0):
    above, valid = daily_regime()
    days = ts // 86400
    # на минуте дня D действует режим дня D−1 (без заглядывания вперёд); сдвиг — для контроля
    prev = days - 1 - shift_days
    up = np.array([above.get(int(d), False) for d in prev])
    return {"SHORT": ~up, "LONG": up}


def run_variant(args):
    name, sides_gated, shift = args
    data = fg.load(SYM)
    gate = None
    if sides_gated:
        g = minute_gate(data[0], shift)
        gate = {sd: g[sd] for sd in sides_gated}
    r = fg.run(data, ("LONG", "SHORT"), STEP, TGT, order_qty=QTY, cap_usd=CAP, max_orders=50, gate=gate)
    return name, shift, r


if __name__ == "__main__":
    base = [("без гейта (сейчас)", (), 0), ("гейт шорта SMA100", ("SHORT",), 0),
            ("гейт лонга SMA100 (зеркало)", ("LONG",), 0), ("гейт обеих сторон", ("LONG", "SHORT"), 0)]
    with ProcessPoolExecutor(max_workers=3) as ex:
        res = list(ex.map(run_variant, base))
    data = fg.load(SYM)
    g = minute_gate(data[0])
    print(f"{SYM} шаг {STEP} цель {TGT} ордер {QTY}, {len(data[0]) / 1440:.0f} сут; шорт разрешён "
          f"{g['SHORT'].mean():.0%} времени, лонг (зеркало) {g['LONG'].mean():.0%}")
    print(f"{'вариант':<30} | {'ИТОГ':>7} {'закрыто':>8} {'мешок':>7} {'просадка':>8} {'оборот':>10} | по сторонам")
    for name, _, r in res:
        print(f"{name:<30} | {r['итог']:>7.0f} {r['закрыто']:>8.0f} {r['мешок']:>7.0f} {r['просадка капитала']:>8.0f} "
              f"{r['оборот']:>10,.0f} | {r['по сторонам']}")
    if NSHIFT:
        best = max(res[1:], key=lambda x: x[2]["итог"])
        sides = dict((n, s) for n, s, _ in base)[best[0]]
        rng = np.random.default_rng(7)
        shifts = sorted(set(int(x) for x in rng.integers(20, 280, NSHIFT)))
        with ProcessPoolExecutor(max_workers=3) as ex:
            ctrl = list(ex.map(run_variant, [(f"сдвиг {s} дн", sides, s) for s in shifts]))
        tots = np.array([r["итог"] for _, _, r in ctrl])
        better = int((tots >= best[2]["итог"]).sum())
        print(f"\nКонтроль для «{best[0]}» ({best[2]['итог']:.0f}): {len(shifts)} случайных сдвигов гейта по кругу — "
              f"итог от {tots.min():.0f} до {tots.max():.0f}, медиана {np.median(tots):.0f}; "
              f"не хуже настоящего гейта: {better} из {len(shifts)}")
