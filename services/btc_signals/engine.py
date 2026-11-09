"""Система оператора по BTC: Простое+, шорт под жёлтой, добор. Те же правила и порядок проверок, что в
docs/tv_pine_scripts/bot7_operator_strategy_A.pine и в research/chart_walk_20261105/pine_mirror_pyr.py (по часам),
но на выходе события: вход, добор, выход — с ценой, весом и уровнями.

Значения 4ч на часе — последняя закрытая свеча 4ч; t[i] — время закрытия часа i (UTC).
Лонг над синей: цена 4ч выше синей EMA200, 2 закрытия 4ч подряд над зелёной, и красная не пробита вниз дважды.
  Выход: 2 закрытия 4ч подряд под красной.
Шорт под синей: цена 4ч ниже синей, 2 закрытия подряд под зелёной, ранг волатильности ≤0.6. Выход: 2 закрытия над зелёной.
Шорт под жёлтой: над синей, ровно второе закрытие под жёлтой, цена выше синей больше чем на 0.5%.
  Цель: синяя (прошлой свечи 4ч) +0.5% — касание по уровню или по открытию часа. Отмена: 2 закрытия над жёлтой.
Добор (только лонг над синей и шорт под синей): первый лот 0.5, добор 0.5 при ходе 2×ATR14 (4ч на входе).
Вес = медиана волатильности за год / текущая, в пределах 0.5–2, делится на 1.18, фиксируется на входе.
Результат — % от базы с весом, издержка 0.068% на сторону, без фандинга."""
from __future__ import annotations

import numpy as np

K4 = 2
SC = 0.068
DIV = 1.18
FIRST = 0.5
ADD = 0.5
X_ATR = 2.0
RANK_TH = 0.6
CS_TOL = 1.005
MAIN = ("над синей", "под синей")
CS = "под жёлтой"


def leg_net(side: int, p0: float, p1: float) -> float:
    """% хода позиции после издержек на вход и выход."""
    return side * (p1 / p0 - 1) * 100 - SC - SC * (p1 / p0)


def simulate(a: dict, lay: tuple, n: int | None = None, lx_blue: bool = False) -> tuple[list[dict], dict | None]:
    """lx_blue — тень V2 (записки оператора 08.11): лонг закрывается ещё и 2 закрытиями 4ч под синей. Только для журнала тени."""
    t, c, h, l, o, j = a["t"], a["c"], a["h"], a["l"], a["o"], a["j"]
    F, B, atr4, Bp = a["f_close"], a["f_B"], a["atr4"], a["B4p"]
    rG0, rY0, rR0 = a["f_run_G"], a["f_run_Y"], a["f_run_R"]
    rB0 = a["f_run_B"] if lx_blue else None
    rk, W = lay
    n = len(t) if n is None else n
    new = np.r_[True, j[1:] != j[:-1]]
    ev: list[dict] = []
    pos: dict | None = None
    for i in range(int(a["i0"]), n):
        new4 = bool(new[i])
        rG, rY, rR = rG0[i], rY0[i], rR0[i]
        lv_cs = float(Bp[i]) * CS_TOL
        close_now, x_px, why = False, 0.0, ""
        if pos and pos["tag"] == CS and l[i] <= lv_cs < pos["entry"]:
            close_now, x_px, why = True, min(lv_cs, float(o[i])), "цель: синяя +0.5%"
        if new4 and not close_now and pos:
            if pos["side"] == 1 and rR <= -K4:
                close_now, x_px, why = True, float(c[i]), "2 закрытия 4ч под красной"
            elif pos["side"] == 1 and lx_blue and rB0[i] <= -K4:
                close_now, x_px, why = True, float(c[i]), "2 закрытия 4ч под синей"
            elif pos["tag"] == CS and rY >= K4:
                close_now, x_px, why = True, float(c[i]), "отмена: 2 закрытия 4ч над жёлтой"
            elif pos["tag"] == "под синей" and rG >= K4:
                close_now, x_px, why = True, float(c[i]), "2 закрытия 4ч над зелёной"
        if pos and pos["tag"] in MAIN and not close_now and not pos["add_done"]:
            lv = pos["add_lv"]
            if (pos["side"] == 1 and h[i] >= lv) or (pos["side"] == -1 and l[i] <= lv):
                pos["add_done"] = True
                pos["add_px"] = max(lv, float(o[i])) if pos["side"] == 1 else min(lv, float(o[i]))
                pos["add_t"] = int(t[i])
                ev.append({"kind": "добор", "t": int(t[i]), "i": i, "side": pos["side"], "tag": pos["tag"], "px": pos["add_px"], "w": pos["w"] * ADD, "pos": dict(pos)})
        if close_now:
            s, w = pos["side"], pos["w"]
            if pos["tag"] in MAIN:
                res = leg_net(s, pos["entry"], x_px) * w * FIRST
                if pos["add_done"]:
                    res += leg_net(s, pos["add_px"], x_px) * w * ADD
            else:
                res = leg_net(s, pos["entry"], x_px) * w
            ev.append({"kind": "выход", "t": int(t[i]), "i": i, "side": s, "tag": pos["tag"], "px": x_px, "why": why, "res": res, "pos": dict(pos)})
            pos = None
        if new4 and pos is None:
            o_side, o_tag = 0, ""
            if F[i] > B[i]:
                if rG >= K4 and rR > -K4:
                    o_side, o_tag = 1, "над синей"
                elif rY == -K4 and c[i] > B[i] * CS_TOL:
                    o_side, o_tag = -1, CS
            elif rG <= -K4 and not rk[i] > RANK_TH:
                o_side, o_tag = -1, "под синей"
            if o_side:
                e = float(c[i])
                ea = float(atr4[i])
                pos = {"side": o_side, "tag": o_tag, "entry": e, "entry_t": int(t[i]), "entry_i": i, "w": float(W[i]) / DIV, "atr": ea,
                       "add_lv": e + o_side * X_ATR * ea, "add_done": False, "add_px": None, "add_t": None}
                ev.append({"kind": "вход", "t": int(t[i]), "i": i, "side": o_side, "tag": o_tag, "px": e, "w": pos["w"], "pos": dict(pos)})
    return ev, pos


