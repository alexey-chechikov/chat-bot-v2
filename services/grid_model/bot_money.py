"""Деньги каждого бота на уровнях цены + шанс туда дойти.

Считается по РЕАЛЬНЫМ открытым ордерам GinArea (/bots/{id}/orders): у каждого
ордера есть цена исполнения, объём и свой тейк. Средняя из stat.averagePrice
для этого НЕ годится — 30.09.2026 у BTC-шорта она была 84 357 при средней
открытых ордеров 82 470, у ETH Auto 2 713 при шортах по 2 595 и лонгах по
2 691. На ней я насчитал «выход по средней ETH 2 659 → +$46, 65% за сутки»,
а настоящий выход шортов — 2 543 (stat.extension.taps).

Модель пути — прямой ход от текущей цены до уровня:
- ордер закрывается, когда цена проходит его тейк (выход по средней ВЫКЛ);
  при выходе по средней ВКЛ сторона закрывается целиком на tapb/taps;
- новые ордера открываются с шагом сетки против позиции: шорт-сетка — на
  росте, лонг-сетка — на падении, Auto — шорты на росте и лонги на падении;
  граница и maxOp останавливают набор;
- по ходу в свою сторону новых ордеров нет (dynamic-вход срабатывает на
  откате, а прямой ход откатов не имеет).
Откаты по дороге добавляют только оборот, поэтому доход здесь — нижняя
оценка, мешок — верхняя. Комиссии не учтены (0.05% на сторону).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

LONG, SHORT = 1, 2


@dataclass
class Order:
    side: int            # 1 лонг, 2 шорт
    qty: float           # монета (линейный) или USD-контракты (инверсный)
    entry: float
    take: float | None


@dataclass
class Book:
    name: str
    coin: str
    inverse: bool
    grid_side: int       # 1 лонг-сетка, 2 шорт-сетка, 3 Auto
    step: float          # доля, 0.006 = 0.6%
    target: float        # доля
    obap: bool
    order_qty: float
    max_orders: int
    border_top: float | None
    border_bottom: float | None
    orders: list[Order] = field(default_factory=list)
    tapb: float | None = None      # выход лонгов по средней
    taps: float | None = None      # выход шортов по средней
    bag_usd: float | None = None   # мешок по GinArea: currentProfit − profit

    def side_avg(self, side: int) -> float | None:
        lst = [o for o in self.orders if o.side == side]
        q = sum(o.qty for o in lst)
        if q <= 0:
            return None
        if self.inverse:                       # средняя инверсного — гармоническая
            return q / sum(o.qty / o.entry for o in lst)
        return sum(o.qty * o.entry for o in lst) / q

    def net_qty(self) -> float:
        return sum(o.qty if o.side == LONG else -o.qty for o in self.orders)


def pnl_usd(o: Order, price: float, inverse: bool) -> float:
    d = 1.0 if o.side == LONG else -1.0
    if inverse:
        return o.qty * (1.0 / o.entry - 1.0 / price) * d * price
    return (price - o.entry) * o.qty * d


@dataclass
class Outcome:
    price: float
    realized: float
    unrealized: float
    net_qty: float
    n_open: int
    note: str = ""

    @property
    def total(self) -> float:
        return self.realized + self.unrealized


def simulate(book: Book, px: float, target_px: float) -> Outcome:
    """Прямой ход px → target_px: закрытия по тейкам/средней и набор по шагу."""
    up = target_px > px
    orders = [Order(o.side, o.qty, o.entry, o.take) for o in book.orders]
    realized, notes = 0.0, []

    # 1) набор против позиции с шагом сетки
    opens_side = None
    if up and book.grid_side in (SHORT, 3):
        opens_side = SHORT
    elif not up and book.grid_side in (LONG, 3):
        opens_side = LONG
    if opens_side is not None and book.step > 0 and book.order_qty > 0:
        lv, capped = px, False
        while len(orders) < book.max_orders:
            lv = lv * (1 + book.step) if up else lv * (1 - book.step)
            if (lv > target_px) if up else (lv < target_px):
                break
            if up and book.border_top and lv > book.border_top:
                capped = True
                break
            if not up and book.border_bottom and lv < book.border_bottom:
                capped = True
                break
            orders.append(Order(opens_side, book.order_qty, lv, None))
        if capped:
            notes.append("граница: набор стоп")
        elif len(orders) >= book.max_orders:
            notes.append("maxOp: набор стоп")

    # 2) закрытия в сторону хода
    closes_side = LONG if up else SHORT
    if book.obap:
        exit_px = book.tapb if up else book.taps
        if exit_px and ((target_px >= exit_px) if up else (target_px <= exit_px)):
            gone = [o for o in orders if o.side == closes_side]
            realized += sum(pnl_usd(o, exit_px, book.inverse) for o in gone)
            orders = [o for o in orders if o.side != closes_side]
            notes.append(f"{'лонги' if up else 'шорты'} закрыты по средней")
    else:
        keep = []
        for o in orders:
            hit = (o.side == closes_side and o.take is not None
                   and ((target_px >= o.take) if up else (target_px <= o.take)))
            if hit:
                realized += pnl_usd(o, o.take, book.inverse)
            else:
                keep.append(o)
        if len(keep) < len(orders):
            notes.append(f"закрыто {len(orders) - len(keep)}")
        orders = keep

    unreal = sum(pnl_usd(o, target_px, book.inverse) for o in orders)
    net = sum(o.qty if o.side == LONG else -o.qty for o in orders)
    return Outcome(target_px, realized, unreal, net, len(orders), ", ".join(notes))


def key_levels(book: Book, px: float) -> list[tuple[str, float]]:
    """Уровни, которые имеют смысл для этого бота: тейки, выходы, граница, ±%."""
    out: list[tuple[str, float]] = []
    if book.obap:
        if book.taps and book.taps < px:
            out.append(("выход шортов по средней", book.taps))
        if book.tapb and book.tapb > px:
            out.append(("выход лонгов по средней", book.tapb))
    else:
        for side, better in ((SHORT, lambda t: t < px), (LONG, lambda t: t > px)):
            takes = sorted({o.take for o in book.orders
                            if o.side == side and o.take and better(o.take)},
                           key=lambda t: abs(t - px))
            if takes:
                out.append(("первый тейк", takes[0]))
                if len(takes) > 1:
                    out.append(("все тейки", takes[-1]))
    net = book.net_qty()
    against_up = net < 0 or (net == 0 and book.grid_side == SHORT)
    border = book.border_top if against_up else book.border_bottom
    if border and abs(border / px - 1) <= 0.15:
        out.append(("граница", float(border)))
    sign = 1 if against_up else -1
    for pct in (0.01, 0.03, 0.05, 0.10):
        out.append((f"{sign * pct:+.0%}", px * (1 + sign * pct)))
    out.sort(key=lambda x: -x[1])
    return out


def _p(p: float) -> str:
    return "<1%" if p < 0.01 else ">99%" if p > 0.99 else f"{p:.0%}"


def block(book: Book, px: float, touch) -> str:
    """touch(pct, horizon) → вероятность; horizon ∈ {'4ч','сутки','7д'}."""
    net = book.net_qty()
    unit = "$" if book.inverse else book.coin
    parts = []
    for side, nm in ((SHORT, "шорты"), (LONG, "лонги")):
        a = book.side_avg(side)
        if a:
            q = sum(o.qty for o in book.orders if o.side == side)
            parts.append(f"{nm} {q:g}{unit} по {a:,.0f}")
    bag = book.bag_usd
    if bag is None:
        bag = sum(pnl_usd(o, px, book.inverse) for o in book.orders)
    head = f"💰 {book.name}: {'; '.join(parts) or 'позиции нет'} · мешок {bag:+,.0f}$"
    lines = [head]
    for label, lvl in key_levels(book, px):
        pct = lvl / px - 1
        o = simulate(book, px, lvl)
        money = f"{o.total:+,.0f}$"
        if o.realized:
            money += f" (забрал {o.realized:+,.0f})"
        pos = f" поз {o.net_qty:+g}" if abs(o.net_qty - net) > 1e-9 else ""
        extra = f" · {o.note}" if o.note and "закрыто" not in o.note else ""
        probs = " ".join(_p(touch(pct, h)) for h in ("4ч", "сутки", "7д"))
        where = (f"{label} {lvl:,.0f}" if label[0] in "+-"
                 else f"{label} {lvl:,.0f} ({pct:+.1%})")
        lines.append(f"  {where}: {money}{pos}{extra} | {probs}")
    lines.append("  (шансы: 4ч · сутки · 7д; итог = забранное + мешок на уровне)")
    return "\n".join(lines)


def book_from_live(bot, params: dict, orders_raw: list[dict], coin: str) -> Book:
    """Собрать книгу из живых данных GinArea: bot из list_bots(), params из
    params.csv, orders_raw из get_orders(only_opened=True)."""
    from services.order_harvester.loop import order_fields

    s = bot.stat
    ext = s.extension
    bal = float(s.balance or 0)
    inverse = abs(bal) < 5
    gap = params.get("gap") or {}
    q = params.get("q") or {}
    border = params.get("border") or {}
    orders = []
    for raw in orders_raw:
        f = order_fields(raw)
        if not f["opened"] or f["side"] not in (LONG, SHORT) or not f["price_in"]:
            continue
        orders.append(Order(int(f["side"]), float(f["qty"]), float(f["price_in"]),
                            f["trigger_price"]))
    bag = float(s.currentProfit or 0) - float(s.profit or 0)
    if inverse:
        bag = None                     # в монете; посчитаем по ордерам в долларах
    return Book(
        name=bot.name, coin=coin, inverse=inverse,
        grid_side=int(params.get("side") or 0),
        step=float(params.get("gs") or 0) / 100,
        target=float(gap.get("tog") or 0) / 100,
        obap=bool(params.get("obap")),
        order_qty=float(q.get("minQ") or 0),
        max_orders=int(params.get("maxOp") or 200),
        border_top=float(border["top"]) if border.get("top") else None,
        border_bottom=float(border["bottom"]) if border.get("bottom") else None,
        orders=orders,
        tapb=float(ext.tapb) if ext.tapb else None,
        taps=float(ext.taps) if ext.taps else None,
        bag_usd=bag,
    )


def fetch_orders(api, bot_id: int, page_size: int = 100) -> list[dict]:
    """Все открытые ордера бота: пагинация 0-based (см. BotsAPI.get_orders)."""
    out, page = [], 0
    while True:
        data = api.get_orders(int(bot_id), page_size=page_size, page_number=page,
                              only_opened=True)
        chunk = data.get("orders") or []
        out.extend(chunk)
        total = int(data.get("totalCount") or 0)
        if not chunk or len(out) >= total or page >= 20:
            return out
        page += 1
