"""Гейт v5.7 (price vs MA200, band0.3, hold2) — чистота EMA vs TEMA vs SMA по флипам.
Отвечает на «простая EMA как будто чище». Чистота = мало флипов режима. По якорям 0/1/2/3ч.
(Это ПРОКСИ чистоты, не grid-$; реальный harvest EMA-vs-TEMA = Win-сим.)
"""
import sys
from pathlib import Path
import numpy as np

ROOT = Path("/Users/alexeychechikov/code/bot7")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from _followthrough_exit_test import load_off

BAND, CONF, WARM = 0.3, 2, 200


def ma200(c, kind):
    if kind == "EMA":
        return c.ewm(span=200, adjust=False).mean().to_numpy(float)
    if kind == "SMA":
        return c.rolling(200).mean().to_numpy(float)
    e1 = c.ewm(span=200, adjust=False).mean()
    e2 = e1.ewm(span=200, adjust=False).mean()
    e3 = e2.ewm(span=200, adjust=False).mean()
    return (3 * e1 - 3 * e2 + e3).to_numpy(float)


def gate(c, ma):
    n = len(c)
    rawL = c > ma * (1 - BAND / 100.0)
    rawS = c < ma * (1 + BAND / 100.0)
    lOn = lOff = sOn = sOff = 0
    lOK = sOK = True
    reg = np.zeros(n, int)
    for i in range(n):
        lOn = lOn + 1 if rawL[i] else 0
        lOff = 0 if rawL[i] else lOff + 1
        sOn = sOn + 1 if rawS[i] else 0
        sOff = 0 if rawS[i] else sOff + 1
        if lOn >= CONF: lOK = True
        elif lOff >= CONF: lOK = False
        if sOn >= CONF: sOK = True
        elif sOff >= CONF: sOK = False
        reg[i] = 0 if (lOK and sOK) else (1 if lOK else -1)
    return reg


def main():
    pair = sys.argv[1] if len(sys.argv) > 1 else "BTCUSDT"
    print(f"=== {pair} 4h  ГЕЙТ v5.7 чистота: flips / %FLAT(обе ноги) по якорям 0/1/2/3ч ===")
    print("(меньше flips = чище; %FLAT = доля времени обе ноги = харвест-зона)")
    for kind in ("EMA", "TEMA", "SMA"):
        cells = []
        for off in (0, 1, 2, 3):
            o = load_off(pair, off)
            cc = o["close"].to_numpy(float)
            reg = gate(cc, ma200(o["close"], kind))[WARM:]
            flips = int((np.diff(reg) != 0).sum())
            flat = round(100 * np.mean(reg == 0))
            cells.append(f"{flips:>3}/{flat:>2}%")
        print(f"  {kind:4s} | " + "  ".join(cells))


if __name__ == "__main__":
    main()