H4 = 14400
TAG432 = "432"
CH432 = 30
ADX432 = 22.0
BRK432 = 0.5
HOLD432 = 20
WARM432 = 300


def rma(x: np.ndarray, n: int) -> np.ndarray:
    """Как ta.rma: старт средним первых n конечных значений, до этого NaN."""
    x = np.asarray(x, float)
    out = np.full(len(x), np.nan)
    ok = np.flatnonzero(np.isfinite(x))
    if len(ok) < n:
        return out
    b = ok[0]
    acc = x[b:b + n].mean()
    out[b + n - 1] = acc
    for i in range(b + n, len(x)):
        if np.isfinite(x[i]):
            acc = (acc * (n - 1) + x[i]) / n
        out[i] = acc
    return out


def ema(x: np.ndarray, n: int) -> np.ndarray:
    al = 2.0 / (n + 1)
    out = np.empty(len(x))
    acc = float(x[0])
    for i, v in enumerate(x):
        acc = al * float(v) + (1 - al) * acc if i else acc
        out[i] = acc
    return out


def bars4(a: dict) -> dict:
    """Свечи 4ч из часов (t — время закрытия часа): open, high, low, close, последний час свечи, закрыта ли свеча."""
    t = np.asarray(a["t"], np.int64)
    k = (t - 1) // H4
    first = np.flatnonzero(np.r_[True, k[1:] != k[:-1]])
    last = np.r_[first[1:], len(t)] - 1
    return {"o": np.asarray(a["o"], float)[first], "h": np.maximum.reduceat(np.asarray(a["h"], float), first), "l": np.minimum.reduceat(np.asarray(a["l"], float), first),
            "c": np.asarray(a["c"], float)[last], "last_i": last, "done": t[last] % H4 == 0, "close_t": (k[first] + 1) * H4}


