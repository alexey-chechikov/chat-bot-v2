"""Оценка ТЗ 'Smart Signal Stop Manager' на НАШИХ данных против нашего валидированного EXIT-FAST.
6 типов сигнальных стопов автора (SuperTrend / ROC / MACD-hist / Volume-spike / Structure-break / Time)
прогоняю на frozen 2y BTC 4ч. Метрики (как в _break_forensics):
  - ЛОЖНЫЕ в чистом ренже (CALM): % баров, где стоп ложно закрыл бы прибыльный грид (цена death-by-cuts);
  - ЛИД на реальных сломах (BLEED): как рано стоп срабатывает (бар от старта окна) + сколько % дрейфа
    уже прошло на момент срабатывания (меньше = раньше = лучше).
Каждый стоп НАПРАВЛЕННЫЙ: срабатывает на движение ПРОТИВ уклона грида (up-окна=шорт-грид, down=лонг-грид).
Эталон = EXIT-FAST: (Donchian-пробой) И (ATR>1.4×) И (объём>1.8×). Строго каузально."""
from pathlib import Path
import numpy as np, pandas as pd
import sys
sys.path.insert(0, "tools")
from _elliott_lab import zigzag_confirmed

ROOT = Path(__file__).resolve().parents[1]
PX = ROOT / "backtests" / "frozen" / "BTCUSDT_1h_2y.csv"

BLEED = [
    ("SHORT bleed (+60% rally)", "2024-10-01", "2025-01-10", "up"),    # грид ШОРТ, враг = рост
    ("Q4 cliff DG",             "2025-11-05", "2025-12-25", "down"),   # грид ЛОНГ, враг = падение
    ("Killer crash 85k->60k",   "2025-12-28", "2026-03-01", "down"),
]
CALM = ("Range (grid friend)", "2026-02-05", "2026-05-05")

def load_4h():
    df = pd.read_csv(PX); df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return (df.set_index("ts").resample("4h").agg({"open": "first", "high": "max",
            "low": "min", "close": "last", "volume": "sum"}).dropna())

def atr(df, n=14):
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()

def supertrend(df, period=10, mult=3.0):
    hl2 = (df["high"] + df["low"]) / 2; a = atr(df, period)
    up = (hl2 + mult * a).to_numpy(); dn = (hl2 - mult * a).to_numpy(); c = df["close"].to_numpy()
    n = len(c); fub = up.copy(); flb = dn.copy(); d = np.ones(n)
    for i in range(1, n):
        fub[i] = up[i] if (up[i] < fub[i - 1] or c[i - 1] > fub[i - 1]) else fub[i - 1]
        flb[i] = dn[i] if (dn[i] > flb[i - 1] or c[i - 1] < flb[i - 1]) else flb[i - 1]
        d[i] = 1 if c[i] > fub[i - 1] else (-1 if c[i] < flb[i - 1] else d[i - 1])
    return d  # +1 бычий (BUY), -1 медвежий (SELL)

def triggers(df):
    """Возвращает dict имя->boolean Series 'стоп сработал на баре' (направленно против уклона)."""
    c = df["close"]; n = len(c)
    # уклон грида по окнам: эту инфу подставим снаружи; здесь считаем СЫРЫЕ направленные события
    st = supertrend(df)
    # MACD hist
    e12 = c.ewm(span=12, adjust=False).mean(); e26 = c.ewm(span=26, adjust=False).mean()
    macd = e12 - e26; sigl = macd.ewm(span=9, adjust=False).mean(); hist = (macd - sigl).to_numpy()
    # ROC 5 баров
    roc5 = (c / c.shift(5) - 1) * 100
    # объём-спайк
    volx = (df["volume"] / df["volume"].rolling(60).median()).to_numpy()
    ret1 = c.pct_change().to_numpy()
    # структура: каузальный zigzag, последний подтверждённый пивот хай/лоу
    piv = zigzag_confirmed(df["high"].to_numpy(), df["low"].to_numpy(), 0.04)
    last_hi = np.full(n, np.nan); last_lo = np.full(n, np.nan)
    hi = lo = np.nan
    pi = 0
    for i in range(n):
        while pi < len(piv) and piv[pi][0] <= i:
            if piv[pi][3] == +1: hi = piv[pi][2]
            else: lo = piv[pi][2]
            pi += 1
        last_hi[i] = hi; last_lo[i] = lo
    cl = c.to_numpy()
    # EXIT-FAST эталон (ненаправленный пробой; направленность учтём в окне)
    up20 = df["high"].rolling(20).max().shift(1); dn20 = df["low"].rolling(20).min().shift(1)
    brk_up = (c > up20).to_numpy(); brk_dn = (c < dn20).to_numpy()
    atr_exp = (atr(df) / atr(df).rolling(60).median()).to_numpy()
    return dict(st=st, hist=hist, roc5=roc5.to_numpy(), volx=volx, ret1=ret1,
                last_hi=last_hi, last_lo=last_lo, cl=cl,
                brk_up=brk_up, brk_dn=brk_dn, atr_exp=atr_exp)

