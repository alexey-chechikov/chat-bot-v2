"""Cascade-followup per-variant JSONL journal. Mirrors range_hunter.journal API
but routed by variant (short_5btc, long_5btc_inverted, ...) instead of symbol.

Format per record:
{
  "signal_id": "cf_20260519_184612_short_5btc",
  "variant": "short_5btc",
  "ts_signal": "2026-05-19T18:46:12+00:00",
  "liq_side": "short",
  "threshold_btc": 5.0,
  "qty_btc": 6.12,
  "last_price": 81500.0,
  "trade_dir": "LONG",
  "entry": 81500.0,
  "tp1": 81769.0,
  "tp2": 82111.0,
  "stop": 81093.0,
  "size_usd": 5000.0,
  "predicted_4h_pct": 0.331,
  "edge_drift_flag": false,
  "by_exchange": {"bybit": {"long": 0, "short": 4.2}, "okx": {...}},

  "user_action": null,
  "placed_at": null,
  "decision_latency_sec": null,

  "outcome": null,
  "realized_4h_pct": null,
  "realized_12h_pct": null,
  "realized_at_ts": null,
  "exit_reason": null
}
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
JOURNAL_DIR = ROOT / "state"


def journal_path_for(variant: str) -> Path:
    return JOURNAL_DIR / f"cascade_followup_{variant}.jsonl"


def parse_signal_id(signal_id: str) -> Optional[str]:
    """Returns variant from signal_id (cf_YYYYMMDD_HHMMSS_<variant>), None if malformed."""
    parts = signal_id.split("_", 3)
    if len(parts) < 4 or parts[0] != "cf":
        return None
    return parts[3]


def _resolve_path(signal_id: str, path: Optional[Path]) -> Optional[Path]:
    if path is not None:
        return path
    variant = parse_signal_id(signal_id)
    if variant is None:
        return None
    return journal_path_for(variant)


def append_signal(record: dict, *, path: Optional[Path] = None) -> None:
    if path is None:
        path = _resolve_path(record.get("signal_id", ""), None)
    if path is None:
        logger.error("cascade_followup.journal.append_bad_signal_id sid=%s", record.get("signal_id"))
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        logger.exception("cascade_followup.journal.append_failed")


def read_all(*, path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:
        return rows
    return rows


def write_all(rows: list[dict], *, path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    except OSError:
        logger.exception("cascade_followup.journal.write_failed")


def update_record(signal_id: str, updates: dict, *, path: Optional[Path] = None) -> bool:
    path = _resolve_path(signal_id, path)
    if path is None:
        return False
    rows = read_all(path=path)
    found = False
    for r in rows:
        if r.get("signal_id") == signal_id:
            r.update(updates)
            found = True
            break
    if found:
        write_all(rows, path=path)
    return found


def mark_user_action(signal_id: str, action: str, *, now: Optional[datetime] = None,
                     path: Optional[Path] = None) -> bool:
    """action: 'placed' | 'skipped'. Auto-routes to per-variant journal."""
    if now is None:
        now = datetime.now(timezone.utc)
    path = _resolve_path(signal_id, path)
    if path is None:
        return False
    rows = read_all(path=path)
    for r in rows:
        if r.get("signal_id") == signal_id:
            r["user_action"] = action
            if action == "placed":
                r["placed_at"] = now.isoformat(timespec="seconds")
                try:
                    ts_sig = datetime.fromisoformat(r["ts_signal"])
                    r["decision_latency_sec"] = round((now - ts_sig).total_seconds(), 1)
                except (KeyError, ValueError):
                    pass
            elif action == "skipped":
                r["exit_reason"] = "user_skip"
            write_all(rows, path=path)
            return True
    return False


def pending_outcomes(*, path: Path) -> list[dict]:
    """Placed signals without realized_4h_pct yet."""
    rows = read_all(path=path)
    return [r for r in rows
            # 2026-07-29: было user_action == "placed" — оператор кнопки не
            # жмёт, поэтому из 269 сигналов исход записан у НУЛЯ, и эдж семьи
            # не мерился вообще. Теневой учёт: считаем ВСЕ (третий случай
            # того же бага — session_breakout, range_hunter, теперь этот).
            if r.get("realized_4h_pct") is None]


def summarize(*, path: Path, min_n: int = 5) -> dict:
    rows = read_all(path=path)
    if not rows:
        return {"total": 0}
    placed = [r for r in rows if r.get("user_action") == "placed"]
    skipped = [r for r in rows if r.get("user_action") == "skipped"]
    pending_dec = [r for r in rows if r.get("user_action") is None]
    closed = [r for r in placed if r.get("realized_4h_pct") is not None]
    wins_4h = [r for r in closed if (r.get("realized_4h_pct") or 0) > 0]
    realized_pcts = [float(r["realized_4h_pct"]) for r in closed if r.get("realized_4h_pct") is not None]
    latencies = [r["decision_latency_sec"] for r in placed if r.get("decision_latency_sec") is not None]
    avg_latency = round(sum(latencies) / len(latencies), 1) if latencies else None
    avg_realized = round(sum(realized_pcts) / len(realized_pcts), 4) if realized_pcts else None
    return {
        "total": len(rows),
        "pending_decision": len(pending_dec),
        "placed": len(placed),
        "skipped": len(skipped),
        "closed": len(closed),
        "wr_4h_pct": round(100 * len(wins_4h) / len(closed), 1) if closed else 0.0,
        "avg_realized_4h_pct": avg_realized,
        "avg_decision_latency_sec": avg_latency,
        "sufficient_sample": len(closed) >= min_n,
    }
