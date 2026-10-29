"""Атлас индикаторов: описание каждого часа словами-метками и что было дальше (оператор 28.10: «фиксировать как можно
больше описаний индикаторов — что характерно для завершения движения, для флета к росту, флета к падению, где рост
заканчивается, где продолжается»).

ПРАВИЛА ЗАПИСАНЫ ДО ПРОГОНА (28.10.2026, до первого расчёта исходов). Менять — только новой версией ATLAS_VERSION.

atlas-2 (28.10, разбор GPT a7d799b §3 и §6.2; результаты atlas-1 не смотрелись — прогон остановлен и отложен в
superseded_atlas1/):
- метки потока по абсолютному знаку: «тейкеры покупают сильно» — дисбаланс > 0 И верхние 10% прошлых окон;
  «продают сильно» — < 0 И нижние 10%; «цена ↑, тейкеры продают» — дисбаланс < 0; стакан «зелёный» — ≥5 из 6 часов
  СТРОГО > 0 (ноль — не зелёный), «сильно красный/зелёный» — со знаком среднего за 6 ч;
- пропуск ≠ ноль: ликвидации, которых нет в выгрузке, остаются неизвестными; сумма за 6 ч — только по 6 известным
  часам; метка всплеска при неизвестном окне — False (не «всплеска не было», а «нельзя сказать»);
- UP требует r24 > 0, DOWN — r24 < 0;
- load проверяет sha256 CSV против манифеста и что каждый бар закрыт к моменту выгрузки;
- «высоко/низко» уровней — относительно прошлых 30 суток (перцентиль), не абсолютный уровень.
Ревизии истории CoinGlass (revision_audit.py, BTC/ETH): у старых баров все столбцы совпадают с живым журналом;
у последнего закрытого часа в момент выгрузки CoinGlass ещё досчитывает объём (медиана 0.6–0.9%) и дельту тейкеров
(1.5–3.1%) — для окон 6–24 ч несущественно.

Данные
- research/coinglass_compare/data/<SYM>_1h.csv — CoinGlass exportData 1h (Binance-перп, агрегаты по 12 биржам),
  только закрытые бары, статус сверки с легендой «ok» в <SYM>_1h.manifest.json; часовой календарь, пропуски — NaN.
- Монеты: COINS (те, что выгрузились со статусом ok).

Признаки на закрытии бара t — только бары ≤ t
- цена: ATR14 (истинный диапазон); r6/r24/r72 — ход за 6/24/72 ч в долях ATR; er24 — эффективность хода 24 ч;
  pos24/pos72 — место close в диапазоне high/low 24/72 ч; r24p — перцентиль r24 среди 720 прошлых часов;
  w24p — перцентиль ширины диапазона 24 ч.
- уровни (oi, fr, frw, lsa, lst, wi): p — перцентиль значения среди 720 прошлых часов (минимум 168);
  z6/z24 — изменение за 6/24 ч в робастных единицах прошлых 720 изменений того же горизонта (OI — в логарифме).
- потоки: tak6/tak24 — дисбаланс тейкеров Σdelta/Σ(buy+|sell|) за 6/24 ч и его перцентиль; book — заявки ±1%:
  red6 — сколько из 6 последних часов < 0, bookp6 — перцентиль среднего за 6 ч; vol6p — перцентиль объёма 6 ч.
- ликвидации: L6/S6 — сумма лонгов/шортов за 6 ч (шорты в выгрузке со знаком минус — берём модуль; пусто при
  живом баре = 0); всплеск — перцентиль суммы среди 720 прошлых ≥ 0.95.

Метки (слова описания) — см. TOKENS; пороги: перцентиль ≤0.10 «низко» / ≥0.90 «высоко»; z ≥ +1 «↑», ≥ +2 «↑↑»,
≤ −1 «↓», ≤ −2 «↓↓»; стакан «красный» — ≥5 из 6 часов < 0, «зелёный» — atlas-1: ≤1 из 6 красных, atlas-2: ≥5 из 6
часов > 0; дивергенции — знак r24 против
знака z24 (|r24| ≥ 2 ATR и |z24| ≥ 1).

Состояния на t (из прошлого, по приоритету)
- UP — r24p ≥ 0.80 и pos24 ≥ 0.70 (рост, цена у верха), atlas-2: и r24 > 0;  DOWN — r24p ≤ 0.20 и pos24 ≤ 0.30,
  atlas-2: и r24 < 0;
- FLAT — er24 ≤ 0.25 (как sc-1) и ширина 24 ч не шире медианы (w24p ≤ 0.50), не UP/DOWN;  иначе MIX.
  (Уточнено до расчёта исходов по меткам: при одном er24 «флетом» выходило 57% часов — у случайного блуждания
  er24 обычно < 0.25.)

Исходы (будущее, только для исследования) — тройной барьер от close t на 24 ч, барьер 2·ATR(t):
- up — high ≥ close + 2·ATR раньше, чем low ≤ close − 2·ATR; down — наоборот; both — оба в одном часе (не считается);
  none — ни один за 24 ч.  UP: up = «рост продолжается», down = «рост закончился (откат)»; DOWN — зеркально;
  FLAT: up = «флет → рост», down = «флет → падение», none = «флет продолжается».
- top_here — максимум high за t+1..t+24 не выше максимума high за t−2..t («вершина здесь»); bottom_here — зеркально.
- f24 — ход close за 24 ч в долях ATR(t).
"""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import numpy as np
import pandas as pd

