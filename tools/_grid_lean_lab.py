"""H5 как ПЕРЕКЛЮЧАТЕЛЬ УКЛОНА грид-книги vs текущий грубый MA100-свитч (2026-06-13).
Ради чего всё затевалось. Полного GinArea-сима тут нет (он у Мака) — но переключатель уклона
ЭТО направленная компонента книги: range-харвест (доход с пилы) от уклона почти не зависит, а
дрейф-блид на «неправильной» ноге = направленный PnL уклона. Его и меряю.

Книга (из project_dynamic_grid_solution): short-нога доит вниз/боковик и блидит на ралли; long-нога
наоборот. Уклон решает, какую ногу давить/капить. Экспозиция уклона e∈[-1..+1]:
  symmetric e=0      — всегда симметрично (нет ставки на сторону, эталон 0)
  MA100     e=±1     — текущий свитч: знак (close − SMA100 4ч), с холдом против whipsaw
  H5        e=+1/-1/0 — наш сигнал: лонг-уклон / шорт-уклон / НЕЙТРАЛ (H5 во флэте = симметрично)
  H5_cap    e=±0.5/0 — мягкий: не флип ноги, а кап (грид не разворачивается, лишь режет неправую ногу)
  hold      e=+1     — buy&hold (всегда лонг-уклон)
Directional PnL = Σ e_prev · лог-доход_бара. Меряю net, DD, % времени на правой стороне, флипы/мес.
Учёт без комиссий (уклон = редкое переключение, не трейдинг). Данные data/ma_lab. 2г = один цикл — оговорка."""
import numpy as np, pandas as pd, sys
from _elliott_lab import load
from _ma_cross_lab4 import h5_signals

def ema(s, n): return s.ewm(span=n, adjust=False).mean()

def ma100_lean(d, hold=3):
    """Текущий грубый свитч: знак (close − SMA100), подтверждение hold баров (≈3.5 флипа/мес)."""
    close = d["close"]; sma = close.rolling(100).mean()
    raw = np.sign((close - sma).to_numpy())
    lean = np.zeros(len(raw)); cur = 0.0; run = 0; prev = 0.0
    for i in range(len(raw)):
        if np.isnan(raw[i]):
            lean[i] = cur; continue
        if raw[i] == prev:
            run += 1
        else:
            run = 1; prev = raw[i]
        if run >= hold and raw[i] != 0:
            cur = raw[i]
        lean[i] = cur
    return lean

def h5_lean(d):
    """Уклон по H5: +1 после лонг-сигнала до обратного кросса, −1 после шорт, 0 во флэте/до старта.
    Флэт = неподтверждённый кросс -> уклон снимается (нейтрал)."""
    close = d["close"]; hl2 = (d["high"] + d["low"]) / 2
    e14, e77 = ema(hl2, 14), ema(hl2, 77)
    diff = (e14 - e77).to_numpy(); sign = np.sign(diff); n = len(close)
    sig = dict(h5_signals(d))         # cross_i -> side (только прошедшие фильтры)
    lean = np.zeros(n); cur = 0.0
    for i in range(1, n):
        crossed = (not np.isnan(sign[i])) and sign[i] != 0 and sign[i] != sign[i - 1]
        if crossed:
            cur = float(sig.get(i, 0.0))   # прошёл H5 -> уклон; иначе нейтрал
        lean[i] = cur
    return lean

def stats(lean, lr, name):
    e = np.nan_to_num(lean)
    pnl = e[:-1] * lr[1:]                       # e_prev · доход
    eq = np.cumsum(pnl)
    dd = float((np.maximum.accumulate(eq) - eq).max()) * 100 if len(eq) else 0.0
    net = eq[-1] * 100 if len(eq) else 0.0
    nonflat = e[:-1] != 0
    right = (np.sign(e[:-1][nonflat]) == np.sign(lr[1:][nonflat]))
    rightpct = right.mean() * 100 if nonflat.sum() else 0.0
    flips = int((np.diff(np.sign(e[e != 0])) != 0).sum()) if (e != 0).sum() > 1 else 0
    months = len(lr) / (6 * 30)                 # 4ч-бары -> мес
    expo = nonflat.mean() * 100
    half = len(pnl) // 2
    h1, h2 = eq[half] * 100 if len(eq) > half else 0, (eq[-1] - eq[half]) * 100 if len(eq) > half else 0
    return dict(name=name, net=net, h1=h1, h2=h2, dd=dd, right=rightpct,
                flips_mo=flips / months if months else 0, expo=expo)

def main():
    syms = sys.argv[1].split(",") if len(sys.argv) > 1 else ["XBTUSDT", "ETHUSDT", "SOLUSDT"]
    for sym in syms:
        d = load(sym, "4h"); close = d["close"]
        lr = np.log(close).diff().fillna(0).to_numpy()
        leans = {
            "symmetric(0)": np.zeros(len(close)),
            "MA100 свитч": ma100_lean(d),
            "H5 свитч": h5_lean(d),
            "H5_cap ±0.5": np.clip(h5_lean(d), -1, 1) * 0.5,
            "buy&hold": np.ones(len(close)),
        }
        print(f"\n=== {sym} 4h ({len(close)} баров ≈ {len(close)/(6*30):.0f} мес) ===")
        print(f"{'уклон':16}{'net%':>7}{'h1%':>7}{'h2%':>7}{'DD%':>6}{'прав%':>6}{'флип/мес':>9}{'экспо%':>7}")
        for nm, ln in leans.items():
            s = stats(ln, lr, nm)
            star = "★" if s['h1'] > 0 and s['h2'] > 0 else " "
            print(f"{nm:16}{s['net']:>7.0f}{s['h1']:>7.0f}{s['h2']:>7.0f}{s['dd']:>6.0f}"
                  f"{s['right']:>6.0f}{s['flips_mo']:>9.1f}{s['expo']:>7.0f} {star}")
    print("\nЧитать: net = направленный доход уклона (range-харвест сверху, ~одинаков у всех).")
    print("Ключевое — DD и прав%: переключатель ценен если ловит сторону (прав%>50) и режет дрейф-блид (DD↓).")
    print("H5 уклон снимается во флэте (экспо<100) — это фича: не ставит сторону, когда тренда нет.")

if __name__ == "__main__":
    main()
