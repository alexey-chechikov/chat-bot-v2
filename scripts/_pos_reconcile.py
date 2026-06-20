"""Сверка СЕЙЧАС: позиция XBTUSDT на бирже (read API) vs сумма BTC-ботов (трекер).
+ последние исполнения после 15:00 UTC — не идёт ли ещё аномальная продажа."""
import csv
import json
import sys
from pathlib import Path

csv.field_size_limit(10_000_000)
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ginarea_tracker.storage import SNAPSHOTS_HEADERS
from services.bitmex_account.poller import _load_credentials, _signed_get

# позиция на бирже
key, secret = _load_credentials()
exch = None
if key:
    import urllib.parse
    flt = urllib.parse.quote(json.dumps({"symbol": "XBTUSDT"}))
    pos = _signed_get(f"/api/v1/position?filter={flt}", key, secret, timeout=15) or []
    for p in pos:
        if p.get("symbol") == "XBTUSDT":
            exch = p.get("currentQty", 0) / 1e6  # контракты XBTUSDT → BTC (1e6 = 1 BTC)
            print(f"Биржа XBTUSDT: {p.get('currentQty')} контрактов = {exch:+.4f} BTC")

# сумма позиций BTC-ботов из последнего снапшота трекера
path = ROOT / "ginarea_live" / "snapshots.csv"
size = path.stat().st_size
with path.open("rb") as fh:
    fh.seek(max(0, size - 5_000_000)); fh.readline()
    text = fh.read().decode("utf-8", errors="replace")
last = {}
for rec in csv.reader(text.replace("\x00", "").splitlines()):
    if len(rec) != len(SNAPSHOTS_HEADERS):
        continue
    r = dict(zip(SNAPSHOTS_HEADERS, rec))
    nm = r["bot_name"] or ""
    if ("SHORT" in nm or "BTC" in nm or "GPT" in nm) and "LONG-✨" not in nm:
        last[r["bot_id"]] = r  # последний по боту

bots_sum = 0.0
print("\nBTC-боты (последний снапшот):")
for bid, r in last.items():
    try:
        p = float(r["position"] or 0)
    except ValueError:
        p = 0.0
    if p:
        print(f"  {r['bot_name'][:24]:24} {p:+.4f} BTC")
    bots_sum += p
print(f"Сумма ботов: {bots_sum:+.4f} BTC")

if exch is not None:
    diff = exch - bots_sum
    flag = "🔴 РАСХОЖДЕНИЕ" if abs(diff) > 0.02 else "✅ сходится"
    print(f"\n{flag}: биржа {exch:+.4f} − боты {bots_sum:+.4f} = {diff:+.4f} BTC")

# исполнения после 15:00 UTC
print("\nИсполнения XBTUSDT после 15:00 UTC (крупные клипы > 6000 = подозрит.):")
import urllib.parse
flt = urllib.parse.quote(json.dumps({"execType": "Trade"}))
rows = _signed_get(f"/api/v1/execution/tradeHistory?symbol=XBTUSDT&count=100&reverse=true&filter={flt}",
                   key, secret, timeout=15) or []
big = 0
for e in rows:
    t = e.get("transactTime", "")
    if t >= "2026-06-12T15:00" and (e.get("lastQty") or 0) > 6000:
        big += 1
        print(f"  {t[11:19]} {e.get('side')} {e.get('lastQty')} @ {e.get('lastPx')}")
print(f"(крупных клипов после 15:00: {big})")
