"""Только чтение: счёт WEEX, жив ли цикл сеток, сохранность переданной оператору стороны (ревью скилов 12.10,
разбор GPT 13.10 §3 Q1 — ложные «ок»).

card_now.py баланса не показывает. Здесь:
  1) депозит и все позиции (включая ручные) — средняя = openValue/size, фандинг — cumFundingFee (поля сверены по
     сырому ответу /capi/v3/account/position/allPosition 12.10); ответ не списком/не словарём → «НЕ ПРОЧИТАНО», код 2;
  2) жив ли цикл — для каждой сетки, которую цикл ведёт живьём: не dry_run (в том числе после /weex stop, enabled=false
     — тейки и закрытие по режиму продолжаются) или холостой с живыми остатками в учёте. Судим по УСПЕШНОМУ проходу:
     ключ учёта last_tick_ok_ts (движок пишет после полного прохода) — до 60 с «жив», 60–180 с «перепроверить»
     (код 2), старше — ПРОБЛЕМА; last_tick_error новее успеха — ПРОБЛЕМА. mtime файла учёта успехом не считается:
     _orphans сохраняет учёт до сопровождения сторон, падающие проходы тоже освежают файл. Ключа нет (старый
     движок) — «успешность прохода не подтверждена», код 2 (свежий файл) или ПРОБЛЕМА (файл старше 180 с).
     Флаг halted в учёте — ПРОБЛЕМА;
  3) режим SMA — той же проверкой, что engine.regime_up (вчерашний день UTC, последовательные дни, конечные цены > 0);
     режим неизвестен (дневки устарели/с пропуском/битые/не прочитаны) — ПРОБЛЕМА: у движка нет новых входов и нет
     закрытия по режиму. Плюс порог СЕГОДНЯШНЕГО дневного закрытия UTC, который меняет режим;
  4) сторона из release_sides (и не из sides — иначе движок её не передаёт): объём на бирже, ордера и algo-ордера бота
     на ней (0), СДЕЛКИ бота на ней после «передано оператору» (0) — по бирже, а не по журналу бота. Владелец сделки и
     открытого ордера — research/weex/weex_monitor_common (нет/пустой clientOrderId и номера нет в реестре бота —
     неизвестен, код 2); история null/не список — «не прочитано», код 2; журнала нет — начала истории нет, код 2;
     сделка бота в секунду записи передачи считается «до» только если её ордер учтён журналом до передачи. Записей
     передачи — не больше одной; записи нет, а сделки бота на стороне есть — результат неизвестен (код 2): границы
     передачи нет.
  Несколько сеток на символе (15.10: BTC и B34/B49/B89): своя сетка — b7g + её знак; ордер или сделка ДРУГОЙ сетки бота
  на переданной оператору стороне — тоже ПРОБЛЕМА (бот на стороне оператора), отдельной строкой; режим SMA одного
  символа печатается один раз; конфиг сетки, ещё не созданный циклом, берётся из шаблона (сетка холостая — пропуск).
  5) общая позиция стороны против суммы лотов ВСЕХ живых сеток символа: позиция на бирже МЕНЬШЕ суммы — часть общей
     позиции закрыта не сетками (вручную?) или учёт отстал от исполнения — код 2, перепроверить через 10–20 с (каждая
     сетка сама сверяет позицию только со СВОИМИ лотами и такого не видит: её тейк/закрытие по режиму могут закрыть
     контракты соседки); больше суммы — ручное или неучтённое, печатается.

    .venv/bin/python3 research/weex/account_now.py      (код 1 — проблема, 2 — не прочитано/не подтверждено)
"""
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from services.weex_api.client import WeexClient  # noqa: E402
from services.weex_grid import engine as eg  # noqa: E402
from research.weex import weex_monitor_common as mc  # noqa: E402

FRESH_SEC, STALE_SEC = 60, 180
LEFTOVER_KEYS = ("entry", "lots", "strays", "pending", "flatten")


def rows_or_exit(x, what: str) -> list:
    if isinstance(x, list):
        return x
    if isinstance(x, dict) and isinstance(x.get("data"), list):
        return x["data"]
    if isinstance(x, dict) and ("balance" in x or "asset" in x):
        return [x]
    print(f"{what}: НЕ ПРОЧИТАНО — ответ {str(x)[:200]}")
    sys.exit(2)


