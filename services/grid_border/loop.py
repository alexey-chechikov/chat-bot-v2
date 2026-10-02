"""Граница набора: за пределом хода сетка перестаёт наращивать позицию.

⛔ ВЫКЛЮЧЕНА 11.09.2026 — ЗАМОРОЗКА ОПРОВЕРГНУТА.

Претензию поднял Win, проверено независимо: симуляция шорт-сетки С
ВЫХОДОМ ПО СРЕДНЕЙ на 20 475 часах H1 BTC (2024-2026). У всех сеток
оператора стоит «Выход по средней цене: on», значит механизм именно
такой.

    режим          закрыто эпизодов   итог      пик позиции   худший мешок
    без правил              64        +$2 478      $31 389        −$8 976
    ЗАМОРОЗКА                6          −$738       $2 520        −$1 728
    рез 30%                278          −$758       $4 838          −$228

Заморозка обрушила число закрытых эпизодов в десять раз. Причина: доборы
ПОДТЯГИВАЮТ среднюю к цене и делают выход достижимым. Заморозишь доборы —
средняя застывает внизу, выход убегает, позиция висит.

МОЯ ОШИБКА В ЗАМЕРЕ. Обоснование +$14 008 (10.09) для этого вывода
невалидно: тот замер брал готовую историю позиции из снимков и обрезал её
сверху. История позиции при этом задавалась извне и от обрезки не
зависела — то есть вопрос «а закрылась бы обрезанная позиция» не
задавался вообще. Для сетки с выходом по средней это и есть решающий
вопрос.

ЧТО РАБОТАЕТ ВМЕСТО: рез, а не заморозка. Закрытие худших входов
поднимает среднюю к цене и УСКОРЯЕТ выход. Лучшая ячейка, влезающая в
депозит $2 161: триггер по дрейфу средней −7%, рез 10% — +$125 за 2.3
года при требуемом капитале $1 392. Код под это ещё не переписан.

Ниже — исходное обоснование, оно оставлено как есть, чтобы было видно,
на чём именно я ошибся.


ЗАЧЕМ. Направленная часть PnL сетки убыточна по построению: позиция
растёт именно тогда, когда рынок идёт против. 03.09 шортовый бот дошёл до
плеча 3.65 и номинала $7 883, и остановить это было нечем — риск-контур
меряет МЕШОК, а мешок при усреднении вверх остаётся маленьким, пока
позиция раздувается.

ЧТО ИМЕННО ИЗМЕРЕНО (11 BTC-ботов, 6 280 бот-часов):

    вариант                          PnL       выигрыш   вне августа
    без ограничения             -$26 048            —             —
    A. открытие суток ±0.75ATR  -$25 900         +$148          -$86
    B. старт позиции ±0.75ATR   -$12 040      +$14 008       +$7 902
    D. ПОК ±0.5ATR              -$18 255       +$7 793       +$2 802
    C. потолок |позиции| ×1.5   -$22 319       +$3 729         +$147

Взят вариант B. Дневная граница (A) не работает и слегка вредит: она
переставляется каждое утро и в тренде едет за рынком. ПОК (D) работает,
но втрое хуже — это ориентир РЫНКА, он не знает, где стоит позиция.
Якорь B меряет, насколько рынок ушёл против ТЕБЯ, а это и есть величина,
от которой растёт мешок. Вариант C держится только на августе.

ЧЕМ МОРОЗИМ. Не паузой: остановленный бот перестаёт и ЗАКРЫВАТЬ ордера,
а замер моделировал заморозку только набора. Морозим через maxOp,
выставляя его равным числу открытых ордеров — новые не открываются,
открытые продолжают закрываться по своим таргетам.

ЧЕГО ЭТО НЕ ДЕЛАЕТ. Не закрывает позицию. Закрытие проверено
контрфактом на 03.09: немедленное сокращение на 30% дало бы -$3.83 к
итогу при выигрыше $47.86 по худшей точке. Резать нечего.

ЧЕСТНАЯ ГРАНИЦА ПРИМЕНИМОСТИ. На нынешних размерах оператора ($1 800
позиции, спокойный месяц) правило даёт единицы долларов: замер по его
живым ботам — BTC_c_c +$4.45 за 333 часа, LONG COIN -$0.31 за 184 часа.
Весь выигрыш сидит в хвосте. Это страховка, а не источник дохода.
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import statistics as st
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "state" / "grid_border_config.json"
STATE_PATH = ROOT / "state" / "grid_border_state.json"
JOURNAL_PATH = ROOT / "state" / "grid_border_journal.jsonl"
HEARTBEAT_PATH = ROOT / "state" / "grid_border_heartbeat.json"
CANDLES_PATH = ROOT / "market_live" / "market_1h.csv"

POLL_INTERVAL_SEC = 120


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _journal(rec: dict) -> None:
    try:
        with JOURNAL_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps({**rec, "ts": _now()}, ensure_ascii=False) + "\n")
    except OSError:
        logger.exception("grid_border.journal_failed")


def load_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def read_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_state(d: dict) -> None:
    try:
        STATE_PATH.write_text(json.dumps(d, ensure_ascii=False, indent=1),
                              encoding="utf-8")
    except OSError:
        logger.exception("grid_border.state_write_failed")


def atr(path: Path = CANDLES_PATH, periods: int = 14) -> float | None:
    """ATR по дневным барам, собранным из часовых свечей."""
    days: dict[str, list] = defaultdict(list)
    try:
        with path.open(encoding="utf-8") as f:
            next(f)
            for ln in f:
                p = ln.split(",")
                if len(p) > 4:
                    try:
                        days[p[0][:10]].append((float(p[1]), float(p[2]),
                                                float(p[3]), float(p[4])))
                    except ValueError:
                        continue
    except OSError:
        return None
    dk = sorted(days)
    if len(dk) < periods + 1:
        return None
    bars = {k: {"high": max(x[1] for x in days[k]),
                "low": min(x[2] for x in days[k]),
                "close": days[k][-1][3]} for k in dk}
    trs = []
    for j in range(len(dk) - periods, len(dk)):
        b, pb = bars[dk[j]], bars[dk[j - 1]]
        trs.append(max(b["high"] - b["low"], abs(b["high"] - pb["close"]),
                       abs(b["low"] - pb["close"])))
    return st.mean(trs) if trs else None


def border_of(anchor: float, is_long: bool, atr_value: float,
              k: float) -> float:
    """Цена, за которой набор замораживается.

    Лонг теряет вниз, шорт вверх — граница ставится с той стороны, где
    позиция УХУДШАЕТСЯ. С противоположной стороны ограничивать нечего:
    там позиция схлопывается сама.
    """
    return (anchor - k * atr_value) if is_long else (anchor + k * atr_value)


def is_breached(price: float, border: float, is_long: bool) -> bool:
    return price < border if is_long else price > border


def decide(*, price: float, position_usd: float, anchor: float | None,
           atr_value: float, k: float, open_orders: int, max_op: int,
           frozen_at: int | None) -> dict:
    """Что сделать с этим ботом. Чистая функция — вся логика здесь.

    Возвращает action: NONE | SET_ANCHOR | FREEZE | RELEASE | CLEAR.
    """
    if not position_usd:
        # Позиция схлопнулась: якорь снимаем, заморозку отпускаем.
        return {"action": "CLEAR" if (anchor or frozen_at) else "NONE"}
    if anchor is None:
        return {"action": "SET_ANCHOR", "anchor": price}
    if not atr_value:
        return {"action": "NONE", "reason": "нет ATR"}
    is_long = position_usd > 0
    border = border_of(anchor, is_long, atr_value, k)
    breached = is_breached(price, border, is_long)
    if breached and frozen_at is None:
        if open_orders <= 0:
            # Морозить нечем: без открытых ордеров maxOp=0 остановил бы
            # сетку целиком, а это уже пауза, а не заморозка набора.
            return {"action": "NONE", "border": border,
                    "reason": "нет открытых ордеров"}
        return {"action": "FREEZE", "border": border,
                "new_max_op": open_orders, "prev_max_op": max_op}
    if not breached and frozen_at is not None:
        return {"action": "RELEASE", "border": border}
    return {"action": "NONE", "border": border,
            "breached": breached, "frozen": frozen_at is not None}


def seed_anchor(bot_id: str, snapshots: Path | None = None) -> float | None:
    """Якорь для позиции, которая УЖЕ открыта к моменту старта службы.

    Иначе служба, поднявшись, поставит якорь на сегодняшнюю цену и решит,
    что всё в порядке. 10.09 так и вышло на первом же тике: LONG COIN
    набирался от $80 468, а якорь встал на $78 128 — граница уехала туда,
    где позиции ничего не грозит, хотя она была глубоко под водой.

    Ищем в снимках последний момент, когда позиция была пуста, и берём
    цену следующего за ним снимка — это и есть начало нынешнего набора.
    Средняя цена позиции для якоря НЕ годится: она ползёт вместе с
    добором, то есть повторяет ошибку дневной границы.
    """
    path = snapshots or (ROOT / "ginarea_live" / "snapshots.csv")
    try:
        with path.open(encoding="utf-8") as f:
            head = f.readline().strip().split(",")
            idx = {n: k for k, n in enumerate(head)}
            need = ("bot_id", "position", "average_price")
            if any(n not in idx for n in need):
                return None
            seq = []
            for ln in f:
                p = ln.rstrip("\n").split(",")
                if len(p) <= max(idx.values()):
                    continue
                try:
                    if str(int(float(p[idx["bot_id"]]))) != str(bot_id):
                        continue
                    seq.append((abs(float(p[idx["position"]])),
                                float(p[idx["average_price"]] or 0)))
                except (ValueError, IndexError):
                    continue
    except OSError:
        return None
    if len(seq) < 5:
        return None
    nonzero = [q for q, _ in seq if q]
    if not nonzero:
        return None
    med = st.median(nonzero)
    start = None
    for k, (q, _) in enumerate(seq):
        if q < med * 0.1:
            start = k
    if start is None or start + 1 >= len(seq):
        return None
    return seq[start + 1][1] or None


def _price_of(inst_id: str) -> float | None:
    from services.order_harvester.loop import okx_price
    try:
        return okx_price(inst_id) or None
    except Exception:
        logger.exception("grid_border.price_failed inst=%s", inst_id)
        return None


def _apply(api, bot_id: int, new_max_op: int) -> bool:
    try:
        p = api.get_params(bot_id)
        api.set_params(bot_id, dataclasses.replace(p, maxOp=int(new_max_op)))
        return True
    except Exception:
        logger.exception("grid_border.set_params_failed bot=%s", bot_id)
        return False


def tick(api=None) -> str:
    cfg = load_config()
    status = "ok"
    try:
        if not cfg.get("enabled"):
            return "disabled"
        if api is None:
            from services.order_harvester.loop import _cached_api
            api = _cached_api()
            if api is None:
                return "no_api"
        atr_value = atr() or 0.0
        k = float(cfg.get("k_atr", 0.75))
        dry = bool(cfg.get("dry_run", True))
        state = read_state()
        bots_state = state.setdefault("bots", {})
        acted = 0

        for bid, bcfg in (cfg.get("bots") or {}).items():
            price = _price_of(bcfg.get("inst_id", ""))
            if not price:
                continue
            try:
                b = api.get_bot(int(bid))
                params = api.get_params(int(bid))
            except Exception:
                logger.exception("grid_border.read_failed bot=%s", bid)
                continue
            if int(b.status) != 2:
                continue
            pos = float(getattr(b.stat, "position", 0) or 0)
            pos_usd = pos if bcfg.get("inverse") else pos * price
            try:
                od = api.get_orders(int(bid), page_size=100, page_number=0,
                                    only_opened=True)
                n_open = len(od.get("orders") or [])
            except Exception:
                logger.exception("grid_border.orders_failed bot=%s", bid)
                continue

            bs = bots_state.setdefault(bid, {})
            d = decide(price=price, position_usd=pos_usd,
                       anchor=bs.get("anchor"), atr_value=atr_value, k=k,
                       open_orders=n_open, max_op=int(params.maxOp or 0),
                       frozen_at=bs.get("frozen_max_op"))
            act = d["action"]
            if act == "SET_ANCHOR":
                # Позиция уже была открыта к моменту старта — якорь берём
                # из истории, иначе он встанет на сегодняшнюю цену и
                # граница уедет туда, где позиции ничего не грозит.
                seeded = seed_anchor(bid)
                anchor = seeded if seeded else d["anchor"]
                bs["anchor"] = anchor
                bs["anchor_ts"] = _now()
                _journal({"event": "ANCHOR", "bot": bid,
                          "alias": bcfg.get("alias", bid),
                          "anchor": round(anchor, 2),
                          "source": "история" if seeded else "текущая цена"})
            elif act == "CLEAR":
                if bs.get("frozen_max_op") and not dry:
                    _apply(api, int(bid), int(bs["frozen_max_op"]))
                _journal({"event": "CLEAR", "bot": bid,
                          "alias": bcfg.get("alias", bid),
                          "restored_max_op": bs.get("frozen_max_op")})
                bots_state[bid] = {}
            elif act == "FREEZE":
                rec = {"event": "WOULD_FREEZE" if dry else "FREEZE",
                       "bot": bid, "alias": bcfg.get("alias", bid),
                       "price": round(price, 2),
                       "border": round(d["border"], 2),
                       "anchor": bs.get("anchor"),
                       "position_usd": round(pos_usd, 2),
                       "max_op_from": d["prev_max_op"],
                       "max_op_to": d["new_max_op"]}
                if not dry and _apply(api, int(bid), d["new_max_op"]):
                    bs["frozen_max_op"] = d["prev_max_op"]
                    acted += 1
                elif dry:
                    bs["frozen_max_op"] = d["prev_max_op"]
                _journal(rec)
            elif act == "RELEASE":
                prev = bs.get("frozen_max_op")
                ok = True if dry else _apply(api, int(bid), int(prev or 0))
                if ok:
                    bs.pop("frozen_max_op", None)
                    acted += 1
                _journal({"event": "WOULD_RELEASE" if dry else "RELEASE",
                          "bot": bid, "alias": bcfg.get("alias", bid),
                          "price": round(price, 2),
                          "border": round(d["border"], 2),
                          "max_op_back_to": prev})

        state["last_tick"] = _now()
        state["atr"] = round(atr_value, 2)
        write_state(state)
        status = f"acted:{acted}" if acted else "ok"
        return status
    finally:
        try:
            HEARTBEAT_PATH.write_text(
                json.dumps({"ts": _now(), "status": status},
                           ensure_ascii=False), encoding="utf-8")
        except OSError:
            logger.exception("grid_border.heartbeat_failed")


async def grid_border_loop(stop_event=None) -> None:
    cfg = load_config()
    logger.info("grid_border.start interval=%ds k=%s dry_run=%s",
                POLL_INTERVAL_SEC, cfg.get("k_atr"), cfg.get("dry_run"))
    while True:
        if stop_event is not None and stop_event.is_set():
            return
        try:
            tick()
        except Exception:
            logger.exception("grid_border.tick_failed")
        try:
            if stop_event is not None:
                await asyncio.wait_for(stop_event.wait(), POLL_INTERVAL_SEC)
                return
            await asyncio.sleep(POLL_INTERVAL_SEC)
        except asyncio.TimeoutError:
            continue
