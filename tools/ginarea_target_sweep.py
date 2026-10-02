"""Развёртки грид-ботов по месячным окнам на движке GinArea (через API).

Начато 01.10.2026 с вопроса «должна ли цель ETH Auto зависеть от
волатильности». Свой симулятор не повторил развёртку оператора (ошибка
135…2400%), поэтому считает сам GinArea на ТЕСТОВЫХ ботах.

GinArea держит ОДИН тест на бота («limit on the number of tests for the
bot»), поэтому цикл: архив и удаление старого теста → прогон → запись.
Удалять можно только на ботах из ALLOWED_DELETE (разрешение оператора).

Безопасность:
- исходные параметры каждого бота сохраняются в
  state/ginarea_sweep_backup_<id>.json и возвращаются в конце;
- боевые боты защищены гардом (state/portfolio.json) — их ID скрипт не примет;
- один процесс = один бот = один логин; пауза между запросами; при 403 — стоп;
- результат каждого теста пишется сразу — прогон можно продолжить.

    tools/ginarea_target_sweep.py 5678633257 --targets=1.0,2.0            # ETH, как было
    tools/ginarea_target_sweep.py 5330789037 --name=btc_auto \\
        --set=side=3,gs=0.1,maxOp=800,q.minQ=0.001,obap=1,so=0.75,ioo=0.1 \\
        --grid=0.1:0.3,0.1:0.5                                          # пары шаг:цель
    tools/ginarea_target_sweep.py 5330789037 --restore
"""
from __future__ import annotations

import dataclasses
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TARGETS = (1.0, 1.3, 1.69, 2.0, 2.5, 3.0)
OUT = ROOT / "state" / "ginarea_eth_target_sweep.jsonl"     # серия «eth» (по умолчанию)
PAUSE = 3.0
# Развёртка ETH 01.10.2026. История тестов GinArea начинается 25.09.2025
# (tests/range) — поэтому все развёртки оператора с этой даты.
# Тихие и бурные — пара для заранее названного решения; ход за месяц в обеих
# группах одного порядка (±5…13%), чтобы тренд не смешался с волатильностью.
QUIET = ("2026-04", "2026-09", "2026-05")      # 2.54 / 2.28 / 1.93 %/день
STORMY = ("2026-03", "2025-10", "2026-02")     # 3.26 / 3.58 / 4.42 %/день
OTHER = ("2025-11", "2025-12", "2026-01", "2026-06", "2026-07", "2026-08")
MONTHS = QUIET + STORMY + OTHER
LIMIT_MSG = "limit on the number of tests"
# Разрешения оператора 01.10.2026: «удаляй тесты на клонах» (ETH _c_c, _c_c_c,
# включая его годовые прогоны — итоги сохранены) и «по BTC остановленные
# динамик-боты и динамик шорт-боты можешь использовать». Каждый тест перед
# удалением пишется в ARCHIVE.
ALLOWED_DELETE = frozenset({5678633257, 6227907209,              # ETH Auto клоны
                            5330789037, 4696727145,              # BTC остановленные
                            4568400511, 5516390489})             # BTC шорт-клоны
ARCHIVE = ROOT / "state" / "ginarea_deleted_tests.jsonl"


def out_path(name: str) -> Path:
    return OUT if name == "eth" else ROOT / "state" / f"ginarea_sweep_{name}.jsonl"


def month_window(ym: str, shift_days: int = 0) -> tuple[datetime, datetime]:
    """Календарный месяц; shift_days сдвигает окно (проверка на удачу пути)."""
    from datetime import timedelta

    y, m = (int(x) for x in ym.split("-"))
    a = datetime(y, m, 1, tzinfo=timezone.utc)
    y2, m2 = (y + 1, 1) if m == 12 else (y, m + 1)
    b = datetime(y2, m2, 1, tzinfo=timezone.utc)
    return a + timedelta(days=shift_days), b + timedelta(days=shift_days)


def _done(path: Path, default_gs: float | None) -> set[tuple]:
    if not path.exists():
        return set()
    out = set()
    for ln in path.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        if r.get("current_profit") is None:
            continue
        gs = r.get("gs", default_gs)
        out.add((float(gs) if gs is not None else None, float(r["target"]), r["from"]))
    return out


def _api(bots: list[int]):
    from services.ginarea_api.backtest import BacktestAPI
    from services.ginarea_api.bots import _load_production_bot_ids
    from services.order_harvester.loop import _cached_api

    api = _cached_api()
    if api is None:
        raise SystemExit("GinArea API недоступен")
    prod = _load_production_bot_ids()
    for bot in bots:
        if bot in prod:
            raise SystemExit(f"{bot} в боевом списке — стоп")
    return api, BacktestAPI(api.client)


