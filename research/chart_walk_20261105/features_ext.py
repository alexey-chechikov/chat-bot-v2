"""PREREG_trade_ext_1109.md: расширенные признаки на часе входа — агрессор спота и фьючерса, базис, OI и лонг/шорт,
фандинг, ончейн CoinMetrics, стейблкоины, DVOL, дивергенции, цикл халвинга, CoinGlass. Каждый внешний ряд берётся
«как известно» (момент публикации, консервативно) и только если не старше max_age — иначе пусто (не протягиваем).
ext_prepare(a, name) → {название: массив по часам a["t"]}. Binance — всё; Bitstamp — ончейн, дивергенции, цикл."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("/Users/alexeychechikov/code/bot7")
sys.path.insert(0, str(ROOT))
from services.btc_signals import engine as en  # noqa: E402
from services.btc_signals import features as fx  # noqa: E402

FZ = ROOT / "backtests" / "frozen"
CG = ROOT / "research" / "coinglass_compare" / "data" / "BTCUSDT_1h.csv"
H, D = 3600, 86400
HALVINGS = [pd.Timestamp(x, tz="UTC").timestamp() for x in ("2012-11-28", "2016-07-09", "2020-05-11", "2024-04-20")]


def asof(t_known: np.ndarray, v: np.ndarray, t: np.ndarray, max_age: float) -> np.ndarray:
    """Значение последней записи, известной к t (t_known ≤ t), если она не старше max_age секунд."""
    o = np.argsort(t_known, kind="stable")
    tk, vv = np.asarray(t_known, float)[o], np.asarray(v, float)[o]
    idx = np.searchsorted(tk, t, side="right") - 1
    ok = (idx >= 0) & (t - tk[np.clip(idx, 0, None)] <= max_age)
    return np.where(ok, vv[np.clip(idx, 0, None)], np.nan)


def rsum(x: np.ndarray, k: int) -> np.ndarray:
    return pd.Series(x).rolling(k, min_periods=k).sum().to_numpy()


def pos_in(x: np.ndarray, k: int) -> np.ndarray:
    s = pd.Series(x)
    lo, hi = s.rolling(k, min_periods=k).min(), s.rolling(k, min_periods=k).max()
    with np.errstate(invalid="ignore", divide="ignore"):
        return ((s - lo) / (hi - lo)).to_numpy()


def rank_in(x: np.ndarray, k: int) -> np.ndarray:
    """Место текущего значения среди k прошлых (0..1)."""
    s = pd.Series(x)
    return s.rolling(k + 1, min_periods=k // 2).apply(lambda w: np.mean(w[:-1] < w[-1]) if np.isfinite(w[-1]) else np.nan, raw=True).to_numpy()


def spot_block(t: np.ndarray, c: np.ndarray) -> dict:
    s = pd.read_csv(FZ / "ext_spot_BTCUSDT_1h.csv", usecols=["ms", "close", "volume", "trades", "taker_base"])
    tk = s["ms"].to_numpy(np.int64) // 1000 + H
    vol, tb, tr = s["volume"].to_numpy(float), s["taker_base"].to_numpy(float), s["trades"].to_numpy(float)
    delta = 2 * tb - vol
    out = {}
    with np.errstate(invalid="ignore", divide="ignore"):
        for k, nm in ((4, "4ч"), (24, "24ч"), (72, "72ч")):
            out[f"дельта агрессора спота {nm}, доля"] = rsum(delta, k) / rsum(vol, k)
        out["CVD спота 7д к объёму"] = rsum(delta, 168) / rsum(vol, 168)
        s4 = rsum(vol, 4)
        out["объём спота 4ч к медиане 30д"] = s4 / pd.Series(s4).rolling(720, min_periods=360).median().to_numpy()
        out["размер сделки 24ч к 30д"] = (rsum(vol, 24) / rsum(tr, 24)) / (rsum(vol, 720) / rsum(tr, 720))
        cvd = np.cumsum(np.nan_to_num(delta))
        out["цена минус CVD в канале 72ч"] = pos_in(s["close"].to_numpy(float), 72) - pos_in(cvd, 72)
    res = {k: asof(tk, v, t, 2 * H) for k, v in out.items()}
    res["_spot_close"] = asof(tk, s["close"].to_numpy(float), t, 2 * H)
    return res


def fut_block(t: np.ndarray, spot_close: np.ndarray) -> dict:
    parts = []
    for nm in ("BTCUSDT_UM_1m_early.csv", "BTCUSDT_UM_1m.csv"):
        m = pd.read_csv(FZ / nm, usecols=["ts", "close", "volume", "taker_buy"])
        m["h"] = m["ts"] // 3_600_000
        g = m.groupby("h").agg(close=("close", "last"), volume=("volume", "sum"), taker_buy=("taker_buy", "sum"), n=("ts", "size"))
        parts.append(g)
    g = pd.concat(parts)
    g = g[~g.index.duplicated(keep="last")].sort_index()
    g = g[g["n"] >= 50]
    tk = (g.index.to_numpy(np.int64) + 1) * H
    vol, tb = g["volume"].to_numpy(float), g["taker_buy"].to_numpy(float)
    out = {}
    with np.errstate(invalid="ignore", divide="ignore"):
        out["дельта агрессора фьючерса 24ч, доля"] = rsum(2 * tb - vol, 24) / rsum(vol, 24)
        fut_v24 = rsum(vol, 24)
    res = {k: asof(tk, v, t, 2 * H) for k, v in out.items()}
    fc = asof(tk, g["close"].to_numpy(float), t, 2 * H)
    with np.errstate(invalid="ignore", divide="ignore"):
        basis = (fc / spot_close - 1) * 100
    res["базис фьючерс−спот, %"] = basis
    res["базис 7д среднее, %"] = pd.Series(basis).rolling(168, min_periods=120).mean().to_numpy()
    s = pd.read_csv(FZ / "ext_spot_BTCUSDT_1h.csv", usecols=["ms", "volume"])
    sv24 = asof(s["ms"].to_numpy(np.int64) // 1000 + H, rsum(s["volume"].to_numpy(float), 24), t, 2 * H)
    with np.errstate(invalid="ignore", divide="ignore"):
        res["объём фьючерс/спот 24ч"] = asof(tk, fut_v24, t, 2 * H) / sv24
    return res


def metrics_block(t: np.ndarray, c: np.ndarray) -> dict:
    m = pd.read_csv(FZ / "ext_metrics_BTCUSDT.csv")
    ts = m["ts"].to_numpy(np.int64)
    tk = (ts // 1000 if ts.max() > 1e11 else ts) + 4 * H
    oi = m["sum_open_interest"].to_numpy(float)
    get = lambda col, dt=0: asof(tk, m[col].to_numpy(float), t - dt, 8 * H)  # noqa: E731
    oi_now = asof(tk, oi, t, 8 * H)
    res = {}
    with np.errstate(invalid="ignore", divide="ignore"):
        for lagh, nm in ((24, "24ч"), (72, "72ч"), (168, "7д")):
            res[f"OI изм. {nm}, %"] = (oi_now / asof(tk, oi, t - lagh * H, 8 * H) - 1) * 100
        ret72 = (c / fx.lag(c, 72) - 1) * 100
        res["цена минус OI за 72ч, п.п."] = ret72 - res["OI изм. 72ч, %"]
        res["лонг/шорт толпы (счета)"] = get("count_long_short_ratio")
        res["лонг/шорт толпы изм. 24ч"] = res["лонг/шорт толпы (счета)"] - get("count_long_short_ratio", 24 * H)
        res["лонг/шорт топ-трейдеров (позиции)"] = get("sum_toptrader_long_short_ratio")
        res["лонг/шорт топ-трейдеров (счета)"] = get("count_toptrader_long_short_ratio")
        res["тейкеры покупка/продажа 4ч"] = get("sum_taker_long_short_vol_ratio")
        ls_rank = rank_in(m["count_long_short_ratio"].to_numpy(float), 540)
        res["лонг/шорт толпы ранг 90д"] = asof(tk, ls_rank, t, 8 * H)
        oi_rank = rank_in(pd.Series(oi).pct_change(18).to_numpy() * 100, 540)
        res["OI изм. 72ч ранг 90д"] = asof(tk, oi_rank, t, 8 * H)
    return res


def funding_block(t: np.ndarray) -> dict:
    f = pd.read_csv(FZ / "BTCUSDT_funding_full.csv")
    tk = f["fundingTime"].to_numpy(np.int64) // 1000
    r = f["fundingRate"].to_numpy(float) * 100
    rk = rank_in(r, 270)
    m7, m30 = pd.Series(r).rolling(21, min_periods=21).mean().to_numpy(), pd.Series(r).rolling(90, min_periods=90).mean().to_numpy()
    return {"фандинг ранг 90д": asof(tk, rk, t, 9 * H), "фандинг 7д минус 30д, %/8ч": asof(tk, m7 - m30, t, 9 * H)}


def daily_block(t: np.ndarray) -> dict:
    cm = pd.read_csv(FZ / "ext_cm_btc.csv").sort_values("day")
    tk = cm["day"].to_numpy(np.int64) + 2 * D
    s = lambda col: cm[col].to_numpy(float)  # noqa: E731
    roll = lambda x, k: pd.Series(x).rolling(k, min_periods=k).mean().to_numpy()  # noqa: E731
    mv = s("CapMVRVCur")
    v = {"MVRV": mv, "MVRV изм. 30д": mv - fx.lag(mv, 30), "MVRV ранг 2г": rank_in(mv, 730),
         "активные адреса 30д/365д": roll(s("AdrActCnt"), 30) / roll(s("AdrActCnt"), 365),
         "хешрейт 30д/60д": roll(s("HashRate"), 30) / roll(s("HashRate"), 60),
         "транзакции 30д/365д": roll(s("TxCnt"), 30) / roll(s("TxCnt"), 365),
         "выпуск USD 30д/365д": roll(s("IssTotUSD"), 30) / roll(s("IssTotUSD"), 365),
         "ROI рынка 30д, %": s("ROI30d")}
    res = {k: asof(tk, x, t, 5 * D) for k, x in v.items()}
    st = pd.read_csv(FZ / "ext_stable.csv").sort_values("day")
    u = st["usd"].to_numpy(float)
    res["стейблкоины изм. 30д, %"] = asof(st["day"].to_numpy(np.int64) + 2 * D, (u / fx.lag(u, 30) - 1) * 100, t, 5 * D)
    return res


def dvol_block(t: np.ndarray, c: np.ndarray) -> dict:
    d = pd.read_csv(FZ / "ext_dvol_BTC.csv")
    tk = d["ms"].to_numpy(np.int64) // 1000 + H
    x = d["close"].to_numpy(float)
    dv = asof(tk, x, t, 2 * H)
    lr = np.diff(np.log(c), prepend=np.nan)
    rv = pd.Series(lr).rolling(720, min_periods=600).std().to_numpy() * np.sqrt(8760) * 100
    with np.errstate(invalid="ignore", divide="ignore"):
        return {"DVOL": dv, "DVOL ранг 1г": asof(tk, rank_in(x, 8760), t, 2 * H), "DVOL к реализованной 30д": dv / rv,
                "DVOL изм. 7д": dv - asof(tk, x, t - 168 * H, 2 * H)}


def div_block(a: dict) -> dict:
    t, c = np.asarray(a["t"], np.int64), np.asarray(a["c"], float)
    b = en.bars4(a)
    c4 = b["c"]
    r4 = fx.rsi(c4)
    cmax, cmin = pd.Series(c4).shift(1).rolling(20).max().to_numpy(), pd.Series(c4).shift(1).rolling(20).min().to_numpy()
    rmax, rmin = pd.Series(r4).shift(1).rolling(20).max().to_numpy(), pd.Series(r4).shift(1).rolling(20).min().to_numpy()
    with np.errstate(invalid="ignore"):
        bear = ((c4 >= cmax) & (r4 < rmax - 3)).astype(float)
        bull = ((c4 <= cmin) & (r4 > rmin + 3)).astype(float)
    macd = en.ema(c4, 12) - en.ema(c4, 26)
    hist = macd - en.ema(macd, 9)
    v4 = {"медв. дивергенция RSI 4ч": bear, "бычья дивергенция RSI 4ч": bull,
          "медв. дивергенция RSI 4ч за 6 свечей": pd.Series(bear).rolling(6, min_periods=1).max().to_numpy(),
          "бычья дивергенция RSI 4ч за 6 свечей": pd.Series(bull).rolling(6, min_periods=1).max().to_numpy(),
          "цена минус RSI в канале 30 свечей 4ч": pos_in(c4, 30) - pos_in(r4, 30),
          "цена минус MACD в канале 30 свечей 4ч": pos_in(c4, 30) - pos_in(hist, 30)}
    idx4 = np.searchsorted(b["close_t"], t, side="right") - 1
    ok = idx4 >= 0
    res = {k: np.where(ok, v[np.clip(idx4, 0, None)], np.nan) for k, v in v4.items()}
    r1 = fx.rsi(c)
    cm1, cn1 = pd.Series(c).shift(1).rolling(72).max().to_numpy(), pd.Series(c).shift(1).rolling(72).min().to_numpy()
    rm1, rn1 = pd.Series(r1).shift(1).rolling(72).max().to_numpy(), pd.Series(r1).shift(1).rolling(72).min().to_numpy()
    with np.errstate(invalid="ignore"):
        res["медв. дивергенция RSI 1ч (72ч)"] = ((c >= cm1) & (r1 < rm1 - 3)).astype(float)
        res["бычья дивергенция RSI 1ч (72ч)"] = ((c <= cn1) & (r1 > rn1 + 3)).astype(float)
    hv = np.array(HALVINGS)
    k = np.searchsorted(hv, t, side="right") - 1
    res["дней после халвинга"] = np.where(k >= 0, (t - hv[np.clip(k, 0, None)]) / D, np.nan)
    return res


def coinglass_block(t: np.ndarray) -> dict:
    g = pd.read_csv(CG)
    tk = pd.to_datetime(g["bar_utc"]).astype("int64").to_numpy() // 10 ** 9 + H
    res = {}
    for col, nm in (("wi2", "CoinGlass: индекс китов"), ("ls_acc", "CoinGlass: лонг/шорт счетов"), ("ls_top_pos", "CoinGlass: лонг/шорт топ-позиций"),
                    ("fr_oiw_pct", "CoinGlass: фандинг по OI, %")):
        res[nm] = asof(tk, g[col].to_numpy(float), t, 2 * H)
    with np.errstate(invalid="ignore", divide="ignore"):
        res["CoinGlass: дельта стакана 24ч"] = asof(tk, rsum(g["bid_ask_delta"].fillna(0).to_numpy(float), 24), t, 2 * H)
        res["CoinGlass: дельта тейкеров 24ч"] = asof(tk, rsum(g["taker_delta"].fillna(0).to_numpy(float), 24), t, 2 * H)
        res["CoinGlass: ликвидации лонгов 24ч, $"] = asof(tk, rsum(g["liq_all_long"].fillna(0).to_numpy(float), 24), t, 2 * H)
        res["CoinGlass: ликвидации шортов 24ч, $"] = asof(tk, rsum(g["liq_all_short"].fillna(0).abs().to_numpy(float), 24), t, 2 * H)
    cov = pd.notna(g["wi2"]).to_numpy()
    first = tk[cov].min() if cov.any() else np.inf
    for k in list(res):
        res[k] = np.where(t >= first, res[k], np.nan)
    return res


MACRO = {"spx": "S&P 500", "xau": "золото", "dxy": "индекс доллара"}


def btc_daily(a: dict) -> pd.Series:
    """Закрытие BTC в 00:00 UTC (конец дня), индекс — начало дня UTC (секунды)."""
    t, c = np.asarray(a["t"], np.int64), np.asarray(a["c"], float)
    m = t % D == 0
    return pd.Series(c[m], index=t[m] - D)


def macro_frame(a: dict, key: str) -> pd.DataFrame | None:
    p = FZ / f"ext_{key}_d.csv"
    if not p.exists():
        return None
    m = pd.read_csv(p)
    day = pd.to_datetime(m["date"]).astype("int64").to_numpy() // 10 ** 9
    f = pd.DataFrame({"x": m["close"].to_numpy(float)}, index=day)
    f["btc"] = btc_daily(a).reindex(f.index).to_numpy()
    f = f[~f.index.duplicated()].sort_index()
    f["rx"], f["rb"] = np.log(f["x"]).diff(), np.log(f["btc"]).diff()
    return f


def macro_block(a: dict) -> dict:
    """S&P 500, золото, индекс доллара (Stooq, день): известно с 00:00 UTC следующего дня, не старше 5 суток."""
    t = np.asarray(a["t"], np.int64)
    res = {}
    for key, nm in MACRO.items():
        f = macro_frame(a, key)
        if f is None:
            continue
        tk = f.index.to_numpy() + D
        x = f["x"]
        v = {f"корреляция с {nm} 30д": f["rx"].rolling(30, min_periods=25).corr(f["rb"]),
             f"корреляция с {nm} 90д": f["rx"].rolling(90, min_periods=70).corr(f["rb"]),
             f"{nm}: ход 5д, %": (x / x.shift(5) - 1) * 100, f"{nm}: ход 20д, %": (x / x.shift(20) - 1) * 100,
             f"{nm}: от SMA200, %": (x / x.rolling(200, min_periods=150).mean() - 1) * 100}
        if key == "spx":
            v["BTC минус S&P 500 за 20д, п.п."] = ((f["btc"] / f["btc"].shift(20)) - (x / x.shift(20))) * 100
        for k, s in v.items():
            res[k] = asof(tk, s.to_numpy(float), t, 5 * D)
    return res


def ext_prepare(a: dict, name: str) -> dict[str, np.ndarray]:
    t = np.asarray(a["t"], np.int64)
    c = np.asarray(a["c"], float)
    P = {}
    P.update(div_block(a))
    P.update(daily_block(t))
    P.update(macro_block(a))
    if name == "Binance":
        sp = spot_block(t, c)
        spot_close = sp.pop("_spot_close")
        P.update(sp)
        P.update(fut_block(t, spot_close))
        P.update(metrics_block(t, c))
        P.update(funding_block(t))
        P.update(dvol_block(t, c))
        P.update(coinglass_block(t))
    return P
