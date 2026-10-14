"""ATLAS 14.10, footprint: 15m-свечи UTC из сделок aggTrades с дельтой агрессора в фитилях + сверка целостности.

Правила — docs/ATLAS_FOOTPRINT_PROTOCOL_2026-10-14.md (дополнение, коммит 18bc3db) к docs/ATLAS_DELTA_PROTOCOL_2026-10-14.md
(715a2de). Архивы — внешние недоверенные данные: читаются только как CSV (zipfile + pandas), ничего из них не исполняется.

  - сделки дня сортируются по (transact_time, agg_trade_id); o/h/l/c свечи — первая/макс./мин./последняя цена;
  - is_buyer_maker = true → агрессор продавец; покупки/продажи агрессоров — суммы quantity;
  - нижний фитиль — сделки с ценой ≤ min(open, close), верхний — ≥ max(open, close) (протокол); сделки ровно на краю
    тела входят в фитиль; *_strict_n — число сделок строго за краем тела (0 → фитиль пустой, [формализация]);
  - сверка ДО любых выводов: по минутам Σ quantity покупателей-агрессоров против taker_buy и Σ quantity против volume
    минутных свечей backtests/frozen/<SYM>_UM_1m.csv; пороги «большого расхождения» зафиксированы ниже до прогона —
    при провале свечи не пишутся, выход с кодом 2.

    .venv/bin/python3 -I research/atlas_data/footprint_bars.py [BTC] [ETH] [--from=2026-08-19] [--to=2026-10-13]
        [--data-root=/Users/alexeychechikov/code/bot7]
Выход: backtests/aggtrades/<SYM>_15m_footprint.csv и <SYM>_footprint_integrity.json (каталог в .gitignore).
"""
from __future__ import annotations

import hashlib
import io
import json
import sys
import zipfile
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
MIN, BAR, DAY = 60_000, 900_000, 86_400_000
SYMS = {"BTC": "BTCUSDT", "ETH": "ETHUSDT"}
FIRST, LAST = "2026-08-19", "2026-10-13"
COLS = ["agg_trade_id", "price", "quantity", "first_trade_id", "last_trade_id", "transact_time", "is_buyer_maker"]
DTYPES = {"agg_trade_id": np.int64, "price": np.float64, "quantity": np.float64, "first_trade_id": np.int64,
          "last_trade_id": np.int64, "transact_time": np.int64, "is_buyer_maker": str}
# Порог «большого расхождения» сверки — зафиксирован ДО первого прогона: провал, если сравнено < 99% минут окна,
# или медиана относительной ошибки (taker_buy или volume) > 0.01%, или > 0.1% минут расходятся больше чем на 1%.
MIN_COVER, MAX_MEDIAN, BIG_REL, MAX_BIG_SHARE = 0.99, 1e-4, 0.01, 1e-3
BAR_COLS = ["bar_ts", "o", "h", "l", "c", "volume", "buy", "sell", "lw_buy", "lw_sell", "uw_buy", "uw_sell",
            "lw_n", "lw_strict_n", "uw_n", "uw_strict_n", "n_agg", "n_trades"]


def parse_trades(raw: bytes) -> dict:
    """CSV aggTrades (с заголовком или без) → массивы в порядке (время, agg_trade_id). buy — агрессор покупатель."""
    nl = raw.find(b"\n")
    first = raw[: nl if nl >= 0 else len(raw)].split(b",")[0].strip()
    header = not first.isdigit()
    df = pd.read_csv(io.BytesIO(raw), header=None, skiprows=1 if header else 0, names=COLS, dtype=DTYPES)
    ibm = df["is_buyer_maker"].str.strip().str.lower()
    bad = ~ibm.isin(["true", "false"])
    if bad.any():
        raise ValueError(f"is_buyer_maker: неожиданные значения {sorted(set(ibm[bad].head(5)))}")
    t = df["transact_time"].to_numpy(dtype=np.int64)
    unit = "ms"
    if len(t) and int(t.max()) > 10 ** 14:                           # микросекунды
        t = t // 1000
        unit = "us"
    aid = df["agg_trade_id"].to_numpy(dtype=np.int64)
    order = np.lexsort((aid, t))
    aid_s = aid[order]
    return {"t": t[order], "px": df["price"].to_numpy(dtype=float)[order],
            "q": df["quantity"].to_numpy(dtype=float)[order],
            "buy": (ibm.to_numpy() == "false")[order],
            "n_tr": (df["last_trade_id"].to_numpy(dtype=np.int64) - df["first_trade_id"].to_numpy(dtype=np.int64)
                     + 1)[order],
            "aid": aid_s, "header": header, "unit": unit,
            "aid_back": int(np.sum(np.diff(aid_s) < 0)) if len(aid_s) > 1 else 0}


