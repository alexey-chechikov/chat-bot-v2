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
import threading
import time

from services.weex_grid import engine as eg

logger = logging.getLogger(__name__)
# Один владелец конфига/учёта: проход сетки и команды /weex не пересекаются (перепроверка GPT 10.10:
# проход, начатый до /weex start, сохранял старый halted=true поверх команды).
STATE_LOCK = threading.RLock()
_SIGMA: dict[str, dict] = {}
# 20.10 (разбор GPT ec48a3a §2, пример okxbot): общая сверка позиции биржи с суммой лотов ВСЕХ живых сеток символа/стороны.
# Сетка сама сравнивает позицию только со своими лотами: на BTC LONG четыре сетки, и каждой хватает всей позиции —
# нехватку под лоты соседей она не видит. Лотов больше позиции AUDIT_PASSES проходов подряд → новые входы на стороне
# запрещены (стоящий вход снимается, тейки работают), одно сообщение; столько же совпадений подряд → снято.
# Позиция больше лотов (ручная/неизвестная) — без блокировки. Сторона из release_sides и сторона с эпизодом тренда — не
# сверяются. Нечитаемые данные — проход сверки пропускается, состояние не меняется.
AUDIT_PASSES = 3
AUDIT_FILE = eg.STATE.with_name("weex_position_audit.json")
TREND_IDLE_SEC = 300     # 23.10: тренд без эпизода/заявки — не чаще раза в 5 мин (Runner._trend_due)


