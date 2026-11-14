"""Сверка моей механики сетки (grid_sim.py) с движком GinArea — 14.11.2026, оператор: «досчитай с эфиром и сверь
с гинареей».

На движке GinArea гоняется лонг-сетка, максимально близкая к WEEX: шаг gs, цель tog, выход по каждому ордеру
(obap=0), 50 ордеров, объём 0.001 BTC, без множителя объёма, Инстоп 0, мин./макс. стоп 0. Клон — стратегия DYNAMIC:
so (отступ границы от цены, граница тянется за ценой вверх) = gs — первый вход на шаг ниже максимума, как у WEEX;
ioo (сдвиг границы после входа) = 0.01 — минимум (0 GinArea не принимает: «invalid InOpenOffset: 0»).
Те же правила — в ga_compare.py на минутках Binance.
Окна: каждый месяц 10.2025–10.2026 (старт пустой), 01–13.11.2026 и год 13.11.2025–13.11.2026 непрерывно (окно длиннее
367 дней GinArea не принимает: «exceeded the range of 367 days»).
Сетки: 0.6/1.4 (основная), 0.1/0.34 и 0.1/0.89 (B34, B89).

Бот — BTC шорт-клон 4568400511 (разрешён оператором к тестам 01.10; tools/ginarea_regime_check.py работает на нём же).
Параметры бота возвращаются в конце (finally). Логин — один на процесс; новых путей API нет: всё через
tools/ginarea_target_sweep (set_config, clear_slot с архивом удаляемого теста) и BacktestAPI.run_test.
Пишет research/grid_hedge_20261114/ga_validate.jsonl — сырой stat теста целиком; уже посчитанное пропускает.

    .venv/bin/python3 research/grid_hedge_20261114/ga_validate.py
"""
from __future__ import annotations

import dataclasses
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import ginarea_target_sweep as gts  # noqa: E402

BOT = 4568400511
OUT = Path(__file__).with_name("ga_validate.jsonl")
GRIDS = ((0.6, 1.4), (0.1, 0.34), (0.1, 0.89))
SPEC = "side=1,s=1,maxOp=50,q.minQ=0.001,q.maxQ=null,q.qr=null,obap=0,ioo=0.01,gap.minS=0,gap.maxS=0"
CHECK = ("side", "gs", "gap.tog", "maxOp", "q.minQ", "q.maxQ", "q.qr", "obap", "so", "ioo", "gap.minS", "gap.maxS", "gap.isg")
END = datetime(2026, 11, 13, 21, 0, tzinfo=timezone.utc)


def windows():
    out = []
    for ym in ("2025-10", "2025-11", "2025-12", "2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06",
               "2026-07", "2026-08", "2026-09", "2026-10"):
        out.append(("месяц " + ym, *gts.month_window(ym)))
    out.append(("месяц 2026-11 (до 13.11 21:00)", datetime(2026, 11, 1, tzinfo=timezone.utc), END))
    out.append(("год непрерывно", datetime(2025, 11, 13, 21, 0, tzinfo=timezone.utc), END))   # GinArea: ≤367 дней
    return out


def _pick(cfg, key):
    outer, _, inner = key.partition(".")
    v = cfg.get(outer)
    return (v or {}).get(inner) if inner else v


def _same(a, b):
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, bool) or isinstance(b, bool):
        return bool(a) == bool(b)
    try:
        return abs(float(a) - float(b)) <= 1e-9
    except (TypeError, ValueError):
        return a == b


def main():
    done = set()
    if OUT.exists():
        for ln in OUT.read_text(encoding="utf-8").splitlines():
            r = json.loads(ln)
            done.add((r["gs"], r["tog"], r["from"], r["to"]))
    api, bt = gts._api([BOT])
    base = gts._base(api, BOT)
    try:
        for gs, tog in GRIDS:
            work = gts.apply_set(base, f"{SPEC},so={gs}")    # первый вход на шаг ниже максимума — как у WEEX
            want =dataclasses.replace(work, gs=gs, gap=dataclasses.replace(work.gap, tog=tog)).to_dict()
            for label, a, b in windows():
                key = (gs, tog, a.isoformat(), b.isoformat())
                if key in done:
                    continue
                gts.set_config(api, BOT, work, gs, tog)
                got = api.get_params(BOT).to_dict()
                diff = [f"{k}: {_pick(want, k)!r} → {_pick(got, k)!r}" for k in CHECK
                        if not _same(_pick(want, k), _pick(got, k))]
                if diff:
                    raise SystemExit(f"параметры не встали: {'; '.join(diff)}")
                gts.clear_slot(bt, BOT)
                t0 = time.time()
                test = bt.run_test(BOT, a, b, poll_interval=15.0, timeout=3600.0)
                s = test.stat
                rec = {"gs": gs, "tog": tog, "label": label, "from": a.isoformat(), "to": b.isoformat(),
                       "test_id": test.id, "status": test.status.name, "seconds": round(time.time() - t0),
                       "params": got, "stat": s.to_dict() if s else None,
                       "hist": [h.to_dict() for h in (test.statHistory or [])]}
                with OUT.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
                print(f"{gs}/{tog} {label}: закрыто {s.profit:+.2f} итог {s.currentProfit:+.2f} входов "
                      f"{s.inFilledCount} тейков {s.outFilledCount} оборот {s.tradeVolume:,.0f} позиция {s.position} "
                      f"({rec['seconds']} с)", flush=True)
                time.sleep(gts.PAUSE)
    finally:
        api.set_params(BOT, base)
        print("параметры бота возвращены", flush=True)


if __name__ == "__main__":
    main()