def read_zip(path: Path) -> tuple[dict, str]:
    raw_zip = Path(path).read_bytes()
    with zipfile.ZipFile(io.BytesIO(raw_zip)) as z:
        names = [n for n in z.namelist() if not n.endswith("/")]
        if len(names) != 1 or not names[0].endswith(".csv"):
            raise ValueError(f"{path}: ожидался один CSV, есть {names}")
        raw = z.read(names[0])
    return parse_trades(raw), hashlib.sha256(raw_zip).hexdigest()


def _segments(key):
    st = np.flatnonzero(np.r_[True, key[1:] != key[:-1]])
    return st, np.r_[st[1:], len(key)]


def minute_agg(tr: dict) -> pd.DataFrame:
    """Минутные суммы из сделок (сделки уже по времени): ts, o/h/l/c, volume, buy (агрессор покупатель), сделки."""
    t, px, q = tr["t"], tr["px"], tr["q"]
    if not len(t):
        return pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume", "buy", "n_trades"])
    mid = t // MIN
    st, en = _segments(mid)
    return pd.DataFrame({"ts": mid[st] * MIN, "open": px[st], "high": np.maximum.reduceat(px, st),
                         "low": np.minimum.reduceat(px, st), "close": px[en - 1],
                         "volume": np.add.reduceat(q, st), "buy": np.add.reduceat(q * tr["buy"], st),
                         "n_trades": np.add.reduceat(tr["n_tr"], st)})


