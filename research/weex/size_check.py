"""Размер живых лонг-сеток по режиму SMA100 (12.10, оператор: «BTC — шаг 0.4, сайз $200, максимум $8 000; эфир тоже»).
Режим «только лонг выше SMA100, иначе всё закрыть» (как живые сетки), минутки frozen, research/weex/regime_grid.py.
Запуск: size_check.py BTCUSDT | ETHUSDT                         — ячейки CELLS ниже
        size_check.py BTCUSDT 0.6 1.4 0.0036 12000 [0.4 1.4 0.0024 8000 …]  — свои ячейки: шаг% цель% qty_монета потолок$
(ревью скилов 12.10: размеры были зашиты в код, живой BTC 0.0036/$12k не посчитан)."""
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import regime_grid as rg  # noqa: E402

CELLS = {
    "BTCUSDT": [("живое 0.6/1.4 0.0036 до $12k", 0.6, 1.4, 0.0036, 12000),
                ("0.6/1.4 0.0012 до $4k", 0.6, 1.4, 0.0012, 4000), ("0.4/1.4 0.0012 до $4k", 0.4, 1.4, 0.0012, 4000),
                ("0.6/1.4 0.0024 до $8k", 0.6, 1.4, 0.0024, 8000), ("0.4/1.4 0.0024 до $8k", 0.4, 1.4, 0.0024, 8000)],
    "ETHUSDT": [("живое 0.6/1.4 0.020 до $2.5k", 0.6, 1.4, 0.02, 2500), ("0.6/1.4 0.08 до $8k", 0.6, 1.4, 0.08, 8000),
                ("0.4/1.4 0.08 до $8k", 0.4, 1.4, 0.08, 8000)],
}


def cells_from_argv(argv):
    nums = [a for a in argv if a.replace(".", "", 1).isdigit()]
    if not nums:
        if rg.SYM not in CELLS:
            sys.exit(f"{rg.SYM}: ячеек по умолчанию нет — задай четвёрки шаг% цель% qty потолок$")
        return CELLS[rg.SYM]
    if len(nums) % 4:
        sys.exit("ячейка = 4 числа: шаг% цель% qty_в_монете потолок$")
    out = []
    for i in range(0, len(nums), 4):
        st, tg, q, cap = (float(x) for x in nums[i:i + 4])
        out.append((f"{st}/{tg} {q:g} до ${cap:,.0f}", st, tg, q, cap))
    return out


def main():
    data = rg.load()
    jobs = [(name, "longflat", 0, st, tg, q, cap) for name, st, tg, q, cap in cells_from_argv(sys.argv[1:])]
    with ProcessPoolExecutor(max_workers=4, initializer=rg.init, initargs=(data,)) as ex:
        res = list(ex.map(rg.run, jobs))
    print(f"{rg.SYM}: только лонг по SMA100, {rg.SRC.name}; срез половин {rg.cut_label(data[0])}")
    print(f"{'настройка':>30} | {'итог':>7} {'1-я пол':>8} {'2-я пол':>8} | {'худшая просадка':>15}")
    for name, mode, seed, step, tgt, eq, mid, dd, flips, side in res:
        print(f"{name:>30} | {eq:>+7.0f} {mid:>+8.0f} {eq - mid:>+8.0f} | {dd:>+15.0f}")


if __name__ == "__main__":
    main()
