"""Universal paper-WR gate for ANY emitter.

Reads all three paper-outcome streams (paper_signals, paper_trades,
p15_paper_trades), maintains rolling WR per (source, signal_class)
bucket, and provides a one-liner decision the emitter can call before
emitting to TG:

    from services.common.paper_wr_gate import should_emit
    ok, reason = should_emit("cascade_alert", "LONG")
    if not ok:
        logger.info("paper_wr_gate.suppressed source=cascade_alert reason=%s", reason)
        continue   # do not send TG card

Default behaviour: ALLOW unless evidence of unhealthy bucket — WR <
UNHEALTHY_WR over the last ROLLING_N evaluated outcomes (n must reach
MIN_N before we have an opinion). This generalises the existing
cascade_followup streak-breaker (3 losses) and edge_drift_guard (n>=10)
into one source-agnostic policy.

State cached in state/paper_wr_gate.json with CACHE_TTL_SEC refresh so
each emit-check is O(1). Refresh happens lazily on the next call after
TTL expiry (no background loop required).

Wiring example — cascade_followup/loop.py before send_fn(card):
    ok, why = should_emit("cascade_followup", variant)
    if not ok:
        logger.info("paper_wr_gate.suppressed variant=%s %s", variant, why)
        continue
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
STATE_PATH = ROOT / "state" / "paper_wr_gate.json"
PSIG = ROOT / "state" / "paper_signals.jsonl"
PTRD = ROOT / "state" / "paper_trades.jsonl"
P15  = ROOT / "state" / "p15_paper_trades.jsonl"

# ─── Tuning ─────────────────────────────────────────────────────────────────
ROLLING_N = 30            # last N evaluated outcomes per bucket
MIN_N = 20                # below this, no opinion (always ALLOW)
UNHEALTHY_WR_PCT = 40.0   # WR strictly below → BLOCK
RECOVERY_WR_PCT = 50.0    # to re-enable after BLOCK, last MIN_N must be ≥ this
# 2026-05-29: WR alone misses a class of bleeders — high win-rate but negative
# net PnL (small TPs, large time-exit losses). cascade_alert::LONG ran WR 60%
# yet −$170 / PF 0.49 over n=55 and sailed through the WR-only gate. Add a
# PnL/expectancy block so a bucket that loses money is suppressed even if its
# WR looks fine. Generalises to any future +WR/−PnL emitter.
UNHEALTHY_PF = 0.9        # profit factor strictly below → BLOCK (with n>=MIN_N)
CACHE_TTL_SEC = 300       # 5 min — re-scan jsonl after this


# ─── jsonl readers ─────────────────────────────────────────────────────────
def _read_jsonl(path: Path) -> list:
    if not path.exists():
        return []
    out = []
    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return out


def _classify_psig(rows: list) -> dict:
    """paper_signals.jsonl → {(source, side): [(ts, pnl), ...]}."""
    by: dict = {}
    for r in rows:
        if r.get("outcome") is None or r.get("pnl_usd") is None:
            continue
        ts = r.get("exit_ts") or r.get("ts_signal") or ""
        key = (str(r.get("source", "?")), str(r.get("side", "?")))
        by.setdefault(key, []).append((ts, float(r["pnl_usd"])))
    return by


def _classify_ptrd(rows: list) -> dict:
    """paper_trades.jsonl closes → {("setup_detector", setup_type): [(ts, pnl)]}."""
    by: dict = {}
    for r in rows:
        if r.get("action") not in ("TP1", "TP2", "SL", "EXPIRE", "CLOSE"):
            continue
        if r.get("realized_pnl_usd") is None:
            continue
        key = ("setup_detector", str(r.get("setup_type", "?")))
        by.setdefault(key, []).append((r.get("ts", ""), float(r["realized_pnl_usd"])))
    return by


def _classify_p15(rows: list) -> dict:
    """p15_paper_trades.jsonl closes → {("p15", side): [(ts, pnl)]}."""
    by: dict = {}
    for r in rows:
        if r.get("action") not in ("CLOSE", "EXPIRE", "STOP"):
            continue
        if r.get("realized_pnl_usd") is None:
            continue
        key = ("p15", str(r.get("side", "?")))
        by.setdefault(key, []).append((r.get("ts", ""), float(r["realized_pnl_usd"])))
    return by


# ─── State computation ─────────────────────────────────────────────────────
def _compute_state(*, now: Optional[datetime] = None,
                   psig_path: Optional[Path] = None,
                   ptrd_path: Optional[Path] = None,
                   p15_path: Optional[Path] = None) -> dict:
    """Build the per-bucket WR map from the three jsonl streams.

    Paths default to module globals (PSIG/PTRD/P15) RESOLVED AT CALL TIME
    so test monkeypatches of those globals take effect.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    if psig_path is None:
        psig_path = PSIG
    if ptrd_path is None:
        ptrd_path = PTRD
    if p15_path is None:
        p15_path = P15
    by: dict = {}
    by.update(_classify_psig(_read_jsonl(psig_path)))
    by.update(_classify_ptrd(_read_jsonl(ptrd_path)))
    # p15 may collide source with psig; merge if same key
    for k, lst in _classify_p15(_read_jsonl(p15_path)).items():
        by.setdefault(k, []).extend(lst)

    buckets: dict = {}
    for (source, sclass), events in by.items():
        # chronological sort, take last ROLLING_N
        events.sort(key=lambda x: x[0])
        recent = events[-ROLLING_N:]
        n = len(recent)
        wins = sum(1 for _, p in recent if p > 0)
        wr = (100.0 * wins / n) if n else 0.0
        pnl_sum = sum(p for _, p in recent)
        gross_win = sum(p for _, p in recent if p > 0)
        gross_loss = -sum(p for _, p in recent if p < 0)
        pf = (gross_win / gross_loss) if gross_loss > 0 else (999.0 if gross_win > 0 else 0.0)
        if n < MIN_N:
            status = "small_sample"
            block = False
        elif wr < UNHEALTHY_WR_PCT:
            status = "unhealthy_wr"
            block = True
        elif pf < UNHEALTHY_PF:
            # +WR but money-losing (the cascade_alert::LONG class)
            status = "unhealthy_pnl"
            block = True
        else:
            status = "healthy"
            block = False
        buckets[f"{source}::{sclass}"] = {
            "source": source,
            "signal_class": sclass,
            "n": n,
            "wins": wins,
            "wr_pct": round(wr, 1),
            "pnl_sum": round(pnl_sum, 2),
            "pf": round(pf, 2),
            "status": status,
            "block_emit": block,
        }
    return {
        "computed_at": now.isoformat(timespec="seconds"),
        "rolling_n": ROLLING_N,
        "min_n": MIN_N,
        "unhealthy_wr_pct": UNHEALTHY_WR_PCT,
        "buckets": buckets,
    }


