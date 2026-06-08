"""volume-RSI (@wozdux RSIVol_2graf) — есть ли реальный сигнал для грид-фильтра?
Реализация точь-в-точь: vwp=ema(close*vol,24)/ema(vol,24); rsi11=rsi(vwp,24);
wt22=ema(rsi11,5) аква; emarr=ema(rsi11,12) синяя; канал ma±1.6185·stdev(wt22,24).
Тестим 3 сигнала на forward-return разделение (edge = fwd(бычий) − fwd(медвежий), %, h=3 бара):
  level    : перепрод(wt<=30) vs перекуп(>=70)         [фейд/реверсия]
  crossover: аква>синяя vs аква<синяя                  [моментум]
  channel  : ниже канала vs выше канала                [реверсия]
>0 и робастно по якорям = сигнал; ≈0 = шум (как RSI-див AUC 0.5). Offset 0/1/2/3ч.
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path("/Users/alexeychechikov/code/bot7")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from _followthrough_exit_test import load_off


def rma(x, n):
    return pd.Series(x).ewm(alpha=1.0 / n, adjust=False).mean().to_numpy()


def rsi(x, n):
    x = np.asarray(x, float)
    d = np.diff(x, prepend=x[0])
    up = np.where(d > 0, d, 0.0)
    dn = np.where(d < 0, -d, 0.0)
    ru, rd = rma(up, n), rma(dn, n)
    rs = np.divide(ru, rd, out=np.full_like(ru, np.inf), where=rd != 0)
    return 100.0 - 100.0 / (1.0 + rs)


def ema(x, span):
    return pd.Series(x).ewm(span=span, adjust=False).mean().to_numpy()


def fwd_edge(c, bull_mask, bear_mask, h):
    fwd = np.full(len(c), np.nan)
    fwd[:-h] = (c[h:] / c[:-h] - 1.0) * 100.0
    return np.nanmean(fwd[bull_mask]) - np.nanmean(fwd[bear_mask])


def main():
    pair = sys.argv[1] if len(sys.argv) > 1 else "BTCUSDT"
    H = 3
    print(f"=== {pair} 4h  volume-RSI 3 сигнала — fwd-edge %% (h={H}), >0+робастно=сигнал ===")
    print(f"{'signal':10s} | off0    off1    off2    off3")
    rows = {"level": [], "crossover": [], "channel": []}
    for off in (0, 1, 2, 3):
        o = load_off(pair, off)
        c = o["close"].to_numpy(float)
        v = o["volume"].to_numpy(float)
        vwp = ema(c * v, 24) / ema(v, 24)
        r11 = rsi(vwp, 24)
        wt = ema(r11, 5)
        bl = ema(r11, 12)
        ma = pd.Series(wt).rolling(24).mean().to_numpy()
        sd = pd.Series(wt).rolling(24).std().to_numpy()
        up = ma + 1.6185 * sd
        dn = ma - 1.6185 * sd
        rows["level"].append(fwd_edge(c, wt <= 30, wt >= 70, H))
        rows["crossover"].append(fwd_edge(c, wt > bl, wt < bl, H))
        rows["channel"].append(fwd_edge(c, wt < dn, wt > up, H))
    for k, vals in rows.items():
        print(f"{k:10s} | " + "  ".join(f"{x:+.2f}" for x in vals))


if __name__ == "__main__":
    main()
