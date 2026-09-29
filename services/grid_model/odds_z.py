"""Шансы касания уровня: z-модель на волатильности. Замена зонной модели SMA100.

ЧТО ЗАМЕРЕНО (29.09.2026, дневные свечи Binance с 17.08.2017, 3230 дней):

1. Признаки вне выборки (учим на половине истории, оцениваем на другой, и
   наоборот; скилл = 1 − Brier/Brier базы, горизонты 1–30 дней):
       волатильность-терциль      BTC +4.4%  ETH +3.9%   (в плюсе 95%/92% ячеек)
       растянутость за 30 дней    BTC +1.4%  ETH +2.1%
       зона SMA100 (прежний /odds) BTC +0.9%  ETH +0.8%   ← самый слабый
       волатильность × SMA100     BTC +1.9%  ETH +1.6%   ← переобучение

2. z-модель: порог в единицах текущей σ, z = X / (σ_дня · √h). Все горизонты и
   пороги ложатся на одну шкалу, в ячейке тысячи наблюдений:
       σ = std 20д        BTC +7.9%  ETH +4.9%
       σ = EWMA           BTC +9.2%  ETH +6.5%
       σ = Паркинсон 20д  BTC +9.5%  ETH +7.1%   ← берём
   Добавка SMA100 поверх z ухудшает на обоих активах.

3. Калибровка (учим на 1-й половине, проверяем на 2-й): 4%→4%, 36%→35%,
   49%→50%, 75%→73% (BTC); наибольшее расхождение 4 п.п. (ETH 29%→25%).

4. Тезис «после ралли повтор менее вероятен» на 9 годах ОПРОВЕРГНУТ: после
   >20% над SMA100 рост +20% за 90д — 63% против 52% безусловно, обе половины
   и все терцили σ в ту же сторону. На 867 днях (2024–2026) было наоборот
   (13% против 32%) — один эпизод, выборка не держит.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "historical"
CACHE = ROOT / "state"

HORIZONS = (1, 3, 7, 14, 30, 60, 90)
THRESH = (0.02, 0.03, 0.05, 0.075, 0.10, 0.15, 0.20, 0.30, 0.40)
# Мелкие корзины + интерполяция между их центрами + монотонность. Грубые
# корзины (первая версия) давали насыщение: +3% за 14/30/90 дней застывало на
# 80%, и скачки между соседними корзинами (коридор ETH 10% против BTC 44%).
ZBINS = np.array([0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.15,
                  1.3, 1.5, 1.75, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 6.0, 8.0, 99.0])
RACE_THR = (0.02, 0.03, 0.05, 0.075, 0.10, 0.15, 0.20)
RACE_BINS = np.array([0.0, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 99.0])
SHRINK = 20
PARK_N = 20


def load_daily(symbol: str, refresh: bool = True) -> pd.DataFrame:
    path = DATA / f"daily_{symbol}.csv"
    stale = (not path.exists()
             or time.time() - path.stat().st_mtime > 12 * 3600)
    if refresh and stale:
        try:
            from tools.fetch_daily_history import fetch
            fetch(symbol)
        except Exception:                                   # noqa: BLE001
            logger.exception("odds_z.refresh_failed sym=%s", symbol)
    d = pd.read_csv(path)
    d["ts"] = pd.to_datetime(d["ts_ms"], unit="ms", utc=True)
    d = d.set_index("ts")[["high", "low", "close"]].astype(float)
    d["sigma"] = parkinson(d)
    c = d["close"]
    d["dist"] = (c / c.rolling(100).mean() - 1) * 100
    return d


def parkinson(d: pd.DataFrame, n: int = PARK_N) -> pd.Series:
    """Дневная σ по размаху high/low — лучше всего вне выборки."""
    x = np.log(d["high"] / d["low"]) ** 2 / (4 * np.log(2))
    return np.sqrt(x).rolling(n).mean()


def _fwd_extremes(d: pd.DataFrame, h: int) -> tuple[np.ndarray, np.ndarray]:
    """Макс. high и мин. low за следующие h дней относительно close сегодня."""
    hi = d["high"].shift(-1).rolling(h).max().shift(-(h - 1))
    lo = d["low"].shift(-1).rolling(h).min().shift(-(h - 1))
    c = d["close"]
    return (hi / c - 1).to_numpy(), (lo / c - 1).to_numpy()


def build_table(d: pd.DataFrame) -> pd.DataFrame:
    sd = d["sigma"].to_numpy()
    rows = []
    for h in HORIZONS:
        mx, mn = _fwd_extremes(d, h)
        ok = ~np.isnan(mx) & ~np.isnan(sd)
        for thr in THRESH:
            z = thr / (sd * np.sqrt(h))
            for kind, y in (("up", mx >= thr), ("down", mn <= -thr),
                            ("stay", (mx < thr) & (mn > -thr))):
                rows.append(pd.DataFrame({
                    "i": np.flatnonzero(ok), "h": h, "thr": thr, "kind": kind,
                    "z": z[ok], "y": y[ok].astype(float)}))
    return pd.concat(rows, ignore_index=True)


def _fit(table: pd.DataFrame) -> dict:
    """Для каждого вида (up/down/stay) — кривая p(z): центры корзин и частоты.

    Касание вверх/вниз с ростом z может только падать, удержание в коридоре —
    только расти; нарушение монотонности = шум корзины, срезаем его.
    """
    t = table.assign(zb=np.digitize(table["z"], ZBINS))
    p0 = t.groupby("kind")["y"].mean()
    curves = {}
    for kind, g in t.groupby("kind"):
        agg = g.groupby("zb").agg(z=("z", "mean"), s=("y", "sum"), n=("y", "count"))
        agg = agg[agg["n"] >= 30].sort_values("z")
        p = ((agg["s"] + SHRINK * p0[kind]) / (agg["n"] + SHRINK)).to_numpy()
        p = np.maximum.accumulate(p) if kind == "stay" else np.minimum.accumulate(p)
        curves[kind] = {"z": agg["z"].round(5).tolist(), "p": p.round(5).tolist()}
    return {"cells": curves, "p0": {k: float(v) for k, v in p0.items()}}


def _curve_p(curves: dict, p0: dict, kind: str, z: float) -> float:
    c = curves.get(kind)
    if not c or not c["z"]:
        return float(p0[kind])
    return float(np.interp(z, c["z"], c["p"]))


def fit_race(d: pd.DataFrame, max_days: int = 120) -> dict:
    """Кто первый: +X или −X. Бин по z = X/σ_дня."""
    c, hi, lo, sd = (d[k].to_numpy() for k in ("close", "high", "low", "sigma"))
    n, stat = len(d), {}
    for i in range(n):
        if not np.isfinite(sd[i]) or sd[i] <= 0:
            continue
        for thr in RACE_THR:
            up_l, dn_l = c[i] * (1 + thr), c[i] * (1 - thr)
            res = None
            for j in range(i + 1, min(n, i + 1 + max_days)):
                u, dn = hi[j] >= up_l, lo[j] <= dn_l
                if u and dn:
                    res = 0.5
                elif u:
                    res = 1.0
                elif dn:
                    res = 0.0
                if res is not None:
                    break
            if res is None:
                continue
            zb = int(np.digitize(thr / sd[i], RACE_BINS))
            s, k = stat.get(zb, (0.0, 0))
            stat[zb] = (s + res, k + 1)
    return {str(k): (s + SHRINK * 0.5) / (n_ + SHRINK) for k, (s, n_) in stat.items()}


def oos_skill(d: pd.DataFrame, table: pd.DataFrame | None = None) -> float:
    """Скилл вне выборки: учим на половине, считаем на другой, горизонты ≤30д."""
    t = (table if table is not None else build_table(d))
    t = t[(t["h"] <= 30) & (t["kind"] != "stay")]
    half = len(d) // 2
    out = []
    for trm, tem in ((t["i"] < half, t["i"] >= half), (t["i"] >= half, t["i"] < half)):
        tr, te = t[trm], t[tem]
        m = _fit(tr)
        base = tr.groupby(["h", "thr", "kind"])["y"].mean().rename("pb")
        te = te.join(base, on=["h", "thr", "kind"])
        p = np.empty(len(te))
        for kind in ("up", "down"):
            mask = (te["kind"] == kind).to_numpy()
            c = m["cells"][kind]
            p[mask] = np.interp(te["z"].to_numpy()[mask], c["z"], c["p"])
        b0 = ((te["pb"] - te["y"]) ** 2).mean()
        out.append(1 - ((p - te["y"]) ** 2).mean() / b0)
    return float(np.mean(out))


def calibration(d: pd.DataFrame, table: pd.DataFrame | None = None) -> pd.DataFrame:
    """Учим на 1-й половине, на 2-й сравниваем предсказание с фактом по децилям."""
    t = (table if table is not None else build_table(d))
    t = t[(t["h"] <= 30) & (t["kind"] != "stay")]
    half = len(d) // 2
    tr, te = t[t["i"] < half], t[t["i"] >= half].copy()
    m = _fit(tr)
    te["p"] = [_curve_p(m["cells"], m["p0"], k, z) for k, z in zip(te["kind"], te["z"])]
    te["bin"] = pd.cut(te["p"], np.linspace(0, 1, 11))
    return te.groupby("bin", observed=True).agg(pred=("p", "mean"), fact=("y", "mean"),
                                                 n=("y", "count"))


@dataclass
class Model:
    symbol: str
    cells: dict
    p0: dict
    race: dict
    skill: float
    last_date: str
    n_days: int

    def p(self, kind: str, pct: float, h: int, sigma: float) -> float:
        z = abs(pct) / (sigma * np.sqrt(h))
        return _curve_p(self.cells, self.p0, kind, z)

    def touch(self, pct: float, h: int, sigma: float) -> float:
        return self.p("up" if pct > 0 else "down", pct, h, sigma)

    def stay(self, pct: float, h: int, sigma: float) -> float:
        return self.p("stay", pct, h, sigma)

    def up_first(self, pct: float, sigma: float) -> float:
        zb = int(np.digitize(abs(pct) / sigma, RACE_BINS))
        return float(self.race.get(str(zb), 0.5))


def get_model(symbol: str, refresh: bool = True) -> tuple[Model, pd.DataFrame]:
    d = load_daily(symbol, refresh=refresh)
    last = str(d.index[-1].date())
    cache = CACHE / f"odds_z_{symbol}.json"
    if cache.exists():
        try:
            raw = json.loads(cache.read_text(encoding="utf-8"))
            if raw.get("last_date") == last:
                return Model(**raw), d
        except Exception:                                   # noqa: BLE001
            logger.exception("odds_z.cache_read_failed")
    table = build_table(d)
    fitted = _fit(table)
    m = Model(symbol=symbol, cells=fitted["cells"], p0=fitted["p0"],
              race=fit_race(d), skill=oos_skill(d, table), last_date=last,
              n_days=int(d["sigma"].notna().sum()))
    try:
        cache.write_text(json.dumps(m.__dict__, ensure_ascii=False), encoding="utf-8")
    except OSError:
        logger.exception("odds_z.cache_write_failed")
    return m, d


def option_levels(coin: str = "BTC", band: float = 0.30) -> dict:
    """Опционная структура Deribit (публичный API, без ключа).

    Возвращает спот, крупнейшую стену коллов и путов в пределах ±band и
    уровень смены знака наивной дилерской гаммы. Наивная модель: коллы +,
    путы − (допущение о стороне клиентов). Используем ТОЛЬКО как точки, для
    которых z-модель считает шанс касания; как сигнал не проверено.
    """
    import math
    import urllib.request
    from collections import defaultdict
    from datetime import datetime, timezone

    url = ("https://www.deribit.com/api/v2/public/get_book_summary_by_currency"
           f"?currency={coin}&kind=option")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.load(r)["result"]
    spot = next((x["underlying_price"] for x in data if x.get("underlying_price")), None)
    if not spot:
        return {}
    now = datetime.now(timezone.utc)
    oi_c, oi_p, gex = defaultdict(float), defaultdict(float), defaultdict(float)
    for x in data:
        _, exp, strike, cp = x["instrument_name"].split("-")
        k, oi = float(strike), float(x.get("open_interest") or 0)
        iv = float(x.get("mark_iv") or 0) / 100
        t = ((datetime.strptime(exp, "%d%b%y").replace(hour=8, tzinfo=timezone.utc)
              - now).total_seconds() / (365 * 86400))
        g = 0.0
        if t > 0 and iv > 0:
            d1 = (math.log(spot / k) + 0.5 * iv * iv * t) / (iv * math.sqrt(t))
            g = (math.exp(-0.5 * d1 * d1) / math.sqrt(2 * math.pi)
                 / (spot * iv * math.sqrt(t))) * oi * spot * spot * 0.01
        if cp == "C":
            oi_c[k] += oi
            gex[k] += g
        else:
            oi_p[k] += oi
            gex[k] -= g
    # стены ищем в ±15%: крупнейший интерес в ±30% у BTC оказался на 60k
    # (−28.6%) — формально стена, практически бесполезна для ботов
    near = [k for k in set(oi_c) | set(oi_p) if abs(k / spot - 1) <= min(band, 0.15)]
    out = {"spot": float(spot)}
    above = [k for k in near if k > spot]
    below = [k for k in near if k < spot]
    if above:
        out["call_wall"] = max(above, key=lambda k: oi_c[k])
    if below:
        out["put_wall"] = max(below, key=lambda k: oi_p[k])
    cum = 0.0
    for k in sorted(gex):
        prev, cum = cum, cum + gex[k]
        if prev < 0 <= cum and k > spot * (1 - band):
            out["gamma_flip"] = k
            break
    return out


def after_rally_context(d: pd.DataFrame, h: int = 90, thr: float = 0.20) -> tuple:
    """Частота роста ≥thr за h дней: обычная и после >20% над SMA100."""
    mx, _ = _fwd_extremes(d, h)
    hot = d["dist"].to_numpy() > 20
    ok = ~np.isnan(mx)
    base = float(np.mean(mx[ok] >= thr))
    cond = float(np.mean(mx[ok & hot] >= thr)) if (ok & hot).any() else float("nan")
    return base, cond, int((ok & hot).sum())


def card(symbol: str = "BTCUSDT", levels: list[tuple[str, float]] | None = None,
         price: float | None = None) -> str:
    m, d = get_model(symbol)
    sigma = float(d["sigma"].iloc[-1])
    px = float(price or d["close"].iloc[-1])
    pct_rank = float((d["sigma"].dropna() < sigma).mean() * 100)
    mood = ("тихий" if pct_rank < 33 else "обычный" if pct_rank < 67 else "бурный")
    coin = symbol.replace("USDT", "")
    hz = (1, 3, 7, 14, 30, 90)
    out = [
        f"🎲 ШАНСЫ · {coin} {px:,.0f} · σ {sigma * 100:.2f}%/день "
        f"({sigma * np.sqrt(365) * 100:.0f}% год.) — {mood} рынок, "
        f"перцентиль {pct_rank:.0f}",
        f"модель: касание уровня за N дней, σ по дневному размаху, {m.n_days} дней "
        f"истории; вне выборки {m.skill:+.1%} к базовой частоте",
        "",
        "ВЕРОЯТНОСТЬ КОСНУТЬСЯ:",
        f"  {'уровень':>9}" + "".join(f"{f'{h}д':>7}" for h in hz),
    ]
    for pct in (0.20, 0.10, 0.05, 0.03, -0.03, -0.05, -0.10, -0.20):
        row = f"  {pct:>+8.0%} "
        row += "".join(f"{m.touch(pct, h, sigma):>7.0%}" for h in hz)
        out.append(row)
    out.append("")
    out.append("КТО ПЕРВЫЙ (симметричные уровни):")
    out.append("  " + " · ".join(f"±{p:.0%}: вверх {m.up_first(p, sigma):.0%}"
                                 for p in (0.03, 0.05, 0.10)))
    out.append("УДЕРЖИТСЯ В КОРИДОРЕ:")
    out.append("  " + " · ".join(f"±{p:.0%} {h}д: {m.stay(p, h, sigma):.0%}"
                                 for p, h in ((0.03, 3), (0.05, 7), (0.10, 30))))
    if levels:
        out.append("")
        out.append("УРОВНИ:")
        for name, lvl in levels:
            pct = lvl / px - 1
            probs = " · ".join(f"{h}д {m.touch(pct, h, sigma):.0%}" for h in (7, 30, 90))
            out.append(f"  {name} {lvl:,.0f} ({pct:+.1%}): {probs}")
    base, cond, n = after_rally_context(d)
    dist_now = float(d["dist"].iloc[-1])
    out.append("")
    out.append(f"КОНТЕКСТ: {dist_now:+.1f}% над SMA100. На всей истории после роста >20% "
               f"над SMA100 рост +20% за 90д шёл ЧАЩЕ: {cond:.0%} против {base:.0%} "
               f"(n={n}). Отката после ралли статистика не обещает.")
    return "\n".join(out)
