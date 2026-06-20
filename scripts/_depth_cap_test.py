"""Тест GPT-идеи #1: 2-layer grid (core всегда + DEEP добор только в благоприятном режиме).
Хвост мешка = глубокий добор в тренде. Гипотеза: ограничить глубину когда цена ДАЛЕКО от линии
(тренд) → меньше мешок, не убив харвест (в чопе у линии глубина разрешена).
Форк Win-sim (один доп. гейт на добор за core_orders). DUAL OPEN-STOP. Критерий: мешок −X% при net ~неизм.
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path("/Users/alexeychechikov/code/bot7")
sys.path.insert(0, str(ROOT))
from tools._grid_sim import load_1m, tema, build_allow, _load


def build_deep_allow(close_1m, deep_band, tf="4h"):
    """DEEP добор разрешён, пока |цена − TEMA200| < deep_band% (у линии = mean-rev зона). Причинно."""
    c = close_1m.resample(tf).last().dropna()
    t200 = tema(c, 200)
    ok = ((c - t200).abs() / t200 * 100.0) < deep_band
    shifted = pd.Series(ok.to_numpy(), index=c.index + pd.Timedelta(tf))
    return shifted.reindex(close_1m.index, method="ffill").fillna(False).astype(bool).to_numpy()


def sim2(close, side="long", step=0.04, target=0.30, min_stop=0.008, size0=0.001,
         order_mult=1.0, max_orders=600, dip_thr=1.0, ind_win=30, instop=0.05,
         fee_bps=0.0, restart=True, allow=None, deep_allow=None, core_orders=600):
    c = close.to_numpy(float); n = len(c); d = 1 if side == "long" else -1
    step /= 100; target /= 100; min_stop /= 100; dip_thr /= 100; instop /= 100
    realized = 0.0; volume = 0.0; max_bag = 0.0
    positions = []; started = False; last_in = None; level = 0; cur_step = step
    pending = False; swing = None
    for i in range(ind_win, n):
        px = c[i]
        still = []
        for p in positions:
            hit = px >= p["entry"] * (1 + target) if d > 0 else px <= p["entry"] * (1 - target)
            if hit:
                realized += p["size"] * p["entry"] * (target - min_stop)
            else:
                still.append(p)
        positions = still
        cur_unreal = sum(p["size"] * (px - p["entry"]) * d for p in positions)
        if cur_unreal < max_bag:
            max_bag = cur_unreal
        gate_ok = allow is None or allow[i]
        if not started and len(positions) == 0:
            mv = c[i] / c[i - ind_win] - 1
            trig = (mv <= -dip_thr) if d > 0 else (mv >= dip_thr)
            if gate_ok and trig:
                positions.append({"entry": px, "size": size0}); volume += size0 * px
                last_in = px; level = 1; started = True; cur_step = step
                pending = False; swing = px
            continue
        adverse = px <= last_in * (1 - cur_step) if d > 0 else px >= last_in * (1 + cur_step)
        if started and gate_ok and len(positions) < max_orders and last_in is not None:
            if adverse:
                pending = True
                swing = px if swing is None else (min(swing, px) if d > 0 else max(swing, px))
            if pending:
                swing = (min(swing, px) if d > 0 else max(swing, px))
                bounce = px >= swing * (1 + instop) if d > 0 else px <= swing * (1 - instop)
                if bounce:
                    can_deep = len(positions) < core_orders or deep_allow is None or deep_allow[i]
                    if can_deep:
                        positions.append({"entry": px, "size": size0}); volume += size0 * px
                        last_in = px; level += 1; cur_step = min(cur_step * order_mult, 0.5)
                    pending = False; swing = px
        if started and len(positions) == 0 and restart:
            started = False; last_in = None; level = 0; pending = False
    unreal = sum(p["size"] * (c[-1] - p["entry"]) * d for p in positions)
    return dict(profit=realized + unreal, max_bag=max_bag, volume=volume)


def dual(label, a, b, band=0.3, core_orders=600, deep_band=None):
    ext, inwin = _load(a, b); close = ext[inwin]
    la = build_allow(ext, "long",  band=band)[inwin]
    sa = build_allow(ext, "short", band=band)[inwin]
    da = build_deep_allow(ext, deep_band)[inwin] if deep_band is not None else None
    L = sim2(close, "long",  allow=la, deep_allow=da, core_orders=core_orders)
    S = sim2(close, "short", allow=sa, deep_allow=da, core_orders=core_orders)
    net = L["profit"] + S["profit"]; bag = min(L["max_bag"], S["max_bag"])
    print(f"  {label:34s} net {net:7.0f}   макс-мешок {bag:8.0f}   vol {L['volume']+S['volume']:10.0f}")
    return net, bag


def main():
    for label, a, b in (("ЦИКЛ апр25→фев26", "2025-04-01", "2026-02-15"),
                        ("2024 chop", "2024-06-01", "2024-10-01")):
        print(f"\n=== {label} — DUAL OPEN-STOP, 2-layer depth-cap ===")
        nb, bb = dual("БАЗА (глубина 600, без cap)", a, b, core_orders=600, deep_band=None)
        for core in (30, 50):
            for db in (2.0, 3.0, 5.0):
                n2, b2 = dual(f"core{core} + deep<{db}% от линии", a, b, core_orders=core, deep_band=db)
                if bb:
                    print(f"      → мешок {100*(b2/bb-1):+.0f}%   net {100*(n2/nb-1) if nb else 0:+.0f}%")


if __name__ == "__main__":
    main()
