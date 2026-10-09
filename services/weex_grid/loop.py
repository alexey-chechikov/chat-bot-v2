"""Цикл сетки WEEX внутри app_runner: раз в poll_sec — один проход Grid.tick().

dry_run=true — ордера НЕ отправляются: живые цены WEEX, исполнения считает имитатор,
отдельные файлы состояния/журнала (*_dry), чтобы учебные лоты не смешались с живыми.
dry_run=false — живые ордера; при enabled=false цикл всё равно сверяется с биржей и
снимает свои входные ордера (тейки остаются).
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import time

from services.weex_grid import engine as eg

logger = logging.getLogger(__name__)
_SIGMA: dict[str, dict] = {}


def sigma24(symbol: str = "BTCUSDT") -> float | None:
    """σ за сутки своей монеты (10.10, разбор GPT: для ETH/золота бралась σ BTC), кэш на час."""
    c = _SIGMA.setdefault(symbol, {"t": 0.0, "v": None})
    if time.time() - c["t"] > 3600:
        try:
            from services.grid_model.stress_budget import sigma24 as s24
            c["v"] = s24(symbol)
        except Exception:                                       # noqa: BLE001
            logger.exception("weex_grid.sigma_failed symbol=%s", symbol)
        c["t"] = time.time()
    return c["v"]


def grid_config(name: str = "BTC") -> dict:
    if name == "BTC":
        return eg.load_config()                     # путь по умолчанию (подменяется в тестах)
    return eg.load_config(eg.grid_files(name)[0], eg.TEMPLATES.get(name))


def save_grid_config(cfg: dict, name: str = "BTC") -> None:
    if name == "BTC":
        eg.save_config(cfg)
    else:
        eg.save_config(cfg, eg.grid_files(name)[0])


def run_files(name: str, dry: bool):
    _, st, jr = eg.grid_files(name)
    if name == "BTC":
        st, jr = eg.STATE, eg.JOURNAL
    if dry:
        st, jr = st.with_name(st.stem + "_dry.json"), jr.with_name(jr.stem + "_dry.jsonl")
    return st, jr


class Runner:
    def __init__(self, send_fn=None):
        self.send = send_fn
        self.real = None
        self.dry_ex: dict[str, eg.DryExchange] = {}
        self.last_err = 0.0
        self.last_halt: dict[str, float] = {}
        self.mode: dict[str, tuple] = {}

    def _client(self):
        from services.weex_api.client import WeexClient
        if self.real is None:
            self.real = WeexClient()
            self.real.sync_time()
            self._synced = time.time()
        elif time.time() - self._synced > 3600:
            self.real.sync_time()
            self._synced = time.time()
        return self.real

    def tick(self) -> None:
        """Проход по всем сеткам; ошибка одной не мешает остальным, но после прохода поднимается
        наверх (цикл делает паузу 60 с и шлёт одно предупреждение в 30 мин)."""
        first = None
        for name in eg.GRIDS:
            try:
                self.tick_one(name)
            except eg.GridHalt as exc:
                # битый конфиг/учёт: эта сетка стоит (ничего не торгует), остальные работают
                logger.error("weex_grid.halt grid=%s err=%s", name, exc)
                if self.send and time.time() - self.last_halt.get(name, 0.0) > 1800:
                    self.last_halt[name] = time.time()
                    try:
                        self.send(f"🛑 Сетка WEEX {name} остановлена: {str(exc)[:250]}. Ордера на бирже не трогаю; "
                                  f"нужно восстановить файл.")
                    except Exception:                           # noqa: BLE001
                        logger.exception("weex_grid.send_failed")
            except Exception as exc:                            # noqa: BLE001
                logger.exception("weex_grid.tick_failed grid=%s", name)
                first = first or RuntimeError(f"{name}: {exc}")
        if first:
            raise first

    def tick_one(self, name: str) -> None:
        cfg = grid_config(name)
        dry = bool(cfg["dry_run"])
        if dry:
            self._live_leftovers(name, cfg)
        if dry and not cfg["enabled"]:
            return
        real = self._client()
        st_path, jr_path = run_files(name, dry)
        if dry:
            if name not in self.dry_ex:
                # учебные ордера живут только в памяти имитатора → после перезапуска с чистого листа
                st_path.unlink(missing_ok=True)
                sym = cfg["symbol"]
                self.dry_ex[name] = eg.DryExchange(lambda: real.book(sym), symbol=sym)
            client = self.dry_ex[name]
        else:
            client = real
        mode = ("dry" if dry else "live", bool(cfg["enabled"]))
        if mode != self.mode.get(name):
            logger.info("weex_grid.mode grid=%s dry=%s enabled=%s", name, dry, cfg["enabled"])
            self.mode[name] = mode
        sym = cfg["symbol"]
        grid = eg.Grid(client, cfg, state_path=st_path, journal_path=jr_path, sigma_fn=lambda: sigma24(sym),
                       send_fn=self.send)
        grid.tick()

    def _live_leftovers(self, name: str, cfg: dict) -> None:
        """Холостой режим, а в живом учёте остались входные ордера/лоты (переключили live→dry):
        живой проход с enabled=false — входы снимаются (исполненное записывается), тейки
        остаются и учитываются. Без этого живые входы висели бы на бирже без присмотра (10.10)."""
        st_path, jr_path = run_files(name, False)
        if not st_path.exists():
            return
        try:
            st = json.loads(st_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise eg.StateCorrupt(f"живой учёт {st_path.name} не читается: {exc}") from exc
        if not any(st.get(s, {}).get("entry") or st.get(s, {}).get("lots") or st.get(s, {}).get("pending")
                   for s in ("LONG", "SHORT")):
            return
        live_cfg = {**cfg, "dry_run": False, "enabled": False}
        eg.Grid(self._client(), live_cfg, state_path=st_path, journal_path=jr_path, send_fn=self.send).tick()

    def on_error(self, exc: Exception) -> None:
        logger.exception("weex_grid.tick_failed")
        if self.send and time.time() - self.last_err > 1800:
            self.last_err = time.time()
            try:
                self.send(f"⚠️ Сетка WEEX: ошибка прохода — {str(exc)[:200]}. Повторю через минуту.")
            except Exception:                                   # noqa: BLE001
                logger.exception("weex_grid.send_failed")


def card(name: str | None = None) -> str:
    """Карточка для /weex (по текущему режиму); без имени — все сетки."""
    from services.weex_api.client import WeexClient
    real = WeexClient()
    real.sync_time()
    out = []
    for n in ([name] if name else eg.GRIDS):
        try:
            cfg = grid_config(n)
            st_path, _ = run_files(n, bool(cfg["dry_run"]))
            sym = cfg["symbol"]
            client = eg.DryExchange(lambda: real.book(sym), symbol=sym) if cfg["dry_run"] else real
            g = eg.Grid(client, cfg, state_path=st_path, journal_path=eg.JOURNAL.with_name("_unused.jsonl"))
            out.append(g.card())
        except eg.GridHalt as exc:
            out.append(f"🛑 СЕТКА WEEX {n} — ОСТАНОВЛЕНА: {exc}")
    return "\n\n".join(out)


SET_KEYS = {"target": "target_pct", "цель": "target_pct", "таргет": "target_pct",
            "step": "step_pct", "шаг": "step_pct",
            "qty": "order_qty", "usd": "usd", "ордер": "usd",
            "cap": "max_notional_usd", "потолок": "max_notional_usd",
            "stop": "daily_loss_stop_usd", "стоп": "daily_loss_stop_usd",
            "max": "max_lots_per_side", "макс": "max_lots_per_side",
            "стресс": "stress_budget_frac", "stress": "stress_budget_frac"}
# 0 у стопа дня и стресс-бюджета = выключено (оператор 09.10: «стопы снимай, ограничиваем количеством»)
LIMITS = {"target_pct": (0.05, 5.0), "step_pct": (0.05, 5.0), "max_notional_usd": (10.0, 20_000.0),
          "daily_loss_stop_usd": (0.0, 2_000.0), "max_lots_per_side": (1, 200),
          "stress_budget_frac": (0.0, 1.0)}          # объём ордера — по qty_step/qty_max сетки
NAMES = {"btc": "BTC", "бтк": "BTC", "биток": "BTC", "биткоин": "BTC",
         "eth": "ETH", "эфир": "ETH", "эth": "ETH",
         "xau": "XAU", "gold": "XAU", "золото": "XAU", "голд": "XAU"}


def set_params(arg: str, price_fn, name: str = "BTC") -> str:
    """/weex [eth] set цель 0.21 ордер 100 — меняет параметры (действуют на НОВЫЕ ордера).
    ордер — в долларах (пересчёт в монету по текущей цене с шагом объёма контракта), qty — в монете."""
    toks = arg.replace("=", " ").replace(",", ".").split()
    cfg = grid_config(name)
    coin = cfg["symbol"].replace("USDT", "")
    if len(toks) < 2 or len(toks) % 2:
        return (f"Формат: /weex {'' if name == 'BTC' else name.lower() + ' '}set цель 0.21 ордер 100 "
                f"[шаг 0.2] [потолок 1000] [стоп 30] [макс 50]\nордер — в долларах, qty — в {coin}.")
    qstep, qmax = float(cfg["qty_step"]), float(cfg["qty_max"])
    qdec = max(0, -int(math.floor(math.log10(qstep) + 1e-9)))
    limits = {**LIMITS, "order_qty": (qstep, qmax)}
    changes, price = {}, None
    for k, v in zip(toks[::2], toks[1::2]):
        key = SET_KEYS.get(k.lower())
        if key is None:
            return f"Не знаю параметр «{k}». Есть: цель, шаг, ордер, qty, потолок, стоп, макс."
        try:
            val = float(v.replace("$", ""))
        except ValueError:
            return f"«{v}» — не число."
        if key == "usd":
            price = price or price_fn()
            key, val = "order_qty", math.floor(val / price / qstep + 1e-9) * qstep
        lo, hi = limits[key]
        if not lo - 1e-12 <= val <= hi + 1e-12:
            return f"{key} = {val:g} вне допустимого [{lo:g}; {hi:g}] — не меняю."
        changes[key] = int(val) if key == "max_lots_per_side" else (f"{val:.{qdec}f}" if key == "order_qty" else val)
    cfg.update(changes)
    save_grid_config(cfg, name)
    price = price or price_fn()
    q = float(cfg["order_qty"])
    per = q * price
    n_cap = int(float(cfg["max_notional_usd"]) // per) if per > 0 else 0
    stop = float(cfg["daily_loss_stop_usd"])
    stress = float(cfg["stress_budget_frac"])
    return (f"✅ Сетка WEEX {cfg['symbol']}: шаг {cfg['step_pct']}%, цель {cfg['target_pct']}%, ордер {cfg['order_qty']} {coin} "
            f"(≈${per:,.0f}). Потолок ${float(cfg['max_notional_usd']):,.0f} на сторону → до "
            f"{min(n_cap, int(cfg['max_lots_per_side']))} ордеров; "
            f"стоп дня {'ВЫКЛ' if stop <= 0 else f'${stop:,.0f}'}; стресс-бюджет {'ВЫКЛ' if stress <= 0 else f'{stress:.0%}'}.\n"
            f"Действует на новые ордера; уже стоящие тейки остаются на старой цели.")


def command(arg: str) -> str:
    """/weex [eth|btc] [start|stop|live|dry|set ...] — управление; без аргумента — карточки всех сеток.
    Без имени монеты команды относятся к BTC (как было до 09.10)."""
    try:
        return _command(arg)
    except eg.GridHalt as exc:
        return f"🛑 Сетка WEEX не тронута: {exc}. Нужно восстановить файл."


def _command(arg: str) -> str:
    raw = (arg or "").strip()
    first = raw.split(None, 1)[0].lower() if raw else ""
    name = NAMES.get(first)
    if name:
        raw = raw.split(None, 1)[1] if " " in raw else ""
    arg = raw.lower()
    if arg.startswith("set") or arg.startswith("настр"):
        from services.weex_api.client import WeexClient
        cfg0 = grid_config(name or "BTC")

        def price():
            b, a = WeexClient().book(cfg0["symbol"])
            return (b + a) / 2
        return set_params(raw.split(None, 1)[1] if " " in raw else "", price, name or "BTC")
    if not arg:
        return card(name)
    name = name or "BTC"
    cfg = grid_config(name)
    tag = f"Сетка WEEX {cfg['symbol']}"
    if arg in ("start", "старт"):
        cfg["enabled"] = True
        for dry in (False, True):
            p, _ = run_files(name, dry)
            if not p.exists():
                continue
            try:
                st = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue                      # битый учёт не перезаписываем — его разберёт проход (GridHalt)
            st["halted"], st["halt_reason"] = False, ""
            eg.atomic_write(p, json.dumps(st, ensure_ascii=False, indent=1))
        save_grid_config(cfg, name)
        return f"▶️ {tag} включена (" + ("холостой режим" if cfg["dry_run"] else "ЖИВАЯ") + ")."
    if arg in ("stop", "стоп"):
        cfg["enabled"] = False
        save_grid_config(cfg, name)
        return f"⏸ {tag}: новые входы сняты, тейки остаются — позиция закроется сама."
    if arg in ("live", "живая"):
        cfg["dry_run"] = False
        save_grid_config(cfg, name)
        how = "" if cfg["enabled"] else f" (включить — /weex {'' if name == 'BTC' else name.lower() + ' '}start)"
        return f"🔴 {tag} переведена в ЖИВОЙ режим{how}."
    if arg in ("dry", "холостой"):
        cfg["dry_run"] = True
        save_grid_config(cfg, name)
        return f"🧪 {tag} в холостом режиме (ордера не отправляются)."
    return card(name)


async def weex_grid_loop(stop_event=None, send_fn=None) -> None:
    runner = Runner(send_fn)
    logger.info("weex_grid.start")
    while True:
        if stop_event is not None and stop_event.is_set():
            return
        try:
            poll = int(eg.load_config().get("poll_sec", 10))
        except eg.GridHalt:
            poll = 10                         # битый конфиг BTC — сетка BTC стоит, остальные работают
        try:
            await asyncio.to_thread(runner.tick)
        except Exception as exc:                                # noqa: BLE001
            runner.on_error(exc)
            poll = max(poll, 60)
        try:
            if stop_event is not None:
                await asyncio.wait_for(stop_event.wait(), poll)
                return
            await asyncio.sleep(poll)
        except asyncio.TimeoutError:
            continue
