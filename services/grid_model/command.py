"""Команда /grid — калькулятор конфигурации на замеренных коэффициентах.

    /grid                       живые боты через модель
    /grid ETH 0.8 1.49 0.04     что даст конфигурация (размер в монете)
    /grid fit ETH 0.8 1.49      подобрать размер ордера под депозит
"""
from __future__ import annotations

import logging

from services.grid_model import model as gm

logger = logging.getLogger(__name__)

HELP = (
    "📐 /grid — калькулятор грид-конфигурации\n\n"
    "/grid — живые боты через модель\n"
    "/grid ETH 0.8 1.49 0.04 — прогноз для конфигурации\n"
    "/grid fit ETH 0.8 1.49 — подобрать размер под депозит\n\n"
    f"есть замеренные коэффициенты: {', '.join(sorted(gm.PATH_C))}"
)


def _live_deposit_and_bots() -> tuple[float, list[dict]]:
    from services.order_harvester.loop import _cached_api

    api = _cached_api()
    deposit, bots = 0.0, []
    for b in api.list_bots():
        if int(b.status) != 2 or b.stat is None:
            continue
        s = b.stat
        bal = float(getattr(s, "balance", 0) or 0)
        deposit = max(deposit, bal)
        avg = float(getattr(s, "averagePrice", 0) or 0)
        pos = float(getattr(s, "position", 0) or 0)
        inverse = abs(bal) < 5
        bots.append({
            "id": str(b.id), "name": b.name, "price": avg, "inverse": inverse,
            "notional": abs(pos) if inverse else abs(pos) * avg,
            "signed_pos": pos,
            "volume": float(getattr(s, "tradeVolume", 0) or 0),
            "profit": float(getattr(s, "profit", 0) or 0),
        })
    return deposit, bots


def _params_for(bot_id: str) -> dict | None:
    """Последний снимок параметров бота из ginarea_live/params.csv."""
    import csv
    import json
    from pathlib import Path

    p = Path(__file__).resolve().parents[2] / "ginarea_live" / "params.csv"
    if not p.exists():
        return None
    tail_bytes = 8 * 1024 * 1024
    try:
        with p.open(encoding="utf-8", errors="ignore") as f:
            header = next(csv.reader(f))
            size = p.stat().st_size
            if size > tail_bytes:
                f.seek(size - tail_bytes)
                f.readline()                     # добиваем обрезанную строку
            # в params.csv встречаются NUL-байты — csv на них падает
            rows = csv.DictReader((ln.replace("\0", "") for ln in f),
                                  fieldnames=header)
            last = None
            for row in rows:
                if str(row.get("bot_id", "")).startswith(bot_id):
                    last = row
    except Exception:                                    # noqa: BLE001
        logger.exception("grid_model.params_read_failed bot=%s", bot_id)
        return None
    if not last or not last.get("raw_params_json"):
        return None
    try:
        return json.loads(last["raw_params_json"])
    except Exception:                                    # noqa: BLE001
        return None


def _border_pct(params: dict, price: float, side: int) -> float | None:
    """Расстояние до жёсткой границы в сторону набора, %.

    Шорт (side=2) набирает вверх — режет верхняя граница; лонг (side=1)
    набирает вниз — нижняя. У Auto набор идёт в обе стороны, берём ближнюю.
    """
    b = params.get("border") or {}
    top, bot = b.get("top"), b.get("bottom")
    if price <= 0:
        return None
    cands = []
    if side in (2, 3) and top:
        cands.append((float(top) / price - 1) * 100.0)
    if side in (1, 3) and bot:
        cands.append((1 - float(bot) / price) * 100.0)
    cands = [c for c in cands if c > 0]
    return min(cands) if cands else None


def _coin_of(name: str) -> str | None:
    up = (name or "").upper()
    for c in gm.PATH_C:
        if c in up:
            return c
    return "BTC" if "COIN" in up else None


def build_live() -> str:
    deposit, bots = _live_deposit_and_bots()
    if not bots:
        return "нет работающих ботов"
    out = [f"📐 ЖИВЫЕ БОТЫ ЧЕРЕЗ МОДЕЛЬ · депозит ${deposit:,.0f}", ""]
    total = 0.0
    for b in bots:
        d = _params_for(b["id"])
        if not d:
            out.append(f"{b['name']}: нет снимка параметров")
            continue
        gap = d.get("gap") or {}
        q = d.get("q") or {}
        coin = _coin_of(b["name"])
        if coin is None:
            out.append(f"{b['name']}: нет замеренного C для этого инструмента")
            continue
        step = float(d.get("gs") or 0)
        target = float(gap.get("tog") or 0)
        size = float(q.get("minQ") or 0)
        side = int(d.get("side") or 0)
        auto = side == 3
        try:
            p = gm.plan(coin, step, target, size, b["price"],
                        max_orders=int(d.get("maxOp") or 400), auto=auto,
                        obap=bool(d.get("obap")), deposit=deposit or 2530.0,
                        inverse=b["inverse"], short=(side == 2),
                        border_pct=_border_pct(d, b["price"], side))
        except ValueError as exc:
            out.append(f"{b['name']}: {exc}")
            continue
        total += p.net
        side = "Auto" if auto else ("шорт" if int(d.get("side") or 0) == 2
                                    else "лонг")
        out.append(
            f"{b['name']} [{side}]\n"
            f"  шаг {step} цель {target} выход по средней "
            f"{'ВКЛ' if d.get('obap') else 'ВЫКЛ'}\n"
            f"  модель: оборот ${p.turnover:,.0f} → реализ ${p.realized:,.0f}"
            f" → итог ${p.net:,.0f}/год\n"
            f"  инвентарь ${p.inventory:,.0f} = {p.leverage:.1f}× депозита")
        for w in p.warnings:
            out.append(f"  ⚠️ {w}")
        out.append("")
    out.append(f"ИТОГО по модели: ${total:,.0f}/год = "
               f"{total / deposit * 100:.0f}% на депозит" if deposit else "")
    out.append(f"коэффициенты с окна {gm.WINDOW}")
    return "\n".join(x for x in out if x is not None)


