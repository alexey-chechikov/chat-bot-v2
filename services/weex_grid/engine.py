"""Движок сетки WEEX: один проход tick() = сверка ордеров с биржей + решения + сохранение.

Состояние в state/weex_grid_state.json сохраняется АТОМАРНО после каждого действия, чтобы
перезапуск не плодил дубли. Журнал исполнений — state/weex_grid_journal.jsonl (цена, объём,
комиссия, мейкер/тейкер, orderId) — по нему меряем реальную цену круга и кэшбэк.

Целостность (разбор GPT по коду 65eae029, 10.10): битый конфиг или учёт НЕ подменяются
значениями по умолчанию (иначе сетка золота торговала бы конфигом BTC) — сетка встаёт
(GridHalt) до ручного восстановления; учёт помнит свой символ.
"""
from __future__ import annotations

import json
import logging
import math
import os
import tempfile
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
LIVE = {"NEW", "PENDING", "CANCELING", "UNTRIGGERED", "UNACTIVATED", "PARTIALLY_FILLED"}   # может ещё исполниться
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
PENDING_TTL = 120.0      # с: ордер с потерянным ответом не нашёлся за полный поиск по времени → не дошёл
FEE_WINDOW = 3600.0      # с: сколько ждать появления комиссии по исполненному ордеру
FEE_POLL = 60.0          # с: как часто досверять комиссии
FEE_BATCH = 5            # курсоров комиссий за одну досверку (по кругу, давно не проверявшиеся первыми)
ORDER_FILLS_KEEP = 7 * 86400.0   # с: сколько хранить курсор исполнения завершённого ордера


class GridHalt(RuntimeError):
    """Сетка не может безопасно торговать (битый конфиг/учёт, чужой символ) — до ручного восстановления."""


class ConfigError(GridHalt):
    pass


class StateCorrupt(GridHalt):
    pass


def atomic_write(path: Path, text: str) -> None:
    """Запись во временный файл рядом + fsync + replace: файл либо старый, либо новый целиком."""
    path = Path(path)
    fd, tmp = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def grid_files(name: str = "BTC") -> tuple[Path, Path, Path]:
    """(конфиг, состояние, журнал) сетки по имени."""
    if name == "BTC":
        return CONFIG, STATE, JOURNAL
    base = ROOT / "state" / f"weex_grid_{name.lower()}"
    return (base.with_name(base.name + "_config.json"), base.with_name(base.name + "_state.json"),
            base.with_name(base.name + "_journal.jsonl"))


def load_config(path: Path = CONFIG, template: dict | None = None) -> dict:
    """Нет файла → создать из шаблона. Файл есть, но битый → ConfigError (НЕ значения по умолчанию:
    10.10 битый конфиг золота превращался в конфиг BTC и слал reduceOnly SELL BTCUSDT 0.023)."""
    base = {**DEFAULT, **(template or {})}
    path = Path(path)
    if not path.exists():
        atomic_write(path, json.dumps({"_note": "сетка WEEX; enabled/dry_run меняет только оператор", **base},
                                      ensure_ascii=False, indent=1))
        return dict(base)
    try:
        cfg = {**base, **json.loads(path.read_text(encoding="utf-8"))}
    except (OSError, ValueError) as exc:
        logger.exception("weex_grid.config_failed path=%s", path)
        raise ConfigError(f"конфиг {path.name} не читается: {exc}") from exc
    want = (template or {}).get("symbol")
    if want and cfg.get("symbol") != want:
        raise ConfigError(f"конфиг {path.name}: символ {cfg.get('symbol')} вместо {want}")
    return cfg


def save_config(cfg: dict, path: Path = CONFIG) -> None:
    atomic_write(path, json.dumps(cfg, ensure_ascii=False, indent=1))


def round_tick(px: float, tick: float, up: bool) -> float:
    n = px / tick
    n = math.ceil(n - 1e-9) if up else math.floor(n + 1e-9)
    return round(n * tick, 8)


def fmt_px(px: float, tick: float) -> str:
    dec = max(0, -int(math.floor(math.log10(tick)))) if tick < 1 else 0
    return f"{px:.{dec}f}"


def new_side_state() -> dict:
    # order_fills — долговечный курсор исполненного по номеру ордера, независимый от лота: при потере
    # привязки тейка восстановление считает только то, что ещё не учтено (перепроверка GPT 10.10)
    return {"ref": None, "entry": None, "lots": [], "realized": 0.0, "fees": 0.0,
            "n_entries": 0, "n_tps": 0, "seq": 0, "turnover": 0.0, "pending": None,
            "strays": [], "fee_book": {}, "order_fills": {}}


