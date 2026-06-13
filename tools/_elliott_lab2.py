"""Elliott фаза-2: самый ЧЕСТНЫЙ к Эллиоту тест — волна как КОНТЕКСТ поверх H5, не замена.
Берём входы H5 (EMA14/77 hl2 4ч + наклон + режим + анти-whipsaw) и делим их по признаку:
была ли НЕПОСРЕДСТВЕННО перед кроссом валидная коррекция волны-2 в фиб-зоне (по каузальному ZigZag),
согласованная с направлением входа. Если Эллиот реален — подмножество «с волной» бьёт «без волны».
Учёт идентичен лабе (fee 0.05%/сторона, лог-доход, половины)."""
import numpy as np, pandas as pd, sys
from _elliott_lab import load, zigzag_confirmed, FIB_LO, FIB_HI, FEE

def ema(s, n): return s.ewm(span=n, adjust=False).mean()

def h5_entries(d):
    """Список (entry_i, exit_i, side) по правилу H5 (вход на кроссе 14x77, выход на обратном)."""
    close = d["close"]; hl2 = (d["high"] + d["low"]) / 2
    e14, e77, e200 = ema(hl2, 14), ema(hl2, 77), ema(hl2, 200)
    slope = e77.diff(5)
    diff = (e14 - e77).to_numpy()
    cl, sl, rg = close.to_numpy(), slope.to_numpy(), e200.to_numpy()
    sign = np.sign(diff)
    n = len(cl)
    entries = []
    last_cross = -1
    open_trade = None
    for i in range(1, n):
        if np.isnan(sign[i]) or sign[i] == 0 or sign[i] == sign[i - 1]:
            continue
        side = int(sign[i])
        prev_leg = i - last_cross if last_cross >= 0 else 999
        last_cross = i
        # закрыть открытую сделку на обратном кроссе
        if open_trade is not None:
            ei, s0 = open_trade
            entries.append((ei, i, s0))
            open_trade = None
        # фильтры H5
        slope_ok = (sl[i] > 0) == (side > 0)
        reg_ok = (cl[i] > rg[i]) == (side > 0)
        whip_ok = prev_leg > 4
        if slope_ok and reg_ok and whip_ok:
            open_trade = (i, side)
    return entries, close

def wave_context(d, entries, thr):
    """Для каждого входа: был ли валидный wave-1+wave-2(фиб) перед кроссом, в сторону входа.
    Каузально: используем только пивоты, ПОДТВЕРЖДённые до бара входа (confirm_i <= entry_i)."""
    high, low = d["high"].to_numpy(), d["low"].to_numpy()
    piv = zigzag_confirmed(high, low, thr)
    flags = []
    for (ei, xi, side) in entries:
        avail = [p for p in piv if p[0] <= ei]      # только подтверждённые к входу
        ok = False
        if len(avail) >= 3:
            L0, H1, L2 = avail[-3], avail[-2], avail[-1]
            if side > 0 and L0[3] == -1 and H1[3] == +1 and L2[3] == -1:
                w1 = H1[2] - L0[2]
                if w1 > 0 and L2[2] > L0[2]:
                    retr = (H1[2] - L2[2]) / w1
                    ok = FIB_LO <= retr <= FIB_HI
            if side < 0 and L0[3] == +1 and H1[3] == -1 and L2[3] == +1:
                w1 = L0[2] - H1[2]
                if w1 > 0 and L2[2] < L0[2]:
                    retr = (L2[2] - H1[2]) / w1
                    ok = FIB_LO <= retr <= FIB_HI
        flags.append(ok)
    return np.array(flags)

def stat(entries, close, mask, label):
    lr = np.log(close).to_numpy(); n = len(close)
    rr = []
    for (ei, xi, side), m in zip(entries, mask):
        if not m or xi <= ei or xi >= n:
            continue
        rr.append(side * (lr[xi] - lr[ei]) - 2 * FEE)
    if len(rr) < 3:
        return f"  {label:26} n={len(rr):>3} — мало"
    rr = np.array(rr)
    gp, gl = rr[rr > 0].sum(), -rr[rr < 0].sum()
    return (f"  {label:26} n={len(rr):>3}  net{rr.sum()*100:>6.0f}%  avg{rr.mean()*100:>5.2f}%"
            f"  win{(rr>0).mean()*100:>4.0f}%  PF{gp/gl if gl>0 else 9:>5.2f}")

def main():
    syms = sys.argv[1].split(",") if len(sys.argv) > 1 else ["XBTUSDT", "ETHUSDT", "SOLUSDT"]
    for sym in syms:
        d = load(sym, "4h")
        entries, close = h5_entries(d)
        print(f"\n=== {sym} 4h — H5 входы, разрез по контексту волны Эллиота ===")
        all_mask = np.ones(len(entries), bool)
        print(stat(entries, close, all_mask, "ВСЕ H5 (база)"))
        for thr in (0.03, 0.05, 0.08):
            wf = wave_context(d, entries, thr)
            print(f"  -- ZigZag порог {thr*100:.0f}% --")
            print(stat(entries, close, wf, f"H5 + волна-2(фиб)"))
            print(stat(entries, close, ~wf, f"H5 без волны"))

if __name__ == "__main__":
    main()
