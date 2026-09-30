"""Шансы внутри дня: коснётся ли цена уровня за 1ч / 4ч / 12ч / сутки.

Та же z-модель, что odds_z, но на часовых свечах Binance с 17.08.2017
(79 803 часа BTC и ETH). Порог в единицах ожидаемой σ до горизонта:
    z = X / σ_пути(h),   σ_пути(h) = σ_без_сезона · √Σ s(час недели)²
σ_без_сезона — средний Паркинсон-размах за 24 часа, делённый на профиль часа
недели s. Профиль нужен, потому что час с открытием США и час азиатской ночи —
разные рынки: s = 1.1–1.25 в 12–16 UTC и 00 UTC, 0.87 в 03–07 UTC, выходные
0.87–0.92.

ЗАМЕР 29.09.2026 (учим на половине, Brier на другой, скилл = 1 − Brier/Brier
базовой частоты ячейки час×порог):

    оценка σ                   BTC     ETH
    Паркинсон 480ч (≈20 дней)  +14.6%  +11.7%   ← σ дневной модели
    дневная 20д / √24          +14.3%  +11.4%
    Паркинсон 24ч              +17.7%  +14.9%
    EWMA полураспад 6ч         +18.1%  +15.3%
    0.6·24ч + 0.4·168ч         +18.2%  +15.2%
    24ч с профилем часа недели +18.3%  +15.4%   ← берём

Поверхность плоская (разброс лучших 0.6 п.п.) — выбран вариант, который
объясним и различает часы. Скилл по горизонтам (BTC): 1ч +22%, 4ч +20%,
12ч +17%, сутки +14%.

Кривые p(z) учатся ОТДЕЛЬНО на каждый горизонт: одна общая кривая (как в
дневной модели) расходилась с фактом до 11 п.п. на сутках.

Калибровка (`oos_check`: профиль и кривые учим до 12.03.2022, проверяем
после): касание вверх/вниз — обещанное против факта ≤3 п.п. на каждом
горизонте (BTC 2.9, ETH 3.0). Коридор: около 80% — 76%→73% BTC и 85%→90%
ETH на сутки; в середине шкалы 45–65% на сутки факт ниже обещанного на
4–7 п.п. Скилл вне выборки BTC +16.8%, ETH +15.1%; последний год отдельно
(ворота №2) BTC +17.3%, ETH +15.0% — свежий период держится сам.

Направление модель НЕ предсказывает: «вверх» и «вниз» различаются только
многолетним дрейфом. Скилл — это знание размаха, а не стороны.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from services.grid_model.odds_z import _curve_p, _fit

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "historical"
CACHE = ROOT / "state"

HOURS = (1, 4, 12, 24)
THRESH = (0.0025, 0.005, 0.0075, 0.01, 0.015, 0.02, 0.03, 0.05, 0.075)
WINDOW = 24
REFIT_DAYS = 7
LN2x4 = 4 * np.log(2)
MEASURED_SKILL = {"BTCUSDT": 0.168, "ETHUSDT": 0.151}     # oos_check 29.09.2026
MEASURED_FRESH = {"BTCUSDT": 0.173, "ETHUSDT": 0.150}


def load_hourly(symbol: str, refresh: bool = True) -> pd.DataFrame:
    path = DATA / f"1h_{symbol}.csv"
    stale = (not path.exists()
             or time.time() - path.stat().st_mtime > 3600)
    if refresh and stale:
        try:
            from tools.fetch_daily_history import fetch
            fetch(symbol, "1h")
        except Exception:                                   # noqa: BLE001
            logger.exception("odds_intraday.refresh_failed sym=%s", symbol)
    d = pd.read_csv(path)
    d["ts"] = pd.to_datetime(d["ts_ms"], unit="ms", utc=True)
    d = d.set_index("ts")[["high", "low", "close"]].astype(float)
    d = d[(d["high"] > 0) & (d["low"] > 0)]
    d["pk"] = np.sqrt(np.log(d["high"] / d["low"]) ** 2 / LN2x4)
    d["how"] = d.index.dayofweek * 24 + d.index.hour
    return d


def season_profile(d: pd.DataFrame, mask: np.ndarray | None = None) -> np.ndarray:
    """Средний размах по часу недели (UTC) относительно общего среднего."""
    pk, how = d["pk"].to_numpy(), d["how"].to_numpy()
    if mask is not None:
        pk, how = pk[mask], how[mask]
    prof = pd.Series(pk).groupby(how).mean().reindex(range(168))
    prof = prof.fillna(prof.mean())
    return (prof / prof.mean()).to_numpy()


def deseason_sigma(d: pd.DataFrame, s: np.ndarray) -> np.ndarray:
    return (d["pk"] / s[d["how"].to_numpy()]).rolling(WINDOW).mean().to_numpy()


def path_scale(s: np.ndarray, how: np.ndarray | int, h: int) -> np.ndarray:
    """√Σ s² по часам, которые пройдут после текущего: сколько «часов σ» впереди."""
    how = np.asarray(how)
    acc = np.zeros(how.shape)
    for k in range(1, h + 1):
        acc = acc + s[(how + k) % 168] ** 2
    return np.sqrt(acc)


def _fwd(d: pd.DataFrame, h: int) -> tuple[np.ndarray, np.ndarray]:
    hi = d["high"].shift(-1).rolling(h).max().shift(-(h - 1))
    lo = d["low"].shift(-1).rolling(h).min().shift(-(h - 1))
    c = d["close"]
    return (hi / c - 1).to_numpy(), (lo / c - 1).to_numpy()


def build_table(d: pd.DataFrame, s: np.ndarray) -> pd.DataFrame:
    ds, how = deseason_sigma(d, s), d["how"].to_numpy()
    rows = []
    for h in HOURS:
        mx, mn = _fwd(d, h)
        se = ds * path_scale(s, how, h)
        ok = ~np.isnan(mx) & np.isfinite(se) & (se > 0)
        for thr in THRESH:
            z = thr / se
            for kind, y in (("up", mx >= thr), ("down", mn <= -thr),
                            ("stay", (mx < thr) & (mn > -thr))):
                rows.append(pd.DataFrame({
                    "i": np.flatnonzero(ok), "h": h, "thr": thr, "kind": kind,
                    "z": z[ok], "y": y[ok].astype(np.float32)}))
    return pd.concat(rows, ignore_index=True)


def fit(table: pd.DataFrame) -> dict:
    """Кривые p(z) отдельно на каждый горизонт.

    Одна кривая на все горизонты (как в дневной модели) здесь врёт: удержание
    в коридоре на сутки расходилось с фактом до 11 п.п. У часа одна свеча,
    у суток — 24, форма распределения экстремума разная.
    """
    out = {}
    for h, g in table.groupby("h"):
        out[str(int(h))] = _fit(g)
    return out


def predict(fitted: dict, t: pd.DataFrame) -> np.ndarray:
    p = np.zeros(len(t))
    for (h, kind), idx in t.groupby(["h", "kind"]).indices.items():
        c = fitted[str(int(h))]["cells"][kind]
        p[idx] = np.interp(t["z"].to_numpy()[idx], c["z"], c["p"])
    return p


def oos_check(d: pd.DataFrame, fresh_hours: int = 24 * 365) -> dict:
    """Учим профиль и кривые на 1-й половине, на 2-й — скилл и калибровка.

    Отдельно — последний год (ворота №2): свежий период обязан держаться сам.
    """
    n = len(d)
    half = n // 2
    s = season_profile(d, np.arange(n) < half)
    t = build_table(d, s)
    tr, te = t[t["i"] < half], t[t["i"] >= half].copy()
    m = fit(tr)
    te["p"] = predict(m, te)
    fresh = te[(te["i"] >= n - fresh_hours) & (te["kind"] != "stay")]
    base_all = tr.groupby(["h", "thr", "kind"])["y"].mean().rename("pb")
    fresh = fresh.join(base_all, on=["h", "thr", "kind"])
    fresh_skill = 1 - (((fresh["p"] - fresh["y"]) ** 2).mean()
                       / ((fresh["pb"] - fresh["y"]) ** 2).mean())
    base = tr.groupby(["h", "thr", "kind"])["y"].mean().rename("pb")
    te = te.join(base, on=["h", "thr", "kind"])
    touch = te[te["kind"] != "stay"]
    skill = 1 - (((touch["p"] - touch["y"]) ** 2).mean()
                 / ((touch["pb"] - touch["y"]) ** 2).mean())
    te["bin"] = pd.cut(te["p"], np.linspace(0, 1, 11))
    cal = te.groupby(["h", "kind", "bin"], observed=True).agg(
        pred=("p", "mean"), fact=("y", "mean"), n=("y", "count"))
    cal = cal[cal["n"] >= 300]
    return {"skill": float(skill), "fresh_skill": float(fresh_skill),
            "worst_gap": float((cal["pred"] - cal["fact"]).abs().max()),
            "cal": cal}


@dataclass
class Model:
    symbol: str
    curves: dict             # "h" → {"cells": {kind: {z, p}}, "p0": {kind: p}}
    profile: list
    fitted_at: float
    n_hours: int

    def _p(self, kind: str, pct: float, h: int, sigma_path: float) -> float:
        z = abs(pct) / sigma_path if sigma_path > 0 else 99.0
        c = self.curves[str(h)]
        return _curve_p(c["cells"], c["p0"], kind, z)

    def touch(self, pct: float, h: int, sigma_path: float) -> float:
        return self._p("up" if pct > 0 else "down", pct, h, sigma_path)

    def stay(self, pct: float, h: int, sigma_path: float) -> float:
        return self._p("stay", pct, h, sigma_path)

    def corridor(self, h: int, sigma_path: float, p: float = 0.8) -> float:
        """Полуширина коридора, внутри которого цена останется с вероятностью p."""
        for x in np.arange(0.0005, 0.30, 0.0005):
            if self.stay(float(x), h, sigma_path) >= p:
                return float(x)
        return 0.30


def get_model(symbol: str, d: pd.DataFrame | None = None) -> tuple[Model, pd.DataFrame]:
    """Кривые и профиль переобучаются раз в неделю (≈20 с), σ — на каждый вызов."""
    if d is None:
        d = load_hourly(symbol)
    cache = CACHE / f"odds_intraday_{symbol}.json"
    if cache.exists():
        try:
            raw = json.loads(cache.read_text(encoding="utf-8"))
            if time.time() - raw["fitted_at"] < REFIT_DAYS * 86400:
                return Model(**raw), d
        except Exception:                                   # noqa: BLE001
            logger.exception("odds_intraday.cache_read_failed")
    s = season_profile(d)
    m = Model(symbol=symbol, curves=fit(build_table(d, s)),
              profile=[round(float(x), 5) for x in s], fitted_at=time.time(),
              n_hours=len(d))
    try:
        cache.write_text(json.dumps(m.__dict__, ensure_ascii=False), encoding="utf-8")
    except OSError:
        logger.exception("odds_intraday.cache_write_failed")
    return m, d


@dataclass
class Now:
    sigma_hour: float        # σ без сезона, доля за час
    paths: dict              # h → σ пути до горизонта
    pct_rank: float          # перцентиль σ_без_сезона на всей истории
    ahead4: float            # средний профиль следующих 4 часов


def now_state(m: Model, d: pd.DataFrame) -> Now:
    s = np.asarray(m.profile)
    ds = deseason_sigma(d, s)
    cur = float(ds[-1])
    how = int(d["how"].iloc[-1])
    hist = ds[np.isfinite(ds)]
    return Now(sigma_hour=cur,
               paths={h: cur * float(path_scale(s, how, h)) for h in HOURS},
               pct_rank=float((hist < cur).mean() * 100),
               ahead4=float(np.mean([s[(how + k) % 168] for k in range(1, 5)])))


def _fmt_p(p: float) -> str:
    if p < 0.01:
        return "<1%"
    if p > 0.99:
        return ">99%"
    return f"{p:.0%}"


def card(symbol: str = "BTCUSDT", levels: list[tuple[str, float]] | None = None,
         price: float | None = None) -> str:
    m, d = get_model(symbol)
    now = now_state(m, d)
    px = float(price or d["close"].iloc[-1])
    coin = symbol.replace("USDT", "")
    mood = ("тише обычного" if now.pct_rank < 33
            else "обычный" if now.pct_rank < 67 else "бурнее обычного")
    ahead = ("впереди активные часы" if now.ahead4 > 1.05
             else "впереди тихие часы" if now.ahead4 < 0.95 else "")
    head = (f"🎲 {coin} {px:,.0f} · ближайшие часы · размах {now.sigma_hour * 100:.2f}%/час"
            f" — {mood} (перцентиль {now.pct_rank:.0f})")
    if ahead:
        head += f", {ahead} (×{now.ahead4:.2f})"
    names = {1: "1ч", 4: "4ч", 12: "12ч", 24: "сутки"}
    out = [head, "", "КОСНЁТСЯ:" + " " * 7 + "".join(f"{names[h]:>7}" for h in HOURS)]
    rows = [0.03, 0.02, 0.01, 0.005, -0.005, -0.01, -0.02, -0.03]
    if m.touch(0.05, 24, now.paths[24]) >= 0.05:
        rows = [0.05] + rows + [-0.05]
    for pct in rows:
        out.append(f"  {pct:>+6.1%} {px * (1 + pct):>9,.0f}"
                   + "".join(f"{_fmt_p(m.touch(pct, h, now.paths[h])):>7}"
                             for h in HOURS))
    out.append("")
    cor = []
    for h in HOURS:
        x = m.corridor(h, now.paths[h], 0.8)
        cor.append(f"{names[h]} ±{x:.1%} ({px * (1 - x):,.0f}–{px * (1 + x):,.0f})")
    out.append("КОРИДОР 80% (цена не выйдет):")
    out.extend(f"  {c}" for c in cor)
    near = [(n, lv) for n, lv in (levels or []) if abs(lv / px - 1) <= 0.06]
    if near:
        out.append("")
        out.append("УРОВНИ РЯДОМ:")
        for name, lvl in sorted(near, key=lambda x: -x[1]):
            pct = lvl / px - 1
            probs = " · ".join(f"{names[h]} {_fmt_p(m.touch(pct, h, now.paths[h]))}"
                               for h in HOURS)
            out.append(f"  {name} {lvl:,.0f} ({pct:+.1%}): {probs}")
    out.append("")
    out.append(f"модель: 9 лет часовых свечей; вне выборки "
               f"{MEASURED_SKILL.get(symbol, 0):+.0%} к базе, свежий год "
               f"{MEASURED_FRESH.get(symbol, 0):+.0%}; касание ≈ факт ±3 п.п., "
               f"коридор ±4. Сторону не угадывает — только размах.")
    return "\n".join(out)
