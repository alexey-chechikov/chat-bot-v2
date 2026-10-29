"""Только чтение: сколько комиссии возвращается и с каких сделок (оператор 29.10: партнёрский кешбэк 77.6% «вшитый,
автоматом»; по начислениям с 09.10 вернулось 37%). Сопоставляет каждое начисление deposit с ближайшей по времени сделкой
(user_trades: maker/taker, комиссия), по дням и по типу исполнения; ставки комиссии аккаунта.

    .venv/bin/python3 research/weex/cashback_check.py
"""
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
for _ in range(60):
    r = c.post(FUTURES, "/capi/v3/account/income", body) or {}
    items += r.get("items", [])
    nk = r.get("nextKey") or {}
    if not r.get("hasNextPage") or not nk:
        break
    body = {**body, "nextKeyId": nk.get("nextKeyId"), "nextKeyTime": nk.get("nextKeyTime")}
items = list({str(x.get("billId")): x for x in items}.values())
kinds = defaultdict(list)
for x in items:
    kinds[x.get("incomeType")].append(x)
print("поля по типам (первая запись):")
for k, v in kinds.items():
    print(" ", k, {kk: vv for kk, vv in v[0].items() if kk not in ("billId",)})
dep = sorted(kinds.get("deposit", []), key=lambda x: int(x.get("time") or x.get("cTime") or 0))
fills = [x for k in ("position_open_long", "position_close_long", "position_open_short", "position_close_short")
         for x in kinds.get(k, [])]
tkey = lambda x: int(x.get("time") or x.get("cTime") or 0)   # noqa: E731
by_day_fee, by_day_dep = defaultdict(float), defaultdict(float)
for x in fills:
    by_day_fee[datetime.fromtimestamp(tkey(x) / 1000, timezone.utc).strftime("%m-%d")] += float(x.get("fillFee") or 0)
for x in dep:
    by_day_dep[datetime.fromtimestamp(tkey(x) / 1000, timezone.utc).strftime("%m-%d")] += float(x.get("income") or 0)
print("\nдень   комиссия  возврат  доля")
for d in sorted(set(by_day_fee) | set(by_day_dep)):
    f, b = by_day_fee[d], by_day_dep[d]
    print(f"{d}  {f:8.4f}  {b:7.4f}  {b / f:5.0%}" if f else f"{d}  {f:8.4f}  {b:7.4f}")
# задержка: время возврата против ближайшей предшествующей сделки с комиссией
ft = sorted(tkey(x) for x in fills if float(x.get("fillFee") or 0) > 0)
import bisect  # noqa: E402
lags = []
for x in dep:
    t = tkey(x)
    i = bisect.bisect_right(ft, t) - 1
    if i >= 0:
        lags.append((t - ft[i]) / 1000)
lags.sort()
if lags:
    print(f"\nзадержка возврата после ближайшей сделки, с: медиана {lags[len(lags) // 2]:.0f}, 90% {lags[int(len(lags) * .9)]:.0f}, макс {lags[-1]:.0f}")
print("\nставки аккаунта:", json.dumps(c.futures_commission("BTCUSDT"), ensure_ascii=False)[:300])