def ind432(b: dict) -> dict:
    h, l, c = b["h"], b["l"], b["c"]
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    atr = rma(tr, 14)
    up, dn = np.r_[0.0, h[1:] - h[:-1]], np.r_[0.0, l[:-1] - l[1:]]
    pdm, mdm = np.where((up > dn) & (up > 0), up, 0.0), np.where((dn > up) & (dn > 0), dn, 0.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        pdi, mdi = 100 * rma(pdm, 14) / atr, 100 * rma(mdm, 14) / atr
        dx = 100 * np.abs(pdi - mdi) / (pdi + mdi)
    adx = rma(np.where(np.isfinite(dx), dx, np.nan), 14)
    n = len(c)
    hi30, lo30 = np.full(n, np.nan), np.full(n, np.nan)
    for k in range(CH432, n):
        hi30[k], lo30[k] = h[k - CH432:k].max(), l[k - CH432:k].min()
    nxt_hi = np.array([h[max(k - CH432 + 1, 0):k + 1].max() for k in range(n)])
    nxt_lo = np.array([l[max(k - CH432 + 1, 0):k + 1].min() for k in range(n)])
    return {"atr": atr, "adx": adx, "e200": ema(c, 200), "hi30": hi30, "lo30": lo30, "next_hi30": nxt_hi, "next_lo30": nxt_lo}


def simulate432(a: dict) -> tuple[list[dict], dict | None, dict]:
    """432 (research/btc432_20261103, btc_vs_432.s432), только лонг, по закрытым свечам 4ч.
    Вход: закрытие выше максимума 30 прошлых свечей, пробой ≥0.5 ATR14, ADX14 ≥22, закрытие выше EMA200 4ч.
    Выход: закрытие ниже минимума 30 прошлых свечей или 20 свечей с сигнала. Одна позиция, размер 1.0 базы.
    Цена — закрытие свечи 4ч (в разборе — открытие следующей, это та же минута). → (события, позиция, уровни последней свечи)."""
    b = bars4(a)
    x = ind432(b)
    c, atr, adx, e200, hi30, lo30 = b["c"], x["atr"], x["adx"], x["e200"], x["hi30"], x["lo30"]
    t = np.asarray(a["t"], np.int64)
    with np.errstate(invalid="ignore", divide="ignore"):
        ent = (c > hi30) & (adx >= ADX432) & (c > e200) & ((c - hi30) / atr >= BRK432)
    ent[:WARM432] = False
    k0 = max(int(np.searchsorted(b["close_t"], t[int(a["i0"])])), WARM432)
    done = np.flatnonzero(b["done"])
    ev: list[dict] = []
    pos: dict | None = None
    for k in done[done >= k0]:
        i = int(b["last_i"][k])
        if pos is not None:
            why = ""
            if c[k] < lo30[k]:
                why = f"закрытие 4ч ниже минимума 30 свечей ({lo30[k]:,.0f})".replace(",", " ")
            elif k - pos["sig_bar"] >= HOLD432:
                why = "прошло 20 свечей 4ч с сигнала"
            if why:
                px = float(c[k])
                ev.append({"kind": "выход", "t": int(t[i]), "i": i, "side": 1, "tag": TAG432, "px": px, "why": why, "res": leg_net(1, pos["entry"], px), "pos": dict(pos)})
                pos = None
            continue
        if ent[k]:
            px = float(c[k])
            pos = {"side": 1, "tag": TAG432, "entry": px, "entry_t": int(t[i]), "entry_i": i, "w": 1.0, "atr": float(atr[k]), "add_lv": None, "add_done": False,
                   "add_px": None, "add_t": None, "sig_bar": int(k), "hi30": float(hi30[k]), "adx": float(adx[k]), "exit_by_t": int(b["close_t"][k]) + HOLD432 * H4}
            ev.append({"kind": "вход", "t": int(t[i]), "i": i, "side": 1, "tag": TAG432, "px": px, "w": 1.0, "pos": dict(pos)})
    kl = int(done[-1]) if len(done) else len(c) - 1
    lv = {"close": float(c[kl]), "atr": float(atr[kl]), "adx": float(adx[kl]), "e200": float(e200[kl]), "next_hi30": float(x["next_hi30"][kl]), "next_lo30": float(x["next_lo30"][kl]),
          "t": int(b["close_t"][kl])}
    return ev, pos, lv


def trades(ev: list[dict]) -> list[tuple[int, int, int, float, bool]]:
    """Закрытые сделки в виде pine_mirror_pyr.run: (час входа, час выхода, сторона, итог %, был ли добор)."""
    return [(e["pos"]["entry_i"], e["i"], e["side"], e["res"], bool(e["pos"]["add_done"]) and e["tag"] in MAIN) for e in ev if e["kind"] == "выход"]
