"""Общий график метрик и разбор совпадений/расхождений (оператор 27–28.10: «видно, где сходятся ликвидации,
лонги-шорты, фандинг», «что сейчас продают или покупают и как сильно»; задание GPT f2559762).

Источники (час UTC, метка — начало бара; ничего не дорисовывается: пропуск = пропуск):
- CoinGlass суперчарт (tv_export: Whale Index 2, ликвидации всех бирж и «Coin-залогом», L/S аккаунтов и топов по
  позициям, ставка фандинга Binance свечами, взвешенная по OI, OI Binance в монетах, дельта тейкеров и стакана ±1%);
- Binance REST: свечи 1ч с объёмом агрессора (taker buy) и фактические выплаты фандинга (раз в 8 ч — точки, не линия);
- deriv_live (5 мин, Binance premiumIndex, OI, L/S) — для сверки с CoinGlass, а не вместо;
- наши потоки ликвидаций Binance/Bybit/OKX USDT-M (liq_raw, время биржи) — другой охват, чем CoinGlass.

Эпизод — часы, где одновременно необычны метрики ≥3 разных семейств (цена/объём, поток, ликвидации, OI, фандинг,
позиции): |z| ≥ 3 против медианы и MAD предыдущих 168 часов (только прошлое); объём и ликвидации — всплеск: не ниже
98-го процентиля прошлой недели и ≥3 её медиан. Соседние часы с разрывом ≤ 2 ч сливаются. Разбор эпизода —
числа до/во время/после, совпадения и расхождения, основное и альтернативное объяснение, что наблюдать и что отменяет
объяснение. «После» в признаки не входит и хранится отдельно (state/coinglass/compare_episodes.jsonl).

Совпадение метрик — описание, не прогноз и не торговый сигнал (проверено: research/market_lens/crowd_check.py,
research/coinglass_compare/operator_lines.py).

Время (разбор GPT e53a117, P1): всё считается по закрытым часам на календарной сетке — пропуск остаётся пропуском, окно
«6 ч» — это ровно 6 календарных часов с подписью «есть k из 6»; бар CoinGlass, выгруженный до своего закрытия, в
расчёт не идёт, пока не придёт закрытая запись; решения и эпизоды хранят свои границы и оцениваются от собственного
времени, а не от заново выделенных групп.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from services.coinglass_web.tv_export import COLUMNS as CG_COLUMNS

ROOT = Path(__file__).resolve().parents[2]
TV_DIR = ROOT / "state" / "coinglass" / "tv"
DERIV = ROOT / "state" / "deriv_live_history.jsonl"
LIQ_RAW = ROOT / "market_live" / "liq_raw"
EPISODES = ROOT / "state" / "coinglass" / "compare_episodes.jsonl"
COMPOSITE = ROOT / "state" / "coinglass" / "compare_composite.jsonl"
WARSAW = ZoneInfo("Europe/Warsaw")
SYMBOLS = ("BTCUSDT", "ETHUSDT")
SHOW_DAYS = 14
WARM_H = 168
Z = 3.0
FAPI = "https://fapi.binance.com"

# метрика → (подпись, как считать, односторонний всплеск)
METRICS = {
    "price": ("цена 1ч", "ret", False),
    "volume": ("объём", "log", True),
    "taker": ("дельта тейкеров", "level", False),
    "book": ("стакан ±1%", "level", False),
    "liq_long": ("ликвидации лонгов", "log", True),
    "liq_short": ("ликвидации шортов", "log", True),
    "oi": ("OI", "ret", False),
    "funding": ("фандинг", "diff", False),
    "ls_acc": ("L/S аккаунтов", "diff", False),
    "ls_top": ("L/S топов", "diff", False),
    "wi2": ("Whale Index 2", "diff", False),
}
# семейства: L/S, топы и Whale Index 2 часто прыгают вместе — эпизод требует разных семейств, а не трёх родственных
FAMILY = {"price": "цена", "volume": "цена", "taker": "поток", "book": "поток", "liq_long": "ликвидации",
          "liq_short": "ликвидации", "oi": "OI", "funding": "фандинг", "ls_acc": "позиции", "ls_top": "позиции",
          "wi2": "позиции"}


# ─────────────────────────────── загрузка ───────────────────────────────

def load_tv(sym: str, asof: datetime | None = None, base: Path = TV_DIR) -> pd.DataFrame:
    """Журнал выгрузок CoinGlass → последнее известное к asof значение каждого бара (asof=None — последнее вообще)."""
    path = base / f"{sym}_1h.jsonl"
    rows: dict[str, dict] = {}
    if path.exists():
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if asof is not None and datetime.fromisoformat(r["obs"]) > asof:
                    continue
                rows[r["bar"]] = r
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows.values())
    df.index = pd.to_datetime(df.pop("bar"), utc=True)
    return df.sort_index()


def _tail_lines(path: Path, nbytes: int) -> list[str]:
    with open(path, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - nbytes))
        data = f.read().decode("utf-8", errors="ignore")
    lines = data.split("\n")
    return lines[1:] if size > nbytes else lines


def load_deriv(sym: str, since: datetime, path: Path = DERIV) -> pd.DataFrame:
    """deriv_live (5 мин) → час: последнее значение в часе и число замеров (охват)."""
    if not path.exists():
        return pd.DataFrame()
    days = (datetime.now(timezone.utc) - since).total_seconds() / 86400 + 1
    recs = []
    for line in _tail_lines(path, int(days * 288 * 4000)):
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except ValueError:
            continue
        d = r.get(sym)
        ts = r.get("last_updated")
        if not d or not ts:
            continue
        t = datetime.fromisoformat(ts)
        if t < since:
            continue
        fr = d.get("funding_rate_8h")
        recs.append({"t": t, "fr_premium_pct": fr * 100 if fr is not None else None, "oi_native": d.get("oi_native"),
                     "ls_global": d.get("global_ls_ratio"), "ls_top": d.get("top_trader_ls_ratio")})
    if not recs:
        return pd.DataFrame()
    df = pd.DataFrame(recs).set_index("t").sort_index()
    df.index = pd.to_datetime(df.index, utc=True)
    g = df.resample("1h")
    out = g.last()
    out["deriv_samples"] = g["oi_native"].count()
    return out


def load_liq(sym: str, since: datetime, base: Path = LIQ_RAW) -> pd.DataFrame:
    """Наши потоки ликвидаций (время биржи) → час: USD лонгов/шортов и число событий; часы без файла — пропуск."""
    recs = []
    day = since.date()
    covered = set()
    while day <= datetime.now(timezone.utc).date():
        for ex in ("binance", "bybit", "okx"):
            p = base / f"{ex}_{day:%Y%m%d}.jsonl"
            if not p.exists():
                continue
            covered.add((ex, day))
            with open(p, encoding="utf-8") as f:
                for line in f:
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    if r.get("symbol") != sym or not r.get("exchange_ts_ms"):
                        continue
                    raw = r.get("raw") or {}
                    try:
                        px = float(raw.get("ap") or r.get("price"))
                        usd = float(r.get("qty")) * px
                    except (TypeError, ValueError):
                        continue
                    recs.append({"t": datetime.fromtimestamp(r["exchange_ts_ms"] / 1000, timezone.utc),
                                 "side": r.get("side_liquidated"), "usd": usd})
        day += timedelta(days=1)
    if not recs:
        return pd.DataFrame()
    df = pd.DataFrame(recs)
    df = df[df["t"] >= since]
    df["t"] = pd.to_datetime(df["t"], utc=True).dt.floor("1h")
    p = df.pivot_table(index="t", columns="side", values="usd", aggfunc="sum")
    out = pd.DataFrame({"our_liq_long": p.get("long"), "our_liq_short": p.get("short")})
    out["our_liq_events"] = df.groupby("t").size()
    return out.sort_index()


def _get(path: str, params: dict):
    import requests
    r = requests.get(FAPI + path, params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def funding_interval_h(sym: str) -> dict:
    """Интервал фандинга инструмента: Binance /fapi/v1/fundingInfo перечисляет только символы с изменённым
    интервалом; нет в списке — стандартные 8 ч (разбор GPT e53a117, вопрос 1: «за 8 ч» — не свойство любой монеты)."""
    try:
        for r in _get("/fapi/v1/fundingInfo", {}):
            if r.get("symbol") == sym and r.get("fundingIntervalHours"):
                return {"hours": int(r["fundingIntervalHours"]), "source": "Binance fundingInfo"}
        return {"hours": 8, "source": "Binance fundingInfo: символа нет в списке изменённых — стандартные 8 ч"}
    except Exception as exc:                                    # noqa: BLE001
        return {"hours": None, "source": f"не прочитано: {type(exc).__name__}"}


def fetch_binance(sym: str, since: datetime) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Свечи 1ч (с объёмом агрессора) и фактические выплаты фандинга Binance с since."""
    ms = int(since.timestamp() * 1000)
    kl = _get("/fapi/v1/klines", {"symbol": sym, "interval": "1h", "startTime": ms, "limit": 1000})
    k = pd.DataFrame(kl, columns=["t", "o", "h", "l", "c", "v", "ct", "qv", "n", "tbv", "tqv", "x"])
    k.index = pd.to_datetime(k["t"], unit="ms", utc=True)
    k = k[["o", "h", "l", "c", "qv", "tqv", "ct"]].astype(float)
    k["bn_taker_delta_usd"] = 2 * k["tqv"] - k["qv"]
    k["bn_closed"] = k["ct"] < datetime.now(timezone.utc).timestamp() * 1000
    k = k.rename(columns={"o": "bn_open", "h": "bn_high", "l": "bn_low", "c": "bn_close", "qv": "bn_volume_usd"})
    fr = _get("/fapi/v1/fundingRate", {"symbol": sym, "startTime": ms, "limit": 1000})
    f = pd.DataFrame(fr)
    if not f.empty:
        f.index = pd.to_datetime(f["fundingTime"].astype("int64"), unit="ms", utc=True)
        f = pd.DataFrame({"paid_pct": f["fundingRate"].astype(float) * 100})
    return k.drop(columns=["tqv", "ct"]), f


