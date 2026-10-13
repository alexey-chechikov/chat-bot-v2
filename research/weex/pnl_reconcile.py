"""Сверка прибыли сетки по сделкам биржи (только чтение).

ВСЕ сделки символа с момента запуска сетки (окна по времени, окно с 100 сделками делится пополам —
не только последние 100), разделение на сетку и ручные; по каждой стороне:
деньги по исполнениям + остаток по текущей цене против учёта бота, отдельно ДО и ПОСЛЕ комиссий.
Не сверяет фандинг и полный капитал счёта (там ручные позиции) — это отдельная задача.

    .venv/bin/python3 research/weex/pnl_reconcile.py [BTC|ETH|XAU]     (по умолчанию BTC)

Какие стороны (разбор GPT 13.10 §3 Q3): все, которыми бот КОГДА-ЛИБО владел — из cfg.sides, из журнала и из учёта
(realized/fees/счётчики/остатки), плюс переданные и любая сторона со сделками бота на бирже, а не только текущие
cfg.sides: сторона, убранная из sides и опустевшая, сверяется со своей старой историей. Передача оператору («передано оператору»: qty, mark, bag) — изъятие остатка по цене
передачи: биржа = деньги сделок бота + переданный объём по mark + остаток по текущей цене; бот = закрыто + мешок при
передаче + мешок сейчас. Сторона из release_sides (и не из sides) сверяется по сделкам ДО конца секунды записи
передачи; сделки бота после — ПРОБЛЕМА. Записи передачи нет, а сделки бота на стороне есть — граница неизвестна.

Владелец сделки — research/weex/weex_monitor_common.order_owner: clientOrderId b7g… — сетка; поля нет/null — владелец
не установлен (если номера нет в реестре бота: журнал + учёт). История null/не список — не прочитано.
Код выхода: 0 — совпадает; 1 — расхождение/сделки бота после передачи; 2 — не прочитано/не подтверждено (владелец
части сделок неизвестен, выборка неполна, границы передачи нет) — при этом расхождение денег тоже печатается."""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from services.weex_api.client import WeexClient  # noqa: E402
from services.weex_grid import engine as eg  # noqa: E402
from research.weex import weex_monitor_common as mc  # noqa: E402

LEFTOVER_KEYS = ("entry", "lots", "strays", "pending", "flatten")
ACTIVITY_KEYS = ("realized", "fees", "n_entries", "n_tps", "turnover", "order_fills")


def ever_owned(side: str, cfg: dict, st: dict, journal: list[dict]) -> bool:
    sd = st.get(side) or {}
    return (side in (cfg.get("sides") or []) or any(r.get("side") == side for r in journal)
            or any(sd.get(k) for k in LEFTOVER_KEYS + ACTIVITY_KEYS))


