"""Повторная сверка своего сима ETH Auto с движком GinArea (10.10).

01.10 tools/eth_auto_sim.py не сошёлся с развёрткой клона 6227907209 (so 0.75 / ioo 0.1). Здесь — другой
эталон: клон 5678633257 (so 0.4, ioo 0.06, шаг 0.1, цель 2.0, ордер 0.01, 800 ордеров, выход по средней):
год 25.09.2025–17.09.2026 (закрыто $3 484, итог $2 946, оборот $366 232, позиция −1.75) и 12 помесячных
тестов (state/ginarea_sweep_eth_border_0.jsonl). Критерий: итог и оборот в пределах ±15% по году и
у большинства месяцев. Иначе — сим не годится, сетку на WEEX по нему не строить."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.eth_auto_sim import VARIANTS, load, path_points, run  # noqa: E402

SO, IOO = 0.4, 0.06
YEAR = {"profit": 3483.51, "current_profit": 2946.46, "volume": 366232.6, "position": -1.75}


def variants():
    out = dict(VARIANTS)
    for k in ("док", "док+сброс обеих"):
        out[k] = dict(out[k], ioo=IOO)
    return out


def show(tag, r, ga):
    vol_err = r.turnover / ga["volume"] - 1 if ga.get("volume") else float("nan")
    net_err = r.net / ga["current_profit"] - 1 if ga.get("current_profit") else float("nan")
    print(f"  {tag:<22} итог {r.net:>8,.0f} (GA {ga['current_profit']:>7,.0f}, {net_err:+.0%}) | закрыто {r.realized:>7,.0f} "
          f"(GA {ga['profit']:>7,.0f}) | оборот {r.turnover:>9,.0f} (GA {ga['volume']:>9,.0f}, {vol_err:+.0%}) | "
          f"закрытий {r.closes}")
    return net_err, vol_err


def main():
    d = load("2025-09-25", "2026-09-17 09:20")
    pts = path_points(d)
    print(f"ГОД {d.index[0]} → {d.index[-1]}")
    for name, kw in variants().items():
        r = run(pts, 2.0, so=SO, **kw)
        show(name, r, YEAR)
    months = [json.loads(x) for x in (ROOT / "state" / "ginarea_sweep_eth_border_0.jsonl").read_text().splitlines()
              if x.strip()]
    months.sort(key=lambda m: m["from"])
    print("\nМЕСЯЦЫ (каждый с нуля, как тест GinArea)")
    score = {k: [] for k in variants()}
    for m in months:
        dm = load(m["from"], m["to"])
        dm = dm[dm.index < m["to"]]
        pm = path_points(dm)
        print(f"{m['from']}: GA итог {m['current_profit']:+.0f}, закрыто {m['profit']:+.0f}, оборот {m['volume']:,.0f}")
        for name, kw in variants().items():
            r = run(pm, 2.0, so=SO, **kw)
            score[name].append(show(name, r, m))
    print("\nСВОДКА: месяцев, где итог И оборот в пределах ±15%")
    for name, errs in score.items():
        ok = sum(1 for a, b in errs if abs(a) <= 0.15 and abs(b) <= 0.15)
        vol_ok = sum(1 for _, b in errs if abs(b) <= 0.15)
        print(f"  {name:<22} {ok}/12, только оборот {vol_ok}/12")


if __name__ == "__main__":
    main()