def build_alloc(budget: float) -> str:
    """Во что превращается каждый доллар инвентаря у каждого бота.

    Доход модели линеен по размеру ордера, поэтому «оптимум» вырождается в
    «всё лучшему». Полезно другое — показать разброс эффективности и цену
    текущего распределения.
    """
    deposit, bots = _live_deposit_and_bots()
    rows = []
    for b in bots:
        d = _params_for(b["id"])
        coin = _coin_of(b["name"])
        if not d or coin is None:
            continue
        gap, q = d.get("gap") or {}, d.get("q") or {}
        side = int(d.get("side") or 0)
        try:
            p = gm.plan(coin, float(d.get("gs") or 0), float(gap.get("tog") or 0),
                        float(q.get("minQ") or 0), b["price"],
                        max_orders=int(d.get("maxOp") or 400), auto=(side == 3),
                        obap=bool(d.get("obap")), deposit=deposit or 2530.0,
                        inverse=b["inverse"], short=(side == 2),
                        border_pct=_border_pct(d, b["price"], side))
        except ValueError:
            continue
        # Фандинг платится с ФАКТИЧЕСКОЙ позиции, а не с худшего инвентаря.
        # Берём текущий нотионал бота; на длинном горизонте он и есть
        # типичная позиция, тогда как inventory — это пик.
        fund = gm.funding_year(coin, b.get("notional", 0.0), short=(side == 2))
        rows.append((b["name"], p, fund, side))
    if not rows:
        return "нет данных по живым ботам"

    # ГРУППИРОВКА ПО МАРЖЕ-СЧЁТУ. USDT-боты делят один залог, монетные
    # (COIN_FUTURES) сидят на отдельном счёте с залогом в монете. Сравнивать
    # «$ с $1 риска» между счетами нельзя — это разные деньги, и капитал
    # между ними не перекладывается без конвертации.
    groups: dict[str, list] = {}
    for r in rows:
        key = "монетный счёт (залог в монете)" if r[1].inverse else "USDT-счёт"
        groups.setdefault(key, []).append(r)

    out = [f"📐 РАСПРЕДЕЛЕНИЕ РИСКА · бюджет инвентаря ${budget:,.0f}"]
    for gname, grp in groups.items():
        grp.sort(key=lambda r: -(r[1].net + r[2]) / max(r[1].inventory, 1))
        out.append(f"\n── {gname}")
        out.append(f"{'бот':<24}{'доход/год':>11}{'инвентарь':>11}"
                   f"{'$ с $1 риска':>14}")
        g_inv = g_inc = 0.0
        for name, p, fund, side in grp:
            inc = p.net + fund
            g_inv += p.inventory
            g_inc += inc
            flag = " ⚠️ завышено" if p.border_pct else ""
            out.append(f"{name[:23]:<24}{inc:>10,.0f}${p.inventory:>10,.0f}$"
                       f"{inc / max(p.inventory, 1):>14.3f}{flag}")
        if len(grp) > 1:
            out.append(f"{'по счёту':<24}{g_inc:>10,.0f}${g_inv:>10,.0f}$"
                       f"{g_inc / max(g_inv, 1):>14.3f}")
        clean = [r for r in grp if not r[1].border_pct]
        if len(clean) > 1:
            eff = [((r[1].net + r[2]) / max(r[1].inventory, 1), r[0])
                   for r in clean]
            hi, lo = max(eff), min(eff)
            out.append(f"  разрыв внутри счёта: «{hi[1][:20]}» {hi[0]:.3f} "
                       f"против «{lo[1][:20]}» {lo[0]:.3f} = "
                       f"{hi[0] / max(lo[0], 1e-9):.1f}×")
        out.append(f"  под бюджет ${budget:,.0f} размеры ордеров:")
        for name, p, fund, side in grp:
            k = budget / max(p.inventory, 1)
            size = p.notional_per_order * k / (1.0 if p.inverse else p.price)
            unit = "USD-контрактов" if p.inverse else name.split()[0]
            out.append(f"    {name[:23]:<24} {size:>10.5f} {unit}")
    out.append("\n⚠️ счета сравнивать между собой нельзя — разный залог.")
    out.append("   Внутри счёта доход линеен по размеру ордера.")
    return "\n".join(out)


