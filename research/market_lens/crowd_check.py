"""Проверка картинки оператора 27.10 (CoinGlass: толпа = L/S всех аккаунтов, крупные, фандинг, ликвидации) на 2.4 годах
часовых данных Binance USDⓈ-M. ПРАВИЛА ЗАПИСАНЫ ДО ПРОГОНА — после прогона не менять.

Данные: 5-мин метрики data.binance.vision (data/<SYM>_metrics_5m.parquet) → часовые: у часа [T, T+1ч) последняя точка
внутри часа (≤ T+55м). Свечи — fapi 1ч. Фандинг — fapi fundingRate, известный к закрытию часа.
Ранг в момент t — доля значений за предыдущие 720 часов (30 сут), которые меньше значения в t (без будущего).
Исход от закрытия часа t на 72 ч вперёд: что первым — +X% или −X% (X = 2% BTC, 3% ETH); оба в одном часе — исключить;
ни одного за 72 ч — исключить из доли (число печатается). Ещё — средняя доходность 24 ч.
Эпизоды: вход в состояние не чаще раза в 24 ч (первый подходящий час, затем 24 ч пропуска).
База: доля «сначала вниз» по всем часам.
Гипотезы (5 × 2 монеты = 10 проверок → интервал Уилсона с z = 2.81, 95% с поправкой Бонферрони):
  H1a толпа в лонгах: ранг толпы ≥ 0.9 → чаще сначала вниз?
  H1b толпа в шортах: ранг толпы ≤ 0.1 → чаще сначала вверх?
  H2a толпа в лонгах, крупные нет: ранг толпы ≥ 0.8 и ранг крупных ≤ 0.2 → чаще вниз?
  H2b толпа в шортах, крупные в лонгах: ранг толпы ≤ 0.2 и ранг крупных ≥ 0.8 → чаще вверх?
  H3 фандинг ≤ 0 и цена за 72 ч ≤ −3% → чаще вверх?
Контроль: циклический сдвиг ряда условия на случайные 30…(N−30) суток, 999 повторов; ранг (k+1)/(n+1) — доля сдвигов
с эффектом в заявленную сторону не меньше настоящего.
Половины: эффект в первой и второй половине периода.
Зеркало: корреляция изменения толпы за 24 ч с доходностью тех же 24 ч и следующих 24 ч.
Разведка (вне Бонферрони, наш сборщик ликвидаций с 05.2026): час с ликвидациями лонгов ≥ 99-го перцентиля 30 сут — был ли
минимум этого часа дном на 72 ч (ниже не ушли больше чем на 0.5%) против часов с тем же падением за 6 ч без всплеска.

Запуск: research/market_lens/fetch_metrics.py BTCUSDT ETHUSDT (≈15 мин, data/ не в git), затем этот скрипт (nice 20).

ИТОГ 27.10 (01.05.2024–27.10.2026, 21 833 часа): все 10 — шум.
  BTC H1a 54.6% [45–64] против 50.1%, половины 62/50, ранг 0.105; H1b 53.1%, ранг 0.183; H2a 51.5%, 0.389;
      H2b 54.8%, 0.233; H3 51.4%, 0.444.
  ETH H1a 53.9% [44–64] против 49.3%, половины 59/49, ранг 0.100; H1b 54.4%, 0.178; H2a 54.1%, 0.192; H2b 45.9%, 0.759;
      H3 53.2%, 0.308.
  Зеркало: корр(Δтолпы 24ч, цена тех же 24ч) −0.69 BTC / −0.64 ETH; со следующими 24ч −0.00 / −0.01.
  Крупные: −0.32 / −0.03 с теми же сутками, +0.01 / −0.00 со следующими.
  Ликвидации (разведка, n мал): минимум часа всплеска удержался 72ч в 35% BTC (n 26) / 22% ETH (n 27) против 10% / 11%
  у часов с тем же падением без всплеска — в 2 из 3 случаев цена всё же ушла ниже.
"""
import csv
import json
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

D = Path(__file__).resolve().parent / "data"
X = {"BTCUSDT": 0.02, "ETHUSDT": 0.03}
Z = 2.81
H = 72
LIQ = {"BTCUSDT": "/Users/alexeychechikov/code/bot7/market_live/liquidations.csv",
       "ETHUSDT": "/Users/alexeychechikov/code/bot7/market_live/liquidations_ETHUSDT.csv"}


def get(url):
    return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "bot7"}),
                                             timeout=30).read())


def klines(sym):
    p = D / f"kl1h_{sym}.parquet"
    if p.exists() and pd.read_parquet(p).index[-1] > pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=3):
        return pd.read_parquet(p)
    t, rows = int(pd.Timestamp("2024-05-01", tz="UTC").timestamp() * 1000), []
    while True:
        r = get(f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}&interval=1h&startTime={t}&limit=1500")
        if not r:
            break
        rows += r
        if len(r) < 1500:
            break
        t = int(r[-1][0]) + 3_600_000
    now = pd.Timestamp.now(tz="UTC").timestamp() * 1000
    df = pd.DataFrame([{"t": pd.Timestamp(int(k[0]), unit="ms", tz="UTC"), "o": float(k[1]), "h": float(k[2]),
                        "l": float(k[3]), "c": float(k[4])} for k in rows if int(k[6]) < now]).set_index("t")
    df = df[~df.index.duplicated()]
    df.to_parquet(p)
    return df


