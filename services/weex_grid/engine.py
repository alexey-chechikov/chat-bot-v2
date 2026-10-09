"""Движок сетки WEEX: один проход tick() = сверка ордеров с биржей + решения + сохранение.

Состояние в state/weex_grid_state.json сохраняется после каждого действия, чтобы перезапуск
не плодил дубли. Журнал исполнений — state/weex_grid_journal.jsonl (цена, объём, комиссия,
мейкер/тейкер) — по нему меряем реальную цену круга и кэшбэк.
"""
from __future__ import annotations

import json
import logging
import math
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "state" / "weex_grid_config.json"
STATE = ROOT / "state" / "weex_grid_state.json"
JOURNAL = ROOT / "state" / "weex_grid_journal.jsonl"
PREFIX = "b7g"
DIR = {"LONG": 1, "SHORT": -1}
LIVE = {"NEW", "PENDING", "CANCELING", "UNTRIGGERED", "UNACTIVATED"}   # ордер ещё может исполниться
OPEN_SIDE = {"LONG": "BUY", "SHORT": "SELL"}
CLOSE_SIDE = {"LONG": "SELL", "SHORT": "BUY"}
DEFAULT = {
    "enabled": False,            # пока false — служба ничего не делает
    "dry_run": True,             # true — ордера не отправляются, исполнения считаются по живым ценам
    "symbol": "BTCUSDT",
    "sides": ["LONG", "SHORT"],
    "step_pct": 0.2,
    "target_pct": 0.3,
    "order_qty": "0.0001",
    "price_tick": 0.1,
    "max_lots_per_side": 50,
    "max_notional_usd": 1000.0,  # на сторону
    "daily_loss_stop_usd": 30.0,
    "stress_floor": 0.10,
    "stress_mult": 3.0,
    "stress_budget_frac": 0.25,
    "trail_min_move_pct": 0.05,
    "poll_sec": 10,
    "qty_step": 0.0001,          # шаг объёма контракта (BTC 0.0001, ETH 0.001)
    "qty_max": 0.01,             # верхняя граница ордера для /weex set (защита от опечатки)
}
# Сетки по монетам. BTC — исходные файлы (weex_grid_config.json …), остальные — weex_grid_<имя>_*.
# Новая сетка создаётся ВЫКЛЮЧЕННОЙ и ХОЛОСТОЙ: живой режим включает только оператор (/weex eth live).
GRIDS = ("BTC", "ETH", "XAU")
TEMPLATES = {
    # 09.10 развёртка 10 мес XAUUSDT (лонг+шорт, $100, потолок $4 000): шаг 0.75 — обе половины окна
    # в плюсе (+$293 / +$116), итог +$349, худший мешок −$684; цель 0.3…1.0 плоско (+349…372),
    # 0.3 даёт оборот ×2.5. Соседи по шагу 0.5 и 1.0 тоже в плюсе. research/weex/sweep_XAUUSDT_*.jsonl
    "XAU": {"symbol": "XAUUSDT", "sides": ["LONG", "SHORT"], "price_tick": 0.01, "qty_step": 0.001,
            "qty_max": 1.0, "order_qty": "0.023", "step_pct": 0.75, "target_pct": 0.3, "max_lots_per_side": 50,
            "max_notional_usd": 4000.0, "daily_loss_stop_usd": 0.0, "stress_budget_frac": 0.0},
    "ETH": {"symbol": "ETHUSDT", "sides": ["SHORT"], "price_tick": 0.01, "qty_step": 0.001, "qty_max": 0.5,
            # 09.10 развёртка 10 мес (research/weex/sweep_ETHUSDT_short_*.jsonl): шорт ETH в минусе во
            # ВСЕХ 30 ячейках, свежая половина −$979…−1 621 на ордер $100; наименее плохая 0.5/1.5 (−$88)
            "order_qty": "0.001", "step_pct": 0.5, "target_pct": 1.5, "max_lots_per_side": 50,
            "max_notional_usd": 1000.0, "daily_loss_stop_usd": 0.0, "stress_budget_frac": 0.0},
}


