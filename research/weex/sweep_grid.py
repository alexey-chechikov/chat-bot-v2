"""Развёртка шага/цели сетки по минуткам (fast_grid, правило GinArea) с разрезом по времени.
Пример: sweep_grid.py XAUUSDT both 0.05,0.1,0.2 0.1,0.21,0.3 100 4000
        sweep_grid.py BTCUSDT both 0.2 0.21 q0.0012 4000      ← объём фиксирован в монете, как у живой сетки
Стороны: both | long | short. Итог — полный капитал (закрыто − комиссии + мешок на конце), без фандинга.
Вторая половина окна — двумя способами (10.10, замечание GPT):
  «с нуля»     — отдельный прогон, стартующий пустым в середине окна;
  «непрерывно» — изменение капитала ТОГО ЖЕ бота со середины до конца (с унаследованным мешком).
Просадка — от пика капитала до дна по часовым точкам (не «худший мешок»)."""
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fast_grid as fg  # noqa: E402

SYM = sys.argv[1]
SIDES = {"both": ("LONG", "SHORT"), "long": ("LONG",), "short": ("SHORT",)}[sys.argv[2]]
STEPS = [float(x) for x in sys.argv[3].split(",")]
TGTS = [float(x) for x in sys.argv[4].split(",")]
SIZE = sys.argv[5] if len(sys.argv) > 5 else "100"
QTY = float(SIZE[1:]) if SIZE.startswith("q") else None
USD = 100.0 if QTY else float(SIZE)
CAP = float(sys.argv[6]) if len(sys.argv) > 6 else 4000.0
OUT = Path(__file__).with_name(f"sweep_{SYM}_{sys.argv[2]}_{sys.argv[3].replace(',', '-')}_{SIZE}.jsonl")


def one(args):
    step, tgt = args
    full = fg.load(SYM)
    ts = full[0]
    mid = int(ts[len(ts) // 2])
    cut = datetime.fromtimestamp(mid, timezone.utc).strftime("%Y-%m-%d")
    cut_ts = int(datetime.fromisoformat(cut).replace(tzinfo=timezone.utc).timestamp())
    kw = dict(order_usd=USD, cap_usd=CAP, max_orders=10_000, order_qty=QTY)
    r = fg.run(full, SIDES, step, tgt, cut_ts=cut_ts, **kw)
    h1 = fg.run(fg.load(SYM, None, cut), SIDES, step, tgt, **kw)
    h2 = fg.run(fg.load(SYM, cut, None), SIDES, step, tgt, **kw)
    r.update(step=step, target=tgt, cut=cut, h1=round(h1["итог"], 2), h2=round(h2["итог"], 2))
    return r


if __name__ == "__main__":
    grid = [(s, t) for s in STEPS for t in TGTS]
    with ProcessPoolExecutor(max_workers=3) as ex:
        res = list(ex.map(one, grid))
    with OUT.open("w") as f:
        for r in res:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    size = f"{QTY} монеты" if QTY else f"${USD:.0f}"
    print(f"{SYM} {sys.argv[2]} ордер {size} потолок ${CAP:.0f}/сторону (по себестоимости); середина {res[0]['cut']}")
    print(f"{'шаг':>5} {'цель':>5} | {'ИТОГ':>7} {'закрыто':>7} {'мешок':>7} {'просадка':>8} {'оборот':>10} "
          f"{'тейков':>6} | {'1-я с 0':>7} {'2-я с 0':>7} {'2-я непр':>8} | мес+ | по сторонам")
    for r in sorted(res, key=lambda r: (r["step"], r["target"])):
        mplus = sum(1 for _, v in r["по месяцам"] if v > 0)
        print(f"{r['step']:>5} {r['target']:>5} | {r['итог']:>7.0f} {r['закрыто']:>7.0f} {r['мешок']:>7.0f} "
              f"{r['просадка капитала']:>8.0f} {r['оборот']:>10,.0f} {r['тейков']:>6} | {r['h1']:>7.0f} "
              f"{r['h2']:>7.0f} {r.get('2-я часть непрерывно', 0):>8.0f} | {mplus}/{len(r['по месяцам'])} | "
              f"{r['по сторонам']}")
