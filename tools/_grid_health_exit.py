"""#3 (Win): health-decay (follow-through) EXIT on the grid leg, in grid-$ (Mac handoff §6).
Health (toward the leg's direction, Mac v5.5 formula):
  25(c>t50) + 15(c>t100) + 10(c>t200) + 20(body in dir) + 15(vol>vma100) + 15(close strength).
fizzle = health <= T for K bars -> cut that leg. Both legs harvest otherwise. Sweep T/K for the
T/K that MINIMIZES give-back WITHOUT killing the 0.29% harvest. Report grid-$ delta vs no-overlay,
across windows + 4 anchors."""
import warnings; warnings.filterwarnings("ignore")
import importlib.util, numpy as np, pandas as pd
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("gs", ROOT/"tools/_grid_sim.py")
gs = importlib.util.module_from_spec(spec); spec.loader.exec_module(gs)
RAW = pd.read_csv(ROOT/"backtests/frozen/BTCUSDT_1h_2y.csv")
RAW["ts"] = pd.to_datetime(RAW["ts"], unit="ms", utc=True); RAW = RAW.set_index("ts")


def health_masks(ext_close_idx, offset_h, T, K):
    """Return (fizzle_long, fizzle_short) 1m-aligned bool: True = cut that leg (health<=T for K bars)."""
    d4 = RAW.resample("4h", offset=f"{offset_h}h").agg(
        {"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna()
    o,h,l,c,v = d4["open"],d4["high"],d4["low"],d4["close"],d4["volume"]
    t50,t100,t200 = gs.tema(c,50), gs.tema(c,100), gs.tema(c,200)
    vma = v.rolling(100).mean()
    rng = (h-l).replace(0,np.nan)
    cs_long = ((c-l)/rng).clip(0,1)            # close strength for long (close near high)
    hl = (25*(c>t50)+15*(c>t100)+10*(c>t200)+20*(c>o)+15*(v>vma)+15*cs_long)
    hs = (25*(c<t50)+15*(c<t100)+10*(c<t200)+20*(c<o)+15*(v>vma)+15*(1-cs_long))
    def fizz(hser):
        low = (hser <= T)
        run = low.astype(int).groupby((~low).cumsum()).cumsum()
        f = (run >= K)
        return pd.Series(f.to_numpy(), index=c.index+pd.Timedelta(f"{4}h")).reindex(
            ext_close_idx, method="ffill").fillna(False).astype(bool).to_numpy()
    return fizz(hl), fizz(hs)


def book(a, b, T, K, offset_h=0, band=0.3, use_health=True):
    ext, inwin = gs._load(a, b); close = ext[inwin]
    la = gs.build_allow(ext,"long", band=band)[inwin]
    sa = gs.build_allow(ext,"short",band=band)[inwin]
    if use_health:
        fl, fs = health_masks(ext.index, offset_h, T, K)
        fl, fs = fl[inwin], fs[inwin]
    else:
        fl = fs = None
    L = gs.sim(close,"long", allow=la, close_mask=fl)
    S = gs.sim(close,"short",allow=sa, close_mask=fs)
    return L["profit"]+S["profit"], min(L["max_bag"], S["max_bag"])


WIN = [("2024 чоп","2024-03-01","2024-11-15"), ("цикл 25-26","2025-04-01","2026-02-15"),
       ("крах","2025-12-20","2026-02-15")]

print("=== БАЗА без health-оверлея (обе ноги + price-gate) ===")
for nm,a,b in WIN:
    p,bag = book(a,b,0,0,use_health=False)
    print(f"  {nm:14} net {p:7.0f}  мешок {bag:8.0f}")

print("\n=== СВИП T/K health-fizzle на грид-ноге (net | мешок) ===")
print(f"{'T/K':>8}{'2024':>16}{'цикл25-26':>16}{'крах':>14}")
for T in (30,40,50):
    for K in (1,2,3):
        row=[]
        for nm,a,b in WIN:
            p,bag = book(a,b,T,K); row.append(f"{p:.0f}|{bag:.0f}")
        print(f"  T{T} K{K}{row[0]:>14}{row[1]:>16}{row[2]:>14}")

print("\n=== РОБАСТНОСТЬ по якорям (лучший кандидат, цикл 25-26) ===")
for T,K in ((40,1),(50,2)):
    anch=[book('2025-04-01','2026-02-15',T,K,offset_h=off)[0] for off in (0,1,2,3)]
    print(f"  T{T}/K{K}: " + "  ".join(f"{x:.0f}" for x in anch) + f"  (разброс {max(anch)-min(anch):.0f})")
