"""Проверка грид-сима Win (дисциплина: не верить на слово, особенно после lookahead +383).
1) calibrate() — воспроизводит ли сим РЕАЛЬНЫЙ оператор'ский GinArea R1 (+1593 / 0.295%)?
2) DUAL OPEN-STOP (close_on_disallow=False, close_mask=None) = конфиг +155/+100/+9 — магнитуды на
   цикле и 2024-чопе, + макс-мешок.
"""
import sys
from pathlib import Path
ROOT = Path("/Users/alexeychechikov/code/bot7")
sys.path.insert(0, str(ROOT))
from tools._grid_sim import calibrate, build_allow, sim, _load


def dual_openstop(label, a, b, band=0.3, **kw):
    ext, inwin = _load(a, b)
    close = ext[inwin]
    la = build_allow(ext, "long",  band=band)[inwin]
    sa = build_allow(ext, "short", band=band)[inwin]
    L = sim(close, "long",  allow=la, close_on_disallow=False, close_mask=None, **kw)
    S = sim(close, "short", allow=sa, close_on_disallow=False, close_mask=None, **kw)
    print(f"  {label:28s} DUAL итог {L['profit']+S['profit']:8.0f}  "
          f"макс-мешок {min(L['max_bag'], S['max_bag']):8.0f}  vol {L['volume']+S['volume']:11.0f}")


def main():
    calibrate()
    print("\n=== DUAL OPEN-STOP (конфиг +155/+100/+9), band 0.3 ===")
    dual_openstop("2024 chop H2 (июн-окт)", "2024-06-01", "2024-10-01")
    dual_openstop("цикл апр25→фев26",       "2025-04-01", "2026-02-15")


if __name__ == "__main__":
    main()
