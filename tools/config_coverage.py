"""Кто из живых ботов выпал из автоматики, и кто числится мёртвым.

Появился 2026-08-17 после того, как BTC SHORT 5189290547 нашёлся вне
автоматики ЧЕТЫРЕ раза подряд: не был заведён в харвестере, не был заведён
в автотюнере, считался в чужих единицах (мешок в BTC против долларовых
порогов), и не попадал в drift-стадии alt_guard, который по устройству
смотрит только side=3.

Каждый разрыв по отдельности полностью выключал автоматику по этому боту,
и находились они по одному. Проверка сравнивает ЖИВОЙ состав со всеми
рукописными списками разом.

Живой состав берётся из state/portfolio.json (это источник истины для
гарда боевых ботов), опционально сверяется с API по --api.

Запуск:
    .venv/bin/python tools/config_coverage.py
    .venv/bin/python tools/config_coverage.py --api     # сверить с GinArea
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PORTFOLIO = ROOT / "state" / "portfolio.json"
SERVICES = {
    "харвестер": ROOT / "state" / "order_harvester_config.json",
    "автотюнер": ROOT / "state" / "grid_autotune_config.json",
}
# Оркестратор держит свой реестр с ЧЕЛОВЕЧЕСКИМИ алиасами, а не с id
# GinArea, поэтому в общую сверку по id он не попадает. Проверяется
# отдельно: 2026-08-19 оператор прислал его карточку с указанием
# «возобновить работу ботов: btc_short_l1» — бота с таким алиасом в
# GinArea нет, id у записи отсутствует вовсе, параметры не совпадают с
# живым BTC SHORT ни в одном поле, а last_command_at там от 2 мая.
GRID_PORTFOLIO = ROOT / "state" / "grid_portfolio.json"
_ID_KEYS = ("ginarea_bot_id", "bot_id", "id", "ginarea_id")


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def live_bots() -> dict[int, str]:
    """{id: имя} боевых ботов из portfolio.json."""
    pf = _load(PORTFOLIO)
    out: dict[int, str] = {}
    for item in pf.get("bots") or []:
        if isinstance(item, dict) and item.get("active") and item.get("id"):
            out[int(item["id"])] = str(item.get("name") or item["id"])
    return out


def service_bots(path: Path) -> dict[int, dict]:
    cfg = _load(path)
    out: dict[int, dict] = {}
    for k, v in (cfg.get("bots") or {}).items():
        try:
            out[int(k)] = v if isinstance(v, dict) else {}
        except (TypeError, ValueError):
            continue
    return out


def check(use_api: bool = False) -> int:
    """Возвращает число найденных расхождений (0 = всё покрыто)."""
    live = live_bots()
    if not live:
        print("portfolio.json пуст или не читается — проверять нечего")
        return 1

    api_names: dict[int, str] = {}
    if use_api:
        sys.path.insert(0, str(ROOT))
        from services.order_harvester.loop import _cached_api

        api = _cached_api()
        if api is None:
            print("API недоступен — сверка с GinArea пропущена\n")
        else:
            for b in api.list_bots():
                api_names[int(b.id)] = str(b.name)

    print(f"боевых ботов в portfolio.json: {len(live)}")
    for bid, name in sorted(live.items()):
        print(f"   {bid}  {name}")

    problems = 0

    if api_names:
        missing = set(api_names) - set(live) - _inactive_ids()
        if missing:
            problems += len(missing)
            print("\nЕСТЬ В GINAREA, НО НЕ В portfolio.json:")
            for bid in sorted(missing):
                print(f"   {bid}  {api_names[bid]}")
        gone = set(live) - set(api_names)
        if gone:
            problems += len(gone)
            print("\nЧИСЛЯТСЯ БОЕВЫМИ, НО В GINAREA ИХ НЕТ:")
            for bid in sorted(gone):
                print(f"   {bid}  {live[bid]}")

    for label, path in SERVICES.items():
        cfg = service_bots(path)
        missing = set(live) - set(cfg)
        dead = set(cfg) - set(live)
        print(f"\n{label}: заведено {len(cfg)}")
        if missing:
            problems += len(missing)
            print(f"   ВЫПАЛИ ИЗ АВТОМАТИКИ ({len(missing)}):")
            for bid in sorted(missing):
                print(f"      {bid}  {live[bid]}")
        if dead:
            problems += len(dead)
            print(f"   ЧИСЛЯТСЯ, НО НЕ БОЕВЫЕ ({len(dead)}):")
            for bid in sorted(dead):
                print(f"      {bid}")
        if not missing and not dead:
            print("   покрытие полное")

    problems += _check_grid_portfolio(live)

    print(f"\nрасхождений: {problems}")
    return problems


def _check_grid_portfolio(live: dict[int, str]) -> int:
    """Реестр оркестратора: у каждой записи должен быть id живого бота."""
    if not GRID_PORTFOLIO.exists():
        return 0
    gp = _load(GRID_PORTFOLIO)
    bots = gp.get("bots")
    if not isinstance(bots, dict) or not bots:
        return 0

    bad = []
    for alias, rec in bots.items():
        if not isinstance(rec, dict):
            continue
        bid = next((rec[k] for k in _ID_KEYS if rec.get(k) is not None), None)
        try:
            bid = int(bid) if bid is not None else None
        except (TypeError, ValueError):
            bid = None
        if bid is None:
            bad.append((alias, "нет id GinArea"))
        elif bid not in live:
            bad.append((alias, f"id {bid} не боевой"))

    print(f"\nоркестратор (grid_portfolio): записей {len(bots)}")
    if not bad:
        print("   все записи ведут на боевых ботов")
        return 0
    print(f"   КОМАНДЫ УЙДУТ В НИКУДА ({len(bad)}):")
    for alias, why in bad:
        print(f"      {alias}: {why}")
    return len(bad)


def _inactive_ids() -> set[int]:
    """Боты, помеченные в portfolio.json как active:false — это осознанно."""
    pf = _load(PORTFOLIO)
    out = set()
    for item in pf.get("bots") or []:
        if isinstance(item, dict) and not item.get("active") and item.get("id"):
            out.add(int(item["id"]))
    return out


if __name__ == "__main__":
    raise SystemExit(1 if check("--api" in sys.argv) else 0)
