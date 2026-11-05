"""D. Журнал хороших входов и выходов: зигзаг 4.5% на разобранных участках, зигзаг 5% на истории, замеры в точке и в момент распознавания,
пересечения зелёной: хорошие против плохих (хороший = +3 ATR раньше −1.5 ATR за 5 дней). Выход: JOURNAL.md, out/journal_points.csv, out/journal_auc.csv, out/journal.png."""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
import cw_data as cw  # noqa: E402
import pos  # noqa: E402
import segment1_chart as sc  # noqa: E402
import tp_blue as tb  # noqa: E402

pd.set_option("display.width", 240, "display.max_columns", 40, "display.max_rows", 200)
A, Z = cw.T("2025-02-15"), cw.T("2025-05-16")


def wilder(x, n):
    out = np.full(len(x), np.nan)
    acc = np.nan
    for i, v in enumerate(x):
        if i < n - 1:
            continue
        acc = np.nanmean(x[:n]) if i == n - 1 else (acc * (n - 1) + v) / n
        out[i] = acc
    return out


def add_extra(b, d1, fund):
    c, h, l = b["close"].to_numpy(), b["high"].to_numpy(), b["low"].to_numpy()
    dc = np.diff(c, prepend=c[0])
    up, dn = wilder(np.clip(dc, 0, None), 14), wilder(np.clip(-dc, 0, None), 14)
    b["rsi"] = 100 - 100 / (1 + up / np.where(dn == 0, np.nan, dn))
    um, dm = np.diff(h, prepend=h[0]), -np.diff(l, prepend=l[0])
    pdm = np.where((um > dm) & (um > 0), um, 0.0)
    mdm = np.where((dm > um) & (dm > 0), dm, 0.0)
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))
    atr = wilder(tr, 14)
    b["pdi"], b["mdi"] = 100 * wilder(pdm, 14) / atr, 100 * wilder(mdm, 14) / atr
    dx = 100 * np.abs(b["pdi"] - b["mdi"]) / (b["pdi"] + b["mdi"])
    b["adx"] = wilder(dx.fillna(0).to_numpy(), 14)
    b["adx_d3"] = b["adx"] - b["adx"].shift(3)
    w30 = 180
    b["from_hi30"] = (b["close"] / b["high"].rolling(w30).max() - 1) * 100
    b["from_lo30"] = (b["close"] / b["low"].rolling(w30).min() - 1) * 100
    # SMA100 для описания: неполные дни не выбрасываем (иначе после остановки биржи SMA устаревает на 100 дней)
    sm = d1["close"].rolling(100, min_periods=90).mean().to_numpy()
    j = np.searchsorted(d1["known"].to_numpy(), b["known"].to_numpy(), side="right") - 1
    sma = np.where(j >= 0, sm[np.clip(j, 0, None)], np.nan)
    b["d_sma100"] = (b["close"] / sma - 1) * 100
    ft, fr = fund.index.to_numpy(), fund.to_numpy()
    jf = np.searchsorted(ft, b["known"].to_numpy(), side="right") - 1
    b["fund"] = np.where(jf >= 0, fr[np.clip(jf, 0, None)] * 100, np.nan)
    cf = np.cumsum(fr)
    jf3 = np.searchsorted(ft, b["known"].to_numpy() - 3 * 86400, side="right") - 1
    b["fund3d"] = (cf[np.clip(jf, 0, None)] - cf[np.clip(jf3, 0, None)]) * 100
    b["body"] = (b["close"] - b["open"]) / (b["high"] - b["low"]).replace(0, np.nan)
    return b


def order_str(r):
    z = sorted([("G", r["G"]), ("Y", r["Y"]), ("R", r["R"])], key=lambda x: -x[1])
    return ">".join(n for n, _ in z)


def recog(b, p, kind):
    """Первое закрытие 4ч через зелёную после точки p (kind −1 минимум: вверх через зелёную; +1 максимум: вниз)."""
    c, g = b["close"].to_numpy(), b["G"].to_numpy()
    for i in range(p, min(p + 60, len(b))):
        if (kind == -1 and c[i] > g[i]) or (kind == 1 and c[i] < g[i]):
            return i
    return None


