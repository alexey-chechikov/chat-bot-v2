"""Phase B — sequential per-symbol backfill: features + Bybit OI + master CSV.

Runs the 3 Phase-B scripts in order for one symbol (sequential because
build_master needs the outputs of the first two). Each takes ~1-3 min;
total ~3-6 min per symbol.

Usage:
    .venv/bin/python3 scripts/pump_research/_run_phase_b.py ETHUSDT
    .venv/bin/python3 scripts/pump_research/_run_phase_b.py XRPUSDT
"""
import subprocess
import sys

ROOT = "/Users/alexeychechikov/code/bot7"
PY = ROOT + "/.venv/bin/python3"

if len(sys.argv) != 2:
    print("usage: _run_phase_b.py <SYMBOL>", file=sys.stderr)
    sys.exit(2)

sym = sys.argv[1]
for script in ("backfill_features.py", "fetch_bybit_oi.py", "build_master.py"):
    print(f"\n--- {script} --symbol {sym} ---", flush=True)
    rc = subprocess.call(
        [PY, f"{ROOT}/scripts/pump_research/{script}", "--symbol", sym]
    )
    if rc != 0:
        print(f"FAIL: {script} exit {rc}", file=sys.stderr)
        sys.exit(rc)
print(f"\n=== Phase B {sym} DONE ===")
