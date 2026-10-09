"""Сетка «на объём» для WEEX: маленькие шаг и цель при комиссиях с кэшбэком 77.6%.

Заранее: BTC и ETH, лонг-книга + шорт-книга (как Auto без выхода по средней), шаг
0.1/0.2/0.3%, цель 0.2/0.3/0.5%, ордер $50, до 200 ордеров на сторону, депозит $3 300.
Комиссии на исполнение: лимитки с кэшбэком 0.0036%, маркет с кэшбэком 0.0108%,
лимитки без кэшбэка 0.016% (если кэшбэк не придёт). Политики: без ограничений и
стресс-бюджет P2. Окна: train / validation / test (по трети, каждое с нуля) и всё.
Полный счёт: закрытое + открытая позиция + реальный фандинг + ликвидация.
"""
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "grid_risk"))
import grid_sim as gs  # noqa: E402

FEES = {"лимит+кэшбэк": 0.000036, "маркет+кэшбэк": 0.000108, "лимит без кэшбэка": 0.00016}
STEPS, TARGETS = (0.1, 0.2, 0.3), (0.2, 0.3, 0.5)
WINDOWS = ("train", "validation", "test", "full")
_M = {}


def task(args):
    sym, step, target = args
    if sym not in _M:
        _M[sym] = gs.load_market(sym)
    m = _M[sym]
    rows = []
    for w in WINDOWS:
        a, b = gs.window_idx(m, *gs.CFG["windows"][w])
        for fname, fee in FEES.items():
            for pname, pol in (("P0", gs.Policy()), ("P2", gs.Policy(budget="vol"))):
                for side in (1, -1):
                    r = gs.run(m, a, b, side, step, target, pol, order_usd=50, max_orders=200,
                               deposit=3300, fee=fee)
                    rows.append({"sym": sym, "step": step, "target": target, "window": w, "fee": fname,
                                 "policy": pname, "side": side, "net": r["net"], "max_dd": r["max_dd"],
                                 "bust": r["bust"], "turnover": r["turnover"], "fees": r["fees"],
                                 "funding": r["funding"], "entries": r["entries"],
                                 "days": (m.t[b - 1] - m.t[a]) / 86400e9})
    return rows


def main():
    jobs = [(s, st, tg) for s in ("BTCUSDT", "ETHUSDT") for st in STEPS for tg in TARGETS]
    out = HERE / "volume_grid_runs.jsonl"
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=6) as ex, out.open("w") as f:
        for i, rows in enumerate(ex.map(task, jobs)):
            for r in rows:
                f.write(json.dumps(r, default=float) + "\n")
            print(f"{i + 1}/{len(jobs)} {time.time() - t0:.0f}с", flush=True)


if __name__ == "__main__":
    main()