def liveness(st: dict | None, st_path: Path, now: float) -> tuple[str, str]:
    """('ok'|'check'|'bad', текст) — по успешному проходу, не по mtime файла учёта."""
    if st is None or not st_path.exists():
        return "bad", "ПРОБЛЕМА: учёта нет — сетка не ходит"
    file_age = now - st_path.stat().st_mtime
    ok_ts = mc.epoch(st.get("last_tick_ok_ts"))
    err = st.get("last_tick_error")
    err_ts = mc.epoch(err)
    why = ""
    if isinstance(err, dict):                    # движок: {ts, phase, err, fatal}; fatal false — неясная деталь ордера
        why = " ".join(str(err.get(k)) for k in ("phase", "err", "error", "msg") if err.get(k))
        if err.get("fatal") is False:
            why = f"(проход без исключения, но неясно) {why}".strip()
    why = f": {why}" if why else ""
    if ok_ts is None:
        if err_ts is not None:
            return "bad", f"ПРОБЛЕМА: успешного прохода не записано, ошибка прохода {now - err_ts:.0f} с назад{why}"
        if file_age > STALE_SEC:
            return "bad", f"ПРОБЛЕМА: сетка не ходит — учёт не обновлялся {file_age:.0f} с"
        return "check", (f"успешность прохода не подтверждена (старый движок: нет last_tick_ok_ts; учёт обновлён "
                         f"{file_age:.0f} с назад, но его пишет и падающий проход)")
    age = now - ok_ts
    if err_ts is not None and err_ts > ok_ts:
        return "bad", (f"ПРОБЛЕМА: последний проход с ошибкой ({now - err_ts:.0f} с назад{why}); последний успешный "
                       f"{age:.0f} с назад")
    if age < -30:
        return "check", f"время успешного прохода в будущем ({-age:.0f} с) — часы? перепроверить"
    if age > STALE_SEC:
        return "bad", f"ПРОБЛЕМА: успешного прохода нет {age:.0f} с (файл учёта обновлён {file_age:.0f} с назад)"
    if age > FRESH_SEC:
        return "check", f"последний успешный проход {age:.0f} с назад — пауза после ошибки? перепроверить через минуту"
    return "ok", f"цикл жив: последний успешный проход {age:.0f} с назад"


