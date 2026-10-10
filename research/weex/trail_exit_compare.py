"""Выход как у GinArea (общий тянущийся стоп-профит по взведённым лотам, закрытие рыночным) против
нашей лимитки на цели. Живой конфиг BTC: шаг 0.2, цель 0.21, 0.0012 BTC, потолок $4 000, 50 ордеров.
Параметры стопа — как у BTC-бота GinArea 5330789037 (мин. стоп 0.006%, макс. стоп 0.02%) и шире.
Комиссия рыночного выхода: 0.048% (замер WEEX 09.10) и 0.01% (тейкер после возврата, по словам оператора)."""
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fast_grid as fg  # noqa: E402

SYM = sys.argv[1] if len(sys.argv) > 1 else "BTCUSDT"
QTY = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0012
STEP = float(sys.argv[3]) if len(sys.argv) > 3 else 0.2
TGT = float(sys.argv[4]) if len(sys.argv) > 4 else 0.21
VARIANTS = [("лимитка на цели (сейчас)", dict(exit_mode="limit"))]
for mn, mx in ((0.006, 0.02), (0.01, 0.05), (0.01, 0.1), (0.02, 0.2)):
    for xf in (0.00048, 0.0001):
        VARIANTS.append((f"GinArea стоп {mn}/{mx}%, рыночный {xf * 100:.3f}%",
                         dict(exit_mode="trail", min_stop=mn, max_stop=mx, exit_fee=xf)))


def one(v):
    name, kw = v
    r = fg.run(fg.load(SYM), ("LONG", "SHORT"), STEP, TGT, order_qty=QTY, cap_usd=4000.0, max_orders=50, **kw)
    return name, r


if __name__ == "__main__":
    with ProcessPoolExecutor(max_workers=3) as ex:
        res = list(ex.map(one, VARIANTS))
    print(f"{SYM} шаг {STEP} цель {TGT} ордер {QTY}, 10 мес, лонг+шорт, комиссия входа 0.016%")
    print(f"{'вариант':<44} | {'ИТОГ':>7} {'закрыто':>8} {'на лот':>7} {'мешок':>7} {'просадка':>8} {'лотов закр':>10} {'оборот':>10}")
    for name, r in res:
        per = r.get("на лот") or (r["закрыто"] / r["тейков"] if r["тейков"] else 0)
        print(f"{name:<44} | {r['итог']:>7.0f} {r['закрыто']:>8.0f} {per:>7.3f} {r['мешок']:>7.0f} "
              f"{r['просадка капитала']:>8.0f} {r['тейков']:>10} {r['оборот']:>10,.0f}")
