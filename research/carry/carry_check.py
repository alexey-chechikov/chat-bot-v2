"""Идеи №3–4: спот + шорт перпа (фандинг) и спот + шорт срочного фьючерса (базис).

№3: реальный фандинг Binance 05.2024–10.2026 (BTC, ETH, XRP) + OKX за 99 дней.
    Постоянно держать пакет против «держать, только если средний фандинг за 3 дня > 0»
    (решение по прошлым данным, каждое переключение = открыть/закрыть пакет).
    Издержки пакета: спот 0.10% за сторону (прайс OKX, обычный уровень) + перп 0.05% за сторону
    = 0.30% за полный круг. Результат в % нотионала за год и в % занятого капитала
    (спот + 1/3 нотионала маржи под шорт).
№4: текущий базис срочных фьючерсов OKX (публичный API) в % годовых.
"""
import json
import time
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ROUND = 0.0030
CAP = 1 + 1 / 3


def carry(rates: pd.Series, mask: pd.Series | None) -> dict:
    r = rates.copy()
    hold = pd.Series(True, r.index) if mask is None else mask.reindex(r.index).fillna(False)
    got = float(r[hold].sum())
    switches = int((hold.astype(int).diff().abs() > 0).sum()) + (1 if hold.iloc[0] else 0)
    cycles = switches / 2
    cost = cycles * ROUND
    years = (r.index[-1] - r.index[0]).days / 365
    net = got - cost
    return {"на нотионал, %/год": 100 * net / years, "на капитал, %/год": 100 * net / years / CAP,
            "валовый фандинг %/год": 100 * got / years, "кругов": round(cycles, 1),
            "время в позиции": float(hold.mean())}


out = {}
for sym in ("BTCUSDT", "ETHUSDT", "XRPUSDT"):
    f = pd.read_csv(ROOT / "research" / "grid_risk" / "data" / f"funding_{sym}.csv")
    f.index = pd.to_datetime(f.ts_ms, unit="ms", utc=True)
    r = f.rate
    mask = (r.rolling(9).mean().shift(1) > 0)              # 3 дня = 9 начислений, только прошлое
    res = {"всегда": carry(r, None), "фильтр 3 дня > 0": carry(r, mask)}
    by_year = {str(y): round(100 * float(g.sum()) / (len(g) / (3 * 365)), 2) for y, g in r.groupby(r.index.year)}
    res["валовый по годам, %/год"] = by_year
    res["доля положительных"] = round(float((r > 0).mean()), 3)
    out[sym] = res


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return json.load(urllib.request.urlopen(req, timeout=20))["data"]


basis = []
try:
    idx = {x["instId"]: float(x["idxPx"]) for x in get("https://www.okx.com/api/v5/market/index-tickers?quoteCcy=USDT")}
    idx.update({x["instId"]: float(x["idxPx"]) for x in get("https://www.okx.com/api/v5/market/index-tickers?quoteCcy=USD")})
    for uly in ("BTC-USD", "ETH-USD", "BTC-USDT", "ETH-USDT"):
        ins = get(f"https://www.okx.com/api/v5/public/instruments?instType=FUTURES&uly={uly}")
        for x in ins:
            t = get(f"https://www.okx.com/api/v5/market/ticker?instId={x['instId']}")[0]
            px = float(t["last"])
            ip = idx.get(uly)
            days = (int(x["expTime"]) / 1000 - time.time()) / 86400
            if ip and days > 3:
                prem = px / ip - 1
                basis.append({"контракт": x["instId"], "дней": round(days), "премия %": round(100 * prem, 3),
                              "годовых %": round(100 * prem * 365 / days, 2)})
            time.sleep(0.15)
except Exception as exc:                                    # noqa: BLE001
    basis.append({"ошибка": str(exc)})
out["OKX срочные: базис сейчас"] = basis
print(json.dumps(out, ensure_ascii=False, indent=1))
(HERE / "carry.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
