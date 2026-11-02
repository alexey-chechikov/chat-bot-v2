"""Утверждения оператора по CoinGlass/TradingView (PREREG.md, K1–K7) и корреляции факторов — с контролем.

Данные: research/coinglass_compare/data/<SYM>_1h.csv (экспорт TV CoinGlass, 10 монет, 01.05–28.10.2026, 1h; в
выборке — именно этот период оператор читал по скриншотам); BTC 15.05.2024–14.10.2026 — поток тейкеров Binance UM
(backtests/frozen/BTCUSDT_UM_1m.csv, копия в scratchpad); K7 — минутки BTC 2018–2026 (mr_data).
Исход — от close часа события до close через 24/72 ч. События монеты не чаще раза в 24 ч. Контроль — 999 случайных
наборов часов той же монеты того же размера; сводка по монетам — общий сдвиг всех событий на один случайный сдвиг
(монеты не независимы). Ранг (k+1)/(n+1) в сторону, которую ждёт оператор. Ничего не подбиралось: пороги из PREREG."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import mr_data as md  # noqa: E402

ROOT = HERE.parents[1]
CG = ROOT / "research" / "coinglass_compare" / "data"
COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT",
         "LTCUSDT"]
RNG = np.random.default_rng(20261102)
N_CTL = 999


def load_cg(sym):
    d = pd.read_csv(CG / f"{sym}_1h.csv")
    d["t"] = pd.to_datetime(d["bar_utc"]).astype("int64") // 10 ** 9
    d = d.set_index("t").sort_index()
    full = np.arange(d.index[0], d.index[-1] + 3600, 3600)
    d = d.reindex(full)
    c = d["close"]
    f = pd.DataFrame(index=d.index)
    f["c"] = c
    f["ret1"] = c / c.shift(1) - 1
    f["ret24"] = c / c.shift(24) - 1
    f["fwd24"] = c.shift(-24) / c - 1
    f["fwd72"] = c.shift(-72) / c - 1
    path = c.diff().abs().rolling(72).sum().shift(-72)
    f["er72"] = (c.shift(-72) - c).abs() / path
    tb, ts_, td = d["taker_buy"], d["taker_sell"].abs(), d["taker_delta"]
    f["tk1"] = td / (tb + ts_)
    f["tk24"] = td.rolling(24).sum() / (tb + ts_).rolling(24).sum()
    have_liq = d["liq_all_long"].notna() | d["liq_all_short"].notna()
    first = have_liq.idxmax()
    lL = d["liq_all_long"].where(d.index < first, d["liq_all_long"].fillna(0))
    lS = d["liq_all_short"].abs().where(d.index < first, d["liq_all_short"].abs().fillna(0))
    f["liqL1"], f["liqS1"] = lL, lS
    f["liqL24"], f["liqS24"] = lL.rolling(24).sum(), lS.rolling(24).sum()
    f["liqL24_med30"] = f["liqL24"].rolling(720, min_periods=240).median().shift(1)
    f["liqS24_med30"] = f["liqS24"].rolling(720, min_periods=240).median().shift(1)
    f["wi2"], f["ls_acc"], f["ls_top"] = d["wi2"], d["ls_acc"], d["ls_top_pos"]
    f["ba24"] = d["bid_ask_delta"].rolling(24).mean()
    f["ba1"] = d["bid_ask_delta"]
    f["fr"] = d["fr_oiw_pct"]
    f["fr_pos72"] = (d["fr_oiw_pct"] > 0).astype(float).where(d["fr_oiw_pct"].notna()).rolling(72).min().shift(1)
    f["doi"] = d["oi_coins"] / d["oi_coins"].shift(1) - 1
    return f


def declust(t_list, gap=86400):
    out, last = [], -10 ** 12
    for t in t_list:
        if t - last >= gap:
            out.append(t)
            last = t
    return np.array(out, dtype=np.int64)


CLAIMS = {
    "K1": ("покупки на падении → вверх", lambda f: (f["ret24"] <= -0.02) & (f["tk24"] > 0), "fwd72", "up"),
    "K2": ("продажи на росте → вниз", lambda f: (f["ret24"] >= 0.02) & (f["tk24"] < 0), "fwd72", "down"),
    "K3": ("киты в шортах + продажи в стакане → падение продолжится",
           lambda f: (f["wi2"] < 0) & (f["ba24"] < 0) & (f["ret24"] < 0), "fwd72", "down"),
    "K4": ("смена фандинга в минус → дно", lambda f: (f["fr"] <= 0) & (f["fr_pos72"] == 1), "fwd72", "up"),
    "K5": ("ликвидации лонгов на росте → вниз", lambda f: (f["ret24"] > 0) & (f["liqL24"] > 2 * f["liqS24"]),
           "fwd72", "down"),
    "K6": ("ликвидации обеих сторон + киты против толпы → флет",
           lambda f: (f["liqL24"] >= f["liqL24_med30"]) & (f["liqS24"] >= f["liqS24_med30"])
           & (np.sign(f["wi2"]) * np.sign(f["ls_acc"] - 1) < 0), "er72", "down"),
}


def rank(real, ctl, direction):
    k = int((ctl >= real).sum()) if direction == "up" else int((ctl <= real).sum())
    return (k + 1) / (len(ctl) + 1)


def event_study(F, name, cond, out_col, direction):
    res, pooled = {}, []
    for sym, f in F.items():
        elig = f[out_col].notna() & f["ret24"].notna()
        m = cond(f).fillna(False) & elig
        ev = declust(f.index[m].to_numpy())
        y = f.loc[ev, out_col].to_numpy()
        pool = f.loc[elig, out_col].to_numpy()
        if len(ev) == 0:
            res[sym] = {"n": 0}
            continue
        ctl = np.array([RNG.choice(pool, len(ev), replace=False).mean() for _ in range(N_CTL)])
        res[sym] = {"n": len(ev), "mean": round(float(y.mean()) * (1 if out_col == "er72" else 100), 3),
                    "base": round(float(pool.mean()) * (1 if out_col == "er72" else 100), 3),
                    "rank": round(rank(y.mean(), ctl, direction), 3),
                    "hit": round(float((y > 0).mean() if direction == "up" else (y < 0).mean()), 2)
                    if out_col != "er72" else None}
        pooled += [(sym, t) for t in ev]
    # общий сдвиг: все события всех монет на один сдвиг (монеты не независимы)
    idx = F["BTCUSDT"].index.to_numpy()
    span = idx[-1] - idx[0] + 3600
    vals = {s: f[out_col] for s, f in F.items()}

    def stat(shift):
        acc = []
        for s, t in pooled:
            tt = idx[0] + (t - idx[0] + shift) % span
            v = vals[s].get(tt, np.nan)
            if np.isfinite(v):
                acc.append(v)
        return np.mean(acc) if acc else np.nan

    real = stat(0)
    shifts = RNG.integers(1, span // 3600, N_CTL) * 3600
    ctl = np.array([stat(int(s)) for s in shifts])
    ctl = ctl[np.isfinite(ctl)]
    sig = sum(1 for r in res.values() if r.get("n", 0) and r["rank"] <= 0.05)
    mul = 1 if out_col == "er72" else 100
    summ = {"claim": name, "n_events": len(pooled), "pooled_mean": round(float(real) * mul, 3),
            "ctl_median": round(float(np.median(ctl)) * mul, 3), "rank_common_shift": round(rank(real, ctl, direction), 3),
            "coins_rank_le_0.05": sig, "per_coin": res}
    return summ


def corr_table(F):
    """Одновременная связь (час к часу) и опережающая (сумма за 24 ч → следующие 24 ч, срезы раз в сутки без
    перекрытия) — по каждой монете; медиана по монетам и число монет с |r| > 2/√N."""
    feats = {"поток тейкеров": ("tk1", "tk24"), "ликвидации L−S": (None, None), "фандинг": ("fr", "fr"),
             "Δ OI": ("doi", None), "WI2": ("wi2", "wi2"), "L/S аккаунтов": ("ls_acc", "ls_acc"),
             "L/S топ-позиций": ("ls_top", "ls_top"), "стакан bid−ask": ("ba1", "ba24")}
    out = {}
    for nm, (c1, c24) in feats.items():
        cc, ll = [], []
        for sym, f in F.items():
            g = f.copy()
            if nm == "ликвидации L−S":
                g["x1"] = (g["liqL1"] - g["liqS1"]) / (g["liqL1"] + g["liqS1"]).replace(0, np.nan)
                g["x24"] = (g["liqL24"] - g["liqS24"]) / (g["liqL24"] + g["liqS24"]).replace(0, np.nan)
            elif nm == "Δ OI":
                g["x1"] = g["doi"]
                g["x24"] = g["c"] * 0 + (1 + g["doi"]).rolling(24).apply(np.prod, raw=True) - 1
            else:
                g["x1"], g["x24"] = g[c1], g[c24]
            if nm in ("WI2", "L/S аккаунтов", "L/S топ-позиций"):
                g["x1"] = g["x1"].diff()                      # уровни трендуют — для одновременной связи изменения
            a = g[["x1", "ret1"]].dropna()
            cc.append(a["x1"].corr(a["ret1"]))
            s = g.iloc[::24][["x24", "fwd24"]].dropna()
            ll.append((s["x24"].corr(s["fwd24"]), len(s)))
        out[nm] = {"одновременно_медиана": round(float(np.median(cc)), 3),
                   "одновременно_по_монетам": [round(float(x), 2) for x in cc],
                   "вперёд24_медиана": round(float(np.median([x for x, _ in ll])), 3),
                   "вперёд24_монет_значимо": sum(1 for x, n in ll if abs(x) > 2 / np.sqrt(n)),
                   "вперёд24_по_монетам": [round(float(x), 2) for x, _ in ll]}
    return out


def btc_um_claims():
    """K1, K2 и проверка GPT «цена 6ч вверх / поток 6ч вниз → 65% снижений» на BTC 2y Binance UM."""
    p = md.SCR / "BTCUSDT_UM_1m.csv"
    d = pd.read_csv(p, usecols=["ts", "close", "volume", "taker_buy"])
    print(f"UM {p.name}: {len(d)} строк, sha256 {md.sha(p)}…", file=sys.stderr)
    t = d["ts"].to_numpy(np.int64) // 1000 // 3600 * 3600
    g = d.groupby(t)
    h = pd.DataFrame({"c": g["close"].last(), "v": g["volume"].sum(), "tb": g["taker_buy"].sum()})
    h = h.reindex(np.arange(h.index[0], h.index[-1] + 3600, 3600))
    h["delta"] = 2 * h["tb"] - h["v"]
    f = pd.DataFrame(index=h.index)
    f["ret24"] = h["c"] / h["c"].shift(24) - 1
    f["tk24"] = h["delta"].rolling(24).sum() / h["v"].rolling(24).sum()
    f["fwd24"] = h["c"].shift(-24) / h["c"] - 1
    f["fwd72"] = h["c"].shift(-72) / h["c"] - 1
    out = {}
    for k in ("K1", "K2"):
        nm, cond, col, dr = CLAIMS[k]
        elig = f[col].notna() & f["ret24"].notna() & f["tk24"].notna()
        ev = declust(f.index[(cond(f).fillna(False) & elig)].to_numpy())
        y = f.loc[ev, col].to_numpy()
        pool = f.loc[elig, col].to_numpy()
        ctl = np.array([RNG.choice(pool, len(ev), replace=False).mean() for _ in range(N_CTL)])
        half = ev < ev[len(ev) // 2] if len(ev) else ev
        out[k] = {"claim": nm, "n": len(ev), "mean_fwd72_%": round(float(y.mean()) * 100, 3),
                  "base_%": round(float(pool.mean()) * 100, 3), "rank": round(rank(y.mean(), ctl, dr), 3),
                  "half1_%": round(float(y[half].mean()) * 100, 3), "half2_%": round(float(y[~half].mean()) * 100, 3)}
    # GPT §6: срез раз в сутки после 23:00 UTC, знак цены за 6 ч и знак потока за 6 ч → следующие 24 ч от open
    f6 = pd.DataFrame(index=h.index)
    f6["p6"] = h["c"] / h["c"].shift(6) - 1
    f6["d6"] = h["delta"].rolling(6).sum()
    f6["nxt"] = h["c"].shift(-24) / h["c"] - 1
    s = f6[(f6.index % 86400) == 23 * 3600].dropna()
    tab = {}
    for pu in (True, False):
        for du in (True, False):
            q = s[((s["p6"] > 0) == pu) & ((s["d6"] > 0) == du)]
            n, k = len(q), int((q["nxt"] < 0).sum())
            z = 1.96
            ph = k / n if n else np.nan
            den = 1 + z * z / n
            ctr = (ph + z * z / (2 * n)) / den
            hw = z * np.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n)) / den
            tab[f"цена6ч {'↑' if pu else '↓'} / поток6ч {'↑' if du else '↓'}"] = {
                "n": n, "доля_снижений": round(ph, 3), "wilson95": [round(ctr - hw, 3), round(ctr + hw, 3)],
                "среднее_24ч_%": round(float(q["nxt"].mean()) * 100, 3)}
    out["GPT_6h_divergence_2y"] = tab
    out["window"] = [str(pd.to_datetime(h.index[0], unit="s")), str(pd.to_datetime(h.index[-1], unit="s"))]
    return out


def k7_touch():
    """K7: касание EMA200 4H сверху при дневном режиме SMA100 вверх → следующие 72 ч (BTC, 2018–2026)."""
    m, h1, h4, d1, fund = md.build()
    k4, L4, C4, B4 = (h4[c].to_numpy() for c in ("known", "low", "close", "B"))
    reg = d1["reg0"]
    up = np.array([reg.get(t // 86400 * 86400, np.nan) == 1.0 for t in k4])
    ser = pd.Series(C4, index=k4)
    fwd = ser.shift(-18) / ser - 1                                    # 18 баров 4H = 72 ч
    ok = (k4 >= pd.Timestamp("2018-01-01", tz="UTC").timestamp()) & fwd.notna().to_numpy()
    ev_m = np.r_[False, (L4[1:] <= B4[1:]) & (C4[:-1] > B4[:-1])] & up & ok
    ev = declust(k4[ev_m])
    y = fwd.loc[ev].to_numpy()
    pool = fwd[up & ok].to_numpy()
    ctl = np.array([RNG.choice(pool, len(ev), replace=False).mean() for _ in range(N_CTL)])
    cut = pd.Timestamp("2024-05-15", tz="UTC").timestamp()
    return {"claim": "касание синей (EMA200 4H) сверху при SMA100 вверх → вниз", "n": len(ev),
            "mean_fwd72_%": round(float(y.mean()) * 100, 3), "base_up_regime_%": round(float(pool.mean()) * 100, 3),
            "rank_down": round(rank(y.mean(), ctl, "down"), 3), "share_down": round(float((y < 0).mean()), 3),
            "до_2024-05_%": round(float(y[ev < cut].mean()) * 100, 3), "после_%": round(float(y[ev >= cut].mean()) * 100, 3),
            "n_до": int((ev < cut).sum()), "n_после": int((ev >= cut).sum())}


def main():
    F = {s: load_cg(s) for s in COINS}
    # проверка знака ликвидаций: часы с перевесом ликвидаций ЛОНГОВ должны падать
    chk = {}
    for s, f in F.items():
        x = (f["liqL1"] - f["liqS1"]) / (f["liqL1"] + f["liqS1"]).replace(0, np.nan)
        a = pd.concat([x, f["ret1"]], axis=1).dropna()
        chk[s] = round(float(a.iloc[:, 0].corr(a.iloc[:, 1])), 3)
    print("знак ликвидаций (corr перевеса лонг-ликвидаций с доходностью часа, ждём < 0):", chk)
    res = {"liq_sign_check": chk, "claims": {}}
    for k, (nm, cond, col, dr) in CLAIMS.items():
        r = event_study(F, nm, cond, col, dr)
        res["claims"][k] = r
        unit = "" if col == "er72" else "%"
        print(f"{k} {nm}: событий {r['n_events']}, среднее {r['pooled_mean']}{unit} против контроля "
              f"{r['ctl_median']}{unit}, ранг общего сдвига {r['rank_common_shift']}, монет с рангом ≤0.05: "
              f"{r['coins_rank_le_0.05']}/10; BTC {r['per_coin']['BTCUSDT']}", flush=True)
    res["corr"] = corr_table(F)
    for k, v in res["corr"].items():
        print(f"корр {k}: одновременно {v['одновременно_медиана']}, вперёд 24ч {v['вперёд24_медиана']} "
              f"(значимо {v['вперёд24_монет_значимо']}/10)", flush=True)
    res["btc_um_2y"] = btc_um_claims()
    print("BTC UM 2y:", json.dumps(res["btc_um_2y"], ensure_ascii=False), flush=True)
    res["K7"] = k7_touch()
    print("K7:", res["K7"], flush=True)
    out = HERE / "out"
    out.mkdir(exist_ok=True)
    (out / "cg_claims_result.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