def _is_stale(state: dict, *, now: Optional[datetime] = None) -> bool:
    if not state:
        return True
    try:
        t = datetime.fromisoformat(state.get("computed_at", "").replace("Z", "+00:00"))
    except ValueError:
        return True
    if now is None:
        now = datetime.now(timezone.utc)
    return (now - t).total_seconds() > CACHE_TTL_SEC


def _load_state(*, now: Optional[datetime] = None) -> dict:
    """Read cached state; recompute lazily if stale."""
    state: dict = {}
    if STATE_PATH.exists():
        try:
            state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            state = {}
    if _is_stale(state, now=now):
        state = _compute_state(now=now)
        try:
            STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")
        except OSError:
            logger.exception("paper_wr_gate.state_write_failed")
    return state


# ─── Public API ────────────────────────────────────────────────────────────
def should_emit(source: str, signal_class: str, *,
                state: Optional[dict] = None) -> tuple[bool, str]:
    """Return (allow_emit, reason). Default ALLOW on unknown / small-sample
    buckets — only known unhealthy buckets get blocked. `state` may be
    injected for testing."""
    if state is None:
        state = _load_state()
    key = f"{source}::{signal_class}"
    b = (state.get("buckets") or {}).get(key)
    if not b:
        return True, f"no bucket data for {key} — allow"
    if b["status"] == "small_sample":
        return True, f"small sample n={b['n']} < {state.get('min_n', MIN_N)} — allow"
    if b["status"] == "unhealthy_wr":
        return False, (f"unhealthy bucket: WR={b['wr_pct']}% over last {b['n']} "
                       f"(< {state.get('unhealthy_wr_pct', UNHEALTHY_WR_PCT)}%)")
    if b["status"] == "unhealthy_pnl":
        return False, (f"unhealthy bucket: WR={b['wr_pct']}% OK but PF={b.get('pf')} "
                       f"PnL={b.get('pnl_sum')}$ over last {b['n']} (PF < {UNHEALTHY_PF})")
    return True, f"healthy WR={b['wr_pct']}% PF={b.get('pf')} n={b['n']}"


def gate_status() -> dict:
    """Full snapshot — useful for diagnostics dashboards / reports."""
    return _load_state()


def refresh_state() -> dict:
    """Force re-scan of jsonl files, write fresh state."""
    return _compute_state()
