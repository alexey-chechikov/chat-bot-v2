"""Признаки сделки на часе входа и путь сделки — один код для истории (research/chart_walk_20261105/trade_table.py) и для
живой службы (run.py пишет их в state/btc_signals_features.jsonl). На часе i — только то, что известно к его закрытию:
линии 4ч — последней закрытой свечи 4ч, дневные — последнего закрытого дня.

prepare(a, lay, h4f=None) → словарь почасовых рядов {название признака: массив}; row(P, i) → значения на часе i.
history(prev, t_entry) — признаки прошлых сделок; path(a, i0, i1, side, entry, exit_px) — путь сделки (MFE, MAE, отдача).
m2_vector / m2_score — балл модели размера (flat_1109b, M2: только тень, не доказан)."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from services.btc_signals import engine as en

DAY = 24
H4 = 14400
M2_PATH = Path(__file__).with_name("model_m2.json")
LN = {"G": "зелёной", "Y": "жёлтой", "R": "красной", "B": "синей"}
PAIRS = (("G", "Y"), ("Y", "R"), ("G", "R"), ("R", "B"), ("G", "B"), ("Y", "B"))
PAIR_NAME = {"G": "З", "Y": "Ж", "R": "К", "B": "С"}


def lag(x, k: int) -> np.ndarray:
    x = np.asarray(x, float)
    if k >= len(x):
        return np.full(len(x), np.nan)
    return np.r_[np.full(k, np.nan), x[:-k]]


def since(ev: np.ndarray) -> np.ndarray:
    """Часов после последнего события (на часе события 0), до первого — NaN."""
    ar = np.arange(len(ev))
    last = np.maximum.accumulate(np.where(ev, ar, -1))
    return np.where(last >= 0, ar - last, np.nan).astype(float)


def carry(ev: np.ndarray, val: np.ndarray) -> np.ndarray:
    """Значение val на последнем событии, протянутое вперёд."""
    ar = np.arange(len(ev))
    last = np.maximum.accumulate(np.where(ev, ar, -1))
    return np.where(last >= 0, val[np.clip(last, 0, None)], np.nan)


def count_in(ev: np.ndarray, k: int) -> np.ndarray:
    cs = np.cumsum(ev.astype(float))
    return cs - np.nan_to_num(lag(cs, k), nan=0.0)


def sign_ffill(d: np.ndarray) -> np.ndarray:
    s = np.sign(np.nan_to_num(d))
    ar = np.arange(len(s))
    last = np.maximum.accumulate(np.where(s != 0, ar, 0))
    return s[last]


def rsi(c: np.ndarray, n: int = 14) -> np.ndarray:
    d = np.diff(c, prepend=c[0])
    au, ad = en.rma(np.maximum(d, 0.0), n), en.rma(np.maximum(-d, 0.0), n)
    with np.errstate(invalid="ignore", divide="ignore"):
        return 100 - 100 / (1 + au / ad)


def dmi(h, l, c, n=14):
    up, dn = np.r_[0.0, h[1:] - h[:-1]], np.r_[0.0, l[:-1] - l[1:]]
    pdm, mdm = np.where((up > dn) & (up > 0), up, 0.0), np.where((dn > up) & (dn > 0), dn, 0.0)
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    atr = en.rma(tr, n)
    with np.errstate(invalid="ignore", divide="ignore"):
        return 100 * en.rma(pdm, n) / atr, 100 * en.rma(mdm, n) / atr, tr


def eff(c: np.ndarray, k: int) -> np.ndarray:
    d = np.abs(np.diff(c, prepend=c[0]))
    num = np.abs(c - lag(c, k))
    den = count_sum(d, k)
    with np.errstate(invalid="ignore", divide="ignore"):
        return num / den


def count_sum(x: np.ndarray, k: int) -> np.ndarray:
    cs = np.cumsum(x)
    return cs - np.nan_to_num(lag(cs, k), nan=0.0)


def roll(x: np.ndarray, k: int, fn) -> np.ndarray:
    from numpy.lib.stride_tricks import sliding_window_view
    out = np.full(len(x), np.nan)
    if len(x) >= k:
        out[k - 1:] = fn(sliding_window_view(x, k), axis=1)
    return out


def align(a: dict, win: int = 24) -> tuple[np.ndarray, np.ndarray]:
    """Выстроены вверх: G>Y>R и все три выше, чем win часов назад (вниз — зеркально); иначе 0. И последнее ненулевое."""
    G, Y, R = a["f_G"], a["f_Y"], a["f_R"]
    with np.errstate(invalid="ignore"):
        up = (G > Y) & (Y > R) & (G > lag(G, win)) & (Y > lag(Y, win)) & (R > lag(R, win))
        dn = (G < Y) & (Y < R) & (G < lag(G, win)) & (Y < lag(Y, win)) & (R < lag(R, win))
    st = np.where(up, 1, np.where(dn, -1, 0))
    ev = st != 0
    last = np.nan_to_num(carry(ev, st.astype(float)), nan=0.0).astype(int)
    return st, last


def prepare(a: dict, lay: tuple, h4f=None) -> dict[str, np.ndarray]:
    t = np.asarray(a["t"], np.int64)
    c, h, l = np.asarray(a["c"], float), np.asarray(a["h"], float), np.asarray(a["l"], float)
    n = len(t)
    F, atr = np.asarray(a["f_close"], float), np.asarray(a["atr4"], float)
    L = {k: np.asarray(a[f"f_{k}"], float) for k in "GYRB"}
    rk, W = lay
    P: dict[str, np.ndarray] = {}
    with np.errstate(invalid="ignore", divide="ignore"):
        for k, nm in LN.items():
            P[f"от {nm}, ATR"] = (F - L[k]) / atr
            P[f"от {nm}, %"] = (F / L[k] - 1) * 100
        P["от синей 1ч, ATR"] = (c - a["B1h"]) / atr
        P["от красной 1ч, ATR"] = (c - a["R1"]) / atr
        P["линий ниже цены"] = sum((F > L[k]).astype(float) for k in "GYRB")
        sl24 = {}
        for k, nm in LN.items():
            for w in (4, 24, 72):
                P[f"наклон {nm} {w}ч, ATR"] = (L[k] - lag(L[k], w)) / atr
            sl24[k] = P[f"наклон {nm} 24ч, ATR"]
        P["наклон синей 1ч 24ч, ATR"] = (a["B1h"] - lag(a["B1h"], 24)) / atr
        P["наклон красной 1ч 24ч, ATR"] = (a["R1"] - lag(a["R1"], 24)) / atr
        P["ускорение зелёной, ATR"] = sl24["G"] - lag(sl24["G"], 24)
        P["ускорение жёлтой, ATR"] = sl24["Y"] - lag(sl24["Y"], 24)
        P["линий растут за 24ч"] = sum((sl24[k] > 0).astype(float) for k in "GYRB")
        P["порядок З>Ж>К"] = np.asarray(a["order"], float)
        P["пар в порядке роста"] = sum((L[x] > L[y]).astype(float) for i, x in enumerate("GYRB") for y in "GYRB"[i + 1:])
        P["зелёная−жёлтая, ATR"] = (L["G"] - L["Y"]) / atr
        P["жёлтая−красная, ATR"] = (L["Y"] - L["R"]) / atr
        P["красная−синяя, ATR"] = (L["R"] - L["B"]) / atr
        P["зелёная−синяя, ATR"] = (L["G"] - L["B"]) / atr
        stk = np.vstack([L["G"], L["Y"], L["R"]])
        P["ширина З/Ж/К, ATR"] = (stk.max(0) - stk.min(0)) / atr
        stk4 = np.vstack([stk, L["B"]])
        P["ширина с синей, ATR"] = (stk4.max(0) - stk4.min(0)) / atr
        P["ранг ширины"] = np.asarray(a["f_width_rank"], float)
        st, last = align(a)
        P["выстроены (24ч)"] = st.astype(float)
        P["прошлое выстраивание"] = last.astype(float)
        P["часов после выстраивания"] = since(st != 0)
        for x, y in PAIRS:
            nm = PAIR_NAME[x] + "/" + PAIR_NAME[y]
            d = L[x] - L[y]
            sg = sign_ffill(d)
            ch = np.r_[False, sg[1:] != sg[:-1]]
            P[f"часов после пересечения {nm}"] = since(ch)
            P[f"сила пересечения {nm}, ATR/сут"] = np.abs(carry(ch, (d - lag(d, 24)) / atr))
            P[f"пересечений {nm} за 10д"] = count_in(ch, 10 * DAY)
            if (x, y) in (("G", "Y"), ("Y", "R")):
                P[f"пересечений {nm} за 30д"] = count_in(ch, 30 * DAY)
        for k, nm in LN.items():
            P[f"закрытий 4ч от {nm}"] = np.asarray(a[f"f_run_{k}"], float)
        P["прошлая серия от зелёной"] = np.asarray(a["f_run_G_prev"], float)
        P["закрытий 1ч от синей 1ч"] = np.asarray(a["run_B1"], float)
        P["закрытий 1ч от красной 1ч"] = np.asarray(a["run_R"], float)
        sgF = sign_ffill(F - L["G"])
        P["пересечений цены и зелёной за 10д"] = count_in(np.r_[False, sgF[1:] != sgF[:-1]], 10 * DAY)
        P["ATR 4ч, %"] = atr / c * 100
        P["ранг ATR100 за год"] = np.asarray(rk, float)
        P["вес системы"] = np.asarray(W, float) / en.DIV
        hi24, lo24 = roll(h, 24, np.max), roll(l, 24, np.min)
        hi72, lo72 = roll(h, 72, np.max), roll(l, 72, np.min)
        P["размах 24ч, ATR"] = (hi24 - lo24) / atr
        P["размах 72ч, ATR"] = (hi72 - lo72) / atr
        P["эффективность 24ч"] = np.asarray(a["er24"], float)
        P["эффективность 72ч"] = eff(c, 72)
        b = en.bars4(a)
        x4 = en.ind432(b)
        pdi, mdi, tr4 = dmi(b["h"], b["l"], b["c"])
        idx4 = np.searchsorted(b["close_t"], t, side="right") - 1
        ok4 = idx4 >= 0
        idx4 = np.clip(idx4, 0, None)

        def m4(x):
            return np.where(ok4, np.asarray(x, float)[idx4], np.nan)
        atr100 = en.rma(tr4, 100)
        P["ADX 4ч"] = np.asarray(a["f_adx"], float)
        P["+DI 4ч"], P["−DI 4ч"] = m4(pdi), m4(mdi)
        P["+DI−DI 4ч"] = P["+DI 4ч"] - P["−DI 4ч"]
        P["ATR14/ATR100 4ч"] = m4(x4["atr"] / atr100)
        P["RSI 4ч"] = m4(rsi(b["c"]))
        P["RSI 1ч"] = rsi(c)
        for w, nm in ((4, "4ч"), (24, "24ч"), (72, "72ч"), (168, "7д"), (720, "30д")):
            P[f"ход {nm}, %"] = (c / lag(c, w) - 1) * 100
        hi30, lo30 = np.asarray(a["x_hi30"], float), np.asarray(a["x_lo30"], float)
        P["место в диапазоне 30д"] = (c - lo30) / (hi30 - lo30)
        P["от максимума 30д, ATR"] = (c - hi30) / atr
        P["от минимума 30д, ATR"] = (c - lo30) / atr
        hi90, lo90 = roll(h, 90 * DAY, np.max), roll(l, 90 * DAY, np.min)
        P["от максимума 90д, ATR"] = (c - hi90) / atr
        P["от минимума 90д, ATR"] = (c - lo90) / atr
        P["от исторического максимума, %"] = (c / np.maximum.accumulate(h) - 1) * 100
        P["часов после нового максимума 30д"] = since(h >= hi30)
        P["часов после нового минимума 30д"] = since(l <= lo30)
        dk = (t - 1) // 86400
        first = np.flatnonzero(np.r_[True, dk[1:] != dk[:-1]])
        lastd = np.r_[first[1:], len(t)] - 1
        dclose, dct = c[lastd], (dk[first] + 1) * 86400
        done = t[lastd] % 86400 == 0
        dclose, dct = dclose[done], dct[done]
        idxd = np.searchsorted(dct, t, side="right") - 1
        okd = idxd >= 0
        idxd = np.clip(idxd, 0, None)
        sma100 = roll(dclose, 100, np.mean)
        sma200 = roll(dclose, 200, np.mean)

        def md(x):
            return np.where(okd, np.asarray(x, float)[idxd], np.nan) if len(x) else np.full(n, np.nan)
        P["от SMA100 дня, %"] = (c / md(sma100) - 1) * 100
        P["наклон SMA100 дня 10д, %"] = md((sma100 / lag(sma100, 10) - 1) * 100)
        P["от SMA200 дня, %"] = (c / md(sma200) - 1) * 100
        P["пробой 432, ATR"] = m4((b["c"] - x4["hi30"]) / x4["atr"])
        P["от минимума 30 свечей 4ч, ATR"] = m4((b["c"] - x4["lo30"]) / x4["atr"])
        P["от EMA200 4ч, %"] = m4((b["c"] / x4["e200"] - 1) * 100)
        Fu = np.asarray(a.get("F", np.zeros(n)), float)
        has_f = np.nanmax(np.abs(Fu)) > 0
        ch_f = np.flatnonzero(np.diff(Fu) != 0)
        fresh = np.arange(n) <= (ch_f[-1] + 1 + 24 if len(ch_f) else -1)  # файл фандинга кончился — дальше пусто, не ноль
        for w, nm in ((24, "24ч"), (168, "7д"), (720, "30д")):
            P[f"фандинг {nm}, %"] = np.where(fresh, Fu - lag(Fu, w), np.nan) if has_f else np.full(n, np.nan)
        if h4f is not None and "vol_vs30" in h4f:
            j = np.asarray(a["j"], int)
            P["объём сутки к медиане 30д"] = h4f["vol_vs30"].to_numpy(float)[j]
            P["объём сутки к прошлым"] = h4f["vol_trend"].to_numpy(float)[j]
        else:
            P["объём сутки к медиане 30д"] = np.full(n, np.nan)
            P["объём сутки к прошлым"] = np.full(n, np.nan)
        ts = t - 3600
        P["час входа UTC"] = ((t // 3600) % 24).astype(float)
        P["день недели"] = (((ts // 86400) + 3) % 7).astype(float)
        P["флет-код"] = np.asarray(a["flat"], float)
    P["_phase"] = np.asarray(a["phase"], object)
    return P


ORDER_CHARS = "ЗЖКС"


def order_text(a: dict, i: int) -> str:
    v = [(float(a[f"f_{k}"][i]), ch) for k, ch in zip("GYRB", ORDER_CHARS)]
    return ">".join(ch for _, ch in sorted(v, reverse=True))


def row(P: dict, a: dict, i: int) -> dict:
    out = {k: (float(v[i]) if np.isfinite(v[i]) else None) for k, v in P.items() if not k.startswith("_")}
    out["фаза"] = str(P["_phase"][i])
    out["порядок линий"] = order_text(a, i)
    return out


def history(prev: list[tuple[int, int, int, float]], t_entry: int, side: int) -> dict:
    """prev — сделки той же стратегии: (вход t, выход t, сторона, итог % базы); берутся закрытые к часу входа."""
    done = [p for p in prev if p[1] <= t_entry]
    if not done:
        return {"прошлая сделка, % базы": None, "прошлая в плюсе": None, "прошлая та же сторона": None, "часов после прошлой": None,
                "сделок за 10д": 0.0, "сделок за 30д": 0.0, "из 5 прошлых в плюсе": None, "итог 30д, % базы": 0.0}
    p = done[-1]
    last5 = done[-5:]
    m10 = [x for x in done if x[1] > t_entry - 10 * 86400]
    m30 = [x for x in done if x[1] > t_entry - 30 * 86400]
    return {"прошлая сделка, % базы": p[3], "прошлая в плюсе": float(p[3] > 0), "прошлая та же сторона": float(p[2] == side), "часов после прошлой": (t_entry - p[1]) / 3600,
            "сделок за 10д": float(len(m10)), "сделок за 30д": float(len(m30)), "из 5 прошлых в плюсе": float(sum(x[3] > 0 for x in last5)),
            "итог 30д, % базы": float(sum(x[3] for x in m30))}


def path(a: dict, i0: int, i1: int, side: int, entry: float, exit_px: float) -> dict:
    """Путь сделки после часа входа по час выхода включительно: MFE/MAE в % и ATR 4ч входа, когда, отдача, что было раньше."""
    atr = float(a["atr4"][i0])
    h, l, c = a["h"][i0 + 1:i1 + 1], a["l"][i0 + 1:i1 + 1], a["c"]
    fav = (h - entry) if side == 1 else (entry - l)
    adv = (entry - l) if side == 1 else (h - entry)
    if len(h):
        k_f, k_a = int(np.argmax(fav)), int(np.argmax(adv))
        mfe, mae = max(float(fav[k_f]), 0.0), max(float(adv[k_a]), 0.0)
        hit_f = np.flatnonzero(fav >= atr)
        hit_a = np.flatnonzero(adv >= atr)
        f1 = hit_f[0] if len(hit_f) else 10 ** 9
        a1 = hit_a[0] if len(hit_a) else 10 ** 9
        first = 1.0 if f1 < a1 else (-1.0 if a1 < f1 else (0.0 if f1 == 10 ** 9 else 0.5))
    else:
        k_f = k_a = 0
        mfe = mae = 0.0
        first = 0.0
    fin = side * (exit_px - entry)
    out = {"MFE, %": mfe / entry * 100, "MAE, %": mae / entry * 100, "MFE, ATR": mfe / atr, "MAE, ATR": mae / atr,
           "часов до MFE": float(k_f + 1) if len(h) else 0.0, "часов до MAE": float(k_a + 1) if len(h) else 0.0,
           "отдача, ATR": (mfe - fin) / atr, "отдача, доля MFE": (mfe - fin) / mfe if mfe > 0 else None,
           "сначала +1 ATR или −1 ATR": first, "часов в сделке": float(i1 - i0)}
    for w, nm in ((24, "24ч"), (72, "72ч"), (168, "7д")):
        j = min(i0 + w, i1)
        px = exit_px if j == i1 else float(c[j])
        out[f"ход через {nm}, %"] = side * (px / entry - 1) * 100
    return out


# ---------- балл M2 (flat_1109b): только тень ----------
M2_FEATS = ["до зелёной", "до жёлтой", "до красной", "до синей", "до синей 1ч", "до красной 1ч", "наклон зелёной", "наклон жёлтой", "наклон красной", "наклон синей 5д",
            "порядок линий", "ч после G/Y", "ч после Y/R", "ч после синей", "пересечений", "ADX", "ранг ширины", "эффективность 24ч", "ранг ATR", "вес", "шорт под жёлтой",
            "сторона", "по прошлому направлению", "флет", "прошлая сделка в плюсе"]


def m2_vector(a: dict, lay: tuple, i: int, side: int, tag: str, prev_res: float, al: tuple | None = None) -> np.ndarray:
    """Те же 25 признаков, что flat_1109.positions (проверяется в trade_table.py на всей истории)."""
    st, last = al if al is not None else align(a)
    rk, W = lay
    m = a["st"][i]
    x = list(side * m[:11]) + list(m[11:15]) + [a["f_adx"][i], a["f_width_rank"][i], a["er24"][i], rk[i], W[i], float(tag == en.CS), float(side),
                                                float(side == last[i]), float(st[i] == 0), float(prev_res > 0)]
    return np.nan_to_num(np.array(x, float))


def m2_load(path: Path = M2_PATH) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text())


def m2_score(model: dict, x: np.ndarray) -> float:
    """Ранг прогноза итога сделки среди сделок обучения, 0..1 (0.5 — середина). Размер в тени = 0.5 + ранг."""
    z = (x - np.array(model["mean"])) / np.array(model["scale"])
    pred = float(z @ np.array(model["coef"]) + model["intercept"])
    q = np.array(model["train_sorted"])
    return float(np.searchsorted(q, pred, side="right") / len(q))
