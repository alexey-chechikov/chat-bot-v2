"""Учёт позиций по деньгам (разбор GPT 5d9e542, PREREG_gpt_check.md): количество монеты внутри сделки постоянно, издержка от оборота каждого исполнения,
фандинг = сторона × q × цена выплаты × ставка, кривая счёта по часам вместе с открытыми сделками. Сделки — кортежи (i0, i1, p0, p1, сторона)."""
from __future__ import annotations

import sys
from collections import namedtuple
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import flips_blue as fb  # noqa: E402
import history_v1 as hv  # noqa: E402
import pos  # noqa: E402
import tp_blue as tb  # noqa: E402

NOTIONAL = 1000.0
SIDE_COST = pos.COST / 2 / 100
Leg = namedtuple("Leg", "i0 i1 p0 p1 s")
LIM5D = 120


def funding_marks(a, fund):
    """Накопленная выплата на 1 монету: ставка × цена на закрытии часа выплаты."""
    t, c = a["t"], a["c"]
    fm = np.zeros(len(t))
    idx = np.searchsorted(t, fund.index.to_numpy(), side="left")
    keep = idx < len(t)                                               # выплата после последнего бара ещё не случилась (разбор GPT 37233f5)
    np.add.at(fm, idx[keep], fund.to_numpy()[keep] * c[idx[keep]])
    return np.cumsum(fm)


def trade_cash(fm, tr):
    i0, i1, p0, p1, s = tr
    q = NOTIONAL / p0
    return s * q * (p1 - p0), NOTIONAL * SIDE_COST + q * p1 * SIDE_COST, s * q * (fm[i1] - fm[i0])


def trades_a(a, conf=1, band=1.0):
    return [(x, y, a["c"][x], a["c"][y], s) for x, y, s in fb.flip_legs(a, conf, band)]


def trades_b(a, f, stop="S2", single=False):
    """Лонг к голубой: выход как в tp_blue.outcomes, но с индексом и ценой. single — событие пропускается, пока прошлая сделка открыта."""
    x = tb.make_arrays(a, 1)
    ev = tb.events(a, 1, "L1", x)
    n, atr = len(x["c"]), a["atr4"]
    out, last = [], -1
    for i in ev:
        if single and i <= last:
            continue
        e_lim = min(i + 1 + tb.LIM, n)
        entry = x["c"][i]
        h, l, o, c = x["h"][i + 1:e_lim], x["l"][i + 1:e_lim], x["o"][i + 1:e_lim], x["c"][i + 1:e_lim]
        if len(h) == 0:
            continue
        lvl = entry * (1 - 3.0 * atr[i] / a["c"][i]) if stop == "S2" else x["l"][max(i - 23, 0):i + 1].min() * (1 - 0.25 * atr[i] / a["c"][i])
        hit = l <= lvl
        st_i, st_px = (int(np.argmax(hit)), min(lvl, o[int(np.argmax(hit))])) if hit.any() else (len(h) - 1, c[-1])
        lv = entry + f * (x["B4p"][i] - entry)
        ok = h[:st_i + 1] >= lv
        if ok.any() and int(np.argmax(ok)) < st_i:
            k = int(np.argmax(ok))
            ex, px = i + 1 + k, max(lv, o[k])
        else:
            ex, px = i + 1 + st_i, st_px
        out.append((i, ex, entry, px, 1))
        last = ex
    return out


def trades_c(a, far_max=3.0, adx_max=25.0, m_tp=3.0, k_st=1.5):
    """Лонг после мелкого отката к зелёной: отбор как в entry_rules.green_cross, выход как в history_v1.manage, но с индексом и ценой."""
    t, c, j = a["t"], a["c"], a["j"]
    n, idx = len(t), np.arange(len(t))
    new4 = j != np.r_[-1, j[:-1]]
    ev = idx[new4 & (idx >= a["i0"]) & (a["f_run_G"] == 1) & (a["f_run_G_prev"] <= -3)]
    ev = ev[ev + LIM5D < n]
    ev = ev[(a["f_far30"][ev] <= far_max) & (a["f_adx"][ev] <= adx_max)]
    out = []
    for i in ev:
        p0 = c[i]
        atr = a["atr4"][i] / p0
        h, l, o = a["h"][i + 1:i + 1 + LIM5D], a["l"][i + 1:i + 1 + LIM5D], a["o"][i + 1:i + 1 + LIM5D]
        lv, lvt = p0 * (1 - k_st * atr), p0 * (1 + m_tp * atr)
        hs, ht = l <= lv, h >= lvt
        st_i = int(np.argmax(hs)) if hs.any() else LIM5D
        tp_i = int(np.argmax(ht)) if ht.any() else LIM5D
        if st_i <= tp_i and st_i < LIM5D:
            ex, px = i + 1 + st_i, min(lv, o[st_i])
        elif tp_i < LIM5D:
            ex, px = i + 1 + tp_i, max(lvt, o[tp_i])
        else:
            ex, px = i + LIM5D, c[i + LIM5D]
        out.append((i, ex, p0, px, 1))
    return out