def funding(sym):
    t, out = int(pd.Timestamp("2024-05-01", tz="UTC").timestamp() * 1000), {}
    while True:
        r = get(f"https://fapi.binance.com/fapi/v1/fundingRate?symbol={sym}&startTime={t}&limit=1000")
        if not r:
            break
        for x in r:
            out[pd.Timestamp(int(x["fundingTime"]), unit="ms", tz="UTC")] = float(x["fundingRate"])
        if len(r) < 1000:
            break
        t = int(r[-1]["fundingTime"]) + 1
    return pd.Series(out).sort_index()


def hourly(sym):
    m = pd.read_parquet(D / f"{sym}_metrics_5m.parquet")
    m["t"] = pd.to_datetime(m["ts_ms"], unit="ms", utc=True)
    m = m.set_index("t").sort_index()
    m = m[m.index.minute != 0]                       # точка ровно в T — граница; час [T, T+1ч) берёт ≤ T+55м
    hm = m[["global_ls_ratio", "top_trader_ls_ratio", "sum_open_interest_value"]].resample("1h").last()
    hm.columns = ["crowd", "top", "oi"]
    kl = klines(sym)
    df = kl.join(hm, how="left")
    fr = funding(sym)
    # фандинг, известный к закрытию часа T+1ч: последнее начисление с fundingTime ≤ T+1ч
    close_t = df.index + pd.Timedelta(hours=1)
    idx = np.searchsorted(fr.index.values, close_t.values, side="right") - 1
    df["fund"] = np.where(idx >= 0, fr.values[np.clip(idx, 0, None)], np.nan)
    return df


def rank(s, w=720):
    v = s.values
    out = np.full(len(v), np.nan)
    for i in range(w, len(v)):
        win = v[i - w:i]
        win = win[~np.isnan(win)]
        if len(win) >= w * 0.8 and not np.isnan(v[i]):
            out[i] = (win < v[i]).mean()
    return out


def first_touch(df, x):
    c, h, l = df["c"].values, df["h"].values, df["l"].values
    n = len(c)
    out = np.full(n, np.nan)                        # 1 — сначала вниз, 0 — сначала вверх, nan — нет/оба
    for i in range(n - 1):
        up, dn = c[i] * (1 + x), c[i] * (1 - x)
        hh, ll = h[i + 1:i + 1 + H], l[i + 1:i + 1 + H]
        iu = np.argmax(hh >= up) if (hh >= up).any() else 10 ** 9
        idn = np.argmax(ll <= dn) if (ll <= dn).any() else 10 ** 9
        if iu == idn:
            continue
        out[i] = 1.0 if idn < iu else 0.0
    return out


def episodes(mask):
    idx, last = [], -10 ** 9
    for i in np.flatnonzero(mask):
        if i - last >= 24:
            idx.append(i)
            last = i
    return np.array(idx, dtype=int)


def wilson(k, n, z=Z):
    if n == 0:
        return 0.0, 1.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    hw = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return c - hw, c + hw


def effect(mask, ft, want_down):
    e = episodes(mask)
    v = ft[e]
    v = v[~np.isnan(v)]
    if len(v) == 0:
        return np.nan, 0, 0
    p = v.mean()
    return (p if want_down else 1 - p), int(v.sum() if want_down else len(v) - v.sum()), len(v)


