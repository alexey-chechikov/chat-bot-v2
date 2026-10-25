"""Strategy 432 BTC (tuC7aGNI, «Donchian Breakout Continuation») — первый кандидат GPT 25.10 (+56% на 08.2024–10.2026,
26 сделок). Независимая проверка на 2017–2026, правила до прогона:
- правила автора: лонг, если close > максимума high прошлых 30 баров, ADX14 ≥ 22, close > EMA200, (close − тот максимум)
  ≥ 0.5×ATR14; выход: close < минимума low прошлых 30 баров или 20 баров в позиции; шортов нет. Исполнение — open
  следующего бара (у автора process_orders_on_close — по close сигнала), издержки 0.068%/сторона, фандинг;
- главное — 2017-11…2024-07 (GPT этот период не смотрел) и 2024-08…2026-10 отдельно (сверка с GPT по числу сделок и
  знаку), BTC и ETH, по годам;
- контроль по режиму: случайный вход по open после бара с close > EMA200, те же длительности, 2000 повторов;
- вердикт «есть эдж» — ранг ≤ 0.01 на 2017–2024 по BTC и плюс на ETH; иначе «нет» с цифрой."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import run as R  # noqa: E402
import strategies as S  # noqa: E402

GPT_FROM = pd.Timestamp("2024-08-01")


def s432(b):
    o, h, l, c = b
    hi30 = pd.Series(h).shift(1).rolling(30).max().to_numpy()
    lo30 = pd.Series(l).shift(1).rolling(30).min().to_numpy()
    a = S.atr(h, l, c, 14)
    e200 = S.ema(c, 200)
    _, _, adx = S.dmi(h, l, c, 14, 14)
    mag = np.where((c > hi30) & (a > 0), (c - hi30) / a, 0.0)
    ent = np.where((c > hi30) & (adx >= 22) & (c > e200) & (mag >= 0.5), 1, 0)
    ent[:300] = 0
    out, pos = [], None
    for i in range(len(c) - 1):
        if pos is not None:
            j, sig_i, px = pos
            if c[i] < lo30[i] or i - sig_i >= 20:
                out.append((j, i + 1, 1, px, o[i + 1], "сигнал"))
                pos = None
                continue                                    # вход того же бара после выхода — нет (как flat у автора)
        if pos is None and ent[i]:
            pos = (i + 1, i, o[i + 1])
    if pos is not None:
        out.append((pos[0], len(c) - 1, 1, pos[2], c[-1], "конец"))
    return out


def control(df, tr, fund, reps=2000, seed=11):
    o, c = df["open"].to_numpy(), df["close"].to_numpy()
    e200 = S.ema(c, 200)
    t = df.index.to_numpy()
    ft, cs = fund
    ok = np.flatnonzero(c > e200)
    ok = ok[(ok > 300) & (ok < len(o) - 25)]
    rng = np.random.default_rng(seed)
    durs = tr["bars"].to_numpy()
    res = np.empty(reps)
    for r in range(reps):
        tot = 0.0
        for d in durs:
            j = int(rng.choice(ok)) + 1
            k = min(j + d, len(o) - 1)
            f = cs[np.searchsorted(ft, t[k])] - cs[np.searchsorted(ft, t[j])]
            tot += o[k] / o[j] - 1 - 2 * S.COST - f
        res[r] = tot / len(durs)
    return res


def part(name, tr, df, fund, with_ctl=True):
    if tr.empty:
        return f"   {name}: сделок 0"
    m, lo, hi = R.ci(tr["net"].to_numpy())
    s = (f"   {name}: n {len(tr)}, win {100 * (tr['net'] > 0).mean():.0f}%, net {100 * m:+.3f}% [{100 * lo:+.3f}…"
         f"{100 * hi:+.3f}], сумма {100 * tr['net'].sum():+.0f}%, сложно ×{np.prod(1 + 0.95 * tr['net'].to_numpy()):.2f}")
    if with_ctl and len(tr) >= 10:
        ctl = control(df, tr, fund)
        s += f" | случайный выше EMA200: медиана {100 * np.median(ctl):+.3f}%, ранг {(1 + int((ctl >= m).sum())) / 2001:.4f}"
    return s


def main():
    for sym, path in (("BTCUSDT", sys.argv[1]), ("ETHUSDT", sys.argv[2])):
        df = R.bars(path)["4h"]
        fund = R.funding(sym)
        tr = R.evaluate(df, s432(tuple(df[k].to_numpy() for k in ("open", "high", "low", "close"))), fund)
        print(f"== {sym} 4h, Strategy 432 (параметры автора)", flush=True)
        print(part("весь 2017–2026", tr, df, fund), flush=True)
        print(part("2017–07.2024 (GPT не смотрел)", tr[tr["t"] < GPT_FROM], df, fund), flush=True)
        print(part("08.2024–10.2026 (окно GPT)", tr[tr["t"] >= GPT_FROM], df, fund), flush=True)
        yr = tr.groupby(pd.to_datetime(tr["t"]).dt.year)["net"].agg(["count", "sum"])
        print("   по годам: " + ", ".join(f"{y} {100 * s:+.0f}% (n {int(k)})" for y, (k, s) in yr.iterrows()), flush=True)
        c2 = tr["net"] - 2 * S.COST
        print(f"   издержки ×2: net {100 * c2.mean():+.3f}%/сделку", flush=True)


if __name__ == "__main__":
    main()
