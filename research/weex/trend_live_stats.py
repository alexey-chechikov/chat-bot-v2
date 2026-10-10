"""Живой журнал трендовых сигналов (state/trend_signals.jsonl): закрытые сделки по монетам, % и PF.
Комиссия OKX 0.1% за круг вычитается из каждой сделки (как в бэктесте 2г)."""
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
rows = [json.loads(l) for l in (ROOT / "state" / "trend_signals.jsonl").read_text().splitlines() if l.strip()]
ex = [r for r in rows if r.get("event") == "EXIT"]
by = defaultdict(list)
for r in ex:
    by[r["symbol"]].append(float(r["pnl_pct"]) - 0.1)
print(f"журнал {rows[0]['ts'][:10]} … {rows[-1]['ts'][:10]}, закрытых сделок {len(ex)}")
tot = []
for sym, p in sorted(by.items()):
    w = [x for x in p if x > 0]
    l_ = [x for x in p if x <= 0]
    pf = sum(w) / -sum(l_) if l_ and sum(l_) else float("inf")
    tot += p
    print(f"{sym}: сделок {len(p)}, в плюсе {len(w)}, сумма {sum(p):+.2f}%, PF {pf:.2f}, лучшая {max(p):+.2f}%, "
          f"худшая {min(p):+.2f}%")
w = [x for x in tot if x > 0]
l_ = [x for x in tot if x <= 0]
print(f"ВСЕ: сделок {len(tot)}, сумма {sum(tot):+.2f}%, PF {sum(w) / -sum(l_):.2f}")
opn = json.loads((ROOT / "state" / "trend_signals_state.json").read_text())
print("открыты:", {k: (v["side"], v["entry_px"]) for k, v in opn.items()})