def equity(a, fm, trades):
    """Кривая счёта по часам, $ при $1000 на вход. → closes (по закрытию часа, с вычетом стоимости закрытия открытых), worst (по худшей цене часа), число сделок и номинал."""
    c, h, l = a["c"], a["h"], a["l"]
    n = len(c)
    closed, op_c, op_w, ex_w = np.zeros(n), np.zeros(n), np.zeros(n), np.zeros(n)
    cnt, notion = np.zeros(n, dtype=int), np.zeros(n)
    for tr in trades:
        i0, i1, p0, p1, s = tr
        q = NOTIONAL / p0
        move, fee, fund = trade_cash(fm, tr)
        closed[i1] += move - fee - fund
        adv1 = l[i1] if s == 1 else h[i1]
        ex_w[i1] += min(0.0, s * q * (adv1 - p1))
        if i1 > i0:
            k = np.arange(i0, i1)
            run = -NOTIONAL * SIDE_COST - s * q * (fm[k] - fm[i0])
            op_c[k] += s * q * (c[k] - p0) - q * c[k] * SIDE_COST + run
            adv = (l[k] if s == 1 else h[k]).copy()
            adv[0] = c[i0]
            op_w[k] += s * q * (adv - p0) - q * adv * SIDE_COST + run
            cnt[k] += 1
            notion[k] += q * c[k]
    base = np.cumsum(closed)
    return base + op_c, base + op_w + ex_w, cnt, notion


def drawdown(eq, worst, t):
    peak = np.maximum.accumulate(np.r_[0.0, eq])[1:]
    d = eq - peak
    i = int(np.argmin(d))
    under, best = 0, 0
    for v in d:
        under = under + 1 if v < 0 else 0
        best = max(best, under)
    return round(float(d.min()), 1), round(float((worst - peak).min()), 1), pos.utc_full(t[i]), round(best / 24)


def block_ci(eq, i0, block_days=90, reps=9999, seed=20261105):
    """Блочный бутстрап дневных изменений кривой: 95% интервал суммы, % номинала."""
    d = np.diff(eq[i0::24]) / NOTIONAL * 100
    n = len(d)
    rng = np.random.default_rng(seed)
    k = int(np.ceil(n / block_days))
    d2 = np.r_[d, d]
    cs = np.r_[0.0, np.cumsum(d2)]
    st = rng.integers(0, n, size=(reps, k))
    tot = (cs[st + block_days] - cs[st]).sum(axis=1) * (n / (k * block_days))
    return round(float(np.quantile(tot, .025)), 1), round(float(np.quantile(tot, .975)), 1), round(float((tot <= 0).mean() * 100), 2)


def summary(a, fm, trades, lab, coin, per=pos.PER):
    t = a["t"]
    pnl_new, fund_tot, fee_tot, old = [], 0.0, 0.0, []
    for tr in trades:
        move, fee, fund = trade_cash(fm, tr)
        pnl_new.append((move - fee - fund) / NOTIONAL * 100)
        fund_tot += fund
        fee_tot += fee
        i0, i1, p0, p1, s = tr
        old.append(s * (p1 / p0 - 1) * 100 - pos.COST - s * (a["F"][i1] - a["F"][i0]))
    r, old = np.array(pnl_new), np.array(old)
    eq, worst, cnt, notion = equity(a, fm, trades)
    i0s = np.array([x[0] for x in trades])
    tt = t[i0s]
    p_sum = {p: round(float(r[(tt >= x) & (tt < z)].sum()), 1) for p, (x, z) in per.items()}
    dd_c, dd_w, dd_t, und = drawdown(eq, worst, t)
    lo, hi, pneg = block_ci(eq, a["i0"])
    se = r.std(ddof=1) / np.sqrt(len(r))
    return {"монета": coin, "что": lab, "n": len(r), "среднее_%": round(float(r.mean()), 2), "плюс_%": round(float((r > 0).mean() * 100), 1), "сумма_старый_%": round(float(old.sum()), 1), "сумма_%": round(float(r.sum()), 1),
            "фандинг_%": round(fund_tot / NOTIONAL * 100, 1), "издержки_%": round(fee_tot / NOTIONAL * 100, 1), **p_sum, "ди_низ_сделки": round(float(r.mean() - 1.96 * se), 2),
            "просадка_закрытых_%": pos.max_dd(r), "просадка_часы_%": round(dd_c / NOTIONAL * 100, 1), "просадка_худшая_%": round(dd_w / NOTIONAL * 100, 1), "дно": dd_t, "под_водой_дней": und,
            "пик_сделок": int(cnt.max()), "пик_номинала_$": int(notion.max()), "блок_низ_%": lo, "блок_верх_%": hi, "блок_≤0_%": pneg}


