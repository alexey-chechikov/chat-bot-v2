"""Общее для проверочных скриптов WEEX (account_now, pnl_reconcile) — только чтение (разбор GPT 13.10, §3 Q1/Q3).

- История сделок: ответ обязан быть списком сделок с обязательными полями; null, не список, ошибка запроса —
  ReadError («не прочитано»), а не «ноль сделок». Нулём считается только подтверждённый пустой список.
- Владелец ордера: деталь с ТЕМ ЖЕ orderId; clientOrderId b7g… — бот, иная непустая строка (у ручных ордеров
  оператора — UUID) — ручной. Поля clientOrderId нет, оно null, пустое или не строка — владелец НЕИЗВЕСТЕН (не
  «ручной»), если номер ордера не найден в реестре бота (orderId из журнала и учёта). Номер из реестра при чужом
  clientOrderId — противоречие → неизвестен. Те же правила — для элемента списка открытых ордеров (cid_owner).
- Время из учёта/журнала: число (сек или мс), ISO-строка или словарь с «ts».
- Несколько сеток на одном символе (15.10, B34/B49/B89 рядом с BTC): префикс сетки = b7g + её знак (engine.cid_tag).
  Свой префикс — бот ЭТОЙ сетки; префикс другой сетки — OTHER (не своя, не ручная, не неизвестная: сделки и ордера
  соседки в сверку сетки не идут и сиротами не считаются); b7g со знаком ни одной сетки — владелец неизвестен.
"""
from __future__ import annotations

import json
import math
import re
import time
from datetime import datetime
from pathlib import Path

HANDOVER = "передано оператору"
TRADE_FIELDS = ("id", "orderId", "positionSide", "side", "price", "qty", "time")
WINDOW_MS = 6 * 86_400_000
BOT, MANUAL, OTHER = "bot", "manual", "other"      # OTHER — ордер другой сетки бота (b7g + чужой знак)
# Формат первых дней живой BTC (09.10 11:31 … 10.10 05:38, проверено по деталям ордеров на счёте 18.10): b7g + сторона
# (L/S) + вид + время — без буквы символа. Тогда на BTCUSDT была одна сетка — BTC (знак 'B'); знаки L/S новым сеткам
# не давать.
LEGACY_BTC = re.compile(r"b7g[LS][a-z]\d")
# 15.10: лимит WEEX — 500 веса за 10 с на IP (заголовок X-USED-WEIGHT-10S), IP общий с живым циклом сеток. Четыре сетки
# BTC за неделю — тысячи сделок: деление окон шло бы десятками запросов подряд (сделки вес 5) и могло упереться в 429
# (бан IP на 10 с — проходы живых сеток падали бы). Пауза между запросами сделок/деталей: ≤ 40 запросов за 10 с.
PACE_SEC = 0.25
_last_call = [0.0]


def _pace() -> None:
    if PACE_SEC > 0:
        wait = _last_call[0] + PACE_SEC - time.monotonic()
        if wait > 0:
            time.sleep(wait)
    _last_call[0] = time.monotonic()


class ReadError(RuntimeError):
    """Ответ биржи не прочитан — это не «ноль сделок»."""


def epoch(x) -> float | None:
    """Секунды epoch из числа (сек/мс), ISO-строки или словаря {'ts': …}; иначе None."""
    if isinstance(x, dict):
        x = x.get("ts")
    if isinstance(x, bool) or x is None:
        return None
    if isinstance(x, (int, float)):
        v = float(x)
    elif isinstance(x, str):
        try:
            v = float(x)
        except ValueError:
            try:
                return datetime.fromisoformat(x).timestamp()
            except ValueError:
                return None
    else:
        return None
    if not math.isfinite(v) or v <= 0:
        return None
    return v / 1000 if v > 1e11 else v


def epoch_ms(x) -> int | None:
    v = epoch(x)
    return None if v is None else int(v * 1000)


def read_journal(path: Path) -> tuple[list[dict], int]:
    """(записи, число битых строк). Битая строка — повод не доверять сверке, а не молча пропустить."""
    path = Path(path)
    if not path.exists():
        return [], 0
    out, bad = [], 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except ValueError:
            bad += 1
            continue
        if isinstance(r, dict):
            out.append(r)
        else:
            bad += 1
    return out, bad


def trade_rows(resp, what: str = "сделки", extra: tuple = ()) -> list[dict]:
    if isinstance(resp, dict) and isinstance(resp.get("data"), list):
        resp = resp["data"]
    if not isinstance(resp, list):
        raise ReadError(f"{what}: ответ не список — {str(resp)[:200]}")
    for t in resp:
        if not isinstance(t, dict) or any(t.get(k) in (None, "") for k in TRADE_FIELDS + tuple(extra)):
            raise ReadError(f"{what}: сделка без обязательных полей — {str(t)[:200]}")
    return resp


def fetch_trades(c, sym: str, start_ms: int, end_ms: int | None = None,
                 extra: tuple = ()) -> tuple[list[dict], list[tuple[int, int]]]:
    """Все сделки символа [start, end]: окна ≤6 суток, окно со 100 сделками делится пополам до 1 с; переполненное
    секундное окно — неполная выборка (второй элемент). Ошибка/null/не список/нет полей → ReadError."""
    end_ms = int(time.time() * 1000) + 60_000 if end_ms is None else int(end_ms)
    incomplete: list[tuple[int, int]] = []

    def get(a: int, b: int) -> list[dict]:
        _pace()
        try:
            r = c.user_trades(sym, start_ms=a, end_ms=b)
        except Exception as e:                                   # noqa: BLE001
            raise ReadError(f"сделки {sym}: ошибка запроса — {e}") from e
        rows = trade_rows(r, f"сделки {sym}", extra)
        if len(rows) < 100:
            return rows
        if b - a <= 1000:
            incomplete.append((a, b))
            return rows
        m = (a + b) // 2
        return get(a, m) + get(m + 1, b)

    out, a = [], int(start_ms)
    while a < end_ms:
        b = min(a + WINDOW_MS, end_ms)
        out += get(a, b)
        a = b + 1
    return list({str(t["id"]): t for t in out}.values()), incomplete