ATLAS_VERSION = "atlas-2"
ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "research" / "coinglass_compare" / "data"
COINS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT", "ADAUSDT", "LINKUSDT", "AVAXUSDT",
         "LTCUSDT")
WIN, MINP = 720, 168
LEVELS = {"oi": "oi_coins", "fr": "fr_pct", "frw": "fr_oiw_pct", "lsa": "ls_acc", "lst": "ls_top_pos", "wi": "wi2"}
NAMES = {"oi": "OI", "fr": "фандинг", "frw": "фандинг по OI", "lsa": "толпа L/S", "lst": "топы L/S", "wi": "WI2"}
BARRIER, HORIZON = 2.0, 24


def load(sym: str, base: Path = DATA) -> pd.DataFrame:
    """CSV выгрузки → часовой календарь (UTC), только при статусе сверки ok."""
    man = json.loads((base / f"{sym}_1h.manifest.json").read_text(encoding="utf-8"))
    if man.get("status") != "ok":
        raise ValueError(f"{sym}: выгрузка не сверена ({man.get('why')})")
    raw = (base / f"{sym}_1h.csv").read_bytes()
    if man.get("sha256") and hashlib.sha256(raw).hexdigest() != man["sha256"]:
        raise ValueError(f"{sym}: CSV не совпадает с манифестом по sha256")
    df = pd.read_csv(io.BytesIO(raw))
    df.index = pd.to_datetime(df.pop("bar_utc"), utc=True)
    df = df.sort_index()
    df = df[~df.index.duplicated(keep="last")]
    if man.get("obs") and len(df) and df.index[-1] + pd.Timedelta(hours=1) > pd.Timestamp(man["obs"]):
        raise ValueError(f"{sym}: в CSV есть бар, не закрытый к моменту выгрузки")
    full = pd.date_range(df.index[0], df.index[-1], freq="1h")
    return df.reindex(full)


def available(base: Path = DATA) -> list[str]:
    out = []
    for s in COINS:
        p = base / f"{s}_1h.manifest.json"
        if p.exists() and json.loads(p.read_text(encoding="utf-8")).get("status") == "ok":
            out.append(s)
    return out


def pct_past(x: pd.Series, win: int = WIN, minp: int = MINP) -> pd.Series:
    """Перцентиль x[t] среди x[t−win..t−1] (без текущего; ничьи — пополам); мало прошлого — NaN."""
    a = x.to_numpy(dtype=float)
    out = np.full(len(a), np.nan)
    for t in range(len(a)):
        if np.isnan(a[t]):
            continue
        past = a[max(0, t - win):t]
        past = past[~np.isnan(past)]
        if len(past) < minp:
            continue
        out[t] = (np.sum(past < a[t]) + 0.5 * np.sum(past == a[t])) / len(past)
    return pd.Series(out, index=x.index)


def robust_z(d: pd.Series, win: int = WIN, minp: int = MINP) -> pd.Series:
    """(d[t] − медиана прошлых) / (1.4826·MAD прошлых); MAD = 0 → среднее абс. отклонение × 1.2533; 0 → NaN."""
    a = d.to_numpy(dtype=float)
    out = np.full(len(a), np.nan)
    for t in range(len(a)):
        if np.isnan(a[t]):
            continue
        past = a[max(0, t - win):t]
        past = past[~np.isnan(past)]
        if len(past) < minp:
            continue
        med = np.median(past)
        sc = 1.4826 * np.median(np.abs(past - med))
        if sc == 0:
            sc = 1.2533 * np.mean(np.abs(past - med))
        if sc > 0:
            out[t] = (a[t] - med) / sc
    return pd.Series(out, index=d.index)