def regime_line(sym: str, n: int, c) -> tuple[str, str]:
    """('ok'|'check'|'bad', текст). Решение — engine.regime_up (та же проверка дневок, что у живого движка); здесь
    только порог: close > (сумма прошлых n−1 закрытий)/(n−1) ⇔ close > SMA{n}, включающей этот close."""
    now = time.time()
    seen: list = []

    def fetch(symbol, limit):
        rows = eg._fetch_daily(symbol, limit)
        seen.append(rows)
        return rows

    band = eg.symbol_band(sym)                         # 25.10: полоса режима живых сеток символа (гистерезис)
    if band is None:
        return "bad", f"SMA{n}: ПРОБЛЕМА — у живых сеток {sym} разная полоса режима (regime_band_pct) — сверить конфиги"
    for k in ((sym, n), (sym, n, band)):
        eg._REGIME_CACHE.pop(k, None)                  # проверить сейчас, а не взять решение из кэша процесса
        eg._REGIME_CACHE.pop(("fail",) + k, None)      # и не пропуск после недавнего сбоя
    up = eg.regime_up(sym, n, now=now, fetch=fetch, band_pct=band)
    if up is None or not seen:
        return "bad", (f"SMA{n}: ПРОБЛЕМА — режим неизвестен (дневки не прочитаны, не вчерашние, с пропуском дня или "
                       f"битые) → у движка нет новых входов и нет закрытия по режиму")
    bars = {int(r[0]) // 86_400_000: r for r in seen[-1] if int(r[6]) < now * 1000}
    closes = [float(bars[d][4]) for d in sorted(bars)[-n:]]
    sma = sum(closes) / n
    thr = eg.regime_threshold(closes, n, up, band)
    bt = f" (полоса {band:g}%)" if band else ""
    what = (f"лонги закроются по рынку, если сегодняшний день UTC закроется НИЖЕ {thr:,.2f}{bt}" if up else
            f"лонги снова разрешатся, если сегодняшний день UTC закроется ВЫШЕ {thr:,.2f}{bt}")
    head = (f"режим {'ЛОНГ' if up else 'ВНЕ РЫНКА'}: SMA{n} {sma:,.2f}, вчерашнее закрытие "
            f"{closes[-1]:,.2f} ({closes[-1] / sma - 1:+.1%})")
    try:
        bid, ask = c.book(sym)
        mid = (bid + ask) / 2
    except Exception as e:                                       # noqa: BLE001
        return "check", f"{head}; {what}; цена не прочитана ({e})"
    return "ok", f"{head}; цена {mid:,.2f}; {what} ({thr / mid - 1:+.1%} от цены)"


def check_released(name: str, sym: str, cfg: dict, st: dict | None, journal_path: Path, c,
                   size_of: dict, own: str = eg.PREFIX, others: tuple = (), legit_prefixes: tuple = (),
                   legit_registry: set | frozenset = frozenset()) -> tuple[bool, bool]:
    """(проблема, не прочитано) по сторонам, переданным оператору. own — префикс ордеров этой сетки (b7g+знак), others —
    префиксы других сеток: их ордера/сделки на переданной стороне — тоже бот на стороне оператора (ПРОБЛЕМА).
    legit_prefixes / legit_registry — сетки, которые САМИ ведут эту сторону (sides; 21.10 шорт-сетка SB на BTCUSDT SHORT):
    их ордера (по префиксу) и сделки (по номерам ордеров их учёта и журнала) — не нарушение передачи."""
    sides = cfg.get("sides") or []
    released = [s for s in (cfg.get("release_sides") or []) if s in eg.DIR and s not in sides]
    if not released:
        return False, False
    problem = unread = False
    journal, n_bad = mc.read_journal(journal_path)
    if n_bad:
        print(f"{name} {sym}: журнал — битых строк {n_bad}, проверка передачи недостоверна")
        unread = True
    registry = mc.own_order_ids(st, journal)
    handed = {s: [r for r in journal if r.get("side") == s and r.get("kind") == mc.HANDOVER] for s in released}
    first_ts = journal[0].get("ts") if journal else None
    # открытые ордера переданной стороны: владелец по clientOrderId, без него — по реестру бота, иначе неизвестен
    on_side = [o for o in c.open_orders(sym) if o.get("positionSide") in released]
    who_open = [(o, mc.cid_owner(o.get("clientOrderId"), o.get("orderId"), own, registry, others, eg.PREFIX))
                for o in on_side]
    mine = [o for o, w in who_open if w == mc.BOT]
    open_other = [o for o, w in who_open if w == mc.OTHER
                  and not str(o.get("clientOrderId") or "").startswith(tuple(legit_prefixes))]
    open_unk = [o for o, w in who_open if w is None]
    algo = [a for a in (c.open_algo_orders(sym) or []) if str(a.get("clientAlgoId", "")).startswith("b7")
            and a.get("positionSide") in released]
    starts = [mc.epoch_ms(r.get("ts")) for v in handed.values() for r in v] + [mc.epoch_ms(first_ts)]
    starts = [x for x in starts if x is not None]
    fills, incomplete, read_err = [], [], None
    if starts:
        try:
            fills, incomplete = mc.fetch_trades(c, sym, min(starts))
        except mc.ReadError as e:
            read_err = str(e)
    else:                                         # нет ни журнала, ни записи передачи — начала истории нет
        read_err = "журнала бота нет — начала истории нет, сделки бота на стороне не проверены"
    cache: dict = {}
    for s in released:
        recs = handed[s]
        t0 = mc.epoch_ms(recs[0].get("ts")) if recs else None
        booked_before = {str(r["order_id"]) for r in journal if r.get("order_id") not in (None, "") and t0 is not None
                         and (mc.epoch_ms(r.get("ts")) or 0) <= t0}
        bot_after, last_bot, n_unread, other_fills = [], None, 0, []
        for t in fills:
            if t.get("positionSide") != s:
                continue
            who = mc.order_owner(c, t["orderId"], own, registry, cache, others=others, family=eg.PREFIX)
            if who is None:
                n_unread += 1
                continue
            if who == mc.OTHER:
                if str(t["orderId"]) in legit_registry:
                    continue                             # сетка, которая сама ведёт эту сторону (SB) — законно
                other_fills.append(t)                    # другая сетка бота на стороне оператора — за всё время
                continue
            if who != mc.BOT:
                continue
            tt = int(t["time"])
            last_bot = max(last_bot or 0, tt)
            if t0 is not None and (tt >= t0 + 1000 or (tt >= t0 and str(t["orderId"]) not in booked_before)):
                bot_after.append(t)
        n_ord = len([o for o in mine if o.get("positionSide") == s])
        n_ord_other = len([o for o in open_other if o.get("positionSide") == s])
        n_ord_unk = len([o for o in open_unk if o.get("positionSide") == s])
        n_algo = len([a for a in algo if a.get("positionSide") == s])
        bad = bool(len(recs) > 1 or n_ord or n_algo or bot_after or n_ord_other or other_fills)
        no_boundary = not recs and last_bot is not None
        side_unread = bool(n_unread or n_ord_unk or incomplete or read_err or no_boundary)
        problem |= bad
        unread |= side_unread
        when = str(recs[0].get("ts", "?"))[:16] if recs else "записи нет (передана без лотов?)"
        if bad:
            verdict = "ПРОБЛЕМА"
        elif no_boundary:
            verdict = "результат неизвестен: записи передачи нет, а сделки бота на стороне есть — границы нет"
        elif side_unread:
            verdict = "не прочитано — перепроверить"
        else:
            verdict = "бот сторону не трогал"
        print(f"{name} {sym} {s} передан оператору {when} (записей {len(recs)}): позиция на бирже "
              f"{size_of.get((sym, s), 0):g}"
              + (" (в т.ч. лоты сеток, которые сами ведут сторону — ручная часть = позиция − их лоты, см. ниже)"
                 if legit_prefixes else "")
              + " — сверить с прошлым значением (память project_portfolio_now); "
              f"ордеров бота {n_ord}, algo бота {n_algo}, сделок бота после передачи "
              f"{len(bot_after) if recs else 'н/д'}"
              + (f"; последняя сделка бота на стороне {datetime.fromtimestamp(last_bot / 1000):%m-%d %H:%M}"
                 if last_bot and not recs else "")
              + (f"; ДРУГИЕ СЕТКИ БОТА на стороне: ордеров {n_ord_other}, сделок {len(other_fills)}"
                 if n_ord_other or other_fills else "")
              + (f"; владелец не установлен у {n_unread} сделок (нет clientOrderId/детали)" if n_unread else "")
              + (f"; открытых ордеров без владельца {n_ord_unk} (нет clientOrderId)" if n_ord_unk else "")
              + (f"; история сделок НЕ ПРОЧИТАНА — {read_err}" if read_err else "")
              + ("; ВЫБОРКА СДЕЛОК НЕПОЛНА" if incomplete else "")
              + f" → {verdict}")
    return problem, unread


def main() -> None:
    c = WeexClient()
    c.sync_time()
    problem = unread = False
    for b in rows_or_exit(c.futures_balance(), "баланс"):
        vals = {k: b.get(k) for k in ("balance", "availableBalance", "unrealizePnl", "frozen") if b.get(k) is not None}
        print("баланс", b.get("asset"), vals)
    size_of = {}
    for p in rows_or_exit(c.futures_positions(), "позиции"):
        size = float(p.get("size") or 0)
        if not size:
            continue
        size_of[(p.get("symbol"), p.get("side"))] = size
        print("позиция", p.get("symbol"), p.get("side"), "объём", p["size"],
              "средняя", round(float(p.get("openValue") or 0) / size, 4), "PnL", p.get("unrealizePnl"),
              "фандинг", p.get("cumFundingFee"))
    tags = eg.grid_tags()
    # 21.10: сетки, которые САМИ ведут сторону (sides) на символе, — их ордера на стороне, переданной оператору другой
    # сеткой, не нарушение передачи (шорт-сетка SB на BTCUSDT SHORT рядом с переданным шортом основной BTC)
    side_owners: dict[tuple, set] = {}
    for n in eg.GRIDS:
        c_n = eg.peek_config(n) or {}
        for s_n in c_n.get("sides") or []:
            if tags.get(n):
                side_owners.setdefault((c_n.get("symbol"), s_n), set()).add(n)
    regimes_done: set = set()
    lots_by: dict[tuple, dict[str, float]] = {}       # (символ, сторона) → {сетка: объём лотов}
    for name in eg.GRIDS:
        cfg_path, st_path, journal = eg.grid_files(name)
        cfg = eg.peek_config(name)                   # нет файла (цикл ещё не создал) — шаблон: сетка холостая
        if cfg is None:
            print(f"{name}: конфиг {cfg_path.name} не читается — ПРОБЛЕМА (сетка стоит)")
            problem = True
            continue
        sym = cfg["symbol"]
        st = json.loads(st_path.read_text()) if st_path.exists() else None
        leftovers = bool(st) and any(st.get(s, {}).get(k) for s in ("LONG", "SHORT") for k in LEFTOVER_KEYS)
        led_live = not cfg.get("dry_run") or leftovers
        if not led_live:
            continue
        try:
            own, others = mc.owner_prefixes(tags, name, eg.PREFIX)
        except ValueError as e:
            print(f"{name} {sym}: ПРОБЛЕМА — {e}; сетка стоит (GridHalt)")
            problem = True
            continue
        if int(cfg.get("regime_sma") or 0) > 0 and (sym, int(cfg["regime_sma"])) not in regimes_done:
            regimes_done.add((sym, int(cfg["regime_sma"])))      # 4 сетки BTC с SMA100 — один режим, одна строка
            level, text = regime_line(sym, int(cfg["regime_sma"]), c)
            problem |= level == "bad"
            unread |= level == "check"
            print(f"{name} {sym}: {text}")
        mode = f"enabled={cfg.get('enabled')} dry_run={cfg.get('dry_run')}"
        level, verdict = liveness(st, st_path, time.time())
        if st and st.get("halted"):
            level, verdict = "bad", f"ПРОБЛЕМА: сетка остановлена (halted) — {st.get('halt_reason')}"
        problem |= level == "bad"
        unread |= level == "check"
        print(f"{name} {sym}: ведётся живьём ({mode}) → {verdict}")
        rel = [s for s in (cfg.get("release_sides") or []) if s in eg.DIR and s not in (cfg.get("sides") or [])]
        legit = sorted(set().union(*[side_owners.get((sym, s), set()) for s in rel]) - {name}) if rel else []
        p, u = check_released(name, sym, cfg, st, Path(journal), c, size_of, own, others,
                              legit_prefixes=tuple(eg.PREFIX + tags[n] for n in legit),
                              legit_registry=set().union(*[mc.grid_registry(eg, n) for n in legit]) if legit else set())
        problem |= p
        unread |= u
        for s in ("LONG", "SHORT"):
            q = sum(float(l.get("qty") or 0) for l in ((st or {}).get(s) or {}).get("lots") or [])
            if q > 0:
                lots_by.setdefault((sym, s), {})[name] = q
    for (sym, s), per in sorted(lots_by.items()):
        tot, pos = sum(per.values()), size_of.get((sym, s), 0.0)
        parts = ", ".join(f"{n} {q:g}" for n, q in per.items())
        if pos < tot - 1e-6:
            unread = True
            print(f"{sym} {s}: позиция на бирже {pos:g} МЕНЬШЕ суммы лотов сеток {tot:g} ({parts}) — часть общей позиции "
                  f"закрыта не сетками или учёт отстал; перепроверить через 10–20 с")
        else:
            print(f"{sym} {s}: позиция на бирже {pos:g}, лотов сеток {tot:g} ({parts})"
                  + (f"; сверх лотов {pos - tot:g} — ручное или неучтённое" if pos > tot + 1e-6 else ""))
    print("ИТОГ:","ЕСТЬ ПРОБЛЕМА" if problem else ("НЕ ВСЁ ПРОЧИТАНО — перепроверить" if unread else "ок"))
    sys.exit(1 if problem else (2 if unread else 0))


if __name__ == "__main__":
    main()
