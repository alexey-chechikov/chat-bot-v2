"""cScalp pre-session density-карта: ключевые уровни плотности перед сессией (BTC/ETH/SOL/XRP).
Плотность ≈ узлы объёма (VPVR) + value area + дневной hi/lo + свинги + круглые. Не DOM (его читаешь
в cScalp живьём), а карта значимых уровней, к которым тянется/отбивается цена. Данные BitMEX 5м."""
import sys
import numpy as np, pandas as pd
sys.path.insert(0, "tools")
from _cscalp_density_backtest import fetch_5m

def vpvr(df, win=288, bins=120):
    """POC/VAH/VAL + топ-HVN по trailing win баров (24ч на 5м)."""
    sub = df.iloc[-win:]; c = sub["close"].to_numpy(); v = sub["volume"].to_numpy()
    lo, hi = sub["low"].min(), sub["high"].max()
    edges = np.linspace(lo, hi, bins + 1); mid = (edges[:-1] + edges[1:]) / 2
    idx = np.clip(np.digitize(c, edges) - 1, 0, bins - 1)
    vol = np.bincount(idx, weights=v, minlength=bins)
    poc_i = vol.argmax(); poc = mid[poc_i]
    # value area: расширяем от POC пока не наберём 70% объёма
    order = sorted(range(bins), key=lambda b: -vol[b])
    tot = vol.sum(); acc = 0; lo_i = hi_i = poc_i
    sel = set()
    for b in order:
        sel.add(b); acc += vol[b]
        if acc >= 0.70 * tot: break
    va = [mid[b] for b in sel]
    vah, val = max(va), min(va)
    # топ-HVN (узлы), разнесённые > 0.3% друг от друга
    hvn = []
    for b in order:
        if vol[b] < 0.3 * vol[poc_i]: break
        if all(abs(mid[b] - x) / x > 0.003 for x in hvn):
            hvn.append(mid[b])
        if len(hvn) >= 6: break
    return poc, vah, val, hvn

def levels(df):
    px = df["close"].iloc[-1]
    poc, vah, val, hvn = vpvr(df)
    d1 = df.iloc[-288:]          # ~сутки
    pdh, pdl = d1["high"].max(), d1["low"].min()
    sw_hi = df["high"].iloc[-48:].max(); sw_lo = df["low"].iloc[-48:].min()  # 4ч свинг
    rnd = round(px / (px * 0.01)) * (px * 0.01)  # ближайшая «круглая» ~1%
    out = [("POC (магнит)", poc), ("VAH", vah), ("VAL", val),
           ("сутки-hi", pdh), ("сутки-lo", pdl), ("свинг-hi 4ч", sw_hi), ("свинг-lo 4ч", sw_lo)]
    out += [(f"HVN", h) for h in hvn if abs(h - poc) / poc > 0.003]
    return px, out

def main():
    syms = sys.argv[1].split(",") if len(sys.argv) > 1 else ["XBTUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]
    print("cScalp DENSITY-КАРТА (BitMEX 5м, trailing 24ч) — уровни отсортированы по близости к цене\n")
    for sym in syms:
        try:
            df = fetch_5m(sym)
            px, lv = levels(df)
            print(f"=== {sym}  цена {px:.4f} ===")
            rows = sorted(lv, key=lambda x: abs(x[1] - px))
            for name, val in rows:
                d = (val / px - 1) * 100
                arrow = "▲над" if val > px else "▼под"
                bar = "★" if abs(d) < 0.4 else " "   # в зоне действия (<0.4%)
                print(f"  {bar} {name:14} {val:>11.4f}  {arrow} {d:>+5.2f}%")
            print()
        except Exception as e:
            print(sym, "err", e)
    print("Читать: ★ = уровень в зоне действия (<0.4% от цены) — самые торгуемые плотности на ближайшие часы.")
    print("Используй как КАРТА (где ставить лимитки в плотность), вход — мейкером, см. бэктест-вывод.")

if __name__ == "__main__":
    main()