def shift_rank(a, fm, trades, step=4, gap_days=90):
    """Контроль политики: все сделки сдвигаются по кругу на каждый шаг 4ч. Цена и выплаты после конца ряда продолжаются с начала ряда с масштабом, ход не рвётся.
    Выход не по закрытию (цель, стоп) сдвигается вместе со своим отступом от закрытия часа, поэтому нулевой сдвиг обязан равняться учёту (разбор GPT 37233f5)."""
    b = a["i0"]
    c0, f0 = a["c"][b:], fm[b:]
    scale = c0[-1] / c0[0]
    c2 = np.r_[c0, c0 * scale]
    f2 = np.r_[f0, f0[-1] + (f0 - f0[0]) * scale]
    s0 = np.array([x[0] for x in trades]) - b
    s1 = np.array([x[1] for x in trades]) - b
    side = np.array([x[4] for x in trades])
    prem = np.array([x[3] / a["c"][x[1]] for x in trades])
    prem0 = np.array([x[2] / a["c"][x[0]] for x in trades])

    def total(k, mask=None):
        i, e = s0 + k, s1 + k
        p0, p1 = c2[i] * prem0, c2[e] * prem
        v = side * (p1 / p0 - 1) - SIDE_COST - (p1 / p0) * SIDE_COST - side * (f2[e] - f2[i]) / p0
        return (v if mask is None else v[mask]).sum() * 100

    led = sum((lambda m: (m[0] - m[1] - m[2]))(trade_cash(fm, tr[:5])) for tr in trades) / NOTIONAL * 100
    assert abs(total(0) - led) < 1e-6, "нулевой сдвиг обязан равняться учёту"
    N = len(c0)
    gap = gap_days * 24
    shifts = np.arange(gap, N - gap, step)
    out = {}
    for lab, mask in (("всё", None), ("лонг", side == 1), ("шорт", side == -1)):
        real = total(0, mask)
        ctl = np.array([total(int(k), mask) for k in shifts])
        out[lab] = {"сумма_%": round(float(real), 1), "медиана_сдвигов_%": round(float(np.median(ctl)), 1), "лучше_%": round(float((ctl < real).mean() * 100), 2), "ранг": round(float(((ctl >= real).sum() + 1) / (len(ctl) + 1)), 5), "сдвигов": len(ctl)}
    return out


def check_same_as_old(a, f=0.5, stop="S2"):
    """Сделки ledger при старом учёте обязаны совпасть с tp_blue.outcomes и history_v1.manage: иначе таблицы считают другие сделки."""
    tb.FR = [f]
    x = tb.make_arrays(a, 1)
    ev = tb.events(a, 1, "L1", x)
    old = tb.outcomes(a, x, ev, 1, stop)[f"f{f}"]
    new = np.array([s * (p1 / p0 - 1) * 100 - pos.COST - s * (a["F"][i1] - a["F"][i0]) for i0, i1, p0, p1, s in trades_b(a, f, stop)])
    ok = ~np.isnan(old)
    assert np.allclose(old[ok], new, atol=1e-9), "B: сделки разошлись со старым кодом"
    trs = trades_c(a)
    new = np.array([s * (p1 / p0 - 1) * 100 - pos.COST - s * (a["F"][i1] - a["F"][i0]) for i0, i1, p0, p1, s in trs])
    old = np.array([hv.manage(a, Leg(i, i + LIM5D, a["c"][i], a["c"][i + LIM5D], 1), 1.5, 3) for i, *_ in trs])
    assert np.allclose(old, new, atol=1e-9), "C: сделки разошлись со старым кодом"


def self_check():
    """Контрпримеры GPT на кривой и выплате: 100→70→101, лонг при цене выплаты 200, шорт 100→90."""
    c = np.array([100.0, 70.0, 101.0])
    a = {"t": np.array([3600, 7200, 10800]), "c": c, "h": c, "l": c}
    fm = np.zeros(3)
    tr = (0, 2, 100.0, 101.0, 1)
    eq, worst, cnt, _ = equity(a, fm, [tr])
    assert pos.max_dd(np.array([0.864])) == 0.0
    assert eq[1] < -300 and worst[1] < -300 and cnt.max() == 1, "кривая обязана видеть 70 внутри сделки"
    fm = np.array([0.0, 2.0, 2.0])                                    # ставка 1% при цене 200 на 1 монету
    assert abs(trade_cash(fm, tr)[2] - 20.0) < 1e-9, "q=10, 200×1%×10 = $20, а не 1% от начальных $1000"
    move, fee, fund = trade_cash(np.zeros(3), (0, 2, 100.0, 90.0, -1))
    assert abs(move - 100.0) < 1e-9 and abs(fee - (0.68 + 0.612)) < 1e-9 and fund == 0.0
