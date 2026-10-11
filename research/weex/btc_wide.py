"""BTC-сетка WEEX «шаг 0.6 / цель 1.4 / ордер больше» (вопрос оператора 11.10; конфиг его GinArea-шорта 0.6/1.39).

fast_grid (сверен с движком, выход каждого лота своим тейком), минутки BTC 11.12.2025–10.10.2026, 50 ордеров.
Ячейки вокруг 0.6/1.4 (ворота плоской поверхности) и стороны отдельно; ордер 0.0012 / 0.003 / 0.006 BTC,
потолок на сторону = 50 ордеров × ордер × ~цена. Комиссия мейкера 0.016%. Половины — непрерывно."""
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import fast_grid as fg  # noqa: E402

JOBS = [  # шаг, цель, ордер, стороны
    (0.2, 0.21, 0.0012, ("LONG", "SHORT")),
    (0.6, 1.4, 0.0012, ("LONG", "SHORT")),
    (0.6, 1.4, 0.003, ("LONG", "SHORT")),
    (0.6, 1.4, 0.006, ("LONG", "SHORT")),
    (0.6, 1.4, 0.003, ("SHORT",)),
    (0.6, 1.4, 0.003, ("LONG",)),
    (0.5, 1.2, 0.003, ("LONG", "SHORT")),
    (0.6, 1.0, 0.003, ("LONG", "SHORT")),
    (0.6, 2.0, 0.003, ("LONG", "SHORT")),
    (0.8, 1.4, 0.003, ("LONG", "SHORT")),
    (0.4, 1.4, 0.003, ("LONG", "SHORT")),
]


def one(job):
    step, tgt, qty, sides = job
    data = fg.load("BTCUSDT")
    cut = int(data[0][len(data[0]) // 2])
    r = fg.run(data, sides=sides, step=step, target=tgt, order_qty=qty, cap_usd=50 * qty * 100_000, max_orders=50,
               cut_ts=cut)
    return job, r


def main():
    with ProcessPoolExecutor(max_workers=3) as ex:
        res = list(ex.map(one, JOBS))
    print(f"{'шаг/цель':>9} {'ордер':>6} {'стороны':>8} | {'итог':>7} {'1-я пол':>8} {'2-я пол':>8} | {'закрыто':>8} "
          f"{'мешок':>7} {'худш.мешок':>10} {'просадка':>8} {'тейков':>6} | по сторонам")
    for (s, t, q, sd), r in res:
        print(f"{s:>4}/{t:<4} {q:>6} {'+'.join(x[0] for x in sd):>8} | {r['итог']:>+7.0f} {r['1-я часть непрерывно']:>+8.0f} "
              f"{r['2-я часть непрерывно']:>+8.0f} | {r['закрыто']:>+8.0f} {r['мешок']:>+7.0f} {r['худший мешок']:>+10.0f} "
              f"{r['просадка капитала']:>+8.0f} {r['тейков']:>6} | {r['по сторонам']}")


if __name__ == "__main__":
    main()