def grid_registry(eg, name: str) -> set[str]:
    """Реестр ордеров сетки name по её ЖИВЫМ учёту и журналу (только чтение); файлов нет/не читаются — пусто."""
    _, sp, jp = eg.grid_files(name)
    try:
        st = json.loads(Path(sp).read_text(encoding="utf-8")) if Path(sp).exists() else None
    except (OSError, ValueError):
        st = None
    try:
        journal, _ = read_journal(jp)
    except OSError:
        journal = []
    return own_order_ids(st if isinstance(st, dict) else None, journal)


def own_order_ids(st: dict | None, journal: list[dict]) -> set[str]:
    """Реестр собственных ордеров бота: order_id записей журнала + курсоры/ссылки учёта (order_fills, fee_book,
    вход, тейки, strays, рыночное закрытие)."""
    ids = {str(r["order_id"]) for r in journal if r.get("order_id") not in (None, "")}
    for s in ("LONG", "SHORT"):
        sd = (st or {}).get(s) or {}
        ids.update(str(k) for k in (sd.get("order_fills") or {}))
        ids.update(str(k) for k in (sd.get("fee_book") or {}))
        refs = [sd.get("entry"), sd.get("flatten")] + [l.get("tp_order") for l in sd.get("lots") or []]
        refs += list(sd.get("strays") or [])
        ids.update(str(o["id"]) for o in refs if isinstance(o, dict) and o.get("id") not in (None, ""))
    return ids


def cid_owner(cid, oid, prefix: str, registry: set | frozenset = frozenset(), others=(),
              family: str | None = None) -> str | None:
    """BOT | OTHER | MANUAL | None по clientOrderId ордера с ПРОВЕРЕННЫМ orderId — правила в шапке модуля.
    prefix — префикс СВОЕЙ сетки (b7g+знак); others — префиксы других сеток; family — общий префикс бота (b7g): ордер
    с ним, но без знака известной сетки — владелец неизвестен. others/family не заданы — прежнее правило (одна сетка)."""
    oid = str(oid)
    if isinstance(cid, str) and cid.startswith(prefix):
        return BOT
    if isinstance(cid, str) and any(cid.startswith(p) for p in others):
        return None if oid in registry else OTHER
    if isinstance(cid, str) and family and LEGACY_BTC.match(cid):
        return BOT if prefix == family + "B" else OTHER
    if isinstance(cid, str) and family and cid.startswith(family):
        # b7g без знака известной сетки. Прежний формат первых дней BTC (09–10.10: b7g + сторона, без буквы символа) —
        # свой, если номер есть в реестре ЭТОЙ сетки (журнал/учёт); иначе владелец неизвестен (18.10: без этого сверка
        # BTC теряла 37 старых ордеров и писала «не всё прочитано»)
        return BOT if oid in registry else None
    if isinstance(cid, str) and cid.strip():
        return None if oid in registry else MANUAL
    return BOT if oid in registry else None


def order_owner(c, oid, prefix: str, registry: set | frozenset = frozenset(), cache: dict | None = None,
                others=(), family: str | None = None, other_registry: set | frozenset = frozenset()) -> str | None:
    """BOT | OTHER | MANUAL | None (владелец не установлен) по детали ордера — правила в шапке модуля.
    other_registry — номера ордеров ДРУГИХ сеток символа (их журналы и учёт): номер только там, а не в своём реестре —
    OTHER без запроса детали (за неделю четырёх сеток BTC — тысячи ордеров соседок; деталь каждой — лишний вес запросов)."""
    oid = str(oid)
    if cache is not None and oid in cache:
        return cache[oid]
    if oid in other_registry and oid not in registry:
        res = OTHER
    else:
        _pace()
        try:
            info = c.order_info(oid)
        except Exception:                                        # noqa: BLE001
            info = None
        matched = isinstance(info, dict) and str(info.get("orderId")) == oid
        # деталь не прочитана/чужой orderId — владелец только по реестру бота (номер ордера из сделки биржи)
        res = cid_owner(info.get("clientOrderId") if matched else None, oid, prefix, registry, others, family)
    if cache is not None:
        cache[oid] = res
    return res


def owner_prefixes(tags: dict, name: str, family: str) -> tuple[str, tuple[str, ...]]:
    """(свой префикс, префиксы других сеток) по {сетка: знак} (engine.grid_tags). Знак сетки не установлен — ValueError
    с причиной (свои ордера не определить — проверка не выполняется)."""
    tag = tags.get(name)
    if not tag:
        raise ValueError(f"знак ордеров сетки {name} не установлен (конфиг не читается или cid_tag негоден)")
    clash = sorted(n for n, t in tags.items() if n != name and t and t.upper() == tag.upper())
    if clash:                                       # как engine.check_tag: сетка с таким знаком стоит (GridHalt)
        raise ValueError(f"знак ордеров «{tag}» сетки {name} совпадает со знаком сетки {', '.join(clash)}")
    return family + tag, tuple(family + t for n, t in tags.items() if n != name and t)


def grid_of_cid(cid, tags: dict, family: str) -> str | None:
    """Имя сетки по clientOrderId (family + знак сетки); не ордер бота или знак ни одной сетки — None."""
    if not isinstance(cid, str) or not cid.startswith(family) or len(cid) <= len(family):
        return None
    ch = cid[len(family)]
    return next((n for n, t in tags.items() if t == ch), None)
