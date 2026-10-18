"""Движок сетки WEEX: один проход tick() = сверка ордеров с биржей + решения + сохранение.

Состояние в state/weex_grid_state.json сохраняется АТОМАРНО после каждого действия, чтобы
перезапуск не плодил дубли. Журнал исполнений — state/weex_grid_journal.jsonl (цена, объём,
комиссия, мейкер/тейкер, orderId) — по нему меряем реальную цену круга и кэшбэк.

Целостность (разбор GPT по коду 65eae029, 10.10): битый конфиг или учёт НЕ подменяются
значениями по умолчанию (иначе сетка золота торговала бы конфигом BTC) — сетка встаёт
(GridHalt) до ручного восстановления; учёт помнит свой символ.

Несколько сеток на одном символе (15.10, сравнение B34/B49/B89 рядом с живой BTC): у каждой сетки свой знак в
clientOrderId (cid_tag, по умолчанию — первая буква символа, прежний формат b7gB…/b7gE…). Своими сетка считает только
ордера с префиксом b7g+свой знак — чужие (соседней сетки и ручные) не усыновляет, не снимает и не записывает в лишние.
Позиция стороны на бирже у сеток одного символа общая (хедж-режим); каждая сетка закрывает только объём своих лотов.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from services.weex_api.client import WeexIncomplete

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "state" / "weex_grid_config.json"
STATE = ROOT / "state" / "weex_grid_state.json"
JOURNAL = ROOT / "state" / "weex_grid_journal.jsonl"
PREFIX = "b7g"
TAG_RE = re.compile(r"[A-Za-z0-9]")      # знак сетки в clientOrderId: ровно один символ ASCII-буква/цифра
DIR = {"LONG": 1, "SHORT": -1}
LIVE = {"NEW", "PENDING", "CANCELING", "UNTRIGGERED", "UNACTIVATED", "PARTIALLY_FILLED"}   # может ещё исполниться
TERMINAL = {"FILLED", "CANCELED", "CANCELLED", "REJECTED", "EXPIRED"}   # подтверждённо больше не исполнится
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
# B34/B49/B89 (15.10, оператор: «запусти 3х ботов и сравнивай неделю») — три лонг-сетки BTCUSDT шаг 0.1%, ордер ≈$100,
# цели 0.34/0.49/0.89%, тот же режим SMA100, что у живой BTC; на одном символе с ней — свои знаки ордеров 3/4/8.
# Шаг 0.1 на истории хуже (CLAUDE.md, «мелкий шаг 0.1–0.15 хуже при любой комиссии») — это живая проверка малым размером.
GRIDS = ("BTC", "ETH", "XAU", "B34", "B49", "B89")
_BTC_CMP = {"symbol": "BTCUSDT", "sides": ["LONG"], "regime_sma": 100, "step_pct": 0.1, "order_qty": "0.0012",
            "qty_step": 0.0001, "price_tick": 0.1, "qty_max": 0.01, "max_lots_per_side": 15, "max_notional_usd": 1500.0,
            "daily_loss_stop_usd": 0.0, "stress_budget_frac": 0.0, "trail_min_move_pct": 0.05, "poll_sec": 10}
TEMPLATES = {
    "B34": {**_BTC_CMP, "cid_tag": "3", "target_pct": 0.34},
    "B49": {**_BTC_CMP, "cid_tag": "4", "target_pct": 0.49},
    "B89": {**_BTC_CMP, "cid_tag": "8", "target_pct": 0.89},
    # 09.10 развёртка 10 мес XAUUSDT (лонг+шорт, $100, потолок $4 000): шаг 0.75 итог +$349 — но «+$116 во
    # второй половине» был второй старт без старого мешка. После исправления методики (ордер 0.023, 50
    # ордеров, непрерывные половины) итог +$270.76, первая половина +$304.99, ВТОРАЯ −$34.23 — проверку по
    # времени НЕ проходит (разбор GPT 11.10), живым не включать. research/weex/sweep_XAUUSDT_*_q0.023.jsonl
    "XAU": {"symbol": "XAUUSDT", "sides": ["LONG", "SHORT"], "price_tick": 0.01, "qty_step": 0.001,
            "qty_max": 1.0, "order_qty": "0.023", "step_pct": 0.75, "target_pct": 0.3, "max_lots_per_side": 50,
            "max_notional_usd": 4000.0, "daily_loss_stop_usd": 0.0, "stress_budget_frac": 0.0},
    "ETH": {"symbol": "ETHUSDT", "sides": ["SHORT"], "price_tick": 0.01, "qty_step": 0.001, "qty_max": 0.5,
            # 09.10 развёртка 10 мес (research/weex/sweep_ETHUSDT_short_*.jsonl): шорт ETH в минусе во
            # ВСЕХ 30 ячейках, свежая половина −$979…−1 621 на ордер $100; наименее плохая 0.5/1.5 (−$88)
            "order_qty": "0.001", "step_pct": 0.5, "target_pct": 1.5, "max_lots_per_side": 50,
            "max_notional_usd": 1000.0, "daily_loss_stop_usd": 0.0, "stress_budget_frac": 0.0},
}
PENDING_TTL = 120.0      # с: раньше этого срока ордер с потерянным ответом «не дошедшим» не считается
# 15.10, разбор GPT P1: один годный пустой ответ истории — не доказательство (история может запаздывать). После TTL нужны
# PENDING_ABSENT_READS годных полных поисков подряд, разнесённых не меньше чем на PENDING_RECHECK, и пустые сделки окна;
# негодный/непрочитанный ответ обнуляет счёт подтверждений
PENDING_RECHECK = 30.0
PENDING_ABSENT_READS = 2
HANDOVER = "передано оператору"     # вид записи журнала о передаче стороны оператору
FEE_WINDOW = 3600.0      # с: сколько ждать появления комиссии по исполненному ордеру
FEE_POLL = 60.0          # с: как часто досверять комиссии
FEE_BATCH = 5            # курсоров комиссий за одну досверку (по кругу, давно не проверявшиеся первыми)
ORDER_FILLS_KEEP = 7 * 86400.0   # с: сколько хранить курсор исполнения завершённого ордера
# Эскалация неясного (14.10, ревью F1/L2-1: ордер с нечитаемой деталью замораживал тейк/вход/закрытие по режиму навсегда
# без единого сообщения): ордер бота с неясной деталью дольше UNKNOWN_ALERT_AFTER — сообщение, повтор не чаще
# UNKNOWN_ALERT_EVERY (сразу — если он начал держать закрытие по режиму или передачу стороны); прочие проглоченные
# сбои дольше ISSUE_ALERT_AFTER без чистого прохода — сообщение не чаще ISSUE_ALERT_EVERY
UNKNOWN_ALERT_AFTER = 300.0
UNKNOWN_ALERT_EVERY = 3600.0
ISSUE_ALERT_AFTER = 600.0
ISSUE_ALERT_EVERY = 1800.0
# 15.10, разбор GPT P2: недоставленное сообщение эскалации ждёт в alert_outbox учёта и повторяется через 1, 2, 5, затем
# каждые 10 мин до первой удачной доставки; часовой/получасовой интервал считается от удачной доставки, не от попытки
ALERT_RETRY = (60.0, 120.0, 300.0, 600.0)
# 15.10: несколько сеток на одном символе — окно ±10 мин вокруг ордера с потерянным ответом плотное. История WEEX
# параметр page ИГНОРИРУЕТ (любая страница = те же новейшие 100; окно startTime/endTime работает — проверено на счёте
# 15.10), поэтому повтор страницы → деление окна пополам; сделки — тоже делением окна (предел ответа 100). Не больше
# стольких запросов на один поиск; не хватило — поиск неполон («не дошёл» не доказан, намерение остаётся).
HISTORY_SPLIT_BUDGET = 8
TRADES_SPLIT_BUDGET = 8
TRADES_DETAILS = 20      # деталей незнакомых ордеров за один поиск по сделкам (прочитанные чужие запоминаются в намерении)
REGIME_RETRY = 30.0      # с: после сбоя дневок режим не перезапрашивается (4 сетки BTC — не 4 таймаута по 15 с за проход)


class GridHalt(RuntimeError):
    """Сетка не может безопасно торговать (битый конфиг/учёт, чужой символ) — до ручного восстановления."""


class ConfigError(GridHalt):
    pass


class StateCorrupt(GridHalt):
    pass


def cid_tag(cfg: dict) -> str:
    """Знак сетки в clientOrderId (b7g + знак + сторона + вид + время + счётчик). Своими сетка считает только ордера с
    префиксом b7g+знак (15.10: на одном символе несколько сеток — иначе сетка усыновляла бы и снимала ордера соседней).
    Ключа cid_tag в конфиге нет — прежний формат: первая буква символа (BTC 'B', ETH 'E', XAU 'X'), живые сетки владеют
    своими ордерами и учётом как раньше. Ключ есть, но не один знак [A-Za-z0-9] (в т.ч. null, '', 'B3') — ConfigError:
    сетка встаёт, знак по умолчанию НЕ подставляется."""
    if "cid_tag" not in cfg:
        sym = str(cfg.get("symbol") or "")
        if not sym or not TAG_RE.fullmatch(sym[0]):
            raise ConfigError(f"символ {sym!r}: нет знака сетки для clientOrderId")
        return sym[0]
    tag = cfg["cid_tag"]
    if not isinstance(tag, str) or not TAG_RE.fullmatch(tag):
        raise ConfigError(f"cid_tag {tag!r} негоден: нужен ровно один знак A–Z, a–z или 0–9")
    if tag.upper() in ("L", "S"):
        # 18.10, разбор GPT P2: старые номера BTC 09–10.10 — b7g + сторона (b7gL…/b7gS…) без буквы символа
        raise ConfigError(f"cid_tag {tag!r} занят старым форматом номеров BTC (b7gL…/b7gS…) — нужен другой знак")
    return tag


def grid_label(name: str | None, symbol: str) -> str:
    """Имя сетки в сообщениях и карточке: у прежних сеток (BTC, ETH, XAU) — символ, как раньше; у сетки со своим именем
    на символе другой монеты (B34 на BTCUSDT) — «B34 BTCUSDT», иначе четыре сетки BTC в сообщениях не различить."""
    return symbol if not name or str(symbol).upper().startswith(name.upper()) else f"{name} {symbol}"


def peek_config(name: str) -> dict | None:
    """Конфиг сетки ТОЛЬКО для чтения (файл не создаётся): нет файла — шаблон с умолчаниями; файл не читается или не
    объект — None (такая сетка сама встанет при загрузке: ConfigError)."""
    path = grid_files(name)[0]
    base = {**DEFAULT, **TEMPLATES.get(name, {})}
    if not path.exists():
        return dict(base)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return {**base, **raw} if isinstance(raw, dict) else None


def grid_tags(names=None) -> dict[str, str | None]:
    """{сетка: знак clientOrderId} по файлам конфигов, только чтение; None — конфиг не читается или знак негоден."""
    out: dict[str, str | None] = {}
    for n in (GRIDS if names is None else names):
        cfg = peek_config(n)
        try:
            out[n] = cid_tag(cfg) if cfg is not None else None
        except ConfigError:
            out[n] = None
    return out


def check_tag(name: str, cfg: dict) -> str:
    """Знак сетки name годен и не совпадает (без учёта регистра) со знаком другой сетки из GRIDS — иначе ConfigError:
    сетка не торгует (две сетки с одним знаком усыновляли бы и снимали ордера друг друга). Совпали — встают ОБЕ: каждая
    видит совпадение со своей стороны. Знаки других сеток — из их файлов конфигов, только чтение; сетка с нечитаемым
    конфигом или негодным знаком в сравнение не входит — она стоит сама."""
    tag = cid_tag(cfg)
    clash = sorted(n for n, t in grid_tags().items() if n != name and t is not None and t.upper() == tag.upper())
    if clash:
        raise ConfigError(f"знак ордеров «{tag}» сетки {name} совпадает со знаком сетки {', '.join(clash)} — сетки "
                          f"перепутали бы ордера друг друга; нужен свой cid_tag (одна буква или цифра)")
    return tag


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
    # привязки тейка восстановление считает только то, что ещё не учтено (перепроверка GPT 10.10).
    # transfers / transferred_mtm — передачи стороны оператору: остаток и его MTM на момент передачи (13.10, дополнение
    # GPT §3) — итог владения включает переданный мешок, передача не меняет заработанное
    return {"ref": None, "entry": None, "lots": [], "realized": 0.0, "fees": 0.0,
            "n_entries": 0, "n_tps": 0, "seq": 0, "turnover": 0.0, "pending": None,
            "strays": [], "fee_book": {}, "order_fills": {}, "transferred_mtm": 0.0, "transfers": []}


_REGIME_CACHE: dict[tuple, object] = {}    # (символ, дни) → (день, решение); ("fail", символ, дни) → время сбоя


def _fetch_daily(symbol: str, limit: int) -> list:
    import urllib.request
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1d&limit={limit}"
    return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "bot7"}),
                                             timeout=15).read())


def regime_up(symbol: str, sma_days: int = 100, now: float | None = None, fetch=None) -> bool | None:
    """Режим SMA (research/weex/regime_grid.py, проверен 11.10 на 2 годах BTC/ETH и на движке GinArea): закрытие
    ВЧЕРАШНЕГО дня UTC выше SMA за sma_days последовательных закрытых дней → True (лонг), ниже → False.
    Решение привязано к дню: в новых сутках — новый запрос (12.10, разбор GPT L6: кэш на 30 мин пускал вчерашнее
    решение после полуночи). Данные проверяются: сортировка по времени, без повторов и пропусков дней, последняя
    закрытая свеча — вчерашняя, цены конечные и положительные. Сбой/устаревшие/битые данные → None (новых входов
    нет, нового закрытия по режиму нет; уже начатое закрытие доводится).
    Кэш процесса общий для всех сеток символа: 4 сетки BTC с SMA100 — один запрос дневок в сутки. После сбоя повтор не
    раньше REGIME_RETRY (15.10: иначе каждая из 4 сеток BTC ждала бы свой таймаут 15 с в каждом проходе)."""
    now = now or time.time()
    today = int(now // 86400)
    key = (symbol, sma_days)
    c = _REGIME_CACHE.get(key)
    if c and c[0] == today:
        return c[1]
    failed = _REGIME_CACHE.get(("fail",) + key)
    if failed is not None and 0 <= now - float(failed) < REGIME_RETRY:
        return None
    try:
        rows = (fetch or _fetch_daily)(symbol, sma_days + 5)
        bars = {int(r[0]) // 86_400_000: r for r in rows if int(r[6]) < now * 1000}   # день → закрытая свеча
        days = sorted(bars)
        if not days or days[-1] != today - 1:
            raise ValueError(f"последняя закрытая свеча не вчерашняя: {days[-1] if days else None} vs {today - 1}")
        tail = days[-sma_days:]
        if len(tail) < sma_days or tail != list(range(tail[0], tail[0] + sma_days)):
            raise ValueError("меньше дней или пропуск дня")
        closes = [float(bars[d][4]) for d in tail]
        if not all(math.isfinite(x) and x > 0 for x in closes):
            raise ValueError("битая цена закрытия")
        up = closes[-1] > sum(closes) / sma_days
    except Exception:                                           # noqa: BLE001
        logger.exception("weex_grid.regime_failed %s", symbol)
        _REGIME_CACHE[("fail",) + key] = now
        return None
    _REGIME_CACHE.pop(("fail",) + key, None)
    _REGIME_CACHE[key] = (today, up)
    return up


class Grid:
    def __init__(self, client, cfg: dict | None = None, state_path: Path = STATE,
                 journal_path: Path = JOURNAL, sigma_fn=None, send_fn=None, now_fn=time.time, regime_fn=None,
                 name: str | None = None):
        self.c = client
        self.regime_fn = regime_fn or regime_up
        self.cfg = cfg or load_config()
        # знак ордеров сетки (15.10): с именем (цикл, карточка) — ещё и проверка, что знак не занят другой сеткой GRIDS;
        # негодный/занятый знак — ConfigError до чтения учёта и до любого запроса к бирже
        self.name = name
        self.tag = check_tag(name, self.cfg) if name else cid_tag(self.cfg)
        self.own = PREFIX + self.tag                 # префикс СВОИХ ордеров: b7g + знак сетки
        self.label = grid_label(name, self.cfg["symbol"])
        self.state_path = Path(state_path)
        self.journal_path = Path(journal_path)
        self.sigma_fn = sigma_fn
        self.send = send_fn
        self.now = now_fn
        self._issues: list[tuple[str, str]] = []     # неясные детали ордеров текущего прохода (для метки живости)
        self._other_issues: list[tuple[str, str]] = []   # те же, кроме неясных ордеров из unknown_orders (своя эскалация)
        self._unknown_now: set[str] = set()          # ордера, чья деталь неясна в ЭТОМ проходе
        self._listed: set[str] = set()               # свои ордера в списке открытых этого прохода (= живые)
        self._closing: set[str] = set()              # стороны, которые этот проход закрывает по режиму
        self._released: set[str] = set()             # стороны, передаваемые оператору
        self._phase = "init"
        self.st = self._load()
        self._room_used = 0.0                    # $ общего потолка, занятые новыми входами текущего прохода
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
        # учёт с диска в формате до 13.10 не хранил переданный оператору мешок — восстановить из журнала (ниже).
        # Свежий учёт (файла нет: первый запуск, холостой после рестарта) старые передачи журнала не наследует
        migrate = [s for s in ("LONG", "SHORT") if st and isinstance(st.get(s), dict) and "transferred_mtm" not in st[s]]
        for s in ("LONG", "SHORT"):
            st.setdefault(s, new_side_state())
            for k, v in new_side_state().items():
                st[s].setdefault(k, v)
        if migrate:
            self._migrate_transfers(st, migrate)
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

    def _migrate_transfers(self, st: dict, sides: list[str]) -> None:
        """Один раз для учёта до 13.10: передачи стороны из журнала («передано оператору», bag — MTM на момент
        передачи) → transfers/transferred_mtm, чтобы итог сетки не оставался сдвинутым на мешок, переданный до
        обновления. day_start_pnl сдвигается на ту же сумму — дневной результат от миграции не прыгает. Журнал не
        читается — ключи убираются, миграция повторится при следующей загрузке. Журнала нет, а у стороны есть история
        (закрыто/комиссии ≠ 0) — миграция тоже не отмечается выполненной (14.10, ревью L3-1: карточка с чужим путём
        журнала показывала итог без переданного мешка; сохранённый такой учёт не мигрировал бы уже никогда)."""
        if not self.journal_path.exists():
            hist = [s for s in sides if float(st[s].get("realized") or 0) or float(st[s].get("fees") or 0)]
            for s in hist:
                st[s].pop("transferred_mtm", None)
                st[s].pop("transfers", None)
            if hist:
                logger.warning("weex_grid.transfer_migration_deferred sides=%s journal=%s — журнала нет", hist,
                               self.journal_path)
            return
        try:
            lines = self.journal_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            logger.exception("weex_grid.transfer_migration_failed path=%s", self.journal_path)
            for s in sides:
                st[s].pop("transferred_mtm", None)
                st[s].pop("transfers", None)
            return
        add = 0.0
        seen: set[str] = set()
        for line in lines:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if not isinstance(r, dict) or r.get("kind") != HANDOVER or r.get("side") not in sides:
                continue
            ev = r.get("event_id")
            if ev:                                              # одна передача — одна запись (15.10, разбор GPT P2)
                if ev in seen:
                    continue
                seen.add(ev)
            bag = float(r.get("bag") or 0)
            st[r["side"]]["transfers"].append({"ts": r.get("ts"), "qty": r.get("qty"), "avg": r.get("avg"),
                                               "mark": r.get("mark"), "mtm": bag, "lots": r.get("lots"),
                                               "src": "журнал", **({"event_id": ev} if ev else {})})
            st[r["side"]]["transferred_mtm"] += bag
            add += bag
        if add and st.get("day"):
            st["day_start_pnl"] = float(st.get("day_start_pnl") or 0) + add
        if add:
            logger.info("weex_grid.transfer_migrated sides=%s mtm=%.4f", sides, add)

    def save(self) -> None:
        atomic_write(self.state_path, json.dumps(self.st, ensure_ascii=False, indent=1))

    def _journal(self, rec: dict) -> None:
        rec = {"ts": datetime.fromtimestamp(self.now(), timezone.utc).isoformat(timespec="seconds"),
               "dry": bool(self.cfg["dry_run"]), **rec}
        with self.journal_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def _notify(self, text: str) -> bool:
        """Отправить сообщение; True — доставлено. Отправитель может бросить исключение или вернуть False (не доставлено,
        15.10, разбор GPT P2: результат раньше проглатывался, и эскалация считалась отправленной); отправителя нет — False."""
        if not self.send:
            return False
        try:
            ok = self.send(text) is not False
        except Exception:                                       # noqa: BLE001
            logger.exception("weex_grid.send_failed")
            return False
        if not ok:
            logger.warning("weex_grid.send_not_delivered text=%s", text[:80])
        return ok

    # ---------- вспомогательное
    def _cid(self, side: str, kind: str) -> str:
        """b7g + знак сетки + сторона + вид + время + счётчик (уникально между сетками). Знак по умолчанию — буква
        символа: у BTC/ETH/XAU формат прежний (b7gBL…, b7gEL…)."""
        s = self.st[side]
        s["seq"] += 1
        return f"{self.own}{side[0]}{kind}{int(self.now())}{s['seq']}"

    def _qty_str(self, q: float) -> str:
        step = float(self.cfg.get("qty_step") or 0.0001)
        dec = max(0, -int(math.floor(math.log10(step) + 1e-9)))
        return f"{round(q / step) * step:.{dec}f}"

    def _tiny(self) -> float:
        return float(self.cfg.get("qty_step") or 0.0001) / 2

    def _own_trades(self, order_id: str, what: str) -> list | None:
        """Сделки ЭТОГО ордера этого символа (18.10, разбор GPT P2 / 7ecda96 §2.1: чужая строка или строка без номера в
        ответе — не наша комиссия). None — ответ не прочитан или не список: сбой записан, это НЕ пустое успешное
        чтение (поздний курсор по нему не помечается проверенным и не истекает)."""
        try:
            rows = self.c.user_trades(self.cfg["symbol"], order_id)
        except Exception as exc:                                # noqa: BLE001
            logger.exception("weex_grid.trades_failed")
            self._issue(f"{what} ордера {order_id} не прочитана ({type(exc).__name__}: {exc})")
            return None
        if not isinstance(rows, list):
            self._issue(f"{what} ордера {order_id}: ответ сделок не список ({str(rows)[:80]})")
            return None
        sym = self.cfg["symbol"]
        return [r for r in rows if isinstance(r, dict) and str(r.get("orderId") or "") == str(order_id)
                and str(r.get("symbol") or sym) == sym]

    def _fee_delta(self, side: str, order_id: str) -> tuple[float, bool | None]:
        """Прирост комиссии ордера против уже записанной (курсор в fee_book). Ордер остаётся в
        книге FEE_WINDOW секунд — поздно появившаяся комиссия будет дописана _settle_fees."""
        s = self.st[side]
        trades = self._own_trades(order_id, "комиссия") or []
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
        if s.get("flatten") and s["flatten"].get("id"):          # рыночное закрытие (12.10, разбор GPT L7)
            ids.add(str(s["flatten"]["id"]))
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
            trades = self._own_trades(oid, "поздняя комиссия")
            if trades is None:
                continue                                        # негодный ответ — не проверка (7ecda96 §2.1)
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
            except Exception as exc:                            # noqa: BLE001
                logger.exception("weex_grid.balance_failed")
                self._issue(f"баланс не прочитан ({type(exc).__name__}: {exc})")
                self._equity = None                             # просроченный кэш не выдаём за известный баланс
        return self._equity

    def unrealized(self, mid: float) -> float:
        return sum(DIR[s] * float(l["qty"]) * (mid - l["entry"]) for s in ("LONG", "SHORT") for l in self.st[s]["lots"])

    def bot_pnl(self, mid: float) -> float:
        """Итог владения: закрытое − комиссии + MTM переданного оператору мешка на момент передачи + мешок своих лотов.
        Передача остатка не меняет итог ни в плюс, ни в минус (13.10, дополнение GPT §3: раньше удаление убыточного
        мешка поднимало итог); дальнейшее движение переданной позиции — уже не бота. Тот же итог — в дневном стопе."""
        return (sum(self.st[s]["realized"] - self.st[s]["fees"] + float(self.st[s].get("transferred_mtm") or 0)
                    for s in ("LONG", "SHORT"))
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
        if free is not None:
            # место = свободное на начало прохода − занятое новыми входами этого прохода + резерв входа
            # этой же стороны (его заменяет новый). 11.10, разбор GPT: при свободных $200 две стороны
            # ставили по $120 — одно место раздавалось дважды
            room = float(free) - self._room_used + self._entry_res(side)
            if q * price > room + 1e-9:
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
    def _entry_res(self, side: str) -> float:
        """Сколько $ общего потолка держит вход стороны: остаток стоящего входа + неясная постановка входа."""
        return self._standing_res(side) + self._pending_res(side)

    def _standing_res(self, side: str) -> float:
        e = self.st[side].get("entry")
        if not e:
            return 0.0
        return max(float(e.get("qty") or 0) - float(e.get("filled") or 0), 0.0) * float(e["price"])

    def _pending_res(self, side: str) -> float:
        p = self.st[side].get("pending")
        return float(p.get("qty") or 0) * float(p["price"]) if p and p.get("kind") == "e" else 0.0

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
        if kind == "e":
            self._room_used += float(q) * price                 # место занято с момента намерения
        self.save()
        try:
            r = self.c.place_limit(cfg["symbol"], "BUY" if buy else "SELL", side, q,
                                   fmt_px(price, tick), cid, reduce_only=reduce, post_only=True)
        except Exception as exc:                                # noqa: BLE001 — один ордер не валит проход
            # исход неизвестен: ордер мог дойти — pending остаётся до выяснения
            logger.warning("weex_grid.place_failed side=%s kind=%s price=%s err=%s", side, kind, price, exc)
            self._issue(f"постановка {cid}: исход неизвестен ({type(exc).__name__}: {exc})")
            return None
        if not isinstance(r, dict) or r.get("success") is not True or not r.get("orderId"):
            # явный отказ — ТОЛЬКО объект с success=false. null, {}, не объект, нет поля success, «успех» без номера —
            # исход неизвестен: намерение и резерв остаются до выяснения (18.10, разбор GPT P1: null/{} снимали намерение,
            # и при принятом, но не видимом ордере вставал второй вход)
            if not (isinstance(r, dict) and r.get("success") is False):
                logger.warning("weex_grid.place_unknown side=%s kind=%s resp=%s", side, kind, str(r)[:200])
                self._issue(f"постановка {cid}: исход неизвестен (ответ {str(r)[:80]})")
                return None
            s["pending"] = None                                 # явный отказ — исход известен
            if kind == "e":
                self._room_used -= float(q) * price
            logger.warning("weex_grid.place_rejected side=%s kind=%s price=%s resp=%s", side, kind, price, r)
            self.save()
            return None
        s["pending"] = None
        return {"id": str(r["orderId"]), "cid": cid, "price": price, "qty": q}

    @staticmethod
    def _orders_list(rows, what: str) -> list[dict]:
        """Ответ-список ордеров WEEX (открытые, история): массив объектов с orderId. Иное — null, {}, объект ошибки,
        строки, ордер без номера — WeexIncomplete: по такому ответу нельзя заключить, что ордера нет (15.10, разбор GPT
        P1: «or []» делал из null/{} полную пустую историю, и после TTL ставился второй живой вход)."""
        if not isinstance(rows, list):
            raise WeexIncomplete(f"{what}: не список ({str(rows)[:120]})")
        bad = next((x for x in rows if not isinstance(x, dict) or x.get("orderId") in (None, "")), None)
        if bad is not None:
            raise WeexIncomplete(f"{what}: элемент не ордер ({str(bad)[:120]})")
        return rows

    def _find_by_cid(self, cid: str, since: float, half: float = 600.0) -> tuple[dict | None, bool]:
        """Свой ордер по clientOrderId: открытые, затем история символа в окне ±half секунд вокруг момента
        намерения по часам биржи, постранично. Второе значение — поиск ПОЛНЫЙ: False, если все 10
        страниц заполнены (неполный поиск не доказывает, что ордер не дошёл, — такой pending не истекает).
        Негодная страница истории (не список ордеров) — WeexIncomplete, а не «не нашёлся» (15.10, разбор GPT P1).
        Страница повторяет предыдущую (WEEX игнорирует page, 15.10) — дальше делением окна пополам (_history_window)."""
        o = next((x for x in self.open.values() if x.get("clientOrderId") == cid), None)
        if o is not None:
            return o, True
        start_ms = int((since - half) * 1000)
        end_ms = int((since + half) * 1000)
        prev: set[str] = set()
        for page in range(10):
            chunk = self._orders_list(self.c.order_history(self.cfg["symbol"], limit=100, page=page,
                                                           start_ms=start_ms, end_ms=end_ms),
                                      f"история ордеров {self.cfg['symbol']}, страница {page}")
            o = next((x for x in chunk if x.get("clientOrderId") == cid), None)
            if o is not None:
                return o, True
            if len(chunk) < 100:
                return None, True
            ids = {str(x["orderId"]) for x in chunk}
            if ids & prev:                                      # биржа не листает — та же страница ещё раз
                return self._history_window(cid, start_ms, end_ms, int(since * 1000), [HISTORY_SPLIT_BUDGET], split=True)
            prev = ids
        return None, False

    def _history_window(self, cid: str, a: int, b: int, near: int, budget: list[int],
                        split: bool = False) -> tuple[dict | None, bool]:
        """Поиск по clientOrderId в окне истории [a, b] мс без листания: ответ меньше 100 — окно прочитано целиком; ровно
        100 — окно делится пополам (до 1 с), сначала половина ближе к моменту намерения near. Всего не больше budget[0]
        запросов; не хватило — (None, False). split — окно уже известно как полное (100), сразу делить."""
        if not split:
            if budget[0] <= 0:
                return None, False
            budget[0] -= 1
            chunk = self._orders_list(self.c.order_history(self.cfg["symbol"], limit=100, page=0, start_ms=a, end_ms=b),
                                      f"история ордеров {self.cfg['symbol']}, окно {a}..{b}")
            o = next((x for x in chunk if x.get("clientOrderId") == cid), None)
            if o is not None:
                return o, True
            if len(chunk) < 100:
                return None, True
        if b - a <= 1000:
            return None, False
        m = (a + b) // 2
        halves = sorted([(a, m), (m, b)], key=lambda w: 0 if w[0] <= near <= w[1] else min(abs(near - w[0]),
                                                                                              abs(near - w[1])))
        complete = True
        for lo, hi in halves:
            o, ok = self._history_window(cid, lo, hi, near, budget)
            if o is not None:
                return o, True
            complete = complete and ok
        return None, complete

    def _find_by_trades(self, cid: str, srv: float, side: str | None = None, want: str | None = None,
                        book: dict | None = None) -> tuple[dict | None, bool]:
        """Свой ордер по сделкам окна ±10 мин → деталь каждого незнакомого ордера → clientOrderId (исполненный ордер,
        которого нет в открытых, а история его не показала, 12.10 L2). Второе значение — поиск ПОЛНЫЙ: сделки окна
        прочитаны целиком (_window_trades), незнакомых ордеров не больше TRADES_DETAILS и деталь каждого годна; иначе
        «не нашёлся» не доказан.
        15.10 (несколько сеток на символе — в окне десятки ордеров соседей): side/want — сторона позиции и направление
        (BUY/SELL) искомого ордера; сделка другой стороны или направления — не наш ордер, деталь не спрашивается (поле не
        пришло или значение незнакомое — не отсеиваем; годная деталь без clientOrderId — поиск неполон, «не дошёл» не
        доказан). book — {orderId: clientOrderId} ордеров окна, чья годная деталь уже прочитана (хранится в
        намерении на диске): известный чужой ордер не спрашивается снова, и поиск продвигается от попытки к попытке, а не
        упирается каждый раз в те же TRADES_DETAILS ордеров."""
        trades, complete = self._window_trades(cid, int((srv - 600) * 1000), int((srv + 600) * 1000))
        if trades is None:
            return None, False
        known = self._referenced("LONG") | self._referenced("SHORT")
        book = {} if book is None else book
        seen: set[str] = set()
        for t in trades:
            oid = str(t.get("orderId") or "")
            if not oid:
                complete = False                                # 18.10, разбор GPT P1: чья сделка — неизвестно,
                continue                                        # «не нашёлся» по такому ответу не доказан
            if oid in known or oid in seen or oid in book:
                continue
            # отсев — только по ИЗВЕСТНЫМ значениям полей (LONG/SHORT, BUY/SELL); поле не пришло или значение
            # незнакомое — сделку не отсеиваем (её ордер мог быть нашим)
            ps, sd = str(t.get("positionSide") or "").upper(), str(t.get("side") or "").upper()
            if side and ps in DIR and ps != side:
                continue
            if want and sd in ("BUY", "SELL") and sd != want:
                continue
            if len(seen) >= TRADES_DETAILS:
                complete = False
                break
            seen.add(oid)
            kind, info = self._detail(oid)
            if kind == "unknown":
                complete = False
                continue
            got = info.get("clientOrderId")
            if got == cid:
                return info, True
            if not isinstance(got, str) or not got:
                complete = False                                # деталь без clientOrderId — чей ордер, неясно
                continue
            book[oid] = got[:48]
        return None, complete

    def _window_trades(self, cid: str, a: int, b: int) -> tuple[list | None, bool]:
        """Сделки символа в окне [a, b] мс. Ответ — не больше 100 сделок: окно со 100 делится пополам (до 1 с), всего не
        больше TRADES_SPLIT_BUDGET запросов. (None, False) — ответ не прочитан или не список сделок; иначе (сделки без
        повторов, выборка полна)."""
        budget = [TRADES_SPLIT_BUDGET]
        rows: dict[str, dict] = {}
        complete = True

        def get(lo: int, hi: int) -> None:
            nonlocal complete
            if budget[0] <= 0:
                complete = False
                return
            budget[0] -= 1
            chunk = self.c.user_trades(self.cfg["symbol"], start_ms=lo, end_ms=hi)
            if not isinstance(chunk, list) or not all(isinstance(t, dict) for t in chunk):
                raise WeexIncomplete(f"ответ не список сделок ({str(chunk)[:120]})")
            for t in chunk:
                rows[str(t.get("id") or f"{t.get('orderId')}:{t.get('time')}:{t.get('qty')}")] = t
            if len(chunk) < 100:
                return
            if hi - lo <= 1000:
                complete = False
                return
            m = (lo + hi) // 2
            get(lo, m)
            get(m, hi)                                          # перекрытие в m (сделки без повторов по id), 18.10
        try:
            get(a, b)
        except WeexIncomplete as exc:
            self._issue(f"сделки окна ордера {cid}: {exc}")
            return None, False
        except Exception as exc:                                # noqa: BLE001
            logger.exception("weex_grid.window_trades_failed cid=%s", cid)
            self._issue(f"сделки окна ордера {cid} не прочитаны ({type(exc).__name__}: {exc})")
            return None, False
        return list(rows.values()), complete

    def _resolve_pending(self, side: str) -> bool:
        """Ордер с потерянным ответом: найти и привязать. False — ещё не выяснено (на этой стороне
        новых ордеров не ставим).
        «Не дошёл» (15.10, разбор GPT P1) — только после TTL, PENDING_ABSENT_READS годных полных поисков подряд по
        открытым и истории (разнесённых не меньше чем на PENDING_RECHECK) и пустого поиска по сделкам окна. Негодный или
        непрочитанный ответ (null, {}, объект ошибки, исключение) — исход НЕИЗВЕСТЕН: намерение остаётся на диске,
        новых ордеров стороны нет, повторной отправки с новым clientOrderId нет, счёт подтверждений обнуляется."""
        s = self.st[side]
        p = s.get("pending")
        if not p:
            return True
        srv = p.get("srv") or p["t"]
        try:
            # намерение без серверного времени (учёт до 10.10) — окно шире: ±30 мин
            o, complete = self._find_by_cid(p["cid"], srv, 600.0 if p.get("srv") else 1800.0)
        except Exception as exc:                                # noqa: BLE001
            logger.exception("weex_grid.history_failed")
            p.pop("absent", None)
            self._issue(f"поиск ордера {p['cid']} не прочитан ({type(exc).__name__}: {exc})")
            return False
        if o is None:
            if self.now() - p["t"] < PENDING_TTL:
                return False
            if not complete:                                    # поиск неполный — не считаем «не дошёл»
                p.pop("absent", None)
                if not p.get("warned"):
                    p["warned"] = True
                    self.save()
                    self._notify(f"⚠️ Сетка WEEX {self.label}: ордер {p['cid']} с потерянным ответом не "
                                 f"найден, история слишком плотная для полного поиска — новые ордера стороны "
                                 f"{side} не ставлю до выяснения.")
                return False
            absent = [float(x) for x in (p.get("absent") or [])]
            if not absent or self.now() - absent[-1] >= PENDING_RECHECK:
                absent.append(float(self.now()))
                p["absent"] = absent
            if len(absent) < PENDING_ABSENT_READS:
                return False
            if self.now() - float(p.get("trades_ts") or 0) < PENDING_RECHECK:
                return False                                    # поиск по сделкам (до 20 деталей) — не каждый проход
            p["trades_ts"] = float(self.now())
            want = OPEN_SIDE[side] if p.get("kind") == "e" else CLOSE_SIDE[side]
            o, complete = self._find_by_trades(p["cid"], srv, side=side, want=want, book=p.setdefault("foreign", {}))
            if o is None:
                if not complete:
                    # 15.10: раньше молча — сторона стояла без новых ордеров без единого сообщения. Теперь одно сообщение
                    # (как у неполной истории); прочитанные чужие ордера окна запомнены в намерении — следующая попытка
                    # через PENDING_RECHECK продолжит с непроверенных
                    if not p.get("warned_trades"):
                        p["warned_trades"] = True
                        self.save()
                        self._notify(f"⚠️ Сетка WEEX {self.label}: ордер {p['cid']} с потерянным ответом пока не найден "
                                     f"ни в истории, ни в сделках окна (поиск по сделкам неполон) — новые ордера стороны "
                                     f"{side} не ставлю до выяснения, ищу дальше.")
                    return False
                logger.warning("weex_grid.pending_not_found side=%s cid=%s reads=%s — ордер не дошёл", side, p["cid"],
                               len(absent))
                self._notify(f"⚠️ Сетка WEEX {self.label}: ответ биржи на ордер {p['cid']} потерян; за "
                             f"{self.now() - p['t']:.0f} с его нет ни в открытых, ни в истории ({len(absent)} проверки "
                             f"подряд), ни в сделках окна — считаю не дошедшим.")
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
        """Свои (b7g+знак этой сетки) ордера этого символа, о которых учёт не знает (потерянный ответ, откат учёта).
        Ордера соседних сеток символа сюда не попадают (self.open отфильтрован по своему префиксу).
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
            fl = s.get("flatten")                               # рыночное закрытие — не сирота (разбор GPT L1)
            if fl:
                pend.add(fl["cid"])
                if fl.get("id"):
                    known.add(fl["id"])
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
                # ранее неучтённый вход занимает место общего потолка СРАЗУ: свободное этого прохода посчитано
                # без него (12.10, разбор GPT R5: место выдавалось новому входу поверх сироты)
                self._room_used += max(float(o.get("origQty") or 0) - float(o.get("executedQty") or 0), 0.0) * price
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
        по цене лота (по факт. цене); подтверждённый конечный статус — забыть, живой — снять ещё раз. Неясная
        деталь ({}, чужой id, нет/неизвестный статус) — ордер остаётся в учёте до подтверждения (13.10, разбор GPT
        W2: пустой ответ стирал живой тейк бота, и сторону потом «передавали» с его живым тейком)."""
        s, d = self.st[side], DIR[side]
        for x in list(s["strays"]):
            kind, info = self._detail(x["id"], side, x)
            if kind == "unknown":
                self._cancel(x)                                 # цель — снять; исход проверим следующим проходом
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
                        self._notify(f"⚠️ Сетка WEEX {self.label}: тейк {x['cid']} закрыл {left:g} {side} "
                                     f"сверх лотов учёта — расхождение, проверь позицию.")
            if kind == "terminal":
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
        """Один проход. Метки для мониторинга (13.10, разбор GPT Q1: mtime учёта освежался и проходом, упавшим
        позже): last_tick_ok_ts — только в конце полностью успешного прохода, без исключения и без неясных деталей
        ордеров; исключение → last_tick_error {ts, phase, err, fatal: true} в СОХРАНЁННЫЙ учёт (недосчитанный
        проход на диск не пишется) и исключение дальше; неясная деталь ордера или сбой запроса, который проход
        пережил (_issue: комиссия, поиск/постановка ордера, позиция, баланс), → last_tick_error с fatal: false,
        успех не отмечается. Затянувшееся неясное поднимается сообщением (_escalations → alert_outbox учёта) — доставка
        после сохранения учёта, недоставленное повторяется следующими проходами (_deliver_alerts)."""
        self._issues = []
        self._other_issues = []
        self._unknown_now = set()
        self._phase = "start"
        try:
            self._tick()
            self._phase = "save"
            self._escalations()
            if self._issues:
                self.st["last_tick_error"] = {
                    "ts": float(self.now()), "phase": self._issues[0][0], "fatal": False,
                    "err": ("неясно: " + "; ".join(f"{p} {e}" for p, e in self._issues))[:400]}
            else:
                self.st["last_tick_ok_ts"] = float(self.now())
            self.save()
        except Exception as exc:
            self._mark_tick_failed(exc)
            raise
        self._deliver_alerts()

    def _escalations(self) -> None:
        """Сообщения о затянувшемся неясном (14.10, ревью F1/L2-1). unknown_orders {oid: {since, why, phase, side,
        role}} ведёт _detail: запись снимается, когда ордер подтверждён (конечный / живой, в т.ч. в списке открытых) или
        учёт его больше не ведёт. Ордер неясен ≥ UNKNOWN_ALERT_AFTER → одно сообщение, повтор не чаще UNKNOWN_ALERT_EVERY;
        если он теперь держит закрытие по режиму или передачу стороны, а прошлое сообщение этого не называло, — сразу.
        Прочие проглоченные сбои подряд ≥ ISSUE_ALERT_AFTER без чистого прохода → сообщение не чаще ISSUE_ALERT_EVERY.
        Сообщение не отправляется здесь, а ставится в alert_outbox учёта (15.10, разбор GPT P2): метки интервала
        unknown_alert_ts / issue_alert_ts пишет только УДАЧНАЯ доставка (_deliver_alerts); пока сообщение ждёт, его текст
        обновляется каждым проходом; условие снято до доставки — сообщение снимается."""
        now = float(self.now())
        if not isinstance(self.st.get("alert_outbox"), dict):
            self.st["alert_outbox"] = {}
        box = self.st["alert_outbox"]
        book = self.st.setdefault("unknown_orders", {})
        for oid, rec in list(book.items()):
            side = rec.get("side")
            refs = self._referenced(side) if side in DIR else set()
            if oid not in refs or (oid in self._listed and oid not in self._unknown_now):
                book.pop(oid, None)
        # флаги сбрасываются только после часового интервала: «мигающая» деталь (неясно ≥5 мин → годный ответ → снова
        # неясно) иначе обходила бы часовой лимит через «новую» блокировку (проверка 14.10, ESC-FLAP: 22 сообщения/2 ч)
        if not book and now - float(self.st.get("unknown_alert_ts") or 0) >= UNKNOWN_ALERT_EVERY:
            self.st.pop("unknown_alert_flags", None)
        old = [(oid, r) for oid, r in book.items() if now - float(r.get("since") or now) >= UNKNOWN_ALERT_AFTER]
        if old:
            flags = {f for _, r in old for f in self._blocks(r)}
            told = set(self.st.get("unknown_alert_flags") or [])
            due = now - float(self.st.get("unknown_alert_ts") or 0) >= UNKNOWN_ALERT_EVERY or not flags <= told
            if due or "unknown" in box:
                self._queue_alert("unknown", self._unknown_text(old, flags, now), flags=sorted(flags | told))
        else:
            self._drop_alert("unknown")
        if self._other_issues:
            since = float(self.st.setdefault("issues_since", now))
            due = now - float(self.st.get("issue_alert_ts") or 0) >= ISSUE_ALERT_EVERY
            if now - since >= ISSUE_ALERT_AFTER and (due or "issue" in box):
                start = min(since, float(self.st.get("last_tick_ok_ts") or since))
                p, what = self._other_issues[0]
                more = f" (и ещё {len(self._other_issues) - 1})" if len(self._other_issues) > 1 else ""
                self._queue_alert("issue", f"⚠️ Сетка WEEX {self.label}: {int((now - start) // 60)} мин без чистого прохода — "
                                           f"{p}: {what[:200]}{more}. Сетка работает дальше, но этот сбой повторяется — "
                                           f"проверь.")
        else:
            self.st.pop("issues_since", None)
            self._drop_alert("issue")
        if not box:
            self.st.pop("alert_outbox", None)

    def _queue_alert(self, kind: str, text: str, **extra) -> None:
        """Поставить/обновить ждущее сообщение вида kind: новое — к отправке сразу, ждущее — новый текст, срок повтора тот же."""
        box = self.st.setdefault("alert_outbox", {})
        rec = box.get(kind)
        if rec is None:
            now = float(self.now())
            box[kind] = {"text": text, "created": now, "attempts": 0, "next_try": now, **extra}
        else:
            rec.update(text=text, **extra)

    def _drop_alert(self, kind: str) -> None:
        rec = (self.st.get("alert_outbox") or {}).pop(kind, None)
        if rec:
            logger.info("weex_grid.alert_dropped kind=%s attempts=%s — условие снято до доставки", kind,
                        rec.get("attempts"))

    def _deliver_alerts(self) -> None:
        """Доставка ждущих сообщений эскалации (после сохранения прохода). Удача — сообщение снято, метка интервала
        (unknown_alert_ts / issue_alert_ts) = время доставки, alert_delivered[kind] = {ts, attempts}. Неудача (исключение
        или False отправителя) — attempts+1, last_attempt, следующая попытка через ALERT_RETRY (1, 2, 5, затем 10 мин).
        Отправителя нет — сообщение ждёт. Учёт сохраняется сразу после попыток: доставленное после рестарта не повторяется."""
        box = self.st.get("alert_outbox") or {}
        if not isinstance(box, dict):
            logger.error("weex_grid.alert_outbox_corrupt %s", str(box)[:120])
            self.st.pop("alert_outbox", None)
            return
        if not box or not self.send:
            return
        now = float(self.now())
        tried = False
        for kind, rec in list(box.items()):
            if now < float(rec.get("next_try") or 0):
                continue
            tried = True
            rec["attempts"] = int(rec.get("attempts") or 0) + 1
            rec["last_attempt"] = now
            if self._notify(str(rec.get("text") or "")):
                box.pop(kind, None)
                self.st.setdefault("alert_delivered", {})[kind] = {"ts": now, "attempts": rec["attempts"],
                                                                   "created": rec.get("created")}
                if kind == "unknown":
                    self.st["unknown_alert_ts"] = now
                    self.st["unknown_alert_flags"] = list(rec.get("flags") or [])
                elif kind == "issue":
                    self.st["issue_alert_ts"] = now
            else:
                rec["next_try"] = now + ALERT_RETRY[min(rec["attempts"], len(ALERT_RETRY)) - 1]
                logger.warning("weex_grid.alert_not_delivered kind=%s attempt=%s next_in=%.0fs", kind, rec["attempts"],
                               rec["next_try"] - now)
        if not box:
            self.st.pop("alert_outbox", None)
        if tried:
            try:
                self.save()
            except Exception:                                   # noqa: BLE001 — проход уже сохранён; повтор доставки возможен
                logger.exception("weex_grid.alert_state_save_failed")

    def _blocks(self, rec: dict) -> set[str]:
        """Что держит неясный ордер: 'close' — закрытие по режиму, 'release' — передачу стороны."""
        side, phase, out = rec.get("side"), str(rec.get("phase") or ""), set()
        if phase.startswith("flatten") or side in self._closing or (side in DIR and self.st[side].get("flatten")):
            out.add("close")
        if phase.startswith("release") or side in self._released:
            out.add("release")
        return out

    def _unknown_text(self, old: list, flags: set, now: float) -> str:
        rows = [f"• {r.get('side')} {r.get('role') or 'ордер'} {oid}: {int((now - float(r['since'])) // 60)} мин, "
                f"фаза {r.get('phase')} — {r.get('why')}" for oid, r in old[:5]]
        if len(old) > 5:
            rows.append(f"• и ещё {len(old) - 5}")
        text = (f"⚠️ Сетка WEEX {self.label}: статус ордера бота неясен дольше "
                f"{int(UNKNOWN_ALERT_AFTER // 60)} мин — замену не ставлю, повторно не отправляю, жду ясного ответа "
                f"биржи.\n" + "\n".join(rows))
        for flag, head, tail in (("close", "ЗАКРЫТИЕ ПО РЕЖИМУ ЗАБЛОКИРОВАНО: рыночного закрытия", "не будет"),
                                 ("release", "ПЕРЕДАЧА СТОРОНЫ ЖДЁТ: сторона", "не передаётся тебе")):
            if flag in flags:
                sides = sorted({str(r.get("side")) for _, r in old if flag in self._blocks(r)})
                text += f"\n🛑 {head} {'/'.join(sides)} {tail}, пока статус не ясен."
        return text + "\nПроверь ордер и позицию в приложении WEEX."

    def _mark_tick_failed(self, exc: BaseException) -> None:
        """Записать ошибку прохода в учёт на диске (последний целостный снимок), не сохраняя недосчитанный проход."""
        rec = {"ts": float(self.now()), "phase": self._phase, "fatal": True,
               "err": f"{type(exc).__name__}: {exc}"[:400]}
        self.st["last_tick_error"] = rec
        try:
            if not self.state_path.exists():
                return
            disk = json.loads(self.state_path.read_text(encoding="utf-8"))
            if isinstance(disk, dict) and disk.get("symbol") in (None, self.cfg["symbol"]):
                disk["last_tick_error"] = rec
                atomic_write(self.state_path, json.dumps(disk, ensure_ascii=False, indent=1))
        except Exception:                                       # noqa: BLE001
            logger.exception("weex_grid.tick_error_mark_failed")

    def _tick(self) -> None:
        cfg = self.cfg
        sym = cfg["symbol"]
        self._phase = "book"
        bid, ask = self.c.book(sym)
        mid = (bid + ask) / 2
        self._room_used = 0.0
        # список открытых неполон (предел страниц) или не список ордеров (null, {}, объект ошибки) → WeexIncomplete:
        # проход прерывается до решений о сиротах и владении (13.10 и 15.10 P1, разборы GPT). Свои — только с префиксом
        # b7g+знак этой сетки: ордера соседней сетки того же символа (b7g+другой знак) и ручные для неё не существуют
        self._phase = "open_orders"
        self.open = {str(o["orderId"]): o for o in self._orders_list(self.c.open_orders(sym), f"открытые ордера {sym}")
                     if str(o.get("clientOrderId", "")).startswith(self.own)}
        self._listed = set(self.open)
        self._phase = "orphans"
        self._orphans()
        open_ids = set(self.open)
        self._phase = "day"
        self._day_roll(mid)
        # передача, учтённая, но не дописанная в журнал (сбой между записью учёта и журнала) — дописать один раз
        for side in DIR:
            if self.st[side].get("handover_unjournaled"):
                self._phase = f"release:{side}"
                self._journal_handover(side)
        # сторона, переданная оператору (release_sides и её нет в sides): бот снимает свои ордера и забывает
        # лоты; пока передача не завершена — сторону не сопровождаем (иначе тейки встали бы снова)
        released = {x for x in (cfg.get("release_sides") or []) if x in DIR and x not in cfg["sides"]}
        self._released = released
        for side in released:
            if self._side_busy(side):
                self._phase = f"release:{side}"
                self.release_side(side, mid)
        # режим SMA (regime_sma > 0): лонг — только выше SMA, шорт — только ниже; сторона не по режиму
        # закрывается по рынку; режим неизвестен — новых входов нет, ничего не закрываем
        allowed = set(cfg["sides"])
        closing: set[str] = set()
        if int(cfg.get("regime_sma") or 0) > 0:
            self._phase = "regime"
            up = self.regime_fn(sym, int(cfg["regime_sma"]))
            self.st["regime"] = up
            if up is None:
                allowed = set()
            else:
                allowed = {x for x in cfg["sides"] if (x == "LONG") == up}
                for side in cfg["sides"]:
                    st_ = self.st[side]
                    if side not in allowed and (st_["lots"] or st_.get("entry") or st_.get("flatten")):
                        closing.add(side)
        for side in DIR:
            if self.st[side].get("flatten"):
                closing.add(side)
        self._closing = closing - released
        for side in closing - released:
            self._phase = f"flatten:{side}"
            self._flatten_side(side, bid, ask, mid)
        # обе стороны сопровождаются всегда, пока у стороны есть что-то на бирже/в учёте; новые входы —
        # только на сторонах из конфига (перепроверка GPT 10.10: после смены sides LONG→SHORT старый
        # вход LONG исполнялся без учёта и тейка)
        for side in ("LONG", "SHORT"):
            s = self.st[side]
            if side in released or side in closing:
                continue
            if side in cfg["sides"] or s.get("entry") or s["lots"] or s["strays"] or s.get("pending"):
                self._phase = f"side:{side}"
                self._side(side, bid, ask, mid, open_ids, enabled=bool(cfg["enabled"]) and side in allowed)
        self._phase = "fees"
        self._settle_fees()
        self._prune_fills()
        self._phase = "risk"
        self._risk(mid)

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
            cmd = "/weex start" if self.name in (None, "BTC") else f"/weex {self.name.lower()} start"
            self._notify(f"🛑 Сетка WEEX {self.label} остановила новые входы: убыток за день ${today:,.2f}. "
                         f"Тейки стоят, позиция закрывается сама. Запуск — {cmd}.")

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
        kind, info = self._detail(e["id"], side, e)
        if kind == "unknown":                 # пустой/чужой/без статуса ответ — не конечный (разбор GPT L4)
            return False                      # оставим отслеживание — разберёмся на следующем проходе
        got = self._take_entry_fill(side, e, info)
        if kind == "terminal":                # отмена подтверждена — забываем; иначе ждём (исполнения
            self._room_used -= self._standing_res(side)                       # место входа освободилось
            s["entry"] = None                 # во время отмены запишутся на следующем проходе)
        self.save()
        return got

    def _reconcile_side(self, side: str, mid: float) -> None:
        """Тейк отклонён → сверить с позицией биржи. Если лотов в учёте больше позиции стороны, снять
        РОВНО недостающий объём (10.10, разбор GPT: раньше удалялся весь лот, хотя на бирже остаток
        был) с лотов без тейка, новые первыми; остаток лота остаётся и получит тейк. Снятое пишется в
        закрытое по текущей цене как оценка внешнего закрытия + сообщение. Позиция может включать
        ручные сделки — тогда она больше суммы лотов и ничего не снимается.
        Несколько сеток на символе (15.10): позиция стороны общая — лоты соседних сеток для этой сетки как ручные.
        Снимается только то, чего не хватает ДАЖЕ во всей позиции; внешнее закрытие части общей позиции, пока её
        хватает на лоты этой сетки, здесь не видно (сознательно: чужие лоты не вычитаются — по ошибке в учёте соседки
        эта сетка не забудет свои настоящие лоты)."""
        s, d = self.st[side], DIR[side]
        try:
            pos = self.c.futures_positions() or []
        except Exception as exc:                                # noqa: BLE001
            logger.exception("weex_grid.positions_failed")
            self._issue(f"позиция {side} не прочитана ({type(exc).__name__}: {exc})")
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
            self._notify(f"⚠️ Сетка WEEX {self.label}: на бирже не хватает {qs} {side} под лот по "
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
            # нет в списке открытых — деталь через единый классификатор (13.10, разбор GPT W1): забываем вход только
            # на подтверждённом конечном статусе; неясный ответ — ссылка и курсор остаются, новый вход поверх не
            # ставится (ниже вход ещё числится), повтор на следующем проходе
            kind, info = self._detail(e["id"], side, e)
            if kind == "terminal":
                self._take_entry_fill(side, e, info)
                s["entry"] = None
                self.save()
            elif kind == "live" and self._take_entry_fill(side, e, info):
                self.save()
        # 2) тейки
        # 2а) тейк на бирже не того объёма, что осталось у лота (биржа урезала reduceOnly) — снять;
        # исполненное до снятия записывается, остаток получит новый тейк — только после подтверждённого конца.
        checked: dict[str, tuple[str, dict]] = {}          # детали этого прохода — не спрашивать дважды
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
                kind, info = checked[o["id"]] = self._detail(o["id"], side, o)
                if kind != "terminal":
                    continue                  # live — отмена ещё не прошла; unknown — исход неясен: тейк остаётся
                self._take_tp_fill(side, lot, o, info, terminal=True)
        for lot in list(s["lots"]):
            o = lot.get("tp_order")
            if o and o["id"] in open_ids:
                live = self.open.get(o["id"])
                if live:
                    self._take_tp_fill(side, lot, o, live, terminal=False)   # частичное исполнение висящего тейка
                continue
            if o:
                # нет в списке открытых — деталь через единый классификатор (13.10, разбор GPT W1: пустой ответ или
                # чужой id считались концом тейка, и рядом с живым ставился второй)
                kind, info = checked.get(o["id"]) or self._detail(o["id"], side, o)
                if kind == "unknown":
                    continue                  # ссылка и курсор остаются, замены нет — повтор на следующем проходе
                if kind == "live":
                    self._take_tp_fill(side, lot, o, info, terminal=False)
                    continue                  # ещё живой, просто не попал в список
                # подтверждённый конечный статус: исполненное — в прибыль (один раз, по курсору), остаток лота —
                # новым тейком ровно на остаток
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

    def _side_busy(self, side: str) -> bool:
        s = self.st[side]
        return bool(s["lots"] or s.get("entry") or s["strays"] or s.get("pending") or s.get("flatten"))

    def _detail(self, oid, side: str | None = None, order: dict | None = None) -> tuple[str, dict]:
        """ЕДИНЫЙ классификатор детали ордера для всех путей — вход, тейк, несовпавший тейк, сирота (stray), рыночное
        закрытие, передача стороны: ('terminal'|'live'|'unknown', info).
        terminal/live — только ответ с тем же orderId, явным известным статусом (TERMINAL/LIVE), тем же символом и
        стороной позиции (если биржа их прислала) и накопленным исполнением не меньше уже учтённого курсором ордера
        (order['filled']); у конечного executedQty обязателен, FILLED — с ненулевым исполнением.
        Всё прочее — {} , ошибка запроса, чужой orderId, нет/неизвестный статус — 'unknown': ссылка и курсор
        остаются, замена не ставится, владение не снимается, повтор на следующем проходе (12.10 L4; 13.10 W1/W2:
        обычные ветки обходили проверку и ставили второй тейк рядом с живым)."""
        try:
            info = self.c.order_info(oid) or {}
        except Exception as exc:                                # noqa: BLE001
            logger.exception("weex_grid.order_info_failed id=%s", oid)
            return self._unknown(oid, f"ошибка запроса ({type(exc).__name__}: {str(exc)[:120]})", side), {}
        if not isinstance(info, dict):
            return self._unknown(oid, "ответ не объект", side), {}
        why = self._detail_problem(oid, info, side, order)
        if why:
            return self._unknown(oid, why, side), info
        (self.st.get("unknown_orders") or {}).pop(str(oid), None)     # подтверждён — эскалация снята
        return ("terminal" if str(info.get("status")).upper() in TERMINAL else "live"), info

    def _detail_problem(self, oid, info: dict, side: str | None, order: dict | None) -> str:
        """Почему ответ детали нельзя считать сведением о НАШЕМ ордере; '' — ответ годен."""
        if not info:
            return "пустой ответ биржи {}"
        if str(info.get("orderId")) != str(oid):
            return f"orderId ответа {info.get('orderId')!r}"
        sym = info.get("symbol")
        if sym and str(sym).upper() != str(self.cfg["symbol"]).upper():
            return f"символ {sym}"
        ps = str(info.get("positionSide") or "").upper()
        if side and ps in DIR and ps != side:
            return f"сторона {ps} вместо {side}"
        st = str(info.get("status") or "").upper()
        if st not in TERMINAL and st not in LIVE:
            return f"статус {info.get('status')!r}"
        raw = info.get("executedQty")
        if raw is None or raw == "":
            return "конечный статус без executedQty" if st in TERMINAL else ""
        try:
            exq = float(raw)
        except (TypeError, ValueError):
            return f"executedQty {raw!r}"
        if not math.isfinite(exq) or exq < 0:
            return f"executedQty {raw!r}"
        done = float((order or {}).get("filled") or 0)
        if exq < done - self._tiny():
            return f"исполнено {exq:g} меньше уже учтённого {done:g}"
        # FILLED без единого исполнения — противоречие (учесть нечего, а замена задвоила бы выход). FILLED с
        # частичным executedQty НЕ отбрасывается: так биржа может закрыть урезанный reduceOnly, а остаток штатно
        # закрывается следующим ордером после конечного статуса прежнего (test_partial_market_rest_closed_next)
        if st == "FILLED" and exq <= self._tiny():
            return "FILLED без исполнения"
        return ""

    def _unknown(self, oid, why: str, side: str | None = None) -> str:
        """Неясная деталь: в журнал службы и в метку прохода (успех прохода не отмечается). Ордер стороны (вход, тейк,
        сирота, рыночное закрытие) — в unknown_orders учёта: с какого момента неясен, почему, в какой фазе (14.10, ревью
        F1: неясность без срока замораживала сторону молча); _escalations поднимает затянувшееся сообщением."""
        logger.warning("weex_grid.order_detail_unknown id=%s phase=%s why=%s", oid, self._phase, why)
        tracked = side in DIR
        if tracked:
            key = str(oid)
            rec = self.st.setdefault("unknown_orders", {}).setdefault(key, {"since": float(self.now()), "side": side})
            rec.update(why=why[:200], phase=self._phase, role=self._role(side, key), last=float(self.now()))
            self._unknown_now.add(key)
        self._issue(f"{oid}: {why}", tracked=tracked)
        return "unknown"

    def _role(self, side: str, oid: str) -> str:
        s = self.st[side]
        if s.get("entry") and str(s["entry"]["id"]) == oid:
            return "вход"
        if any(l.get("tp_order") and str(l["tp_order"]["id"]) == oid for l in s["lots"]):
            return "тейк"
        x = next((x for x in s["strays"] if str(x["id"]) == oid), None)
        if x is not None:
            return "лишний " + ("вход" if x.get("kind") == "e" else "тейк")
        if s.get("flatten") and str(s["flatten"].get("id")) == oid:
            return "рыночное закрытие"
        return "ордер"

    def _issue(self, what: str, tracked: bool = False) -> None:
        """Сбой, который проход переживает (деталь неясна, запрос к бирже не прочитан, исход постановки неизвестен):
        проход не считается полностью успешным — last_tick_ok_ts не освежается, причина — в last_tick_error.
        Снятие ордера сюда не пишется: его исход проверяется деталью. tracked — неясный ордер из unknown_orders: у него
        своя эскалация, в сообщение «без чистого прохода» он не идёт."""
        self._issues.append((self._phase, what))
        if not tracked:
            self._other_issues.append((self._phase, what))

    def _cancel_tps(self, side: str) -> bool:
        """Снять тейки стороны, исполненное до снятия — в прибыль. True — все тейки в подтверждённом конечном
        статусе (тейк забывается только тогда)."""
        s = self.st[side]
        ok = True
        for lot in list(s["lots"]):
            o = lot.get("tp_order")
            if not o:
                continue
            self._cancel(o)
            kind, info = self._detail(o["id"], side, o)
            if kind == "unknown":
                ok = False
                continue
            self._take_tp_fill(side, lot, o, info, terminal=kind == "terminal")
            if kind != "terminal":
                ok = False
        return ok

    def release_side(self, side: str, mid: float) -> bool:
        """Передать сторону оператору (11.10: «шорт-сетку оставляю за собой, закрывать буду сам»): снять свои
        ордера стороны (вход, тейки, сироты), учесть исполнения до снятия, довести уже отправленное рыночное
        закрытие (12.10, разбор GPT L3), и только потом убрать лоты из учёта бота. Позиция на бирже остаётся —
        её ведёт оператор. False — что-то ещё не в подтверждённом конечном статусе, повторить на следующем проходе
        (лоты не теряются, сообщение «передано» не отправляется): неясный вход/тейк/stray/pending/рыночное закрытие
        передачу не завершает (13.10, разбор GPT W2).
        Передача фиксируется один раз (13.10, дополнение GPT §3): время, остаток, средняя, марк и переданный MTM — в
        учёт стороны (transfers, transferred_mtm) и в журнал; итог сетки включает MTM на момент передачи, поэтому
        передача мешка — ни прибыль, ни убыток. Событие пишется и при нуле лотов — граница передачи для мониторинга;
        повторная передача уже переданной стороны без лотов (снята всплывшая сирота) — только учёт и лог (ревью L2-3).
        Учёт — на диск ДО журнала; сбой между ними дописывает журнал на следующем проходе (handover_unjournaled)."""
        s = self.st[side]
        if s.get("pending") and not self._resolve_pending(side):
            return False
        if s.get("flatten"):
            self._flatten_progress(side, mid)
            if s.get("flatten"):
                return False
        self._drop_entry(side)
        if s.get("entry"):
            return False
        if not self._cancel_tps(side):
            self.save()
            return False
        if s["strays"]:
            self._process_strays(side, mid)
            if s["strays"]:
                return False
        lots = s["lots"]
        q = sum(float(l["qty"]) for l in lots)
        avg = sum(float(l["qty"]) * l["entry"] for l in lots) / q if q > self._tiny() else None
        bag = sum(DIR[side] * float(l["qty"]) * (mid - l["entry"]) for l in lots)
        rec = {"ts": datetime.fromtimestamp(self.now(), timezone.utc).isoformat(timespec="seconds"),
               "qty": self._qty_str(q), "avg": avg, "mark": mid, "mtm": bag, "lots": len(lots)}
        if not lots and s.get("transfers"):
            # сторона уже передана раньше, лотов нет (снята всплывшая сирота): граница в журнале уже есть — второе
            # «передано оператору» с нулём сбивало бы мониторинг (14.10, ревью L2-3). Только запись учёта и лог
            s["transfers"] = list(s["transfers"]) + [{**rec, "mtm": 0.0, "repeat": True}]
            s["ref"] = None
            self.save()
            logger.info("weex_grid.release_repeat side=%s — сторона уже передана, свои ордера сняты, лотов нет; "
                        "в журнал не пишу", side)
            return True
        # постоянный номер события передачи (15.10, разбор GPT P2): один и тот же в учёте (transfers) и в журнале — по нему
        # запись журнала идемпотентна, сколько бы раз ни повторялась дозапись после сбоя. Со знаком сетки (b7g3-…): у
        # сеток одного символа номера не совпадают
        rec["event_id"] = (f"{self.own}-{self.cfg['symbol']}-{side}-hand-{int(self.now() * 1000)}-"
                           f"{len(s.get('transfers') or []) + 1}")
        s["transfers"] = list(s.get("transfers") or []) + [rec]
        s["transferred_mtm"] = float(s.get("transferred_mtm") or 0) + bag
        s["lots"], s["ref"] = [], None
        s["handover_unjournaled"] = rec
        self.save()                                             # учёт передачи — на диск до журнала (L8)
        self._journal_handover(side)
        if lots:
            self._notify(f"🤝 Сетка WEEX {self.label}: сторона {side} передана тебе — ордера бота сняты, "
                         f"{len(lots)} лот(ов) {self._qty_str(q)} по средней {avg:,.1f} (мешок ${bag:+.2f}, входит в "
                         f"итог сетки) остаются на бирже, бот их больше не ведёт.")
        else:
            self._notify(f"🤝 Сетка WEEX {self.label}: сторона {side} передана тебе — ордера бота сняты, "
                         f"лотов бота на стороне нет.")
        return True

    def _journal_handover(self, side: str) -> None:
        """Записать в журнал передачу, уже сохранённую в учёте, ровно один раз (ts — момент передачи). Идемпотентно по
        event_id (15.10, разбор GPT P2: запись в журнал прошла, а снятие флага handover_unjournaled на диске — нет; после
        рестарта передача дописывалась второй раз, сверка денег суммировала оба мешка): событие с тем же event_id уже в
        журнале — флаг снимается без записи. Журнал не читается — флаг остаётся, дозапись на следующем проходе. Флаг из
        учёта до 15.10 без номера получает его и сохраняется на диск ДО записи журнала."""
        s = self.st[side]
        rec = s.get("handover_unjournaled")
        if not rec:
            return
        if not rec.get("event_id"):
            rec["event_id"] = f"{self.own}-{self.cfg['symbol']}-{side}-hand-{rec.get('ts')}"
            for tr in s.get("transfers") or []:
                if tr.get("ts") == rec.get("ts") and not tr.get("event_id"):
                    tr["event_id"] = rec["event_id"]
            self.save()
        done = self._journal_events()
        if done is None:
            self._issue(f"журнал {self.journal_path.name} не читается — передача {side} будет дописана позже")
            return
        if rec["event_id"] in done:
            logger.warning("weex_grid.handover_already_journaled side=%s event=%s — повтор не пишу", side,
                           rec["event_id"])
        else:
            self._journal({"ts": rec["ts"], "side": side, "kind": HANDOVER, "qty": rec["qty"], "avg": rec["avg"],
                           "mark": rec["mark"], "bag": rec["mtm"], "lots": rec["lots"], "event_id": rec["event_id"]})
        s.pop("handover_unjournaled", None)
        self.save()

    def _journal_events(self) -> set[str] | None:
        """Номера событий (event_id), уже записанных в журнал; None — журнал есть, но не читается."""
        if not self.journal_path.exists():
            return set()
        try:
            text = self.journal_path.read_text(encoding="utf-8")
        except OSError:
            logger.exception("weex_grid.journal_read_failed path=%s", self.journal_path)
            return None
        out: set[str] = set()
        for line in text.splitlines():
            if '"event_id"' not in line:
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if isinstance(r, dict) and r.get("event_id"):
                out.add(str(r["event_id"]))
        return out

    def _find_market(self, side: str, fl: dict) -> dict | None:
        """Потерянный ответ рыночного закрытия: история ордеров по clientOrderId, затем сделки окна ±10 мин →
        деталь ордера → clientOrderId (12.10, разбор GPT L2: завершённого market нет в открытых, а короткая или
        пустая история — не доказательство, что он не исполнился). Негодный ответ истории (15.10, P1) — не повод
        прерывать проход: сбой в метку прохода, поиск идёт дальше по сделкам; не найден — повтора market нет."""
        srv = fl.get("srv") or fl["t"]
        try:
            o, _ = self._find_by_cid(fl["cid"], srv)
        except Exception as exc:                                # noqa: BLE001
            logger.exception("weex_grid.flatten_history_failed")
            self._issue(f"история для закрытия {fl['cid']} не прочитана ({type(exc).__name__}: {exc})")
            o = None
        if o is not None:
            return o
        o, _ = self._find_by_trades(fl["cid"], srv, side=side, want=CLOSE_SIDE[side], book=fl.setdefault("foreign", {}))
        return o

    def _flatten_side(self, side: str, bid: float, ask: float, mid: float) -> None:
        """Закрыть сторону по смене режима (как в research/weex/regime_grid.py): снять вход и тейки (исполненное до
        снятия — в прибыль), затем ОДИН рыночный reduceOnly на объём лотов бота. Намерение — на диск до отправки;
        пока исход отправленного ордера не выяснен — НОВОГО рыночного нет (12.10, разбор GPT L2); частичное —
        остаток следующим ордером только после конечного статуса прежнего."""
        s = self.st[side]
        if self.st["halted"] and int(s.get("flatten_rejects") or 0) >= 3:
            return                                              # стоп после трёх отказов — ждём оператора
        if s.get("pending") and not self._resolve_pending(side):
            return
        if s.get("flatten"):
            self._flatten_progress(side, mid)
            return
        self._drop_entry(side)
        if s.get("entry"):
            return
        if not self._cancel_tps(side):
            self.save()
            return
        if s["strays"]:
            self._process_strays(side, mid)
            if s["strays"]:
                return
        q = sum(float(l["qty"]) for l in s["lots"])
        if q <= self._tiny():
            s["ref"] = None
            self.save()
            return
        cid = self._cid(side, "x")
        srv = self.now() + float(getattr(self.c, "_offset_ms", 0) or 0) / 1000
        s["flatten"] = {"cid": cid, "qty": self._qty_str(q), "t": self.now(), "srv": srv,
                        "filled": 0.0, "filled_val": 0.0}
        self.save()
        try:
            r = self.c.place_market(self.cfg["symbol"], CLOSE_SIDE[side], side, self._qty_str(q), cid,
                                    reduce_only=True)
        except Exception as exc:                                # noqa: BLE001 — исход неизвестен, найдём по cid
            logger.warning("weex_grid.flatten_send_failed side=%s err=%s", side, exc)
            self._issue(f"рыночное закрытие {cid}: исход неизвестен ({type(exc).__name__}: {exc})")
            return
        if r and r.get("success") and r.get("orderId"):
            s["flatten"]["id"] = str(r["orderId"])
            self._notify(f"↩️ Сетка WEEX {self.label}: режим сменился — закрываю {side} {self._qty_str(q)} "
                         f"по рынку (лоты бота).")
        elif r and not r.get("success"):
            # явный отказ (чаще всего позиции на бирже меньше лотов — часть закрыта вручную): учёт к позиции
            # биржи; три отказа подряд (вместе с конечными исходами без исполнения) — стоп и сообщение
            s["flatten"] = None
            self._reconcile_side(side, mid)
            self._count_reject(side, r.get("errorCode") or r.get("msg") or r)
        self.save()

    def _count_reject(self, side: str, why) -> None:
        s = self.st[side]
        s["flatten_rejects"] = int(s.get("flatten_rejects") or 0) + 1
        if s["flatten_rejects"] >= 3 and s["lots"]:
            self.st["halted"] = True
            self.st["halt_reason"] = f"рыночное закрытие {side} по режиму не исполнилось 3 раза"
            self._notify(f"🛑 Сетка WEEX {self.label}: закрытие {side} по режиму 3 раза не исполнилось ({why}). "
                         f"Сетка остановлена, лоты бота в учёте — проверь позицию руками.")
        else:
            self._notify(f"⚠️ Сетка WEEX {self.label}: закрытие {side} по режиму не исполнилось ({why}) — "
                         f"сверил учёт с позицией, повторю.")

    def _flatten_progress(self, side: str, mid: float) -> None:
        """Сопровождение УЖЕ отправленного рыночного закрытия: найти (если ответ потерян), учесть прирост
        исполнения по курсору, завершить только на подтверждённом конечном статусе. Новых ордеров не ставит."""
        s, d = self.st[side], DIR[side]
        fl = s["flatten"]
        if not fl.get("id"):
            # 15.10: полный поиск потерянного market (история делением окна, сделки окна, детали) — не чаще раза в
            # PENDING_RECHECK. При смене режима четыре сетки BTC закрываются в одном проходе, окно ±10 мин плотное (их
            # снятые тейки); поиск каждым проходом по каждой сетке упирался бы в лимит веса WEEX (500 за 10 с на IP).
            # Пропуск поиска ничего не отправляет: пока исход неизвестен, нового market нет
            last = float(fl.get("search_ts") or 0)
            o = None
            if not 0 <= self.now() - last < PENDING_RECHECK:
                fl["search_ts"] = float(self.now())
                o = self._find_market(side, fl)
            if o is None:
                if self.now() - fl["t"] >= PENDING_TTL and not fl.get("warned"):
                    fl["warned"] = True
                    self.save()
                    self._notify(f"⚠️ Сетка WEEX {self.label}: ответ на рыночное закрытие {side} потерян и ордер "
                                 f"{fl['cid']} пока не найден. Повторно НЕ отправляю (мог исполниться) — ищу дальше; "
                                 f"проверь позицию.")
                return
            fl["id"] = str(o.get("orderId"))
            self.save()
        kind, info = self._detail(fl["id"], side, fl)
        if kind == "unknown":
            return
        exq = float(info.get("executedQty") or 0)
        dq = exq - float(fl.get("filled") or 0)
        if dq > self._tiny():
            avg = float(info.get("avgPrice") or 0) or mid
            val = avg * exq
            px = (val - float(fl.get("filled_val") or 0)) / dq
            fl["filled"], fl["filled_val"] = exq, val
            self._mark_fills(side, fl)
            fee, _ = self._fee_delta(side, fl["id"])
            rem, pnl = dq, 0.0
            for lot in list(s["lots"]):                         # старые лоты первыми
                take = min(float(lot["qty"]), rem)
                pnl += d * take * (px - lot["entry"])
                left = float(lot["qty"]) - take
                if left <= self._tiny():
                    s["lots"].remove(lot)
                else:
                    lot["qty"] = self._qty_str(left)
                rem -= take
                if rem <= self._tiny():
                    break
            s["realized"] += pnl
            s["fees"] += fee
            s["turnover"] += dq * px
            s["flatten_rejects"] = 0                            # был прогресс
            self.save()                                         # учёт на диск ДО журнала (12.10, разбор GPT L8)
            self._journal({"side": side, "kind": "закрытие по режиму", "price": px, "qty": self._qty_str(dq),
                           "fee": fee, "pnl": pnl, "order_id": fl["id"], "cum_qty": exq})
        if kind == "live":
            self.save()
            return
        s["flatten"] = None
        if exq <= self._tiny():                                 # конечный без исполнения (REJECTED/EXPIRED…)
            self._count_reject(side, info.get("status"))
        if not s["lots"]:
            s["ref"] = None
            self._notify(f"✅ Сетка WEEX {self.label}: {side} закрыт по режиму, новых входов до смены режима нет.")
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
        if self.label != self.cfg["symbol"]:
            return self._card_compact(mid)
        cfg = self.cfg
        tick = float(cfg["price_tick"])
        mode = ("ВЫКЛ" if not cfg["enabled"] else "ХОЛОСТОЙ (без ордеров)" if cfg["dry_run"] else "ЖИВАЯ")
        lines = [f"🕸 СЕТКА WEEX {cfg['symbol']} — {mode}" + (f" · СТОП: {self.st['halt_reason']}" if self.st["halted"] else ""),
                 f"шаг {cfg['step_pct']}% · цель {cfg['target_pct']}% · ордер {cfg['order_qty']} · цена {fmt_px(mid, tick)}"]
        if int(cfg.get("regime_sma") or 0) > 0:
            r = self.st.get("regime")
            lines.append(f"режим SMA{int(cfg['regime_sma'])}: " + ("ЛОНГ (цена выше)" if r is True else "ШОРТ (цена ниже)"
                         if r is False else "нет данных — новых входов нет"))
        tm_all = 0.0
        for side in ("LONG", "SHORT"):
            s = self.st[side]
            tm = float(s.get("transferred_mtm") or 0)
            tm_all += tm
            if side not in cfg["sides"] and not (s.get("entry") or s["lots"] or s["strays"]):
                # сторона снята из конфига/передана: её история владения остаётся в итоге и видна (13.10, дополнение
                # GPT §3: старые realised/fees не должны прятаться за общей строкой итога)
                tr = s.get("transfers") or []
                name = "ЛОНГ" if side == "LONG" else "ШОРТ"
                hist = f"закрыто ${s['realized']:+.2f}, комиссии ${s['fees']:.3f}"
                if tr:
                    when = str(tr[-1].get("ts") or "")[:16].replace("T", " ")
                    lines.append(f"🤝 {name} передан оператору {when}: мешок при передаче ${tm:+.2f}, {hist} — в итоге "
                                 f"сетки; дальше позиция не бота")
                elif s["realized"] or s["fees"]:
                    lines.append(f"⏹ {name} снят из конфига: {hist} — в итоге сетки")
                continue
            q = sum(float(l["qty"]) for l in s["lots"])
            un = sum(DIR[side] * float(l["qty"]) * (mid - l["entry"]) for l in s["lots"])
            ent = f"вход {fmt_px(s['entry']['price'], tick)}" if s.get("entry") else ("вход нет: " + s.get("blocked", "") if s.get("blocked") else "вход нет")
            lines.append(f"{'🟢 ЛОНГ' if side == 'LONG' else '🔴 ШОРТ'}: {self._slots(side)} орд. ({q:g}), мешок ${un:+.2f}, "
                         f"закрыто ${s['realized']:+.2f}, комиссии ${s['fees']:.3f}, тейков {s['n_tps']} · {ent}")
        tot = self.bot_pnl(mid)
        turn = sum(self.st[s]["turnover"] for s in ("LONG", "SHORT"))
        lines.append(f"итог сетки с мешком ${tot:+.2f}"
                     + (f" (в т.ч. мешок, переданный оператору, ${tm_all:+.2f} — по цене передачи)" if tm_all else "")
                     + f" · оборот ${turn:,.0f}")
        return "\n".join(lines)

    def _card_compact(self, mid: float) -> str:
        """Карточка сетки со своим именем (B34 …, 15.10): 1–3 строки, чтобы несколько сеток одного символа не раздували
        /weex. Выключенная сетка без истории — одна строка; режим SMA — в заголовке, только когда он не пускает входы."""
        cfg, tick = self.cfg, float(self.cfg["price_tick"])
        mode = "ВЫКЛ" if not cfg["enabled"] else "ХОЛОСТОЙ" if cfg["dry_run"] else "ЖИВАЯ"
        if cfg["enabled"] and int(cfg.get("regime_sma") or 0) > 0 and self.st.get("regime") is not True:
            mode += " · ниже SMA — входов нет" if self.st.get("regime") is False else " · режим неизвестен — входов нет"
        rows = [f"🕸 {self.label} — {mode}" + (f" · СТОП: {self.st['halt_reason']}" if self.st["halted"] else "")
                + f" · шаг {cfg['step_pct']}% цель {cfg['target_pct']}% ордер {cfg['order_qty']}"]
        hist = any(self._side_busy(x) or self.st[x]["realized"] or self.st[x]["fees"] or self.st[x].get("transferred_mtm")
                   for x in DIR)
        if not cfg["enabled"] and not hist:
            return rows[0]
        for side in DIR:
            s = self.st[side]
            if side not in cfg["sides"] and not self._side_busy(side) and not (s["realized"] or s["fees"]):
                continue
            q = sum(float(l["qty"]) for l in s["lots"])
            un = sum(DIR[side] * float(l["qty"]) * (mid - l["entry"]) for l in s["lots"])
            ent = (f"вход {fmt_px(s['entry']['price'], tick)}" if s.get("entry") else
                   f"вход нет: {s['blocked']}" if s.get("blocked") else "вход нет")
            rows.append(f"{'🟢 Л' if side == 'LONG' else '🔴 Ш'} {self._slots(side)} орд. ({q:g}), мешок ${un:+.2f}, "
                        f"закрыто ${s['realized']:+.2f}, ком. ${s['fees']:.3f}, тейков {s['n_tps']} · {ent}")
        turn = sum(self.st[s]["turnover"] for s in DIR)
        rows.append(f"итог с мешком ${self.bot_pnl(mid):+.2f} · оборот ${turn:,.0f}")
        return "\n".join(rows)


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

    def place_market(self, symbol, side, position_side, qty, cid, reduce_only=False):
        """Рыночный ордер — сразу по лучшей встречной цене (комиссия тейкера 0.048%). reduceOnly — не больше
        позиции стороны; позиции нет — отказ (как биржа)."""
        bid, ask = self.book_fn()
        px = ask if side == "BUY" else bid
        if reduce_only:
            pos = next((float(p["size"]) for p in self.futures_positions() if p["side"] == position_side), 0.0)
            if pos <= 0:
                return {"success": False, "errorCode": "REDUCE_ONLY_NO_POSITION", "orderId": None}
            qty = f"{min(float(qty), pos):.4f}"
        self.n += 1
        oid = f"dry{self.n}"
        self.orders[oid] = {"clientOrderId": cid, "side": side, "positionSide": position_side, "price": str(px),
                            "origQty": qty, "status": "FILLED", "executedQty": qty, "avgPrice": str(px),
                            "reduceOnly": reduce_only, "type": "MARKET"}
        self.trades[oid] = [{"id": f"t{oid}", "orderId": oid, "commission": str(float(qty) * px * 0.00048),
                             "maker": False, "price": str(px), "qty": qty, "time": int(self.now_fn() * 1000)}]
        return {"success": True, "orderId": oid, "clientOrderId": cid}

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
