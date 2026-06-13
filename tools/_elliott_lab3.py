"""Elliott фаза-3: ПРОВЕРКА находки Мака (12.06) на моём движке + multi-symbol (его caveat).
Мак: на BTC 4ч «импульс vs коррекция» структуры свингов = уклон качества входа H5 (импульс +2.67 win44
vs коррекция −1.12 win19), совпадает с H5-наклоном лишь на 64% → новая инфа. Робастно «импульс лучше»
по порогам 2.5–5%, хрупко «коррекция плоха». Нужен ETH/SOL.

Измеримый импульс/коррекция (= «чистый тренд vs перекрытие» в EW-обёртке): на баре входа берём
последние M подтверждённых ZigZag-пивотов (каузально) и swing-ER = |нетто-смещение| / |путь по свингам|.
ER→1 = импульс (цена шла эффективно), ER→0 = коррекция/чоп (перекрытие). Делим исходы H5 по медиане ER.
Учёт идентичен лабе (fee 0.05%/сторона). Скрипты: переиспользуем h5_entries/zigzag."""
import numpy as np, pandas as pd, sys
from _elliott_lab import load, zigzag_confirmed, FEE
from _elliott_lab2 import h5_entries

M_PIV = 4          # сколько последних свингов в окно ER (4 пивота = ~2 свинга)

def swing_er_at(piv_avail):
    """swing-ER по последним M_PIV подтверждённым пивотам. None если мало."""
    if len(piv_avail) < M_PIV:
        return None
    pts = [p[2] for p in piv_avail[-M_PIV:]]
    net = abs(pts[-1] - pts[0])
    path = sum(abs(pts[k + 1] - pts[k]) for k in range(len(pts) - 1))
    return net / path if path > 0 else None

def label_entries(d, entries, thr):
    """Для каждого входа H5 — swing-ER по пивотам, подтверждённым ДО бара входа (каузально)."""
    high, low = d["high"].to_numpy(), d["low"].to_numpy()
    piv = zigzag_confirmed(high, low, thr)
    ers = []
    for (ei, xi, side) in entries:
        avail = [p for p in piv if p[0] <= ei]
        ers.append(swing_er_at(avail))
    return np.array([np.nan if e is None else e for e in ers])

def outcomes(entries, close):
    lr = np.log(close).to_numpy(); n = len(close)
    out = []
    for (ei, xi, side) in entries:
        if xi <= ei or xi >= n:
            out.append(np.nan); continue
        out.append((side * (lr[xi] - lr[ei]) - 2 * FEE) * 100)
    return np.array(out)

def grp(rr, mask, label):
    r = rr[mask & ~np.isnan(rr)]
    if len(r) < 4:
        return f"    {label:18} n={len(r):>3} — мало"
    gp, gl = r[r > 0].sum(), -r[r < 0].sum()
    return (f"    {label:18} n={len(r):>3}  avg{r.mean():>6.2f}%  win{(r>0).mean()*100:>4.0f}%"
            f"  net{r.sum():>6.0f}%  PF{gp/gl if gl>0 else 9:>5.2f}")

def main():
    syms = sys.argv[1].split(",") if len(sys.argv) > 1 else ["XBTUSDT", "ETHUSDT", "SOLUSDT"]
    for sym in syms:
        d = load(sym, "4h")
        entries, close = h5_entries(d)
        rr = outcomes(entries, close)
        base = rr[~np.isnan(rr)]
        print(f"\n=== {sym} 4h — импульс/коррекция-разрез H5 ({len(base)} сделок) ===")
        gpb, glb = base[base > 0].sum(), -base[base < 0].sum()
        print(f"    {'БАЗА H5':18} n={len(base):>3}  avg{base.mean():>6.2f}%  win{(base>0).mean()*100:>4.0f}%"
              f"  net{base.sum():>6.0f}%  PF{gpb/glb:>5.2f}")
        for thr in (0.025, 0.03, 0.04, 0.05):
            er = label_entries(d, entries, thr)
            med = np.nanmedian(er)
            print(f"  -- ZigZag {thr*100:.1f}% (медиана ER={med:.2f}) --")
            print(grp(rr, er >= med, "импульс (ER↑)"))
            print(grp(rr, er < med, "коррекция (ER↓)"))

if __name__ == "__main__":
    main()