def grid_files(name: str = "BTC") -> tuple[Path, Path, Path]:
    """(конфиг, состояние, журнал) сетки по имени."""
    if name == "BTC":
        return CONFIG, STATE, JOURNAL
    base = ROOT / "state" / f"weex_grid_{name.lower()}"
    return (base.with_name(base.name + "_config.json"), base.with_name(base.name + "_state.json"),
            base.with_name(base.name + "_journal.jsonl"))


def load_config(path: Path = CONFIG, template: dict | None = None) -> dict:
    base = {**DEFAULT, **(template or {})}
    try:
        return {**base, **json.loads(path.read_text(encoding="utf-8"))}
    except FileNotFoundError:
        path.write_text(json.dumps({"_note": "сетка WEEX; enabled/dry_run меняет только оператор",
                                    **base}, ensure_ascii=False, indent=1), encoding="utf-8")
        return dict(base)
    except (OSError, ValueError):
        logger.exception("weex_grid.config_failed")
        return {**DEFAULT, "enabled": False}


def save_config(cfg: dict, path: Path = CONFIG) -> None:
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")


def round_tick(px: float, tick: float, up: bool) -> float:
    n = px / tick
    n = math.ceil(n - 1e-9) if up else math.floor(n + 1e-9)
    return round(n * tick, 8)


def fmt_px(px: float, tick: float) -> str:
    dec = max(0, -int(math.floor(math.log10(tick)))) if tick < 1 else 0
    return f"{px:.{dec}f}"


def new_side_state() -> dict:
    return {"ref": None, "entry": None, "lots": [], "realized": 0.0, "fees": 0.0,
            "n_entries": 0, "n_tps": 0, "seq": 0, "turnover": 0.0, "pending": None}


PENDING_TTL = 120.0      # с: ордер с потерянным ответом не нашёлся ни в открытых, ни в истории → не дошёл


