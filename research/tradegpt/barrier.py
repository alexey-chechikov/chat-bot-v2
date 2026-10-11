"""Правило оператора 11.10: входить по сигналам в духе TradeGPT, тейк 1%, стоп 3% или 5% (вопрос «на $200»).

Сигналы — research/tradegpt/backtest.signals (MACD(12,26,9) сменил знак + объём 6ч вырос + 12ч шли в обратную
сторону), 1ч свечи Binance spot, 2 года. Вход по открытию следующего бара; дальше по барам: если в баре задеты и
тейк, и стоп — считаем стоп (осторожно); не закрылась за 72 ч — закрытие по цене. Комиссия 0.1% за круг.
Безубыточная доля тейков = (стоп + комиссия) / (тейк + стоп): 1/3 → 77.5%, 1/5 → 85%.
Контроли: те же моменты со случайным направлением; сигналы, сдвинутые по кругу (20 сдвигов).
Разрез по времени: старая / свежая половина. Монеты: 8 прежних + альты из живых сигналов (STX, ARPA, STRK)."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import backtest as bt  # noqa: E402

COINS = bt.COINS + ["STXUSDT", "ARPAUSDT", "STRKUSDT"]
FEE = 0.1
MAX_H = 72


def trades(d, sig, tp, sl):
    o, h, l, c = (d[k].to_numpy() for k in ("open", "high", "low", "close"))
    out = []
    n = len(d)
    for i in np.where(sig != 0)[0]:
        if i + 1 >= n:
            continue
        s, e = sig[i], o[i + 1]
        res = None
        for j in range(i + 1, min(n, i + 1 + MAX_H)):
            bad = s * ((l[j] if s > 0 else h[j]) / e - 1) * 100
            good = s * ((h[j] if s > 0 else l[j]) / e - 1) * 100
            if bad <= -sl:
                res = -sl
                break
            if good >= tp:
                res = tp
                break
        if res is None:
            j = min(n - 1, i + MAX_H)
            res = s * (c[j] / e - 1) * 100
        out.append((i, res - FEE))
    return out


def main():
    rng = np.random.default_rng(11)
    data = {}
    for sym in COINS:
        try:
            data[sym] = bt.load(sym)
        except Exception as exc:                                  # noqa: BLE001
            print(sym, "нет данных:", str(exc)[:60])
    for tp, sl in ((1.0, 3.0), (1.0, 5.0), (2.0, 5.0)):
        be = (sl + FEE) / (tp + sl)
        real, rnd, old, new, per = [], [], [], [], []
        for sym, d in data.items():
            sig = bt.signals(d).to_numpy()
            t = trades(d, sig, tp, sl)
            r = np.array([x for _, x in t])
            real.append(r)
            cut = len(d) // 2
            old += [x for i, x in t if i < cut]
            new += [x for i, x in t if i >= cut]
            rs = sig.copy()
            nz = rs != 0
            rs[nz] = rng.choice([-1, 1], nz.sum())
            rnd.append(np.array([x for _, x in trades(d, rs, tp, sl)]))
            per.append(f"{sym[:-4]} {r.mean():+.2f}")
        r, q = np.concatenate(real), np.concatenate(rnd)
        se = r.std(ddof=1) / np.sqrt(len(r))
        win = (r > 0).mean()
        print(f"\nТЕЙК {tp}% / СТОП {sl}% — безубыток при {be:.1%} тейков")
        print(f"  сигналы: N {len(r)}, тейков {win:.1%}, на сделку {r.mean():+.3f}% ± {1.96 * se:.3f} (95%)")
        print(f"  случайное направление: на сделку {q.mean():+.3f}%, тейков {(q > 0).mean():.1%}")
        print(f"  старая половина {np.mean(old):+.3f}% (N {len(old)}), свежая {np.mean(new):+.3f}% (N {len(new)})")
        print("  по монетам: " + ", ".join(per))
        sh = []
        for k in rng.integers(200, 5000, 20):
            acc = []
            for sym, d in data.items():
                s = np.roll(bt.signals(d).to_numpy(), int(k))
                acc += [x for _, x in trades(d, s, tp, sl)]
            sh.append(np.mean(acc))
        print(f"  сдвиги по кругу: {min(sh):+.3f}…{max(sh):+.3f}%, не хуже настоящего {sum(x >= r.mean() for x in sh)}/20")
        print(f"  на $200 позиции (без плеча): {r.mean() * 2:+.2f}$ за сделку, {len(r) / 730 * 365:.0f} сделок в год "
              f"→ {r.mean() * 2 * len(r) / 2:+.0f}$/год")


if __name__ == "__main__":
    main()
