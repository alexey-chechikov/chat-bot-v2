"""Все ли ЖИВЫЕ боты покрыты автоматикой? Запускать после любой смены ботов.

Урок 2026-07-23 (переезд на OKX): харвестер и автотюнер смотрели на 7 мёртвых
BitMEX-ID и не видели ни одного живого бота — молча, без ошибок. Этот скрипт
ловит такое за секунду.

Запуск: .venv/bin/python3 tools/check_bot_coverage.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CONFIGS = {
    "order_harvester": ROOT / "state" / "order_harvester_config.json",
    "grid_autotune": ROOT / "state" / "grid_autotune_config.json",
}
EXCHANGE = {3: "OKX", 4: "BitMEX"}
STATUS = {2: "Working", 3: "Paused", 10: "FAILED", 12: "Stopped", 13: "цикл",
          16: "стоп TP/SL"}


def main() -> int:
    from services.short_bots_guard.control import _build_api
    api, err = _build_api()
    if api is None:
        print("API GinArea недоступен:", err)
        return 1

    bots = {str(b.id): b for b in api.list_bots()}
    active = {bid: b for bid, b in bots.items() if int(b.status) == 2}
    print(f"ЖИВЫХ БОТОВ В GinArea: {len(active)} (всего в аккаунте {len(bots)})\n")
    for bid, b in sorted(active.items(), key=lambda kv: kv[1].name):
        ex = EXCHANGE.get(int(b.exchangeId), f"exch={b.exchangeId}")
        print(f"  {bid:12s} {b.name[:32]:32s} {ex}")

    print()
    problems = []
    for name, path in CONFIGS.items():
        try:
            cfg = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"{name}: конфиг не читается ({e})")
            problems.append(name)
            continue
        ids = set((cfg.get("bots") or {}).keys())
        covered = ids & set(active)
        dead = [i for i in ids if i not in active]
        missing = [i for i in active if i not in ids]
        state = "ВКЛ" if cfg.get("enabled") else "ВЫКЛ"
        print(f"{name} ({state}): покрыто {len(covered)}/{len(active)} живых")
        if dead:
            names = [bots[i].name[:20] if i in bots else "нет в аккаунте" for i in dead]
            print(f"  ⚠️ мёртвые ID в конфиге: {list(zip(dead, names))}")
            problems.append(f"{name}: мёртвые ID")
        if missing:
            print(f"  ❌ ЖИВЫЕ БОТЫ ВНЕ АВТОМАТИКИ:")
            for i in missing:
                b = active[i]
                print(f"       {i}  {b.name[:30]}  ({EXCHANGE.get(int(b.exchangeId), '?')})")
            problems.append(f"{name}: не покрыты {missing}")

    # трендовые сигналы — по профилям активов
    prof_path = ROOT / "state" / "asset_profiles.json"
    try:
        prof = json.loads(prof_path.read_text(encoding="utf-8"))
        ok = [s for s, p in (prof.get("assets") or {}).items() if p.get("trend_bot_ok")]
        allp = list((prof.get("assets") or {}).keys())
        print(f"\ntrend_signals: профилей {len(allp)} {allp}")
        print(f"  с подтверждённым эджем (сигналят): {ok}")
    except Exception as e:
        print(f"\ntrend_signals: профили не читаются ({e})")

    print()
    if problems:
        print("ИТОГ: ЕСТЬ ПРОБЛЕМЫ →", "; ".join(problems))
        return 2
    print("ИТОГ: все живые боты покрыты автоматикой ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