class Grid:
    def __init__(self, client, cfg: dict | None = None, state_path: Path = STATE,
                 journal_path: Path = JOURNAL, sigma_fn=None, send_fn=None, now_fn=time.time):
        self.c = client
        self.cfg = cfg or load_config()
        self.state_path = state_path
        self.journal_path = journal_path
        self.sigma_fn = sigma_fn
        self.send = send_fn
        self.now = now_fn
        self.st = self._load()
        self._equity = None
        self._equity_ts = 0.0

    # ---------- состояние
    def _load(self) -> dict:
        try:
            st = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            st = {}
        for s in ("LONG", "SHORT"):
            st.setdefault(s, new_side_state())
        st.setdefault("halted", False)
        st.setdefault("halt_reason", "")
        st.setdefault("day", None)
        st.setdefault("day_start_pnl", 0.0)
        return st

    def save(self) -> None:
        self.state_path.write_text(json.dumps(self.st, ensure_ascii=False, indent=1), encoding="utf-8")

    def _journal(self, rec: dict) -> None:
        rec = {"ts": datetime.fromtimestamp(self.now(), timezone.utc).isoformat(timespec="seconds"),
               "dry": bool(self.cfg["dry_run"]), **rec}
        with self.journal_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def _notify(self, text: str) -> None:
        if self.send:
            try:
                self.send(text)
            except Exception:                                   # noqa: BLE001
                logger.exception("weex_grid.send_failed")

    # ---------- вспомогательное
    def _cid(self, side: str, kind: str) -> str:
        """b7g + буква символа + сторона + вид + время + счётчик (уникально между сетками)."""
        s = self.st[side]
        s["seq"] += 1
        return f"{PREFIX}{self.cfg['symbol'][0]}{side[0]}{kind}{int(self.now())}{s['seq']}"

    def _qty_str(self, q: float) -> str:
        step = float(self.cfg.get("qty_step") or 0.0001)
        dec = max(0, -int(math.floor(math.log10(step) + 1e-9)))
        return f"{round(q / step) * step:.{dec}f}"

    def _tiny(self) -> float:
        return float(self.cfg.get("qty_step") or 0.0001) / 2

    def _fee_of(self, order_id) -> tuple[float, bool | None]:
        try:
            trades = self.c.user_trades(self.cfg["symbol"], order_id) or []
        except Exception:                                       # noqa: BLE001
            logger.exception("weex_grid.trades_failed")
            return 0.0, None
        fee = sum(float(t.get("commission") or 0) for t in trades)
        makers = {bool(t.get("maker")) for t in trades}
        return fee, (makers.pop() if len(makers) == 1 else None)

    def equity(self) -> float:
        if self._equity is None or self.now() - self._equity_ts > 60:
            try:
                bal = self.c.futures_balance()
                usdt = next((b for b in bal if b.get("asset") == "USDT"), None)
                self._equity = float(usdt["balance"]) + float(usdt.get("unrealizePnl") or 0) if usdt else 0.0
                self._equity_ts = self.now()
            except Exception:                                   # noqa: BLE001
                logger.exception("weex_grid.balance_failed")
                self._equity = self._equity or 0.0
        return self._equity

    def unrealized(self, mid: float) -> float:
        return sum(DIR[s] * float(l["qty"]) * (mid - l["entry"]) for s in ("LONG", "SHORT") for l in self.st[s]["lots"])

    def bot_pnl(self, mid: float) -> float:
        return (sum(self.st[s]["realized"] - self.st[s]["fees"] for s in ("LONG", "SHORT"))
                + self.unrealized(mid))

    def may_add(self, side: str, price: float, mid: float) -> tuple[bool, str]:
        cfg, s = self.cfg, self.st[side]
        if self.st["halted"]:
            return False, "стоп: " + self.st["halt_reason"]
        if len(s["lots"]) >= int(cfg["max_lots_per_side"]):
            return False, "достигнут максимум ордеров"
        q = float(cfg["order_qty"])
        # потолок — по большему из себестоимости и текущей стоимости (10.10, разбор GPT: по одной
        # текущей стоимости на падении цены докупали сверх потолка по себестоимости)
        cost = sum(float(l["qty"]) * l["entry"] for l in s["lots"])
        value = sum(float(l["qty"]) for l in s["lots"]) * mid
        notional = max(cost, value) + q * price
        if notional > float(cfg["max_notional_usd"]):
            return False, "достигнут потолок позиции"
        if float(cfg["stress_budget_frac"]) <= 0:          # 0 = стресс-бюджет выключен оператором
            return True, ""
        sigma = self.sigma_fn() if self.sigma_fn else None
        S = max(float(cfg["stress_floor"]), float(cfg["stress_mult"]) * sigma * math.sqrt(3)) if sigma else float(cfg["stress_floor"])
        d = DIR[side]
        ps = mid * (1 - d * S)
        loss = sum(float(l["qty"]) * (l["entry"] - ps) * d for l in s["lots"]) + q * (price - ps) * d
        eq = self.equity()
        if eq > 0 and loss > float(cfg["stress_budget_frac"]) * eq:
            return False, f"стресс-бюджет: обвал {S:.0%} съест ${loss:,.0f} > {cfg['stress_budget_frac']:.0%} баланса"
        return True, ""

    # ---------- ордера
    def _place(self, side: str, kind: str, price: float, reduce: bool, bid: float, ask: float,
               qty: str | None = None, lot: dict | None = None):
        """kind: 'e' вход, 't' тейк. POST_ONLY: цену не пускаем пересечь стакан.
        qty: у тейка — объём СВОЕГО лота (09.10: после смены размера тейк ставился новым
        объёмом 0.0012 на лот 0.0001 → биржа отклоняла, проход падал целиком).
        Намерение пишется на диск ДО отправки (pending): если ответ потерян (сеть/таймаут),
        следующий проход ищет ордер по clientOrderId и не ставит второй (10.10, разбор GPT)."""
        cfg, s = self.cfg, self.st[side]
        tick = float(cfg["price_tick"])
        buy = (OPEN_SIDE[side] if kind == "e" else CLOSE_SIDE[side]) == "BUY"
        if buy and price >= ask:
            price = bid
        if not buy and price <= bid:
            price = ask
        price = round_tick(price, tick, up=not buy)
        cid = self._cid(side, kind)
        s["pending"] = {"cid": cid, "kind": kind, "price": price, "lot_t": lot["t"] if lot else None,
                        "t": self.now()}
        self.save()
        try:
            r = self.c.place_limit(cfg["symbol"], "BUY" if buy else "SELL", side, qty or cfg["order_qty"],
                                   fmt_px(price, tick), cid, reduce_only=reduce, post_only=True)
        except Exception as exc:                                # noqa: BLE001 — один ордер не валит проход
            # исход неизвестен: ордер мог дойти — pending остаётся до выяснения
            logger.warning("weex_grid.place_failed side=%s kind=%s price=%s err=%s", side, kind, price, exc)
            return None
        s["pending"] = None                    # ответ получен — исход известен
        if not r or not r.get("success", False) or not r.get("orderId"):
            logger.warning("weex_grid.place_rejected side=%s kind=%s price=%s resp=%s", side, kind, price, r)
            self.save()
            return None
        return {"id": str(r["orderId"]), "cid": cid, "price": price}

    def _resolve_pending(self, side: str) -> bool:
        """Ордер с потерянным ответом: найти по clientOrderId в открытых или в истории и привязать.
        False — ещё не выяснено (на этой стороне новых ордеров не ставим)."""
        s = self.st[side]
        p = s.get("pending")
        if not p:
            return True
        o = next((x for x in getattr(self, "open", {}).values() if x.get("clientOrderId") == p["cid"]), None)
        if o is None:
            try:
                hist = self.c.order_history(self.cfg["symbol"]) or []
            except Exception:                                   # noqa: BLE001
                logger.exception("weex_grid.history_failed")
                return False
            o = next((x for x in hist if x.get("clientOrderId") == p["cid"]), None)
        if o is None:
            if self.now() - p["t"] < PENDING_TTL:
                return False
            logger.warning("weex_grid.pending_not_found side=%s cid=%s — ордер не дошёл", side, p["cid"])
            s["pending"] = None
            self.save()
            return True
        order = {"id": str(o["orderId"]), "cid": p["cid"], "price": p["price"]}
        logger.warning("weex_grid.pending_adopted side=%s kind=%s cid=%s status=%s", side, p["kind"], p["cid"],
                       o.get("status"))
        if p["kind"] == "e":
            if s["entry"] is None:
                s["entry"] = order
            else:                                               # не должно случиться: вход уже есть
                self._cancel_and_take(side, order)
        else:
            lot = next((l for l in s["lots"] if l["t"] == p["lot_t"]), None)
            if lot is not None and lot.get("tp_order") is None:
                lot["tp_order"] = order
            elif o.get("status") in LIVE:
                self._cancel(order)
        s["pending"] = None
        self.save()
        return True

    def _cancel_and_take(self, side: str, order: dict) -> None:
        """Снять лишний входной ордер; исполненную часть записать лотом."""
        self._cancel(order)
        try:
            info = self.c.order_info(order["id"])
        except Exception:                                       # noqa: BLE001
            logger.exception("weex_grid.info_after_cancel_failed id=%s", order["id"])
            return
        self._take_entry_fill(side, order, info)

    def _orphans(self) -> None:
        """Свои (b7g) ордера этого символа, о которых учёт не знает (потерянный ответ без pending,
        откат файла состояния): входы снять и исполненное записать лотом, тейки — снять."""
        known = set()
        for side in ("LONG", "SHORT"):
            s = self.st[side]
            if s.get("entry"):
                known.add(s["entry"]["id"])
            known.update(l["tp_order"]["id"] for l in s["lots"] if l.get("tp_order"))
        pend = {self.st[sd]["pending"]["cid"] for sd in ("LONG", "SHORT") if self.st[sd].get("pending")}
        for oid, o in list(self.open.items()):
            if oid in known or o.get("clientOrderId") in pend:
                continue
            side = o.get("positionSide")
            logger.warning("weex_grid.orphan_order id=%s cid=%s side=%s reduce=%s", oid, o.get("clientOrderId"),
                           side, o.get("reduceOnly"))
            order = {"id": oid, "cid": o.get("clientOrderId"), "price": float(o.get("price") or 0)}
            if side in DIR and not o.get("reduceOnly"):
                self._cancel_and_take(side, order)
            else:
                self._cancel(order)
            self.open.pop(oid, None)
        self.save()

    def _cancel(self, order: dict) -> None:
        try:
            self.c.cancel(order["id"])
        except Exception:                                       # noqa: BLE001
            logger.exception("weex_grid.cancel_failed id=%s", order.get("id"))

    # ---------- один проход
    def tick(self) -> None:
        cfg = self.cfg
        sym = cfg["symbol"]
        bid, ask = self.c.book(sym)
        mid = (bid + ask) / 2
        self.open = {str(o["orderId"]): o for o in self.c.open_orders(sym)
                     if str(o.get("clientOrderId", "")).startswith(PREFIX)}
        self._orphans()
        open_ids = set(self.open)
        self._day_roll(mid)
        for side in cfg["sides"]:
            self._side(side, bid, ask, mid, open_ids, enabled=bool(cfg["enabled"]))
        self._risk(mid)
        self.save()

    def _day_roll(self, mid: float) -> None:
        day = datetime.fromtimestamp(self.now(), timezone.utc).strftime("%Y-%m-%d")
        if self.st["day"] != day:
            self.st["day"] = day
            self.st["day_start_pnl"] = self.bot_pnl(mid)

    def _risk(self, mid: float) -> None:
        if self.st["halted"] or float(self.cfg["daily_loss_stop_usd"]) <= 0:   # 0 = стоп дня выключен
            return
        today = self.bot_pnl(mid) - self.st["day_start_pnl"]
        if today < -float(self.cfg["daily_loss_stop_usd"]):
            self.st["halted"] = True
            self.st["halt_reason"] = f"убыток за день ${today:,.2f}"
            for side in ("LONG", "SHORT"):
                self._drop_entry(side)
            self._notify(f"🛑 Сетка WEEX остановила новые входы: убыток за день ${today:,.2f}. "
                         f"Тейки стоят, позиция закрывается сама. Запуск — /weex start.")

    def _take_entry_fill(self, side: str, e: dict, info: dict) -> bool:
        """Записать НОВУЮ исполненную часть входного ордера как лот. executedQty у биржи
        накопительный — пишем только прирост против уже записанного (e['filled']), цена прироста —
        из прироста стоимости, комиссия — прирост комиссии ордера. Повтор того же снимка = 0."""
        cfg, s, d = self.cfg, self.st[side], DIR[side]
        exq = float(info.get("executedQty") or 0)
        done = float(e.get("filled") or 0)
        dq = exq - done
        if dq <= self._tiny():
            return False
        avg = float(info.get("avgPrice") or 0) or e["price"]
        val = avg * exq
        px = (val - float(e.get("filled_val") or 0)) / dq
        fee_all, maker = self._fee_of(e["id"])
        fee = max(fee_all - float(e.get("fee_done") or 0), 0.0)
        e["filled"], e["filled_val"], e["fee_done"] = exq, val, fee_all
        lot = {"entry": px, "qty": self._qty_str(dq),
               "tp": round_tick(px * (1 + d * float(cfg["target_pct"]) / 100), float(cfg["price_tick"]), up=d > 0),
               "tp_order": None, "t": self.now()}
        while any(l["t"] == lot["t"] for l in s["lots"]):  # t — ключ лота для pending тейка
            lot["t"] += 0.001
        s["lots"].append(lot)
        s["ref"] = px
        s["fees"] += fee
        s["turnover"] += dq * px
        s["n_entries"] += 1
        self._journal({"side": side, "kind": "вход" if dq >= exq - self._tiny() else "вход (часть)", "price": px,
                       "qty": lot["qty"], "fee": fee, "maker": maker})
        return True

    def _take_tp_fill(self, side: str, lot: dict, o: dict, info: dict) -> bool:
        """Исполненная часть тейка (целиком или частично): прибыль по исполненному объёму, остаток
        лота уменьшается. True — лот закрыт полностью и удалён."""
        s, d = self.st[side], DIR[side]
        exq = float(info.get("executedQty") or 0)
        if exq <= self._tiny():
            return False
        px = float(info.get("avgPrice") or 0) or o["price"]
        fee, maker = self._fee_of(o["id"])
        pnl = d * exq * (px - lot["entry"])
        s["realized"] += pnl
        s["fees"] += fee
        s["turnover"] += exq * px
        rest = float(lot["qty"]) - exq
        full = rest <= self._tiny()
        self._journal({"side": side, "kind": "тейк" if full else "тейк (часть)", "price": px, "qty": str(exq),
                       "fee": fee, "maker": maker, "pnl": pnl, "entry": lot["entry"]})
        if full:
            s["n_tps"] += 1
            s["lots"].remove(lot)
        else:
            lot["qty"] = self._qty_str(rest)
            lot["tp_order"] = None
        self.save()
        return full

    def _drop_entry(self, side: str) -> bool:
        """Снять входной ордер; если он успел исполниться — записать лот. True = был лот."""
        s = self.st[side]
        e = s["entry"]
        if not e:
            return False
        self._cancel(e)
        try:
            info = self.c.order_info(e["id"])
        except Exception:                                       # noqa: BLE001
            logger.exception("weex_grid.info_after_cancel_failed id=%s", e["id"])
            return False                      # оставим отслеживание — разберёмся на следующем проходе
        got = self._take_entry_fill(side, e, info)
        if info.get("status") not in LIVE:    # отмена подтверждена — забываем; иначе ждём (исполнения
            s["entry"] = None                 # во время отмены запишутся на следующем проходе)
        self.save()
        return got

    def _reconcile_side(self, side: str, mid: float) -> None:
        """Тейк не ставится → сверить с позицией биржи. Если лотов в учёте больше, чем позиция
        стороны на бирже (лот уже закрыт чужим/урезанным ордером), снять из учёта лоты без
        тейка, начиная с последних. Позиция может включать ручные сделки оператора — тогда
        она больше суммы лотов и ничего не снимается (консервативно).
        Снятый лот НЕ исчезает бесплатно (10.10, разбор GPT): результат пишется в закрытое по
        текущей цене как оценка внешнего закрытия, оператору — сообщение."""
        s, d = self.st[side], DIR[side]
        try:
            pos = self.c.futures_positions() or []
        except Exception:                                       # noqa: BLE001
            logger.exception("weex_grid.positions_failed")
            return
        size = sum(float(p.get("size") or 0) for p in pos
                   if p.get("symbol") == self.cfg["symbol"] and p.get("side") == side)
        held = sum(float(l["qty"]) for l in s["lots"])
        for lot in sorted([l for l in s["lots"] if l.get("tp_order") is None], key=lambda l: -l["t"]):
            if held <= size + 1e-12:
                break
            s["lots"].remove(lot)
            held -= float(lot["qty"])
            pnl = d * float(lot["qty"]) * (mid - lot["entry"])
            s["realized"] += pnl
            logger.warning("weex_grid.phantom_lot_dropped side=%s entry=%s qty=%s exch_size=%s est_pnl=%.4f",
                           side, lot["entry"], lot["qty"], size, pnl)
            self._journal({"side": side, "kind": "внешнее закрытие (оценка по текущей цене)", "price": mid,
                           "qty": lot["qty"], "entry": lot["entry"], "pnl": pnl})
            self._notify(f"⚠️ Сетка WEEX {self.cfg['symbol']}: на бирже нет позиции под лот {side} "
                         f"{lot['qty']} по {lot['entry']:,.2f} — закрыт не сеткой (вручную?). "
                         f"Записал по текущей цене {mid:,.2f}: ${pnl:+.2f}.")

    def _side(self, side: str, bid: float, ask: float, mid: float, open_ids: set, enabled: bool) -> None:
        cfg, s, d = self.cfg, self.st[side], DIR[side]
        # 0) ордер с потерянным ответом — сначала выяснить, иначе на этой стороне ничего не ставим
        if not self._resolve_pending(side):
            return
        # 1) входной ордер: исполненная часть записывается сразу (и пока ордер ещё висит — чтобы
        # она получила тейк); сам ордер забываем только в конечном статусе.
        e = s["entry"]
        if e and e["id"] in open_ids:
            live = getattr(self, "open", {}).get(e["id"])
            if live and self._take_entry_fill(side, e, live):
                self.save()
        elif e:
            info = self.c.order_info(e["id"])
            if info.get("status") not in LIVE:
                self._take_entry_fill(side, e, info)
                s["entry"] = None
                self.save()
            elif self._take_entry_fill(side, e, info):
                self.save()
        # 2) тейки
        # 2а) тейк на бирже с объёмом не своего лота (09.10: биржа урезала reduceOnly 0.0012 до
        # позиции 0.0002 → один тейк на два лота, второй отклонялся) — снять, поставим заново.
        # Исполненная до снятия часть записывается (10.10).
        for lot in list(s["lots"]):
            o = lot.get("tp_order")
            live = getattr(self, "open", {}).get(o["id"]) if o else None
            if live and abs(float(live.get("origQty") or 0) - float(lot["qty"])) > 1e-12:
                logger.warning("weex_grid.tp_qty_mismatch side=%s lot=%s order=%s", side, lot["qty"], live.get("origQty"))
                self._cancel(o)
                open_ids.discard(o["id"])
                try:
                    info = self.c.order_info(o["id"])
                except Exception:                               # noqa: BLE001
                    logger.exception("weex_grid.info_after_cancel_failed id=%s", o["id"])
                    continue                  # tp_order остаётся — разберёмся на следующем проходе
                if info.get("status") in LIVE:
                    continue                  # отмена ещё не прошла — ждём
                lot["tp_order"] = None
                self._take_tp_fill(side, lot, o, info)
                self.save()
        for lot in list(s["lots"]):
            o = lot.get("tp_order")
            if o and o["id"] not in open_ids:
                info = self.c.order_info(o["id"])
                if info.get("status") in LIVE:
                    continue                  # ещё живой, просто не попал в список
                # конечный статус: исполненное (целиком или частично) — в прибыль, остаток лота — новым тейком
                lot["tp_order"] = None
                if self._take_tp_fill(side, lot, o, info):
                    continue
            if lot.get("tp_order") is None:
                lot["tp_order"] = self._place(side, "t", lot["tp"], True, bid, ask, qty=lot["qty"], lot=lot)
                if lot["tp_order"] is None and not s.get("pending"):
                    self._reconcile_side(side, mid)
                self.save()
                if s.get("pending"):
                    return                    # исход постановки неизвестен — дальше по этой стороне не идём
        # 3) опорная цена — как у GinArea: шаг от крайнего ОТКРЫТОГО ордера (лонг — нижний, шорт —
        # верхний); после тейка уровень заполняется снова. Сверено 09.10 по журналу шортового бота
        # 5021652508: 9 из 9 входов после тейка ровно на шаг от верхнего открытого (±0.06%).
        if s["lots"]:
            s["ref"] = (min if d > 0 else max)(l["entry"] for l in s["lots"])
        # без позиции опорная цена тянется за ценой
        if not s["lots"]:
            s["ref"] = mid if s["ref"] is None else (max(s["ref"], mid) if d > 0 else min(s["ref"], mid))
        if s["ref"] is None:
            s["ref"] = mid
        # 4) входной ордер
        desired = s["ref"] * (1 - d * float(cfg["step_pct"]) / 100)
        ok, why = self.may_add(side, desired, mid)
        if not enabled or not ok:
            self._drop_entry(side)
            s["blocked"] = "выключено" if not enabled else why
            return
        s["blocked"] = ""
        if s["entry"]:
            if float(s["entry"].get("filled") or 0) > 0:
                return                        # частично исполнен — держим, остаток добирается на том же уровне
            live = getattr(self, "open", {}).get(s["entry"]["id"])
            same_qty = live is None or abs(float(live.get("origQty") or 0) - float(cfg["order_qty"])) < 1e-12
            if same_qty and abs(s["entry"]["price"] - desired) / desired * 100 <= float(cfg["trail_min_move_pct"]):
                return                        # цена и объём те же — оставить
            if self._drop_entry(side) or s["entry"]:
                return                        # успел исполниться — новый вход считаем на следующем проходе
        s["entry"] = self._place(side, "e", desired, False, bid, ask)
        self.save()

    def disable_entries(self) -> None:
        """Снять свои входные ордера (тейки остаются)."""
        for side in ("LONG", "SHORT"):
            self._drop_entry(side)
        self.save()

    def card(self, mid: float | None = None) -> str:
        if mid is None:
            bid, ask = self.c.book(self.cfg["symbol"])
            mid = (bid + ask) / 2
        cfg = self.cfg
        tick = float(cfg["price_tick"])
        mode = ("ВЫКЛ" if not cfg["enabled"] else "ХОЛОСТОЙ (без ордеров)" if cfg["dry_run"] else "ЖИВАЯ")
        lines = [f"🕸 СЕТКА WEEX {cfg['symbol']} — {mode}" + (f" · СТОП: {self.st['halt_reason']}" if self.st["halted"] else ""),
                 f"шаг {cfg['step_pct']}% · цель {cfg['target_pct']}% · ордер {cfg['order_qty']} · цена {fmt_px(mid, tick)}"]
        for side in cfg["sides"]:
            s = self.st[side]
            q = sum(float(l["qty"]) for l in s["lots"])
            un = sum(DIR[side] * float(l["qty"]) * (mid - l["entry"]) for l in s["lots"])
            ent = f"вход {fmt_px(s['entry']['price'], tick)}" if s.get("entry") else ("вход нет: " + s.get("blocked", "") if s.get("blocked") else "вход нет")
            lines.append(f"{'🟢 ЛОНГ' if side == 'LONG' else '🔴 ШОРТ'}: {len(s['lots'])} орд. ({q:g}), мешок ${un:+.2f}, "
                         f"закрыто ${s['realized']:+.2f}, комиссии ${s['fees']:.3f}, тейков {s['n_tps']} · {ent}")
        tot = self.bot_pnl(mid)
        turn = sum(self.st[s]["turnover"] for s in ("LONG", "SHORT"))
        lines.append(f"итог сетки с мешком ${tot:+.2f} · оборот ${turn:,.0f}")
        return "\n".join(lines)


