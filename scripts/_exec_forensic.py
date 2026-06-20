"""Форензика: (1) таймлайн XBT-позиций из margin_automated.jsonl за сегодня,
(2) read-only история исполнений BitMEX (XBTUSDT) 13:30–16:30 UTC с clOrdID —
GinArea-ордера несут метку, ручные из UI — пустую."""
import json
import sys
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.bitmex_account.poller import _load_credentials, _signed_get

print("=== Позиции из margin_automated.jsonl (сегодня, смены) ===")
mp = ROOT / "state" / "margin_automated.jsonl"
prev = None
if mp.exists():
    for line in mp.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts = r.get("ts_utc") or r.get("ts") or ""
        if not ts.startswith("2026-06-12"):
            continue
        pos = {p.get("symbol"): p.get("currentQty") for p in (r.get("positions") or [])}
        if pos != prev:
            print(f"{ts}  {pos}")
            prev = pos

key, secret = _load_credentials()
if not key:
    print("\nнет ключей — exec history недоступна")
    raise SystemExit(0)

print("\n=== Исполнения XBTUSDT 13:30–16:30 UTC (биржа, read-only) ===")
flt = urllib.parse.quote(json.dumps({"execType": "Trade"}))
path = (f"/api/v1/execution/tradeHistory?symbol=XBTUSDT&count=200&reverse=true&filter={flt}")
rows = _signed_get(path, key, secret, timeout=15) or []
n = 0
agg = {}
for e in rows[::-1]:
    t = e.get("transactTime", "")
    if not ("2026-06-12T13:30" <= t <= "2026-06-12T16:30"):
        continue
    n += 1
    clid = e.get("clOrdID") or "(пусто=вручную/UI)"
    tag = clid[:18]
    qty = e.get("lastQty")
    side = e.get("side")
    print(f"{t[11:19]} {side:4} qty={qty:>8} px={e.get('lastPx')} ordType={e.get('ordType','')[:8]} clOrdID={tag}")
    sgn = -1 if side == "Sell" else 1
    agg[tag[:10]] = agg.get(tag[:10], 0) + sgn * (qty or 0)
print(f"(исполнений в окне: {n})")
print("\nСумма по меткам clOrdID (контракты, − = продажи):")
for k, v in agg.items():
    print(f"  {k:14} {v:+}")
