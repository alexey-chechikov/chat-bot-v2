"""Сетка по режиму SMA100 на движке GinArea (11.10, оператор: «бэктесты для чего? у тебя джинерия»).

Правило из research/weex/regime_grid.py: режим дня = вчерашнее закрытие BTC выше/ниже SMA100 → лонг-сетка / шорт-
сетка; на смене режима сторона закрывается (тест GinArea на отрезке кончается открытой позицией — итог
current_profit включает мешок по цене конца отрезка, т.е. закрытие без комиссии выхода).
Каждый отрезок режима с 25.09.2025 (начало истории тестов GinArea) гоняется ДВАЖДЫ: по режиму и наоборот
(та же сетка, противоположная сторона) — разница = польза направления на независимом движке.
Сетка: шаг 0.6, цель 1.4, 50 ордеров, 0.001 BTC, выход по каждому ордеру (obap выкл), без множителя объёма.
Бот — шорт-клон 4568400511 (разрешён к тестам 01.10); параметры возвращаются в конце.

    .venv/bin/python3 tools/ginarea_regime_check.py            # прогон 0.6/1.4
    .venv/bin/python3 tools/ginarea_regime_check.py --gs=0.4 --tog=1.4 --spec="gs=0.4,maxOp=50,..." --out=state/x.jsonl
    .venv/bin/python3 tools/ginarea_regime_check.py --restore  # вернуть параметры бота

Пропуск уже посчитанного — по ключу (from, to, side, gs, target) (ревью скилов 12.10: был (from, side) — смена шага
молча брала старые результаты, текущий отрезок не продлевался). SPEC (maxOp, объём) в записи нет — при его смене
нужен новый --out.
"""
from __future__ import annotations

import dataclasses
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import ginarea_target_sweep as gts  # noqa: E402

def _opt(name: str, default: str) -> str:
    return next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith(f"--{name}=")), default)


BOT = 4568400511                                          # BTC-клон: отрезки и бот — только BTC (ETH — target_sweep)
OUT = ROOT / _opt("out", "state/ginarea_regime_check.jsonl")
GS, TOG = float(_opt("gs", "0.6")), float(_opt("tog", "1.4"))
SPEC = _opt("spec", f"gs={GS},maxOp=50,q.minQ=0.001,q.maxQ=null,q.qr=null,obap=0")
if not SPEC.strip():                                      # пустой --spec = базовые параметры клона (maxOp 400, qr…)
    sys.exit("--spec пустой — не передавать или задать полностью")


def segments():
    import pandas as pd
    d = pd.read_csv(ROOT / "backtests" / "frozen" / "BTCUSDT_1m_2y.csv", usecols=["ts", "close"])
    s = pd.Series(d["close"].to_numpy(), index=pd.to_datetime(d["ts"], unit="ms", utc=True))
    dc = s.resample("1D").last().dropna()
    sma = dc.rolling(100).mean()
    reg = (dc > sma).where(sma.notna()).shift(1).dropna()
    reg = reg[reg.index >= "2025-09-25"]
    grp = reg.ne(reg.shift()).cumsum()
    now = datetime.now(timezone.utc) - timedelta(minutes=30)
    out = []
    for _, g in reg.groupby(grp):
        a = g.index[0].to_pydatetime()
        b = min((g.index[-1] + pd.Timedelta("1D")).to_pydatetime(), now)
        out.append((bool(g.iloc[0]), a, b))
    return out


def main() -> None:
    api, bt = gts._api([BOT])
    base = gts._base(api, BOT)
    if "--restore" in sys.argv:
        api.set_params(BOT, base)
        print("параметры возвращены")
        return
    done = set()
    if OUT.exists():
        for ln in OUT.read_text(encoding="utf-8").splitlines():
            r = json.loads(ln)
            if r.get("current_profit") is not None:
                done.add((r["from"], r["to"], r["side"], float(r["gs"]), float(r["target"])))
    work = gts.apply_set(base, SPEC)
    try:
        for long_regime, a, b in segments():
            for mode in ("режим", "наоборот"):
                side = 1 if (long_regime == (mode == "режим")) else 2
                if (a.date().isoformat(), b.date().isoformat(), side, GS, TOG) in done:
                    continue
                from services.ginarea_api.models import DefaultGridParams, Side
                d = work.to_dict()
                d["side"] = side
                d["s"] = side                                  # у односторонних ботов s = сторона
                p = DefaultGridParams.from_dict(d)
                if p.side is not None and not isinstance(p.side, Side):
                    p = dataclasses.replace(p, side=Side(int(p.side)))
                gts.set_config(api, BOT, p, GS, TOG)
                got = api.get_params(BOT)
                if int(got.side or 0) != side:
                    raise SystemExit(f"сторона не встала: {got.side} вместо {side}")
                gts.clear_slot(bt, BOT)
                r = gts.run_one(bt, BOT, GS, TOG, a, b, OUT)
                print(f"{'ЛОНГ' if long_regime else 'ШОРТ'}-режим {a.date()}→{b.date()} [{mode}, сторона "
                      f"{'лонг' if side == 1 else 'шорт'}]: итог {r['current_profit']} закрыто {r['profit']} "
                      f"оборот {r['volume']} худший итог {r['worst_total']} ({r['seconds']}с)", flush=True)
                time.sleep(gts.PAUSE)
    finally:
        api.set_params(BOT, base)
        print("параметры бота возвращены", flush=True)


if __name__ == "__main__":
    main()
