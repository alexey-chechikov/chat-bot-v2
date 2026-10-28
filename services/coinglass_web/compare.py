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
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

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
    tv = load_tv(sym) if tv is None else tv
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
    # цена — Binance REST; нет его — свечи CoinGlass (те же Binance, сверено ниже)
    for a, b in (("open", "bn_open"), ("high", "bn_high"), ("low", "bn_low"), ("close", "bn_close")):
        if b in df:
            df[f"px_{a}"] = df[b].where(df[b].notna(), df.get(a))
        else:
            df[f"px_{a}"] = df.get(a)
    meta = {"sym": sym, "built": now.isoformat(timespec="seconds"), "errors": errors,
            "paid_count": int(len(paid)), "tv_last_obs": tv["obs"].max() if not tv.empty else None}
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
    """z против медианы и MAD предыдущих window часов (текущий час в базу не входит)."""
    vals = s.to_numpy(dtype=float)
    z = np.full(len(vals), np.nan)
    for i in range(window // 2, len(vals)):
        base = vals[max(0, i - window):i]
        base = base[~np.isnan(base)]
        if len(base) < window // 2 or np.isnan(vals[i]):
            continue
        med = np.median(base)
        mad = np.median(np.abs(base - med)) * 1.4826
        if mad > 0:
            z[i] = (vals[i] - med) / mad
    return pd.Series(z, index=s.index)


def _spike(s: pd.Series, window: int = WARM_H) -> pd.Series:
    """Всплеск (объём, ликвидации): значение ≥ 98-го процентиля предыдущих window часов и ≥ Z медиан → «z» = во
    сколько раз больше медианы (до 50), иначе NaN. 28.10: z по логарифму сжимал всплески — вынос лонгов BTC 24.10
    14:00 ($78M за час) давал 2.6 и эпизод не находился."""
    vals = s.to_numpy(dtype=float)
    z = np.full(len(vals), np.nan)
    for i in range(window // 2, len(vals)):
        base = vals[max(0, i - window):i]
        base = base[~np.isnan(base)]
        if len(base) < window // 2 or np.isnan(vals[i]):
            continue
        med = np.median(base)
        if med > 0 and vals[i] >= np.percentile(base, 98) and vals[i] / med >= Z:
            z[i] = min(vals[i] / med, 50.0)
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


def _sum(df, col, a, b):
    if col not in df:
        return None
    s = df.loc[a:b, col].dropna()
    return float(s.sum()) if len(s) else None


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


def describe(df: pd.DataFrame, ep: dict, now: datetime) -> dict:
    """Числа до/во время/после, совпадения, расхождения, объяснения. «После» — только созревшее, в выводе не участвует."""
    s, e = ep["start"], ep["end"]
    h = pd.Timedelta(hours=1)
    pre = s - h                                                 # закрытие часа перед эпизодом
    p0, p1 = _v(df, "px_close", pre), _v(df, "px_close", e)
    hi = float(df.loc[s:e, "px_high"].max())
    lo = float(df.loc[s:e, "px_low"].min())
    d_px = _pct(p0, p1)
    d = _sgn(d_px, 0.3)
    base = df.loc[s - pd.Timedelta(hours=WARM_H):pre]
    vol = _sum(df, "volume_usd", s, e)
    vol_med = float(base["volume_usd"].median()) if "volume_usd" in base and base["volume_usd"].notna().any() else None
    nh = int((e - s) / h) + 1
    taker = _sum(df, "taker_delta", s, e)
    taker_pre = _sum(df, "taker_delta", s - 6 * h, pre)
    book = df.loc[s:e, "bid_ask_delta"].mean() if "bid_ask_delta" in df else None
    book_pre = df.loc[s - 6 * h:pre, "bid_ask_delta"].mean() if "bid_ask_delta" in df else None
    oi0, oi1 = _v(df, "oi_coins", pre), _v(df, "oi_coins", e)
    d_oi = _pct(oi0, oi1)
    fr0, fr1 = _v(df, "fr_pct", pre), _v(df, "fr_pct", e)
    ls0, ls1 = _v(df, "ls_acc", pre), _v(df, "ls_acc", e)
    tp0, tp1 = _v(df, "ls_top_pos", pre), _v(df, "ls_top_pos", e)
    w0, w1 = _v(df, "wi2", pre), _v(df, "wi2", e)
    ll, ls_ = _sum(df, "liq_all_long", s, e), _sum(df, "liq_all_short", s, e)
    cl, cs = _sum(df, "liq_coin_long", s, e), _sum(df, "liq_coin_short", s, e)
    ol, os_ = _sum(df, "our_liq_long", s, e), _sum(df, "our_liq_short", s, e)
    ll_a, ls_a = abs(ll or 0), abs(ls_ or 0)
    nums = {
        "price": {"before": p0, "end": p1, "pct": d_px, "high": hi, "low": lo},
        "volume_x_median": (vol / nh / vol_med) if vol and vol_med else None,
        "taker_delta_coins": taker, "taker_delta_6h_before": taker_pre,
        "book_delta_mean": None if book is None or pd.isna(book) else float(book),
        "book_delta_6h_before": None if book_pre is None or pd.isna(book_pre) else float(book_pre),
        "oi_pct": d_oi, "funding_pct": [fr0, fr1], "ls_acc": [ls0, ls1], "ls_top": [tp0, tp1], "wi2": [w0, w1],
        "liq_all_usd": [ll, ls_], "liq_coin_usd": [cl, cs], "liq_ours_usd": [ol, os_]}
    agree, differ = [], []
    word = {1: "рост", -1: "падение", 0: "без направления"}[d]
    if taker is not None and d:
        (agree if _sgn(taker) == d else differ).append(
            f"тейкеры {_n(taker, True)} монет — " + ("агрессор в сторону движения" if _sgn(taker) == d
                                                     else "агрессор против движения: лимитные заявки поглощали"))
    if d and (ll_a or ls_a):
        dom = 1 if ls_a > 2 * ll_a else (-1 if ll_a > 2 * ls_a else 0)
        txt = f"ликвидации лонгов {_usd(ll)}, шортов {_usd(ls_)}"
        if dom == d:
            agree.append(txt + (" — выбивало шортов на росте" if d > 0 else " — выбивало лонгов на падении"))
        elif dom == -d:
            differ.append(txt + " — выбивало сторону, по которой цена шла")
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
            differ.append(f"стакан ±1%: перевес {'заявок на покупку' if db > 0 else 'заявок на продажу'} вырос "
                          f"на {_n(abs(db))} монет — лимитники стояли против движения")
    main, alt, watch, cancel = (_minus(x) for x in explain(d, d_oi, p0, hi, lo, oi0, ll_a, ls_a, taker, ls0, ls1))
    agree, differ = [_minus(x) for x in agree], [_minus(x) for x in differ]
    after = {}
    for hrs in (6, 24):
        t = e + pd.Timedelta(hours=hrs)
        if t + h <= pd.Timestamp(now):
            pa = _v(df, "px_close", t)
            after[f"{hrs}h"] = {"price_pct": _pct(p1, pa), "oi_pct": _pct(oi1, _v(df, "oi_coins", t)),
                                "new_low": bool(df.loc[e + h:t, "px_low"].min() < lo),
                                "new_high": bool(df.loc[e + h:t, "px_high"].max() > hi)}
        else:
            after[f"{hrs}h"] = None
    return {"start": s.isoformat(), "end": e.isoformat(), "hours": nh, "when": _fmt_t(s), "score": ep["score"],
            "metrics": [METRICS[k][0] for k in ep["metrics"]], "direction": word, "numbers": nums,
            "agree": agree, "differ": differ, "main": main, "alt": alt, "watch": watch, "cancel": cancel,
            "after": after}


def explain(d, d_oi, p0, hi, lo, oi0, ll, ls, taker, ls0, ls1):
    """Основное и альтернативное объяснение по направлению цены, OI и перевесу ликвидаций. Кто открыл/закрыл —
    по OI не определить: это описание совместимых версий, не установленный факт."""
    oi = _sgn(d_oi, 0.15)
    oi_t = "нет данных" if d_oi is None else f"{d_oi:+.2f}%"
    crowd = "" if None in (ls0, ls1) else f" (толпа L/S {ls0:.2f}→{ls1:.2f})"
    tk = f", тейкеры {_n(taker, True)} монет." if taker else "."
    p0_t = _n(p0) if p0 is not None else "нет данных"
    if d < 0 and oi < 0:
        return (f"Закрытие лонгов: цена вниз, OI {oi_t}, ликвидации лонгов {_usd(ll)}.",
                "Добровольные продажи лонгов без принуждения — если ликвидации малы против объёма.",
                f"Держится ли минимум эпизода {_n(lo)}; перестаёт ли падать OI.",
                f"Новый минимум ниже {_n(lo)} при росте OI — давят новые шорты, а не выход лонгов.")
    if d < 0:
        return (f"Новые продавцы: цена вниз при OI {oi_t}{tk}",
                f"Лонги набирают на падении{crowd} — по OI не отличить, кто открыл.",
                f"Растёт ли OI дальше вместе с падением; уровень начала эпизода {p0_t}.",
                f"Возврат выше {p0_t} при падающем OI — шорты закрываются (выжимание).")
    if d > 0 and oi < 0:
        return (f"Закрытие шортов: цена вверх, OI {oi_t}, ликвидации шортов {_usd(ls)}.",
                "Фиксация прибыли лонгами тоже снижает OI — если рост без ликвидаций шортов.",
                f"Держится ли максимум эпизода {_n(hi)}; перестаёт ли падать OI.",
                f"Новый максимум выше {_n(hi)} при росте OI — тянут новые лонги, а не выход шортов.")
    if d > 0:
        return (f"Новые покупатели: цена вверх при OI {oi_t}{tk}",
                f"Шорты открываются в рост{crowd} — по OI не отличить, кто открыл.",
                f"Растёт ли OI дальше вместе с ценой; уровень начала эпизода {p0_t}.",
                f"Возврат ниже {p0_t} при падающем OI — новые лонги вышли.")
    return (f"Всплеск без направления цены (OI {oi_t}): ликвидации лонгов {_usd(ll)}, шортов {_usd(ls)}.",
            "Крупный участник прошёл через стакан, цена вернулась — обе стороны встретились.",
            f"Выход из диапазона эпизода {_n(lo)}–{_n(hi)}.",
            "Объяснение отменяет выход за диапазон эпизода с объёмом выше эпизодного.")


# ─────────────────────────────── «что сейчас» ───────────────────────────────

def strength(series: pd.Series, at: pd.Timestamp, hours: int) -> tuple[float | None, float | None]:
    """Сумма за последние hours закрытых часов и во сколько раз она больше обычной по модулю (медиана |сумм за
    hours| по предыдущим 7 суткам; только прошлое)."""
    s = series.dropna()
    s = s[s.index < at]
    if len(s) < hours + 24:
        return None, None
    roll = s.rolling(hours).sum()
    cur = float(roll.iloc[-1])
    base = roll.iloc[-WARM_H - 1:-hours].abs().median()
    return cur, (abs(cur) / base) if base and base > 0 else None


def now_summary(df: pd.DataFrame, now: datetime, coin: str) -> list[str]:
    """Кто сейчас покупает/продаёт и насколько сильнее обычного — по закрытым часам."""
    at = pd.Timestamp(now).floor("1h")
    out = []
    for hrs in (6, 24):
        cur, x = strength(df.get("taker_delta", pd.Series(dtype=float)), at, hrs)
        if cur is not None:
            who = "покупают" if cur > 0 else "продают"
            out.append(f"Рынком {who} {hrs} ч: тейкеры {_n(cur, True)} {coin}{_force(x)}")
    if "bid_ask_delta" in df and df["bid_ask_delta"].notna().any():
        last = df["bid_ask_delta"].dropna()
        last = last[last.index < at]
        if len(last) > WARM_H:
            v = float(last.iloc[-1])
            base = last.iloc[-WARM_H - 1:-1].abs().median()
            out.append(f"Стакан ±1%: {'заявок на покупку' if v > 0 else 'заявок на продажу'} больше на {_n(abs(v))} "
                       f"{coin}{_force(abs(v) / base if base else None)}")
    ll, xl = strength(df["liq_all_long"].abs() if "liq_all_long" in df else pd.Series(dtype=float), at, 24)
    ls, xs = strength(df["liq_all_short"].abs() if "liq_all_short" in df else pd.Series(dtype=float), at, 24)
    if ll is not None and ls is not None:
        out.append(f"Ликвидации 24 ч: лонги {_usd(ll)}" + (f" (×{xl:.1f} к обычным суткам)" if xl else "")
                   + f", шорты {_usd(ls)}" + (f" (×{xs:.1f})" if xs else ""))
    for col, name, fmt in (("ls_acc", "Толпа L/S", "{:.2f}"), ("wi2", "Whale Index 2", "{:+.1f}"),
                           ("fr_pct", "Фандинг", "{:.4f}%")):
        if col in df:
            s = df[col].dropna()
            s = s[s.index < at]
            if len(s) > 24:
                out.append(f"{name} {fmt.format(s.iloc[-1])} (24 ч назад {fmt.format(s.iloc[-25])})"
                           .replace("-", "−"))
    return out


# ─────────────────────────────── совокупность «3 из 4» ───────────────────────────────

COMP = ("bid_ask_delta", "fr_pct", "ls_acc", "wi2")


def _slope_sign(v: np.ndarray) -> int:
    if len(v) < 2 or np.isnan(v).any():
        return 0
    t = np.arange(len(v), dtype=float) - (len(v) - 1) / 2
    return int(np.sign(np.dot(t, v - v.mean())))


def composite(df: pd.DataFrame, at: pd.Timestamp, n: int = 72) -> dict | None:
    """Знаки наклона за n часов (бары с концом ≤ at) по 4 линиям скрина оператора и их сумма."""
    win = df.loc[at - pd.Timedelta(hours=n):at - pd.Timedelta(hours=1)]
    if len(win) < n or any(c not in win for c in COMP):
        return None
    signs = {c: _slope_sign(win[c].to_numpy(dtype=float)) for c in COMP}
    if any(np.isnan(win[c].to_numpy(dtype=float)).any() for c in COMP):
        return None
    return {"signs": signs, "S": int(sum(signs.values()))}


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


def log_episodes(sym: str, df: pd.DataFrame, z: pd.DataFrame, now: datetime, path: Path = EPISODES) -> int:
    """Новые эпизоды — с временем фиксации и признаками на этот момент; созревшие исходы — отдельными записями."""
    have = _read_jsonl(path)
    known = {(r["sym"], r["start"]) for r in have if r.get("kind") == "episode"}
    done = {(r["sym"], r["start"], r["h"]) for r in have if r.get("kind") == "outcome"}
    closed = pd.Timestamp(now).floor("1h")
    eps = find_episodes(df, z, closed - pd.Timedelta(days=SHOW_DAYS), closed_before=closed, top=50)
    n = 0
    with open(path, "a", encoding="utf-8") as f:
        for ep in eps:
            key = (sym, ep["start"].isoformat())
            info = describe(df, ep, now)
            if key not in known and ep["end"] < closed - pd.Timedelta(hours=1):   # эпизод закончился
                rec = {k: v for k, v in info.items() if k != "after"}
                lag = (pd.Timestamp(now) - ep["end"] - pd.Timedelta(hours=1)).total_seconds() / 3600
                f.write(json.dumps({"kind": "episode", "sym": sym, "fixed_utc": now.isoformat(timespec="seconds"),
                                    "fixed_after_end_h": round(lag, 1), **rec}, ensure_ascii=False,
                                   default=float) + "\n")
                n += 1
            for hk, res in (info.get("after") or {}).items():
                if res is not None and (sym, ep["start"].isoformat(), hk) not in done:
                    f.write(json.dumps({"kind": "outcome", "sym": sym, "start": ep["start"].isoformat(), "h": hk,
                                        "checked_utc": now.isoformat(timespec="seconds"), **res}, default=float) + "\n")
    return n


def log_composite(sym: str, df: pd.DataFrame, now: datetime, path: Path = COMPOSITE) -> None:
    """Раз в сутки в 00:00 UTC: совокупность «3 из 4» и цена; исход через 24 ч — отдельной записью."""
    have = _read_jsonl(path)
    days = {r["day"] for r in have if r.get("sym") == sym and r.get("kind") == "call"}
    res = {r["day"] for r in have if r.get("sym") == sym and r.get("kind") == "outcome"}
    calls = {r["day"]: r for r in have if r.get("sym") == sym and r.get("kind") == "call"}
    today = pd.Timestamp(now).floor("1D")
    with open(path, "a", encoding="utf-8") as f:
        for at in (today,):                                     # только сегодняшний: исход ещё не известен
            key = at.strftime("%Y-%m-%d")
            if key in days or at > pd.Timestamp(now):
                continue
            c = composite(df, at)
            px = _v(df, "px_close", at - pd.Timedelta(hours=1))
            if c is None or px is None:
                continue
            call = 1 if c["S"] >= 2 else (-1 if c["S"] <= -2 else 0)
            f.write(json.dumps({"kind": "call", "sym": sym, "day": key, "fixed_utc": now.isoformat(timespec="seconds"),
                                "S": c["S"], "signs": c["signs"], "call": call, "price": px}) + "\n")
            calls[key] = {"price": px, "call": call}
        for key, c in calls.items():
            at = pd.Timestamp(key, tz="UTC") + pd.Timedelta(hours=24)
            if key in res or at > pd.Timestamp(now):
                continue
            px = _v(df, "px_close", at - pd.Timedelta(hours=1))
            if px is None:
                continue
            ret = (px / c["price"] - 1) * 100
            f.write(json.dumps({"kind": "outcome", "sym": sym, "day": key, "ret_24h_pct": ret,
                                "hit": (None if not c["call"] else bool(np.sign(ret) == c["call"]))}) + "\n")


def log_all(now: datetime | None = None) -> dict:
    """Каждый час из сборщика CoinGlass: эпизоды и совокупность в журналы. → {символ: новых эпизодов | ошибка}."""
    now = now or datetime.now(timezone.utc)
    out = {}
    for sym in SYMBOLS:
        try:
            df, _paid, _meta = frame(sym, now)
            out[sym] = log_episodes(sym, df, zscores(df), now)
            log_composite(sym, df, now)
        except Exception as exc:                                # noqa: BLE001
            out[sym] = f"{type(exc).__name__}: {exc}"[:200]
    return out


def composite_stats(sym: str, path: Path = COMPOSITE) -> dict:
    rows = _read_jsonl(path)
    hits = [r["hit"] for r in rows if r.get("sym") == sym and r.get("kind") == "outcome" and r.get("hit") is not None]
    return {"n": len(hits), "hit": (sum(hits) / len(hits)) if hits else None}
