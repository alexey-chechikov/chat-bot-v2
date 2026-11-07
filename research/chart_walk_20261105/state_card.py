"""Карта текущего положения: линии, расстояния, направления, пересечения, фаза, позиция автомата, следующие события с ценами и похожие места из разобранных участков.
Только чтение данных backtests/frozen, ничего не торгует и никуда не шлёт. Любую дату можно подставить: --at "2025-12-12 08:00". Запуск: python state_card.py [BTC|ETH] [--at "..."]
Похожие участки показывают, что оператор делал в таком положении; направление и флет-или-ход вперёд они не предсказывают (state_map_eval.py: AUC 0.50–0.52, как у случайных)."""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
import cw_data as cw  # noqa: E402
import gpt_check as gc  # noqa: E402
import ledger as lg  # noqa: E402
import pos  # noqa: E402
import segment1_chart as sc  # noqa: E402
import state_map as sm  # noqa: E402
import words as wd  # noqa: E402
import words2 as w2  # noqa: E402

CFG = dict(w2.MAIN26)
S_STOP, S_TP = CFG["s_stop"], CFG["s_tp"]
FAR_G, FAR_B = -5.0, -10.0


def load_coin(coin):
    """Свежие минуты из frozen: копия, последняя неполная строка и неполный час отбрасываются."""
    tmp = Path(tempfile.mkdtemp(prefix="state_card_"))
    src = gc.FROZEN
    new = tmp / f"{coin}USDT_1m_2y.csv"
    raw = (src / new.name).read_bytes()
    new.write_bytes(raw[:raw.rfind(b"\n") + 1])
    cw.md.SRC_OLD, cw.md.SRC_NEW, cw.md.SRC_FUND = src / f"{coin}USDT_1m_2017_2024.csv", new, src / f"{coin}USDT_funding_full.csv"
    m = cw.md.load_1m()
    last = int(m["ts"].iloc[-1]) + 60
    m = m[m["ts"] < last // 3600 * 3600]
    h1, h4 = cw.md.add_ind(cw.md.bars(m, 3600)), cw.md.add_ind(cw.md.bars(m, 14400))
    d1 = cw.md.bars(m, 86400)
    fund = cw.md.load_funding()
    shutil.rmtree(tmp, ignore_errors=True)
    h1f, h4f = cw.features(h1, h4, 1), cw.features(h4, h1, 4)
    a, _ = gc.er.prep(h1f, h4f, d1, fund)
    wd.add_runs(a)
    sm.add_state(a)
    return a, lg.funding_marks(a, fund), h4f


def way(v, eps):
    return "вверх" if v > eps else ("вниз" if v < -eps else "плоско")


def last_cross(x, y, i):
    s = np.sign(x[:i + 1] - y[:i + 1])
    w = np.where(s[1:] != s[:-1])[0]
    if not len(w):
        return None
    k = int(w[-1]) + 1
    return k, "вверх" if s[k] > 0 else "вниз"


def p_fmt(x):
    return f"{x:,.0f}".replace(",", " ")


def lines_block(a, i):
    c, fc, atr = a["c"][i], a["f_close"][i], a["atr4"][i]
    rows = []
    for nm, col, ref, slope, eps, runs, need in (("зелёная 4ч", "f_G", fc, a["st"][i, 6], .15, a["f_run_G"][i], 2), ("жёлтая 4ч", "f_Y", fc, a["st"][i, 7], .15, a["f_run_Y"][i], 2), ("красная 4ч", "f_R", fc, a["st"][i, 8], .15, a["f_run_R"][i], 2), ("голубая 4ч", "f_B", fc, a["st"][i, 9], sm.FLAT_B4, a["f_run_B"][i], 2),
                                                 ("голубая 1ч", "B1h", c, (a["B1h"][i] - a["B1h"][i - 24]) / atr, .15, a["run_B1"][i], 3), ("красная 1ч", "R1", c, (a["R1"][i] - a["R1"][i - 24]) / atr, .15, a["run_R"][i], 3)):
        v = a[col][i]
        side = "над" if runs > 0 else "под"
        rows.append(f"  {nm:<11} {p_fmt(v):>8}  {(ref / v - 1) * 100:+6.2f}%  {(ref - v) / atr:+5.1f} ATR  {way(slope, eps):<6} закрытий {side}: {abs(int(runs))}{' — закрепились' if abs(runs) >= need else ''}")
    return rows


def cross_block(a, i):
    t = a["t"]
    out = []
    for nm, x, y in (("зелёная/жёлтая", a["f_G"], a["f_Y"]), ("жёлтая/красная", a["f_Y"], a["f_R"]), ("цена/голубая 4ч", a["f_close"], a["f_B"]), ("цена/голубая 1ч", a["c"], a["B1h"])):
        r = last_cross(x, y, i)
        if r:
            out.append(f"  {nm}: {r[1]} {sm.utc(t[r[0]])}, {(i - r[0]) / 24:.1f} дн. назад")
    return out


def events(a, i, st):
    """Что должно случиться дальше: по правилам автомата, с ценами сейчас."""
    fc, c, g, y, r, b, b1, r1 = a["f_close"][i], a["c"][i], a["f_G"][i], a["f_Y"][i], a["f_R"][i], a["f_B"][i], a["f_B1"][i], a["R1"][i]
    atr, rg, ry, rr, r_1 = a["atr4"][i], a["f_run_G"][i], a["f_run_Y"][i], a["f_run_R"][i], a["run_R"][i]
    cnt = f"сейчас 4ч под зелёной {max(-rg, 0)} из 2, 1ч под красной {max(-r_1, 0)} из 3"
    cur = st["cur"]
    L = []
    if cur is not None and cur[2] == 1:
        i0, p0, _, tag, _ = cur
        size = "полный" if w2.in_portrait(a, i0, 1) else "половина (вне описания)"
        L.append(f"ПОЗИЦИЯ: лонг «{tag}» с {sm.utc(a['t'][i0])}, вход {p_fmt(p0)}, сейчас {(c / p0 - 1) * 100:+.2f}%, размер {size}")
        if tag == "к голубой":
            L.append(f"  цель: голубая 4ч минус 0.5% = {p_fmt(b * .995)}" + (" — уже ниже входа, цель не определена" if p0 >= b * .995 else ""))
            L.append(f"  закрыть: 4ч под зелёной {p_fmt(g)} и жёлтой {p_fmt(y)} и 3 закрытия 1ч под красной {p_fmt(r1)}, дальше перекладка в шорт. X01 (без жёлтой): {cnt}")
        elif tag == "над голубыми":
            L.append(f"  закрыть: 2 закрытия 4ч под жёлтой {p_fmt(y)}, сейчас {max(-ry, 0)} из 2. X01: {cnt}")
        else:
            L.append(f"  закрыть: 2 закрытия 4ч под красной {p_fmt(r)}, сейчас {max(-rr, 0)} из 2. X01: {cnt}")
    elif cur is not None:
        i0, p0, _, tag, _ = cur
        a0 = a["atr4"][i0]
        L.append(f"ПОЗИЦИЯ: шорт «{tag}» с {sm.utc(a['t'][i0])}, вход {p_fmt(p0)}, сейчас {(p0 / c - 1) * 100:+.2f}%")
        L.append(f"  стоп 2 ATR {p_fmt(p0 + S_STOP * a0)}, тейк 6 ATR {p_fmt(p0 - S_TP * a0)}")
        L.append(f"  далеко: −5% от зелёной = {p_fmt(g * (1 + FAR_G / 100))}" + (f", −10% от голубой = {p_fmt(b * (1 + FAR_B / 100))}" if tag.startswith("от голубой") else ""))
        if tag == "от голубой":
            L.append(f"  стоп по линии: закрытие 4ч над голубой {p_fmt(b)}; под зелёной {p_fmt(g)} включится обычный выход шорта")
        elif tag == "над голубыми":
            L.append(f"  закрыть: 4ч над зелёной {p_fmt(g)} и 3 закрытия 1ч над голубой 1ч {p_fmt(a['B1h'][i])}")
        else:
            L.append(f"  закрыть и в лонг: 4ч над зелёной {p_fmt(g)} и жёлтой {p_fmt(y)} и 3 закрытия 1ч над красной {p_fmt(r1)}")
    else:
        L.append("ПОЗИЦИЯ: нет")
        if st["await_blue"]:
            L.append(f"  после цели лонга ждём шорт от голубой: закрытие 4ч под {p_fmt(b)}")
        if fc < b:
            L.append(f"  лонг к голубой: 4ч над зелёной {p_fmt(g)} и жёлтой {p_fmt(y)} и 3 закрытия 1ч над красной {p_fmt(r1)} (сейчас {max(r_1, 0)} из 3), цель {p_fmt(b * .995)}")
            if st["covered"]:
                L.append(f"  снова шорт: возврат ближе 1% под зелёную {p_fmt(g)}, закрытия над ней не было")
            else:
                ok = w2.in_portrait(a, i, -1)
                L.append(f"  шорт под голубой: 4ч под зелёной, жёлтой и обеими голубыми ({p_fmt(min(g, y, b, b1))}); по описанию {'разрешён' if ok else 'сейчас не разрешён'}")
        else:
            L.append(f"  лонг снова над жёлтой: первое закрытие 4ч над {p_fmt(y)} при цене над обеими голубыми {p_fmt(max(b, b1))}")
            L.append(f"  лонг над голубыми: зелёная>жёлтая>красная и закрытие 4ч над зелёной {p_fmt(g)} и жёлтой {p_fmt(y)}")
            L.append(f"  шорт над голубыми: 2 закрытия 4ч под красной {p_fmt(r)}, сейчас {max(-rr, 0)} из 2; по описанию {'разрешён' if w2.in_portrait(a, i, -1) else 'сейчас не разрешён'}")
    return L


def phase_stats(coin, ph):
    p = pos.OUT / "state_eval_phases.csv"
    if not p.exists():
        return None
    d = pd.read_csv(p)
    d = d[(d["ряд"] == coin) & (d["фаза"] == ph)]
    return None if d.empty else d.iloc[0]


def phase_trades(ph):
    """Сделки варианта A с входом в этой фазе, 24 ряда: итог на сделку по периодам."""
    p = pos.OUT / "state_phase_trades.csv"
    if not p.exists():
        return []
    d = pd.read_csv(p)
    d = d[d["фаза"] == ph]
    out = []
    for s, nm in ((1, "лонг"), (-1, "шорт")):
        g = d[d["s"] == s]
        if g.empty:
            out.append(f"  {nm}: вариант A в этой фазе не открывает")
            continue
        o, n = g[g["период"] == "до 2025"], g[g["период"] == "2025–26"]
        plus = int((g.groupby("ряд")["r"].sum() > 0).sum())
        out.append(f"  {nm}: до 2025 {o['r'].mean():+.2f}% на сделку ({len(o)}), 2025–26 {n['r'].mean():+.2f}% ({len(n)}), в плюсе {plus} рядов из {g['ряд'].nunique()}")
    return out


def actions_near(t0):
    """Его действия вокруг момента: последнее до и ближайшие после, за неделю."""
    acts = sorted([(sm.T(ts), act, word) for ts, act, word in list(wd.MARKS) + list(w2.MARKS2)])
    before = [x for x in acts if t0 - 7 * 86400 <= x[0] <= t0][-1:]
    after = [x for x in acts if t0 < x[0] <= t0 + 7 * 86400][:2]
    return before, after


def analogs(a, i, k=3):
    t = a["t"]
    cand = np.where(np.any([(t >= sm.T(x)) & (t < sm.T(z)) for x, z, _ in sm.WINDOWS], axis=0) & (np.abs(t - t[i]) >= 30 * 86400) & (t <= t[-1] - 5 * 86400))[0]
    cand = cand[np.isfinite(a["st"][cand]).all(axis=1)]
    if not len(cand):
        return []
    idx, dist = sm.nearest(a["st"], cand, a["st"][i], k, 72, sm.scales(a, a["i0"] + 365 * 24 * 2))
    fw = sm.forward(a)
    out = []
    for j, d in zip(idx, dist):
        win = next(nm for x, z, nm in sm.WINDOWS if sm.T(x) <= t[j] < sm.T(z))
        out.append({"i": int(j), "d": float(d), "win": win, "ret": fw["ret"][j], "up": fw["up"][j], "dn": fw["dn"][j], "before": actions_near(t[j])[0], "after": actions_near(t[j])[1]})
    return out


ACT = {"L": "лонг", "S": "шорт", "xL": "закрыл лонг", "xS": "закрыл шорт"}


def fmt_act(x, t0):
    dh = (x[0] - t0) / 3600
    when = f"через {dh:.0f} ч" if dh > 0 else f"{-dh:.0f} ч назад"
    return f"{when}: {ACT[x[1]]}, «{x[2]}»"


def legs_with_state(a, i):
    st = {}
    legs = w2.run(a, **CFG, stop_at=i, out=st)
    return legs, st


def card(coin, a, fm, i):
    t, c, atr = a["t"], a["c"][i], a["atr4"][i]
    legs, st = legs_with_state(a, i)
    order = {1: "зелёная > жёлтая > красная (вверх)", -1: "зелёная < жёлтая < красная (вниз)", 0: "смешаны"}[int(a["order"][i])]
    ph = a["phase"][i]
    flat = {0: "сжатия нет", 2: "сжатие и локальный диапазон", 3: "сжатие, диапазона нет (переход)"}[int(a["flat"][i])]
    trend = "ТРЕНД ВВЕРХ" if ph == "рост" else ("ТРЕНД ВНИЗ" if ph == "падение" else ("ФЛЕТ" if a["flat"][i] == 2 else "тренда нет"))
    L = [f"{coin} {sm.utc(t[i])} UTC, закрытый час. Цена {p_fmt(c)}, ATR 4ч {p_fmt(atr)} ({atr / c * 100:.2f}%)", "", "ЛИНИИ: цена, расстояние, направление, закрепление"]
    L += lines_block(a, i)
    L += ["", f"ПОРЯДОК: {order}. Пересечений зелёной и жёлтой за 10 дней: {int(a['x_cross'][i])}"]
    L += cross_block(a, i)
    L += ["", f"ЧТО СЕЙЧАС: {trend}. Фаза «{ph}», {flat}."]
    s = phase_stats(coin, ph)
    if s is not None:
        L.append(f"  после такой фазы за 5 дней вверх в {s['вверх_%']:.0f}% (до 2022 {s['вверх_до 2022']:.0f}, 2022–24 {s['вверх_2022–24']:.0f}, 2025–26 {s['вверх_2025–26']:.0f}); 80% случаев: вниз не дальше {s['вниз_80']:.1f} ATR = {p_fmt(c - s['вниз_80'] * atr)}, вверх не дальше {s['вверх_80']:.1f} ATR = {p_fmt(c + s['вверх_80'] * atr)}")
    x01 = a["f_run_G"][i] <= -2 and a["run_R"][i] <= -3
    L.append(f"  твой выход X01 (4ч под зелёной и 1ч под красной): {'ДА, закрепились, лонг по твоему правилу закрыт' if x01 else 'нет'}; 4ч под зелёной {max(-int(a['f_run_G'][i]), 0)} из 2, 1ч под красной {max(-int(a['run_R'][i]), 0)} из 3")
    if x01 and a["f_close"][i] > a["f_B"][i] and a["c"][i] > a["B1h"][i]:
        L.append(f"  твой короткий шорт после роста: цель голубая 1ч {p_fmt(a['B1h'][i])}. Вариант A его не открывает: выход с таким шортом денег не добавил, BTC +224 против +218, ETH +252 против +281 (порог роста 3 ATR, words2_variants.csv)")
    L += ["", "ЧЕМ КОНЧАЛИСЬ ВХОДЫ В ЭТОЙ ФАЗЕ"] + phase_trades(ph)
    L += [""] + events(a, i, st)
    L += ["", "ПОХОЖИЕ МЕСТА В РАЗОБРАННЫХ УЧАСТКАХ (что делал ты; будущее они не предсказывают)"]
    an = analogs(a, i)
    for z in an:
        L.append(f"  {sm.utc(t[z['i']])}, {z['win']}, отличие {z['d']:.1f}, фаза «{a['phase'][z['i']]}»")
        for x in z["before"] + z["after"]:
            L.append(f"    {fmt_act(x, t[z['i']])}")
        if not z["before"] and not z["after"]:
            L.append("    твоих действий рядом не записано")
        if np.isfinite(z["ret"]):
            L.append(f"    потом за 5 дней: итог {z['ret']:+.1f} ATR, вверх {z['up']:.1f}, вниз {z['dn']:.1f}")
    return "\n".join(L), an, legs, st


def panel(ax, a, h4, legs, i_mark, x0, x1, title, levels=()):
    sc.style(ax)
    t = a["t"]
    A, Z = t[i_mark] - x0 * 86400, t[i_mark] + x1 * 86400
    s4 = h4[(h4.index >= A) & (h4.index < min(Z, t[-1]))]
    sc.candles(ax, s4, 14400)
    xx = sc.num(s4.index.to_numpy() + 7200)
    for col, clr, lw, ls in (("G", sc.C_G, 1.2, "-"), ("Y", sc.C_Y, 1.2, "-"), ("R", sc.C_R, 1.2, "-"), ("B", sc.C_B4, 2.0, "-"), ("B1", sc.C_B1, 1.0, (0, (4, 2)))):
        ax.plot(xx, s4[col], color=clr, lw=lw, ls=ls)
    for x in legs:
        t0, t1 = t[x[0]], t[x[1]]
        if t1 >= A and t0 < Z:
            ax.axvspan(sc.num(max(t0, A)), sc.num(min(t1, Z)), color=sc.TINT_L if x[4] == 1 else sc.TINT_S, alpha=0.28, lw=0, zorder=0)
    ax.axvline(sc.num(t[i_mark]), color="#f9fafb", lw=1.1, ls=(0, (2, 2)), zorder=4)
    lo, hi = s4["low"].min(), s4["high"].max()
    for ts, act, _ in list(wd.MARKS) + list(w2.MARKS2):
        tt = sm.T(ts)
        if A <= tt < Z:
            k = int(np.searchsorted(t, tt))
            ax.scatter(sc.num(tt), a["c"][k], s=75, marker="^" if act == "L" else ("v" if act == "S" else "x"), color="#f9fafb", lw=1.2, zorder=6)
    for val, nm, clr in levels:
        ax.axhline(val, color=clr, lw=0.9, ls=(0, (6, 3)), zorder=3)
        ax.text(sc.num(min(Z, t[-1])), val, f" {nm} {p_fmt(val)}", color=sc.INK, fontsize=8, va="center", ha="right", zorder=7, bbox=dict(fc=sc.SURFACE, ec="none", pad=0.8))
        lo, hi = min(lo, val), max(hi, val)
    ax.set_ylim(lo - (hi - lo) * .03, hi + (hi - lo) * .03)
    ax.set_xlim(sc.num(A), sc.num(Z))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))
    ax.set_title(title, color=sc.INK, fontsize=10.5, loc="left")


