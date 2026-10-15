"""Только чтение: свои ордера на бирже против живого учёта сетки — в ОБЕ стороны. Ордера не ставит и не снимает.

биржа → учёт: свои (b7g) ордера, о которых учёт не знает (сироты; новый код их снимет/усыновит). «В учёте» — тот же
набор, что у Grid._orphans: вход, тейки, снимаемые strays, рыночное закрытие, неясная постановка по cid.
учёт → биржа: тейк каждого лота. Есть в списке открытых — сверяются направление, reduceOnly и покрываемый остаток.
Нет в списке (разбор GPT 13.10 §3 Q2: отсутствие в списке — повод спросить, а не доказательство) — деталь ордера с
проверкой orderId, статуса, направления, цены и reduceOnly, затем класс:
  исполнен — ждёт учёта (остатка нет)            — не находка;
  жив (в т.ч. частично), пропущен списком        — не находка, если его остаток покрывает остаток лота;
  отменён/отклонён/истёк — остаток без TP         — НАХОДКА (код 1);
  неизвестен (пустой/чужой ответ, нет статуса)    — НАХОДКА (код 2: не «ок», но и не доказанная дыра).
Тейка нет в учёте — лот без тейка (код 1). Плюс условные (algo) ордера с префиксом b7g — у сеток их быть не должно.
Ревью скилов 12.10: проверка была только в одну сторону, «своих N, в учёте N» вводило в заблуждение.
Сразу после постановки/исполнения возможна гонка с проходом сетки — при находке перепроверить через 10–20 с.
Несколько сеток на символе (15.10: BTC и B34/B49/B89): «свои» сетки — только b7g + её знак (engine.cid_tag), ордера
соседней сетки — не её сироты. Ордер b7g со знаком НИ ОДНОЙ сетки — сирота без хозяина (код 1), строкой символа.

    .venv/bin/python3 research/weex/orphan_check.py   (код 1 — сироты/остаток без TP/algo, 2 — тейк неизвестен)
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from services.weex_api.client import WeexClient  # noqa: E402
from services.weex_grid import engine as eg  # noqa: E402

BOOKED, LIVE, UNPROTECTED, UNKNOWN = "booked", "live", "unprotected", "unknown"


def _num(x) -> float:
    return float(x or 0)


def classify_tp(info, lot: dict, side: str, tiny: float, tick: float, listed: bool) -> tuple[str, str]:
    """Класс тейка лота по ответу биржи (элемент списка открытых или деталь order_info) и пояснение."""
    o = lot["tp_order"]
    oid = str(o["id"])
    if not isinstance(info, dict) or str(info.get("orderId")) != oid:
        return UNKNOWN, "ответ без совпавшего orderId"
    status = str(info.get("status") or "")
    if listed and not status:
        status = "NEW"                                   # в списке открытых — значит, ещё может исполниться
    if status not in eg.LIVE and status not in eg.TERMINAL:
        return UNKNOWN, f"статус «{status or 'нет'}»"
    ps, sd = info.get("positionSide"), info.get("side")
    if (ps and ps != side) or (sd and sd != eg.CLOSE_SIDE[side]):
        return UNKNOWN, f"не то направление: {ps} {sd}"
    if info.get("reduceOnly") is not None and str(info.get("reduceOnly")).lower() in ("false", "0"):
        return UNKNOWN, "не reduceOnly"
    try:
        exq = _num(info.get("executedQty"))
        orig = _num(info.get("origQty") or o.get("qty"))
        price = _num(info.get("price"))
        lot_qty = _num(lot["qty"])
    except (TypeError, ValueError):
        return UNKNOWN, "битые объёмы/цена"
    want_px = _num(o.get("price") or lot.get("tp"))
    if price > 0 and want_px > 0 and abs(price - want_px) > tick + 1e-9:
        return UNKNOWN, f"цена {price:g} вместо {want_px:g}"
    rest = lot_qty - max(exq - _num(o.get("filled")), 0.0)      # остаток лота после учёта нового исполнения
    part = f"частично исполнен {exq:g} из {orig:g}, " if tiny < exq < orig - tiny else ""
    if status in eg.LIVE:
        cover = orig - exq
        if rest > cover + tiny:
            return UNPROTECTED, f"жив ({status}), но закрывает {cover:g} из остатка {rest:g} — {rest - cover:g} без TP"
        if listed:
            return LIVE, f"{part}в списке открытых"
        return LIVE, f"{part}жив ({status}), но пропущен списком открытых — защищает {cover:g}"
    if rest <= tiny:
        return BOOKED, f"исполнен ({status}, {exq:g}) — ждёт учёта"
    what = "отменён/отклонён" if status != "FILLED" else "завершён"
    return UNPROTECTED, f"{what} ({status}{', ' + part.rstrip(', ') if part else ''}) — остаток {rest:g} без TP"


def tp_detail(c, lot: dict, side: str, tiny: float, tick: float) -> tuple[str, str]:
    try:
        info = c.order_info(lot["tp_order"]["id"])
    except Exception as e:                                       # noqa: BLE001
        return UNKNOWN, f"деталь не прочитана ({e})"
    return classify_tp(info, lot, side, tiny, tick, listed=False)


def main() -> None:
    c = WeexClient()
    c.sync_time()
    bad = unknown = False
    tags = eg.grid_tags()
    opens_cache: dict[str, list] = {}
    algos_cache: dict[str, list] = {}

    def opens(sym: str) -> list:                       # один запрос на символ, а не на каждую из 4 сеток BTC
        if sym not in opens_cache:
            opens_cache[sym] = list(c.open_orders(sym))
        return opens_cache[sym]

    def algos(sym: str) -> list:
        if sym not in algos_cache:
            algos_cache[sym] = list(c.open_algo_orders(sym) or [])
        return algos_cache[sym]

    for name in eg.GRIDS:
        cfg_path, st_path, _ = eg.grid_files(name)
        cfg = eg.peek_config(name)                     # как load_config, но файл не создаётся
        if cfg is None:
            print(f"{name}: конфиг {cfg_path.name} не читается — свои ордера не определить")
            unknown = True
            continue
        sym = cfg.get("symbol", "BTCUSDT")
        tiny = float(cfg.get("qty_step") or 0.0001) / 2
        tick = float(cfg.get("price_tick") or 0.0)
        if not tags.get(name):
            print(f"{name} {sym}: знак ордеров сетки не установлен (cid_tag негоден) — свои ордера не определить")
            unknown = True
            continue
        clash = sorted(n for n, t in tags.items() if n != name and t and t.upper() == tags[name].upper())
        if clash:                                      # как engine.check_tag: обе сетки стоят (GridHalt)
            print(f"{name} {sym}: знак ордеров «{tags[name]}» совпадает со знаком сетки {', '.join(clash)} — сетки "
                  f"стоят, своих ордеров не различить")
            bad = True
            continue
        own = eg.PREFIX + tags[name]
        if not st_path.exists():
            # учёта нет — любой свой ордер символа на бирже = сирота (раунд 2 ревью: раньше биржу не спрашивали)
            stray = [o for o in opens(sym) if str(o.get("clientOrderId", "")).startswith(own)]
            stray_algo = [a for a in algos(sym) if str(a.get("clientAlgoId", "")).startswith(own)]
            bad |= bool(stray or stray_algo)
            print(f"{name} {sym}: живого учёта нет; своих ордеров на бирже {len(stray)}, algo {len(stray_algo)}"
                  + (" — СИРОТЫ" if stray or stray_algo else ""))
            continue
        st = json.loads(st_path.read_text())
        known, pend = set(), set()
        for s in ("LONG", "SHORT"):
            side = st.get(s, {})
            if side.get("entry"):
                known.add(str(side["entry"]["id"]))
            known.update(str(l["tp_order"]["id"]) for l in side.get("lots", []) if l.get("tp_order"))
            known.update(str(x["id"]) for x in side.get("strays", []))
            if side.get("pending"):
                pend.add(side["pending"]["cid"])
            fl = side.get("flatten")
            if fl:
                pend.add(fl["cid"])
                if fl.get("id"):
                    known.add(str(fl["id"]))
        mine = [o for o in opens(sym) if str(o.get("clientOrderId", "")).startswith(own)]
        open_by_id = {str(o["orderId"]): o for o in mine}
        lots_total = 0
        no_tp, unk, notes = [], [], []
        for s in ("LONG", "SHORT"):
            for l in st.get(s, {}).get("lots", []):
                lots_total += 1
                row = (s, l["entry"], l["qty"], (l.get("tp_order") or {}).get("id"))
                if not l.get("tp_order"):
                    no_tp.append((*row, "тейка нет в учёте"))
                    continue
                listed = open_by_id.get(str(l["tp_order"]["id"]))
                if listed is not None:
                    kind, text = classify_tp(listed, l, s, tiny, tick, listed=True)
                else:
                    kind, text = tp_detail(c, l, s, tiny, tick)
                if kind == UNPROTECTED:
                    no_tp.append((*row, text))
                elif kind == UNKNOWN:
                    unk.append((*row, text))
                elif listed is None:
                    notes.append((*row, text))
        orphans = [o for o in mine if str(o["orderId"]) not in known and o.get("clientOrderId") not in pend]
        matched = sum(1 for o in mine if str(o["orderId"]) in known)
        by_cid = sum(1 for o in mine if str(o["orderId"]) not in known and o.get("clientOrderId") in pend)
        # algo сетки (b7g) быть не должно; стопы тренда (b7t) — его, тут только печатаются (тренд сверяется отдельно)
        algo_all = [a for a in algos(sym) if str(a.get("clientAlgoId", "")).startswith("b7")]
        algo = [a for a in algo_all if str(a.get("clientAlgoId", "")).startswith(own)]
        trend_algo = [a for a in algo_all if not str(a.get("clientAlgoId", "")).startswith(eg.PREFIX)]
        if trend_algo:
            print(f"   стопов тренда b7t на {sym}: {len(trend_algo)} (не сверяются здесь)")
        bad |= bool(orphans or no_tp or algo)
        unknown |= bool(unk)
        print(f"{name} {sym}: своих ордеров {len(mine)} — сопоставлено с учётом {matched}, по cid неясной постановки "
              f"{by_cid}, сирот {len(orphans)}; лотов {lots_total}, без тейка на бирже {len(no_tp)}, тейк неизвестен "
              f"{len(unk)}, тейк вне списка (исполнен/жив) {len(notes)}; algo b7 {len(algo)}")
        for o in orphans:
            print("   сирота:", o["positionSide"], o["side"], o["price"], o["origQty"], o.get("clientOrderId"))
        for s, entry, q, tid, why in no_tp:
            print(f"   лот без тейка: {s} вход {entry} объём {q} тейк в учёте {tid or 'нет'} — {why}")
        for s, entry, q, tid, why in unk:
            print(f"   тейк неизвестен: {s} вход {entry} объём {q} тейк {tid} — {why}")
        for s, entry, q, tid, why in notes:
            print(f"   тейк вне списка: {s} вход {entry} объём {q} тейк {tid} — {why}")
        for a in algo:
            print("   algo:", a.get("positionSide"), a.get("side"), a.get("triggerPrice"), a.get("quantity"),
                  a.get("clientAlgoId"))
        for o in mine:
            print("    ", o["positionSide"], o["side"], o["price"], o["origQty"], "исп", o.get("executedQty"),
                  "reduce" if o.get("reduceOnly") else "вход")
    # ордера бота (b7g) со знаком ни одной сетки — их не ведёт никто (сетку убрали из GRIDS, сменили cid_tag)
    known_prefixes = tuple(eg.PREFIX + t for t in tags.values() if t)
    for sym in opens_cache:
        nobody = [o for o in opens_cache[sym] if str(o.get("clientOrderId", "")).startswith(eg.PREFIX)
                  and not str(o.get("clientOrderId", "")).startswith(known_prefixes)]
        if nobody:
            if all(tags.values()):
                bad = True
                print(f"{sym}: ордеров бота без сетки (знак b7g ни одной сетки) {len(nobody)} — СИРОТЫ БЕЗ ХОЗЯИНА")
            else:                                        # знак какой-то сетки не прочитан — хозяин мог быть ею
                unknown = True
                print(f"{sym}: ордеров бота с неизвестным знаком {len(nobody)} — знак одной из сеток не прочитан")
            for o in nobody:
                print("   без сетки:", o.get("positionSide"), o.get("side"), o.get("price"), o.get("origQty"),
                      o.get("clientOrderId"))
    if bad:
        print("ИТОГ: есть находки — перепроверить через 10–20 с")
    elif unknown:
        print("ИТОГ: неясно (тейк неизвестен или знак сетки не прочитан) — не «ок», перепроверить через 10–20 с")
    else:
        print("ИТОГ: сирот 0, лотов без тейка 0")
    sys.exit(1 if bad else (2 if unknown else 0))


if __name__ == "__main__":
    main()