# ─────────────────────────────── сборка ───────────────────────────────

def frame(sym: str, now: datetime | None = None, days: int = SHOW_DAYS, *, tv=None, deriv=None, liq=None,
          binance=None) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """→ (часовая таблица с прогревом, выплаты фандинга, метаданные охвата). Индекс — начало бара UTC."""
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(days=days) - timedelta(hours=WARM_H + 24)).replace(minute=0, second=0, microsecond=0)
    tv = load_tv(sym, asof=now) if tv is None else tv           # как было известно в момент now
    errors = {}
    if binance is None:
        try:
            binance = fetch_binance(sym, since)
        except Exception as exc:                                # noqa: BLE001
            errors["binance"] = f"{type(exc).__name__}: {exc}"[:160]
            binance = (pd.DataFrame(), pd.DataFrame())
    kl, paid = binance
    deriv = load_deriv(sym, since) if deriv is None else deriv
    liq = load_liq(sym, since) if liq is None else liq
    end = pd.Timestamp(now).floor("1h")
    idx = pd.date_range(pd.Timestamp(since), end, freq="1h", tz="UTC")
    df = pd.DataFrame(index=idx)
    for part in (tv, kl, deriv, liq):
        if part is not None and not part.empty:
            df = df.join(part[~part.index.duplicated(keep="last")], how="left")
    # бар CoinGlass, последняя запись которого снята до закрытия бара, — частичный: в расчёты не идёт (наступившее по
    # часам закрытие не делает старый частичный снимок окончательным)
    if "closed" in df:
        partial = df["closed"].eq(False)
        cg = [c for c in CG_COLUMNS if c in df]
        df.loc[partial, cg] = np.nan
        df["cg_partial"] = partial
    # цена — Binance REST; нет его — свечи CoinGlass (те же Binance, сверено ниже)
    for a, b in (("open", "bn_open"), ("high", "bn_high"), ("low", "bn_low"), ("close", "bn_close")):
        if b in df:
            df[f"px_{a}"] = df[b].where(df[b].notna(), df.get(a))
        else:
            df[f"px_{a}"] = df.get(a)
    meta = {"sym": sym, "built": now.isoformat(timespec="seconds"), "errors": errors,
            "paid_count": int(len(paid)), "tv_last_obs": tv["obs"].max() if not tv.empty and "obs" in tv else None,
            "funding_interval": funding_interval_h(sym) if "binance" not in errors and not kl.empty else
            {"hours": None, "source": "Binance недоступен"}}
    meta["checks"] = checks(df)
    return df, paid, meta


def checks(df: pd.DataFrame) -> dict:
    """Адресные проверки: выравнивание часа CoinGlass↔Binance, единицы фандинга, L/S CoinGlass↔наш, дубли."""
    out = {}
    if "close" in df and "bn_close" in df:
        both = df[["close", "bn_close"]].dropna()
        if len(both):
            d = (both["close"] / both["bn_close"] - 1).abs()
            out["close_cg_vs_binance"] = {"bars": int(len(both)), "max_rel_diff": float(d.max()),
                                          "share_exact": float((d < 1e-9).mean())}
            sh = (both["close"] / both["bn_close"].shift(1) - 1).abs().dropna()
            out["close_shifted_1h_max_rel_diff"] = float(sh.median()) if len(sh) else None
    if "fr_pct" in df and "fr_premium_pct" in df:
        both = df[["fr_pct", "fr_premium_pct"]].dropna()
        if len(both):
            out["funding_cg_vs_premiumIndex_pct"] = {"bars": int(len(both)),
                                                     "median_abs_diff_pp": float((both.iloc[:, 0] - both.iloc[:, 1]).abs().median())}
    if "ls_acc" in df and "ls_global" in df:
        both = df[["ls_acc", "ls_global"]].dropna()
        if len(both):
            out["ls_acc_cg_vs_binance"] = {"bars": int(len(both)),
                                           "median_abs_diff": float((both.iloc[:, 0] - both.iloc[:, 1]).abs().median())}
    out["duplicate_bars"] = int(df.index.duplicated().sum())
    return out


