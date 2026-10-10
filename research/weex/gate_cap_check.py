"""Почему гейт шорта по SMA100 не меняет сетку WEEX: проверка гипотезы «потолок $4 000 набивается раньше,
чем включается гейт». Тот же гейт при потолке $40 000 — если гипотеза верна, гейт начинает влиять."""
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fast_grid as fg  # noqa: E402
import gate_compare as gc  # noqa: E402


def one(args):
    cap, gated = args
    data = fg.load("BTCUSDT")
    gate = {"SHORT": gc.minute_gate(data[0])["SHORT"]} if gated else None
    r = fg.run(data, ("LONG", "SHORT"), 0.2, 0.21, order_qty=0.0012, cap_usd=cap, max_orders=10_000, gate=gate)
    return cap, gated, r


if __name__ == "__main__":
    with ProcessPoolExecutor(max_workers=4) as ex:
        res = list(ex.map(one, [(4000.0, False), (4000.0, True), (40000.0, False), (40000.0, True)]))
    for cap, gated, r in res:
        print(f"потолок ${cap:,.0f} {'с гейтом шорта' if gated else 'без гейта     '}: итог {r['итог']:+.0f}, "
              f"шорт {r['по сторонам']['SHORT']:+.0f}, худший мешок {r['худший мешок']:.0f}, просадка {r['просадка капитала']:.0f}")