def features(df: pd.DataFrame) -> pd.DataFrame:
    """Числовые признаки на закрытии каждого бара — только из прошлого и текущего бара."""
    c, h, lo = df["close"], df["high"], df["low"]
    tr = pd.concat([h - lo, (h - c.shift()).abs(), (lo - c.shift()).abs()], axis=1).max(axis=1, skipna=False)
    atr = tr.rolling(14, min_periods=14).mean()
    f = pd.DataFrame(index=df.index)
    f["atr"] = atr
    for k in (6, 24, 72):
        f[f"r{k}"] = (c - c.shift(k)) / atr
    path = c.diff().abs().rolling(24, min_periods=24).sum()
    f["er24"] = (c - c.shift(24)).abs() / path
    for k in (24, 72):
        hi, lw = h.rolling(k, min_periods=k).max(), lo.rolling(k, min_periods=k).min()
        f[f"pos{k}"] = (c - lw) / (hi - lw)
    f["w24"] = (h.rolling(24, min_periods=24).max() - lo.rolling(24, min_periods=24).min()) / c
    f["r24p"] = pct_past(f["r24"])
    f["w24p"] = pct_past(f["w24"])
    for key, col in LEVELS.items():
        s = df[col].astype(float)
        if key == "oi":
            s = np.log(s.where(s > 0))
        f[f"{key}_p"] = pct_past(df[col].astype(float))
        for k in (6, 24):
            f[f"{key}_z{k}"] = robust_z(s - s.shift(k))
    buy, sell = df["taker_buy"].astype(float), df["taker_sell"].astype(float).abs()
    for k in (6, 24):
        f[f"tak{k}"] = df["taker_delta"].rolling(k, min_periods=k).sum() / (buy + sell).rolling(k, min_periods=k).sum()
        f[f"tak{k}p"] = pct_past(f[f"tak{k}"])
    book = df["bid_ask_delta"].astype(float)
    f["red6"] = (book < 0).astype(float).where(book.notna()).rolling(6, min_periods=6).sum()
    f["green6"] = (book > 0).astype(float).where(book.notna()).rolling(6, min_periods=6).sum()
    f["book6"] = book.rolling(6, min_periods=6).mean()
    f["bookp6"] = pct_past(f["book6"])
    f["vol6p"] = pct_past(df["volume_usd"].astype(float).rolling(6, min_periods=6).sum())
    for side, col in (("L", "liq_all_long"), ("S", "liq_all_short")):
        # шорты в выгрузке со знаком минус (рисуются вниз); пусто — НЕИЗВЕСТНО (atlas-2: не ноль, GPT a7d799b)
        s = df[col].astype(float).abs()
        s6 = s.rolling(6, min_periods=6).sum()
        f[f"liq{side}6"] = s6
        f[f"liq{side}6p"] = pct_past(s6)
        f[f"liq{side}_spike"] = f[f"liq{side}6p"] >= 0.95
    return f


def tokens(f: pd.DataFrame) -> pd.DataFrame:
    """Слова описания часа (булевы столбцы). NaN признака → False."""
    t = {}
    for key, nm in NAMES.items():
        p = f[f"{key}_p"]
        t[f"{nm} высоко"] = p >= 0.90
        t[f"{nm} низко"] = p <= 0.10
        for k in (6, 24):
            z = f[f"{key}_z{k}"]
            t[f"{nm} ↑↑ {k}ч"] = z >= 2
            t[f"{nm} ↑ {k}ч"] = (z >= 1) & (z < 2)
            t[f"{nm} ↓ {k}ч"] = (z <= -1) & (z > -2)
            t[f"{nm} ↓↓ {k}ч"] = z <= -2
        up, dn = f["r24"] >= 2, f["r24"] <= -2
        t[f"цена ↑, {nm} ↓ (дивергенция 24ч)"] = up & (f[f"{key}_z24"] <= -1)
        t[f"цена ↓, {nm} ↑ (дивергенция 24ч)"] = dn & (f[f"{key}_z24"] >= 1)
    for k in (6, 24):
        p, x = f[f"tak{k}p"], f[f"tak{k}"]
        t[f"тейкеры покупают сильно {k}ч"] = (x > 0) & (p >= 0.90)
        t[f"тейкеры продают сильно {k}ч"] = (x < 0) & (p <= 0.10)
    t["цена ↑, тейкеры продают 24ч"] = (f["r24"] >= 2) & (f["tak24"] < 0)
    t["цена ↓, тейкеры покупают 24ч"] = (f["r24"] <= -2) & (f["tak24"] > 0)
    t["стакан красный 5+/6"] = f["red6"] >= 5
    t["стакан зелёный 5+/6"] = f["green6"] >= 5
    t["стакан сильно красный (6ч)"] = (f["book6"] < 0) & (f["bookp6"] <= 0.10)
    t["стакан сильно зелёный (6ч)"] = (f["book6"] > 0) & (f["bookp6"] >= 0.90)
    t["объём высокий 6ч"] = f["vol6p"] >= 0.90
    t["объём низкий 6ч"] = f["vol6p"] <= 0.10
    t["всплеск ликвидаций лонгов 6ч"] = f["liqL_spike"].astype(bool)
    t["всплеск ликвидаций шортов 6ч"] = f["liqS_spike"].astype(bool)
    t["диапазон 24ч узкий"] = f["w24p"] <= 0.20
    t["диапазон 24ч широкий"] = f["w24p"] >= 0.80
    return pd.DataFrame({k: v.fillna(False).astype(bool) for k, v in t.items()}, index=f.index)


