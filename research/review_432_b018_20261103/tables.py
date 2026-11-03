"""Markdown-таблицы для docs/WEEX_GPT_432_B018_REVIEW_ANSWERS_2026-11-03.md из out/*.csv|json (после snap.py, b018_check.py)."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

OUT = Path(__file__).parent / "out"


def f(x, d=2, pct=False):
    if pd.isna(x):
        return "—"
    return f"{100 * x:.0f}" if pct else f"{x:+.{d}f}"


def zone(x):
    return "—" if pd.isna(x) else {1: "+1", 0: "0", -1: "−1"}[int(x)]


def main():
    t = pd.read_csv(OUT / "t432_entry_exit.csv")
    w = t[t["entry"] >= "2026-05-01"]
    print("### 432, май–октябрь 2026 (окно CoinGlass)\n")
    print("| Монета | Вход UTC | Выход UTC / причина | Net % | Зона H1 / H4 на входе | До EMA200 H4, % | Зона H4 на выходе | "
          "Следующие 20 H4 после выхода, % | CG вход: поток · ликв. шортов · ΔOI6 · фандинг · WI2 · L/S топ (перцентиль) | "
          "CG выход: поток · доля ликв. лонгов · ΔOI6 |")
    print("|---|---|---|---:|---|---:|---|---:|---|---|")
    for _, r in w.iterrows():
        cin = " · ".join(f(r[f"in_cgp_{k}"], pct=True) for k in ("flow6", "liqS6", "dOI6", "fr", "wi2", "ls_top"))
        cout = " · ".join(f(r[f"out_cgp_{k}"], pct=True) for k in ("flow6", "liqLshare6", "dOI6"))
        print(f"| {r['sym'][:3]} | {r['entry'][5:16]} | {r['exit'][5:16]} / {r['reason']} | {100 * r['net']:+.2f} | "
              f"{zone(r['in_h1_zone'])} / {zone(r['in_h4_zone'])} | {r['in_h4_dB']:+.1f} | {zone(r['out_h4_zone'])} | "
              f"{100 * r['fwd20']:+.2f} | {cin} | {cout} |")
    b = pd.read_csv(OUT / "b018_entry_exit.csv")
    print("\n### B018, все 12 циклов (выход — EMA3-вариант)\n")
    print("| № | Вход UTC / сторона | Net исходный → EMA3 | Зона H1 / H4 на входе | До EMA200 H4, % | Лестница G>Y>R H4 | "
          "Зона H4 на выходе | CG вход: поток 6ч % · доля ликв. лонгов · ΔOI6 % · WI2 · L/S топ | CG выход: поток 6ч % · доля ликв. лонгов · ΔOI6 % |")
    print("|---:|---|---|---|---:|---|---|---|---|")
    for _, r in b.iterrows():
        side = "L" if r["side"] == 1 else "S"
        cin = " · ".join(f(r.get(f"in_cg_{k}"), d) for k, d in (("flow6", 1), ("liqLshare6", 2), ("dOI6", 2), ("wi2", 0), ("ls_top", 2)))
        cout = " · ".join(f(r.get(f"out_cg_{k}"), d) for k, d in (("flow6", 1), ("liqLshare6", 2), ("dOI6", 2)))
        print(f"| {r['cycle']} | {r['entry'][5:]} / {side} | {r['net_base']:+.2f} → {r['net_ema3']:+.2f} | "
              f"{zone(r['in_h1_zone'])} / {zone(r['in_h4_zone'])} | {r['in_h4_dB']:+.1f} | {'да' if r['in_h4_stack'] else 'нет'} | "
              f"{zone(r['out_h4_zone'])} | {cin} | {cout} |")
    res = json.loads((OUT / "snap_result.json").read_text())
    print("\n### Средние оператора на входе 432, 2018–2026: доля «выше» и разница net (перестановки 9 999)\n")
    print("| Признак | BTC: доля у 432 / у случайных выше EMA200 | BTC: Δnet п.п., p, половины | ETH: доля 432 / случайных | ETH: Δnet п.п., p, половины |")
    print("|---|---|---|---|---|")
    for k in res["BTCUSDT"]["E"]:
        cells = []
        for sym in ("BTCUSDT", "ETHUSDT"):
            e, base = res[sym]["E"][k], res[sym]["random_regime_share"][k]
            cells.append(f"{100 * e['share_yes']:.0f}% / {100 * base:.0f}%")
            if e["p"] is None:
                cells.append("групп <10 — не проверяется")
            else:
                cells.append(f"{e['diff_pct']:+.2f}, p {e['p']:.2f}; {e['diff_p1_pct']:+.2f} / {e['diff_p2_pct']:+.2f}")
        print(f"| {k} | {cells[0]} | {cells[1]} | {cells[2]} | {cells[3]} |")


if __name__ == "__main__":
    main()
