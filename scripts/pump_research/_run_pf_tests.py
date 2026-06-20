"""Run the pump_freeze test suite from the repo root (avoids cd / PYTHONPATH
fiddling in bash). One-shot helper for the pump_freeze v2 assembly check."""
import os
import subprocess
import sys

ROOT = "/Users/alexeychechikov/code/bot7"
os.chdir(ROOT)
rc = subprocess.call(
    [ROOT + "/.venv/bin/python3", "-m", "pytest",
     "tests/services/pump_freeze/", "-q"]
)
sys.exit(rc)
