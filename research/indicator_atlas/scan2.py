"""Однофакторный скан «метка → исход» по 10 монетам атласа, версия atlas-2 (разбор GPT a7d799b §6.2, §8).

ПРАВИЛА ЗАПИСАНЫ ДО ПРОГОНА (28.10.2026, до первого расчёта исходов этим скриптом; результаты atlas-1 не смотрелись).
Менять под результат нельзя; соседние варианты — только ниже, под пометкой «ЧУВСТВИТЕЛЬНОСТЬ», на выживших не влияют.

Данные
- atlas.build_all() (ATLAS_VERSION = atlas-2, только сверенные выгрузки CoinGlass 1h, sha256 и закрытость баров
  проверяет atlas.load); метки — atlas.token_columns(d) (88 булевых; NaN признака → False); состояние — context;
  исходы — first / top_here / bottom_here / f24 (atlas.outcomes: тройной барьер ±2·ATR на 24 ч).
- Каждая монета — свой часовой календарь (сортировка по времени внутри монеты).

Тест = (состояние, метка, исход). Состояния UP, DOWN, FLAT (MIX не берём). Исходы:
    UP:   cont = first=='up',   rev = first=='down', top    = top_here==1,    f24;
    DOWN: cont = first=='down', rev = first=='up',   bottom = bottom_here==1, f24;
    FLAT: brk_up = first=='up', brk_dn = first=='down', stay = first=='none', f24.
  Для исходов по first строки с first ∈ {both, None} исключены; для top/bottom/f24 — строки с NaN исхода.
  Строка годна для теста, если она в этом состоянии и исход определён (далее «часы» — только такие строки).
- Δ = среднее исхода в часах (состояние & метка) − среднее в часах (состояние & не метка), все монеты вместе.
  Для бинарных исходов Δ — в долях (в отчёте п.п.), для f24 — в ATR(t).
- Допуск: ≥150 часов (состояние & метка) суммарно И ≥30 эпизодов. Эпизод — серия таких часов одной монеты;
  следующий час с меткой начинает новый эпизод, если от предыдущего часа с меткой прошло ≥24 ч (разрыв <24 ч —
  тот же эпизод). Часы и эпизоды считаются по строкам, годным для данного теста.
- Плацебо: 999 повторов, зерно 20261028; в каждом повторе для КАЖДОЙ монеты своё круговое смещение всей матрицы
  меток на s ∈ [168, N−168] (целые, концы включены; N — часов у монеты), состояние и исходы на месте.
  p = (1 + #{|Δ_пл| ≥ |Δ| − 1e−12}) / (999 + 1), двусторонний; Δ_пл не определён (нет часов с меткой или без неё)
  — считается превышением (в пользу нуля). «Ошибка» Δ — стандартное отклонение определённых Δ_пл (ddof=1).
- Множественность: Бенджамини–Хохберг q ≤ 0.10 по ВСЕМУ семейству допущенных тестов (все состояния × метки ×
  исходы, включая f24); q — монотонно скорректированные BH (не выше 1).
- Устойчивость:
  половины — Δ того же знака (≠0), что общий, отдельно в часах до 2026-08-01 00:00 UTC и после; в каждой половине
  ≥50 часов (состояние & метка); иначе — не пройдено;
  монеты — m = монеты с ≥20 часами (состояние & метка); k = из них монеты с Δ_монеты того же знака, что общий
  (Δ_монеты не определён — несогласна); пройдено, если m ≥ 1 и k/m ≥ 0.70.
- Выживший = допущен И q ≤ 0.10 И половины И монеты.
- Для выжившего: доли (средние) с меткой / без, Δ (п.п. или ATR), Δf24 (тот же состояние & метка, исход f24, ATR),
  часы, эпизоды, p, q, половины (Δ и часы), монеты k/m и фраза «на исследованной истории: при «метка» <состояние>
  <исход> в A% часов против B%».
- Сводка: число тестов всего и допущенных; сколько допущенных с p < 0.01 и ожидание случайно (0.01 × допущенных).
- Топ-25: допущенные тесты по |Δ| / ошибка, с флагами непройденных критериев (FDR, половины, монеты).
- Отдельно, описательно (без отбора): по монетам доли часов, где неизвестны метки потока (tak6/tak24 и их
  перцентили), стакана (red6/green6, bookp6) и ликвидаций (liqL6/liqS6 и их перцентили): окно неизвестно (сумма
  окна NaN) и перцентиль неизвестен (окно NaN или мало прошлого); по всем часам и по часам UP/DOWN/FLAT; плюс доля
  пустых сырых значений и первый непустой час каждого сырого столбца.

ЧУВСТВИТЕЛЬНОСТЬ (записана ДО прогона, на выживших не влияет, показывается отдельно):
- общее смещение: в каждом повторе ОДНО s ∈ [168, min N − 168] на все монеты (раздельные смещения рвут
  одновременность меток разных монет — общерыночные эпизоды; разброс Δ_пл может быть занижен). 999 повторов,
  зерно 20261029, те же p/BH/половины/монеты; показывается число выживших и их список.

ЧУВСТВИТЕЛЬНОСТЬ, ДОБАВЛЕННАЯ ПОСЛЕ ПЕРВОГО ПРОГОНА (28.10, после того как общее смещение дало 0 выживших; правила
основного вывода не меняет, на выживших не влияет): перебор ВСЕХ общих смещений s ∈ [168, min N − 168] (4 032 при
N = 4 367) вместо 999 случайных. Причина: у 999 повторов пол p = 0.001, а BH по ~900 тестам при q 0.10 пропускает
p = 0.001, только если таких тестов ≥ 9 — ноль мог быть следствием разрешения, а не отсутствия эффекта.
p = (1 + #превышений) / (1 + число смещений), те же BH/половины/монеты.

    OMP_NUM_THREADS=2 nice -n 20 /Users/alexeychechikov/code/bot7/.venv/bin/python3 \
        /Users/alexeychechikov/code/bot7/research/indicator_atlas/scan2.py
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, "/Users/alexeychechikov/code/bot7")
from research.indicator_atlas import atlas  # noqa: E402

OUT = Path(__file__).resolve().parent / "scan2_result.json"
CUT = pd.Timestamp("2026-08-01", tz="UTC")
REPS, SEED, SEED_COMMON = 999, 20261028, 20261029
MIN_HOURS, MIN_EPIS, EPI_GAP = 150, 30, 24
HALF_MIN, COIN_MIN, COIN_SHARE = 50, 20, 0.70
FDR_Q, SHIFT_MIN, P_LOW, TOL = 0.10, 168, 0.01, 1e-12

OUTCOMES = {
    "UP": [("cont", "first", "up"), ("rev", "first", "down"), ("top", "top_here", None), ("f24", "f24", None)],
    "DOWN": [("cont", "first", "down"), ("rev", "first", "up"), ("bottom", "bottom_here", None), ("f24", "f24", None)],
    "FLAT": [("brk_up", "first", "up"), ("brk_dn", "first", "down"), ("stay", "first", "none"), ("f24", "f24", None)],
}
STATE_RU = {"UP": "на росте", "DOWN": "на падении", "FLAT": "во флете"}
PHRASE = {
    ("UP", "cont"): "рост продолжался (+2 ATR раньше −2 ATR за 24 ч)",
    ("UP", "rev"): "наступал откат (−2 ATR раньше +2 ATR за 24 ч)",
    ("UP", "top"): "вершина ближайших 24 ч уже была пройдена (выше max последних 3 ч не поднялись)",
    ("DOWN", "cont"): "падение продолжалось (−2 ATR раньше +2 ATR за 24 ч)",
    ("DOWN", "rev"): "наступал отскок (+2 ATR раньше −2 ATR за 24 ч)",
    ("DOWN", "bottom"): "дно ближайших 24 ч уже было пройдено (ниже min последних 3 ч не опустились)",
    ("FLAT", "brk_up"): "был выход вверх (+2 ATR раньше −2 ATR за 24 ч)",
    ("FLAT", "brk_dn"): "был выход вниз (−2 ATR раньше +2 ATR за 24 ч)",
    ("FLAT", "stay"): "флет держался (ни +2, ни −2 ATR за 24 ч)",
}
NAN_GROUPS = {
    "поток 6ч": ("tak6", "tak6p"), "поток 24ч": ("tak24", "tak24p"),
    "стакан 5+/6": ("red6", "red6"), "стакан сильно 6ч": ("book6", "bookp6"),
    "ликвидации лонгов 6ч": ("liqL6", "liqL6p"), "ликвидации шортов 6ч": ("liqS6", "liqS6p"),
}
RAW_COLS = ("taker_delta", "taker_buy", "taker_sell", "bid_ask_delta", "liq_all_long", "liq_all_short")


def fnum(x):
    if x is None:
        return None
    x = float(x)
    return None if math.isnan(x) or math.isinf(x) else x


def test_keys():
    return [(st, name, col, val) for st, outs in OUTCOMES.items() for name, col, val in outs]


def outcome_mats(d: pd.DataFrame, keys) -> tuple[np.ndarray, np.ndarray]:
    """VY (значение исхода × годность) и V (годность = состояние & исход определён), по столбцу на тест-исход."""
    first = d["first"]
    first_ok = first.isin(["up", "down", "none"]).to_numpy()
    ctx = d["context"]
    ys, vs = [], []
    for st, _name, col, val in keys:
        stm = (ctx == st).to_numpy()
        if col == "first":
            valid = stm & first_ok
            y = (first == val).to_numpy(dtype=float)
        else:
            x = d[col].to_numpy(dtype=float)
            valid = stm & ~np.isnan(x)
            y = np.where(np.isnan(x), 0.0, x)
        vs.append(valid.astype(float))
        ys.append(np.where(valid, y, 0.0))
    return np.column_stack(ys), np.column_stack(vs)


def delta_from(acc: np.ndarray, tot: np.ndarray, j: int):
    """acc: K×2J суммы по часам с меткой [Σy, Σv]; tot: 2J итоги по состоянию. → (Δ, с меткой, без, часы)."""
    a, b = acc[:, :j], acc[:, j:]
    sy, sv = tot[:j], tot[j:]
    with np.errstate(divide="ignore", invalid="ignore"):
        w = np.where(b > 0, a / b, np.nan)
        nb = sv[None, :] - b
        wo = np.where(nb > 0, (sy[None, :] - a) / nb, np.nan)
    return w - wo, w, wo, b


def bh(p: np.ndarray) -> np.ndarray:
    m = len(p)
    if m == 0:
        return p
    order = np.argsort(p, kind="mergesort")
    ranked = p[order] * m / np.arange(1, m + 1)
    q = np.minimum.accumulate(ranked[::-1])[::-1]
    out = np.empty(m)
    out[order] = np.minimum(q, 1.0)
    return out


def episodes(mask: np.ndarray) -> int:
    idx = np.flatnonzero(mask)
    if len(idx) == 0:
        return 0
    return int(1 + np.sum(np.diff(idx) >= EPI_GAP))


def placebo(Ts, Ms, tot, j, common: bool, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    ns = [len(t) for t in Ts]
    k = Ts[0].shape[1]
    out = np.empty((REPS, k, j))
    for r in range(REPS):
        acc = np.zeros((k, 2 * j))
        if common:
            s_all = int(rng.integers(SHIFT_MIN, min(ns) - SHIFT_MIN + 1))
        for c, (T, M) in enumerate(zip(Ts, Ms)):
            s = s_all if common else int(rng.integers(SHIFT_MIN, ns[c] - SHIFT_MIN + 1))
            # метки сдвинуты на +s: Σ_t T[t−s]·M[t] = Σ_u T[u]·M[u+s]
            acc += T.T @ np.roll(M, -s, axis=0)
        out[r] = delta_from(acc, tot, j)[0]
        if (r + 1) % 200 == 0:
            print(f"  плацебо {'общее' if common else 'раздельное'}: {r + 1}/{REPS}", flush=True)
    return out


def placebo_all_common(Ts, Ms, tot, j) -> np.ndarray:
    """Все общие смещения s ∈ [168, min N − 168] (чувствительность, добавлена после первого прогона)."""
    n = min(len(t) for t in Ts)
    shifts = range(SHIFT_MIN, n - SHIFT_MIN + 1)
    out = np.empty((len(shifts), Ts[0].shape[1], j))
    for r, s in enumerate(shifts):
        acc = sum(T.T @ np.roll(M, -s, axis=0) for T, M in zip(Ts, Ms))
        out[r] = delta_from(acc, tot, j)[0]
    return out


def pvals(delta: np.ndarray, pl: np.ndarray) -> np.ndarray:
    exceed = np.isnan(pl) | (np.abs(pl) >= np.abs(delta)[None] - TOL)
    return (1 + exceed.sum(axis=0)) / (len(pl) + 1)


def nan_windows(d_by: dict, syms: list[str]) -> dict:
    out = {}
    for s in syms:
        g = d_by[s]
        raw = atlas.load(s)
        st = g["context"].isin(["UP", "DOWN", "FLAT"]).to_numpy()
        row = {"часов": int(len(g)), "часов UP/DOWN/FLAT": int(st.sum()), "группы": {}, "сырые": {}}
        for nm, (wcol, pcol) in NAN_GROUPS.items():
            wn = g[wcol].isna().to_numpy()
            pn = g[pcol].isna().to_numpy()
            row["группы"][nm] = {
                "окно неизвестно, все часы": fnum(wn.mean()),
                "окно неизвестно, часы состояний": fnum(wn[st].mean()) if st.any() else None,
                "перцентиль неизвестен, все часы": fnum(pn.mean()),
                "перцентиль неизвестен, часы состояний": fnum(pn[st].mean()) if st.any() else None,
            }
        for col in RAW_COLS:
            x = raw[col]
            nn = x.notna()
            row["сырые"][col] = {"пусто, доля часов": fnum(1 - nn.mean()),
                                 "первый непустой": str(x.index[nn.to_numpy()][0]) if nn.any() else None,
                                 "пусто после первого непустого": fnum(1 - nn[nn.idxmax():].mean()) if nn.any() else None}
        out[s] = row
    return out


def main() -> None:
    t0 = time.time()
    d = atlas.build_all()
    print(f"build_all: {time.time() - t0:.1f} с, строк {len(d)}", flush=True)
    toks = atlas.token_columns(d)
    keys = test_keys()
    j, k = len(keys), len(toks)
    syms = list(dict.fromkeys(d["sym"].tolist()))
    d_by = {s: d[d["sym"] == s].sort_index() for s in syms}
    idx0 = d_by[syms[0]].index
    same_calendar = all(d_by[s].index.equals(idx0) for s in syms)

    Ts, Ms, Ms1, Ms2, halves_masks = [], [], [], [], []
    for s in syms:
        g = d_by[s]
        T = g[toks].to_numpy(dtype=float)
        vy, v = outcome_mats(g, keys)
        M = np.hstack([vy, v])
        h1 = (g.index < CUT).astype(float)[:, None]
        Ts.append(T)
        Ms.append(M)
        Ms1.append(M * h1)
        Ms2.append(M * (1 - h1))

    def pooled(mlist):
        acc = sum(T.T @ M for T, M in zip(Ts, mlist))
        tot = sum(M.sum(axis=0) for M in mlist)
        return acc, tot

    acc, tot = pooled(Ms)
    delta, w, wo, hours = delta_from(acc, tot, j)
    acc1, tot1 = pooled(Ms1)
    d1, _, _, h1n = delta_from(acc1, tot1, j)
    acc2, tot2 = pooled(Ms2)
    d2, _, _, h2n = delta_from(acc2, tot2, j)
    coin = [delta_from(T.T @ M, M.sum(axis=0), j) for T, M in zip(Ts, Ms)]

    eps = np.zeros((k, j), dtype=int)
    for T, M in zip(Ts, Ms):
        V = M[:, j:] > 0
        Tb = T > 0
        for a in range(k):
            m = Tb[:, a][:, None] & V
            for b in range(j):
                eps[a, b] += episodes(m[:, b])
    print(f"фактические Δ и эпизоды: {time.time() - t0:.1f} с", flush=True)

    pl = placebo(Ts, Ms, tot, j, common=False, seed=SEED)
    p = pvals(delta, pl)
    with np.errstate(invalid="ignore"):
        err = np.nanstd(pl, axis=0, ddof=1)
    print(f"плацебо раздельное: {time.time() - t0:.1f} с", flush=True)
    plc = placebo(Ts, Ms, tot, j, common=True, seed=SEED_COMMON)
    pc = pvals(delta, plc)
    print(f"плацебо общее: {time.time() - t0:.1f} с", flush=True)
    pla = placebo_all_common(Ts, Ms, tot, j)
    pa = pvals(delta, pla)
    n_all_shifts = len(pla)
    del pla
    print(f"все общие смещения ({n_all_shifts}): {time.time() - t0:.1f} с", flush=True)

    admitted = (hours >= MIN_HOURS) & (eps >= MIN_EPIS) & ~np.isnan(delta)
    q = np.full((k, j), np.nan)
    q[admitted] = bh(p[admitted])
    qc = np.full((k, j), np.nan)
    qc[admitted] = bh(pc[admitted])
    qa = np.full((k, j), np.nan)
    qa[admitted] = bh(pa[admitted])

    sgn = np.sign(delta)
    halves_ok = (h1n >= HALF_MIN) & (h2n >= HALF_MIN) & (np.sign(d1) == sgn) & (np.sign(d2) == sgn) & (sgn != 0)
    coin_m = np.zeros((k, j), dtype=int)
    coin_k = np.zeros((k, j), dtype=int)
    for dc, _, _, hc in coin:
        elig = hc >= COIN_MIN
        coin_m += elig
        coin_k += elig & (np.sign(dc) == sgn) & ~np.isnan(dc)
    with np.errstate(divide="ignore", invalid="ignore"):
        coins_ok = (coin_m >= 1) & (coin_k / np.maximum(coin_m, 1) >= COIN_SHARE)
    fdr_ok = admitted & (q <= FDR_Q)
    surv = fdr_ok & halves_ok & coins_ok
    surv_c = admitted & (qc <= FDR_Q) & halves_ok & coins_ok
    surv_a = admitted & (qa <= FDR_Q) & halves_ok & coins_ok

    f24_col = {st: next(i for i, kk in enumerate(keys) if kk[0] == st and kk[1] == "f24") for st in OUTCOMES}

    def is_bin(b):
        return keys[b][1] != "f24"

    def rec(a, b, with_phrase=False):
        st, name = keys[b][0], keys[b][1]
        sc = 100.0 if is_bin(b) else 1.0
        fj = f24_col[st]
        r = {
            "состояние": st, "исход": name, "метка": toks[a],
            "с меткой": fnum(w[a, b] * sc), "без метки": fnum(wo[a, b] * sc),
            "единица": "% часов" if is_bin(b) else "ATR",
            "Δ": fnum(delta[a, b] * sc), "ошибка (σ плацебо)": fnum(err[a, b] * sc),
            "|Δ|/ошибка": fnum(abs(delta[a, b]) / err[a, b]) if err[a, b] > 0 else None,
            "Δf24 ATR": fnum(delta[a, fj]), "f24 с/без ATR": [fnum(w[a, fj]), fnum(wo[a, fj])],
            "часов": int(hours[a, b]), "эпизодов": int(eps[a, b]),
            "p": fnum(p[a, b]), "q": fnum(q[a, b]), "p общее смещение (чувств.)": fnum(pc[a, b]),
            "q общее смещение (чувств.)": fnum(qc[a, b]),
            "p все общие смещения (чувств. после прогона)": fnum(pa[a, b]),
            "q все общие смещения (чувств. после прогона)": fnum(qa[a, b]),
            "половины": {"до 01.08": {"Δ": fnum(d1[a, b] * sc), "часов": int(h1n[a, b])},
                         "после": {"Δ": fnum(d2[a, b] * sc), "часов": int(h2n[a, b])}},
            "монеты k/m": f"{int(coin_k[a, b])}/{int(coin_m[a, b])}",
            "по монетам Δ": {s: {"Δ": fnum(coin[c][0][a, b] * sc), "часов": int(coin[c][3][a, b])}
                             for c, s in enumerate(syms)},
            "допущен": bool(admitted[a, b]), "FDR": bool(fdr_ok[a, b]), "половины ок": bool(halves_ok[a, b]),
            "монеты ок": bool(coins_ok[a, b]), "выжил": bool(surv[a, b]),
        }
        flags = []
        if not admitted[a, b]:
            flags.append("не допущен")
        if admitted[a, b] and not fdr_ok[a, b]:
            flags.append("FDR")
        if not halves_ok[a, b]:
            flags.append("половины")
        if not coins_ok[a, b]:
            flags.append("монеты")
        r["не пройдено"] = flags
        if with_phrase:
            if is_bin(b):
                r["фраза"] = (f"на исследованной истории: при «{toks[a]}» {STATE_RU[st]} {PHRASE[(st, name)]} "
                              f"в {w[a, b] * 100:.1f}% часов против {wo[a, b] * 100:.1f}% без метки "
                              f"({int(hours[a, b])} ч, {int(eps[a, b])} эпизодов)")
            else:
                r["фраза"] = (f"на исследованной истории: при «{toks[a]}» {STATE_RU[st]} цена за 24 ч в среднем "
                              f"сдвигалась на {w[a, b]:+.2f} ATR против {wo[a, b]:+.2f} ATR без метки "
                              f"({int(hours[a, b])} ч, {int(eps[a, b])} эпизодов)")
        return r

    n_adm = int(admitted.sum())
    n_low = int((admitted & (p < P_LOW)).sum())
    z = np.where(admitted & (err > 0), np.abs(delta) / np.where(err > 0, err, 1), -1)
    top_idx = np.dstack(np.unravel_index(np.argsort(-z, axis=None), z.shape))[0][:25]
    survivors = [rec(a, b, True) for a, b in zip(*np.nonzero(surv))]
    survivors.sort(key=lambda r: r["p"])
    surv_common = [f"{keys[b][0]}/{keys[b][1]}/{toks[a]}" for a, b in zip(*np.nonzero(surv_c))]

    ctx_counts = {s: {st: int((d_by[s]["context"] == st).sum()) for st in ("UP", "DOWN", "FLAT", "MIX")}
                  for s in syms}
    by_state = {}
    for st in OUTCOMES:
        cols = [b for b in range(j) if keys[b][0] == st]
        by_state[st] = {"допущено": int(admitted[:, cols].sum()), "p<0.01": int((admitted & (p < P_LOW))[:, cols].sum()),
                        "FDR": int(fdr_ok[:, cols].sum()), "выжило": int(surv[:, cols].sum())}

    out = {
        "версия": "scan2 / " + atlas.ATLAS_VERSION, "правила": "см. docstring scan2.py (записаны до прогона)",
        "мета": {
            "монеты": syms, "меток": k, "исходов": j, "один календарь у всех монет": bool(same_calendar),
            "часов по монетам": {s: int(len(d_by[s])) for s in syms},
            "период": [str(idx0[0]), str(idx0[-1])], "состояния, часов": ctx_counts,
            "повторов плацебо": REPS, "секунд": round(time.time() - t0, 1),
        },
        "сводка": {
            "тестов всего": int(k * j), "Δ определён": int((~np.isnan(delta)).sum()), "допущено": n_adm,
            "допущено с p<0.01": n_low, "ожидание случайно (0.01×допущенных)": round(P_LOW * n_adm, 1),
            "q≤0.10": int(fdr_ok.sum()), "FDR+половины": int((fdr_ok & halves_ok).sum()),
            "FDR+монеты": int((fdr_ok & coins_ok).sum()), "выжило": int(surv.sum()),
            "по состояниям": by_state,
            "чувствительность: общее смещение": {"допущено с p<0.01": int((admitted & (pc < P_LOW)).sum()),
                                                "q≤0.10": int((admitted & (qc <= FDR_Q)).sum()),
                                                "выжило": int(surv_c.sum()), "список": surv_common},
            "чувствительность после прогона: все общие смещения": {
                "смещений": n_all_shifts, "пол p": round(1 / (n_all_shifts + 1), 6),
                "допущено с p<0.01": int((admitted & (pa < P_LOW)).sum()),
                "допущено с p≤0.001": int((admitted & (pa <= 0.001)).sum()),
                "q≤0.10": int((admitted & (qa <= FDR_Q)).sum()), "выжило": int(surv_a.sum()),
                "список": [f"{keys[b][0]}/{keys[b][1]}/{toks[a]} p {pa[a, b]:.5f} q {qa[a, b]:.3f}"
                           for a, b in zip(*np.nonzero(surv_a))]},
        },
        "выжившие": survivors,
        "топ-25 по |Δ|/ошибка (допущенные)": [rec(a, b, True) for a, b in top_idx if z[a, b] >= 0],
        "окна неизвестных данных (описательно)": nan_windows(d_by, syms),
        "все тесты": [rec(a, b) for a in range(k) for b in range(j)],
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out["сводка"], ensure_ascii=False, indent=1), flush=True)
    for r in survivors:
        print(r["фраза"], f"| Δ {r['Δ']:+.2f} p {r['p']:.3f} q {r['q']:.3f} монеты {r['монеты k/m']}", flush=True)
    print(f"готово: {time.time() - t0:.1f} с → {OUT}", flush=True)


if __name__ == "__main__":
    main()
