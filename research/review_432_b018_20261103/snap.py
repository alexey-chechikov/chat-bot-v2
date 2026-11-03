"""Точки входа/выхода 432 (BTC/ETH H4, 2018–2026) и B018: средние оператора H1/H4 и CoinGlass 1h. Правила — PREREG.md.
Запуск: snap.py --pk-btc=<bars_*.pkl BTC> --pk-eth=<bars_*.pkl ETH>  (кэш mr_data.build; nice 20)."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "research" / "tv_lab_1025"))
from validate_432 import s432  # noqa: E402

OUT = HERE / "out"
CG = ROOT / "research" / "coinglass_compare" / "data"
COST = 0.00048 + 0.0002
SPLIT = int(pd.Timestamp("2024-08-01", tz="UTC").timestamp())
H4 = 14400
RNG = np.random.default_rng(20261103)
NPERM = 9999

# B018 по таблице Codex (WEEX_GPT_B018_SPLIT_EXIT_AND_432_SCOPE_2026-11-03.md §3 и all_trade_costs.csv): вход, сторона,
# выход исходный / EMA3, net исходный / EMA3
B018 = [
    ("2026-06-12 20:00", -1, "2026-06-13 21:00", "2026-06-13 21:00", -1.5255, -1.5255),
    ("2026-07-06 08:00", -1, "2026-07-06 13:00", "2026-07-06 13:00", 1.5365, 1.5365),
    ("2026-07-07 08:00", -1, "2026-07-10 16:00", "2026-07-10 12:00", -1.2504, -1.9864),
    ("2026-07-26 00:00", 1, "2026-07-26 22:00", "2026-07-26 22:00", 1.2852, 1.2852),
    ("2026-07-29 12:00", 1, "2026-07-31 14:00", "2026-07-30 00:00", -3.0433, -0.6268),
    ("2026-08-31 04:00", 1, "2026-08-31 16:00", "2026-08-31 16:00", 1.3099, 1.3099),
    ("2026-09-08 20:00", 1, "2026-09-09 08:00", "2026-09-09 08:00", 1.3704, 1.3704),
    ("2026-09-11 20:00", 1, "2026-09-14 20:00", "2026-09-14 20:00", 1.5185, 1.5185),
    ("2026-09-17 00:00", 1, "2026-09-18 08:00", "2026-09-18 08:00", 1.4853, 1.4853),
    ("2026-10-09 00:00", 1, "2026-10-11 15:00", "2026-10-11 15:00", 1.5794, 1.5794),
    ("2026-10-15 20:00", 1, "2026-10-19 04:00", "2026-10-17 00:00", 0.1649, -0.5322),
    ("2026-10-29 04:00", -1, "2026-10-30 18:00", "2026-10-30 18:00", 5.7539, 5.7539),
]


def ts(s: str) -> int:
    return int(pd.Timestamp(s, tz="UTC").timestamp())


def arg(name: str) -> Path:
    v = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith(f"--{name}=")), None)
    if v is None:
        sys.exit(f"нужен --{name}=")
    return Path(v)


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def load(pk: Path):
    m, h1, h4, d1, fund = pd.read_pickle(pk)
    print(f"кэш {pk.name}: sha256 {sha(pk)[:16]}…, H4 {len(h4)} баров "
          f"{pd.to_datetime(h4.index[0], unit='s')} → {pd.to_datetime(h4.index[-1], unit='s')}", flush=True)
    del m
    return h1, h4, fund


# ------------------------------------------------------------------ снимки
MA_COLS = ("G", "Y", "R", "B")


def ma_snap(b: pd.DataFrame, T: int, pre: str) -> dict:
    i = int(np.searchsorted(b["known"].to_numpy(), T, side="right")) - 1
    r = b.iloc[i]
    c = r["close"]
    d = {f"{pre}_{k}": int(c > r[k]) for k in MA_COLS}
    d[f"{pre}_zone"] = int(r["zone"])
    d[f"{pre}_stack"] = int(r["G"] > r["Y"] > r["R"])
    d[f"{pre}_dB"] = 100 * (c / r["B"] - 1)
    d[f"{pre}_dR"] = 100 * (c / r["R"] - 1)
    return d


def ma_arrays(b: pd.DataFrame) -> dict:
    c = b["close"].to_numpy()
    out = {k: (c > b[k].to_numpy()).astype(int) for k in MA_COLS}
    out["zone"] = b["zone"].to_numpy().astype(int)
    out["stack"] = ((b["G"] > b["Y"]) & (b["Y"] > b["R"])).to_numpy().astype(int)
    return out


class CGData:
    """CoinGlass 1h: признаки на момент T по закрытым часам + перцентили внутри ряда."""

    def __init__(self, sym: str):
        p = CG / f"{sym}_1h.csv"
        man = json.loads((CG / f"{sym}_1h.manifest.json").read_text())
        d = pd.read_csv(p)
        print(f"CoinGlass {p.name}: {len(d)} строк, sha256 {sha(p)[:16]}… (манифест {man['sha256'][:16]}…)", flush=True)
        d["t"] = pd.to_datetime(d["bar_utc"]).astype("int64") // 10**9
        d = d.set_index("t").sort_index()
        flow_den = (d["taker_buy"] - d["taker_sell"]).rolling(6).sum()
        f = pd.DataFrame(index=d.index)
        f["flow6"] = 100 * d["taker_delta"].rolling(6).sum() / flow_den
        f["liqL6"] = d["liq_all_long"].fillna(0).rolling(6).sum()
        f["liqS6"] = d["liq_all_short"].abs().fillna(0).rolling(6).sum()
        f["liqLshare6"] = f["liqL6"] / (f["liqL6"] + f["liqS6"])
        f["dOI6"] = 100 * (d["oi_coins"] / d["oi_coins"].shift(6) - 1)
        f["dOI24"] = 100 * (d["oi_coins"] / d["oi_coins"].shift(24) - 1)
        f["fr"] = d["fr_oiw_pct"]
        f["ba6"] = d["bid_ask_delta"].rolling(6).mean()
        f["wi2"] = d["wi2"]
        f["ls_acc"] = d["ls_acc"]
        f["ls_top"] = d["ls_top_pos"]
        f["ret6"] = 100 * (d["close"] / d["close"].shift(6) - 1)
        f = f[d["wi2"].notna() | d["taker_delta"].notna()]
        self.f = f
        self.known = f.index.to_numpy() + 3600
        self.pct = f.rank(pct=True)
        # проверка меток ликвидаций: лонги ликвидируют на падениях (corr < 0), шорты — на ростах (corr > 0)
        ret = d["close"] / d["open"] - 1
        self.liq_check = {"corr_liqL_ret1h": float(d["liq_all_long"].corr(ret)),
                          "corr_liqS_ret1h": float(d["liq_all_short"].abs().corr(ret))}

    def snap(self, T: int, pre: str) -> dict:
        i = int(np.searchsorted(self.known, T, side="right")) - 1
        if i < 0 or T - self.known[i] > 3600:
            return {}
        r, q = self.f.iloc[i], self.pct.iloc[i]
        out = {}
        for k in self.f.columns:
            out[f"{pre}_cg_{k}"] = float(r[k])
            out[f"{pre}_cgp_{k}"] = float(q[k])
        return out


# ------------------------------------------------------------------ 432
def trades432(h4: pd.DataFrame, fund: pd.Series) -> pd.DataFrame:
    o = h4["open"].to_numpy()
    arr = tuple(h4[k].to_numpy() for k in ("open", "high", "low", "close"))
    t = h4.index.to_numpy()
    ft, fr = fund.index.to_numpy(), fund.to_numpy()
    cs = np.r_[0.0, np.cumsum(fr)]
    lo30 = pd.Series(h4["low"].to_numpy()).shift(1).rolling(30).min().to_numpy()
    c = h4["close"].to_numpy()
    rows = []
    for j, k, _s, pin, pout, why in s432(arr):
        if why == "конец":
            continue
        fsum = cs[np.searchsorted(ft, t[k])] - cs[np.searchsorted(ft, t[j])]
        gross = pout / pin - 1
        reason = "канал" if c[k - 1] < lo30[k - 1] else "20 баров"
        r = {"j": j, "k": k, "te": int(t[j]), "tx": int(t[k]), "bars": k - j, "gross": gross,
             "net": gross - 2 * COST - fsum, "reason": reason}
        for hz in (20, 40):
            r[f"fwd{hz}"] = o[k + hz] / o[k] - 1 if k + hz < len(o) else np.nan
        # вариант «без предела 20 баров»: держать до close < низа канала 30 (выход open следующего)
        kk = k if reason == "канал" else next((i + 1 for i in range(k - 1, len(c) - 1) if c[i] < lo30[i]), None)
        if kk is None:
            r["net_nocap"] = np.nan
        else:
            f2 = cs[np.searchsorted(ft, t[kk])] - cs[np.searchsorted(ft, t[j])]
            r["net_nocap"] = o[kk] / pin - 1 - 2 * COST - f2
            r["bars_nocap"] = kk - j
        rows.append(r)
    return pd.DataFrame(rows)


def perm_diff(y: np.ndarray, g: np.ndarray) -> tuple[float, float, int, int]:
    g = g.astype(bool)
    n1, n0 = int(g.sum()), int((~g).sum())
    if n1 < 10 or n0 < 10:
        return np.nan, np.nan, n1, n0
    d = y[g].mean() - y[~g].mean()
    cnt = 0
    for _ in range(NPERM):
        p = RNG.permutation(g)
        cnt += abs(y[p].mean() - y[~p].mean()) >= abs(d) - 1e-15
    return float(d), (cnt + 1) / (NPERM + 1), n1, n0


ENTRY_FEATS = [("h1", k) for k in ("G", "Y", "R", "B", "zone", "stack")] + [("h4", k) for k in ("G", "Y", "R", "zone", "stack")]


def feat_val(df: pd.DataFrame, pre: str, tf: str, k: str) -> np.ndarray:
    col = f"{pre}_{tf}_{k}"
    v = df[col].to_numpy()
    return (v == 1).astype(int)


def analyse_coin(sym: str, h1, h4, fund, cg: CGData) -> tuple[pd.DataFrame, dict]:
    tr = trades432(h4, fund)
    snaps = []
    for _, r in tr.iterrows():
        s = {}
        for pre, T in (("in", r["te"]), ("out", r["tx"])):
            s.update({f"{pre}_{k}": v for k, v in ma_snap(h1, T, "h1").items()})
            s.update({f"{pre}_{k}": v for k, v in ma_snap(h4, T, "h4").items()})
            s.update(cg.snap(T, pre))
        snaps.append(s)
    tr = pd.concat([tr, pd.DataFrame(snaps)], axis=1)
    tr["sym"] = sym
    tr["entry"] = pd.to_datetime(tr["te"], unit="s")
    tr["exit"] = pd.to_datetime(tr["tx"], unit="s")
    tr = tr[tr["te"] >= ts("2018-01-01")].reset_index(drop=True)
    res = {"n": len(tr), "n_p1": int((tr["te"] < SPLIT).sum()), "n_p2": int((tr["te"] >= SPLIT).sum()),
           "net_mean_pct": 100 * tr["net"].mean(), "win_pct": 100 * (tr["net"] > 0).mean()}

    # E: признаки входа
    y = tr["net"].to_numpy()
    half = tr["te"].to_numpy() >= SPLIT
    E = {}
    for tf, k in ENTRY_FEATS:
        g = feat_val(tr, "in", tf, k)
        d, p, n1, n0 = perm_diff(y, g)
        h = []
        for m in (~half, half):
            gg = g[m].astype(bool)
            h.append(float(y[m][gg].mean() - y[m][~gg].mean()) if gg.sum() >= 3 and (~gg).sum() >= 3 else np.nan)
        E[f"{tf}_{k}"] = {"diff_pct": 100 * d if d == d else None, "p": p if p == p else None, "n_yes": n1,
                          "n_no": n0, "share_yes": n1 / len(g), "diff_p1_pct": 100 * h[0], "diff_p2_pct": 100 * h[1]}
    res["E"] = E

    # доля признаков при входе против случайных H4-баров выше EMA200 (тот же режим)
    a4, a1 = ma_arrays(h4), ma_arrays(h1)
    c4, b4 = h4["close"].to_numpy(), h4["B"].to_numpy()
    t4 = h4.index.to_numpy()
    ok = np.flatnonzero((c4 > b4) & (t4 >= ts("2018-01-01")) & (t4 < t4[-1] - 50 * H4))
    known1 = h1["known"].to_numpy()
    base = {}
    for tf, k in ENTRY_FEATS:
        if tf == "h4":
            v = (a4[k][ok] == 1).mean()
        else:
            i1 = np.searchsorted(known1, t4[ok] + H4, side="right") - 1
            v = (a1[k][i1] == 1).mean()
        base[f"{tf}_{k}"] = float(v)
    res["random_regime_share"] = base

    # X: после выхода — 20 H4 вперёд против случайных баров выше EMA200
    o4 = h4["open"].to_numpy()
    # случайный бар i (close > EMA200): решение на его закрытии, доход от open i+1 на 20 H4 — как после выхода 432
    fwd_all = np.full(len(o4), np.nan)
    fwd_all[:-21] = o4[21:] / o4[1:-20] - 1
    okf = ok[np.isfinite(fwd_all[ok])]
    X = {}
    for name, m in (("все", np.ones(len(tr), bool)), ("20 баров", tr["reason"].eq("20 баров").to_numpy()),
                    ("канал", tr["reason"].eq("канал").to_numpy())):
        f = tr.loc[m, "fwd20"].dropna().to_numpy()
        if len(f) < 5:
            continue
        ctl = np.array([fwd_all[RNG.choice(okf, len(f))].mean() for _ in range(2000)])
        X[name] = {"n": len(f), "fwd20_mean_pct": 100 * f.mean(), "ctl_median_pct": 100 * float(np.median(ctl)),
                   "rank": float((1 + (ctl >= f.mean()).sum()) / 2001)}
    # зона H4 при выходе (+1 — тренд по средним жив) → доход после выхода; та же разница на всех барах выше EMA200
    f = tr["fwd20"].to_numpy()
    mfin = np.isfinite(f)
    g = (tr["out_h4_zone"].to_numpy() == 1)
    d, p, n1, n0 = perm_diff(f[mfin], g[mfin])
    gen = fwd_all[okf]
    gz = a4["zone"][okf] == 1
    X["zone_h4_at_exit"] = {"diff_pct": None if d != d else 100 * d, "p": None if p != p else p, "n_yes": n1, "n_no": n0,
                            "general_diff_pct": 100 * float(gen[gz].mean() - gen[~gz].mean())}
    res["X"] = X

    # вариант без предела 20 баров
    v = tr.dropna(subset=["net_nocap"])
    NC = {}
    for nm, m in (("2018–07.2024", v["te"] < SPLIT), ("08.2024–2026", v["te"] >= SPLIT), ("всё", v["te"] > 0)):
        w = v[m]
        NC[nm] = {"n": len(w), "orig_sum_pct": 100 * w["net"].sum(), "nocap_sum_pct": 100 * w["net_nocap"].sum(),
                  "orig_mean_pct": 100 * w["net"].mean(), "nocap_mean_pct": 100 * w["net_nocap"].mean(),
                  "orig_bars": float(w["bars"].mean()), "nocap_bars": float(w["bars_nocap"].mean()),
                  "worst_orig_pct": 100 * w["net"].min(), "worst_nocap_pct": 100 * w["net_nocap"].min()}
    res["nocap"] = NC
    return tr, res


def b018_table(h1, h4, cg: CGData) -> pd.DataFrame:
    rows = []
    for i, (te, side, x0, x3, n0, n3) in enumerate(B018, 1):
        r = {"cycle": i, "entry": te, "side": side, "exit_base": x0, "exit_ema3": x3, "net_base": n0, "net_ema3": n3}
        for pre, T in (("in", ts(te)), ("out", ts(x3))):
            r.update({f"{pre}_{k}": v for k, v in ma_snap(h1, T, "h1").items()})
            r.update({f"{pre}_{k}": v for k, v in ma_snap(h4, T, "h4").items()})
            r.update(cg.snap(T, pre))
        rows.append(r)
    return pd.DataFrame(rows)


def cg_compare(df: pd.DataFrame, net_col: str) -> dict:
    """Описательно: медианы признаков CoinGlass у плюсовых и минусовых сделок (n — единицы)."""
    out = {}
    if df.empty:
        return out
    w, l_ = df[df[net_col] > 0], df[df[net_col] <= 0]
    for col in [c for c in df.columns if "_cgp_" in c]:
        out[col] = {"win_med": float(w[col].median()) if len(w) else None,
                    "loss_med": float(l_[col].median()) if len(l_) else None, "n_win": int(w[col].notna().sum()),
                    "n_loss": int(l_[col].notna().sum())}
    return out


def main():
    OUT.mkdir(exist_ok=True)
    result = {}
    all_tr = []
    for sym, pk in (("BTCUSDT", arg("pk-btc")), ("ETHUSDT", arg("pk-eth"))):
        h1, h4, fund = load(pk)
        lvl = float(h4["close"].iloc[-1])
        if (sym == "BTCUSDT") != (lvl > 20000):
            sys.exit(f"{pk.name}: цена {lvl} не похожа на {sym} — отказ")
        cg = CGData(sym)
        tr, res = analyse_coin(sym, h1, h4, fund, cg)
        res["liq_label_check"] = cg.liq_check
        cgw = tr[tr["in_cg_flow6"].notna()] if "in_cg_flow6" in tr else tr.iloc[0:0]
        res["cg_window_trades"] = len(cgw)
        res["cg_entry_win_vs_loss"] = cg_compare(cgw, "net")
        result[sym] = res
        all_tr.append(tr)
        if sym == "BTCUSDT":
            bt = b018_table(h1, h4, cg)
            bt.to_csv(OUT / "b018_entry_exit.csv", index=False)
            result["B018"] = {"cg_ema3": cg_compare(bt, "net_ema3")}
        print(f"{sym}: сделок 432 {res['n']}, в окне CoinGlass {len(cgw)}", flush=True)
    pd.concat(all_tr).to_csv(OUT / "t432_entry_exit.csv", index=False)
    (OUT / "snap_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, default=float))
    print(json.dumps(result, ensure_ascii=False, indent=1, default=float)[:6000])


if __name__ == "__main__":
    main()
