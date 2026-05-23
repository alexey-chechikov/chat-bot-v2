"""Inspect the current paper_wr_gate verdicts — what would be blocked right
now if every emitter was wired through `should_emit()`. Shadow-mode view
before turning on hard suppression.
"""
import os
import sys

sys.path.insert(0, "/Users/alexeychechikov/code/bot7")
os.chdir("/Users/alexeychechikov/code/bot7")

from services.common import paper_wr_gate as g  # noqa: E402

state = g.refresh_state()
buckets = state.get("buckets") or {}
print(f"computed_at: {state['computed_at']}")
print(f"policy: rolling_n={state['rolling_n']}  min_n={state['min_n']}  "
      f"unhealthy_wr<{state['unhealthy_wr_pct']}%\n")

# split by status
groups = {"unhealthy": [], "small_sample": [], "healthy": []}
for k, b in buckets.items():
    groups[b["status"]].append((k, b))

print(f"=== 🔴 UNHEALTHY (would be BLOCKED): {len(groups['unhealthy'])} ===")
print(f"  {'bucket':<55} {'n':>4} {'WR':>7}")
for k, b in sorted(groups["unhealthy"], key=lambda x: x[1]["wr_pct"]):
    print(f"  {k:<55} {b['n']:>4} {b['wr_pct']:>6.1f}%")

print(f"\n=== 🟢 HEALTHY (allowed): {len(groups['healthy'])} ===")
print(f"  {'bucket':<55} {'n':>4} {'WR':>7}")
for k, b in sorted(groups["healthy"], key=lambda x: -x[1]["wr_pct"]):
    print(f"  {k:<55} {b['n']:>4} {b['wr_pct']:>6.1f}%")

print(f"\n=== ⚪ SMALL SAMPLE (n<{state['min_n']} — auto-allow): "
      f"{len(groups['small_sample'])} ===")
print(f"  {'bucket':<55} {'n':>4} {'WR':>7}")
for k, b in sorted(groups["small_sample"], key=lambda x: -x[1]["n"]):
    print(f"  {k:<55} {b['n']:>4} {b['wr_pct']:>6.1f}%")

print(f"\ntotal buckets tracked: {len(buckets)}")
print(f"state file: {g.STATE_PATH}")