def position_gaps(grids: list[dict], busy: set, positions: list) -> dict:
    """grids — живые сетки: {"symbol", "sides", "release_sides", "qty_step", "state"}; busy — {(symbol, side)} без
    сверки (эпизод тренда); positions — ответ futures_positions. → {"SYM:SIDE": {"lots", "exchange", "deficit"}}.
    Сторона, переданная оператору (release_sides), не сверяется, ПОКА ею не владеет другая живая сетка (21.10: шорт-сетка
    SB на BTCUSDT SHORT рядом с переданным шортом основной BTC — её лоты сверяются; ручной шорт оператора даёт избыток,
    а не нехватку, и входы не блокирует)."""
    want, tol, skip = {}, {}, set(busy)
    owned = {(g["symbol"], s) for g in grids for s in (g.get("sides") or [])}
    for g in grids:
        for side in ("LONG", "SHORT"):
            key = (g["symbol"], side)
            if side in (g.get("release_sides") or []) and side not in (g.get("sides") or []):
                if key not in owned:
                    skip.add(key)
                continue
            lots = (g.get("state") or {}).get(side, {}).get("lots") or []
            want[key] = want.get(key, 0.0) + sum(float(l["qty"]) for l in lots)
            tol[key] = min(tol.get(key, 1.0), float(g.get("qty_step") or 0.0001) / 2)
    have = {}
    for p in positions or []:
        key = (p.get("symbol"), p.get("side"))
        have[key] = have.get(key, 0.0) + float(p.get("size") or 0)
    out = {}
    for key, q in want.items():
        if key in skip:
            continue
        size = have.get(key, 0.0)
        out[f"{key[0]}:{key[1]}"] = {"lots": round(q, 8), "exchange": round(size, 8), "deficit": q - size > tol[key]}
    return out


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
        self.trend = None
        self._trend_last = 0.0
        self.audit = self._audit_load()

    def _trend_due(self, now: float) -> bool:
        """23.10 (оператор «да»): трендовый бот 4ч идёт в том же цикле, что сетки, и его проход занимал медиану 8 с, до
        58 с (замер по меткам учёта) — тейки сеток ставились с задержкой до минуты. Без эпизода и неподтверждённой
        заявки — не чаще раза в TREND_IDLE_SEC (вход по закрытию 4ч бара запаздывает максимум на это время). Эпизод или
        pending в живом или холостом учёте любой монеты — каждый проход, как раньше. Нечитаемо — каждый проход (тренд
        сам остановится с ошибкой)."""
        if now - self._trend_last >= TREND_IDLE_SEC:
            return True
        try:
            from services.weex_trend import engine as te
            from services.weex_trend.loop import files as trend_files, symbols as trend_symbols
            for sym in trend_symbols(te.load_config()):
                for dry in (False, True):
                    p = trend_files(dry, sym)[0]
                    if p.exists():
                        st = json.loads(p.read_text(encoding="utf-8"))
                        if st.get("episode") or st.get("pending"):
                            return True
        except Exception:                                       # noqa: BLE001
            return True
        return False

    # ---------------------------------------------------------------- общая сверка позиции (20.10)
    def _audit_load(self) -> dict:
        """Блокировки сверки переживают перезапуск: иначе рестарт молча вернул бы входы при нехватке позиции."""
        try:
            return json.loads(AUDIT_FILE.read_text(encoding="utf-8")) if AUDIT_FILE.exists() else {}
        except (OSError, ValueError):
            logger.exception("weex_grid.position_audit_load_failed")
            return {}

    def _audit_blocks(self, symbol: str) -> dict:
        return {k.split(":")[1]: r["reason"] for k, r in self.audit.items()
                if k.split(":")[0] == symbol and r.get("blocked")}

    def _trend_busy(self) -> set:
        """Стороны с эпизодом тренда (его объём не в лотах сеток) — не сверяются; нечитаемо → исключение."""
        from services.weex_trend import engine as te
        from services.weex_trend.loop import files as trend_files, symbols as trend_symbols
        busy = set()
        for sym in trend_symbols(te.load_config()):
            p = trend_files(False, sym)[0]
            ep = json.loads(p.read_text(encoding="utf-8")).get("episode") if p.exists() else None
            if ep:
                busy.add((sym, ep.get("side")))
        return busy

    def _position_audit(self) -> None:
        try:
            grids = []
            for name in eg.GRIDS:
                cfg = grid_config(name)
                if cfg["dry_run"]:
                    continue
                p = run_files(name, False)[0]
                grids.append({"symbol": cfg["symbol"], "sides": cfg.get("sides") or [],
                              "release_sides": cfg.get("release_sides") or [],
                              "qty_step": cfg.get("qty_step"),
                              "state": json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}})
            gaps = position_gaps(grids, self._trend_busy(), self._client().futures_positions())
        except Exception:                                       # noqa: BLE001 — неполно: сверку пропускаем
            logger.exception("weex_grid.position_audit_skipped")
            return
        self._audit_apply(gaps)

    def _audit_apply(self, gaps: dict) -> None:
        changed = False
        for key, g in gaps.items():
            r = self.audit.setdefault(key, {"bad": 0, "ok": 0, "blocked": False, "reason": ""})
            r["last"] = {"lots": g["lots"], "exchange": g["exchange"], "t": time.time()}
            if g["deficit"]:
                r["bad"], r["ok"] = r["bad"] + 1, 0
            else:
                r["ok"], r["bad"] = r["ok"] + 1, 0
            if not r["blocked"] and r["bad"] >= AUDIT_PASSES:
                r["blocked"], changed = True, True
                r["reason"] = f"на бирже {g['exchange']:g}, лотов сеток {g['lots']:g}"
                logger.error("weex_grid.position_mismatch %s lots=%s exchange=%s", key, g["lots"], g["exchange"])
                self._send(f"🛑 Сверка позиции {key}: на бирже {g['exchange']:g}, а лотов всех сеток {g['lots']:g} — "
                           f"{AUDIT_PASSES} прохода подряд. Новые входы на этой стороне остановлены, тейки работают. "
                           f"Снимется само после {AUDIT_PASSES} совпадений подряд.") if self.send else None
            elif r["blocked"] and r["ok"] >= AUDIT_PASSES:
                r["blocked"], r["reason"], changed = False, "", True
                logger.warning("weex_grid.position_restored %s", key)
                self._send(f"✅ Сверка позиции {key} восстановлена: на бирже {g['exchange']:g}, лотов "
                           f"{g['lots']:g} — входы снова разрешены.") if self.send else None
        try:
            eg.atomic_write(AUDIT_FILE, json.dumps(self.audit, ensure_ascii=False, indent=1))
        except OSError:
            logger.exception("weex_grid.position_audit_save_failed")
        if changed:
            logger.info("weex_grid.position_audit %s", {k: r["blocked"] for k, r in self.audit.items()})

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
        """Проход по всем сеткам ПО ОЧЕРЕДИ; ошибка одной не мешает остальным, но после прохода поднимается
        наверх (цикл делает паузу 60 с и шлёт одно предупреждение в 30 мин).
        18.10: параллельный проход (834887d) откачен — разбор GPT (docs/WEEX_GPT_SECTION2_REVIEW_2026-10-18.md §2):
        найденная сирота не уменьшала долю соседей, ask×1.01 не ограничивал итоговый вход → потолок мог быть превышен.
        Выигрыш был мал (25–30 с против 30–45 с). Вернуть параллель — только с общим атомарным резервом риска."""
        first = None
        for name in eg.GRIDS:
            try:
                with STATE_LOCK:
                    # свободное — заново перед каждой сеткой: входы предыдущей уже в её учёте (11.10, разбор
                    # GPT: одно место раздавалось всем сеткам и тренду)
                    self.tick_one(name, self._portfolio_free())
            except eg.GridHalt as exc:
                # битый конфиг/учёт: эта сетка стоит (ничего не торгует), остальные работают
                logger.error("weex_grid.halt grid=%s err=%s", name, exc)
                if self.send and time.time() - self.last_halt.get(name, 0.0) > 1800:
                    if self._send(f"🛑 Сетка WEEX {name} остановлена: {str(exc)[:250]}. Ордера на бирже не трогаю; "
                                  f"нужно восстановить файл."):
                        self.last_halt[name] = time.time()
            except Exception as exc:                            # noqa: BLE001
                logger.exception("weex_grid.tick_failed grid=%s", name)
                first = first or RuntimeError(f"{name}: {exc}")
        with STATE_LOCK:
            self._position_audit()                              # после всех сеток: их лоты уже в учёте
        # трендовый бот ETH (services/weex_trend) — в том же цикле, ошибки отделены от сеток
        try:
            with STATE_LOCK:
                if self.trend is None:
                    from services.weex_trend.loop import TrendRunner
                    self.trend = TrendRunner(self._client, self.send)
                now = time.time()
                if self._trend_due(now):                            # 23.10: без позиции — раз в 5 мин
                    self._trend_last = now
                    self.trend.tick(portfolio_free=self._portfolio_free)     # функция — заново перед каждой монетой
        except Exception as exc:                                # noqa: BLE001
            logger.exception("weex_trend.tick_failed")
            first = first or RuntimeError(f"тренд: {exc}")
        if first:
            raise first

    def _portfolio_free(self) -> float | None:
        """Свободное место под общим потолком счёта (живые сетки + живой тренд)."""
        try:
            from services.weex_grid import portfolio
            from services.weex_trend import engine as te
            from services.weex_trend.loop import files as trend_files, symbols as trend_symbols
            grids = [run_files(n, False)[0] for n in eg.GRIDS]
            try:
                tsyms = trend_symbols(te.load_config())
            except eg.GridHalt:
                tsyms = ["ETHUSDT"]
            free, _, _ = portfolio.free_usd(grids, [trend_files(False, s)[0] for s in tsyms])
            return free
        except eg.GridHalt:
            return 0.0                                          # битый конфиг потолка — новых входов нет
        except Exception:                                       # noqa: BLE001
            logger.exception("weex_portfolio.failed")
            return 0.0

    def tick_one(self, name: str, free: float | None = None) -> None:
        cfg = grid_config(name)
        if not cfg["dry_run"] and free is not None:
            cfg = {**cfg, "portfolio_free_usd": free}
        if not cfg["dry_run"]:
            cfg = {**cfg, "audit_block": self._audit_blocks(cfg["symbol"])}
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
        # name — знак ордеров сетки проверяется на совпадение с другими сетками (совпал/негоден → GridHalt, ни одного
        # запроса к бирже от этой сетки)
        grid = eg.Grid(client, cfg, state_path=st_path, journal_path=jr_path, sigma_fn=lambda: sigma24(sym),
                       send_fn=self.send, name=name)
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
        if not any(st.get(s, {}).get(k) for s in ("LONG", "SHORT")
                   for k in ("entry", "lots", "pending", "strays", "fee_book")):
            return                            # живых остатков нет (сироты и недосверенные комиссии — тоже остатки)
        live_cfg = {**cfg, "dry_run": False, "enabled": False}
        eg.Grid(self._client(), live_cfg, state_path=st_path, journal_path=jr_path, send_fn=self.send, name=name).tick()

    def _send(self, text: str) -> bool:
        """True — доставлено. Интервал «раз в 30 мин» считается от УДАЧНОЙ доставки (15.10, разбор GPT P2: метка
        ставилась до отправки, сбой Telegram глотался — оператор не получал ни первого сообщения, ни повтора полчаса);
        недоставленное повторяется на следующей ошибке (цикл после ошибки ждёт ≥60 с)."""
        try:
            ok = self.send(text) is not False
        except Exception:                                       # noqa: BLE001
            logger.exception("weex_grid.send_failed")
            return False
        if not ok:
            logger.warning("weex_grid.send_not_delivered")
        return ok

    def on_error(self, exc: Exception) -> None:
        logger.exception("weex_grid.tick_failed")
        if self.send and time.time() - self.last_err > 1800:
            if self._send(f"⚠️ Сетка WEEX: ошибка прохода — {str(exc)[:200]}. Повторю через минуту."):
                self.last_err = time.time()