def main() -> None:
    args = [a.upper() for a in sys.argv[1:]]
    if args and args[0] not in eg.GRIDS:
        print(f"сетка «{sys.argv[1]}» неизвестна — есть {', '.join(eg.GRIDS)}")
        sys.exit(2)
    name = args[0] if args else "BTC"
    cfg_path, state_path, journal_path = eg.grid_files(name)
    cfg = json.loads(cfg_path.read_text())
    sym = cfg["symbol"]
    if not state_path.exists() or not journal_path.exists():
        print(f"{name}: живого учёта/журнала нет (сетка холостая) — сверять нечего")
        sys.exit(2)
    journal, n_bad = mc.read_journal(journal_path)
    if n_bad:
        print(f"{name}: в журнале битых строк {n_bad} — сверка недостоверна")
        sys.exit(2)
    if not journal:
        print(f"{name}: живой журнал пуст — сверять нечего")
        sys.exit(2)
    st = json.loads(state_path.read_text())
    sides_cfg = cfg.get("sides") or []
    released = [s for s in cfg.get("release_sides") or [] if s in eg.DIR and s not in sides_cfg]

    c = WeexClient()
    c.sync_time()
    bid, ask = c.book(sym)
    mid = (bid + ask) / 2
    first = journal[0].get("ts")
    start = mc.epoch_ms(first)
    if start is None:
        print(f"{name}: у первой записи журнала нет времени — сверка недостоверна")
        sys.exit(2)
    try:
        trades, incomplete = mc.fetch_trades(c, sym, start - 3_600_000, extra=("commission",))
    except mc.ReadError as e:
        print(f"{name} {sym}: история сделок НЕ ПРОЧИТАНА — {e}")
        print("ИТОГ: НЕ ПРОЧИТАНО — сверка не выполнена")
        sys.exit(2)
    registry = mc.own_order_ids(st, journal)
    cache: dict = {}
    owner = {str(t["orderId"]): mc.order_owner(c, t["orderId"], eg.PREFIX, registry, cache) for t in trades}
    unread = [oid for oid, w in owner.items() if w is None]
    grid = [t for t in trades if owner[str(t["orderId"])] == mc.BOT]
    manual = [t for t in trades if owner[str(t["orderId"])] == mc.MANUAL]
    print(f"{name} {sym}: цена {mid:,.4f}; сделок с {str(first)[:16]}: {len(trades)} (сетки {len(grid)}, ручных "
          f"{len(manual)}" + (f", владелец не установлен у {len(unread)} ордеров — нет clientOrderId/детали"
                              if unread else "") + ")")
    for t in manual:
        print("  ручная:", t["side"], t["positionSide"], t["price"], t["qty"])
    # стороны бота: когда-либо владел по журналу/учёту/sides, переданные, и любая сторона со сделками бота на бирже
    # (журнал и учёт сторону не знают — записи потеряны/учёт сброшен; сделки бота всё равно должны сойтись с учётом)
    owned = [s for s in ("LONG", "SHORT") if ever_owned(s, cfg, st, journal) or s in released
             or any(t["positionSide"] == s for t in grid)]
    if not owned:
        print("сторон бота нет — сверять нечего")
        sys.exit(2)

    money_ok, hard, unknown = True, False, bool(unread or incomplete)
    for side in owned:
        d = eg.DIR[side]
        recs = [r for r in journal if r.get("side") == side and r.get("kind") == mc.HANDOVER]
        is_released = side in released
        all_ts = [t for t in grid if t["positionSide"] == side]
        bound = None
        if is_released and recs:
            t0 = mc.epoch_ms(recs[-1].get("ts"))
            bound = None if t0 is None else t0 + 1000          # конец секунды записи передачи
            if t0 is None:
                print(f"{side}: у записи передачи нет времени — граница неизвестна")
                unknown = True
        ts = [t for t in all_ts if bound is None or int(t["time"]) < bound]
        after = [t for t in all_ts if bound is not None and int(t["time"]) >= bound]
        try:
            q_h = sum(float(r["qty"]) for r in recs)
            transfer = sum(d * float(r["qty"]) * float(r["mark"]) for r in recs)
            bag_h = sum(float(r["bag"]) for r in recs)
        except (KeyError, TypeError, ValueError):
            print(f"{side}: запись передачи без qty/mark/bag — деньги до границы не сверить")
            unknown = True
            q_h = transfer = bag_h = 0.0
        cash = sum((1 if t["side"] == "SELL" else -1) * float(t["price"]) * float(t["qty"]) for t in ts)
        net = sum((1 if t["side"] == "BUY" else -1) * float(t["qty"]) for t in ts)
        fee = sum(float(t["commission"]) for t in ts)
        exch = cash + (net - d * q_h) * mid + transfer
        s = st.get(side) or eg.new_side_state()
        lots = s.get("lots") or []
        bag = sum(d * float(l["qty"]) * (mid - l["entry"]) for l in lots)
        held = sum(float(l["qty"]) for l in lots)
        realized, fees_bot = float(s.get("realized") or 0), float(s.get("fees") or 0)
        bot = realized + bag_h + bag
        diff, fdiff, qdiff = bot - exch, fees_bot - fee, held - (d * net - q_h)
        side_ok = abs(diff) < 0.01 and abs(fdiff) < 0.01 and abs(qdiff) < 1e-9
        money_ok &= side_ok
        scope = " до передачи" if bound is not None else ""
        tag = ("" if side in sides_cfg else (" (передана оператору)" if is_released else " (не в sides — история)"))
        print(f"{side}{tag}: биржа{scope} — сделок {len(ts)}, остаток {abs(d * net - q_h):.4f}"
              + (f", передано {q_h:g} по {transfer / (d * q_h):,.4f}" if q_h else "")
              + f", до комиссий ${exch:+.4f}, комиссии ${fee:.4f}, после ${exch - fee:+.4f}")
        print(f"{side}: бот   — остаток {held:.4f}, закрыто ${realized:+.4f}"
              + (f" + мешок при передаче ${bag_h:+.4f}" if recs else "")
              + f" + мешок ${bag:+.4f} = ${bot:+.4f}, комиссии ${fees_bot:.4f}, после ${bot - fees_bot:+.4f}")
        print(f"{side}: расхождение — деньги ${diff:+.4f}, комиссии ${fdiff:+.4f}, объём {qdiff:+.4f}")
        if is_released:
            if not recs:
                if all_ts:
                    print(f"{side}: в release_sides, записи «передано оператору» нет — граница передачи неизвестна; "
                          f"сделок бота на стороне {len(all_ts)} → результат после передачи неизвестен")
                    unknown = True
                else:
                    print(f"{side}: в release_sides, записи «передано оператору» нет, сделок бота нет — ок")
            else:
                bad = bool(after) or len(recs) > 1
                hard |= bad
                print(f"{side}: передано оператору {str(recs[-1].get('ts'))[:16]} (записей {len(recs)}); сделок бота "
                      f"на стороне после передачи {len(after)} → {'ПРОБЛЕМА' if bad else 'ок'}")
    if incomplete:
        print(f"ВЫБОРКА НЕПОЛНА: {len(incomplete)} секундных окон со 100 сделками — сверка недостоверна")
    if hard or (not money_ok and not unknown):
        print("ИТОГ: ЕСТЬ РАСХОЖДЕНИЕ" + ("" if money_ok else " (деньги/комиссии/объём)")
              + (" и сделки бота после передачи" if hard else ""))
        sys.exit(1)
    if unknown:
        print("ИТОГ: НЕ ВСЁ ПРОЧИТАНО — сверка не подтверждена" + ("" if money_ok else "; расхождение денег есть, "
                                                                     "но владелец части сделок/граница неизвестны"))
        sys.exit(2)
    print(f"ИТОГ: совпадает по {'+'.join(owned)} (деньги и комиссии ±$0.01, объём точно)")
    sys.exit(0)


if __name__ == "__main__":
    main()
