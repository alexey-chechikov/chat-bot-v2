"""Portable paths and offline pinned-source extraction for the research lab.

BTC_REPAIR_OLD_SOURCE overrides the original-source directory.
BTC_REPAIR_DATA overrides the raw-data directory (flat filenames or repo layout).
Importing this module never extracts files, changes Git state, or uses a network.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

LAB_ROOT = Path(__file__).resolve().parent
ORIGINAL_COMMIT = "762ec6f8124cb499a7104fd74544887190d04acb"


def _find_project_root(start):
    for candidate in (Path(start), *Path(start).parents):
        if (candidate / "services/btc_signals/engine.py").is_file() and (candidate / "research/chart_walk_20261105").is_dir():
            return candidate.resolve()
    raise RuntimeError("Place the lab inside a checkout containing services/btc_signals/engine.py and research/chart_walk_20261105")


PROJECT_ROOT = _find_project_root(LAB_ROOT)
_sibling_original = LAB_ROOT.with_name("btc-features-audit-20261109")
_default_original = _sibling_original if _sibling_original.is_dir() else LAB_ROOT / "original_source"
ORIGINAL_SOURCE = Path(os.environ.get("BTC_REPAIR_OLD_SOURCE", str(_default_original))).expanduser().resolve()
_legacy_project = Path(r"C:\bot7")
_legacy_data = _legacy_project / "tmp/indicator_lab_data"
_default_data = _legacy_data if _legacy_data.is_dir() else PROJECT_ROOT / "tmp/indicator_lab_data"
_data_overridden = "BTC_REPAIR_DATA" in os.environ
DATA_DIR = Path(os.environ.get("BTC_REPAIR_DATA", str(_default_data))).expanduser().resolve()

# These are the exact original Python bodies used by AST loaders, the original
# features/engine modules, and the committed table used for reconciliation.
ORIGINAL_FILES = (
    "services/btc_signals/engine.py",
    "services/btc_signals/features.py",
    "research/chart_walk_20261105/cw_data.py",
    "research/chart_walk_20261105/journal.py",
    "research/chart_walk_20261105/rules.py",
    "research/chart_walk_20261105/entry_rules.py",
    "research/chart_walk_20261105/words.py",
    "research/chart_walk_20261105/entry_common.py",
    "research/chart_walk_20261105/state_map.py",
    "research/chart_walk_20261105/plus.py",
    "research/chart_walk_20261105/out/trade_table_btc.csv",
)


def bootstrap_project():
    """Make the selected checkout's production modules importable from the lab."""
    value = str(PROJECT_ROOT)
    if not sys.path or sys.path[0] != value:
        if value in sys.path:
            sys.path.remove(value)
        sys.path.insert(0, value)


def ensure_original_sources():
    """Extract only missing pinned inputs, via local git show; never overwrite.

    Git lazy object fetching is explicitly disabled. If the commit/blob is not
    present locally, fail with an offline-source instruction, never git fetch.
    Existing original sources are reused without any regeneration.
    """
    missing = []
    for rel in ORIGINAL_FILES:
        path = ORIGINAL_SOURCE / rel
        if path.exists():
            if not path.is_file():
                raise RuntimeError(f"Original-source path exists but is not a file: {path}")
        else:
            missing.append((rel, path))
    if not missing:
        return ORIGINAL_SOURCE
    env = dict(os.environ, GIT_NO_LAZY_FETCH="1", GIT_TERMINAL_PROMPT="0")
    payloads = []
    for rel, path in missing:
        completed = subprocess.run(
            ["git", "-c", "core.fsmonitor=false", "-C", str(PROJECT_ROOT), "show", f"{ORIGINAL_COMMIT}:{rel}"],
            capture_output=True, env=env, check=False,
        )
        if completed.returncode:
            error = completed.stderr.decode("utf-8", "replace").strip()
            raise RuntimeError(
                f"Pinned original source is unavailable offline: {rel}. "
                "Provide a local complete checkout/object database or set BTC_REPAIR_OLD_SOURCE. "
                f"No network fetch was attempted. Git: {error}"
            )
        payloads.append((path, completed.stdout))
    for path, payload in payloads:
        path.resolve().relative_to(ORIGINAL_SOURCE)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("xb") as handle:
                handle.write(payload)
        except FileExistsError:
            if path.read_bytes() != payload:
                raise RuntimeError(f"Refusing to overwrite an existing original-source file: {path}")
    return ORIGINAL_SOURCE


def auxiliary_file(name):
    """Use the old audit artifact or its byte-identical packaged lab fallback."""
    original = ORIGINAL_SOURCE / name
    return original if original.is_file() else LAB_ROOT / name


def raw_data_file(relative):
    """Resolve auxiliary minute data while honoring an explicit DATA override.

    With BTC_REPAIR_DATA set, only that directory's flat/repo-layout files are
    considered. Without an override, preserve the isolated lab's C:\\bot7 raw
    inputs and also support an ordinary checkout containing the ignored data.
    """
    rel = Path(relative)
    if _data_overridden:
        candidates = (DATA_DIR / rel, DATA_DIR / rel.name)
    else:
        candidates = (PROJECT_ROOT / rel, DATA_DIR / rel.name, _legacy_project / rel)
    return next((path for path in candidates if path.is_file()), candidates[0])