def card(name: str | None = None) -> str:
    """Карточка для /weex (по текущему режиму); без имени — все сетки."""
    from services.weex_api.client import WeexClient
    real = WeexClient()
    real.sync_time()
    out = []
    for n in ([name] if name else eg.GRIDS):
        try:
            cfg = grid_config(n)
            # журнал — той же сетки и режима (14.10, ревью L3-1: с подставным путём миграция передач из журнала не
            # видела записей, и карточка до первого прохода показывала итог без переданного мешка). Карточка журнал
            # только читает
            st_path, jr_path = run_files(n, bool(cfg["dry_run"]))
            sym = cfg["symbol"]
            client = eg.DryExchange(lambda: real.book(sym), symbol=sym) if cfg["dry_run"] else real
            g = eg.Grid(client, cfg, state_path=st_path, journal_path=jr_path, name=n)
            out.append(g.card())
        except eg.GridHalt as exc:
            out.append(f"🛑 СЕТКА WEEX {n} — ОСТАНОВЛЕНА: {exc}")
    if not name:
        try:
            from services.weex_trend.loop import card as trend_card
            out.append(trend_card())
        except Exception as exc:                                # noqa: BLE001
            out.append(f"📈 ТРЕНД: карточка недоступна ({exc})")
        out.append(_account_line(real))
    return "\n\n".join(out)


