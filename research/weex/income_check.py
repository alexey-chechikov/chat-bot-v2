"""Только чтение: начисления фьючерсного счёта WEEX с начала сетки (09.10) — комиссии сделок (fillFee),
возвраты (deposit/подарки/возврат комиссии), фандинг (position_funding). Ответ на вопрос «возвращается ли
комиссия на сделки через API и сколько», плюс фандинг для учёта сетки."""
import json
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from services.weex_api.client import FUTURES, WeexClient  # noqa: E402

c = WeexClient()
c.sync_time()
start = int(datetime(2026, 10, 9, tzinfo=timezone.utc).timestamp() * 1000)
items, body = [], {"limit": 100, "startTime": start, "endTime": int(time.time() * 1000)}
for _ in range(50):
    r = c.post(FUTURES, "/capi/v3/account/income", body) or {}
    items += r.get("items", [])
    nk = r.get("nextKey") or {}
    if not r.get("hasNextPage") or not nk:
        break
    body = {**body, "nextKeyId": nk.get("nextKeyId"), "nextKeyTime": nk.get("nextKeyTime")}
items = list({str(x.get("billId")): x for x in items}.values())
by_type = defaultdict(float)
cnt = defaultdict(int)
fees = 0.0
reasons = defaultdict(float)
funding = defaultdict(float)
for x in items:
    t = x.get("incomeType")
    by_type[t] += float(x.get("income") or 0)
    cnt[t] += 1
    fees += float(x.get("fillFee") or 0)
    if t == "deposit":
        reasons[x.get("transferReason")] += float(x.get("income") or 0)
    if t == "position_funding":
        funding[x.get("symbol")] += float(x.get("income") or 0)
print(f"начислений с 09.10: {len(items)}")
for t, v in sorted(by_type.items(), key=lambda kv: -abs(kv[1])):
    print(f"  {t:<24} {cnt[t]:>4} шт, сумма {v:+.4f}")
print(f"комиссии сделок (fillFee): {fees:.4f}")
for rsn, v in reasons.items():
    print(f"  возвраты deposit [{rsn}]: {v:+.4f}")
dep = sum(reasons.values())
print(f"доля возвращённой комиссии: {dep / fees * 100 if fees else 0:.1f}%")
print("фандинг по символам:", {k: round(v, 4) for k, v in funding.items()} or "нет начислений")
