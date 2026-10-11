"""«Поднять интенсивность» BTC-сетки WEEX (вопрос оператора 11.10): мельче шаг / больше ордер против текущей 0.2/0.21.

fast_grid (сверен с движком), минутки BTC 11.12.2025–10.10.2026, обе стороны, 50 ордеров, потолок $4 000 на
сторону (у 2× ордера — $8 000). Комиссия: мейкер 0.016% (после бонуса) и 0 (пока бонус возвращает 100%).
Итог — полный капитал (закрыто − комиссии + мешок); половины — непрерывно, граница по середине окна."""
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import fast_grid as fg  # noqa: E402

CONFIGS = [  # шаг, цель, ордер BTC, потолок $
    (0.2, 0.21, 0.0012, 4000), (0.15, 0.15, 0.0012, 4000), (0.1, 0.15, 0.0012, 4000), (0.1, 0.1, 0.0012, 4000),
    (0.2, 0.21, 0.0024, 8000),
]


def one(args):
    step, tgt, qty, cap, fee = args
    data = fg.load("BTCUSDT")
    cut = int(data[0][len(data[0]) // 2])
    r = fg.run(data, step=step, target=tgt, order_qty=qty, cap_usd=cap, max_orders=50, fee=fee, cut_ts=cut)
    return args, r


def main():
    jobs = [(s, t, q, c, f) for s, t, q, c in CONFIGS for f in (fg.MAKER, 0.0)]
    with ProcessPoolExecutor(max_workers=3) as ex:
        res = list(ex.map(one, jobs))
    print(f"{'шаг/цель':>9} {'ордер':>7} {'комис':>6} | {'итог':>7} {'1-я пол':>8} {'2-я пол':>8} | {'закрыто':>8} "
          f"{'комиссии':>8} {'мешок':>7} {'худш.мешок':>10} {'просадка':>8} {'тейков':>6} {'оборот':>9}")
    for (s, t, q, c, f), r in res:
        print(f"{s:>4}/{t:<4} {q:>7} {f * 100:>5.3f}% | {r['итог']:>+7.0f} {r['1-я часть непрерывно']:>+8.0f} "
              f"{r['2-я часть непрерывно']:>+8.0f} | {r['закрыто']:>+8.0f} {r['комиссии']:>8.0f} {r['мешок']:>+7.0f} "
              f"{r['худший мешок']:>+10.0f} {r['просадка капитала']:>+8.0f} {r['тейков']:>6} {r['оборот']:>9,.0f}")


if __name__ == "__main__":
    main()
