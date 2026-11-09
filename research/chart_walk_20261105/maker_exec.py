"""Исполнение системы BTC лимитками (мейкер WEEX 0.016%) вместо рыночных (0.068% на сторону в учёте). Записано до прогона:
вход и выход по правилу — лимитка по цене закрытия 4ч; исполнена, если следующий час коснулся цены (лонг-вход: low ≤ цены,
лонг-выход: high ≥ цены; шорт зеркально); не исполнена — по рынку на закрытии следующего часа, 0.068%.
Цель шорта под жёлтой и добор — уровни известны заранее, лимитка, 0.016%. Без фандинга, вес как в системе."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path("/Users/alexeychechikov/code/bot7")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))
import plus as pl  # noqa: E402
import state_card as sc  # noqa: E402
from services.btc_signals import engine as en  # noqa: E402

TAKER, MAKER = 0.068, 0.016
T25 = 1735689600


def leg(side, p0, p1, f0, f1):
    return side * (p1 / p0 - 1) * 100 - f0 - f1 * (p1 / p0)


THRU = 0.0


def limit_fill(a, i, side, px, is_entry):
    """Лимитка по px на час i+1: исполнена, только если цена прошла сквозь неё на THRU (очередь в стакане). → (цена, комиссия, исполнена ли)."""
    if i + 1 >= len(a["t"]):
        return px, TAKER, False
    buy = (side == 1) == is_entry
    hit = a["l"][i + 1] <= px * (1 - THRU) if buy else a["h"][i + 1] >= px * (1 + THRU)
    return (px, MAKER, True) if hit else (float(a["c"][i + 1]), TAKER, False)


def main():
    global THRU
    a, _, _ = sc.load_coin("BTC")
    ev, _ = en.simulate(a, pl.layer(a))
    for THRU in (0.0, 0.0005, 0.001, 0.002):
        print(f"== сквозь цену на {THRU * 100:.2f}%", flush=True)
        one(a, ev)


def one(a, ev):
    base, mk, fills, n, b25, m25 = 0.0, 0.0, 0, 0, 0.0, 0.0
    for e in ev:
        if e["kind"] != "выход":
            continue
        p = e["pos"]
        s, w = e["side"], p["w"]
        p0, i0 = p["entry"], p["entry_i"]
        q0, f0, ok0 = limit_fill(a, i0, s, p0, True)
        if e["why"].startswith("цель"):
            q1, f1, ok1 = e["px"], MAKER, True
        else:
            q1, f1, ok1 = limit_fill(a, e["i"], s, e["px"], False)
        fills += ok0 + ok1
        n += 2
        if p["tag"] in en.MAIN:
            b = leg(s, p0, e["px"], TAKER, TAKER) * w * en.FIRST
            m = leg(s, q0, q1, f0, f1) * w * en.FIRST
            if p["add_done"]:
                b += leg(s, p["add_px"], e["px"], TAKER, TAKER) * w * en.ADD
                m += leg(s, p["add_px"], q1, MAKER, f1) * w * en.ADD
        else:
            b = leg(s, p0, e["px"], TAKER, TAKER) * w
            m = leg(s, q0, q1, f0, f1) * w
        base += b
        mk += m
        if p["entry_t"] >= T25:
            b25 += b
            m25 += m
    print(f"сделок {n // 2}; лимитки по закрытию исполнились в {fills / n * 100:.0f}% случаев", flush=True)
    print(f"рыночные: {base:+.1f}; лимитки: {mk:+.1f}; разница {mk - base:+.1f} | с 2025: {b25:+.1f} → {m25:+.1f} ({m25 - b25:+.1f})", flush=True)


if __name__ == "__main__":
    main()
