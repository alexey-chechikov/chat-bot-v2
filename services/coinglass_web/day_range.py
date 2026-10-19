"""Прогноз РАЗМАХА на сутки (не направления) для утренней сводки: коридор цены от 08:00 Варшавы до 08:00 завтра и шанс
коснуться уровней (магнитные зоны CoinGlass) — эмпирически по 730 утрам 08:00 в единицах ATR14 часовых свечей.

Замер 19.10.2026 на BTC (подбор 18.10.2024–17.10.2025, проверка 18.10.2025–17.10.2026, 08:00 Варшавы):
шанс коснуться — обещано 11/29/49/70/85% → сбылось 12/28/48/72/87%; Brier 0.160 против 0.217 у «средней частоты»;
коридор 90%/90% целиком удержан в 76% дней проверки. Прогноз направления не даёт — вверх и вниз почти симметричны
(прогноз направления опровергнут многократно — CLAUDE.md «Где не искать»).

Каждое утро: вчерашний прогноз против факта (полные 1440 минут Binance) и накопленная сверка «обещано → сбылось».
Файлы: state/coinglass/day_range_table.json (таблица, строится один раз из frozen), day_range_log.jsonl (прогнозы и
проверки).
"""
from __future__ import annotations

import hashlib
import json
import urllib.request
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np

from services.coinglass_web.collector import DIR, ROOT

WARSAW = ZoneInfo("Europe/Warsaw")
SYMS = ("BTCUSDT", "ETHUSDT")
TABLE = DIR / "day_range_table.json"
LOG = DIR / "day_range_log.jsonl"
Q = 0.90                                  # квантиль каждой стороны коридора
MIN, HOUR = 60_000, 3_600_000
HOUR_LOCAL = 8


def _get(url: str):
    return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "bot7"}),
                                             timeout=20).read())


def klines(sym: str, interval: str, start_ms: int, end_ms: int) -> list:
    """Binance USDⓈ-M свечи [start, end) по openTime."""
    out, t, step = [], start_ms, {"1m": MIN, "1h": HOUR}[interval]
    while t < end_ms:
        rows = _get(f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}&interval={interval}&limit=1500"
                    f"&startTime={t}&endTime={end_ms - 1}")
        if not rows:
            break
        out += [r for r in rows if int(r[0]) < end_ms]
        t = int(rows[-1][0]) + step
    return out


def atr14(h: list, lo: list, c: list) -> float:
    """Простое среднее 14 TR по 15 свечам (первая — только для previous close)."""
    tr = [max(h[i] - lo[i], abs(h[i] - c[i - 1]), abs(lo[i] - c[i - 1])) for i in range(1, 15)]
    return sum(tr) / 14


def anchor_ms(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, HOUR_LOCAL, tzinfo=WARSAW).timestamp() * 1000)


# ---------------------------------------------------------------- таблица (один раз из замороженных минуток)
def _moves(ts, op, hi, lo, cl, a_ms: int):
    """(up, dn, atr, p0) для окна 1440 минут от a_ms; None — неполное покрытие."""
    i = int(np.searchsorted(ts, a_ms))
    if i + 1440 > len(ts) or ts[i] != a_ms or ts[i + 1439] != a_ms + 1439 * MIN:
        return None
    j = int(np.searchsorted(ts, a_ms - 15 * HOUR))
    if ts[j] != a_ms - 15 * HOUR or i - j != 900:
        return None
    hs = [float(hi[j + k * 60:j + k * 60 + 60].max()) for k in range(15)]
    ls = [float(lo[j + k * 60:j + k * 60 + 60].min()) for k in range(15)]
    cs = [float(cl[j + k * 60 + 59]) for k in range(15)]
    atr, p0 = atr14(hs, ls, cs), float(op[i])
    return (float(hi[i:i + 1440].max()) - p0) / atr, (p0 - float(lo[i:i + 1440].min())) / atr, atr, p0