def _account_line(client) -> str:
    """Общий потолок (занято/свободно) и фандинг по символам живых сеток с начала их журналов."""
    lines = []
    try:
        from services.weex_grid import portfolio
        from services.weex_trend import engine as te
        from services.weex_trend.loop import files as trend_files, symbols as trend_symbols
        free, used, cap = portfolio.free_usd([run_files(n, False)[0] for n in eg.GRIDS],
                                             [trend_files(False, s)[0] for s in trend_symbols(te.load_config())])
        lines.append(f"💼 Счёт: занято ${used:,.0f} из общего потолка ${cap:,.0f}")
    except Exception as exc:                                    # noqa: BLE001
        lines.append(f"💼 Счёт: потолок недоступен ({exc})")
    try:
        from services.weex_api.client import FUTURES
        start = None
        if eg.JOURNAL.exists():
            first = eg.JOURNAL.read_text(encoding="utf-8").splitlines()[:1]
            if first:
                from datetime import datetime
                start = int(datetime.fromisoformat(json.loads(first[0])["ts"]).timestamp() * 1000)
        body = {"incomeType": "position_funding", "limit": 100}
        if start:                                       # биржа принимает начало только вместе с концом
            body["startTime"] = start
            body["endTime"] = int(time.time() * 1000)
        r = client.post(FUTURES, "/capi/v3/account/income", body) or {}
        by_sym: dict[str, float] = {}
        for x in r.get("items", []):
            by_sym[x.get("symbol")] = by_sym.get(x.get("symbol"), 0.0) + float(x.get("income") or 0)
        if by_sym:
            lines.append("фандинг (вся позиция символа: все сетки символа и ручные): " +
                         ", ".join(f"{k} ${v:+.2f}" for k, v in by_sym.items()))
    except Exception:                                           # noqa: BLE001
        logger.exception("weex_card.funding_failed")
    return "\n".join(lines)


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
         "xau": "XAU", "gold": "XAU", "золото": "XAU", "голд": "XAU",
         # 15.10: три сетки BTCUSDT для сравнения (шаг 0.1, цели 0.34/0.49/0.89) — /weex b34 live|start|stop|set …
         "b34": "B34", "b49": "B49", "b89": "B89",
         # 21.10: заряженные шорт-сетки (без режима SMA), запуск — /weex sb go или кнопкой /panel
         "sb": "SB", "se": "SE"}
BUMP_USD = 50.0          # шаг кнопок «ордер ±» (21.10): ≈$50 по текущей цене, округлённо к шагу объёма контракта


