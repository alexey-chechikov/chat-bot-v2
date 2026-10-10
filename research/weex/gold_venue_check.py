"""Золото: совпадают ли цены WEEX XAUUSDT с Binance XAUUSDT (на которых считалась развёртка), какой спред
на WEEX и торгуется ли контракт в выходные. Только публичные данные."""
import json
import statistics
import time
import urllib.request

import numpy as np


def get(url):
    return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "bot7"}),
                                             timeout=30).read())


wx = get("https://api-contract.weex.com/capi/v3/market/klines?symbol=XAUUSDT&interval=1m&limit=1000")
wx = {int(k[0]): (float(k[4]), float(k[5])) for k in wx}
start = min(wx)
bn = get(f"https://fapi.binance.com/fapi/v1/klines?symbol=XAUUSDT&interval=1m&limit=1000&startTime={start}")
bn = {int(k[0]): (float(k[4]), float(k[5])) for k in bn}
common = sorted(set(wx) & set(bn))
d = np.array([(wx[t][0] / bn[t][0] - 1) * 100 for t in common])
rw = np.diff([wx[t][0] for t in common]) / np.array([wx[t][0] for t in common][:-1]) * 100
rb = np.diff([bn[t][0] for t in common]) / np.array([bn[t][0] for t in common][:-1]) * 100
print(f"минут общих: {len(common)} ({time.strftime('%d.%m %H:%M', time.gmtime(common[0] / 1000))} — "
      f"{time.strftime('%d.%m %H:%M', time.gmtime(common[-1] / 1000))} UTC)")
print(f"WEEX − Binance: средняя разница {d.mean():+.3f}%, разброс {d.std():.3f}%, максимум |{np.abs(d).max():.3f}|%")
print(f"корреляция минутных ходов: {np.corrcoef(rw, rb)[0, 1]:.3f}; размах минут WEEX {np.abs(rw).mean():.4f}% "
      f"против Binance {np.abs(rb).mean():.4f}%")
vol_w = [wx[t][1] for t in common]
print(f"объём WEEX за минуту: медиана {statistics.median(vol_w):.3f} oz, минут без сделок "
      f"{sum(1 for v in vol_w if v == 0)} из {len(vol_w)}")
spreads = []
for _ in range(5):
    b = get("https://api-contract.weex.com/capi/v3/market/ticker/bookTicker?symbol=XAUUSDT")
    b = b[0] if isinstance(b, list) else b
    bid, ask = float(b["bidPrice"]), float(b["askPrice"])
    spreads.append((ask - bid) / ((ask + bid) / 2) * 100)
    time.sleep(1)
print(f"спред WEEX сейчас: {min(spreads):.4f}…{max(spreads):.4f}% (шаг сетки 0.75%, цель 0.3%)")
last = max(wx)
print(f"последняя минута WEEX: {time.strftime('%a %d.%m %H:%M', time.gmtime(last / 1000))} UTC, объём {wx[last][1]}")
