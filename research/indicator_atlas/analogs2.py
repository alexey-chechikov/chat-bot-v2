"""Аналогии (atlas-2): помогают ли похожие прошлые часы предсказать исход лучше базы (разбор GPT 2026-10-28 §4, §6.2, §8).

ПРАВИЛА ЗАПИСАНЫ ДО ПРОГОНА (29.10.2026, до первого расчёта исходов этим скриптом). Менять под результат нельзя;
соседние варианты — только в разделе «ЧУВСТВИТЕЛЬНОСТЬ», на вывод не влияют.

Данные
- atlas.build_all() (ATLAS_VERSION = atlas-2: только сверенные выгрузки CoinGlass 1h, sha256 и закрытость баров
  проверяет atlas.load); состояние — context; исходы — first (тройной барьер ±2·ATR на 24 ч), top_here, bottom_here,
  f24 (atlas.outcomes); описание часа — atlas.describe по atlas.token_columns.

Вектор часа (37 чисел, евклид без весов)
- r6, r24, r72: обрезать ±10, разделить на 5; NaN → 0.
- er24, pos24, pos72, w24p, r24p: как есть; NaN → 0.5.
- для k в oi, fr, frw, lsa, lst, wi: k_p (NaN → 0.5); k_z6, k_z24 — обрезать ±5, разделить на 2.5 (NaN → 0).
- tak6p, tak24p; red6/6, green6/6; bookp6; vol6p; liqL6p, liqS6p — NaN → 0.5.
- флаги «неизвестно» (0/1): поток = tak6p или tak24p NaN; стакан = red6, green6 или bookp6 NaN;
  ликвидации = liqL6p или liqS6p NaN.
- нечисловые бесконечности (деление на ноль в признаке) — после обрезки как NaN своей группы.

Задачи
- Состояния UP, DOWN, FLAT — отдельно (своя выборка, свой пул, своя модель).
- «first»: классы (up, down, none); часы с first ∈ {both, None} не берутся ни в пул, ни в оценку.
- бинарные: top_here только в UP, bottom_here только в DOWN (классы нет/да); часы с NaN исхода не берутся.

Walk-forward
- Оцениваемые t: с 2026-07-01 00:00 UTC, часы с чётным часом UTC (каждый 2-й час) каждой монеты, в своём состоянии,
  исход определён.
- Пул для t: часы ВСЕХ монет того же состояния с годным исходом, s ≤ t − 25 ч (исход s закрыт к t с запасом 1 ч).
- kNN: K = 50 ближайших по евклиду (ничьи — раньше по времени, затем по порядку монет atlas.COINS);
  прогноз = (счёт класса + 1) / (K + число классов). Пул < K — точка пропускается (счёт пропусков в отчёте).
- База: частоты классов того же пула, (счёт + 1) / (размер пула + число классов).
- Логистическая: sklearn LogisticRegression (мультиномиальная для 3 классов, L2, C = 0.1, lbfgs, max_iter 5000)
  на тех же 37 числах; переобучение раз в 7 суток: окна [2026-07-01 + 7k сут, +7 сут), модель окна обучена на пуле
  s ≤ начало окна − 25 ч. Класса нет в обучении — вероятность 0 (в log loss обрезка снизу 1e-12).

Метрики
- Брайер = Σ по классам (p − 1[класс])² (для бинарных это 2× обычный — skill не меняется); log loss = −ln p(истина).
- skill = 1 − ΣБрайер_модели / ΣБрайер_базы.
- ДИ 95% разности (Брайер_базы − Брайер_модели, среднее на точку) и skill — блочный бутстреп по суткам UTC
  (сутки — блок всех монет вместе), 1000 повторов, зерно 20261029, одинаковые выборки суток для всех моделей
  разреза; перцентили 2.5 / 97.5. Так же — разность log loss (база − модель), справочно.
- Разрезы: всё (для first — все три состояния вместе), каждое состояние, половины периода оценки
  (июль–август: t < 2026-09-01; сентябрь–октябрь: t ≥ 2026-09-01), состояние × половина, монеты.

Решение (по Брайеру, log loss — справочно)
- «Аналогии работают» = kNN K=50, задача first, все состояния вместе: skill > 0 и нижняя граница ДИ разности > 0,
  И skill > 0 в обеих половинах. Иначе — «не работают».
- Тот же критерий отдельно: логистическая (сравнение), каждое состояние (справочно), top_here (UP), bottom_here (DOWN).

«Сегодня» (BTCUSDT, ETHUSDT, последний бар выгрузки)
- состояние, atlas.describe часа; пул того же состояния, s ≤ t − 25 ч; 10 ближайших аналогов: монета, время,
  расстояние, 6 меток (до 6 истинных меток аналога: сначала общие с сегодняшним часом, затем прочие, в порядке
  atlas.token_columns), исход (first, top_here, bottom_here, f24); прогноз kNN K=50 и логистической (на всём пуле)
  против базы для first и (UP/DOWN) для top/bottom.
- Если состояние MIX — те же расчёты по пулу MIX, с пометкой «MIX walk-forward не проверялся».

ЧУВСТВИТЕЛЬНОСТЬ (записана до прогона, на вывод не влияет): kNN K = 20 и K = 100 (тот же порядок соседей),
разрезы «всё» и половины для каждой задачи.

    OMP_NUM_THREADS=2 nice -n 20 /Users/alexeychechikov/code/bot7/.venv/bin/python3 \
        /Users/alexeychechikov/code/bot7/research/indicator_atlas/analogs2.py
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

sys.path.insert(0, "/Users/alexeychechikov/code/bot7")
from research.indicator_atlas import atlas  # noqa: E402

HERE = Path(__file__).resolve().parent
OUT = HERE / "analogs2_result.json"
EVAL_START = pd.Timestamp("2026-07-01", tz="UTC")
HALF_CUT = pd.Timestamp("2026-09-01", tz="UTC")
GAP_NS = int(pd.Timedelta(hours=25).value)
WEEK_NS = int(pd.Timedelta(days=7).value)
K = 50
K_SENS = (20, 100)
C_LOG = 0.1
BOOT, SEED = 1000, 20261029
STATES = ("UP", "DOWN", "FLAT")
CLASSES = ("up", "down", "none")
BIN_CLASSES = ("нет", "да")
TASKS = (("first", "UP"), ("first", "DOWN"), ("first", "FLAT"), ("top", "UP"), ("bottom", "DOWN"))
LEVEL_KEYS = ("oi", "fr", "frw", "lsa", "lst", "wi")
TODAY_SYMS = ("BTCUSDT", "ETHUSDT")
N_ANALOGS, N_LABELS = 10, 6
EPS = 1e-12


def fnum(x):
    if x is None:
        return None
    x = float(x)
    return None if math.isnan(x) or math.isinf(x) else round(x, 6)


def vectors(d: pd.DataFrame) -> tuple[np.ndarray, list[str]]:
    cols: dict[str, np.ndarray] = {}

    def col(name):
        x = d[name].to_numpy(dtype=float).copy()
        x[~np.isfinite(x)] = np.nan
        return x

    for k in ("r6", "r24", "r72"):
        x = d[k].to_numpy(dtype=float)
        x = np.clip(x, -10, 10) / 5.0
        cols[k] = np.where(np.isnan(x), 0.0, x)
    for k in ("er24", "pos24", "pos72", "w24p", "r24p"):
        x = col(k)
        cols[k] = np.where(np.isnan(x), 0.5, x)
    for key in LEVEL_KEYS:
        x = col(f"{key}_p")
        cols[f"{key}_p"] = np.where(np.isnan(x), 0.5, x)
        for h in (6, 24):
            z = d[f"{key}_z{h}"].to_numpy(dtype=float)
            z = np.clip(z, -5, 5) / 2.5
            cols[f"{key}_z{h}"] = np.where(np.isnan(z), 0.0, z)
    for k in ("tak6p", "tak24p"):
        x = col(k)
        cols[k] = np.where(np.isnan(x), 0.5, x)
    for k in ("red6", "green6"):
        x = col(k) / 6.0
        cols[f"{k}/6"] = np.where(np.isnan(x), 0.5, x)
    for k in ("bookp6", "vol6p", "liqL6p", "liqS6p"):
        x = col(k)
        cols[k] = np.where(np.isnan(x), 0.5, x)
    cols["flow_unknown"] = (np.isnan(col("tak6p")) | np.isnan(col("tak24p"))).astype(float)
    cols["book_unknown"] = (np.isnan(col("red6")) | np.isnan(col("green6")) | np.isnan(col("bookp6"))).astype(float)
    cols["liq_unknown"] = (np.isnan(col("liqL6p")) | np.isnan(col("liqS6p"))).astype(float)
    names = list(cols)
    return np.column_stack([cols[n] for n in names]), names


def labels_for(d: pd.DataFrame, target: str) -> tuple[np.ndarray, int]:
    if target == "first":
        f = d["first"]
        ok = f.isin(CLASSES).to_numpy()
        y = np.full(len(d), -1, dtype=int)
        for i, c in enumerate(CLASSES):
            y[(f == c).to_numpy()] = i
        y[~ok] = -1
        return y, 3
    v = d["top_here" if target == "top" else "bottom_here"].to_numpy(dtype=float)
    y = np.where(np.isnan(v), -1, v).astype(int)
    return y, 2


def brier_ll(p: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    oh = np.eye(p.shape[1])[y]
    b = ((p - oh) ** 2).sum(axis=1)
    ll = -np.log(np.clip(p[np.arange(len(y)), y], EPS, 1.0))
    return b, ll


def knn_probs(PX, Py, ncls, x, n, ks):
    dd = ((PX[:n] - x) ** 2).sum(axis=1)
    order = np.argsort(dd, kind="stable")
    out = {}
    for k in ks:
        if n < k:
            out[k] = None
            continue
        cnt = np.bincount(Py[order[:k]], minlength=ncls)
        out[k] = (cnt + 1.0) / (k + ncls)
    return out, order, dd


def fit_log(X, y, ncls):
    if len(np.unique(y)) < 2:
        return None
    m = LogisticRegression(C=C_LOG, max_iter=5000)
    m.fit(X, y)
    return m


def log_probs(m, X, ncls):
    p = np.zeros((len(X), ncls))
    pr = m.predict_proba(X)
    for j, c in enumerate(m.classes_):
        p[:, int(c)] = pr[:, j]
    return p


def run_task(d, X, times, symcode, target, state):
    y, ncls = labels_for(d, target)
    ctx = d["context"].to_numpy(dtype=object)
    valid = (ctx == state) & (y >= 0)
    pidx = np.where(valid)[0]
    pidx = pidx[np.lexsort((symcode[pidx], times[pidx]))]
    PX, Py, Pt = X[pidx], y[pidx], times[pidx]
    cum = np.zeros((len(pidx) + 1, ncls))
    cum[1:] = np.cumsum(np.eye(ncls)[Py], axis=0)
    hours = d.index.hour.to_numpy()
    ev = np.where(valid & (times >= EVAL_START.value) & (hours % 2 == 0))[0]
    ev = ev[np.lexsort((symcode[ev], times[ev]))]
    ks = (K, *K_SENS)
    recs = {"i": [], "y": [], "base": [], "log": []}
    for k in ks:
        recs[f"knn{k}"] = []
    skipped = 0
    models = {}
    log_skipped = 0
    for i in ev:
        n = int(np.searchsorted(Pt, times[i] - GAP_NS, side="right"))
        if n < K:
            skipped += 1
            continue
        pk, _, _ = knn_probs(PX, Py, ncls, X[i], n, ks)
        wk = int((times[i] - EVAL_START.value) // WEEK_NS)
        if wk not in models:
            cut = EVAL_START.value + wk * WEEK_NS - GAP_NS
            nt = int(np.searchsorted(Pt, cut, side="right"))
            models[wk] = (fit_log(PX[:nt], Py[:nt], ncls), nt)
        m = models[wk][0]
        if m is None:
            log_skipped += 1
            plog = np.full(ncls, np.nan)
        else:
            plog = log_probs(m, X[i:i + 1], ncls)[0]
        recs["i"].append(i)
        recs["y"].append(y[i])
        recs["base"].append((cum[n] + 1.0) / (n + ncls))
        recs["log"].append(plog)
        for k in ks:
            recs[f"knn{k}"].append(pk[k] if pk[k] is not None else np.full(ncls, np.nan))
    out = {k: np.array(v) for k, v in recs.items()}
    info = {"pool_rows": int(len(pidx)), "eval_candidates": int(len(ev)), "evaluated": int(len(out["i"])),
            "skipped_pool_lt_K": skipped, "log_windows": len(models),
            "log_train_rows": {str(k): v[1] for k, v in sorted(models.items())}, "log_skipped": log_skipped}
    return out, ncls, info


def boot_stats(day, bm, bb, lm, lb):
    """Сводка разреза; бутстреп по суткам, одинаковые выборки для всех моделей (зерно SEED)."""
    days, inv = np.unique(day, return_inverse=True)
    nd = len(days)
    cnt = np.bincount(inv, minlength=nd).astype(float)
    sbm, sbb = np.bincount(inv, bm, nd), np.bincount(inv, bb, nd)
    slm, slb = np.bincount(inv, lm, nd), np.bincount(inv, lb, nd)
    rng = np.random.default_rng(SEED)
    idx = rng.integers(0, nd, size=(BOOT, nd))
    n_b = cnt[idx].sum(1)
    bm_b, bb_b = sbm[idx].sum(1), sbb[idx].sum(1)
    lm_b, lb_b = slm[idx].sum(1), slb[idx].sum(1)
    diff_b = (bb_b - bm_b) / n_b
    skill_b = 1 - bm_b / bb_b
    lld_b = (lb_b - lm_b) / n_b
    n = len(bm)
    return {
        "n": int(n), "days": int(nd),
        "brier_model": fnum(bm.mean()), "brier_base": fnum(bb.mean()),
        "skill": fnum(1 - bm.sum() / bb.sum()),
        "diff_base_minus_model": fnum((bb.sum() - bm.sum()) / n),
        "diff_ci95": [fnum(np.percentile(diff_b, 2.5)), fnum(np.percentile(diff_b, 97.5))],
        "skill_ci95": [fnum(np.percentile(skill_b, 2.5)), fnum(np.percentile(skill_b, 97.5))],
        "logloss_model": fnum(lm.mean()), "logloss_base": fnum(lb.mean()),
        "logloss_diff_base_minus_model": fnum((lb.sum() - lm.sum()) / n),
        "logloss_diff_ci95": [fnum(np.percentile(lld_b, 2.5)), fnum(np.percentile(lld_b, 97.5))],
    }


def verdict(s_all, s_h1, s_h2):
    ok_all = s_all is not None and s_all["skill"] is not None and s_all["skill"] > 0 and s_all["diff_ci95"][0] > 0
    ok_h = all(s is not None and s["skill"] is not None and s["skill"] > 0 for s in (s_h1, s_h2))
    return {"works": bool(ok_all and ok_h), "overall_skill_gt0_ci_excl0": bool(ok_all), "both_halves_gt0": bool(ok_h)}


def main():
    t0 = time.time()
    d = atlas.build_all()
    coins = list(atlas.COINS)
    d = d.copy()
    symcode = d["sym"].map({s: i for i, s in enumerate(coins)}).to_numpy(dtype=int)
    times = d.index.asi8.astype(np.int64)
    X, vnames = vectors(d)
    tokcols = atlas.token_columns(d)
    syms_arr = d["sym"].to_numpy(dtype=object)
    ctx_arr = d["context"].to_numpy(dtype=object)

    # ---------- walk-forward ----------
    task_out, infos = {}, {}
    for target, state in TASKS:
        o, ncls, info = run_task(d, X, times, symcode, target, state)
        task_out[(target, state)] = (o, ncls)
        infos[f"{target}|{state}"] = info
        print(target, state, info["evaluated"], "points", round(time.time() - t0, 1), "s", flush=True)

    def collect(target, states, model):
        parts = []
        for st in states:
            o, ncls = task_out[(target, st)]
            if len(o["i"]) == 0:
                continue
            p = o[model]
            b_m, l_m = brier_ll(p, o["y"])
            b_b, l_b = brier_ll(o["base"], o["y"])
            ii = o["i"]
            tt = pd.to_datetime(times[ii], utc=True)
            parts.append(pd.DataFrame({"state": st, "sym": syms_arr[ii], "t": tt,
                                       "day": tt.floor("D").asi8, "bm": b_m, "bb": b_b, "lm": l_m, "lb": l_b}))
        return pd.concat(parts, ignore_index=True)

    def slices(df, with_states):
        res = {}
        h1 = df["t"] < HALF_CUT

        def st_(mask):
            g = df[mask]
            if len(g) == 0:
                return None
            return boot_stats(g["day"].to_numpy(), g["bm"].to_numpy(), g["bb"].to_numpy(),
                              g["lm"].to_numpy(), g["lb"].to_numpy())

        allm = np.ones(len(df), dtype=bool)
        res["всё"] = st_(allm)
        res["июль–август"] = st_(h1.to_numpy())
        res["сентябрь–октябрь"] = st_((~h1).to_numpy())
        if with_states:
            for st in STATES:
                sm = (df["state"] == st).to_numpy()
                res[st] = st_(sm)
                res[f"{st} июль–август"] = st_(sm & h1.to_numpy())
                res[f"{st} сентябрь–октябрь"] = st_(sm & (~h1).to_numpy())
        res["монеты"] = {s: st_((df["sym"] == s).to_numpy()) for s in coins}
        return res

    results, verdicts, sens = {}, {}, {}
    task_groups = {"first": STATES, "top": ("UP",), "bottom": ("DOWN",)}
    for target, states in task_groups.items():
        results[target] = {}
        for model in (f"knn{K}", "log"):
            df = collect(target, states, model)
            if model == "log":
                df = df[np.isfinite(df["bm"])]
            r = slices(df, with_states=(target == "first"))
            results[target][model] = r
            verdicts[f"{target}|{model}|всё"] = verdict(r["всё"], r["июль–август"], r["сентябрь–октябрь"])
            if target == "first":
                for st in STATES:
                    verdicts[f"{target}|{model}|{st}"] = verdict(r[st], r[f"{st} июль–август"],
                                                                 r[f"{st} сентябрь–октябрь"])
        sens[target] = {}
        for k in K_SENS:
            df = collect(target, states, f"knn{k}")
            df = df[np.isfinite(df["bm"])]
            h1 = (df["t"] < HALF_CUT).to_numpy()
            sens[target][f"knn{k}"] = {
                name: boot_stats(g["day"].to_numpy(), g["bm"].to_numpy(), g["bb"].to_numpy(),
                                 g["lm"].to_numpy(), g["lb"].to_numpy())
                for name, g in (("всё", df), ("июль–август", df[h1]), ("сентябрь–октябрь", df[~h1]))}
        print("scored", target, round(time.time() - t0, 1), "s", flush=True)

    # ---------- class frequencies in evaluation ----------
    freq = {}
    for target, state in TASKS:
        o, ncls = task_out[(target, state)]
        names = CLASSES if target == "first" else BIN_CLASSES
        cnt = np.bincount(o["y"], minlength=ncls)
        freq[f"{target}|{state}"] = {names[j]: fnum(cnt[j] / max(1, cnt.sum())) for j in range(ncls)}
        freq[f"{target}|{state}"]["n"] = int(cnt.sum())

    # ---------- today ----------
    today = {}
    for sym in TODAY_SYMS:
        rows = np.where(syms_arr == sym)[0]
        i = rows[np.argmax(times[rows])]
        st = ctx_arr[i]
        trow = d.iloc[i]
        desc = atlas.describe(trow[tokcols])
        entry = {"bar_utc": str(pd.Timestamp(times[i], tz="UTC")), "state": None if not isinstance(st, str) else st,
                 "describe": desc, "close": fnum(trow["close"])}
        if not isinstance(st, str):
            entry["note"] = "состояние не определено"
            today[sym] = entry
            continue
        if st == "MIX":
            entry["note"] = "MIX walk-forward не проверялся"
        tasks_today = [("first", 3)]
        if st == "UP":
            tasks_today.append(("top", 2))
        if st == "DOWN":
            tasks_today.append(("bottom", 2))
        today_tok = set(c for c in tokcols if bool(trow[c]))
        for target, _ in tasks_today:
            y, ncls = labels_for(d, target)
            valid = (ctx_arr == st) & (y >= 0) & (times <= times[i] - GAP_NS)
            pidx = np.where(valid)[0]
            pidx = pidx[np.lexsort((symcode[pidx], times[pidx]))]
            PX, Py = X[pidx], y[pidx]
            n = len(pidx)
            pk, order, dd = knn_probs(PX, Py, ncls, X[i], n, (K,))
            base = (np.bincount(Py, minlength=ncls) + 1.0) / (n + ncls)
            m = fit_log(PX, Py, ncls)
            plog = log_probs(m, X[i:i + 1], ncls)[0] if m is not None else None
            names = CLASSES if target == "first" else BIN_CLASSES
            blk = {"pool": n,
                   "knn50": {names[j]: fnum(pk[K][j]) for j in range(ncls)} if pk[K] is not None else None,
                   "logistic": {names[j]: fnum(plog[j]) for j in range(ncls)} if plog is not None else None,
                   "base": {names[j]: fnum(base[j]) for j in range(ncls)}}
            if target == "first":
                an = []
                for j in order[:N_ANALOGS]:
                    g = pidx[j]
                    arow = d.iloc[g]
                    true_tok = [c for c in tokcols if bool(arow[c])]
                    lab = [c for c in true_tok if c in today_tok] + [c for c in true_tok if c not in today_tok]
                    an.append({"sym": syms_arr[g], "bar_utc": str(pd.Timestamp(times[g], tz="UTC")),
                               "dist": fnum(math.sqrt(dd[j])), "labels6": lab[:N_LABELS],
                               "shared_labels": int(sum(1 for c in true_tok if c in today_tok)),
                               "first": arow["first"], "top_here": fnum(arow["top_here"]),
                               "bottom_here": fnum(arow["bottom_here"]), "f24_atr": fnum(arow["f24"])})
                blk["analogs10"] = an
                cnt10 = {c: sum(1 for a in an if a["first"] == c) for c in CLASSES}
                blk["analogs10_first_counts"] = cnt10
            entry[target] = blk
        today[sym] = entry

    man = {}
    for s in atlas.available():
        mj = json.loads((atlas.DATA / f"{s}_1h.manifest.json").read_text(encoding="utf-8"))
        man[s] = mj.get("sha256")
    result = {
        "script": "research/indicator_atlas/analogs2.py",
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "atlas_version": atlas.ATLAS_VERSION,
        "csv_sha256": man,
        "vector": vnames,
        "data_first_bar": str(d.index.min()), "data_last_bar": str(d.index.max()),
        "eval_start": str(EVAL_START), "half_cut": str(HALF_CUT),
        "K": K, "C": C_LOG, "boot": BOOT, "seed": SEED,
        "tasks_info": infos,
        "eval_class_freq": freq,
        "verdict_main": {"rule": "kNN K=50, first, все состояния: skill>0, ДИ разности без нуля, skill>0 в обеих "
                                 "половинах",
                         **verdicts[f"first|knn{K}|всё"]},
        "verdicts": verdicts,
        "results": results,
        "sensitivity_K": sens,
        "today": today,
        "runtime_s": round(time.time() - t0, 1),
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("main verdict", result["verdict_main"])
    print("written", OUT, result["runtime_s"], "s")


if __name__ == "__main__":
    main()