def _num(v: str):
    if v.lower() in ("true", "false"):
        return v.lower() == "true"
    if v.lower() in ("null", "none"):
        # 01.10: перевод шорта в Auto — GinArea «not allowed to pass `s` and
        # `side` together»: у Auto (side=3) поле s пустое, как у ETH Auto
        return None
    try:
        f = float(v)
        return int(f) if f.is_integer() and "." not in v else f
    except ValueError:
        return v


def apply_set(base, spec: str):
    """--set=side=3,gs=0.1,q.minQ=0.001,so=0.75 → новые параметры (поверх base)."""
    from services.ginarea_api.models import DefaultGridParams, Side

    d = base.to_dict()
    for item in filter(None, spec.split(",")):
        key, val = item.split("=", 1)
        v = _num(val)
        if key == "obap":
            v = bool(int(val)) if val.isdigit() else bool(v)
        if "." in key:
            outer, inner = key.split(".", 1)
            d.setdefault(outer, {})
            d[outer] = dict(d[outer] or {})
            d[outer][inner] = v
        else:
            d[key] = v
    p = DefaultGridParams.from_dict(d)
    if p.side is not None and not isinstance(p.side, Side):
        p = dataclasses.replace(p, side=Side(int(p.side)))
    return p


def start_price(sym: str, a: datetime) -> float:
    """Цена закрытия дня перед окном — от неё ставится граница окна."""
    from services.grid_model import odds_z as oz

    d = oz.load_daily(sym, refresh=False)
    return float(d["close"][:a].iloc[-2] if d.index[-1] >= a else d["close"].iloc[-1])


def set_config(api, bot: int, work, gs: float, target: float,
               border: tuple[float, float] | None = None):
    p = dataclasses.replace(work, gs=gs, gap=dataclasses.replace(work.gap, tog=target))
    if border is not None:
        p = dataclasses.replace(p, border=dataclasses.replace(
            p.border, bottom=round(border[0], 2), top=round(border[1], 2)))
    api.set_params(bot, p)
    time.sleep(PAUSE)
    got = api.get_params(bot)
    if abs(float(got.gap.tog) - target) > 1e-9 or abs(float(got.gs) - gs) > 1e-9:
        raise SystemExit(f"настройки не встали на {bot}: шаг {got.gs} цель {got.gap.tog}")