def journal_rows(b, piv):
    rows = []
    for q, (p, kind) in enumerate(piv):
        nxt = piv[q + 1][0] if q + 1 < len(piv) else None
        r = b.iloc[p]
        px = r["low"] if kind == -1 else r["high"]
        nx_px = None if nxt is None else (b["high"].iloc[nxt] if kind == -1 else b["low"].iloc[nxt])
        i = recog(b, p, kind)
        row = {"тип": "минимум" if kind == -1 else "максимум", "kind": kind, "i": p, "t": int(r["known"]), "цена": float(px), "закрытие": float(r["close"]),
               "порядок": order_str(r), "d_G": r["d_G"], "a_G": r["a_G"], "d_Y": r["d_Y"], "d_R": r["d_R"], "d_B4": r["d_B"], "a_B4": r["a_B"], "d_B1": r["d_Bo"], "ширина": r["width"], "ширина3": r["width3"], "ранг": r["width_rank"],
               "накл_G": r["slope_G"], "накл_Y": r["slope_Y"], "накл_R": r["slope_R"], "накл_B4": r["slope_B"], "закр_через_G": int(r["run_G"]), "объём30": r["vol_vs30"], "объём_сутки": r["vol_trend"], "ATR_%": r["atr_pct"], "RSI": r["rsi"], "ADX": r["adx"], "DI": r["pdi"] - r["mdi"],
               "до_SMA100": r["d_sma100"], "от_хая30д": r["from_hi30"], "от_лоу30д": r["from_lo30"], "фандинг": r["fund"], "фандинг3д": r["fund3d"], "ret24": r["ret24"], "ret72": r["ret72"]}
        row["ход_дальше_%"] = None if nx_px is None else (nx_px / px - 1) * 100
        row["часов_до_след"] = None if nxt is None else (nxt - p) * 4
        row["гэп_до_B4_%"] = (r["B"] / px - 1) * 100
        if i is not None and nx_px is not None and i < nxt:
            ri = b.iloc[i]
            row["распозн_t"] = int(ri["known"])
            row["распозн_цена"] = float(ri["close"])
            row["осталось_%"] = (nx_px / ri["close"] - 1) * 100
            seg = b.iloc[i + 1:nxt + 1]
            row["против_после_распозн_%"] = ((seg["low"].min() / ri["close"] - 1) * 100) if kind == -1 else ((seg["high"].max() / ri["close"] - 1) * 100)
            row["доля_хода_осталась"] = row["осталось_%"] / row["ход_дальше_%"] if row["ход_дальше_%"] else None
        rows.append(row)
    return pd.DataFrame(rows)


def auc(x, y):
    ok = np.isfinite(x)
    x, y = x[ok], y[ok]
    if y.sum() < 10 or (~y).sum() < 10:
        return np.nan
    r = pd.Series(x).rank().to_numpy()
    return (r[y].sum() - y.sum() * (y.sum() + 1) / 2) / (y.sum() * (~y).sum())


def cross_events(b, side):
    """Первое закрытие через зелёную после минимум 3 закрытий с другой стороны. Хороший: 3 ATR по ходу раньше 1.5 ATR против за 30 свечей."""
    run = b["run_G"].to_numpy()
    c, h, l, atr = b["close"].to_numpy(), b["high"].to_numpy(), b["low"].to_numpy(), b["atr"].to_numpy()
    idx = [i for i in range(1, len(b)) if (side == 1 and run[i] == 1 and run[i - 1] <= -3) or (side == -1 and run[i] == -1 and run[i - 1] >= 3)]
    good = []
    for i in idx:
        up, dn = (c[i] + side * 3 * atr[i]), (c[i] - side * 1.5 * atr[i])
        res = False
        for k in range(i + 1, min(i + 31, len(b))):
            if (side == 1 and l[k] <= dn) or (side == -1 and h[k] >= dn):
                break
            if (side == 1 and h[k] >= up) or (side == -1 and l[k] <= up):
                res = True
                break
        good.append(res)
    return np.array(idx), np.array(good)


FEATS = ["d_Y", "d_R", "d_B", "d_Bo", "a_Y", "a_R", "a_B", "width", "width3", "width_rank", "slope_G", "slope_Y", "slope_R", "slope_B", "vol_vs30", "vol_trend", "atr_pct", "ret24", "ret72", "rsi", "adx", "adx_d3", "di", "from_hi30", "from_lo30", "d_sma100", "fund", "fund3d", "body", "prev_run", "prev_far"]


