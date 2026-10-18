"""Досверка снимков CoinGlass — правила v1 (18.10, ответ GPT на docs/COINGLASS_MAC_PIPELINE_2026-10-18.md).

Зона и исход:
  - с каждой стороны — самая сильная опубликованная зона (max strength); касание её БЛИЖНЕГО к цене края: у зоны шортов
    сверху — нижний край U, у зоны лонгов снизу — верхний край L. Границы заморожены на 24 ч;
  - окно — с первой полной минуты ПОСЛЕ времени получения страницы уровней (levels_captured), 24 ч, Binance USDⓈ-M 1m;
    требуется ПОЛНАЯ минутная сетка (каждая минута, без пропусков), иначе исход ждёт; старше 3 сут — «missing»;
  - исход: upper / lower / both (обе в одном отрезке — порядок не определён) / none (ни одна) — все в знаменателе;
  - основное сравнение — на 60-минутных отрезках от момента снимка (та же зернистость, что у базы); минутный исход
    пишется рядом справочно.
База — эмпирическая: расстояния до U и L в ATR14 часовых баров на момент снимка; по всем прошлым часовым окнам Binance
UM (frozen 1m → 1h) — частоты upper/lower/both/none за следующие 24 часа при тех же расстояниях в ATR.
Серия — снимок 07:00 Варшавы (если его нет — день пропущен, другим временем не заменяется). Часовые снимки — не
независимые дни. Итог — описательная таблица, без автоматического объявления преимущества: подтверждение — отдельным
заранее назначенным разбором.
Ближнее поле: пишется доля шортов и её изменение, следующая доходность, high–low диапазон 24 ч и движение предыдущих
24 ч — гипотеза без заранее присвоенного направления.
Ключ результата — (время снимка, горизонт, версия правил); результаты прежних версий не переписываются.
"""
from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

from services.coinglass_web.collector import DIR

RULES = "v1-2026-10-18"
H24 = 24 * 3600
WARSAW = ZoneInfo("Europe/Warsaw")
ROOT = Path(__file__).resolve().parents[2]
HIST = DIR / "hist_1h.npz"
FROZEN = (ROOT / "backtests" / "frozen" / "BTCUSDT_UM_1m_early.csv", ROOT / "backtests" / "frozen" / "BTCUSDT_UM_1m.csv")


def _get(url: str):
    return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "bot7"}),
                                             timeout=20).read())


def _klines(interval: str, start_ms: int, end_ms: int) -> list:
    out, t, step = [], start_ms, {"1m": 60_000, "1h": 3_600_000}[interval]
    while t < end_ms:
        rows = _get(f"https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval={interval}&limit=1500"
                    f"&startTime={t}&endTime={end_ms - 1}")
        if not rows:
            break
        out += rows
        t = int(rows[-1][0]) + step
    return out


def atr14(highs, lows, closes) -> float:
    tr = [highs[0] - lows[0]] + [max(h - l, abs(h - pc), abs(l - pc))
                                 for h, l, pc in zip(highs[1:], lows[1:], closes[:-1])]
    return float(np.mean(tr[-14:]))


def first_touch(highs, lows, upper: float, lower: float) -> str:
    for h, lo in zip(highs, lows):
        hu, hl = h >= upper, lo <= lower
        if hu and hl:
            return "both"
        if hu:
            return "upper"
        if hl:
            return "lower"
    return "none"


# ---------------------------------------------------------------- эмпирическая база
def _hist() -> dict:
    """Часовые бары BTCUSDT UM из frozen 1m (кэш state/coinglass/hist_1h.npz): ts, high, low, close, atr14."""
    if HIST.exists():
        z = np.load(HIST)
        return {k: z[k] for k in z.files}
    import pandas as pd
    parts = [pd.read_csv(p, usecols=["ts", "high", "low", "close"]) for p in FROZEN if p.exists()]
    d = pd.concat(parts).drop_duplicates("ts").sort_values("ts")
    d["h"] = d["ts"] // 3_600_000
    g = d.groupby("h").agg(high=("high", "max"), low=("low", "min"), close=("close", "last"), n=("ts", "size"))
    g = g[g["n"] == 60]                                        # только полные часы
    pc = g["close"].shift()
    tr = np.maximum(g["high"] - g["low"], np.maximum((g["high"] - pc).abs(), (g["low"] - pc).abs()))
    out = {"h": g.index.to_numpy(), "high": g["high"].to_numpy(), "low": g["low"].to_numpy(),
           "close": g["close"].to_numpy(), "atr": tr.rolling(14).mean().to_numpy()}
    np.savez(HIST, **out)
    return out


def baseline(du_atr: float, dl_atr: float, hist: dict | None = None, horizon_h: int = 24) -> dict:
    """Частоты upper/lower/both/none по прошлым часовым окнам при тех же расстояниях в ATR (только непрерывные окна)."""
    hs = hist or _hist()
    h, hi, lo, c, a = hs["h"], hs["high"], hs["low"], hs["close"], hs["atr"]
    n = len(h) - horizon_h
    idx = np.arange(15, n)
    ok = (h[idx + horizon_h] - h[idx] == horizon_h) & np.isfinite(a[idx])          # окно без пропущенных часов
    idx = idx[ok]
    up = c[idx] + du_atr * a[idx]
    dn = c[idx] - dl_atr * a[idx]
    win = idx[:, None] + np.arange(1, horizon_h + 1)[None, :]
    hu = hi[win] >= up[:, None]
    hl = lo[win] <= dn[:, None]
    big = horizon_h + 1
    fu = np.where(hu.any(1), hu.argmax(1), big)
    fl = np.where(hl.any(1), hl.argmax(1), big)
    res = np.where((fu == big) & (fl == big), 0, np.where(fu == fl, 3, np.where(fu < fl, 1, 2)))
    k = len(res)
    return {"n": int(k), "none": float((res == 0).mean()), "upper": float((res == 1).mean()),
            "lower": float((res == 2).mean()), "both": float((res == 3).mean())}