class Grid:
    def __init__(self, client, cfg: dict | None = None, state_path: Path = STATE,
                 journal_path: Path = JOURNAL, sigma_fn=None, send_fn=None, now_fn=time.time):
        self.c = client
        self.cfg = cfg or load_config()
        self.state_path = Path(state_path)
        self.journal_path = Path(journal_path)
        self.sigma_fn = sigma_fn
        self.send = send_fn
        self.now = now_fn
        self.st = self._load()
        self._equity = None
        self._equity_ts = 0.0
        self.open: dict[str, dict] = {}

    # ---------- состояние
    def _load(self) -> dict:
        """Нет файла — первый запуск. Файл есть, но не читается — StateCorrupt (НЕ пустой бот:
        пустой снимал бы тейки реальной позиции как «сирот» и ставил новый вход)."""
        if not self.state_path.exists():
            st = {}
        else:
            try:
                st = json.loads(self.state_path.read_text(encoding="utf-8"))
                if not isinstance(st, dict):
                    raise ValueError("не объект")
            except (OSError, ValueError) as exc:
                logger.exception("weex_grid.state_failed path=%s", self.state_path)
                raise StateCorrupt(f"учёт {self.state_path.name} не читается: {exc}") from exc
        sym = self.cfg["symbol"]
        if st.get("symbol") and st["symbol"] != sym:
            raise StateCorrupt(f"учёт {self.state_path.name} от {st['symbol']}, а сетка {sym}")
        st["symbol"] = sym
        for s in ("LONG", "SHORT"):
            st.setdefault(s, new_side_state())
            for k, v in new_side_state().items():
                st[s].setdefault(k, v)
        st.setdefault("halted", False)
        st.setdefault("halt_reason", "")
        st.setdefault("day", None)
        st.setdefault("day_start_pnl", 0.0)
        st.setdefault("fee_checked", 0.0)
        # миграция курсора комиссии из учёта до 10.10 (entry/stray['fee_done']) — иначе следующий
        # прирост прибавил бы уже учтённую комиссию заново (разбор GPT, перепроверка 10.10)
        for s in ("LONG", "SHORT"):
            sd = st[s]
            for o in [sd.get("entry")] + list(sd.get("strays") or []):
                if o and o.get("fee_done") and str(o["id"]) not in sd["fee_book"]:
                    sd["fee_book"][str(o["id"])] = {"done": float(o["fee_done"]), "t": self.now()}
        return st

    def save(self) -> None:
        atomic_write(self.state_path, json.dumps(self.st, ensure_ascii=False, indent=1))

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

    def _fee_delta(self, side: str, order_id: str) -> tuple[float, bool | None]:
        """Прирост комиссии ордера против уже записанной (курсор в fee_book). Ордер остаётся в
        книге FEE_WINDOW секунд — поздно появившаяся комиссия будет дописана _settle_fees."""
        s = self.st[side]
        try:
            trades = self.c.user_trades(self.cfg["symbol"], order_id) or []
        except Exception:                                       # noqa: BLE001
            logger.exception("weex_grid.trades_failed")
            trades = []
        fee_all = sum(float(t.get("commission") or 0) for t in trades)
        makers = {bool(t.get("maker")) for t in trades}
        rec = s["fee_book"].setdefault(str(order_id), {"done": 0.0, "t": self.now(), "t0": self.now()})
        delta = max(fee_all - rec["done"], 0.0)
        rec["done"] = max(rec["done"], fee_all)
        rec["t"] = self.now()
        return delta, (makers.pop() if len(makers) == 1 else None)

    def _mark_fills(self, side: str, order: dict) -> None:
        """Записать долговечный курсор исполненного ордера (по номеру, отдельно от лота)."""
        self.st[side]["order_fills"][str(order["id"])] = {"filled": float(order.get("filled") or 0),
                                                           "val": float(order.get("filled_val") or 0),
                                                           "t": self.now()}

    def _with_cursor(self, side: str, order: dict) -> dict:
        """Ордер с курсором исполненного из order_fills (если ордер уже учитывался)."""
        cur = self.st[side]["order_fills"].get(str(order["id"]))
        if cur:
            order = {**order, "filled": cur["filled"], "filled_val": cur["val"]}
        return order

    def _prune_fills(self) -> None:
        now = self.now()
        for sd in ("LONG", "SHORT"):
            refs = self._referenced(sd)
            book = self.st[sd]["order_fills"]
            for oid in [k for k, v in book.items() if k not in refs and now - float(v["t"]) > ORDER_FILLS_KEEP]:
                book.pop(oid, None)

    def _referenced(self, side: str) -> set[str]:
        """Ордера стороны, которые учёт ещё ведёт (их курсоры не истекают)."""
        s = self.st[side]
        ids = {str(x["id"]) for x in s["strays"]}
        if s.get("entry"):
            ids.add(str(s["entry"]["id"]))
        ids.update(str(l["tp_order"]["id"]) for l in s["lots"] if l.get("tp_order"))
        return ids

    def _settle_fees(self) -> None:
        """Раз в минуту дописать комиссии, которых не было в момент исполнения: адресно, сделками
        КОНКРЕТНОГО ордера (orderId), до FEE_BATCH давно не проверявшихся курсоров за проход, по кругу.
        Без окон по времени — нет ни лимита 7 суток, ни застревания на плотной истории (перепроверка
        GPT 10.10: общая выборка окном упиралась в 7 суток и бюджет запросов). Курсор ордера, который
        учёт ещё ведёт, не истекает; завершённого — снимается через FEE_WINDOW после последней проверки."""
        now = self.now()
        books = [(sd, oid, rec) for sd in ("LONG", "SHORT") for oid, rec in self.st[sd]["fee_book"].items()]
        if not books or now - float(self.st.get("fee_checked") or 0) < FEE_POLL:
            return
        self.st["fee_checked"] = now
        refs = {sd: self._referenced(sd) for sd in ("LONG", "SHORT")}
        books.sort(key=lambda b: float(b[2].get("checked") or 0))
        for sd, oid, rec in books[:FEE_BATCH]:
            try:
                trades = self.c.user_trades(self.cfg["symbol"], oid) or []
            except Exception:                                   # noqa: BLE001
                logger.exception("weex_grid.trades_failed")
                continue
            rec["checked"] = now
            fee_all = sum(float(t.get("commission") or 0) for t in trades)
            if fee_all > rec["done"] + 1e-12:
                add = fee_all - rec["done"]
                self.st[sd]["fees"] += add
                rec["done"] = fee_all
                rec["t"] = now
                self._journal({"side": sd, "kind": "комиссия (поздняя)", "fee": add, "order_id": oid})
        for sd, oid, rec in books:
            if oid in refs[sd] or now - float(rec["t"]) <= FEE_WINDOW or not rec.get("checked"):
                continue
            if rec["done"] <= 0:
                logger.warning("weex_grid.fee_unresolved side=%s order=%s", sd, oid)
                self._journal({"side": sd, "kind": "комиссия не найдена за час", "order_id": oid})
            self.st[sd]["fee_book"].pop(oid, None)

    def equity(self) -> float | None:
        if self._equity is None or self.now() - self._equity_ts > 60:
            try:
                bal = self.c.futures_balance()
                usdt = next((b for b in bal if b.get("asset") == "USDT"), None)
                self._equity = float(usdt["balance"]) + float(usdt.get("unrealizePnl") or 0) if usdt else None
                self._equity_ts = self.now()
            except Exception:                                   # noqa: BLE001
                logger.exception("weex_grid.balance_failed")
                self._equity = None                             # просроченный кэш не выдаём за известный баланс
        return self._equity

    def unrealized(self, mid: float) -> float:
        return sum(DIR[s] * float(l["qty"]) * (mid - l["entry"]) for s in ("LONG", "SHORT") for l in self.st[s]["lots"])

    def bot_pnl(self, mid: float) -> float:
        return (sum(self.st[s]["realized"] - self.st[s]["fees"] for s in ("LONG", "SHORT"))
                + self.unrealized(mid))

    def _slots(self, side: str) -> int:
        """Занятые слоты — по исходным заявкам, а не по кускам их исполнения (10.10, разбор GPT:
        50 исполнений по 0.0001 занимали 50 слотов при тех же $500)."""
        return len({l.get("parent") or f"lot{id(l)}" for l in self.st[side]["lots"]})

    def may_add(self, side: str, price: float, mid: float, qty: float | None = None,
                parent: str | None = None) -> tuple[bool, str]:
        """Можно ли держать/ставить вход объёмом qty (по умолчанию — размер ордера из конфига) по
        цене price. parent — уже занятый слот (частично исполненный вход) — второй слот не нужен."""
        cfg, s = self.cfg, self.st[side]
        if self.st["halted"]:
            return False, "стоп: " + self.st["halt_reason"]
        if any(x.get("kind") == "e" for x in s["strays"]):
            return False, "разбираю лишний входной ордер"
        taken = self._slots(side)
        new_slot = not (parent and any(l.get("parent") == parent for l in s["lots"]))
        if taken + (1 if new_slot else 0) > int(cfg["max_lots_per_side"]):
            return False, "достигнут максимум ордеров"
        q = float(cfg["order_qty"]) if qty is None else float(qty)
        # потолок — по большему из себестоимости и текущей стоимости (на падении цены по одной
        # текущей стоимости докупали сверх потолка по себестоимости)
        cost = sum(float(l["qty"]) * l["entry"] for l in s["lots"])
        value = sum(float(l["qty"]) for l in s["lots"]) * mid
        notional = max(cost, value) + q * price
        if notional > float(cfg["max_notional_usd"]) + 1e-9:
            return False, "достигнут потолок позиции"
        free = cfg.get("portfolio_free_usd")                # общий потолок всех живых сеток и тренда (10.10)
        if free is not None and q * price > float(free) + 1e-9:
            return False, "достигнут общий потолок счёта"
        if float(cfg["stress_budget_frac"]) <= 0:          # 0 = стресс-бюджет выключен оператором
            return True, ""
        sigma = self.sigma_fn() if self.sigma_fn else None
        S = max(float(cfg["stress_floor"]), float(cfg["stress_mult"]) * sigma * math.sqrt(3)) if sigma else float(cfg["stress_floor"])
        d = DIR[side]
        ps = mid * (1 - d * S)
        loss = sum(float(l["qty"]) * (l["entry"] - ps) * d for l in s["lots"]) + q * (price - ps) * d
        eq = self.equity()
        if eq is None or eq <= 0:                          # баланс неизвестен — риск не добавляем
            return False, "стресс-бюджет: баланс неизвестен"
        if loss > float(cfg["stress_budget_frac"]) * eq:
            return False, f"стресс-бюджет: обвал {S:.0%} съест ${loss:,.0f} > {cfg['stress_budget_frac']:.0%} баланса"
        return True, ""

    # ---------- ордера
    def _place(self, side: str, kind: str, price: float, reduce: bool, bid: float, ask: float,
               qty: str | None = None, lot: dict | None = None):
        """kind: 'e' вход, 't' тейк. POST_ONLY: цену не пускаем пересечь стакан.
        qty: у тейка — объём СВОЕГО лота. Вход проверяется потолком по ОКОНЧАТЕЛЬНОЙ цене (после
        сдвига к стакану и округления). Намерение пишется на диск ДО отправки (pending): если ответ
        потерян, следующий проход ищет ордер по clientOrderId и не ставит второй."""
        cfg, s = self.cfg, self.st[side]
        tick = float(cfg["price_tick"])
        buy = (OPEN_SIDE[side] if kind == "e" else CLOSE_SIDE[side]) == "BUY"
        if buy and price >= ask:
            price = bid
        if not buy and price <= bid:
            price = ask
        price = round_tick(price, tick, up=not buy)
        q = qty or cfg["order_qty"]
        if kind == "e":
            ok, why = self.may_add(side, price, (bid + ask) / 2, qty=float(q))
            if not ok:
                s["blocked"] = why
                return None
        cid = self._cid(side, kind)
        # srv — время намерения по часам БИРЖИ (сдвиг из синхронизации подписи): история ордеров фильтруется
        # по серверному времени (перепроверка GPT 10.10: при расхождении часов >2 мин ордер выпадал из окна)
        srv = self.now() + float(getattr(self.c, "_offset_ms", 0) or 0) / 1000
        s["pending"] = {"cid": cid, "kind": kind, "price": price, "qty": q, "lot_t": lot["t"] if lot else None,
                        "t": self.now(), "srv": srv}
        self.save()
        try:
            r = self.c.place_limit(cfg["symbol"], "BUY" if buy else "SELL", side, q,
                                   fmt_px(price, tick), cid, reduce_only=reduce, post_only=True)
        except Exception as exc:                                # noqa: BLE001 — один ордер не валит проход
            # исход неизвестен: ордер мог дойти — pending остаётся до выяснения
            logger.warning("weex_grid.place_failed side=%s kind=%s price=%s err=%s", side, kind, price, exc)
            return None
        if not r or not r.get("success", False) or not r.get("orderId"):
            if r and r.get("success"):                          # «успех» без номера — исход неизвестен
                logger.warning("weex_grid.place_no_id side=%s kind=%s resp=%s", side, kind, r)
                return None
            s["pending"] = None                                 # явный отказ — исход известен
            logger.warning("weex_grid.place_rejected side=%s kind=%s price=%s resp=%s", side, kind, price, r)
            self.save()
            return None
        s["pending"] = None
        return {"id": str(r["orderId"]), "cid": cid, "price": price, "qty": q}

    def _find_by_cid(self, cid: str, since: float, half: float = 600.0) -> tuple[dict | None, bool]:
        """Свой ордер по clientOrderId: открытые, затем история символа в окне ±half секунд вокруг момента
        намерения по часам биржи, постранично. Второе значение — поиск ПОЛНЫЙ: False, если все 10
        страниц заполнены (неполный поиск не доказывает, что ордер не дошёл, — такой pending не истекает)."""
        o = next((x for x in self.open.values() if x.get("clientOrderId") == cid), None)
        if o is not None:
            return o, True
        start_ms = int((since - half) * 1000)
        end_ms = int((since + half) * 1000)
        for page in range(10):
            chunk = self.c.order_history(self.cfg["symbol"], limit=100, page=page,
                                         start_ms=start_ms, end_ms=end_ms) or []
            o = next((x for x in chunk if x.get("clientOrderId") == cid), None)
            if o is not None:
                return o, True
            if len(chunk) < 100:
                return None, True
        return None, False

    def _resolve_pending(self, side: str) -> bool:
        """Ордер с потерянным ответом: найти и привязать. False — ещё не выяснено (на этой стороне
        новых ордеров не ставим)."""
        s = self.st[side]
        p = s.get("pending")
        if not p:
            return True
        try:
            # намерение без серверного времени (учёт до 10.10) — окно шире: ±30 мин
            o, complete = self._find_by_cid(p["cid"], p.get("srv") or p["t"], 600.0 if p.get("srv") else 1800.0)
        except Exception:                                       # noqa: BLE001
            logger.exception("weex_grid.history_failed")
            return False
        if o is None:
            if self.now() - p["t"] < PENDING_TTL:
                return False
            if not complete:                                    # поиск неполный — не считаем «не дошёл»
                if not p.get("warned"):
                    p["warned"] = True
                    self.save()
                    self._notify(f"⚠️ Сетка WEEX {self.cfg['symbol']}: ордер {p['cid']} с потерянным ответом не "
                                 f"найден, история слишком плотная для полного поиска — новые ордера стороны "
                                 f"{side} не ставлю до выяснения.")
                return False
            logger.warning("weex_grid.pending_not_found side=%s cid=%s — ордер не дошёл", side, p["cid"])
            self._notify(f"⚠️ Сетка WEEX {self.cfg['symbol']}: ответ биржи на ордер {p['cid']} потерян, за "
                         f"{PENDING_TTL:.0f} с в открытых и истории его нет — считаю не дошедшим.")
            s["pending"] = None
            self.save()
            return True
        order = self._with_cursor(side, {"id": str(o["orderId"]), "cid": p["cid"], "price": p["price"],
                                         "qty": p.get("qty")})
        logger.warning("weex_grid.pending_adopted side=%s kind=%s cid=%s status=%s", side, p["kind"], p["cid"],
                       o.get("status"))
        if p["kind"] == "e":
            if s["entry"] is None:
                s["entry"] = order
            else:                                               # не должно случиться: вход уже есть
                self._to_stray(side, order, "e")
        else:
            lot = next((l for l in s["lots"] if l["t"] == p["lot_t"]), None)
            if lot is not None and lot.get("tp_order") is None:
                lot["tp_order"] = order
            else:
                self._to_stray(side, order, "t")
        s["pending"] = None
        self.save()
        return True

    def _to_stray(self, side: str, order: dict, kind: str) -> None:
        """Лишний свой ордер: СНАЧАЛА записать на диск, потом снять и вести до конечного статуса
        (перепроверка GPT 10.10: снятие до сохранения при сбое оставляло исполненный ордер без учёта)."""
        self.st[side]["strays"].append({**order, "kind": kind})
        self.save()
        self._cancel(order)

    def _orphans(self) -> None:
        """Свои (b7g) ордера этого символа, о которых учёт не знает (потерянный ответ, откат учёта).
        Вход: если на стороне входа нет — принять как вход (его исполнения пойдут в лоты); иначе —
        снять и вести до конца. Тейк: если есть лот без тейка с тем же объёмом и ценой — принять как
        его тейк; иначе снять и вести до конца (исполненное распределить по лоту)."""
        known, pend = set(), set()
        for side in ("LONG", "SHORT"):
            s = self.st[side]
            if s.get("entry"):
                known.add(s["entry"]["id"])
            known.update(l["tp_order"]["id"] for l in s["lots"] if l.get("tp_order"))
            known.update(x["id"] for x in s["strays"])
            if s.get("pending"):
                pend.add(s["pending"]["cid"])
        tick = float(self.cfg["price_tick"])
        for oid, o in list(self.open.items()):
            if oid in known or o.get("clientOrderId") in pend:
                continue
            side = o.get("positionSide")
            if side not in DIR:
                continue
            s = self.st[side]
            price = float(o.get("price") or 0)
            # курсор исполненного — из долговечного order_fills: уже учтённое не учитывается повторно
            order = self._with_cursor(side, {"id": oid, "cid": o.get("clientOrderId"), "price": price,
                                             "qty": o.get("origQty")})
            known_cursor = str(oid) in s["order_fills"]
            logger.warning("weex_grid.orphan_order id=%s cid=%s side=%s reduce=%s", oid, o.get("clientOrderId"),
                           side, o.get("reduceOnly"))
            if not o.get("reduceOnly"):
                if s["entry"] is None and not s.get("pending"):
                    s["entry"] = order                      # неучтённое исполненное пойдёт в лоты
                    continue
                self._to_stray(side, order, "e")
            else:
                orig, exq = float(o.get("origQty") or 0), float(o.get("executedQty") or 0)
                near = [l for l in s["lots"] if l.get("tp_order") is None and abs(l["tp"] - price) <= tick + 1e-9]
                rec = float(order.get("filled") or 0)
                # лот = заявка минус уже учтённое по курсору → принять тейк с этим курсором
                lot = next((l for l in near if abs(float(l["qty"]) - (orig - rec)) <= self._tiny()), None)
                if lot is not None:
                    lot["tp_order"] = order
                    continue
                # курсора нет (учёт до 10.10) и лот уменьшен ровно на исполненное → оно уже учтено
                if not known_cursor and exq > 0:
                    lot = next((l for l in near if abs(float(l["qty"]) - (orig - exq)) <= self._tiny()), None)
                    if lot is not None:
                        avg = float(o.get("avgPrice") or 0) or price
                        lot["tp_order"] = {**order, "filled": exq, "filled_val": avg * exq}
                        continue
                self._to_stray(side, order, "t")
            self.open.pop(oid, None)
        self.save()

    def _process_strays(self, side: str, mid: float) -> None:
        """Лишние ордера стороны: исполнения входа → лоты; исполнения тейка → закрытие ближайшего
        по цене лота (по факт. цене); конечный статус — забыть, живой — снять ещё раз."""
        s, d = self.st[side], DIR[side]
        for x in list(s["strays"]):
            try:
                info = self.c.order_info(x["id"])
            except Exception:                                   # noqa: BLE001
                logger.exception("weex_grid.stray_info_failed id=%s", x["id"])
                continue
            if x["kind"] == "e":
                self._take_entry_fill(side, x, info)
            else:
                exq = float(info.get("executedQty") or 0)
                dq = exq - float(x.get("filled") or 0)
                if dq > self._tiny():
                    avg = float(info.get("avgPrice") or 0) or x["price"]
                    val = avg * exq
                    px = (val - float(x.get("filled_val") or 0)) / dq
                    x["filled"], x["filled_val"] = exq, val
                    self._mark_fills(side, x)
                    fee, maker = self._fee_delta(side, x["id"])
                    s["fees"] += fee
                    left = dq
                    for lot in sorted(s["lots"], key=lambda l: abs(l["tp"] - x["price"])):
                        if left <= self._tiny():
                            break
                        take = min(float(lot["qty"]), left)
                        pnl = d * take * (px - lot["entry"])
                        s["realized"] += pnl
                        s["turnover"] += take * px
                        left -= take
                        rest = float(lot["qty"]) - take
                        self._journal({"side": side, "kind": "тейк (восстановлен)", "price": px,
                                       "qty": self._qty_str(take), "fee": fee, "maker": maker, "pnl": pnl,
                                       "entry": lot["entry"], "order_id": x["id"]})
                        fee = 0.0
                        if rest <= self._tiny():
                            s["lots"].remove(lot)
                            s["n_tps"] += 1
                        else:
                            lot["qty"] = self._qty_str(rest)
                    if left > self._tiny():
                        logger.warning("weex_grid.stray_tp_unallocated side=%s qty=%s", side, left)
                        self._notify(f"⚠️ Сетка WEEX {self.cfg['symbol']}: тейк {x['cid']} закрыл {left:g} {side} "
                                     f"сверх лотов учёта — расхождение, проверь позицию.")
            if info.get("status") not in LIVE:
                s["strays"].remove(x)
            else:
                self._cancel(x)
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
        # обе стороны сопровождаются всегда, пока у стороны есть что-то на бирже/в учёте; новые входы —
        # только на сторонах из конфига (перепроверка GPT 10.10: после смены sides LONG→SHORT старый
        # вход LONG исполнялся без учёта и тейка)
        for side in ("LONG", "SHORT"):
            s = self.st[side]
            if side in cfg["sides"] or s.get("entry") or s["lots"] or s["strays"] or s.get("pending"):
                self._side(side, bid, ask, mid, open_ids, enabled=bool(cfg["enabled"]) and side in cfg["sides"])
        self._settle_fees()
        self._prune_fills()
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
        из прироста стоимости, комиссия — прирост комиссии ордера. Повтор того же снимка = 0.
        Лоты одной заявки помечены parent — занимают один слот."""
        cfg, s, d = self.cfg, self.st[side], DIR[side]
        exq = float(info.get("executedQty") or 0)
        done = float(e.get("filled") or 0)
        dq = exq - done
        if dq <= self._tiny():
            return False
        avg = float(info.get("avgPrice") or 0) or e["price"]
        val = avg * exq
        px = (val - float(e.get("filled_val") or 0)) / dq
        fee, maker = self._fee_delta(side, e["id"])
        e["filled"], e["filled_val"] = exq, val
        self._mark_fills(side, e)
        lot = {"entry": px, "qty": self._qty_str(dq),
               "tp": round_tick(px * (1 + d * float(cfg["target_pct"]) / 100), float(cfg["price_tick"]), up=d > 0),
               "tp_order": None, "t": self.now(), "parent": e["id"]}
        while any(l["t"] == lot["t"] for l in s["lots"]):  # t — ключ лота для pending тейка
            lot["t"] += 0.001
        s["lots"].append(lot)
        s["ref"] = px
        s["fees"] += fee
        s["turnover"] += dq * px
        s["n_entries"] += 1
        self._journal({"side": side, "kind": "вход" if dq >= exq - self._tiny() else "вход (часть)", "price": px,
                       "qty": lot["qty"], "fee": fee, "maker": maker, "order_id": e["id"], "cum_qty": exq})
        return True

    def _take_tp_fill(self, side: str, lot: dict, o: dict, info: dict, terminal: bool) -> bool:
        """Новая исполненная часть тейка (курсор o['filled'] — тейк может исполняться частями и пока
        висит): прибыль по приросту, лот уменьшается. terminal — ордер в конечном статусе: остаток
        лота получит новый тейк. True — лот закрыт полностью и удалён."""
        s, d = self.st[side], DIR[side]
        exq = float(info.get("executedQty") or 0)
        dq = exq - float(o.get("filled") or 0)
        full = False
        if dq > self._tiny():
            avg = float(info.get("avgPrice") or 0) or o["price"]
            val = avg * exq
            px = (val - float(o.get("filled_val") or 0)) / dq
            o["filled"], o["filled_val"] = exq, val
            self._mark_fills(side, o)
            fee, maker = self._fee_delta(side, o["id"])
            pnl = d * dq * (px - lot["entry"])
            s["realized"] += pnl
            s["fees"] += fee
            s["turnover"] += dq * px
            rest = float(lot["qty"]) - dq
            full = rest <= self._tiny()
            self._journal({"side": side, "kind": "тейк" if full else "тейк (часть)", "price": px,
                           "qty": self._qty_str(dq), "fee": fee, "maker": maker, "pnl": pnl, "entry": lot["entry"],
                           "order_id": o["id"], "cum_qty": exq})
            if full:
                s["n_tps"] += 1
                s["lots"].remove(lot)
            else:
                lot["qty"] = self._qty_str(rest)
        if terminal and not full:
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
        """Тейк отклонён → сверить с позицией биржи. Если лотов в учёте больше позиции стороны, снять
        РОВНО недостающий объём (10.10, разбор GPT: раньше удалялся весь лот, хотя на бирже остаток
        был) с лотов без тейка, новые первыми; остаток лота остаётся и получит тейк. Снятое пишется в
        закрытое по текущей цене как оценка внешнего закрытия + сообщение. Позиция может включать
        ручные сделки — тогда она больше суммы лотов и ничего не снимается."""
        s, d = self.st[side], DIR[side]
        try:
            pos = self.c.futures_positions() or []
        except Exception:                                       # noqa: BLE001
            logger.exception("weex_grid.positions_failed")
            return
        size = sum(float(p.get("size") or 0) for p in pos
                   if p.get("symbol") == self.cfg["symbol"] and p.get("side") == side)
        deficit = sum(float(l["qty"]) for l in s["lots"]) - size
        for lot in sorted([l for l in s["lots"] if l.get("tp_order") is None], key=lambda l: -l["t"]):
            if deficit <= self._tiny():
                break
            take = min(float(lot["qty"]), deficit)
            deficit -= take
            rest = float(lot["qty"]) - take
            pnl = d * take * (mid - lot["entry"])
            s["realized"] += pnl
            if rest <= self._tiny():
                s["lots"].remove(lot)
            else:
                lot["qty"] = self._qty_str(rest)
            qs = self._qty_str(take)
            logger.warning("weex_grid.external_close side=%s entry=%s qty=%s rest=%s exch_size=%s est_pnl=%.4f",
                           side, lot["entry"], qs, rest, size, pnl)
            self._journal({"side": side, "kind": "внешнее закрытие (оценка по текущей цене)", "price": mid,
                           "qty": qs, "entry": lot["entry"], "pnl": pnl})
            self._notify(f"⚠️ Сетка WEEX {self.cfg['symbol']}: на бирже не хватает {qs} {side} под лот по "
                         f"{lot['entry']:,.2f} — закрыто не сеткой (вручную?). Записал по текущей цене "
                         f"{mid:,.2f}: ${pnl:+.2f}" + (f"; остаток лота {self._qty_str(rest)} оставлен." if rest > self._tiny() else "."))
        self.save()

    def _side(self, side: str, bid: float, ask: float, mid: float, open_ids: set, enabled: bool) -> None:
        cfg, s, d = self.cfg, self.st[side], DIR[side]
        # 0) ордер с потерянным ответом: пока не выяснено — НОВЫХ ордеров на стороне не ставим, но
        # сопровождение продолжается (учёт исполнений, отмена входа при стопе/потолке). Перепроверка GPT
        # 10.10: раньше неясный тейк блокировал всю сторону, и /weex stop не снимал известный вход.
        can_place = self._resolve_pending(side)
        if s["strays"]:
            self._process_strays(side, mid)
        # 1) входной ордер: исполненная часть записывается сразу (и пока ордер ещё висит — чтобы
        # она получила тейк); сам ордер забываем только в конечном статусе.
        e = s["entry"]
        if e and e["id"] in open_ids:
            live = self.open.get(e["id"])
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
        # 2а) тейк на бирже не того объёма, что осталось у лота (биржа урезала reduceOnly) — снять;
        # исполненное до снятия записывается, остаток получит новый тейк.
        for lot in list(s["lots"]):
            o = lot.get("tp_order")
            live = self.open.get(o["id"]) if o else None
            if not live:
                continue
            remaining = float(live.get("origQty") or 0) - float(o.get("filled") or 0)
            if abs(remaining - float(lot["qty"])) > self._tiny():
                # сначала учесть исполненное (прирост) — вдруг расхождение из-за частичного исполнения
                if self._take_tp_fill(side, lot, o, live, terminal=False):
                    continue
                remaining = float(live.get("origQty") or 0) - float(o.get("filled") or 0)
                if abs(remaining - float(lot["qty"])) <= self._tiny():
                    continue
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
                self._take_tp_fill(side, lot, o, info, terminal=True)
        for lot in list(s["lots"]):
            o = lot.get("tp_order")
            if o and o["id"] in open_ids:
                live = self.open.get(o["id"])
                if live:
                    self._take_tp_fill(side, lot, o, live, terminal=False)   # частичное исполнение висящего тейка
                continue
            if o:
                info = self.c.order_info(o["id"])
                if info.get("status") in LIVE:
                    if self._take_tp_fill(side, lot, o, info, terminal=False):
                        continue
                    continue                  # ещё живой, просто не попал в список
                # конечный статус: исполненное — в прибыль, остаток лота — новым тейком
                if self._take_tp_fill(side, lot, o, info, terminal=True):
                    continue
            if lot.get("tp_order") is None:
                if not can_place:
                    continue                  # неясный ордер на стороне — тейк не ставим поверх (не дублировать)
                lot["tp_order"] = self._place(side, "t", lot["tp"], True, bid, ask, qty=lot["qty"], lot=lot)
                if lot["tp_order"] is None and not s.get("pending"):
                    self._reconcile_side(side, mid)
                self.save()
                if s.get("pending"):
                    can_place = False         # исход постановки неизвестен — новых ордеров больше не ставим
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
        e = s["entry"]
        if e and float(e.get("filled") or 0) > 0:
            # частично исполненный вход: держим ради остатка на том же уровне, но резерв — его реальный
            # остаток по его цене (10.10, разбор GPT: проверялся размер из конфига)
            rem = float(e.get("qty") or cfg["order_qty"]) - float(e.get("filled") or 0)
            ok, why = self.may_add(side, e["price"], mid, qty=max(rem, 0.0), parent=e["id"])
        else:
            ok, why = self.may_add(side, desired, mid)
        if not enabled or not ok:
            self._drop_entry(side)
            s["blocked"] = "выключено" if not enabled else why
            return
        s["blocked"] = ""
        if e:
            if float(e.get("filled") or 0) > 0:
                return                        # частично исполнен — держим, остаток добирается на том же уровне
            live = self.open.get(e["id"])
            same_qty = live is None or abs(float(live.get("origQty") or 0) - float(cfg["order_qty"])) < 1e-12
            if same_qty and abs(e["price"] - desired) / desired * 100 <= float(cfg["trail_min_move_pct"]):
                # оставить можно, только если стоящий ордер САМ проходит потолок по своей цене (перепроверка
                # GPT 10.10: допуск 0.05% оставлял старую заявку чуть сверх сниженного потолка)
                keep_ok, keep_why = self.may_add(side, e["price"], mid,
                                                 qty=float(e.get("qty") or (live or {}).get("origQty") or cfg["order_qty"]))
                if keep_ok:
                    return                    # цена и объём те же — оставить
                s["blocked"] = keep_why
            if self._drop_entry(side) or s["entry"]:
                return                        # успел исполниться — новый вход считаем на следующем проходе
        if not can_place:
            return                            # неясный ордер на стороне — новый вход не ставим
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
        for side in ("LONG", "SHORT"):
            s = self.st[side]
            if side not in cfg["sides"] and not (s.get("entry") or s["lots"] or s["strays"]):
                continue                      # сторона снята из конфига — показываем, пока у неё есть остатки
            q = sum(float(l["qty"]) for l in s["lots"])
            un = sum(DIR[side] * float(l["qty"]) * (mid - l["entry"]) for l in s["lots"])
            ent = f"вход {fmt_px(s['entry']['price'], tick)}" if s.get("entry") else ("вход нет: " + s.get("blocked", "") if s.get("blocked") else "вход нет")
            lines.append(f"{'🟢 ЛОНГ' if side == 'LONG' else '🔴 ШОРТ'}: {self._slots(side)} орд. ({q:g}), мешок ${un:+.2f}, "
                         f"закрыто ${s['realized']:+.2f}, комиссии ${s['fees']:.3f}, тейков {s['n_tps']} · {ent}")
        tot = self.bot_pnl(mid)
        turn = sum(self.st[s]["turnover"] for s in ("LONG", "SHORT"))
        lines.append(f"итог сетки с мешком ${tot:+.2f} · оборот ${turn:,.0f}")
        return "\n".join(lines)


class DryExchange:
    """Имитатор биржи для холостого прогона и тестов: цены — живые (или заданные), ордера
    исполняются, когда стакан их пересекает (покупка — ask ≤ цены, продажа — bid ≥ цены)."""

    def __init__(self, book_fn, maker_fee: float = 0.00016, balance: float = 3300.0, symbol: str = "BTCUSDT",
                 now_fn=time.time):
        self.book_fn = book_fn
        self.symbol = symbol
        self.now_fn = now_fn                         # время сделок — для выборки по окну, как у биржи
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
                self.trades[oid] = [{"id": f"t{oid}", "orderId": oid,
                                     "commission": str(float(o["origQty"]) * px * self.maker_fee),
                                     "maker": True, "price": o["price"], "qty": o["origQty"],
                                     "time": int(self.now_fn() * 1000)}]
        return bid, ask

    def open_orders(self, symbol):
        return [{"orderId": k, **v} for k, v in self.orders.items() if v["status"] in ("NEW", "CANCELING")]

    def order_info(self, oid):
        return {"orderId": oid, **self.orders[str(oid)]}

    def order_history(self, symbol, limit=100, page=0, start_ms=None, end_ms=None):
        rows = [{"orderId": k, **v} for k, v in list(self.orders.items())[::-1]]
        return rows[page * limit:(page + 1) * limit]

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

    def user_trades(self, symbol, order_id=None, start_ms=None, end_ms=None):
        if order_id is not None:
            return self.trades.get(str(order_id), [])
        rows = [t for ts in self.trades.values() for t in ts
                if (start_ms is None or t.get("time", 0) >= start_ms) and (end_ms is None or t.get("time", 0) <= end_ms)]
        return sorted(rows, key=lambda t: -t.get("time", 0))[:100]     # как биржа: новые первыми, не больше 100

    def futures_balance(self):
        return [{"asset": "USDT", "balance": str(self.balance), "unrealizePnl": "0"}]

    def futures_positions(self):
        """Позиция стороны = исполненные входы − исполненные тейки (по ордерам имитатора, включая частичные)."""
        size = {"LONG": 0.0, "SHORT": 0.0}
        for o in self.orders.values():
            q = float(o.get("executedQty") or 0)
            if q > 0:
                size[o["positionSide"]] += -q if o["reduceOnly"] else q
        return [{"symbol": self.symbol, "side": k, "size": f"{max(v, 0):.4f}"} for k, v in size.items()]