def clear_slot(bt, bot: int) -> int:
    """Освободить слот теста: заархивировать и удалить тесты бота."""
    if bot not in ALLOWED_DELETE:
        return 0
    n = 0
    for t in bt.list_tests(bot):
        s = t.stat
        rec = {"bot": bot, "test_id": t.id, "from": str(t.dateFrom), "to": str(t.dateTo),
               "status": t.status.name, "tog": t.params.gap.tog, "gs": t.params.gs,
               "maxOp": t.params.maxOp,
               "profit": s.profit if s else None,
               "current_profit": s.currentProfit if s else None,
               "volume": s.tradeVolume if s else None,
               "position": s.position if s else None,
               "deleted_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        with ARCHIVE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        time.sleep(PAUSE)
        try:
            bt.delete_test(bot, t.id)
        except Exception:                                   # noqa: BLE001
            time.sleep(30)                 # тест мог ещё считаться — ждём и повторяем
            bt.delete_test(bot, t.id)
        n += 1
        time.sleep(PAUSE)
    return n


def run_one(bt, bot: int, gs: float, target: float, a: datetime, b: datetime,
            path: Path) -> dict:
    t0 = time.time()
    test = bt.run_test(bot, a, b, poll_interval=20.0, timeout=3600.0)
    s = test.stat
    hist = test.statHistory or []
    # риск внутри окна: худший мешок (нереализованное) и максимальная позиция
    worst_bag = min((h.currentProfit - h.profit for h in hist), default=None)
    worst_total = min((h.currentProfit for h in hist), default=None)
    max_pos = max((abs(h.position) for h in hist), default=None)
    rec = {"gs": gs, "target": target, "from": a.date().isoformat(),
           "worst_bag": worst_bag, "worst_total": worst_total, "max_pos": max_pos,
           "hist_points": len(hist),
           "to": b.date().isoformat(), "bot": bot, "test_id": test.id,
           "status": test.status.name, "tog_in_test": test.params.gap.tog,
           "gs_in_test": test.params.gs, "side": int(test.params.side or 0),
           "profit": s.profit if s else None,
           "current_profit": s.currentProfit if s else None,
           "volume": s.tradeVolume if s else None,
           "position": s.position if s else None,
           "seconds": round(time.time() - t0)}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def _backup(bot: int) -> Path:
    return ROOT / "state" / f"ginarea_sweep_backup_{bot}.json"


def _base(api, bot: int):
    """Исходные параметры бота: снимаем один раз и храним на диске."""
    from services.ginarea_api.models import DefaultGridParams

    f = _backup(bot)
    if f.exists():
        return DefaultGridParams.from_dict(json.loads(f.read_text(encoding="utf-8")))
    base = api.get_params(bot)
    f.write_text(json.dumps(base.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
    return base


def _arg(name: str, default: str = "") -> str:
    return next((a.split("=", 1)[1] for a in sys.argv if a.startswith(f"--{name}=")), default)


def main() -> None:
    bots = [int(x) for x in sys.argv[1:] if x.isdigit()]
    if not bots:
        raise SystemExit("укажи ID ботов")
    api, bt = _api(bots)
    if "--restore" in sys.argv:
        for bot in bots:
            if _backup(bot).exists():
                api.set_params(bot, _base(api, bot))
                print(f"{bot}: параметры возвращены")
        return
    name = _arg("name", "eth")
    path = out_path(name)
    bases = {bot: _base(api, bot) for bot in bots}
    spec = _arg("set")
    works = {bot: (apply_set(b, spec) if spec else b) for bot, b in bases.items()}
    for bot, w in works.items():
        print(f"бот {bot} [{name}]: side {w.side} шаг {w.gs} ордеров {w.maxOp} q {w.q.minQ} "
              f"выход по средней {w.obap} so {w.extra_raw.get('so')} "
              f"ioo {w.extra_raw.get('ioo')} граница {w.border}", flush=True)
    grid_s = _arg("grid")
    if grid_s:
        grid = [tuple(float(x) for x in pair.split(":")) for pair in grid_s.split(",")]
    else:
        tg = _arg("targets")
        targets = [float(x) for x in tg.split(",")] if tg else list(TARGETS)
        grid = [(float(works[bots[0]].gs), t) for t in targets]
    months = _arg("months").split(",") if _arg("months") else list(MONTHS)
    shift = int(_arg("shift-days", "0"))
    if shift:                       # последний месяц со сдвигом уйдёт за конец истории
        months = [m for m in months if month_window(m, shift)[1]
                  <= datetime.now(timezone.utc)]
    done = _done(path, 0.1 if name == "eth" else None)
    tasks = [(gs, tgt, ym) for gs, tgt in grid for ym in months
             if (gs, tgt, month_window(ym, shift)[0].date().isoformat()) not in done]
    print(f"осталось тестов: {len(tasks)}", flush=True)
    # --border-pct=10 --sym=ETHUSDT: граница ±10% от цены начала каждого окна
    border_pct = float(_arg("border-pct", "0")) / 100
    sym = _arg("sym", "ETHUSDT")
    ci, on_cfg, touched = 0, {}, set()
    try:
        for gs, tgt, ym in tasks:
            a, b = month_window(ym, shift)
            border = None
            if border_pct:
                p0 = start_price(sym, a)
                border = (p0 * (1 - border_pct), p0 * (1 + border_pct))
            while ci < len(bots):
                bot = bots[ci]
                if on_cfg.get(bot) != (gs, tgt, border):
                    set_config(api, bot, works[bot], gs, tgt, border)
                    on_cfg[bot] = (gs, tgt, border)
                    touched.add(bot)
                cleared = clear_slot(bt, bot)
                if cleared:
                    print(f"бот {bot}: удалено тестов {cleared} (итоги в архиве)", flush=True)
                try:
                    r = run_one(bt, bot, gs, tgt, a, b, path)
                except Exception as exc:                    # noqa: BLE001
                    msg = str(exc)
                    if LIMIT_MSG in msg:
                        print(f"бот {bot}: лимит тестов — дальше следующий", flush=True)
                        ci += 1
                        continue
                    print(f"шаг {gs} цель {tgt} {ym}: ОШИБКА {msg[:200]}", flush=True)
                    if "403" in msg:
                        raise SystemExit("403 — стоп, ждём тихо (урок WAF)")
                    break
                print(f"шаг {gs} цель {tgt} {ym} (бот {bot}): итог {r['current_profit']} "
                      f"реализ {r['profit']} оборот {r['volume']} ({r['seconds']}с)",
                      flush=True)
                time.sleep(PAUSE)
                break
            else:
                print("боты кончились", flush=True)
                return
    finally:
        for bot in touched:
            try:
                api.set_params(bot, bases[bot])
                print(f"{bot}: параметры возвращены", flush=True)
            except Exception as exc:                        # noqa: BLE001
                print(f"{bot}: НЕ УДАЛОСЬ вернуть параметры: {exc}", flush=True)


if __name__ == "__main__":
    main()