def bar_agg(tr: dict) -> pd.DataFrame:
    """15m-свечи UTC из сделок с объёмами агрессоров в фитилях (протокол footprint)."""
    t, px, q, buy = tr["t"], tr["px"], tr["q"], tr["buy"]
    if not len(t):
        return pd.DataFrame(columns=BAR_COLS)
    st, en = _segments(t // BAR)
    o, c = px[st], px[en - 1]
    lo_e, hi_e = np.minimum(o, c), np.maximum(o, c)
    seg = np.repeat(np.arange(len(st)), en - st)
    lw, lws = px <= lo_e[seg], px < lo_e[seg]
    uw, uws = px >= hi_e[seg], px > hi_e[seg]
    qb, qs = q * buy, q * ~buy

    def s(x):
        return np.add.reduceat(x, st)

    vol = s(q)
    bb = s(qb)
    return pd.DataFrame({"bar_ts": (t[st] // BAR) * BAR, "o": o, "h": np.maximum.reduceat(px, st),
                         "l": np.minimum.reduceat(px, st), "c": c, "volume": vol, "buy": bb, "sell": s(qs),
                         "lw_buy": s(qb * lw), "lw_sell": s(qs * lw), "uw_buy": s(qb * uw), "uw_sell": s(qs * uw),
                         "lw_n": s(lw.astype(np.int64)), "lw_strict_n": s(lws.astype(np.int64)),
                         "uw_n": s(uw.astype(np.int64)), "uw_strict_n": s(uws.astype(np.int64)),
                         "n_agg": en - st, "n_trades": s(tr["n_tr"])})


def rel_err(agg, kl):
    """|agg − kl| / kl; при kl = 0: 0, если и agg = 0, иначе inf."""
    agg, kl = np.asarray(agg, dtype=float), np.asarray(kl, dtype=float)
    with np.errstate(invalid="ignore", divide="ignore"):
        r = np.abs(agg - kl) / np.where(kl > 0, kl, 1.0)
    return np.where(kl > 0, r, np.where(agg == 0, 0.0, np.inf))


def _err_stats(r) -> dict:
    r = np.asarray(r, dtype=float)
    fin = r[np.isfinite(r)]
    return {"max": float(r.max()) if len(r) else None, "median": float(np.median(r)) if len(r) else None,
            "p99": float(np.percentile(fin, 99)) if len(fin) else None, "n_inf": int(np.sum(~np.isfinite(r))),
            "n_gt_1e-9": int(np.sum(r > 1e-9)), "n_gt_1e-4": int(np.sum(r > 1e-4)), "n_gt_1pct": int(np.sum(r > BIG_REL))}


def integrity(minutes: pd.DataFrame, kl: pd.DataFrame, t0: int, t1: int) -> dict:
    """Сверка минут сделок с минутными свечами в окне [t0, t1). Возвращает числа и вердикт по порогам выше."""
    k = kl[(kl["ts"] >= t0) & (kl["ts"] < t1)]
    a = minutes[(minutes["ts"] >= t0) & (minutes["ts"] < t1)]
    j = a.merge(k, on="ts", how="inner", suffixes=("_a", "_k"))
    window = int((t1 - t0) // MIN)
    rb, rv = rel_err(j["buy"], j["taker_buy"]), rel_err(j["volume_a"], j["volume_k"])
    k_only = k[~k["ts"].isin(a["ts"])]
    px_mis = {c: int(np.sum(~np.isclose(j[f"{c}_a"], j[f"{c}_k"], rtol=1e-9, atol=0.0)))
              for c in ("open", "high", "low", "close")}
    out = {"window_minutes": window, "kline_minutes": int(len(k)), "trade_minutes": int(len(a)),
           "compared": int(len(j)), "only_trades": int((~a["ts"].isin(k["ts"])).sum()),
           "only_klines": int(len(k_only)), "only_klines_nonzero_volume": int((k_only["volume"] > 0).sum()),
           "taker_buy": _err_stats(rb), "volume": _err_stats(rv), "price_mismatch_minutes": px_mis,
           "trades_count_mismatch": int(np.sum(j["n_trades_a"] != j["n_trades_k"])) if "n_trades_k" in j else None}
    # Объяснение расхождений по минутам (добавлено ПОСЛЕ первого прогона, когда порог по минутам не прошёл; пороги
    # не меняются): время aggTrade — время первого исполнения агрегата, а минутная свеча раскладывает исполнения по
    # их собственному времени. Тогда объём лишь переезжает в соседнюю минуту: накопленная разность Σ(сделки − свечи)
    # не растёт, суммы за 15 минут и за день совпадают, а open свечи = close прошлой минуты по сделкам.
    j = j.sort_values("ts").reset_index(drop=True)
    dv = (j["volume_a"] - j["volume_k"]).to_numpy()
    db = (j["buy"] - j["taker_buy"]).to_numpy()
    prev_close = np.r_[np.nan, j["close_a"].to_numpy()[:-1]]
    open_mis = ~np.isclose(j["open_a"], j["open_k"], rtol=1e-9, atol=0.0)
    day = j["ts"] // DAY
    gd = j.groupby(day)[["volume_a", "volume_k", "buy", "taker_buy"]].sum()
    b15 = j.groupby(j["ts"] // BAR)[["volume_a", "volume_k", "buy", "taker_buy"]].sum()
    rb15, rv15 = rel_err(b15["buy"], b15["taker_buy"]), rel_err(b15["volume_a"], b15["volume_k"])
    out["boundary"] = {
        "neighbour_corr_volume_diff": (float(np.corrcoef(dv[:-1], dv[1:])[0, 1])
                                       if len(dv) > 2 and np.std(dv[:-1]) > 0 and np.std(dv[1:]) > 0 else None),
        "cum_diff_volume_max_abs": float(np.max(np.abs(np.cumsum(dv)))) if len(dv) else None,
        "cum_diff_buy_max_abs": float(np.max(np.abs(np.cumsum(db)))) if len(db) else None,
        "cum_diff_volume_end": float(np.sum(dv)), "cum_diff_buy_end": float(np.sum(db)),
        "median_minute_volume": float(np.median(j["volume_k"])) if len(j) else None,
        "day_rel_max_volume": float(rel_err(gd["volume_a"], gd["volume_k"]).max()) if len(gd) else None,
        "day_rel_max_buy": float(rel_err(gd["buy"], gd["taker_buy"]).max()) if len(gd) else None,
        "bar15_volume": _err_stats(rv15), "bar15_buy": _err_stats(rb15),
        "open_mismatch": int(open_mis.sum()),
        "open_mismatch_kline_open_eq_prev_trade_close": int(np.sum(open_mis & np.isclose(j["open_k"], prev_close,
                                                                                         rtol=1e-9, atol=0.0)))}
    reasons = []
    if out["compared"] < MIN_COVER * window:
        reasons.append(f"сравнено {out['compared']} из {window} минут")
    for key in ("taker_buy", "volume"):
        st = out[key]
        if st["median"] is None or st["median"] > MAX_MEDIAN:
            reasons.append(f"{key}: медиана {st['median']}")
        if st["n_gt_1pct"] > MAX_BIG_SHARE * max(out["compared"], 1):
            reasons.append(f"{key}: минут с расхождением > 1% — {st['n_gt_1pct']}")
    out["ok"] = not reasons
    out["fail_reasons"] = reasons
    return out


def load_klines(root: Path, sym: str) -> tuple[pd.DataFrame, str]:
    p = root / "backtests" / "frozen" / f"{sym}_UM_1m.csv"
    raw = p.read_bytes()
    d = pd.read_csv(io.BytesIO(raw))
    d = d.rename(columns={"trades": "n_trades"})
    return d, hashlib.sha256(raw).hexdigest()


def build(sym: str, root: Path, first: str, last: str) -> dict:
    d0, d1 = date.fromisoformat(first), date.fromisoformat(last)
    src = root / "backtests" / "aggtrades" / sym
    bars, mins, files = [], [], []
    stats = {"days": 0, "trades": 0, "headers": 0, "units": set(), "out_of_day": 0, "aid_back": 0,
             "aid_gaps_in_day": 0, "aid_gaps_between_days": 0}
    prev_last_aid = None
    d = d0
    while d <= d1:
        name = f"{sym}-aggTrades-{d.isoformat()}.zip"
        tr, sha = read_zip(src / name)
        day_ms = (d - date(1970, 1, 1)).days * DAY
        out = (tr["t"] < day_ms) | (tr["t"] >= day_ms + DAY)
        if out.any():
            stats["out_of_day"] += int(out.sum())
            tr = {k: (v[~out] if isinstance(v, np.ndarray) else v) for k, v in tr.items()}
        aid = tr["aid"]
        if len(tr["q"]):
            stats["max_agg_qty"] = max(stats.get("max_agg_qty", 0.0), float(tr["q"].max()))
        if len(aid):
            ua = np.unique(aid)
            stats["aid_gaps_in_day"] += int(ua[-1] - ua[0] + 1 - len(ua))
            if prev_last_aid is not None and int(ua[0]) != prev_last_aid + 1:
                stats["aid_gaps_between_days"] += 1
            prev_last_aid = int(ua[-1])
        stats["days"] += 1
        stats["trades"] += int(len(tr["t"]))
        stats["headers"] += int(tr["header"])
        stats["units"].add(tr["unit"])
        stats["aid_back"] += tr["aid_back"]
        files.append({"file": name, "sha256": sha, "trades": int(len(tr["t"]))})
        bars.append(bar_agg(tr))
        mins.append(minute_agg(tr))
        print(f"  {name}: сделок {len(tr['t']):,}", flush=True)
        d += timedelta(days=1)
    stats["units"] = sorted(stats["units"])
    stats["files_sha256"] = hashlib.sha256("".join(f["sha256"] for f in files).encode()).hexdigest()
    b = pd.concat(bars, ignore_index=True)
    m = pd.concat(mins, ignore_index=True)
    bday = b["bar_ts"] // DAY
    per_day = bday.value_counts()
    stats["bars"] = int(len(b))
    stats["complete_days"] = int((per_day == 96).sum())
    stats["incomplete_days"] = sorted(int(x) for x in per_day[per_day != 96].index)
    return {"bars": b, "minutes": m, "stats": stats, "files": files,
            "t0": (d0 - date(1970, 1, 1)).days * DAY, "t1": ((d1 - date(1970, 1, 1)).days + 1) * DAY}


def _arg(name: str, default=None):
    return next((x.split("=", 1)[1] for x in sys.argv[1:] if x.startswith(f"--{name}=")), default)


def main() -> None:
    syms = [s for s in sys.argv[1:] if s in SYMS] or list(SYMS)
    root = Path(_arg("data-root", str(ROOT)))
    first, last = _arg("from", FIRST), _arg("to", LAST)
    failed = False
    for s in syms:
        sym = SYMS[s]
        print(f"{sym}: чтение архивов {first} … {last}", flush=True)
        r = build(sym, root, first, last)
        kl, kl_sha = load_klines(root, sym)
        integ = integrity(r["minutes"], kl, r["t0"], r["t1"])
        # 15m o/h/l/c из сделок против 15m из минутных свечей (вход/выход теста берутся из свечей сделок)
        kb = kl[(kl["ts"] >= r["t0"]) & (kl["ts"] < r["t1"])].copy()
        kb["bar_ts"] = kb["ts"] // BAR * BAR
        g = kb.groupby("bar_ts")
        k15 = pd.DataFrame({"ko": g["open"].first(), "kc": g["close"].last(), "kv": g["volume"].sum(),
                            "ktb": g["taker_buy"].sum()}).reset_index()
        jb = r["bars"].merge(k15, on="bar_ts", how="inner")
        integ["bars_15m"] = {"compared": int(len(jb)),
                             "open_mismatch": int(np.sum(~np.isclose(jb["o"], jb["ko"], rtol=1e-9, atol=0))),
                             "close_mismatch": int(np.sum(~np.isclose(jb["c"], jb["kc"], rtol=1e-9, atol=0))),
                             "volume_rel_max": float(rel_err(jb["volume"], jb["kv"]).max()),
                             "buy_rel_max": float(rel_err(jb["buy"], jb["ktb"]).max())}
        override = bool(not integ["ok"] and "--proceed-despite-minute-gate" in sys.argv)
        rep = {"symbol": sym, "klines_sha256": kl_sha, "stats": r["stats"], "files": r["files"], "integrity": integ,
               "override_minute_gate": override}
        out_dir = root / "backtests" / "aggtrades"
        (out_dir / f"{sym}_footprint_integrity.json").write_text(
            json.dumps(rep, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
        tb, vv, bd = integ["taker_buy"], integ["volume"], integ["boundary"]
        print(f"{sym}: дней {r['stats']['days']}, сделок {r['stats']['trades']:,}, заголовок в {r['stats']['headers']} "
              f"файлах, время {r['stats']['units']}, вне дня {r['stats']['out_of_day']}, 15m-свечей "
              f"{r['stats']['bars']}, полных дней {r['stats']['complete_days']}")
        print(f"  сверка минут: сравнено {integ['compared']} из {integ['window_minutes']} (только в сделках "
              f"{integ['only_trades']}, только в свечах {integ['only_klines']}, из них с объёмом "
              f"{integ['only_klines_nonzero_volume']}); taker_buy: макс {tb['max']:.3g}, медиана {tb['median']:.3g}, "
              f"> 1e-9: {tb['n_gt_1e-9']}, > 1%: {tb['n_gt_1pct']}; volume: макс {vv['max']:.3g}, медиана "
              f"{vv['median']:.3g}, > 1e-9: {vv['n_gt_1e-9']}, > 1%: {vv['n_gt_1pct']}; цены минут не совпали "
              f"{integ['price_mismatch_minutes']}; число сделок не совпало {integ['trades_count_mismatch']}; "
              f"15m: {integ['bars_15m']}")
        print(f"  переезд объёма между соседними минутами: корр. соседних разностей "
              f"{bd['neighbour_corr_volume_diff']:+.3f}; накопленная разность объёма макс {bd['cum_diff_volume_max_abs']:.4g}, "
              f"на конце {bd['cum_diff_volume_end']:.3g} (медиана минуты {bd['median_minute_volume']:.4g}, крупнейший "
              f"агрегат {r['stats'].get('max_agg_qty', float('nan')):.4g}); покупок макс {bd['cum_diff_buy_max_abs']:.4g}, "
              f"на конце {bd['cum_diff_buy_end']:.3g}; за день макс отн. объём {bd['day_rel_max_volume']:.3g}, покупки "
              f"{bd['day_rel_max_buy']:.3g}; 15m объём медиана {bd['bar15_volume']['median']:.3g} p99 "
              f"{bd['bar15_volume']['p99']:.3g} макс {bd['bar15_volume']['max']:.3g}, покупки медиана "
              f"{bd['bar15_buy']['median']:.3g} p99 {bd['bar15_buy']['p99']:.3g} макс {bd['bar15_buy']['max']:.3g}; "
              f"open не совпал {bd['open_mismatch']}, из них open свечи = close прошлой минуты по сделкам "
              f"{bd['open_mismatch_kline_open_eq_prev_trade_close']}")
        if not integ["ok"]:
            print(f"  ПОРОГ СВЕРКИ ПО МИНУТАМ НЕ ПРОЙДЕН: {integ['fail_reasons']}")
            if not override:
                failed = True
                print("  свечи не записаны (запись — только с --proceed-despite-minute-gate, решение — в отчёте)")
                continue
            print("  --proceed-despite-minute-gate: свечи пишутся, отметка в *_footprint_integrity.json")
        r["bars"][BAR_COLS].to_csv(out_dir / f"{sym}_15m_footprint.csv", index=False)
        print(f"  записано {out_dir / f'{sym}_15m_footprint.csv'}")
    if failed:
        sys.exit(2)


if __name__ == "__main__":
    main()