def auc_table(b):
    rows = []
    t = b.index.to_numpy()
    b = b.copy()
    b["di"] = b["pdi"] - b["mdi"]
    b["prev_run"] = np.abs(b["run_G"].shift(1))
    dg = b["d_G"].to_numpy()
    for side, nm in ((1, "лонг, вверх через зелёную"), (-1, "шорт, вниз через зелёную")):
        idx, good = cross_events(b, side)
        idx_ok = idx >= int(np.searchsorted(t, cw.T("2018-01-01")))
        idx, good = idx[idx_ok], good[idx_ok]
        far = np.array([np.abs(dg[max(i - 30, 0):i]).max() for i in idx])
        per = pos.period_of(t[idx])
        print(nm, "событий", len(idx), "хороших", int(good.sum()), round(float(good.mean() * 100), 1), "%", {p: round(float(good[per == p].mean() * 100), 1) for p in pos.PER})
        for f in FEATS:
            x = far if f == "prev_far" else b[f].to_numpy()[idx]
            row = {"сторона": nm, "показатель": f, "всё": round(float(auc(x, good)), 3)}
            for p in pos.PER:
                row[p] = round(float(auc(x[per == p], good[per == p])), 3)
            rows.append(row)
    d = pd.DataFrame(rows)
    d["держится"] = ((d[["A", "B", "C"]] >= 0.55).all(axis=1)) | ((d[["A", "B", "C"]] <= 0.45).all(axis=1))
    return d


def history_summary(b):
    piv = tb.zigzag(b["high"].to_numpy(), b["low"].to_numpy(), 0.05)
    piv = [(i, k) for i, k in piv if b.index[i] >= cw.T("2018-01-01")]
    j = journal_rows(b, piv)
    j.to_csv(pos.OUT / "journal_history.csv", index=False)
    base = b[b.index >= cw.T("2018-01-01")]
    cols = {"d_G": "d_G", "a_G": "a_G", "d_R": "d_R", "d_B4": "d_B", "d_B1": "d_Bo", "ширина": "width", "ранг": "width_rank", "объём30": "vol_vs30", "RSI": "rsi", "ADX": "adx", "ATR_%": "atr_pct", "до_SMA100": "d_sma100", "фандинг3д": "fund3d"}
    rows = []
    for nm, col in cols.items():
        lows, highs = j.loc[j["kind"] == -1, nm], j.loc[j["kind"] == 1, nm]
        rows.append({"показатель": nm, "минимумы_медиана": round(float(lows.median()), 2), "минимумы_q25–q75": f"{lows.quantile(.25):.2f}…{lows.quantile(.75):.2f}", "максимумы_медиана": round(float(highs.median()), 2),
                     "максимумы_q25–q75": f"{highs.quantile(.25):.2f}…{highs.quantile(.75):.2f}", "все_свечи_медиана": round(float(base[col].median()), 2)})
    s = pd.DataFrame(rows)
    s.to_csv(pos.OUT / "journal_history_summary.csv", index=False)
    print(s.to_string(index=False))
    for k, nm in ((-1, "минимумы"), (1, "максимумы")):
        g = j[j["kind"] == k]
        print(nm, "n", len(g), "ход дальше медиана", round(float(g["ход_дальше_%"].median()), 2), "распознано через", round(float(((g["распозн_t"] - g["t"]) / 3600).median()), 0), "ч; доля хода осталась медиана", round(float(g["доля_хода_осталась"].median()), 2),
              "хода не осталось", round(float((g["осталось_%"].fillna(0) * (-k) <= 0).mean() * 100), 1), "%; против после распознавания медиана", round(float(g["против_после_распозн_%"].median()), 2))
    return j