def levels_for(a, i, st):
    cur = st["cur"]
    b, g, r1 = a["f_B"][i], a["f_G"][i], a["R1"][i]
    if cur is None:
        return [(b, "голубая 4ч", sc.C_B4)]
    i0, p0, s, tag, _ = cur
    if s == 1:
        return [(p0, "вход", sc.INK)] + ([(b * .995, "цель", sc.C_B4)] if tag == "к голубой" else [])
    a0 = a["atr4"][i0]
    return [(p0, "вход", sc.INK), (p0 + S_STOP * a0, "стоп 2 ATR", sc.C_R), (p0 - S_TP * a0, "тейк 6 ATR", sc.C_G)]


def picture(coin, a, h4, i, an, legs, st, suffix=""):
    n = 1 + len(an)
    fig, axes = plt.subplots(n, 1, figsize=(13, 3.7 * n), dpi=110, gridspec_kw={"hspace": 0.3})
    axes = np.atleast_1d(axes)
    fig.patch.set_facecolor(sc.SURFACE)
    t = a["t"]
    all_legs = w2.run(a, **CFG)
    panel(axes[0], a, h4, legs, i, 45, 0.5, f"{coin} сейчас, {sm.utc(t[i])}: фаза «{a['phase'][i]}»", levels_for(a, i, st))
    for ax, z in zip(axes[1:], an):
        nxt = z["after"][0][2] if z["after"] else (z["before"][0][2] if z["before"] else "действий нет")
        panel(ax, a, h4, all_legs, z["i"], 30, 15, f"похоже: {sm.utc(t[z['i']])}, {z['win']}, отличие {z['d']:.1f} (меньше — ближе). Твоё действие рядом: {nxt}")
    fig.subplots_adjust(bottom=0.045)
    fig.text(0.125, 0.012, "Вертикаль — момент сравнения. Зелёная заливка — лонг автомата, красная — шорт. Белые значки — твои действия: ▲ лонг, ▼ шорт, × закрытие.", color=sc.MUTED, fontsize=9)
    p = pos.OUT / f"state_card_{coin}{suffix}.png"
    fig.savefig(p, bbox_inches="tight", facecolor=sc.SURFACE)
    plt.close(fig)
    return p


def main():
    args = sys.argv[1:]
    at = None
    if "--at" in args:
        k = args.index("--at")
        at = args[k + 1]
        args = args[:k] + args[k + 2:]
    coin = args[0] if args else "BTC"
    a, fm, h4 = load_coin(coin)
    i = len(a["t"]) - 1 if at is None else int(np.searchsorted(a["t"], sm.T(at)))
    text, an, legs, st = card(coin, a, fm, i)
    print(text, flush=True)
    suffix = "" if at is None else "_" + at[:10]
    (pos.OUT / f"state_card_{coin}{suffix}.txt").write_text(text + "\n", encoding="utf-8")
    print("картинка:", picture(coin, a, h4, i, an, legs, st, suffix), flush=True)


if __name__ == "__main__":
    main()