def run(sym):
    df = hourly(sym)
    x = X[sym]
    df["rc"] = rank(df["crowd"])
    df["rt"] = rank(df["top"])
    ft = first_touch(df, x)
    ret24 = df["c"].shift(-24) / df["c"] - 1
    r72p = df["c"] / df["c"].shift(72) - 1
    base_dn = np.nanmean(ft)
    valid = ~np.isnan(df["rc"].values) & ~np.isnan(df["rt"].values)
    print(f"\n=== {sym}: часов {len(df)} ({df.index[0]:%d.%m.%Y}–{df.index[-1]:%d.%m.%Y}), с рангами {valid.sum()}, "
          f"исход ±{x:.0%} за {H} ч: сначала вниз {base_dn:.1%} (база), без касания "
          f"{np.isnan(ft).mean():.1%}")
    hyp = {
        "H1a толпа в лонгах (ранг ≥0.9) → вниз": (df["rc"].values >= 0.9, True),
        "H1b толпа в шортах (ранг ≤0.1) → вверх": (df["rc"].values <= 0.1, False),
        "H2a толпа лонг, крупные нет → вниз": ((df["rc"].values >= 0.8) & (df["rt"].values <= 0.2), True),
        "H2b толпа шорт, крупные лонг → вверх": ((df["rc"].values <= 0.2) & (df["rt"].values >= 0.8), False),
        "H3 фандинг ≤0 после −3% за 72ч → вверх": ((df["fund"].values <= 0) & (r72p.values <= -0.03), False),
    }
    half = len(df) // 2
    rng = np.random.default_rng(20261027)
    n = len(df)
    for name, (mask, want_down) in hyp.items():
        mask = np.where(np.isnan(df["rc"].values), False, mask)
        p, k, m = effect(mask, ft, want_down)
        base = base_dn if want_down else 1 - base_dn
        lo, hi = wilson(k, m)
        m1 = mask.copy()
        m1[half:] = False
        m2 = mask.copy()
        m2[:half] = False
        p1, _, n1 = effect(m1, ft, want_down)
        p2, _, n2 = effect(m2, ft, want_down)
        e24 = np.nanmean(ret24.values[episodes(mask)]) if m else np.nan
        ge = 0
        for _ in range(999):
            sh = int(rng.integers(720, n - 720))
            pp, _, mm = effect(np.roll(mask, sh), ft, want_down)
            if mm and pp - base >= p - base:
                ge += 1
        verdict = "ОТЛИЧИЕ" if (lo > base or hi < base) else "шум"
        print(f"{name}: эпизодов {m}, в заявленную сторону {p:.1%} [95%Б {lo:.0%}–{hi:.0%}] против базы {base:.1%} → "
              f"{verdict}; половины {p1:.0%} (n {n1}) / {p2:.0%} (n {n2}); доходность 24ч {e24:+.2%}; "
              f"ранг сдвигов {(ge + 1) / 1000:.3f}")
    # зеркало: изменение толпы за 24 ч против доходности тех же и следующих 24 ч
    dc = df["crowd"].pct_change(24)
    r_same = df["c"].pct_change(24)
    r_next = df["c"].shift(-24) / df["c"] - 1
    s = pd.DataFrame({"dc": dc, "same": r_same, "next": r_next}).iloc[::24].dropna()
    print(f"зеркало (каждые 24 ч, n {len(s)}): корр(Δтолпы, доходность тех же 24ч) {s.dc.corr(s.same):+.2f}; "
          f"с доходностью следующих 24ч {s.dc.corr(s.next):+.2f}")
    dt = df["top"].pct_change(24)
    s2 = pd.DataFrame({"dt": dt, "same": r_same, "next": r_next}).iloc[::24].dropna()
    print(f"крупные: корр(Δкрупных, те же 24ч) {s2.dt.corr(s2.same):+.2f}; следующие 24ч {s2.dt.corr(s2.next):+.2f}")
    now = df.dropna(subset=["rc"]).iloc[-1]
    print(f"сейчас ({now.name:%d.%m %H}ч): толпа {now.crowd:.2f} ранг 30 сут {now.rc:.0%}; крупные {now.top:.2f} ранг "
          f"{now.rt:.0%}; фандинг {now.fund * 100:.4f}%")
    liq_probe(sym, df)


def liq_probe(sym, df):
    ll = {}
    with open(LIQ[sym], newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                t = pd.Timestamp(datetime.fromisoformat(r["ts_utc"])).floor("h")
                usd = float(r["qty"]) * float(r["price"])
            except (KeyError, ValueError):
                continue
            if r["side"] == "long":
                ll[t] = ll.get(t, 0.0) + usd
    s = pd.Series(ll).sort_index()
    d = df[df.index >= s.index[0]].copy()
    d["ll"] = s.reindex(d.index).fillna(0.0)
    d["p99"] = d["ll"].rolling(720, min_periods=500).quantile(0.99).shift(1)
    d["r6"] = d["c"] / d["c"].shift(6) - 1
    fut_low = d["l"][::-1].rolling(H, min_periods=H).min()[::-1].shift(-1)
    d["held"] = (fut_low >= d["l"] * 0.995).astype(float)
    d.loc[fut_low.isna(), "held"] = np.nan
    spike = (d["ll"] > d["p99"]).values
    e = episodes(spike)
    v = d["held"].values[e]
    r6 = d["r6"].values[e]
    ok = ~np.isnan(v)
    # контроль: часы без всплеска (ll ≤ медианы 30 сут) с падением за 6 ч не меньше, чем в эпизодах
    thr = np.nanmedian(r6[ok]) if ok.any() else np.nan
    calm = (d["ll"] <= d["ll"].rolling(720, min_periods=500).median().shift(1)).values & (d["r6"].values <= thr)
    ec = episodes(calm)
    vc = d["held"].values[ec]
    print(f"разведка ликвидаций ({d.index[0]:%d.%m}–{d.index[-1]:%d.%m}): всплесков лонгов {ok.sum()}, минимум часа "
          f"удержался 72ч в {np.nanmean(v):.0%}; контроль (то же падение за 6ч ≤{thr:+.1%}, без всплеска) "
          f"{np.nanmean(vc):.0%} (n {np.isfinite(vc).sum()})")


if __name__ == "__main__":
    for sym in sys.argv[1:] or ("BTCUSDT", "ETHUSDT"):
        run(sym)