def _label(name: str, cfg: dict) -> str:
    return eg.grid_label(name, cfg["symbol"])


def _cmd(name: str) -> str:
    """Начало команды сетки: «/weex » у BTC (по умолчанию), «/weex eth » и т.п. у остальных."""
    return "/weex " + ("" if name == "BTC" else name.lower() + " ")


def split_message(text: str, limit: int = 4096) -> list[str]:
    """Текст для Telegram кусками не длиннее limit (предел сообщения): режется по пустым строкам между карточками, затем
    по строкам, в крайнем случае — по limit знаков. 15.10: шесть сеток + тренд + счёт не влезали в 4096 и обрезались —
    пропадала строка общего потолка."""
    tokens: list[tuple[str, str]] = []
    for block in text.split("\n\n"):
        pieces = [block] if len(block) <= limit else [ln[i:i + limit] for ln in block.split("\n")
                                                       for i in range(0, max(len(ln), 1), limit)]
        tokens += [("\n\n" if i == 0 else "\n", p) for i, p in enumerate(pieces)]
    parts: list[str] = []
    cur: str | None = None
    for sep, piece in tokens:
        if cur is None:
            cur = piece
        elif len(cur) + len(sep) + len(piece) <= limit:
            cur += sep + piece
        else:
            parts.append(cur)
            cur = piece
    parts.append(cur or "")
    return parts