def build_table(syms=SYMS, n_days: int = 730) -> dict:
    import pandas as pd
    out = {}
    for sym in syms:
        src = ROOT / "backtests" / "frozen" / f"{sym}_UM_1m.csv"
        d = pd.read_csv(src, usecols=["ts", "open", "high", "low", "close"]).drop_duplicates("ts").sort_values("ts")
        ts = d.ts.to_numpy(dtype=np.int64)
        arrs = [d[c].to_numpy(dtype=float) for c in ("open", "high", "low", "close")]
        last = datetime.fromtimestamp(ts[-1] / 1000, timezone.utc).astimezone(WARSAW).date() - timedelta(days=2)
        days, up, dn = [], [], []
        day = last
        while len(days) < n_days and day > last - timedelta(days=n_days + 60):
            m = _moves(ts, *arrs, anchor_ms(day))
            if m:
                days.append(day.isoformat())
                up.append(round(m[0], 4))
                dn.append(round(m[1], 4))
            day -= timedelta(days=1)
        days, up, dn = days[::-1], up[::-1], dn[::-1]
        u, w = np.array(up), np.array(dn)
        half = len(days) // 2                                   # вне выборки: подбор на первой половине
        pr, ac = [], []
        for i in range(half, len(days)):
            for arr, real in ((u[:half], u[i]), (w[:half], w[i])):
                for dd in (0.5, 1, 2, 3, 4, 6, 8):
                    pr.append(float(np.mean(arr >= dd)))
                    ac.append(float(real >= dd))
        pr, ac = np.array(pr), np.array(ac)
        bins = []
        for lo_, hi_ in ((0, .2), (.2, .4), (.4, .6), (.6, .8), (.8, 1.01)):
            m = (pr >= lo_) & (pr < hi_)
            if m.sum():
                bins.append([round(float(pr[m].mean()), 3), round(float(ac[m].mean()), 3), int(m.sum())])
        qu, qd = np.quantile(u[:half], Q), np.quantile(w[:half], Q)
        out[sym] = {"days": [days[0], days[-1]], "n": len(days), "up": up, "dn": dn,
                    "source": src.name, "source_sha256": hashlib.sha256(src.read_bytes()).hexdigest(),
                    "validation": {"split": [days[0], days[half - 1], days[half], days[-1]],
                                   "promised_realized_n": bins,
                                   "corridor_inside_share": round(float(np.mean((u[half:] <= qu) & (w[half:] <= qd))), 3)}}
    TABLE.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


_TAB = None


def table() -> dict:
    global _TAB
    if _TAB is None:
        _TAB = json.loads(TABLE.read_text(encoding="utf-8")) if TABLE.exists() else build_table()
    return _TAB


def chance(sym: str, side: str, dist_atr: float) -> float:
    arr = np.array(table()[sym]["up" if side == "up" else "dn"])
    return float(np.mean(arr >= dist_atr))


# ---------------------------------------------------------------- прогноз и проверка
def _read() -> list[dict]:
    return [json.loads(x) for x in LOG.read_text(encoding="utf-8").splitlines() if x.strip()] if LOG.exists() else []


