"""Range Hunter journal — state/range_hunter_signals.jsonl.

Format per record (поля по запросу мак-колеги):
{
  "signal_id": "rh_20260514_213045",
  "ts_signal": "2026-05-14T21:30:45+00:00",
  "mid_signal": 81500.0,
  "buy_level": 81418.5,
  "sell_level": 81581.5,
  "stop_loss_pct": 0.20,
  "size_usd": 10000.0,
  "size_btc": 0.1227,
  "contract": "XBTUSDT",
  "hold_h": 6,

  // Filter values at signal time
  "range_4h_pct": 0.43,
  "atr_pct": 0.07,
  "trend_pct_per_h": 0.04,

  // User decision (inline button)
  "placed_at": null,  // ISO when user clicked ✅ Placed (or null)
  "user_action": null,  // "placed" | "skipped" | null (no click yet)
  "decision_latency_sec": null,  // placed_at - ts_signal

  // Fill outcomes (filled by outcome_tracker)
  "buy_fill_ts": null,
  "sell_fill_ts": null,
  "exit_ts": null,
  "exit_reason": null,  // pair_win | buy_stopped | sell_stopped | buy_timeout | sell_timeout | no_fill | user_skip
  "legs_filled": null,  // 0 | 1 | 2
  "pnl_usd": null
}
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

JOURNAL_PATH = Path("state/range_hunter_signals.jsonl")


def journal_path_for(symbol: str, variant: str = "1m") -> Path:
    """Per-(symbol, variant) журнал. BTCUSDT 1m → default path (backward compat),
    остальные → state/range_hunter_signals_<SYMBOL>[_<variant>].jsonl."""
    sym = symbol.upper()
    if sym == "BTCUSDT" and variant == "1m":
        return JOURNAL_PATH
    base = f"range_hunter_signals_{sym}"
    if variant != "1m":
        base += f"_{variant}"
    return JOURNAL_PATH.parent / f"{base}.jsonl"


def signal_id_from_ts(ts: datetime, symbol: str = "BTCUSDT", variant: str = "1m") -> str:
    sym = symbol.upper()
    parts = ["rh_" + ts.strftime("%Y%m%d_%H%M%S")]
    if sym != "BTCUSDT":
        parts.append(sym)
    if variant != "1m":
        parts.append(variant)
    return "_".join(parts)


def parse_signal_id(signal_id: str) -> tuple[str, str]:
    """Reverse of signal_id_from_ts → (symbol, variant). Defaults BTCUSDT/1m."""
    parts = signal_id.split("_")
    if len(parts) < 3 or parts[0] != "rh":
        return ("BTCUSDT", "1m")
    symbol = "BTCUSDT"
    variant = "1m"
    for token in parts[3:]:
        up = token.upper()
        if up.endswith("USDT") or up.endswith("USD"):
            symbol = up
        else:
            variant = token
    return (symbol, variant)


def _resolve_path(signal_id: str, path: Optional[Path]) -> Path:
    """If path provided — use it; otherwise derive from signal_id."""
    if path is not None:
        return path
    symbol, variant = parse_signal_id(signal_id)
    return journal_path_for(symbol, variant)


def append_signal(record: dict, *, path: Path = JOURNAL_PATH) -> None:
    """Append a new signal row to journal."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        logger.exception("range_hunter.journal.append_failed")


def read_all(*, path: Path = JOURNAL_PATH) -> list[dict]:
    if not path.exists():
        return []
    out = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:
        return out
    return out


def write_all(rows: list[dict], *, path: Path = JOURNAL_PATH) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    except OSError:
        logger.exception("range_hunter.journal.write_failed")


def update_record(signal_id: str, updates: dict, *, path: Path = JOURNAL_PATH) -> bool:
    """In-place update of a record by signal_id. Returns True if found."""
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
    """Mark user's choice from inline button.

    action: "placed" (user поставил обе лимитки) | "skipped" (пропустил)

    If path is None, derived from signal_id via parse_signal_id() — so multi-asset
    TG callbacks route to the correct per-symbol journal.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    path = _resolve_path(signal_id, path)
    rows = read_all(path=path)
    for r in rows:
        if r.get("signal_id") == signal_id:
            r["user_action"] = action
            if action == "placed":
                r["placed_at"] = now.isoformat(timespec="seconds")
                # decision latency
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


def mark_hedge_action(signal_id: str, action: str, *,
                       now: Optional[datetime] = None,
                       path: Optional[Path] = None) -> bool:
    """Mark hedge advisory choice. action: 'hedged' | 'closed' | 'hold'.

    If path is None, derived from signal_id (multi-asset auto-routing).
    """
    if now is None:
        now = datetime.now(timezone.utc)
    path = _resolve_path(signal_id, path)
    rows = read_all(path=path)
    for r in rows:
        if r.get("signal_id") == signal_id:
            r["hedge_action"] = action
            r["hedge_action_ts"] = now.isoformat(timespec="seconds")
            write_all(rows, path=path)
            return True
    return False


def pending_signals(*, path: Path = JOURNAL_PATH) -> list[dict]:
    """Signals which user PLACED but outcome not yet evaluated."""
    rows = read_all(path=path)
    return [r for r in rows if r.get("user_action") == "placed" and r.get("exit_reason") is None]


def summarize(*, path: Path = JOURNAL_PATH, min_n: int = 5) -> dict:
    """Aggregate stats for live tracking."""
    rows = read_all(path=path)
    if not rows:
        return {"total": 0}
    placed = [r for r in rows if r.get("user_action") == "placed"]
    skipped = [r for r in rows if r.get("user_action") == "skipped"]
    pending = [r for r in rows if r.get("user_action") is None]

    closed = [r for r in placed if r.get("exit_reason") is not None]
    pair_win = [r for r in closed if r.get("exit_reason") == "pair_win"]
    pnls = [float(r.get("pnl_usd") or 0) for r in closed]

    by_outcome: dict[str, int] = {}
    for r in closed:
        reason = r.get("exit_reason", "unknown")
        by_outcome[reason] = by_outcome.get(reason, 0) + 1

    # Legs-fill statistics — главная метрика для оценки реального fill rate
    legs_2 = sum(1 for r in closed if r.get("legs_filled") == 2)
    legs_1 = sum(1 for r in closed if r.get("legs_filled") == 1)
    legs_0 = sum(1 for r in closed if r.get("legs_filled") == 0)
    total_legs_placed = 2 * len(closed)
    total_legs_filled = 2 * legs_2 + legs_1
    empirical_fill_rate = total_legs_filled / total_legs_placed if total_legs_placed else 0.0

    avg_latency = None
    latencies = [r["decision_latency_sec"] for r in placed if r.get("decision_latency_sec") is not None]
    if latencies:
        avg_latency = round(sum(latencies) / len(latencies), 1)

    return {
        "total": len(rows),
        "pending_decision": len(pending),
        "placed": len(placed),
        "skipped": len(skipped),
        "closed": len(closed),
        "pair_win_pct": round(100 * len(pair_win) / len(closed), 1) if closed else 0.0,
        "by_outcome": by_outcome,
        "legs_filled_2": legs_2,
        "legs_filled_1": legs_1,
        "legs_filled_0": legs_0,
        "empirical_fill_rate": round(empirical_fill_rate, 3),
        "total_pnl_usd": round(sum(pnls), 2),
        "avg_decision_latency_sec": avg_latency,
        "sufficient_sample": len(closed) >= min_n,
    }
