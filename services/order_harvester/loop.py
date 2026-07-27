"""Order Harvester — фиксация отдельных плюсовых ордеров у dynamic-грид ботов.

Проблема (2026-07-08): у DYN-ботов выход по средней (obap=true) → отдельные
ордера почти никогда не закрываются по своим триггерам, профит копится бумагой.
Оператор (2026-07-15): когда открытый ордер достигает порога (BTC +$2.5,
альты +$1) — пауза бота → закрыть ВСЕ такие ордера батчем
(PUT /bots/{id}/close/{orderId}, как ✕ в UI) → снова запустить бота.
Батч за одну паузу — как оператор делает руками (10:08–10:33 МСК 15.07:
10 ордеров TEST ETH за 20 минут).

2026-07-18, разбор трёх дней молчания — две причины, обе в _candidates:
1) пагинация /bots/{id}/orders 0-BASED: с pageNumber=1 (дефолт клиента был
   1-based) сервер отдавал orders:null — харвестер видел пустоту;
2) у открытых ордеров profit=null (UI считает на клиенте) — даже с ордерами
   кандидатов бы не было. Теперь считаем сами: mark из stat (derive_mark),
   profit = (mark − вход) · qty · направление.

Безопасность:
- работает ТОЛЬКО по ботам из state/order_harvester_config.json;
- перед паузой проверяет, что у бота НЕТ in.otc (урок 2026-05-17: stop/start
  otc-ботов сбрасывает otcPassed → Failed). Динамики без in-блока — безопасно;
- каждый шаг журналируется в state/order_harvester_journal.jsonl;
- если resume не удался — ретраи, затем CRITICAL TG + freeze-файл: сервис
  замирает до ручного разбора (state/order_harvester_frozen.json);
- лимит действий в сутки на бота.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "state" / "order_harvester_config.json"
JOURNAL_PATH = ROOT / "state" / "order_harvester_journal.jsonl"
FROZEN_PATH = ROOT / "state" / "order_harvester_frozen.json"

POLL_INTERVAL_SEC = 60
STATUS_POLL_SEC = 3.0
STATUS_WAIT_MAX_SEC = 45.0
RESUME_RETRIES = 3

STATUS_ACTIVE = 2
STATUS_PAUSED = 3
STATUS_STOPPING = 11
STATUS_STOPPED = 12
PAUSED_LIKE = {STATUS_PAUSED, STATUS_STOPPED}

DEFAULT_CONFIG = {
    # безопасный фолбэк: если state-конфиг пропал/бит — ничего не трогаем
    "enabled": False,
    "bots": {},
    "max_orders_per_cycle": 10,
    "max_orders_per_day_per_bot": 40,
    # оператор 2026-07-15: чек и закрытие раз в минуту (= каждый тик)
    "min_gap_between_harvests_sec": 60,
    # но после цикла, где закрытия НЕ удались, — длинный откат, чтобы не
    # долбить pause/resume и API вхолостую (урок WAF 2026-07-08)
    "fail_backoff_sec": 600,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _journal(rec: dict) -> None:
    rec.setdefault("ts", _now())
    try:
        with JOURNAL_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        logger.exception("order_harvester.journal_failed")


def load_config() -> dict:
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        CONFIG_PATH.write_text(
            json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8")
        return dict(DEFAULT_CONFIG)
    except Exception:
        logger.exception("order_harvester.config_read_failed — using defaults")
        return dict(DEFAULT_CONFIG)
    out = dict(DEFAULT_CONFIG)
    out.update(cfg)
    return out


def freeze(reason: str, detail: dict | None = None) -> None:
    """Стоп-кран: сервис замирает до ручного удаления freeze-файла."""
    try:
        FROZEN_PATH.write_text(json.dumps(
            {"ts": _now(), "reason": reason, "detail": detail or {}},
            ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        logger.exception("order_harvester.freeze_write_failed")
    _journal({"event": "FROZEN", "reason": reason, "detail": detail or {}})


def is_frozen() -> bool:
    return FROZEN_PATH.exists()


# ── извлечение полей ордера (форма ответа /bots/{id}/orders) ─────────────────

def order_fields(o: dict) -> dict:
    """Нормализованные поля ордера GET /bots/{id}/orders (реальные формы:
    закрытый снят 2026-07-09, открытый — 2026-07-18): id=GUID, isOpen=bool,
    quantity, price (вход), side (1=BUY, 2=SELL), openedAt, trigger{...}.

    profit: у ЗАКРЫТЫХ — USD float; у ОТКРЫТЫХ — null (UI считает на клиенте).
    Для открытых profit_usd заполняет _candidates() по mark-цене."""
    oid = o.get("id")
    profit = o.get("profit")
    return {
        "order_id": str(oid) if oid is not None else None,
        "profit_usd": float(profit) if profit is not None else None,
        "opened": bool(o.get("isOpen")),
        "qty": o.get("quantity"),
        "price_in": o.get("price"),
        "side": o.get("side"),
    }


# ниже этого нотионала |pos|·avg деление bag/pos ненадёжно; и боли от мешка
# при таком pos нет — просто пропускаем тик
MIN_MARK_NOTIONAL_USD = 200.0


def derive_mark(stat) -> float | None:
    """Текущая цена, восстановленная из stat бота (линейные USDT-контракты).

    У открытых ордеров API отдаёт profit=null (UI GinArea считает на клиенте),
    поэтому воспроизводим тот же расчёт.

    OKX (замер 2026-07-27): `currentProfit` = ЧИСТЫЙ нереализованный PnL
    текущей позиции = (mark − averagePrice) · position, БЕЗ реализованного.
    Значит mark = avg + currentProfit/pos. Сверено с колонкой «Прибыль» в
    GinArea до цента (топ-ордер +$2.00, следующий +$1.82).

    Прежняя формула `(currentProfit − profit)` — семантика BitMEX, где
    currentProfit включал реализованный; на OKX она завышала mark на
    profit/pos (для ETH-OKX: +$21.9 → все ордера ложно в минусе, харвестер
    не находил кандидатов). BitMEX закрыт, оставляем OKX-семантику.
    """
    pos = float(stat.position or 0)
    avg = float(stat.averagePrice or 0)
    if avg <= 0 or abs(pos * avg) < MIN_MARK_NOTIONAL_USD:
        return None
    unrealized = float(stat.currentProfit or 0)
    return avg + unrealized / pos


def order_profit_usd(mark: float, f: dict) -> float | None:
    """(mark − вход) · qty · направление; side 1=BUY → +1, 2=SELL → −1."""
    if f["side"] == 1:
        direction = 1.0
    elif f["side"] == 2:
        direction = -1.0
    else:
        return None
    try:
        return (mark - float(f["price_in"])) * float(f["qty"]) * direction
    except (TypeError, ValueError):
        return None


def _candidates(api, bot_id: str, min_profit: float) -> list[dict]:
    stat = api.get_stat(int(bot_id))
    mark = derive_mark(stat)
    if mark is None:
        return []
    data = api.get_orders(int(bot_id), only_opened=True)
    orders = data.get("orders") or []
    out = []
    for o in orders:
        f = order_fields(o)
        if not (f["order_id"] and f["opened"]):
            continue
        profit = order_profit_usd(mark, f)
        if profit is None or profit < min_profit:
            continue
        f["profit_usd"] = round(profit, 2)
        out.append(f)
    out.sort(key=lambda f: -(f["profit_usd"] or 0))
    return out


def _wait_status(api, bot_id: str, want: set[int]) -> int | None:
    """Поллим runtime-статус до попадания в want. Возвращает статус или None."""
    deadline = time.monotonic() + STATUS_WAIT_MAX_SEC
    last = None
    while time.monotonic() < deadline:
        try:
            last = int(api.get_bot(int(bot_id)).status)
            if last in want:
                return last
        except Exception:
            logger.exception("order_harvester.status_read_failed bot=%s", bot_id)
        time.sleep(STATUS_POLL_SEC)
    return last


def _otc_guard(api, bot_id: str) -> bool:
    """True = безопасно паузить. Урок 2026-05-17: stop/start бота с in.otc
    сбрасывает otcPassed → Failed. У динамиков in-блока нет."""
    try:
        params = api.get_params(int(bot_id))
        in_block = (params.extra_raw or {}).get("in") or {}
        if in_block.get("otc"):
            return False
        return True
    except Exception:
        logger.exception("order_harvester.otc_guard_read_failed bot=%s", bot_id)
        return False  # не смогли проверить — не трогаем


def _day_count(bot_id: str, today: str) -> int:
    try:
        n = 0
        for ln in JOURNAL_PATH.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(ln)
            except json.JSONDecodeError:
                continue
            if r.get("event") == "HARVESTED" and r.get("bot_id") == bot_id \
                    and str(r.get("ts", "")).startswith(today):
                n += 1
        return n
    except OSError:
        return 0


def harvest_orders(api, bot_id: str, alias: str, cands: list[dict],
                   send_fn=None) -> int:
    """Одна пауза → закрыть ВСЕ ордера-кандидаты → резюм.
    Возвращает число реально закрытых ордеров."""
    from services.short_bots_guard import control

    base = {"bot_id": bot_id, "alias": alias}
    total = sum(c["profit_usd"] or 0 for c in cands)

    if not _otc_guard(api, bot_id):
        _journal({"event": "SKIP_OTC_GUARD", **base,
                  "order_ids": [c["order_id"] for c in cands]})
        freeze("otc_guard: у бота появился in.otc — пауза опасна", base)
        if send_fn:
            send_fn(f"🌾⛔️ Order Harvester ЗАМОРОЖЕН: у {alias} обнаружен in.otc — "
                    "пауза сбросит otcPassed. Разберись и удали "
                    "state/order_harvester_frozen.json")
        return 0

    _journal({"event": "HARVEST_START", **base, "n_orders": len(cands),
              "profit_total_usd": round(total, 2)})

    rec = control.pause_bot(
        bot_id, reason=f"order_harvest {len(cands)} orders +${total:.2f}",
        trigger="order_harvester")
    if rec.get("action") in ("skip_api_unavailable", "skip_read_failed", "error"):
        _journal({"event": "PAUSE_FAILED", **base, "control": rec})
        return 0
    st = _wait_status(api, bot_id, PAUSED_LIKE)
    if st not in PAUSED_LIKE:
        _journal({"event": "PAUSE_TIMEOUT", **base, "status": st})
        # бот не остановился — пробуем вернуть как было и выходим
        control.resume_bot(bot_id, reason="rollback: pause timeout",
                           trigger="order_harvester")
        return 0

    closed: list[dict] = []
    failed: list[dict] = []
    for cand in cands:
        obase = {**base, "order_id": cand["order_id"],
                 "profit_usd": cand["profit_usd"], "qty": cand["qty"],
                 "price_in": cand["price_in"]}
        try:
            api.close_order(int(bot_id), cand["order_id"])
            closed.append(cand)
            _journal({"event": "ORDER_CLOSED", **obase})
        except Exception as e:
            failed.append(cand)
            _journal({"event": "CLOSE_FAILED", **obase, "error": str(e)[:300]})
            logger.exception("order_harvester.close_failed bot=%s order=%s",
                             bot_id, cand["order_id"])

    # резюм ОБЯЗАТЕЛЕН независимо от исхода close — бот не должен стоять
    resumed = False
    for attempt in range(RESUME_RETRIES):
        control.resume_bot(bot_id, reason=f"order_harvest {len(closed)} closed",
                           trigger="order_harvester")
        st = _wait_status(api, bot_id, {STATUS_ACTIVE})
        if st == STATUS_ACTIVE:
            resumed = True
            break
        _journal({"event": "RESUME_RETRY", **base, "attempt": attempt + 1, "status": st})

    if not resumed:
        freeze("resume_failed: бот не вернулся в Active", {**base, "status": st})
        if send_fn:
            send_fn(f"🌾🚨 КРИТИЧНО: {alias} НЕ ЗАПУСТИЛСЯ после фиксации ордеров "
                    f"(статус {st}). Запусти руками в GinArea! Harvester заморожен.")
        _journal({"event": "RESUME_FAILED", **base, "status": st})
        return len(closed)

    for cand in closed:
        _journal({"event": "HARVESTED", **base, "order_id": cand["order_id"],
                  "profit_usd": cand["profit_usd"], "qty": cand["qty"],
                  "price_in": cand["price_in"]})

    if send_fn:
        if len(closed) == 1:
            c = closed[0]
            send_fn(f"🌾 {alias}: зафиксирован ордер +${c['profit_usd']:.2f} "
                    f"({c['qty'] or '?'} @ {c['price_in'] or '?'}). "
                    "Бот снова Working ✅")
        elif closed:
            got = sum(c["profit_usd"] for c in closed)
            parts = " + ".join(f"{c['profit_usd']:.2f}" for c in closed)
            send_fn(f"🌾 {alias}: зафиксировано ордеров: {len(closed)}, "
                    f"+${got:.2f} ({parts}). Бот снова Working ✅")
        if failed:
            send_fn(f"🌾⚠️ {alias}: не удалось закрыть {len(failed)} орд. "
                    f"(из {len(cands)}) — бот перезапущен, попробую позже.")
    return len(closed)


def tick(send_fn=None, api=None) -> int:
    """Один проход: по каждому боту конфига закрыть батчем все ордера выше
    порога (в рамках бюджетов). Возвращает число закрытых ордеров."""
    if is_frozen():
        return 0
    cfg = load_config()
    if not cfg.get("enabled"):
        return 0

    if api is None:
        api = _cached_api()
        if api is None:
            return 0

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    harvested = 0
    for bot_id, bcfg in (cfg.get("bots") or {}).items():
        alias = bcfg.get("alias", bot_id)
        min_profit = float(bcfg.get("min_order_profit_usd", 7.0))

        day_cap = int(cfg.get("max_orders_per_day_per_bot", 40))
        day_used = _day_count(bot_id, today)
        if day_used >= day_cap:
            continue
        last = _last_harvest_mono.get(bot_id)
        if last is not None and (time.monotonic() - last) < _next_gap.get(bot_id, 0):
            continue

        try:
            bot = api.get_bot(int(bot_id))
            if int(bot.status) != STATUS_ACTIVE:
                continue  # трогаем только работающего (Working) бота
            cands = _candidates(api, bot_id, min_profit)
        except Exception:
            logger.exception("order_harvester.scan_failed bot=%s", bot_id)
            continue
        if not cands:
            continue

        budget = min(int(cfg.get("max_orders_per_cycle", 10)), day_cap - day_used)
        n = harvest_orders(api, bot_id, alias, cands[:budget], send_fn=send_fn)
        harvested += n
        # успешный цикл → обычный gap (оператор: раз в минуту достаточно);
        # цикл без единого закрытия (пауза была, closes упали) → длинный
        # откат, чтобы не дёргать pause/resume каждый тик (урок WAF 07-08)
        _last_harvest_mono[bot_id] = time.monotonic()
        _next_gap[bot_id] = (float(cfg.get("min_gap_between_harvests_sec", 60))
                             if n > 0 else float(cfg.get("fail_backoff_sec", 600)))
    return harvested


_last_harvest_mono: dict[str, float] = {}
_next_gap: dict[str, float] = {}  # сколько ждать после последнего цикла бота
_api_cache: list = []  # [BotsAPI] — один логин на процесс; клиент сам ре-логинится на 401


def _cached_api():
    """GinArea логин нельзя дёргать каждый тик (2026-07-08: burst логинов →
    403 на /accounts/login на десятки минут). Держим один клиент на процесс —
    внутри GinAreaClient токен обновляется сам при 401."""
    if _api_cache:
        return _api_cache[0]
    from services.short_bots_guard.control import _build_api
    api, err = _build_api()
    if api is None:
        logger.warning("order_harvester.api_unavailable: %s", err)
        return None
    _api_cache.append(api)
    return api


async def order_harvester_loop(stop_event, *, send_fn=None,
                               interval_sec=POLL_INTERVAL_SEC):
    import asyncio
    logger.info("order_harvester.start interval=%ds config=%s",
                interval_sec, CONFIG_PATH)
    while not stop_event.is_set():
        try:
            await asyncio.to_thread(tick, send_fn)
        except Exception:
            logger.exception("order_harvester.tick_failed")
        try:
            await asyncio.wait_for(asyncio.shield(stop_event.wait()),
                                   timeout=interval_sec)
        except asyncio.TimeoutError:
            continue
    logger.info("order_harvester.stopped")