def write_md2(j, summary_txt):
    def f(x, nd=1):
        return "—" if x is None or not np.isfinite(float(x)) else f"{float(x):+.{nd}f}"

    def ts(x):
        return pd.Timestamp(int(x), unit="s").strftime("%d.%m %H:%M")

    lines = ["# Журнал хороших входов и выходов", "", "Дополняется с каждым участком. Точка — разворот зигзага 4.5% по максимумам и минимумам 4ч: минимум — хороший вход в лонг и выход из шорта, максимум — наоборот.",
             "Замеры — на закрытии свечи разворота. Точка выбрана задним числом; столбец «Распознать» — то, что было видно в тот момент: первое закрытие 4ч через зелёную.", "",
             "Сокращения: G зелёная, Y жёлтая, R красная, Г4 голубая 4ч, Г1 голубая 1ч. Расстояния в %, минус — цена ниже линии. Время — закрытие свечи, UTC. Ширина — все 4 линии, рядом место среди самых узких за 180 дней.", "",
             "## Участки 1–3: 15.02–15.05.2025", "",
             "| № | Что | Закрытие | Цена | Дальше | Порядок; до G / Y / R / Г4 / Г1 | Ширина, место | Объём к 30д | RSI, ADX, DI | ATR | До SMA100; от хая, лоу 30д | Фандинг 3д | Распознать: закрытие, цена, осталось, против |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for n, r in enumerate(j.to_dict("records"), 1):
        rec = "не успели"
        if np.isfinite(float(r.get("распозн_t", np.nan))):
            rec = f"{ts(r['распозн_t'])}, {int(round(r['распозн_цена']))}, {f(r['осталось_%'])}%, {f(r['против_после_распозн_%'])}%"
        lines.append(f"| {n} | {r['тип']} | {ts(r['t'])} | {int(round(r['цена']))} | {f(r['ход_дальше_%'])}% за {f(r['часов_до_след'], 0).replace('+', '')} ч | {r['порядок']}; {f(r['d_G'])} / {f(r['d_Y'])} / {f(r['d_R'])} / {f(r['d_B4'])} / {f(r['d_B1'])} | "
                     f"{r['ширина']:.1f}%, {r['ранг'] * 100:.0f} | {r['объём30']:.1f} | {r['RSI']:.0f}, {r['ADX']:.0f}, {r['DI']:+.0f} | {r['ATR_%']:.1f} | {f(r['до_SMA100'])}; {f(r['от_хая30д'])}, {f(r['от_лоу30д'])} | {f(r['фандинг3д'], 3)} | {rec} |")
    lines += ["", summary_txt, ""]
    (cw.HERE / "JOURNAL.md").write_text("\n".join(lines))


def extras(jh, h4, s):
    """Текст сводки: что общего у разворотов и что отличает хорошие пересечения зелёной. Терти считаются по всей истории, это описание."""
    lows, highs = jh[jh["kind"] == -1], jh[jh["kind"] == 1]
    out = ["## Что общего, история 2018–2026 (зигзаг 5%)", "",
           f"Минимумов {len(lows)}, максимумов {len(highs)}. Ход после минимума: медиана {lows['ход_дальше_%'].median():+.1f}%, после максимума {highs['ход_дальше_%'].median():+.1f}%.", "",
           f"- До зелёной на минимуме: медиана {lows['d_G'].median():+.1f}%, половина между {lows['d_G'].quantile(.25):+.1f} и {lows['d_G'].quantile(.75):+.1f}. Ниже −5% только {float((lows['d_G'] <= -5).mean() * 100):.0f}% минимумов, ниже −3% — {float((lows['d_G'] <= -3).mean() * 100):.0f}%.",
           f"- RSI на минимуме {lows['RSI'].median():.0f}, на максимуме {highs['RSI'].median():.0f}, все свечи {50.65:.0f}. Объём к 30 дням: минимум ×{lows['объём30'].median():.1f}, максимум ×{highs['объём30'].median():.1f}, все свечи ×1.1.",
           f"- Распознавание по закрытию 4ч через зелёную: минимум через {float(((lows['распозн_t'] - lows['t']) / 3600).median()):.0f} ч, осталось {lows['осталось_%'].median():+.1f}% (доля хода {lows['доля_хода_осталась'].median():.2f}), против после этого {lows['против_после_распозн_%'].median():+.1f}%.",
           f"- Максимум через {float(((highs['распозн_t'] - highs['t']) / 3600).median()):.0f} ч, осталось {highs['осталось_%'].median():+.1f}% (доля хода {highs['доля_хода_осталась'].median():.2f}), против после этого {highs['против_после_распозн_%'].median():+.1f}%.", ""]
    b = h4.copy()
    b["di"] = b["pdi"] - b["mdi"]
    dg = b["d_G"].to_numpy()
    t = b.index.to_numpy()
    out += ["## Хорошие пересечения зелёной против плохих", "", "Событие — первое закрытие 4ч через зелёную после минимум 3 закрытий с другой стороны. Хорошее — 3 ATR по ходу раньше 1.5 ATR против за 5 дней.", ""]
    for side, nm in ((1, "вверх"), (-1, "вниз")):
        idx, good = cross_events(b, side)
        ok = idx >= int(np.searchsorted(t, cw.T("2018-01-01")))
        idx, good = idx[ok], good[ok]
        per = pos.period_of(t[idx])
        far = np.array([np.abs(dg[max(i - 30, 0):i]).max() for i in idx])
        out.append(f"{nm.capitalize()}: {len(idx)} событий, хороших {good.mean() * 100:.0f}% (A {good[per == 'A'].mean() * 100:.0f}, B {good[per == 'B'].mean() * 100:.0f}, C {good[per == 'C'].mean() * 100:.0f}). Случайная точка при таких целях даёт около 33%.")
        for f_, lab in (("adx", "ADX"), ("atr_pct", "ATR%"), ("prev_far", "сколько цена уходила от зелёной перед пересечением, %")):
            x = far if f_ == "prev_far" else b[f_].to_numpy()[idx]
            q1, q2 = np.nanquantile(x, [1 / 3, 2 / 3])
            lo, mid, hi = x <= q1, (x > q1) & (x <= q2), x > q2
            cells = []
            for p in pos.PER:
                m = per == p
                cells.append(f"{p} {good[m & lo].mean() * 100:.0f}/{good[m & hi].mean() * 100:.0f}")
            out.append(f"- {lab}: нижняя треть (до {q1:.1f}) {good[lo].mean() * 100:.0f}%, средняя {good[mid].mean() * 100:.0f}%, верхняя (от {q2:.1f}) {good[hi].mean() * 100:.0f}%. По периодам низ/верх: {', '.join(cells)}.")
        out.append("")
    hold = s[s["держится"]]
    out.append("Показатели, у которых AUC по одну сторону от 0.55/0.45 во всех трёх периодах: " + ("; ".join(f"{r['сторона'].split(',')[0]}, {r['показатель']} ({r['A']}/{r['B']}/{r['C']})" for r in hold.to_dict("records")) if len(hold) else "нет") + f". Проверено {s['показатель'].nunique()} показателей на сторону.")
    return "\n".join(out)


def picture(b, j):
    s = b[(b.index >= A) & (b.index < Z)]
    fig, ax = plt.subplots(1, 1, figsize=(17, 7.5), dpi=112)
    fig.patch.set_facecolor(sc.SURFACE)
    sc.style(ax)
    sc.candles(ax, s, 14400)
    x = sc.num(s.index.to_numpy() + 7200)
    ax.plot(x, s["G"], color=sc.C_G, lw=1.4, label="зелёная TEMA50")
    ax.plot(x, s["Y"], color=sc.C_Y, lw=1.4, label="жёлтая TEMA100")
    ax.plot(x, s["R"], color=sc.C_R, lw=1.4, label="красная TEMA200")
    ax.plot(x, s["B"], color=sc.C_B4, lw=2.2, label="голубая 4ч")
    ax.plot(x, s["B1"], color=sc.C_B1, lw=1.2, ls=(0, (4, 2)), label="голубая 1ч")
    for n, r in enumerate(j.itertuples(), 1):
        xx = sc.num(int(r.t) - 7200)
        yy = r.цена * (0.982 if r.kind == -1 else 1.018)
        ax.annotate(str(n), (xx, yy), color="#111827", fontsize=9, fontweight="bold", ha="center", va="center", zorder=7, bbox=dict(boxstyle="circle,pad=0.25", fc="#f9fafb", ec="#f9fafb"))
    ax.set_ylim(71000, 109000)
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=4))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))
    ax.set_xlim(sc.num(A), sc.num(Z) + 0.1)
    ax.legend(loc="lower right", ncol=5, frameon=False, labelcolor=sc.INK, fontsize=9.5)
    fig.suptitle("Журнал: развороты BTC 4ч, 15.02–15.05.2025 (зигзаг 4.5%). Номера — как в JOURNAL.md", color=sc.INK, fontsize=13.5, fontweight="bold", x=0.012, ha="left", y=0.975)
    fig.subplots_adjust(left=0.012, right=0.955, top=0.93, bottom=0.06)
    fig.savefig(pos.OUT / "journal.png", facecolor=sc.SURFACE)