def build_odds(which: str = "") -> str:
    """Карточка шансов по BTC и ETH: z-модель на 9 годах + уровни ботов и опционов.

    Прежняя версия считала шансы по зоне SMA100 — вне выборки это самый слабый
    признак (+0.9% к базе), z-модель по волатильности даёт +10.4% и
    откалибрована. Подробности в services/grid_model/odds_z.py.
    """
    from services.grid_model import odds as od
    from services.grid_model import odds_z

    try:
        deposit, bots = _live_deposit_and_bots()
    except Exception:                                    # noqa: BLE001
        logger.exception("grid_model.odds_bots_failed")
        deposit, bots = 0.0, []
    cards = []
    for sym, coin in (("BTCUSDT", "BTC"), ("ETHUSDT", "ETH")):
        if which and which.upper() not in (coin, sym):
            continue
        levels: list[tuple[str, float]] = []
        try:
            opt = odds_z.option_levels(coin)
        except Exception:                                # noqa: BLE001
            logger.exception("grid_model.option_levels_failed coin=%s", coin)
            opt = {}
        spot = opt.get("spot")
        for b in bots:
            if _coin_of(b["name"]) != coin or not spot:
                continue
            d = _params_for(b["id"])
            if not d:
                continue
            q = d.get("q") or {}
            side = int(d.get("side") or 0)
            bd = d.get("border") or {}
            border = bd.get("top") if b["signed_pos"] < 0 else bd.get("bottom")
            short_name = b["name"].split()[0] + (" шорт" if b["signed_pos"] < 0
                                                 else " лонг" if side == 1 else "")
            if border:
                levels.append((f"граница {short_name}", float(border)))
            if b["inverse"]:
                continue                  # залог в монете — обнуление считается иначе
            lv = od.bot_levels(price=spot, avg=b["price"], position=b["signed_pos"],
                               step_pct=float(d.get("gs") or 0),
                               order_size=float(q.get("minQ") or 0),
                               deposit=deposit or 2530.0,
                               border=float(border) if border else None,
                               short=b["signed_pos"] < 0,
                               max_orders=int(d.get("maxOp") or 400),
                               adverse_pct=40.0 if side == 3 else 64.0)
            levels.append((f"обнуление залога ({short_name})", lv.zero_equity))
        for key, nm in (("call_wall", "стена коллов"), ("put_wall", "стена путов"),
                        ("gamma_flip", "смена знака гаммы")):
            if opt.get(key):
                levels.append((nm, float(opt[key])))
        try:
            cards.append(odds_z.card(sym, levels=levels, price=spot))
        except Exception as exc:                         # noqa: BLE001
            logger.exception("grid_model.odds_card_failed sym=%s", sym)
            cards.append(f"❌ {coin}: {exc}")
    if not cards:
        return "укажи BTC или ETH"
    return "\n\n".join(cards)


def build(arg: str = "") -> str:
    parts = (arg or "").split()
    if not parts:
        return build_live()
    if parts[0].lower() in ("odds", "шансы"):
        return build_odds(parts[1] if len(parts) > 1 else "")
    if parts[0].lower() in ("help", "?"):
        return HELP
    if parts[0].lower() == "alloc":
        try:
            budget = float(parts[1]) if len(parts) > 1 else 7500.0
        except ValueError:
            return f"❌ бюджет числом\n\n{HELP}"
        return build_alloc(budget)
    try:
        if parts[0].lower() == "fit":
            coin, step, target = parts[1], float(parts[2]), float(parts[3])
            deposit = float(parts[4]) if len(parts) > 4 else 2530.0
            price = _price_hint(coin)
            p = gm.fit_to_deposit(coin, step, target, price, deposit)
            size = p.notional_per_order / price
            return (gm.card(p) + f"\n\nразмер ордера: {size:.4f} {coin.upper()}"
                    f" (${p.notional_per_order:,.0f}) при цене {price:,.0f}")
        coin, step, target, size = parts[0], float(parts[1]), float(parts[2]), \
            float(parts[3])
        deposit = float(parts[4]) if len(parts) > 4 else 2530.0
        return gm.card(gm.plan(coin, step, target, size, _price_hint(coin),
                               deposit=deposit))
    except (IndexError, ValueError) as exc:
        return f"❌ {exc}\n\n{HELP}"


def _price_hint(coin: str) -> float:
    """Текущая цена монеты из живых ботов, иначе разумный дефолт."""
    try:
        _, bots = _live_deposit_and_bots()
        for b in bots:
            if _coin_of(b["name"]) == coin.upper() and b["price"] > 0:
                return b["price"]
    except Exception:                                    # noqa: BLE001
        logger.exception("grid_model.price_hint_failed")
    return {"ETH": 2450.0, "BTC": 84_400.0}.get(coin.upper(), 1.0)