def _append(rec: dict) -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def forecast(sym: str, day: date, levels: list[tuple[str, float]] = ()) -> dict | None:
    """Прогноз от 08:00 `day`: P0 = open минуты 08:00, ATR по 15 закрытым часам до 08:00, коридор по квантилю 90%
    каждой стороны, шанс коснуться каждого уровня. Пишется один раз на (день, монету)."""
    for r in _read():
        if r.get("kind") == "forecast" and r["date"] == day.isoformat() and r["sym"] == sym:
            return r
    a = anchor_ms(day)
    k = klines(sym, "1m", a, a + MIN)
    hrs = klines(sym, "1h", a - 15 * HOUR, a)
    if not k or int(k[0][0]) != a or len(hrs) != 15 or any(int(hrs[i][6]) >= a for i in range(15)):
        return None
    p0 = float(k[0][1])
    atr = atr14([float(x[2]) for x in hrs], [float(x[3]) for x in hrs], [float(x[4]) for x in hrs])
    t = table()[sym]
    hi = p0 + float(np.quantile(t["up"], Q)) * atr
    lo = p0 - float(np.quantile(t["dn"], Q)) * atr
    lv = []
    for name, price in levels:
        side = "up" if price > p0 else "dn"
        dist = abs(price - p0) / atr
        lv.append({"name": name, "price": price, "side": side, "dist_atr": round(dist, 3),
                   "chance": round(chance(sym, side, dist), 3)})
    rec = {"kind": "forecast", "date": day.isoformat(), "sym": sym, "A_ms": a, "P0": p0, "atr": atr,
           "corridor": [lo, hi], "q": Q, "median_move": [float(np.median(t["dn"])) * atr, float(np.median(t["up"])) * atr],
           "levels": lv, "table_days": t["days"], "made_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    _append(rec)
    return rec


def check(sym: str, day: date, now: datetime) -> dict | None:
    """Исход прогноза `day`: полные 1440 минут — коридор удержан? уровни задеты? Пишется один раз."""
    for r in _read():
        if r.get("kind") == "check" and r["date"] == day.isoformat() and r["sym"] == sym:
            return r
    f = next((r for r in _read() if r.get("kind") == "forecast" and r["date"] == day.isoformat() and r["sym"] == sym),
             None)
    if f is None or now.timestamp() * 1000 < f["A_ms"] + 1440 * MIN + MIN:
        return None
    rows = klines(sym, "1m", f["A_ms"], f["A_ms"] + 1440 * MIN)
    if len(rows) != 1440 or any(int(r[0]) != f["A_ms"] + i * MIN for i, r in enumerate(rows)):
        return None
    h, lw = max(float(r[2]) for r in rows), min(float(r[3]) for r in rows)
    lo, hi = f["corridor"]
    rec = {"kind": "check", "date": day.isoformat(), "sym": sym, "high": h, "low": lw,
           "inside": h <= hi and lw >= lo, "broke_up": h > hi, "broke_down": lw < lo,
           "levels": [{**x, "touched": (h >= x["price"]) if x["side"] == "up" else (lw <= x["price"])}
                      for x in f["levels"]]}
    _append(rec)
    return rec


def stats(sym: str) -> dict:
    ch = [r for r in _read() if r.get("kind") == "check" and r["sym"] == sym]
    lv = [x for r in ch for x in r["levels"]]
    return {"days": len(ch), "inside": sum(r["inside"] for r in ch),
            "levels": len(lv), "promised": (sum(x["chance"] for x in lv) / len(lv)) if lv else None,
            "realized": (sum(x["touched"] for x in lv) / len(lv)) if lv else None}


def _p(x: float, sym: str) -> str:
    return f"{x:,.0f}" if sym.startswith("BTC") else f"{x:,.1f}"


def zones_at(day: date) -> list[tuple[str, float]]:
    """Ближние края первых зон CoinGlass из снимка 08:00 этого дня (снят в [07:50; 08:10]). Позже снятые зоны
    не берём: цена могла уже дойти до них после 08:00, и сверка касаний врала бы в пользу прогноза."""
    p = DIR / "snapshots.jsonl"
    a = anchor_ms(day)
    best = None
    for line in (p.read_text(encoding="utf-8").splitlines() if p.exists() else []):
        try:
            s = json.loads(line)
        except ValueError:
            continue
        cap = s.get("levels_captured")
        if not s.get("levels") or not cap:
            continue
        t = datetime.fromisoformat(cap).timestamp() * 1000
        if a - 10 * MIN <= t <= a + 10 * MIN:
            best = s
    if best is None:
        return []
    lv, out = best["levels"], []
    zs, zl = (lv.get("zones_short") or [None])[0], (lv.get("zones_long") or [None])[0]
    if zs:
        out.append(("зоны шортов сверху", float(zs["lo"])))
    if zl:
        out.append(("зоны лонгов снизу", float(zl["hi"])))
    return out


def lines(now: datetime | None = None, zones: list[tuple[str, float]] | None = None) -> list[str]:
    """Блок карточки: прогноз на сегодня (BTC с зонами CoinGlass из снимка 08:00, ETH) + вчерашний итог + сверка."""
    now = now or datetime.now(timezone.utc)
    loc = now.astimezone(WARSAW)
    today = loc.date() if loc.hour >= HOUR_LOCAL else loc.date() - timedelta(days=1)
    zones = zones_at(today) if zones is None else zones
    out = ["📏 Прогноз на сутки — размах, не направление (от 08:00 до 08:00 завтра):"]
    for sym in SYMS:
        name = sym[:3]
        try:
            f = forecast(sym, today, zones if sym == "BTCUSDT" else ())
        except Exception as exc:                                # noqa: BLE001
            out.append(f"• {name}: не посчитано ({type(exc).__name__})")
            continue
        if f is None:
            out.append(f"• {name}: нет полных свечей Binance на 08:00 — пропуск")
            continue
        lo, hi = f["corridor"]
        dn, up = f["median_move"]
        out.append(f"• {name} от {_p(f['P0'], sym)}: коридор {_p(lo, sym)}–{_p(hi, sym)} (≈3 дня из 4 цена "
                   f"внутри); обычный ход за сутки вверх до +{_p(up, sym)}, вниз до −{_p(dn, sym)}")
        for x in f["levels"]:
            pct = (x["price"] / f["P0"] - 1) * 100
            out.append(f"  шанс коснуться {x['name']} {_p(x['price'], sym)} ({pct:+.1f}%): {x['chance'] * 100:.0f}%")
    for sym in SYMS:
        try:
            c = check(sym, today - timedelta(days=1), now)
        except Exception:                                       # noqa: BLE001
            c = None
        if c:
            how = "удержан" if c["inside"] else ("пробит вверх" if c["broke_up"] else "") + \
                (" и " if c["broke_up"] and c["broke_down"] else "") + ("пробит вниз" if c["broke_down"] else "")
            tl = "; ".join(f"{x['name']} {'задета' if x['touched'] else 'нет'} (шанс был {x['chance'] * 100:.0f}%)"
                           for x in c["levels"])
            out.append(f"  вчера {sym[:3]}: коридор {how}" + (f"; {tl}" if tl else ""))
    s = stats("BTCUSDT")
    if s["days"]:
        tail = (f"; шансы касания — обещано в среднем {s['promised'] * 100:.0f}%, сбылось {s['realized'] * 100:.0f}% "
                f"({s['levels']} уровней)") if s["levels"] else ""
        out.append(f"  сверка BTC за {s['days']} дн.: коридор держался {s['inside']}/{s['days']}{tail}"
                   + (" — мало дней" if s["days"] < 30 else ""))
    v = table()["BTCUSDT"]["validation"]["promised_realized_n"]
    out.append("  на истории вне выборки: обещано " + "/".join(f"{b[0] * 100:.0f}" for b in v) + "% → сбылось "
               + "/".join(f"{b[1] * 100:.0f}" for b in v) + "%")
    return out
