"""Риск-проверка свежезапущенных альт-ботов: SL/TP, size, mult, охват, позиция.

Берёт активных ботов текущего цикла трекера (не managed) + их params,
сверяет с риск-рамкой alt-grid (SL=−175 обязателен, TP=+175, mult≤1.4,
охват ~12%). Плюс XRP funding из deriv_live (памп-предиктор AUC 0.695).
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.morning_brief import tracker_reader as tr
from services.morning_brief.card import _bag, _load_managed

snap = tr.read_snapshots()
params = tr.read_params()
managed = {m["bot_id"] for m in _load_managed()}

print(f"трекер: stale {snap['stale_min']:.1f} мин\n")
for bid, slot in sorted(snap["bots"].items()):
    latest = slot["latest"]
    if not slot.get("fresh") or bid in managed or latest["status"] != tr.STATUS_ACTIVE:
        continue
    name = (latest.get("bot_name") or bid).strip()
    print(f"── {name}  (id {bid})")
    print(f"   профит {latest['profit']} · мешок {_bag(latest)} · поз {latest['position']}"
          f" · avg {latest['average_price']} · ликв {latest['liquidation_price']}"
          f" · balance {latest['balance']}")
    p = params.get(bid)
    if not p:
        print("   ⚠ params ещё не записаны трекером")
        continue
    raw = {}
    try:
        raw = json.loads(p.get("raw_params_json") or "{}")
    except json.JSONDecodeError:
        pass
    q = raw.get("q") or {}
    border = raw.get("border") or {}
    slp = raw.get("slp") or {}
    print(f"   side={p.get('side')} step={p.get('grid_step')} maxOp={p.get('max_opened_orders')}"
          f" target={p.get('target')} qr(mult)={q.get('qr')} minQ={q.get('minQ')} maxQ={q.get('maxQ')}")
    print(f"   border={border.get('bottom') or border.get('from')}..{border.get('top') or border.get('to')}"
          f" off(so)={raw.get('so')} ioo={raw.get('ioo')}")
    ttp = raw.get('ttp')
    lsl = raw.get('lsl')
    slp_tp = slp.get('tp')
    print(f"   TP(ttp)={ttp} ttpinc={raw.get('ttpinc')} · SL: slp.tp={slp_tp} lsl={lsl} slt={raw.get('slt')}")
    flags = []
    if not slp_tp and not lsl:
        flags.append("🚨 SL НЕ ВИДЕН в params (slp.tp/lsl пусто) — проверь TP/SL ±$175 руками!")
    if q.get("qr") and float(q["qr"]) > 1.4:
        flags.append(f"⚠ mult {q['qr']} > 1.4 (ETH-blowup был при 1.9)")
    if ttp and abs(float(ttp)) > 200:
        flags.append(f"⚠ TP {ttp} ≠ +175 из рамки")
    for f in flags:
        print(f"   {f}")
    print()

# XRP funding — памп-предиктор
try:
    deriv = json.loads((ROOT / "state" / "deriv_live.json").read_text(encoding="utf-8"))
    x = deriv.get("XRPUSDT") or {}
    print(f"XRP deriv: funding_8h={x.get('funding_rate_8h')} LS={x.get('global_ls_ratio')}"
          f" OI_1h%={x.get('oi_change_1h_pct')} taker={x.get('taker_buy_sell_ratio')}")
except Exception as e:
    print(f"deriv_live недоступен: {e}")