def _robust_z(s: pd.Series, window: int = WARM_H) -> pd.Series:
    """z против медианы и MAD предыдущих window часов (текущий час в базу не входит). Нулевой разброс — заранее
    заданная ветка (разбор GPT e53a117, вопрос 2), а не молчаливое «события нет»: MAD = 0 → средний модуль отклонения
    ×1.2533; и он 0 (ряд стоял) → значение, равное медиане, даёт 0, отличное — ±10 (необычно по определению)."""
    vals = s.to_numpy(dtype=float)
    z = np.full(len(vals), np.nan)
    for i in range(window // 2, len(vals)):
        base = vals[max(0, i - window):i]
        base = base[~np.isnan(base)]
        if len(base) < window // 2 or np.isnan(vals[i]):
            continue
        med = np.median(base)
        dev = vals[i] - med
        mad = np.median(np.abs(base - med)) * 1.4826
        if mad <= 0:
            mad = np.mean(np.abs(base - med)) * 1.2533
        if mad > 0:
            z[i] = dev / mad
        else:
            z[i] = 0.0 if dev == 0 else math.copysign(10.0, dev)
    return pd.Series(z, index=s.index)


def _spike(s: pd.Series, window: int = WARM_H) -> pd.Series:
    """Всплеск (объём, ликвидации): значение ≥ 98-го процентиля предыдущих window часов и ≥ Z «обычных» → кратность
    (до 50; это НЕ z — в подписях «кратность медианы»), иначе NaN. «Обычное» — медиана; медиана 0 (неделя почти без
    ликвидаций) → 75-й процентиль; и он 0 → любое ненулевое значение = всплеск (кратность 50). 28.10: z по логарифму
    сжимал всплески — вынос лонгов BTC 24.10 14:00 ($78M за час) давал 2.6 и эпизод не находился."""
    vals = s.to_numpy(dtype=float)
    z = np.full(len(vals), np.nan)
    for i in range(window // 2, len(vals)):
        base = vals[max(0, i - window):i]
        base = base[~np.isnan(base)]
        if len(base) < window // 2 or np.isnan(vals[i]):
            continue
        scale = np.median(base)
        if scale <= 0:
            scale = np.percentile(base, 75)
        if scale <= 0:
            if vals[i] > 0:
                z[i] = 50.0
            continue
        if vals[i] >= np.percentile(base, 98) and vals[i] / scale >= Z:
            z[i] = min(vals[i] / scale, 50.0)
    return pd.Series(z, index=s.index)


def metric_series(df: pd.DataFrame) -> pd.DataFrame:
    """Исходные ряды: доходности, всплески (как есть), уровни потоков, приросты отношений."""
    m = pd.DataFrame(index=df.index)
    m["price"] = df["px_close"].pct_change(fill_method=None)
    m["volume"] = df["volume_usd"] if "volume_usd" in df else np.nan
    m["taker"] = df.get("taker_delta")
    m["book"] = df.get("bid_ask_delta")
    m["liq_long"] = df["liq_all_long"].abs() if "liq_all_long" in df else np.nan
    m["liq_short"] = df["liq_all_short"].abs() if "liq_all_short" in df else np.nan
    m["oi"] = df["oi_coins"].pct_change(fill_method=None) if "oi_coins" in df else np.nan
    m["funding"] = df["fr_pct"].diff() if "fr_pct" in df else np.nan
    m["ls_acc"] = df["ls_acc"].diff() if "ls_acc" in df else np.nan
    m["ls_top"] = df["ls_top_pos"].diff() if "ls_top_pos" in df else np.nan
    m["wi2"] = df["wi2"].diff() if "wi2" in df else np.nan
    return m


def zscores(df: pd.DataFrame) -> pd.DataFrame:
    m = metric_series(df)
    return pd.DataFrame({k: (_spike(m[k]) if one_sided else _robust_z(m[k]))
                         for k, (_, _, one_sided) in METRICS.items()}, index=df.index)


def find_episodes(df: pd.DataFrame, z: pd.DataFrame, start: pd.Timestamp, *, min_metrics: int = 3,
                  top: int = 5, closed_before: pd.Timestamp | None = None) -> list[dict]:
    """Часы, где необычны метрики ≥min_metrics разных семейств → эпизоды (слияние при разрыве ≤ 2 ч) → top сильных."""
    zz = z[z.index >= start]
    if closed_before is not None:
        zz = zz[zz.index < closed_before]
    fam = (zz.abs() >= Z).T.groupby(lambda k: FAMILY[k]).any().T
    hot = fam.sum(axis=1) >= min_metrics
    hours = list(zz.index[hot])
    groups: list[list[pd.Timestamp]] = []
    for t in hours:
        if groups and (t - groups[-1][-1]) <= pd.Timedelta(hours=3):
            groups[-1].append(t)
        else:
            groups.append([t])
    eps = []
    for g in groups:
        sub = zz.loc[g[0]:g[-1]]
        score = float(sub.abs().clip(upper=10).where(sub.abs() >= Z).sum().sum())
        peak = sub.abs().where(sub.abs() >= Z).sum(axis=1).idxmax()
        notable = [k for k in METRICS if (sub[k].abs() >= Z).any()]
        eps.append({"start": g[0], "end": g[-1], "peak": peak, "score": round(score, 1), "metrics": notable})
    eps.sort(key=lambda e: -e["score"])
    return sorted(eps[:top], key=lambda e: e["start"])


# ─────────────────────────────── разбор эпизода ───────────────────────────────

def _v(df, col, t):
    try:
        x = df.at[t, col]
        return None if x is None or (isinstance(x, float) and math.isnan(x)) else float(x)
    except KeyError:
        return None


def _window(df, col, a, b) -> tuple[pd.Series, int]:
    """Значения ряда за календарные часы a…b включительно и сколько часов ожидалось (пропуски не заполняются)."""
    want = int((b - a) / pd.Timedelta(hours=1)) + 1
    if col not in df:
        return pd.Series(dtype=float), want
    return df[col].reindex(pd.date_range(a, b, freq="1h")), want


def _sum_cov(df, col, a, b) -> tuple[float | None, int, int]:
    """(сумма, получено часов, ожидалось часов); сумма — только по полученным, неполнота видна по счёту."""
    s, want = _window(df, col, a, b)
    got = s.dropna()
    return (float(got.sum()) if len(got) else None), int(len(got)), want


def _sum(df, col, a, b):
    """Сумма за полное календарное окно; хоть один пропуск — None (неполная сумма за полную не выдаётся)."""
    v, got, want = _sum_cov(df, col, a, b)
    return v if got == want else None


def _pct(a, b):
    return None if a in (None, 0) or b is None else (b / a - 1) * 100


def _usd(x):
    if x is None:
        return "нет данных"
    x = abs(x)
    return f"${x / 1e6:.1f}M" if x >= 1e6 else f"${x / 1e3:.0f}K"


def _n(x: float, sign: bool = False) -> str:
    """Число с пробелом между тысячами: 80 646, +1 234."""
    return (f"{x:+,.0f}" if sign else f"{x:,.0f}").replace(",", " ").replace("-", "−")


def _minus(s: str) -> str:
    """Дефис перед числом → знак минуса (−4.26%, −92.4)."""
    import re
    return re.sub(r"(?<![\w])-(?=\d)", "−", s)


def _force(x: float | None) -> str:
    """Во сколько раз больше обычного — словами и числом."""
    if x is None:
        return ""
    word = "слабее обычного" if x < 0.7 else ("как обычно" if x <= 1.5 else "сильнее обычного")
    return f" — {word} (×{x:.1f})"


def _sgn(x, eps=0.0):
    return 0 if x is None or abs(x) <= eps else (1 if x > 0 else -1)


def _fmt_t(t: pd.Timestamp) -> str:
    return f"{t.tz_convert(WARSAW):%d.%m %H:%M} Варшава ({t:%H:%M} UTC)"


def _mean_cov(df, col, a, b) -> tuple[float | None, int, int]:
    s, want = _window(df, col, a, b)
    got = s.dropna()
    return (float(got.mean()) if len(got) else None), int(len(got)), want


def hypothesis_test(df: pd.DataFrame, ref_t: pd.Timestamp, level: float | None, side: int, hours: int,
                    now: datetime | None = None) -> dict:
    """Проверка заранее записанной гипотезы «закрытия часа за уровнем не будет» по барам ref_t … ref_t+hours−1 по
    очереди: side=−1 — уровень снизу (пробой = закрытие ниже), +1 — сверху, 0 — оба края (level=(lo, hi)).
    → {"matured", "broken_at", "bars", "got"}; пропуск бара не считается удержанием."""
    h = pd.Timedelta(hours=1)
    idx = pd.date_range(ref_t, ref_t + (hours - 1) * h, freq="1h")
    matured = now is None or idx[-1] + h <= pd.Timestamp(now)
    c = df["px_close"].reindex(idx) if "px_close" in df else pd.Series(index=idx, dtype=float)
    broken = None
    for t, v in c.items():
        if now is not None and t + h > pd.Timestamp(now):
            break
        if pd.isna(v) or level is None:
            continue
        if (side < 0 and v < level) or (side > 0 and v > level) or \
                (side == 0 and (v < level[0] or v > level[1])):
            broken = t.isoformat()
            break
    return {"matured": bool(matured), "broken_at": broken, "bars": len(idx), "got": int(c.notna().sum())}


def describe(df: pd.DataFrame, ep: dict, now: datetime) -> dict:
    """Числа до/во время/после, совпадения, расхождения, описание и гипотеза. Окна — календарные, у каждой суммы
    покрытие «получено/ожидалось»; неизвестное остаётся неизвестным. «После» — только созревшее, в вывод не входит."""
    s, e = ep["start"], ep["end"]
    h = pd.Timedelta(hours=1)
    pre = s - h                                                 # закрытие часа перед эпизодом
    p0, p1 = _v(df, "px_close", pre), _v(df, "px_close", e)
    hi_s, lo_s = df.loc[s:e, "px_high"].max(), df.loc[s:e, "px_low"].min()
    hi = None if pd.isna(hi_s) else float(hi_s)
    lo = None if pd.isna(lo_s) else float(lo_s)
    d_px = _pct(p0, p1)
    d = _sgn(d_px, 0.3)
    base = df.loc[s - pd.Timedelta(hours=WARM_H):pre]
    vol, vol_got, nh = _sum_cov(df, "volume_usd", s, e)
    vol_med = float(base["volume_usd"].median()) if "volume_usd" in base and base["volume_usd"].notna().any() else None
    cov = {}
    taker, *cov["taker"] = _sum_cov(df, "taker_delta", s, e)
    taker_pre, *cov["taker_6h_before"] = _sum_cov(df, "taker_delta", s - 6 * h, pre)
    book, *cov["book"] = _mean_cov(df, "bid_ask_delta", s, e)
    book_pre, *cov["book_6h_before"] = _mean_cov(df, "bid_ask_delta", s - 6 * h, pre)
    oi0, oi1 = _v(df, "oi_coins", pre), _v(df, "oi_coins", e)
    d_oi = _pct(oi0, oi1)
    fr0, fr1 = _v(df, "fr_pct", pre), _v(df, "fr_pct", e)
    ls0, ls1 = _v(df, "ls_acc", pre), _v(df, "ls_acc", e)
    tp0, tp1 = _v(df, "ls_top_pos", pre), _v(df, "ls_top_pos", e)
    w0, w1 = _v(df, "wi2", pre), _v(df, "wi2", e)
    ll, *cov["liq_all_long"] = _sum_cov(df, "liq_all_long", s, e)
    ls_, *cov["liq_all_short"] = _sum_cov(df, "liq_all_short", s, e)
    cl, *cov["liq_coin_long"] = _sum_cov(df, "liq_coin_long", s, e)
    cs, *cov["liq_coin_short"] = _sum_cov(df, "liq_coin_short", s, e)
    ol, *cov["liq_ours_long"] = _sum_cov(df, "our_liq_long", s, e)
    os_, *cov["liq_ours_short"] = _sum_cov(df, "our_liq_short", s, e)
    full = {k: v[0] == v[1] for k, v in cov.items()}
    # в логику идут только полные окна; неизвестное (None) нулём не становится
    ll_a = abs(ll) if ll is not None and full["liq_all_long"] else None
    ls_a = abs(ls_) if ls_ is not None and full["liq_all_short"] else None
    taker_full = taker if full["taker"] else None
    nums = {
        "price": {"before": p0, "end": p1, "pct": d_px, "high": hi, "low": lo},
        "volume_x_median": (vol / vol_got / vol_med) if vol and vol_got and vol_med else None,
        "taker_delta_coins": taker, "taker_delta_6h_before": taker_pre,
        "book_delta_mean": book, "book_delta_6h_before": book_pre,
        "oi_pct": d_oi, "funding_pct": [fr0, fr1], "ls_acc": [ls0, ls1], "ls_top": [tp0, tp1], "wi2": [w0, w1],
        "liq_all_usd": [ll, ls_], "liq_coin_usd": [cl, cs], "liq_ours_usd": [ol, os_],
        "coverage": {k: list(v) for k, v in cov.items()}}
    agree, differ = [], []
    word = {1: "рост", -1: "падение", 0: "без направления"}[d]
    if taker_full is not None and d and _sgn(taker_full):
        (agree if _sgn(taker_full) == d else differ).append(
            f"чистая дельта тейкеров {_n(taker_full, True)} монет — " +
            ("агрессивнее сторона движения" if _sgn(taker_full) == d
             else "агрессивнее сторона против движения (совместимо с поглощением лимитными заявками; не установлено)"))
    if d and ll_a is not None and ls_a is not None and (ll_a or ls_a):
        dom = 1 if ls_a > 2 * ll_a else (-1 if ll_a > 2 * ls_a else 0)
        txt = f"ликвидации лонгов {_usd(ll)}, шортов {_usd(ls_)}"
        if dom == d:
            agree.append(txt + (" — преобладали ликвидации шортов на росте" if d > 0
                                else " — преобладали ликвидации лонгов на падении"))
        elif dom == -d:
            differ.append(txt + " — преобладали ликвидации той стороны, в которую шла цена")
        # без перевеса (меньше чем вдвое) — ни совпадение, ни расхождение: числа остаются в «Числах»
    if ls0 is not None and ls1 is not None and d:
        dl = ls1 - ls0
        if _sgn(dl, 0.01) == -d:
            agree.append(f"толпа L/S {ls0:.2f}→{ls1:.2f} — зеркало цены (обычное поведение, корреляция −0.69)")
        elif _sgn(dl, 0.01) == d:
            differ.append(f"толпа L/S {ls0:.2f}→{ls1:.2f} — пошла за ценой, это необычно")
    if None not in (ls0, ls1, w0, w1):
        if _sgn(w1 - w0, 2) and _sgn(ls1 - ls0, 0.01) and _sgn(w1 - w0, 2) != _sgn(ls1 - ls0, 0.01):
            differ.append(f"Whale Index 2 {w0:+.1f}→{w1:+.1f} против толпы {ls0:.2f}→{ls1:.2f}")
        elif _sgn(w1 - w0, 2) and _sgn(w1 - w0, 2) == _sgn(ls1 - ls0, 0.01):
            agree.append(f"Whale Index 2 {w0:+.1f}→{w1:+.1f} в ту же сторону, что толпа")
    if None not in (fr0, fr1) and d and _sgn(fr1 - fr0, 0.0005):
        (agree if _sgn(fr1 - fr0, 0.0005) == d else differ).append(
            f"фандинг {fr0:.4f}%→{fr1:.4f}% " + ("вслед за ценой" if _sgn(fr1 - fr0, 0.0005) == d else "против цены"))
    if nums["book_delta_mean"] is not None and nums["book_delta_6h_before"] is not None and d:
        db = nums["book_delta_mean"] - nums["book_delta_6h_before"]
        if _sgn(db) == -d:
            differ.append(f"стакан ±1% (заявки, не сделки): перевес {'на покупку' if db > 0 else 'на продажу'} "
                          f"вырос на {_n(abs(db))} монет — заявки против движения")
    main, alt, watch, cancel = (_minus(x) for x in explain(d, d_px, d_oi, hi, lo, ll_a, ls_a, taker_full, ls0, ls1))
    agree, differ = [_minus(x) for x in agree], [_minus(x) for x in differ]
    level, side = hypothesis_of(d, hi, lo)
    after = {}
    for hrs in (6, 24):
        t = e + pd.Timedelta(hours=hrs)
        if t + h <= pd.Timestamp(now):
            pa = _v(df, "px_close", t)
            hyp = hypothesis_test(df, e + h, level, side, hrs, now)
            after[f"{hrs}h"] = {"price_pct": _pct(p1, pa), "oi_pct": _pct(oi1, _v(df, "oi_coins", t)),
                                "first_close_beyond": hyp["broken_at"], "bars_got": hyp["got"]}
        else:
            after[f"{hrs}h"] = None
    return {"start": s.isoformat(), "end": e.isoformat(), "hours": nh, "when": _fmt_t(s), "score": ep["score"],
            "metrics": [METRICS[k][0] for k in ep["metrics"]], "direction": word, "numbers": nums,
            "agree": agree, "differ": differ, "main": main, "alt": alt, "watch": watch, "cancel": cancel,
            "hypothesis": {"level": level, "side": side, "hours": 24}, "phases": phases(df, s, e), "after": after}


def phases(df: pd.DataFrame, s: pd.Timestamp, e: pd.Timestamp) -> dict:
    """Каждый час эпизода (цена к прошлому закрытию, чистая дельта тейкеров, OI Binance к прошлому часу, ликвидации
    всех бирж) и фазы: граница — смена знака хода цены (порог 0.1%) или агрессора. OI — характеристика фазы, не
    граница; порядок внутри часа не придумывается (разбор GPT e53a117, вопрос 3)."""
    h = pd.Timedelta(hours=1)
    rows = []
    for t in pd.date_range(s, e, freq="1h"):
        pc = _pct(_v(df, "px_close", t - h), _v(df, "px_close", t))
        tk = _v(df, "taker_delta", t)
        rows.append({"t": t.isoformat(), "price_pct": pc, "close": _v(df, "px_close", t), "taker": tk,
                     "oi_pct": _pct(_v(df, "oi_coins", t - h), _v(df, "oi_coins", t)),
                     "liq_long": None if _v(df, "liq_all_long", t) is None else abs(_v(df, "liq_all_long", t)),
                     "liq_short": None if _v(df, "liq_all_short", t) is None else abs(_v(df, "liq_all_short", t)),
                     "key": (_sgn(pc, 0.1), _sgn(tk))})
    segs = []
    for r in rows:
        if segs and segs[-1]["key"] == r["key"]:
            segs[-1]["hours"].append(r)
        else:
            segs.append({"key": r["key"], "hours": [r]})
    out = []
    for g in segs:
        hs = g["hours"]
        pmove, agg = g["key"]
        oi = [x["oi_pct"] for x in hs if x["oi_pct"] is not None]
        tk = [x["taker"] for x in hs if x["taker"] is not None]
        out.append({"from": hs[0]["t"], "to": hs[-1]["t"], "hours": len(hs),
                    "label": {1: "цена вверх", -1: "цена вниз", 0: "цена на месте"}[pmove] + ", агрессивнее "
                             + {1: "покупатели", -1: "продавцы", 0: "никто"}[agg],
                    "taker": sum(tk) if len(tk) == len(hs) else None,
                    "oi_pct": (float(np.prod([1 + x / 100 for x in oi])) - 1) * 100 if len(oi) == len(hs) else None,
                    "liq_long": sum(x["liq_long"] or 0 for x in hs) if all(x["liq_long"] is not None for x in hs) else None,
                    "liq_short": sum(x["liq_short"] or 0 for x in hs) if all(x["liq_short"] is not None for x in hs) else None})
    for r in rows:
        r.pop("key")
    return {"hours": rows, "phases": out, "note": "OI — Binance, ликвидации и тейкеры — все биржи CoinGlass: охват разный"}


OI_SMALL = 0.15                                                 # % за эпизод: меньше — «почти не изменился»


def hypothesis_of(d: int, hi, lo):
    """Гипотеза о продолжении на 24 ч: экстремум эпизода не будет обновлён закрытием часа (падение — минимум снизу,
    рост — максимум сверху, без направления — оба края)."""
    if d < 0:
        return lo, -1
    if d > 0:
        return hi, 1
    return (None if None in (lo, hi) else (lo, hi)), 0


def explain(d, d_px, d_oi, hi, lo, ll, ls, taker, ls0, ls1):
    """→ (наблюдение и совместимое объяснение, альтернатива, гипотеза на 24 ч, условие смены сценария).
    Только наблюдаемое: OI — число открытых контрактов, у каждого есть покупатель и продавец, поэтому сторону нового
    инициатора OI не устанавливает (определение CME). OI неизвестен / почти не изменился — отдельные ветки;
    неизвестные ликвидации остаются «нет данных». Прошлый механизм будущим движением не отменяется — проверяется
    заранее записанная гипотеза со сроком."""
    oi = None if d_oi is None else (0 if abs(d_oi) < OI_SMALL else (1 if d_oi > 0 else -1))
    oi_t = "OI: нет данных" if d_oi is None else f"OI {d_oi:+.2f}%"
    liq_t = f"ликвидации лонгов {_usd(ll)}, шортов {_usd(ls)}"
    tk_t = (f"чистая дельта тейкеров {_n(taker, True)} монет" if taker is not None
            else "дельта тейкеров за эпизод неполная")
    crowd = "" if None in (ls0, ls1) else f" (толпа L/S {ls0:.2f}→{ls1:.2f})"
    lo_t = _n(lo) if lo is not None else "нет данных"
    hi_t = _n(hi) if hi is not None else "нет данных"
    dom = None if ll is None or ls is None else (1 if ls > 2 * ll else (-1 if ll > 2 * ls else 0))
    if d == 0:
        return (f"Всплеск без направления цены: диапазон {lo_t}–{hi_t}, {oi_t}, {liq_t}, {tk_t}. Активны обе "
                "стороны; кто преобладал, эти агрегаты не устанавливают.",
                "Возможны и вынос стопов в обе стороны, и смена агрессора внутри часа — по часовым данным не различить.",
                f"Гипотеза на 24 ч: ни один час не закроется вне диапазона {lo_t}–{hi_t}.",
                f"Закрытие часа вне {lo_t}–{hi_t} в течение 24 ч — сценарий сменился на выход из диапазона.")
    up = d > 0
    obs = f"Цена {d_px:+.2f}%, {oi_t}, {liq_t}, {tk_t}."
    gone, other = ("шортов", "лонгов") if up else ("лонгов", "шортов")
    if oi is None:
        comp = " Без OI механизм по позициям не оценить."
        alt = "—"
    elif oi < 0:
        forced = ", в том числе принудительным" if dom == d else ""
        comp = f" Картина совместима с закрытием {gone}{forced}."
        alt = (f"Фиксация прибыли {other} тоже снижает OI; кто закрывал, OI не показывает.")
    elif oi > 0:
        comp = (f" Открытая экспозиция росла на {'росте' if up else 'падении'}; сторону инициатора OI не "
                "устанавливает" + (" — агрессивнее были " + ("покупатели" if taker > 0 else "продавцы")
                                  if taker else "") + ".")
        alt = f"Набор {'шортов' if up else 'лонгов'} против движения тоже растит OI{crowd}."
    else:
        comp = f" OI почти не изменился (меньше {OI_SMALL}%): позиции в основном переходили из рук в руки."
        alt = (f"Одновременное закрытие {gone} и открытие новых позиций даёт тот же нулевой итог OI.")
    lvl = hi_t if up else lo_t
    return (obs + comp, alt,
            f"Гипотеза на 24 ч: {'максимум' if up else 'минимум'} эпизода {lvl} не будет обновлён закрытием часа.",
            f"Закрытие часа {'выше' if up else 'ниже'} {lvl} в течение 24 ч — сценарий сменился на продолжение "
            f"{'роста' if up else 'падения'} (прошлое описание это не отменяет).")


# ─────────────────────────────── «что сейчас» ───────────────────────────────

def strength(series: pd.Series, at: pd.Timestamp, hours: int) -> dict:
    """Сумма за последние hours КАЛЕНДАРНЫХ закрытых часов (бары at−hours … at−1 ч) и во сколько раз она больше
    обычной по модулю (медиана |сумм за hours| по полным окнам предыдущих 7 суток, текущее окно не входит).
    → {"sum", "got", "want", "x", "base_n"}; sum и x — None, если окно неполное (видно «есть got из want»)."""
    h = pd.Timedelta(hours=1)
    idx = pd.date_range(at - (WARM_H + hours) * h, at - h, freq="1h")
    s = series.reindex(idx)
    cur = s.iloc[-hours:]
    got = int(cur.notna().sum())
    out = {"sum": None, "got": got, "want": hours, "x": None, "base_n": 0,
           "partial_sum": float(cur.sum()) if got else None}
    if got < hours:
        return out
    out["sum"] = float(cur.sum())
    roll = s.rolling(hours, min_periods=hours).sum().iloc[:-hours]   # окна, кончающиеся до текущего окна
    base = roll.dropna().abs()
    out["base_n"] = int(len(base))
    if len(base) >= WARM_H // 2 and base.median() > 0:
        out["x"] = abs(out["sum"]) / float(base.median())
    return out


def _at_hour(df, col, t) -> float | None:
    """Значение ровно за календарный час t (бар с началом t) или None — без подмены соседним."""
    return _v(df, col, t) if col in df else None


def now_summary(df: pd.DataFrame, now: datetime, coin: str) -> list[str]:
    """Чья сторона агрессивнее и насколько сильнее обычного — по закрытым календарным часам; неполное окно показано
    как «есть k из n», без вывода о силе; «сейчас» — последний закрытый час, «24 ч назад» — ровно тот же час сутки
    назад."""
    at = pd.Timestamp(now).floor("1h")
    h = pd.Timedelta(hours=1)
    last_bar = at - h
    out = []
    for hrs in (6, 24):
        st = strength(df.get("taker_delta", pd.Series(dtype=float)), at, hrs)
        if st["sum"] is not None:
            who = "покупатели" if st["sum"] > 0 else "продавцы"
            out.append(f"Чистая дельта тейкеров {hrs} ч: {_n(st['sum'], True)} {coin} — агрессивнее {who}"
                       f"{_force(st['x'])}")
        elif st["got"]:
            out.append(f"Чистая дельта тейкеров {hrs} ч: есть {st['got']} из {hrs} ч (по ним "
                       f"{_n(st['partial_sum'], True)} {coin}) — окно неполное, силу не оцениваю")
        else:
            out.append(f"Чистая дельта тейкеров {hrs} ч: нет данных")
    if "bid_ask_delta" in df:
        v = _at_hour(df, "bid_ask_delta", last_bar)
        base = df["bid_ask_delta"].reindex(pd.date_range(last_bar - WARM_H * h, last_bar - h, freq="1h")).dropna()
        if v is None:
            out.append("Стакан ±1% (заявки): за последний закрытый час нет данных")
        elif len(base) >= WARM_H // 2:
            med = float(base.abs().median())
            out.append(f"Стакан ±1% (заявки, не сделки): {'на покупку' if v > 0 else 'на продажу'} больше на "
                       f"{_n(abs(v))} {coin}{_force(abs(v) / med if med else None)}")
    ll = strength(df["liq_all_long"].abs() if "liq_all_long" in df else pd.Series(dtype=float), at, 24)
    ls = strength(df["liq_all_short"].abs() if "liq_all_short" in df else pd.Series(dtype=float), at, 24)
    if ll["sum"] is not None and ls["sum"] is not None:
        out.append(f"Ликвидации 24 ч: лонги {_usd(ll['sum'])}" + (f" (×{ll['x']:.1f} к обычным суткам)" if ll["x"] else "")
                   + f", шорты {_usd(ls['sum'])}" + (f" (×{ls['x']:.1f})" if ls["x"] else ""))
    elif ll["got"] or ls["got"]:
        out.append(f"Ликвидации 24 ч: есть {min(ll['got'], ls['got'])} из 24 ч — окно неполное")
    for col, name, fmt in (("ls_acc", "Толпа L/S", "{:.2f}"), ("wi2", "Whale Index 2", "{:+.1f}"),
                           ("fr_pct", "Фандинг", "{:.4f}%")):
        if col not in df:
            continue
        cur, ago = _at_hour(df, col, last_bar), _at_hour(df, col, last_bar - 24 * h)
        if cur is None:
            s = df[col].dropna()
            s = s[s.index < at]
            age = int((last_bar - s.index[-1]) / h) if len(s) else None
            out.append(f"{name}: за последний закрытый час нет данных" +
                       (f" (последнее значение {age} ч назад)" if age is not None else ""))
            continue
        out.append((f"{name} {fmt.format(cur)} (24 ч назад " +
                    (fmt.format(ago) if ago is not None else "нет данных") + ")").replace("-", "−"))
    return out


# ─────────────────────────────── совокупность «3 из 4» ───────────────────────────────

COMP = ("bid_ask_delta", "fr_pct", "ls_acc", "wi2")


def _slope_sign(v: np.ndarray) -> int:
    if len(v) < 2 or np.isnan(v).any():
        return 0
    t = np.arange(len(v), dtype=float) - (len(v) - 1) / 2
    return int(np.sign(np.dot(t, v - v.mean())))


def composite(df: pd.DataFrame, at: pd.Timestamp, n: int = 72) -> dict | None:
    """Знаки наклона за n КАЛЕНДАРНЫХ часов (бары at−n … at−1 ч, все закрыты к at) по 4 линиям скрина оператора.
    Вывод — не меньше трёх НЕНУЛЕВЫХ наклонов одного знака (разбор GPT e53a117, вопрос 5): два плюса и два нуля — не
    три согласные линии; при четырёх ненулевых это то же, что |S| ≥ 2. Хоть один пропуск в окне — None."""
    idx = pd.date_range(at - pd.Timedelta(hours=n), at - pd.Timedelta(hours=1), freq="1h")
    if any(c not in df for c in COMP):
        return None
    win = df[list(COMP)].reindex(idx)
    if win.isna().any().any():
        return None
    signs = {c: _slope_sign(win[c].to_numpy(dtype=float)) for c in COMP}
    pos = sum(1 for v in signs.values() if v > 0)
    neg = sum(1 for v in signs.values() if v < 0)
    call = 1 if pos >= 3 else (-1 if neg >= 3 else 0)
    return {"signs": signs, "S": int(sum(signs.values())), "pos": pos, "neg": neg,
            "zero": len(COMP) - pos - neg, "call": call}


# ─────────────────────────────── журнал эпизодов и проверка вперёд ───────────────────────────────

def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


EP_VERSION = "ep-2"
EP_MERGE_H = 3                                                  # горячие часы с разрывом ≤ 3 ч — один эпизод
EP_KINDS = ("open", "update", "final")


def _write(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, default=float) + "\n")


def log_episodes(sym: str, df: pd.DataFrame, z: pd.DataFrame, now: datetime, path: Path = EPISODES) -> int:
    """Эпизоды с неизменным ID и записями open → update → final (разбор GPT e53a117, P1: раньше ключом было только
    начало, запись не обновлялась, а исход считался от заново выделенного конца).
    - open — сразу, как закрылся первый час эпизода; оценивается от СВОЕГО времени: цена последнего закрытого часа на
      момент записи;
    - update — группа расширилась (новый горячий час в пределах слияния): новая запись, прежние не меняются;
    - final — прошли все EP_MERGE_H часов слияния без новых горячих: границы окончательны; оценивается от конца
      эпизода (описательно — запись сделана позже конца, это видно по fixed_after_end_h).
    Исходы 6/24 ч — отдельные записи со ссылкой на запись (id|вид|время), считаются только по сохранённым в ней
    полям (время и цена отсчёта, уровень гипотезы) и только для записей, лежавших в журнале до этого прогона."""
    have = [r for r in _read_jsonl(path) if r.get("sym") == sym and r.get("v") == EP_VERSION]
    last = {r["id"]: r for r in have if r.get("kind") in EP_KINDS}
    done = {(r["ref"], r["h"]) for r in have if r.get("kind") == "outcome"}
    T = pd.Timestamp(now)
    closed = T.floor("1h")                                      # бары с началом < closed закрыты
    h = pd.Timedelta(hours=1)
    eps = find_episodes(df, z, closed - pd.Timedelta(days=SHOW_DAYS), closed_before=closed, top=10 ** 6)
    rows = []
    for ep in eps:
        eid = f"{sym}:{ep['start']:%Y-%m-%dT%H}"
        prev = last.get(eid)
        final = ep["end"] + EP_MERGE_H * h < closed              # часы end+1 … end+3 закрыты и не горячие
        if prev is not None and (prev["kind"] == "final" or (prev["end"] == ep["end"].isoformat() and not final)):
            continue
        kind = "final" if final else ("update" if prev else "open")
        info = describe(df, ep, now)
        ref_t = ep["end"] + h if kind == "final" else closed
        rows.append({"kind": kind, "v": EP_VERSION, "id": eid, "sym": sym,
                     "fixed_at": T.isoformat(timespec="seconds"), "ref_time": ref_t.isoformat(),
                     "ref_price": _v(df, "px_close", ref_t - h), "ref_oi": _v(df, "oi_coins", ref_t - h),
                     "fixed_after_end_h": round((T - ep["end"] - h).total_seconds() / 3600, 1),
                     **{k: v for k, v in info.items() if k != "after"}})
    for r in have:
        if r.get("kind") not in EP_KINDS:
            continue
        ref = f"{r['id']}|{r['kind']}|{r['fixed_at']}"
        t0 = pd.Timestamp(r["ref_time"])
        hyp = r.get("hypothesis") or {}
        for hrs in (6, 24):
            if (ref, f"{hrs}h") in done or t0 + hrs * h > closed:
                continue
            t_end = t0 + (hrs - 1) * h                          # закрытие этого бара — момент t0 + hrs
            pa = _v(df, "px_close", t_end)
            test = hypothesis_test(df, t0, hyp.get("level"), hyp.get("side", 0), hrs, now)
            rows.append({"kind": "outcome", "v": EP_VERSION, "sym": sym, "ref": ref, "h": f"{hrs}h",
                         "checked_at": T.isoformat(timespec="seconds"), "ref_time": r["ref_time"],
                         "ref_price": r.get("ref_price"), "price_at_end": pa, "ret_pct": _pct(r.get("ref_price"), pa),
                         "oi_pct": _pct(r.get("ref_oi"), _v(df, "oi_coins", t_end)),
                         "hyp_broken_at": test["broken_at"], "bars_got": test["got"], "bars": test["bars"]})
    _write(path, rows)
    return sum(1 for r in rows if r["kind"] != "outcome")


COMP_VERSION = "comp-2"
COMP_SLOT = (6, 8)          # решение — первый прогон сборщика с 06:00 до 08:00 UTC (после штатного сбора 07–09 Варшавы)
COMP_N, COMP_H = 72, 24


def binance_open_at(sym: str, t) -> float | None:
    """Цена открытия минуты t (Binance USDT-M, 1m kline с началом ровно t) — известна только после t."""
    ms = int(pd.Timestamp(t).timestamp() * 1000)
    kl = _get("/fapi/v1/klines", {"symbol": sym, "interval": "1m", "startTime": ms, "limit": 1})
    if kl and int(kl[0][0]) == ms:
        return float(kl[0][1])
    return None


def _snapshot(df: pd.DataFrame, at: pd.Timestamp, n: int) -> str:
    """Отпечаток значений окна решения: тот же sha — те же входы."""
    import hashlib
    idx = pd.date_range(at - pd.Timedelta(hours=n), at - pd.Timedelta(hours=1), freq="1h")
    win = df[list(COMP)].reindex(idx)
    blob = json.dumps([[None if pd.isna(v) else float(f"{v:.8g}") for v in row] for row in win.to_numpy()])
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def log_composite(sym: str, df: pd.DataFrame, now: datetime, path: Path = COMPOSITE, *,
                  available_at: str | None = None, price_at=None) -> dict:
    """«3 из 4 → сутки», версия comp-2 (разбор GPT e53a117, P1: comp-1 записывал прогноз «на 00:00» в 06:02 с ценой
    00:00 — первые часы дня попадали в исход решения, которого тогда ещё не было).
    - Решение принимается в момент запуска T, только в окне COMP_SLOT UTC, раз в сутки; признаки — бары, закрытые к T,
      и выгрузка CoinGlass не позже T (frame(..., now=T)); feature_cutoff — конец последнего бара окна.
    - Исполнение — открытие следующей полной минуты после T по Binance; горизонт — +24 ч от исполнения. Цена входа и
      выхода берутся после горизонта по свечам 1m, задержка решения и исполнения входит в результат.
    - Нет прогона в окне — запись skip; задним числом решение не восстанавливается.
    → {"call": запись решения | None, "outcomes": записано исходов}."""
    price_at = price_at or binance_open_at
    have = [r for r in _read_jsonl(path) if r.get("sym") == sym and r.get("v") == COMP_VERSION]
    T = pd.Timestamp(now)
    day = T.strftime("%Y-%m-%d")
    seen = {r["day"] for r in have if r.get("kind") in ("call", "skip")}
    done = {r["day"] for r in have if r.get("kind") == "outcome"}
    calls = [r for r in have if r.get("kind") == "call"]
    rows, made = [], None
    head = {"v": COMP_VERSION, "sym": sym, "day": day, "decision_at": T.isoformat(timespec="seconds")}
    if day not in seen and T.hour >= COMP_SLOT[0]:
        if T.hour < COMP_SLOT[1]:
            at = T.floor("1h")
            c = composite(df, at, COMP_N)
            if c is None:
                rows.append({"kind": "skip", **head, "reason": "в окне 72 ч есть пропуски или незакрытые бары"})
            else:
                exe = T.floor("1min") + pd.Timedelta(minutes=1)
                made = {"kind": "call", **head, "feature_cutoff": at.isoformat(), "available_at": available_at,
                        "execution_at": exe.isoformat(), "horizon_end": (exe + pd.Timedelta(hours=COMP_H)).isoformat(),
                        "rule": {"n_h": COMP_N, "horizon_h": COMP_H, "min_agree": 3, "slot_utc": list(COMP_SLOT)},
                        "snapshot": _snapshot(df, at, COMP_N), **c}
                rows.append(made)
                calls.append(made)
        else:
            rows.append({"kind": "skip", **head, "reason": "нет прогона 06–08 UTC — решение задним числом не "
                                                           "восстанавливается"})
    for c in calls:
        end = pd.Timestamp(c["horizon_end"])
        if c["day"] in done or end + pd.Timedelta(minutes=2) > T:
            continue
        try:
            p0, p1 = price_at(sym, pd.Timestamp(c["execution_at"])), price_at(sym, end)
        except Exception:                                       # noqa: BLE001 — сеть: попробуем в следующий прогон
            continue
        if p0 is None or p1 is None:
            continue
        ret = (p1 / p0 - 1) * 100
        rows.append({"kind": "outcome", "v": COMP_VERSION, "sym": sym, "day": c["day"],
                     "checked_at": T.isoformat(timespec="seconds"), "entry_at": c["execution_at"], "entry_price": p0,
                     "exit_at": c["horizon_end"], "exit_price": p1, "ret_24h_pct": ret,
                     "hit": (None if not c["call"] else bool(np.sign(ret) == c["call"]))})
    _write(path, rows)
    return {"call": made, "outcomes": sum(1 for r in rows if r["kind"] == "outcome")}


def log_all(now: datetime | None = None) -> dict:
    """Каждый час из сборщика CoinGlass: эпизоды, совокупность и теневые сценарии в журналы."""
    from services.coinglass_web import scenarios
    now = now or datetime.now(timezone.utc)
    out = {}
    for sym in SYMBOLS:
        try:
            df, _paid, meta = frame(sym, now)
            out[sym] = {"episodes": log_episodes(sym, df, zscores(df), now)}
            out[sym]["composite"] = bool(log_composite(sym, df, now, available_at=meta.get("tv_last_obs"))["call"])
            out[sym]["scenarios"] = scenarios.update(sym, df, now, available_at=meta.get("tv_last_obs"))
        except Exception as exc:                                # noqa: BLE001
            out[sym] = f"{type(exc).__name__}: {exc}"[:200]
    return out


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    if not n:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return c - m, c + m


def composite_stats(sym: str, path: Path | None = None) -> dict:
    """Счёт вперёд версии comp-2 (записи comp-1 с ошибкой времени не входят)."""
    rows = [r for r in _read_jsonl(path or COMPOSITE) if r.get("sym") == sym and r.get("v") == COMP_VERSION]
    hits = [r["hit"] for r in rows if r.get("kind") == "outcome" and r.get("hit") is not None]
    k = sum(hits)
    return {"n": len(hits), "hit": (k / len(hits)) if hits else None, "ci95": wilson(k, len(hits)),
            "calls": sum(1 for r in rows if r.get("kind") == "call"),
            "skips": sum(1 for r in rows if r.get("kind") == "skip"), "version": COMP_VERSION}