class DryExchange:
    """Имитатор биржи для холостого прогона и тестов: цены — живые (или заданные), ордера
    исполняются, когда стакан их пересекает (покупка — ask ≤ цены, продажа — bid ≥ цены)."""

    def __init__(self, book_fn, maker_fee: float = 0.00016, balance: float = 3300.0, symbol: str = "BTCUSDT"):
        self.book_fn = book_fn
        self.symbol = symbol
        self.maker_fee = maker_fee
        self.orders: dict[str, dict] = {}
        self.trades: dict[str, list] = {}
        self.n = 0
        self.balance = balance

    def book(self, symbol):
        bid, ask = self.book_fn()
        for oid, o in self.orders.items():
            if o["status"] != "NEW":
                continue
            px = float(o["price"])
            hit = (o["side"] == "BUY" and ask <= px) or (o["side"] == "SELL" and bid >= px)
            if hit:
                o.update(status="FILLED", executedQty=o["origQty"], avgPrice=o["price"])
                self.trades[oid] = [{"orderId": oid, "commission": str(float(o["origQty"]) * px * self.maker_fee),
                                     "maker": True, "price": o["price"], "qty": o["origQty"]}]
        return bid, ask

    def open_orders(self, symbol):
        return [{"orderId": k, **v} for k, v in self.orders.items() if v["status"] == "NEW"]

    def order_info(self, oid):
        return {"orderId": oid, **self.orders[str(oid)]}

    def order_history(self, symbol, limit=100, page=0):
        return [{"orderId": k, **v} for k, v in list(self.orders.items())[::-1][:limit]]

    def place_limit(self, symbol, side, position_side, qty, price, cid, reduce_only=False, post_only=True):
        bid, ask = self.book_fn()
        if post_only and ((side == "BUY" and float(price) >= ask) or (side == "SELL" and float(price) <= bid)):
            return {"success": False, "errorCode": "POST_ONLY_REJECT", "orderId": None}
        self.n += 1
        oid = f"dry{self.n}"
        self.orders[oid] = {"clientOrderId": cid, "side": side, "positionSide": position_side, "price": price,
                            "origQty": qty, "status": "NEW", "executedQty": "0", "avgPrice": "0",
                            "reduceOnly": reduce_only}
        return {"success": True, "orderId": oid, "clientOrderId": cid}

    def cancel(self, oid):
        o = self.orders.get(str(oid))
        if o and o["status"] == "NEW":
            o["status"] = "CANCELED"
        return {"success": True, "orderId": oid}

    def user_trades(self, symbol, order_id=None):
        return self.trades.get(str(order_id), [])

    def futures_balance(self):
        return [{"asset": "USDT", "balance": str(self.balance), "unrealizePnl": "0"}]

    def futures_positions(self):
        """Позиция стороны = объём исполненных входов − исполненных тейков (по ордерам имитатора)."""
        size = {"LONG": 0.0, "SHORT": 0.0}
        for o in self.orders.values():
            if o["status"] == "FILLED":
                q = float(o["executedQty"])
                size[o["positionSide"]] += -q if o["reduceOnly"] else q
        return [{"symbol": self.symbol, "side": k, "size": f"{max(v, 0):.4f}"} for k, v in size.items()]