def context(f: pd.DataFrame) -> pd.Series:
    """Состояние на t: UP / DOWN / FLAT / MIX; признаков не хватает — NaN."""
    ok = f[["r24p", "pos24", "er24"]].notna().all(axis=1)
    s = pd.Series("MIX", index=f.index, dtype=object)
    s[(f["er24"] <= 0.25) & (f["w24p"] <= 0.50)] = "FLAT"
    s[(f["r24p"] <= 0.20) & (f["pos24"] <= 0.30) & (f["r24"] < 0)] = "DOWN"
    s[(f["r24p"] >= 0.80) & (f["pos24"] >= 0.70) & (f["r24"] > 0)] = "UP"
    return s.where(ok)


def outcomes(df: pd.DataFrame, f: pd.DataFrame) -> pd.DataFrame:
    """Исходы на 24 ч (используют будущее — только для исследования)."""
    c, h, lo = df["close"].to_numpy(float), df["high"].to_numpy(float), df["low"].to_numpy(float)
    atr = f["atr"].to_numpy(float)
    n = len(c)
    first = np.full(n, None, dtype=object)
    top, bot = np.full(n, np.nan), np.full(n, np.nan)
    f24 = np.full(n, np.nan)
    for t in range(n - HORIZON):
        if np.isnan(c[t]) or np.isnan(atr[t]) or atr[t] <= 0:
            continue
        hh, ll = h[t + 1:t + 1 + HORIZON], lo[t + 1:t + 1 + HORIZON]
        if np.isnan(hh).any() or np.isnan(ll).any():
            continue
        up_hit = hh >= c[t] + BARRIER * atr[t]
        dn_hit = ll <= c[t] - BARRIER * atr[t]
        iu = np.argmax(up_hit) if up_hit.any() else None
        idn = np.argmax(dn_hit) if dn_hit.any() else None
        if iu is None and idn is None:
            first[t] = "none"
        elif idn is None or (iu is not None and iu < idn):
            first[t] = "up"
        elif iu is None or idn < iu:
            first[t] = "down"
        else:
            first[t] = "both"
        prev_hi = np.nanmax(h[max(0, t - 2):t + 1])
        prev_lo = np.nanmin(lo[max(0, t - 2):t + 1])
        top[t] = float(hh.max() <= prev_hi)
        bot[t] = float(ll.min() >= prev_lo)
        if not np.isnan(c[t + HORIZON]):
            f24[t] = (c[t + HORIZON] - c[t]) / atr[t]
    return pd.DataFrame({"first": first, "top_here": top, "bottom_here": bot, "f24": f24}, index=df.index)


def describe(row: pd.Series) -> str:
    """Строка описания часа из булевых меток."""
    return "; ".join(k for k, v in row.items() if v)


def build(sym: str, base: Path = DATA) -> pd.DataFrame:
    """Одна монета: признаки + состояние + метки + исходы, по часам."""
    df = load(sym, base)
    f = features(df)
    out = pd.concat([f, tokens(f)], axis=1)
    out["context"] = context(f)
    out = pd.concat([out, outcomes(df, f)], axis=1)
    out["close"] = df["close"]
    out["sym"] = sym
    return out


def build_all(base: Path = DATA, cache: Path | None = None) -> pd.DataFrame:
    """Все сверенные монеты одной таблицей (кэш — pickle рядом, по sha256 выгрузок)."""
    syms = available(base)
    shas = {s: json.loads((base / f"{s}_1h.manifest.json").read_text(encoding="utf-8"))["sha256"] for s in syms}
    cache = cache or (Path(__file__).resolve().parent / "cache")
    cache.mkdir(parents=True, exist_ok=True)
    frames = []
    for s in syms:
        p = cache / f"{s}_{ATLAS_VERSION}_{shas[s][:12]}.pkl"
        if p.exists():
            frames.append(pd.read_pickle(p))
            continue
        d = build(s, base)
        d.to_pickle(p)
        frames.append(d)
    return pd.concat(frames)


def token_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if df[c].dtype == bool and c not in ("liqL_spike", "liqS_spike")]
