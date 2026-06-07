"""Follow-through EXIT — свип порога (T=health threshold, K=подряд баров).
Цель оператора = МИН ПРОСАДКА. Выбираем config робастный по ВСЕМ anchor-offset (не по одному).
Reuse build/load_off/metr из _followthrough_exit_test. Mode = regime+voloff+fizzle.
"""
import sys
from pathlib import Path
import numpy as np

ROOT = Path("/Users/alexeychechikov/code/bot7")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from _followthrough_exit_test import load_off, build, metr, FEE


def bt(d, T, K, fee=FEE):
    c, regDir, voloff, ftBull, ftBear, n = d["c"], d["regDir"], d["voloff"], d["ftBull"], d["ftBear"], d["n"]
    pos = 0; entry = 0.0; lowcnt = 0; rets = []
    for i in range(2, n):
        if pos != 0:
            hd = ftBull[i] if pos == 1 else ftBear[i]
            lowcnt = lowcnt + 1 if hd <= T else 0
            ex = regDir[i] != pos or voloff[i] or lowcnt >= K
            if ex:
                rets.append((c[i] - entry) / entry * pos - fee / 100.0)
                pos = 0; lowcnt = 0
        if pos == 0 and regDir[i] != regDir[i-1] and regDir[i] != 0:
            pos = regDir[i]; entry = c[i]; lowcnt = 0
    return rets


def main():
    pair = sys.argv[1] if len(sys.argv) > 1 else "BTCUSDT"
    ds = [build(load_off(pair, off)) for off in (0, 1, 2, 3)]
    base = [metr(bt(d, -1, 9999)) for d in ds]  # T=-1 => fizzle никогда = regime+voloff
    print(f"=== {pair} follow-through THRESHOLD SWEEP (regime+voloff+fizzle, anchors 0/1/2/3ч) ===")
    print(f"BASELINE (no fizzle): DD per-off {[b['dd'] for b in base]}  net {[b['net'] for b in base]}")
    print(f"{'T':>3} {'K':>2} | net~ DD~  DDworst | DD per-offset           net per-offset")
    best = None
    for T in (25, 30, 35, 40, 45, 50):
        for K in (1, 2, 3):
            ms = [metr(bt(d, T, K)) for d in ds]
            nets = [m["net"] for m in ms]; dds = [m["dd"] for m in ms]
            mn, mdd, wdd = round(np.mean(nets)), round(np.mean(dds)), min(dds)
            print(f"{T:>3} {K:>2} | {mn:>4} {mdd:>4} {wdd:>6}  | {str(dds):22s} {nets}")
            # робастный критерий: лучший (наименее плохой) worst-DD, при net не хуже baseline
            score = (wdd, mn)
            if best is None or score > best[0]:
                best = (score, T, K, mn, mdd, wdd)
    _, T, K, mn, mdd, wdd = best
    print(f"\nРОБАСТНЫЙ выбор (max worst-DD, потом net): T={T} K={K}  net~{mn} DD~{mdd} DDworst {wdd}")


if __name__ == "__main__":
    main()