def fire_series(T, adverse):
    """adverse: 'up' (грид шорт, враг=рост) или 'down' (грид лонг, враг=падение).
    Возвращает dict имя->np.bool массив срабатываний."""
    n = len(T["cl"]); up = adverse == "up"
    f = {}
    # 1 SuperTrend: флип в сторону врага
    f["SuperTrend"] = (T["st"] == (1 if up else -1))
    # 2 ROC>±2% против позиции
    f["ROC>2%"] = (T["roc5"] > 2) if up else (T["roc5"] < -2)
    # 3 MACD hist флип в сторону врага (сменил знак на враждебный)
    hist = T["hist"]; prev = np.r_[0, hist[:-1]]
    f["MACD-flip"] = ((hist > 0) & (prev <= 0)) if up else ((hist < 0) & (prev >= 0))
    # 4 Volume spike + бар против позиции
    advbar = (T["ret1"] > 0) if up else (T["ret1"] < 0)
    f["Vol-spike"] = (T["volx"] > 2.0) & advbar
    # 5 Structure break: пробой последнего пивота в сторону врага
    f["Struct-break"] = (T["cl"] > T["last_hi"]) if up else (T["cl"] < T["last_lo"])
    # эталон EXIT-FAST: направленный пробой И ATR>1.4 И объём>1.8
    brk = T["brk_up"] if up else T["brk_dn"]
    f["EXIT-FAST*"] = brk & (T["atr_exp"] > 1.4) & (T["volx"] > 1.8)
    return {k: np.nan_to_num(v).astype(bool) for k, v in f.items()}

def main():
    df = load_4h(); T = triggers(df)
    idx = df.index
    names = ["SuperTrend", "ROC>2%", "MACD-flip", "Vol-spike", "Struct-break", "EXIT-FAST*"]
    # CALM ложные срабатывания (грид в ренже симметричен — считаем оба направления, берём ИЛИ:
    # стоп закрыл бы, если сработал хоть в одну сторону — это и есть death-by-cuts риск)
    cmask = (idx >= pd.Timestamp(CALM[1], tz="UTC")) & (idx <= pd.Timestamp(CALM[2], tz="UTC"))
    fu = fire_series(T, "up"); fd = fire_series(T, "down")
    print(f"Данные: {idx[0]:%Y-%m-%d} → {idx[-1]:%Y-%m-%d}  ({len(df)} 4ч баров)")
    print(f"\n{'='*78}\nЛОЖНЫЕ в ЧИСТОМ РЕНЖЕ ({CALM[1]}→{CALM[2]}, {int(cmask.sum())} баров)")
    print("(% баров, где стоп ложно закрыл бы прибыльный грид — death-by-cuts)")
    print(f"{'стоп':14}{'ложных%':>9}{'срабат.шт':>11}")
    for nm in names:
        both = fu[nm] | fd[nm]
        pct = 100 * both[cmask].mean(); cnt = int(both[cmask].sum())
        print(f"{nm:14}{pct:>8.1f}%{cnt:>11}")
    # BLEED лид
    for name, a, b, adv in BLEED:
        wmask = (idx >= pd.Timestamp(a, tz="UTC")) & (idx <= pd.Timestamp(b, tz="UTC"))
        w = df.loc[wmask]; c0 = w["close"].iloc[0]
        # максимальный неблагоприятный ход в окне
        if adv == "up":
            maxadv = (w["high"].cummax() / c0 - 1) * 100
        else:
            maxadv = (1 - w["low"].cummin() / c0) * 100
        f = fire_series(T, adv)
        print(f"\n{'='*78}\n{name}  ({a}→{b}, враг={adv}, макс.ход {maxadv.iloc[-1]:.0f}%)")
        print(f"{'стоп':14}{'1й сигнал':>17}{'бар#':>6}{'% хода прошло':>15}")
        wi = np.flatnonzero(wmask)
        for nm in names:
            ff = f[nm][wmask]
            if ff.any():
                k = int(np.flatnonzero(ff)[0])
                elapsed = maxadv.iloc[k] / maxadv.iloc[-1] * 100 if maxadv.iloc[-1] > 0 else 0
                print(f"{nm:14}{w.index[k]:%Y-%m-%d %H:%M}{k:>6}{elapsed:>14.0f}%")
            else:
                print(f"{nm:14}{'НЕ сработал':>17}")

if __name__ == "__main__":
    main()
