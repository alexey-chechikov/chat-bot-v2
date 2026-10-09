"""Стресс-бюджет живых сеток: сколько потеряет бот, если цена резко уйдёт против него,
и где поставить границу, чтобы сетка не доливала до опасного размера.

Проверено 06.10.2026 (research/grid_risk/, полный капитал, 25 книг × 3 окна): правило
«новый ордер только пока убыток при стресс-ходе S = max(10%, 3·σ24ч·√3) не больше 25%
капитала» почти не меняет доход по медиане, но вдвое–втрое режет ликвидации:
2/3/0 против 6/9/2 у просто меньшего ордера. Цена — часть дохода прибыльных книг.

Бот ботов НЕ трогает (пауза GinArea сломана): считает и подсказывает границу,
решение и правка — за оператором. Сигнал — только при ухудшении статуса бота
(событийный риск-пинг), полная карточка — по команде /stress.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "state" / "stress_budget_config.json"
STATE = ROOT / "state" / "stress_budget_state.json"
JOURNAL = ROOT / "state" / "stress_budget_journal.jsonl"
DEFAULT = {"enabled": True, "budget_frac": 0.25, "danger_frac": 0.50, "s_floor": 0.10,
           "s_mult": 3.0, "poll_sec": 1800, "cooldown_hours": 12.0, "equity_usd": None,
           # оператор 22.07: «мешки в ТГ не интересуют» — сам пишет только при 🔴
           # (один стресс-ход съест ≥ половины депозита); 🟡 видно по /stress
           "ping_min_status": "danger"}
SYM = {"BTC": "BTCUSDT", "ETH": "ETHUSDT"}
RANK = {"ok": 0, "warn": 1, "danger": 2}
COIN_RU = {"BTC": "BTC", "ETH": "ETH"}


def load_config() -> dict:
    try:
        return {**DEFAULT, **json.loads(CONFIG.read_text(encoding="utf-8"))}
    except FileNotFoundError:
        CONFIG.write_text(json.dumps({"_note": __doc__.splitlines()[0], **DEFAULT},
                                     ensure_ascii=False, indent=1), encoding="utf-8")
        return dict(DEFAULT)
    except (OSError, ValueError):
        logger.exception("stress_budget.config_failed")
        return dict(DEFAULT)


def sigma24(sym: str) -> float | None:
    """Паркинсон σ за последние 24 закрытых часа (доля цены)."""
    from services.grid_model import odds_intraday as oi

    try:
        d = oi.load_hourly(sym, refresh=False).tail(24)
    except Exception:                                   # noqa: BLE001
        logger.exception("stress_budget.sigma_failed sym=%s", sym)
        return None
    if len(d) < 20:
        return None
    var = (d["high"] / d["low"]).map(math.log) ** 2 / (4 * math.log(2))
    return float(math.sqrt(var.sum()))


def stress_move(sigma: float | None, cfg: dict) -> float:
    s = float(cfg["s_floor"])
    if sigma:
        s = max(s, float(cfg["s_mult"]) * sigma * math.sqrt(3))
    return s


@dataclass
class Verdict:
    bot: str
    coin: str
    direction: int          # +1 цена вверх (против шорта), −1 вниз (против лонга)
    move: float             # стресс-ход, доля
    price: float
    stress_px: float
    bag_now: float          # итог позиции сейчас (минус = мешок)
    total_at_stress: float  # итог на стресс-цене (забранное по пути + мешок)
    loss: float             # сколько потеряем от «сейчас» до стресс-цены (>0 — потеря)
    new_orders: int
    equity: float
    status: str
    border_now: float | None
    safe_border: float | None
    note: str = ""

    @property
    def loss_frac(self) -> float:
        return self.loss / self.equity if self.equity > 0 else math.inf


def _directions(book) -> list[int]:
    from services.grid_model import bot_money as bm

    if book.grid_side == 3:
        return [1, -1]
    if book.grid_side == bm.SHORT:
        return [1]
    if book.grid_side == bm.LONG:
        return [-1]
    net = book.net_qty()
    return [1] if net < 0 else [-1] if net > 0 else [1, -1]


def _with_border(book, direction: int, border: float | None):
    return replace(book, border_top=border) if direction > 0 else replace(book, border_bottom=border)


def _new_orders(book, px: float, target: float) -> int:
    """Сколько ордеров сетка доберёт по прямому ходу px → target (то же правило, что в
    bot_money.simulate: шаг от цены, стоп на границе и maxOp)."""
    from services.grid_model import bot_money as bm

    up = target > px
    if not ((up and book.grid_side in (bm.SHORT, 3)) or (not up and book.grid_side in (bm.LONG, 3))):
        return 0
    if book.step <= 0 or book.order_qty <= 0:
        return 0
    n, lv = 0, px
    while len(book.orders) + n < book.max_orders:
        lv = lv * (1 + book.step) if up else lv * (1 - book.step)
        if (lv > target) if up else (lv < target):
            break
        if up and book.border_top and lv > book.border_top:
            break
        if not up and book.border_bottom and lv < book.border_bottom:
            break
        n += 1
    return n


def _loss(book, px: float, target: float) -> tuple[float, float, int]:
    from services.grid_model import bot_money as bm

    now = sum(bm.pnl_usd(o, px, book.inverse) for o in book.orders)
    o = bm.simulate(book, px, target)
    return now - o.total, o.total, _new_orders(book, px, target)


def safe_border(book, px: float, direction: int, target: float, budget: float) -> float | None:
    """Самая дальняя граница, при которой убыток до стресс-цены ≤ бюджета.
    None — бюджет превышен даже без новых ордеров (надо уменьшать позицию)."""
    lo, hi = px, target                   # граница у самой цены → новых ордеров нет
    if _loss(_with_border(book, direction, px * (1 + direction * 1e-6)), px, target)[0] > budget:
        return None
    if _loss(_with_border(book, direction, None), px, target)[0] <= budget:
        return target                     # бюджет держит весь стресс-ход
    for _ in range(40):
        mid = (lo + hi) / 2
        if _loss(_with_border(book, direction, mid), px, target)[0] <= budget:
            lo = mid
        else:
            hi = mid
    return lo


def assess(book, px: float, move: float, equity: float, cfg: dict) -> Verdict:
    from services.grid_model import bot_money as bm

    best = None
    for d in _directions(book):
        target = px * (1 + d * move)
        loss, total, new = _loss(book, px, target)
        if best is None or loss > best[1]:
            best = (d, loss, total, new, target)
    d, loss, total, new, target = best
    bag_now = sum(bm.pnl_usd(o, px, book.inverse) for o in book.orders)
    budget = float(cfg["budget_frac"]) * equity
    status = ("ok" if loss <= budget else
              "warn" if loss <= float(cfg["danger_frac"]) * equity else "danger")
    border_now = book.border_top if d > 0 else book.border_bottom
    sb = safe_border(book, px, d, target, budget) if status != "ok" else None
    note = ""
    if status != "ok" and sb is None:
        # уже набранная позиция сама по себе вылезает за бюджет: убыток БЕЗ новых
        # ордеров почти линеен по позиции → во сколько раз её сократить
        loss0 = _loss(_with_border(book, d, px * (1 + d * 1e-6)), px, target)[0]
        keep = budget / loss0 if loss0 > 0 else 1.0
        net = abs(book.net_qty())
        unit = "$" if book.inverse else book.coin
        stop_adding = "" if new == 0 else "не добирай (граница у текущей цены) и "
        note = (f"граница не поможет: уже набранная позиция без новых ордеров теряет ~${loss0:,.0f}. "
                f"Чтобы уложиться в бюджет, {stop_adding}сократи позицию примерно на {1 - keep:.0%} "
                f"(с {net:g} до ~{net * keep:.3g} {unit})")
    name = (" ".join(book.name.split()[:2]) if book.inverse
            else book.name.split()[0] + (" Auto" if book.grid_side == 3 else
                                         " шорт" if d > 0 else " лонг"))
    if "[вход выкл]" in book.name:
        name += " (вход выкл)"
    return Verdict(name, book.coin, d, move, px, target, bag_now, total, loss, new, equity,
                   status, border_now, sb, note)


def line(v: Verdict) -> str:
    icon = {"ok": "🟢", "warn": "🟡", "danger": "🔴"}[v.status]
    way = "вырастет" if v.direction > 0 else "упадёт"
    s = (f"{icon} {v.bot}: если {v.coin} за 3 дня {way} на {v.move:.0%} (до {v.stress_px:,.0f}), "
         f"бот доберёт {v.new_orders} орд. и потеряет ещё ~${v.loss:,.0f} = {v.loss_frac:.0%} депозита")
    if v.status == "ok":
        return s + " — в пределах бюджета."
    if v.safe_border is not None:
        cur = f"сейчас {v.border_now:,.0f}" if v.border_now else "сейчас нет"
        ok = v.border_now is not None and (
            (v.direction > 0 and v.border_now <= v.safe_border) or
            (v.direction < 0 and v.border_now >= v.safe_border))
        return s + (f". Граница, при которой потеря ≤ бюджета: {v.safe_border:,.0f} ({cur}"
                    + (" ✓)." if ok else " — поставь её)."))
    return s + f". {v.note}."


def card(verdicts: list[Verdict], cfg: dict) -> str:
    if not verdicts:
        return "🛡 Стресс-бюджет: живых ботов с позицией не найдено."
    eq = verdicts[0].equity
    head = (f"🛡 СТРЕСС-БЮДЖЕТ (депозит ${eq:,.0f}, бюджет {cfg['budget_frac']:.0%} = "
            f"${cfg['budget_frac'] * eq:,.0f})")
    tail = ("\nСтресс-ход = три обычных размаха за 3 дня (не меньше 10%). "
            "Проверено на истории: такое правило вдвое–втрое реже доводит сетку до ликвидации. "
            "Бот ботов не трогает.")
    return "\n".join([head, *[line(v) for v in verdicts]]) + tail


def live_books() -> tuple[float, dict]:
    """Как command._live_books, но и боты со статусом «вход отключён» (4): позиция у них
    живая, новых ордеров нет — для них max_orders = уже набранным."""
    from services.grid_model import bot_money as bm
    from services.grid_model.command import _coin_of, _params_for
    from services.order_harvester.loop import _cached_api

    api = _cached_api()
    deposit, books = 0.0, {}
    if api is None:
        return deposit, books
    for b in api.list_bots():
        st = int(b.status)
        if st not in (2, 4) or b.stat is None:
            continue
        deposit = max(deposit, float(b.stat.balance or 0))
        coin = _coin_of(b.name)
        params = _params_for(str(b.id))
        if coin is None or not params:
            continue
        try:
            book = bm.book_from_live(b, params, bm.fetch_orders(api, int(b.id)), coin)
        except Exception:                               # noqa: BLE001
            logger.exception("stress_budget.book_failed bot=%s", b.id)
            continue
        if st == 4:
            book = replace(book, max_orders=len(book.orders), name=book.name + " [вход выкл]")
        books.setdefault(coin, []).append(book)
    return deposit, books


def collect(cfg: dict | None = None, books=None, prices=None, equity: float | None = None,
            sigmas: dict | None = None) -> list[Verdict]:
    cfg = cfg or load_config()
    if books is None:
        dep, books = live_books()
        equity = equity or cfg.get("equity_usd") or dep
    equity = float(equity or cfg.get("equity_usd") or 0)
    if prices is None:
        from services.order_harvester.loop import market_mark
        prices = {c: market_mark(s) for c, s in SYM.items()}
    sigmas = sigmas or {}
    out = []
    for coin, bl in books.items():
        px = prices.get(coin)
        if not px or coin not in SYM:
            continue
        if coin not in sigmas:
            sigmas[coin] = sigma24(SYM[coin])
        move = stress_move(sigmas[coin], cfg)
        for book in bl:
            if not book.orders and book.grid_side not in (1, 2, 3):
                continue
            try:
                out.append(assess(book, px, move, equity, cfg))
            except Exception:                           # noqa: BLE001
                logger.exception("stress_budget.assess_failed bot=%s", book.name)
    out.sort(key=lambda v: -RANK[v.status])
    return out


def _state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def tick(send_fn=None, now: float | None = None, **kw) -> list[str]:
    """Пинг только при УХУДШЕНИИ статуса бота (ok→warn→danger), не чаще cooldown."""
    cfg = load_config()
    if not cfg.get("enabled"):
        return []
    now = now or time.time()
    verdicts = collect(cfg, **kw)
    st = _state()
    sent = []
    for v in verdicts:
        key = v.bot
        prev = st.get(key, {})
        worse = RANK[v.status] > RANK.get(prev.get("status", "ok"), 0)
        last = prev.get("ts")
        cooled = last is None or now - float(last) >= float(cfg["cooldown_hours"]) * 3600
        loud = RANK[v.status] >= RANK.get(str(cfg.get("ping_min_status", "danger")), 2)
        if worse and cooled and loud:
            text = "🛡 " + line(v)
            if send_fn:
                try:
                    send_fn(text)
                except Exception:                       # noqa: BLE001
                    logger.exception("stress_budget.send_failed")
            sent.append(text)
            st[key] = {"status": v.status, "ts": now}
        elif RANK[v.status] != RANK.get(prev.get("status", "ok"), 0):
            st[key] = {"status": v.status, "ts": prev.get("ts")}        # без пинга — тихо
        rec = {"ts": datetime.fromtimestamp(now, timezone.utc).isoformat(timespec="seconds"),
               "bot": v.bot, "status": v.status, "move": round(v.move, 4), "loss": round(v.loss, 2),
               "loss_frac": round(v.loss_frac, 4), "new_orders": v.new_orders,
               "safe_border": v.safe_border, "border_now": v.border_now, "price": v.price}
        with JOURNAL.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    STATE.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    return sent


def build_card() -> str:
    cfg = load_config()
    return card(collect(cfg), cfg)


async def stress_budget_loop(stop_event=None, send_fn=None) -> None:
    cfg = load_config()
    poll = int(cfg.get("poll_sec", 1800))
    logger.info("stress_budget.start poll=%ds budget=%.2f", poll, float(cfg["budget_frac"]))
    while True:
        if stop_event is not None and stop_event.is_set():
            return
        try:
            sent = await asyncio.to_thread(tick, send_fn)
            if sent:
                logger.info("stress_budget.sent n=%d", len(sent))
        except Exception:                               # noqa: BLE001
            logger.exception("stress_budget.tick_failed")
        try:
            if stop_event is not None:
                await asyncio.wait_for(stop_event.wait(), poll)
                return
            await asyncio.sleep(poll)
        except asyncio.TimeoutError:
            continue