def main():
    m, h1, h4, d1, fund = cw.load()
    del m
    h4 = add_extra(h4.copy(), d1, fund)
    lines = h4[["G", "Y", "R"]]
    h4["width3"] = (lines.max(axis=1) - lines.min(axis=1)) / h4["close"] * 100
    w = h4[(h4.index >= cw.T("2025-01-20")) & (h4.index < cw.T("2025-06-05"))]
    piv_all = tb.zigzag(w["high"].to_numpy(), w["low"].to_numpy(), 0.045)
    piv = [(int(np.searchsorted(h4.index.to_numpy(), w.index[i])), k) for i, k in piv_all]
    piv = [(i, k) for i, k in piv if A <= h4.index[i] < Z]
    j = journal_rows(h4, piv)
    j.to_csv(pos.OUT / "journal_points.csv", index=False)
    print(j[["тип", "цена", "порядок", "d_G", "d_R", "d_B4", "d_B1", "ширина", "объём30", "RSI", "ход_дальше_%", "осталось_%", "против_после_распозн_%"]].assign(t=[cw.utc(int(x)) for x in j["t"]]).round(1).to_string(index=False))
    jh = history_summary(h4)
    s = auc_table(h4)
    s.to_csv(pos.OUT / "journal_auc.csv", index=False)
    print(s[s["держится"]].to_string(index=False))
    txt = extras(jh, h4, s)
    print(txt)
    write_md2(j, txt)
    picture(h4, j)


if __name__ == "__main__":
    main()
