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
- перед паузой проверяет, что у otc-бота ЕСТЬ позиция: пока она открыта,
  цикл не завершён и пауза «разовую проверку» не сбрасывает
  (docs/GINAREA_MECHANICS.md §1). Инцидент 17.05 с Failed был от
  set_params(p=false), а не от PUT /stop — раньше это было склеено, и гард
  морозил всю службу при виде in.otc;
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
    Для открытых profit_usd заполняет _candidates() по mark-цене.

    2026-08-02 (оператор поймал закрытия в минус, разбор по данным GinArea:
    133 закрытых ордера, 63 из них УБЫТОЧНЫЕ на −$24.63):
    - вход берём из `closedPrice` — это РЕАЛЬНАЯ цена исполнения. Раньше брали
      `price` (лимитная заявка), она с фактом не совпадает;
    - `fee` — фактическая комиссия входа, списанная биржей. Раньше её не
      вычитали вовсе, хотя выход стоит примерно столько же.
    """
    oid = o.get("id")
    profit = o.get("profit")

    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    # цена исполнения приоритетнее лимитной; если её нет — ордер не считаем
    fill = _f(o.get("closedPrice"))
    return {
        "order_id": str(oid) if oid is not None else None,
        "profit_usd": float(profit) if profit is not None else None,
        "opened": bool(o.get("isOpen")),
        "qty": o.get("quantity"),
        "price_in": fill if fill and fill > 0 else None,
        "limit_price": _f(o.get("price")),
        "fee": _f(o.get("fee")),
        "trigger_price": _f((o.get("trigger") or {}).get("price")),
        "side": o.get("side"),
        "fee_ccy": o.get("feeExchangeCurrencyId"),
    }


def past_own_trigger(mark: float, f: dict) -> bool | None:
    """Прошёл ли рынок собственный тейк ордера, а бот его так и не закрыл.

    ИМЕННО ЭТО ищет оператор. У ботов obap=true (выход по СРЕДНЕЙ цене):
    бот не обязан закрывать отдельный ордер на его тейке — он ждёт, пока к
    цели придёт средняя всей позиции (tapb/taps в stat.extension). Поэтому
    цена уходит за тейк отдельного ордера, а тот висит в плюсе.

    2026-08-02: сначала я сделал из тейка ПОТОЛОК и отбрасывал всё, что выше —
    то есть резал ровно те ордера, ради которых механизм и нужен. Ошибка.
    """
    trig, side = f.get("trigger_price"), f.get("side")
    if trig is None or side not in (1, 2):
        return None
    return (mark > float(trig)) if side == 1 else (mark < float(trig))


DERIV_LIVE_PATH = ROOT / "state" / "deriv_live.json"
MARK_STALE_SEC = 300.0     # цена старше 5 мин → не действуем


def market_mark(symbol: str, *, path: Path = DERIV_LIVE_PATH,
                now: datetime | None = None) -> float | None:
    """РЕАЛЬНАЯ текущая цена символа из рыночных данных (deriv_live mark_price).

    2026-07-28: НЕ выводим mark из stat бота (currentProfit/position) — на
    малой позиции это давало абсурд (BTC-OKX pos 0.005: $22 профита / 0.005 =
    сдвиг +$4400 → все ордера ложно +$22 → харвестер закрывал их в РЕАЛЬНЫЙ
    минус). Оператор: «бери данные где прибыльный ордер и закрывай, не
    пересчитывай». Реальная цена рынка не зависит от размера позиции.
    """
    now = now or datetime.now(timezone.utc)
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("order_harvester.deriv_read_failed")
        return None
    upd = d.get("last_updated")
    try:
        age = (now - datetime.fromisoformat(upd)).total_seconds()
        if age > MARK_STALE_SEC:
            logger.warning("order_harvester.mark_stale %s age=%.0fs", symbol, age)
            return None
    except (TypeError, ValueError):
        return None
    px = (d.get(symbol) or {}).get("mark_price")
    try:
        px = float(px)
        return px if px > 0 else None
    except (TypeError, ValueError):
        return None


OKX_HOSTS = ("https://www.okx.com", "https://aws.okx.com")
OKX_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
PRICE_MAX_DIVERGENCE_PCT = 0.3    # расхождение двух источников → не действуем


def okx_price(inst_id: str, *, timeout: float = 10.0) -> float | None:
    """Цена с ТОЙ ЖЕ биржи, где стоят боты. GinArea считает профит по ней.

    2026-08-02: раньше брали цену из deriv_live (сводка по Binance/Bybit) —
    там нет отметки времени на КАЖДЫЙ символ, только общая на файл, поэтому
    протухшая цена одного альта проходила проверку свежести и давала ложный
    плюс. OKX-тикер отдаёт цену того инструмента, которым торгует бот.
    """
    import urllib.request

    if not inst_id:
        return None
    for host in OKX_HOSTS:
        try:
            req = urllib.request.Request(
                f"{host}/api/v5/market/ticker?instId={inst_id}",
                headers={"User-Agent": OKX_UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                j = json.loads(r.read().decode("utf-8"))
            px = float((j.get("data") or [{}])[0].get("last"))
            return px if px > 0 else None
        except Exception:
            continue
    logger.warning("order_harvester.okx_price_failed inst=%s", inst_id)
    return None


def binance_price(symbol: str, *, timeout: float = 10.0) -> float | None:
    """Второй ЖИВОЙ источник цены для сверки (публичный тикер, без ключей)."""
    import urllib.request

    try:
        req = urllib.request.Request(
            f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}",
            headers={"User-Agent": OKX_UA, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            px = float(json.loads(r.read().decode("utf-8"))["price"])
        return px if px > 0 else None
    except Exception:
        return None


def agreed_price(inst_id: str, symbol: str) -> float | None:
    """Цена, подтверждённая ДВУМЯ независимыми источниками.

    Одиночный источник уже подводил дважды (28.07 и 02.08) и каждый раз это
    стоило денег. Основная — OKX (биржа бота), сверочная — живой тикер Binance,
    запасная — deriv_live. Расходятся больше чем на PRICE_MAX_DIVERGENCE_PCT —
    значит один источник врёт, и мы НЕ ДЕЙСТВУЕМ.

    2026-08-02: сверочным сначала стоял только файл deriv_live — он пишется
    раз в ~5 мин и постоянно упирался в проверку свежести (mark_stale в логе),
    то есть глушил механизм целиком. Живой тикер снимает эту зависимость.
    """
    okx = okx_price(inst_id)
    if okx is None:
        return None
    ref = binance_price(symbol)
    if ref is None:
        ref = market_mark(symbol)          # запасной сверочный источник
    if ref is None:
        logger.warning("order_harvester.no_second_source symbol=%s — не действуем",
                       symbol)
        return None
    div = abs(okx - ref) / ref * 100
    if div > PRICE_MAX_DIVERGENCE_PCT:
        logger.warning("order_harvester.price_divergence %s okx=%.6f ref=%.6f "
                       "расхождение %.2f%% > %.2f%% — не действуем",
                       symbol, okx, ref, div, PRICE_MAX_DIVERGENCE_PCT)
        return None
    return okx


USDT_CURRENCY_ID = 11       # feeExchangeCurrencyId у линейных USDT-ботов
FEE_RATE_MIN = 0.0001       # 0.01% — ниже этого ставка комиссии неправдоподобна
FEE_RATE_MAX = 0.002        # 0.20% — выше тоже

def _is_inverse(mark: float, f: dict) -> bool | None:
    """Инверсный контракт (qty в долларовых контрактах, комиссия в монете)?

    2026-08-17, оператор спросил, почему у BTC SHORT нет ордеров «эквивалентных
    $2»: этот бот монетно-маржинальный (OKX exchangeId=3, баланс в BTC), а
    формула прибыли была написана только под линейные USDT-боты.

    Признак — валюта комиссии: 11=USDT → линейный, иное (4=BTC) → инверсный.
    Отдельно перепроверяем ЦИФРОЙ: ставка комиссии обязана попасть в
    правдоподобный диапазон при выбранной трактовке. У BTC SHORT она даёт
    0.0500% только как инверсная, у BTC DYNAMIC_c — только как линейная.
    Признак и проверка разошлись → возвращаем None, ордер пропускаем: гадать
    здесь нельзя, ошибка в трактовке завышает прибыль в тысячи раз.
    """
    try:
        qty = float(f["qty"])
        price = float(f["price_in"])
        fee = abs(float(f.get("fee") or 0.0))
    except (TypeError, ValueError, KeyError):
        return None
    if qty <= 0 or price <= 0:
        return None

    ccy = f.get("fee_ccy")
    by_ccy = None if ccy is None else (ccy != USDT_CURRENCY_ID)

    if fee == 0.0:
        # нулевая комиссия (мейкер-ребейт, синтетика в тестах): ставку не
        # проверить, но и слагаемое комиссии обнуляется. Решаем по валюте,
        # без валюты — линейный: так вело себя всё до 2026-08-17, и ни один
        # реальный инверсный ордер без feeExchangeCurrencyId не встречался.
        return bool(by_ccy)

    linear_rate = fee / (qty * price)          # комиссия в USDT, qty в монете
    inverse_rate = fee * price / qty           # комиссия в монете, qty в USD
    linear_ok = FEE_RATE_MIN <= linear_rate <= FEE_RATE_MAX
    inverse_ok = FEE_RATE_MIN <= inverse_rate <= FEE_RATE_MAX
    if linear_ok == inverse_ok:                # обе или ни одной — неоднозначно
        return None
    if by_ccy is not None and by_ccy != inverse_ok:
        return None                            # валюта и ставка спорят — не гадаем
    return inverse_ok


def order_profit_usd(mark: float, f: dict) -> float | None:
    """ЧИСТАЯ прибыль ордера в долларах, за вычетом комиссий.

    side 1=BUY → +1, 2=SELL → −1.
    Комиссия: `fee` — фактически списанная за вход; выход стоит примерно
    столько же, поэтому вычитаем удвоенную. Не знаем комиссию — не гадаем,
    ордер пропускаем (2026-08-02: без этого вычета половина закрытий уходила
    в минус на копеечном плюсе).

    Линейный контракт: qty в монете, PnL = (mark − вход) · qty · направление.
    Инверсный: qty в долларовых контрактах, PnL в монете =
    qty · (1/вход − 1/mark) для LONG и qty · (1/mark − 1/вход) для SHORT,
    затем переводим в доллары по mark.
    """
    if f["side"] == 1:
        direction = 1.0
    elif f["side"] == 2:
        direction = -1.0
    else:
        return None
    if f.get("price_in") is None:
        return None                     # нет цены исполнения — не гадаем
    fee = f.get("fee")
    if fee is None:
        return None                     # нет комиссии — не гадаем
    try:
        price_in = float(f["price_in"])
        qty = float(f["qty"])
        fee = abs(float(fee))
    except (TypeError, ValueError):
        return None
    if mark <= 0 or price_in <= 0:
        return None

    inverse = _is_inverse(mark, f)
    if inverse is None:
        return None                     # тип контракта неясен — не гадаем
    if inverse:
        pnl_coin = qty * (1.0 / price_in - 1.0 / mark) * direction
        return (pnl_coin - 2.0 * fee) * mark
    return (mark - price_in) * qty * direction - 2.0 * fee


WATCH_PATH = ROOT / "state" / "order_harvester_watch.json"
HOLD_MIN_DEFAULT = 15.0   # минут подряд в плюсе, прежде чем закрывать


def _read_watch() -> dict:
    try:
        return json.loads(WATCH_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_watch(w: dict) -> None:
    try:
        WATCH_PATH.write_text(json.dumps(w, ensure_ascii=False, indent=1),
                              encoding="utf-8")
    except OSError:
        logger.exception("order_harvester.watch_write_failed")


def _candidates(api, bot_id: str, min_profit: float, symbol: str,
                inst_id: str = "", hold_min: float = HOLD_MIN_DEFAULT,
                now: datetime | None = None) -> list[dict]:
    """Кандидаты на закрытие: ЗАВИСШИЕ прибыльные ордера.

    ТЗ оператора (02.08, дословно): «иногда почему-то GinArea не закрывает
    такие ордера — задача не моментально, а с каким-то кулдауном
    анализировать и если есть такие зависшие, реально прибыльные — закрывать».

    Кулдаун здесь же и защита: ордер должен держать прибыль выше порога
    hold_min минут ПОДРЯД. Ложная цена живёт секунды-минуты и не подтвердится,
    а реально зависший ордер стоит часами. Именно этой проверки не было, когда
    харвестер закрыл 70 ордеров в минус.
    """
    now = now or datetime.now(timezone.utc)
    mark = agreed_price(inst_id, symbol) if inst_id else market_mark(symbol)
    if mark is None:
        return []          # цена не подтверждена — не гадаем, не действуем
    data = api.get_orders(int(bot_id), only_opened=True)
    orders = data.get("orders") or []
    watch = _read_watch()
    seen: set[str] = set()
    out = []
    for o in orders:
        f = order_fields(o)
        if not (f["order_id"] and f["opened"]):
            continue
        profit = order_profit_usd(mark, f)
        if profit is None:
            continue
        oid = f["order_id"]
        if profit < min_profit:
            watch.pop(oid, None)       # упал ниже порога — отсчёт заново
            continue
        seen.add(oid)
        rec = watch.get(oid)
        if not rec:
            rec = {"since": now.isoformat(timespec="seconds"), "bot": bot_id}
            watch[oid] = rec
            if hold_min > 0:
                logger.info("order_harvester.watch_start bot=%s order=%s "
                            "профит=%.2f$ — жду %.0f мин подтверждения",
                            bot_id, oid, profit, hold_min)
        try:
            held = (now - datetime.fromisoformat(rec["since"])).total_seconds() / 60
        except (KeyError, ValueError):
            rec["since"] = now.isoformat(timespec="seconds")
            held = 0.0
        rec["profit"] = round(profit, 2)
        if held < hold_min:
            continue                   # ещё не выдержан кулдаун
        f["profit_usd"] = round(profit, 2)
        f["held_min"] = round(held)
        f["past_trigger"] = past_own_trigger(mark, f)
        out.append(f)
    # чистим ордера, которых уже нет среди открытых
    for oid in [k for k, v in watch.items()
                if v.get("bot") == bot_id and k not in seen]:
        watch.pop(oid, None)
    _write_watch(watch)
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
    """True = безопасно паузить.

    2026-08-17, оператор поправил: пауза сама по себе «разовую проверку» НЕ
    сбрасывает. docs/GINAREA_MECHANICS.md §1: «Цикл начинается при старте
    бота или после full-close позиции», и отдельно — «сбрасывается только
    при full-close, не при Out Stop». Пока позиция открыта, цикл не завершён:
    снятый с паузы бот игнорирует in-условие и работает обычным гридом, пока
    не сбросит позицию целиком, и только тогда снова ждёт точку входа.

    Инцидент 17.05 с переходом в Failed был вызван set_params(p=false) —
    правкой конфига, а не PUT /bots/{id}/stop. Здесь это было склеено в одно,
    из-за чего гард морозил всю службу при виде in.otc.

    Что осталось настоящим ограничением: паузить otc-бота БЕЗ позиции не
    надо — резюм начнёт новый цикл и бот будет ждать indicator-сигнал.
    На практике сюда не попадаем (нет позиции — нет и открытых ордеров),
    но условие оставлено явным.
    """
    try:
        params = api.get_params(int(bot_id))
        in_block = (params.extra_raw or {}).get("in") or {}
        if not in_block.get("otc"):
            return True
        stat = api.get_stat(int(bot_id))
        return bool(float(getattr(stat, "position", 0.0) or 0.0))
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


def _close_batch(api, bot_id: str, base: dict,
                 cands: list[dict]) -> tuple[list[dict], list[dict]]:
    """Закрыть список ордеров, вернуть (закрытые, упавшие). Журналирует каждый."""
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
    return closed, failed


def harvest_orders(api, bot_id: str, alias: str, cands: list[dict],
                   send_fn=None) -> int:
    """Одна пауза → закрыть ВСЕ ордера-кандидаты → резюм.
    Возвращает число реально закрытых ордеров.

    У ботов с in.otc паузы НЕ делаем — закрываем прямо на ходу, см. ниже.
    """
    from services.short_bots_guard import control

    base = {"bot_id": bot_id, "alias": alias}
    total = sum(c["profit_usd"] or 0 for c in cands)

    if not _otc_guard(api, bot_id):
        # otc-бот без позиции: пауза не нужна (и кандидатов там взяться
        # неоткуда). Просто пропускаем — службу не морозим, остальные боты
        # к этому отношения не имеют.
        _journal({"event": "SKIP_OTC_NO_POSITION", **base,
                  "order_ids": [c["order_id"] for c in cands]})
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

    closed, failed = _close_batch(api, bot_id, base, cands)

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
        symbol = bcfg.get("symbol")
        if not symbol:
            logger.warning("order_harvester.no_symbol bot=%s — пропуск "
                           "(нужна реальная цена)", bot_id)
            continue

        # дневной кап: 0 / отсутствует = БЕЗ ЛИМИТА (оператор 2026-07-27:
        # «какой ещё лимит?» — закрыть плюсовой ордер выгодно всегда, квота
        # бессмысленна; API бережёт gap между циклами, не суточный потолок).
        day_cap = int(cfg.get("max_orders_per_day_per_bot", 0) or 0)
        day_used = _day_count(bot_id, today) if day_cap > 0 else 0
        if day_cap > 0 and day_used >= day_cap:
            continue
        last = _last_harvest_mono.get(bot_id)
        if last is not None and (time.monotonic() - last) < _next_gap.get(bot_id, 0):
            continue

        try:
            bot = api.get_bot(int(bot_id))
            if int(bot.status) != STATUS_ACTIVE:
                continue  # трогаем только работающего (Working) бота
            cands = _candidates(api, bot_id, min_profit, symbol,
                                inst_id=bcfg.get("inst_id", ""),
                                hold_min=float(cfg.get("min_hold_minutes",
                                                       HOLD_MIN_DEFAULT)))
        except Exception as exc:
            # GinArea регулярно отдаёт 502/503 — это их сервер, не наша ошибка.
            # Раньше любой сбой писался как ERROR с полным трейсбеком: 15 штук
            # в сутки, на этом фоне настоящую ошибку в логе не найти.
            # Транзиентные серверные — одной строкой WARNING, остальное как было.
            transient = ("502" in str(exc) or "503" in str(exc)
                         or "504" in str(exc) or "Bad Gateway" in str(exc)
                         or type(exc).__name__ == "GinAreaServerError")
            if transient:
                logger.warning("order_harvester.scan_skipped bot=%s "
                               "(сервер GinArea недоступен: %s)",
                               bot_id, type(exc).__name__)
            else:
                logger.exception("order_harvester.scan_failed bot=%s", bot_id)
            continue
        if not cands:
            continue

        cycle_cap = int(cfg.get("max_orders_per_cycle", 10))
        budget = cycle_cap if day_cap <= 0 else min(cycle_cap, day_cap - day_used)
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
