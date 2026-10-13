"""Только чтение: свои ордера на бирже против живого учёта сетки — в ОБЕ стороны.

биржа → учёт: свои (b7g) ордера, о которых учёт не знает (сироты; новый код их снимет/усыновит). «В учёте» — тот же
набор, что у Grid._orphans: вход, тейки, снимаемые strays, рыночное закрытие, неясная постановка по cid.
учёт → биржа: лоты без тейка на бирже (тейка нет в учёте или его id нет среди открытых) — позиция без выхода.
Плюс условные (algo) ордера с префиксом b7 — у сеток их быть не должно.
Ревью скилов 12.10: проверка была только в одну сторону, «своих N, в учёте N» вводило в заблуждение.
Сразу после постановки/исполнения возможна гонка с проходом сетки — при находке перепроверить через 10–20 с.

    .venv/bin/python3 research/weex/orphan_check.py          (код выхода 1 — есть сироты или лоты без тейка)
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from services.weex_api.client import WeexClient  # noqa: E402
from services.weex_grid import engine as eg  # noqa: E402

c = WeexClient()
c.sync_time()
bad = False
for name in eg.GRIDS:
    cfg_path, st_path, _ = eg.grid_files(name)
    sym = json.loads(cfg_path.read_text()).get("symbol", "BTCUSDT")
    if not st_path.exists():
        # учёта нет — любой свой ордер символа на бирже = сирота (раунд 2 ревью: раньше биржу не спрашивали)
        stray = [o for o in c.open_orders(sym) if str(o.get("clientOrderId", "")).startswith(eg.PREFIX)]
        stray_algo = [a for a in (c.open_algo_orders(sym) or []) if str(a.get("clientAlgoId", "")).startswith(eg.PREFIX)]
        bad |= bool(stray or stray_algo)
        print(f"{name} {sym}: живого учёта нет; своих ордеров на бирже {len(stray)}, algo {len(stray_algo)}"
              + (" — СИРОТЫ" if stray or stray_algo else ""))
        continue
    st = json.loads(st_path.read_text())
    known, pend = set(), set()
    lots_total, no_tp = 0, []
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
    mine = [o for o in c.open_orders(sym) if str(o.get("clientOrderId", "")).startswith(eg.PREFIX)]
    open_ids = {str(o["orderId"]) for o in mine}
    for s in ("LONG", "SHORT"):
        for l in st.get(s, {}).get("lots", []):
            lots_total += 1
            if not l.get("tp_order") or str(l["tp_order"]["id"]) not in open_ids:
                no_tp.append((s, l["entry"], l["qty"], (l.get("tp_order") or {}).get("id")))
    orphans = [o for o in mine if str(o["orderId"]) not in known and o.get("clientOrderId") not in pend]
    matched = sum(1 for o in mine if str(o["orderId"]) in known)
    by_cid = sum(1 for o in mine if str(o["orderId"]) not in known and o.get("clientOrderId") in pend)
    # algo сетки (b7g) быть не должно; стопы тренда (b7t) — его, тут только печатаются (тренд сверяется отдельно)
    algo_all = [a for a in (c.open_algo_orders(sym) or []) if str(a.get("clientAlgoId", "")).startswith("b7")]
    algo = [a for a in algo_all if str(a.get("clientAlgoId", "")).startswith(eg.PREFIX)]
    trend_algo = [a for a in algo_all if a not in algo]
    if trend_algo:
        print(f"   стопов тренда b7t на {sym}: {len(trend_algo)} (не сверяются здесь)")
    bad |= bool(orphans or no_tp or algo)
    print(f"{name} {sym}: своих ордеров {len(mine)} — сопоставлено с учётом {matched}, по cid неясной постановки "
          f"{by_cid}, сирот {len(orphans)}; лотов {lots_total}, без тейка на бирже {len(no_tp)}; algo b7 {len(algo)}")
    for o in orphans:
        print("   сирота:", o["positionSide"], o["side"], o["price"], o["origQty"], o.get("clientOrderId"))
    for s, entry, q, tid in no_tp:
        print(f"   лот без тейка: {s} вход {entry} объём {q} тейк в учёте {tid or 'нет'}")
    for a in algo:
        print("   algo:", a.get("positionSide"), a.get("side"), a.get("triggerPrice"), a.get("quantity"), a.get("clientAlgoId"))
    for o in mine:
        print("    ", o["positionSide"], o["side"], o["price"], o["origQty"], "исп", o.get("executedQty"),
              "reduce" if o.get("reduceOnly") else "вход")
print("ИТОГ:", "есть находки — перепроверить через 10–20 с" if bad else "сирот 0, лотов без тейка 0")
sys.exit(1 if bad else 0)