def set_params(arg: str, price_fn, name: str = "BTC") -> str:
    """/weex [eth] set цель 0.21 ордер 100 — меняет параметры (действуют на НОВЫЕ ордера).
    ордер — в долларах (пересчёт в монету по текущей цене с шагом объёма контракта), qty — в монете."""
    toks = arg.replace("=", " ").replace(",", ".").split()
    cfg = grid_config(name)
    coin = cfg["symbol"].replace("USDT", "")
    if len(toks) < 2 or len(toks) % 2:
        return (f"Формат: {_cmd(name)}set цель 0.21 ордер 100 "
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
    return (f"✅ Сетка WEEX {_label(name, cfg)}: шаг {cfg['step_pct']}%, цель {cfg['target_pct']}%, ордер {cfg['order_qty']} {coin} "
            f"(≈${per:,.0f}). Потолок ${float(cfg['max_notional_usd']):,.0f} на сторону → до "
            f"{min(n_cap, int(cfg['max_lots_per_side']))} ордеров; "
            f"стоп дня {'ВЫКЛ' if stop <= 0 else f'${stop:,.0f}'}; стресс-бюджет {'ВЫКЛ' if stress <= 0 else f'{stress:.0%}'}.\n"
            f"Действует на новые ордера; уже стоящие тейки остаются на старой цели.")


def _live_sides(name: str) -> list[str]:
    """Стороны, где у живого учёта сетки есть что закрывать (лоты, вход, незавершённое закрытие)."""
    p = run_files(name, False)[0]
    if not p.exists():
        return []
    try:
        st = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise eg.StateCorrupt(f"живой учёт {p.name} не читается: {exc}") from exc
    return [s for s in eg.DIR if (st.get(s) or {}).get("lots") or (st.get(s) or {}).get("entry")
            or (st.get(s) or {}).get("flatten")]


def close_grid(name: str) -> str:
    """Закрыть позиции сетки по рынку (только лоты бота) и выключить её: enabled=false + flatten_request — движок на
    следующем проходе снимает вход и тейки и шлёт один reduceOnly на объём лотов (как закрытие по режиму)."""
    cfg = grid_config(name)
    sides = [s for s in _live_sides(name) if s not in (cfg.get("release_sides") or []) or s in cfg["sides"]]
    cfg["enabled"] = False
    cfg["flatten_request"] = sides
    save_grid_config(cfg, name)
    tag = f"Сетка WEEX {_label(name, cfg)}"
    if not sides:
        return f"⏸ {tag}: позиций бота нет — сетка выключена."
    return (f"⛔ {tag}: закрываю по рынку лоты бота ({', '.join(sides)}) и выключаю. Ручные позиции не трогаю. "
            f"Включить снова — {_cmd(name)}go.")


def bump_qty(name: str, sign: int, price_fn) -> str:
    """Ордер ± ≈$50 (кнопки панели): новый объём = текущий ± round(50 / цена, шаг объёма), в пределах [шаг; qty_max]
    сетки — через set_params (та же проверка, что /weex set)."""
    cfg = grid_config(name)
    qstep, qmax = float(cfg["qty_step"]), float(cfg["qty_max"])
    price = price_fn()
    delta = max(qstep, round(BUMP_USD / price / qstep) * qstep)
    new = min(qmax, max(qstep, float(cfg["order_qty"]) + sign * delta))
    if abs(new - float(cfg["order_qty"])) < qstep / 2:
        return f"Ордер {_label(name, cfg)} уже на границе: {cfg['order_qty']} (допустимо {qstep:g}…{qmax:g})."
    qdec = max(0, -int(math.floor(math.log10(qstep) + 1e-9)))
    return set_params(f"qty {new:.{qdec}f}", lambda: price, name)


def pause_all() -> str:
    """Пауза всем живым сеткам: enabled=false — новые входы сняты, тейки работают, закрытие по режиму — как было."""
    done = []
    for name in eg.GRIDS:
        cfg = grid_config(name)
        if cfg["enabled"] and not cfg["dry_run"]:
            cfg["enabled"] = False
            save_grid_config(cfg, name)
            done.append(_label(name, cfg))
    return ("⏸ Пауза: " + ", ".join(done) + " — новые входы сняты, тейки остаются.") if done else \
        "⏸ Живых включённых сеток нет — пауза не нужна."


def close_all() -> str:
    """Закрыть позиции всех ботов (только лоты бота, ручные позиции не трогаются) и выключить сетки."""
    out = [close_grid(name) for name in eg.GRIDS if not grid_config(name)["dry_run"] and _live_sides(name)]
    return "\n".join(out) if out else "Позиций ботов нет — закрывать нечего."


def command(arg: str) -> str:
    """/weex [eth|btc] [start|stop|live|dry|set ...] — управление; без аргумента — карточки всех сеток.
    Без имени монеты команды относятся к BTC (как было до 09.10)."""
    try:
        with STATE_LOCK:
            return _command(arg)
    except eg.GridHalt as exc:
        return f"🛑 Сетка WEEX не тронута: {exc}. Нужно восстановить файл."


def _command(arg: str) -> str:
    raw = (arg or "").strip()
    first = raw.split(None, 1)[0].lower() if raw else ""
    if first in ("pauseall", "паузавсем"):             # 21.10: кнопка «пауза всем»
        return pause_all()
    if first in ("closeall", "закрытьвсе"):            # 21.10: кнопка «закрыть позиции ботов»
        return close_all()
    if first in ("тренд", "trend"):                    # трендовый бот ETH: /weex тренд …
        from services.weex_trend.loop import command as trend_command
        return trend_command(raw.split(None, 1)[1] if " " in raw else "")
    if first in ("портфель", "portfolio"):             # общий потолок счёта: /weex портфель 12000
        from services.weex_grid import portfolio
        cfg = portfolio.load()
        rest = raw.split()[1:]
        if rest:
            try:
                val = float(rest[0].replace("$", "").replace(",", "."))
            except ValueError:
                return "Формат: /weex портфель 12000 (потолок себестоимости всех живых позиций, $)"
            if not 500 <= val <= 100_000:
                return f"{val:g} вне [500; 100000] — не меняю."
            cfg["gross_cap_usd"] = val
            eg.atomic_write(portfolio.CONFIG, json.dumps(cfg, ensure_ascii=False, indent=1))
        return f"💼 Общий потолок счёта: ${float(cfg['gross_cap_usd']):,.0f} (себестоимость всех живых позиций сеток и тренда)."
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
    tag = f"Сетка WEEX {_label(name, cfg)}"
    if arg in ("qty+", "ордер+", "qty-", "ордер-"):
        from services.weex_api.client import WeexClient

        def price():
            b, a = WeexClient().book(cfg["symbol"])
            return (b + a) / 2
        return bump_qty(name, 1 if arg.endswith("+") else -1, price)
    if arg in ("close", "закрыть"):
        return close_grid(name)
    if arg in ("go", "запуск"):                          # 21.10: живой запуск одной кнопкой (заряженные сетки)
        cfg["dry_run"] = False
        arg = "start"
    if arg in ("start", "старт"):
        cfg["enabled"] = True
        cfg.pop("flatten_request", None)                # закрытие по команде снято — сетка снова набирает
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
        how = "" if cfg["enabled"] else f" (включить — {_cmd(name)}start)"
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