# ---------------------------------------------------------------- исходы
def _snapshots() -> list[dict]:
    p = DIR / "snapshots.jsonl"
    out = []
    for line in (p.read_text(encoding="utf-8").splitlines() if p.exists() else []):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        lv = r.get("levels") or {}
        if lv.get("zones_short") and lv.get("zones_long"):
            out.append(r)
    return out


def _done() -> set:
    p = DIR / "outcomes.jsonl"
    if not p.exists():
        return set()
    keys = set()
    for x in p.read_text(encoding="utf-8").splitlines():
        if x.strip():
            r = json.loads(x)
            keys.add((r["ts"], r["horizon"], r.get("rules", "v0")))
    return keys


def captured(r: dict) -> datetime:
    """Время получения страницы уровней; у снимков v0 его нет — время запуска + 2 мин (консервативно позже)."""
    if r.get("levels_captured"):
        return datetime.fromisoformat(r["levels_captured"])
    return datetime.fromisoformat(r["ts"]) + timedelta(minutes=2)


def evaluate(r: dict, now: datetime, hist: dict | None = None) -> dict | None:
    lv = r["levels"]
    p = lv["price"]
    zs = max(lv["zones_short"], key=lambda z: z["strength"])
    zl = max(lv["zones_long"], key=lambda z: z["strength"])
    up, dn = zs["lo"], zl["hi"]
    cap = captured(r)
    a = (int(cap.timestamp()) // 60 + 1) * 60_000                  # первая полная минута после получения
    if now.timestamp() * 1000 < a + H24 * 1000 + 120_000:
        return None
    rows = _klines("1m", a, a + H24 * 1000)
    ts = [int(x[0]) for x in rows]
    complete = len(ts) == 1440 and all(t == a + i * 60_000 for i, t in enumerate(ts))
    base = {"ts": r["ts"], "horizon": "24h", "rules": RULES, "captured": cap.isoformat(), "price": p,
            "upper": up, "lower": dn, "upper_strength": zs["strength"], "lower_strength": zl["strength"]}
    if not complete:
        if now - cap > timedelta(days=3):
            return {**base, "outcome": "missing", "reason": f"минуток {len(ts)} из 1440"}
        return None
    highs = [float(x[2]) for x in rows]
    lows = [float(x[3]) for x in rows]
    hh = [max(highs[i:i + 60]) for i in range(0, 1440, 60)]          # 60-мин отрезки от момента снимка
    ll = [min(lows[i:i + 60]) for i in range(0, 1440, 60)]
    pre = _klines("1h", a - 16 * 3_600_000, a)                        # закрытые часы до снимка
    ph, pl, pcl = [float(x[2]) for x in pre], [float(x[3]) for x in pre], [float(x[4]) for x in pre]
    atr = atr14(ph, pl, pcl) if len(pre) >= 15 else None
    du_atr = (up - p) / atr if atr else None
    dl_atr = (p - dn) / atr if atr else None
    nr = lv.get("near") or {}
    prior = _klines("1m", a - H24 * 1000, a - H24 * 1000 + 60_000)
    return {**base, "outcome": first_touch(hh, ll, up, dn), "outcome_1m": first_touch(highs, lows, up, dn),
            "atr_1h": atr, "du_atr": du_atr, "dl_atr": dl_atr,
            "base": baseline(du_atr, dl_atr, hist) if atr else None,
            "ret_24h": float(rows[-1][4]) / p - 1, "range_24h": (max(highs) - min(lows)) / p,
            "prior_ret_24h": (p / float(prior[0][1]) - 1) if prior else None,
            "near_short_pct": nr.get("short_pct"), "near_short_pp_24h": nr.get("short_pp_24h")}


def update(now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    done, new, hist = _done(), 0, None
    with open(DIR / "outcomes.jsonl", "a", encoding="utf-8") as f:
        for r in _snapshots():
            if (r["ts"], "24h", RULES) in done:
                continue
            if hist is None:
                hist = _hist()
            rec = evaluate(r, now, hist)
            if rec:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                new += 1
    return new


def is_morning(r: dict) -> bool:
    return captured(r).astimezone(WARSAW).hour == 7


def table() -> dict:
    """Описательная таблица по снимкам 07:00 Варшавы (день без такого снимка пропущен): наблюдаемые доли исходов против
    средних эмпирических ожиданий. Без автоматического вывода о преимуществе."""
    p = DIR / "outcomes.jsonl"
    rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []
    rows = [r for r in rows if r.get("rules") == RULES and r.get("outcome") not in (None, "missing") and r.get("base")
            and datetime.fromisoformat(r["captured"]).astimezone(WARSAW).hour == 7]
    days: dict[str, dict] = {}
    for r in sorted(rows, key=lambda r: r["captured"]):
        days.setdefault(datetime.fromisoformat(r["captured"]).astimezone(WARSAW).strftime("%Y-%m-%d"), r)
    sel = list(days.values())
    n = len(sel)
    if not n:
        return {"n": 0}
    obs = {k: sum(r["outcome"] == k for r in sel) / n for k in ("upper", "lower", "both", "none")}
    exp = {k: sum(r["base"][k] for r in sel) / n for k in ("upper", "lower", "both", "none")}
    return {"n": n, "obs": obs, "exp": exp}
