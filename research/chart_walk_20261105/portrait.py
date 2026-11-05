"""Портрет прибыльного входа в словах оператора и прогон автомата под него. Описание смотрит только на закрытые бары в момент входа.
Лонг: цена над обеими голубыми и голубая 4ч растёт за 5 дней.
Шорт: цветные смешаны (ни G>Y>R, ни G<Y<R), либо отскок внутри падения: цена под обеими голубыми, голубая 4ч падает, G>Y>R.
Сделки вне портрета не исчезают: считаются отдельно, полным объёмом, половиной и нулём."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import entry_common as ec  # noqa: E402
import ledger as lg  # noqa: E402
import pos  # noqa: E402
import words as wd  # noqa: E402
import words2 as w2  # noqa: E402

pd.set_option("display.width", 260, "display.max_columns", 40, "display.max_rows", 300)
DAY = 24
in_portrait = w2.in_portrait


def split(a, legs):
    return [x for x in legs if in_portrait(a, x[0], x[4])], [x for x in legs if not in_portrait(a, x[0], x[4])]


def eq_of(a, fm, legs, w=1.0):
    if not legs:
        return np.zeros(len(a["c"])), np.zeros(len(a["c"]))
    eq, worst, _, _ = lg.equity(a, fm, [x[:5] for x in legs])
    return eq * w, worst * w


def book(a, fm, inn, out, w_out, per):
    """Сводка книги: сделки портрета полным объёмом, вне портрета с весом w_out."""
    e1, w1 = eq_of(a, fm, inn)
    e2, w2_ = eq_of(a, fm, out, w_out)
    eq, worst = e1 + e2, w1 + w2_
    b = a["i0"]
    dd = lg.drawdown(eq[b:], worst[b:], a["t"][b:])
    lo, hi, pneg = lg.block_ci(eq, b)
    t = a["t"]
    total = eq[-1] / lg.NOTIONAL * 100
    r = {}
    for k, (x, z) in per.items():
        i0, i1 = int(np.searchsorted(t, x)), min(int(np.searchsorted(t, z)), len(t) - 1)
        if i1 > i0:
            r[k] = round((eq[i1] - eq[max(i0, b)]) / lg.NOTIONAL * 100)
    return {"итог": round(total), "просадка": round(dd[0] / lg.NOTIONAL * 100), "итог/просадка": round(total / max(abs(dd[0] / lg.NOTIONAL * 100), 1), 2), "под_водой_дн": dd[3], "блок_низ": lo, "блок_верх": hi, **r}


def main():
    series = ec.load_all()
    pers = {"BTC": pos.PER, "ETH": pos.PER, "Bitstamp": wd.PER_BS, "XRP": wd.PER_X}
    rows = []
    for coin, a, fm in series:
        legs = wd.run(a)
        inn, out = split(a, legs)
        yrs = (a["t"][-1] - a["t"][a["i0"]]) / (365.25 * 86400)
        for lab, w in (("все полным объёмом", 1.0), ("вне портрета половиной", 0.5), ("только портрет", 0.0)):
            n = len(inn) + (len(out) if w else 0)
            rows.append({"ряд": coin, "вариант": lab, "сделок": n, "в_год": round(n / yrs), "в_портрете": len(inn), **book(a, fm, inn, out, w, pers[coin])})
        print(coin, "портрет лонг", round(sum(w2.net(fm, x) for x in inn if x[4] == 1)), "шорт", round(sum(w2.net(fm, x) for x in inn if x[4] == -1)), "| вне лонг", round(sum(w2.net(fm, x) for x in out if x[4] == 1)), "шорт", round(sum(w2.net(fm, x) for x in out if x[4] == -1)), flush=True)
    t = pd.DataFrame(rows)
    t.to_csv(pos.OUT / "portrait_books.csv", index=False)
    print(t.to_string(index=False), flush=True)
    a = series[0][1]
    fm = series[0][2]
    legs = wd.run(a)
    rows = []
    for ts, act, word in wd.MARKS + w2.MARKS2:
        if act.startswith("x"):
            continue
        i = int(np.searchsorted(a["t"], wd.cw.T(ts)))
        s = 1 if act == "L" else -1
        rows.append({"время": ts, "действие": act, "слова": word, "в_портрете": bool(in_portrait(a, i, s)), "цветные": "вверх" if a["f_G"][i] > a["f_Y"][i] > a["f_R"][i] else ("вниз" if a["f_G"][i] < a["f_Y"][i] < a["f_R"][i] else "смешаны"), "над_голубыми": bool(a["f_close"][i] > a["f_B"][i] and a["f_close"][i] > a["f_B1"][i]), "под_голубыми": bool(a["f_close"][i] < a["f_B"][i] and a["f_close"][i] < a["f_B1"][i]), "голубая_растёт": bool(a["f_B"][i] > a["f_B"][max(i - 5 * DAY, 0)])})
    m = pd.DataFrame(rows)
    m.to_csv(pos.OUT / "portrait_his_marks.csv", index=False)
    print(m.to_string(index=False), flush=True)
    print("его входов в портрете:", int(m["в_портрете"].sum()), "из", len(m), flush=True)
    rows = []
    for coin, a, fm in series:
        inn, out = split(a, wd.run(a))
        rows.append({"ряд": coin, "портрет": lg.shift_rank(a, fm, [x[:5] for x in inn]), "вне": lg.shift_rank(a, fm, [x[:5] for x in out])})
        print(coin, "сдвиги портрет:", rows[-1]["портрет"], flush=True)
        print(coin, "сдвиги вне:", rows[-1]["вне"], flush=True)


if __name__ == "__main__":
    main()
