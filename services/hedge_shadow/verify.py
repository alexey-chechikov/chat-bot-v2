"""Проверка механики закрытия и переоткрытия хеджа. РЕАЛЬНЫЕ ордера.

Последнее непроверенное звено: как именно меняется размер. Гипотеза —
close_position закрывает позицию, а бот, оставаясь Active с maxOp=1,
открывает её заново уже новым размером из set_params.

Живёт в пакете hedge_shadow, потому что close_position разрешён только
своим службам (services/ginarea_api/bots.py, _CLOSE_ALLOWED).
"""
from __future__ import annotations

import dataclasses
import time

HEDG = 5848117800
STATUS = {0: "CREATED", 1: "STARTING", 2: "Active", 3: "Paused",
          10: "FAILED", 11: "STOPPING", 12: "STOPPED", 13: "CLOSING"}


def _show(api, tag):
    b = api.get_bot(HEDG)
    p = api.get_params(HEDG)
    s = b.stat
    pos = float(getattr(s, "position", 0) or 0)
    print(f"{tag:20s} статус={STATUS.get(int(b.status), b.status):9s} "
          f"позиция={pos:9,.0f} размер_настройки={p.q.minQ} "
          f"средняя={getattr(s, 'averagePrice', 0):,.1f}")
    return b, p, pos


def run(api) -> None:
    print("=== ПРОВЕРКА ЗАКРЫТИЯ И ПЕРЕОТКРЫТИЯ ===")
    _show(api, "исходно")

    # 2026-08-31: close_position на РАБОТАЮЩЕМ боте отдаёт
    # «bot[...] is running». Значит порядок обязателен: пауза -> закрытие
    # -> смена размера -> запуск. И maxOp возвращаем в 1: при maxOp=3 бот
    # сам добрал со $100 до $700, потому что LONG-сетка добирает на
    # падении — её логика работает против задачи хеджа.
    print("\n0. возвращаю maxOp=1 и останавливаю бота")
    p0 = api.get_params(HEDG)
    api.set_params(HEDG, dataclasses.replace(p0, maxOp=1))
    from services.short_bots_guard import control
    control.pause_bot(str(HEDG), reason="закрытие хеджа",
                      trigger="hedge_verify")
    for _ in range(6):
        time.sleep(5)
        b = api.get_bot(HEDG)
        if int(b.status) != 2:
            break
    _show(api, "  после паузы")

    print("\n1. закрываю позицию")
    api.close_position(HEDG)
    for k in range(6):
        time.sleep(10)
        _, _, pos = _show(api, f"  +{(k+1)*10}с")
        if pos == 0:
            print("   позиция закрыта")
            break
    else:
        print("   за минуту не закрылась")

    print("\n2. меняю размер на 200 и жду, откроется ли заново")
    p = api.get_params(HEDG)
    api.set_params(HEDG, dataclasses.replace(
        p, q=dataclasses.replace(p.q, minQ=200.0)))
    for k in range(6):
        time.sleep(10)
        _, _, pos = _show(api, f"  +{(k+1)*10}с")
        if pos != 0:
            print(f"   открылась заново размером {pos:,.0f}")
            break
    else:
        print("   сама не открылась — нужен явный resume_bot")
        from services.short_bots_guard import control
        control.resume_bot(str(HEDG), reason="переоткрытие хеджа",
                           trigger="hedge_verify")
        for k in range(6):
            time.sleep(10)
            _, _, pos = _show(api, f"  resume +{(k+1)*10}с")
            if pos != 0:
                print(f"   открылась после resume: {pos:,.0f}")
                break
