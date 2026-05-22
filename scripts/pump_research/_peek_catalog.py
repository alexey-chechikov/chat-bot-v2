"""Quick sanity peek at the Phase 1 pump event catalog — confirms the
deliverable is usable before handoff to Phase 2. NOT the full Phase 2
discrimination analysis (precision/recall by horizon — that is Win's)."""
import pandas as pd

CAT = "/Users/alexeychechikov/code/bot7/state/pump_event_catalog.csv"
pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 30)

c = pd.read_csv(CAT)
print(f"catalog: {len(c)} rows x {len(c.columns)} cols")
print(f"columns: {list(c.columns)}\n")

feat = ["move_pct", "fwd_extreme_pct", "vol_spike", "oi_delta_win",
        "oi_delta_t30", "taker_win", "wick_ratio"]
for d in ("up", "down"):
    sub = c[c["direction"] == d]
    print(f"=== {d.upper()}  ({len(sub)} events) — mean by outcome ===")
    g = sub.groupby("outcome")[feat].mean().round(3)
    g.insert(0, "n", sub.groupby("outcome").size())
    print(g)
    print()
