"""Paper signal journal — state/paper_signals.jsonl.

Per-record:
{
  "signal_id":     "ca_20260518_140000_LONG",
  "source":        "cascade_alert" | "spike_alert" | "grid_coord" | "market_intel" | "level_break",
  "ts_signal":     "2026-05-18T14:00:00+00:00",
  "side":          "LONG" | "SHORT",
  "entry":         80000.0,
  "stop":          79600.0,
  "tp":            80600.0,
  "size_usd":      1000.0,
  "hold_h":        4,
  "context":       "long_liq_5btc"  // free-text trigger description for grouping in reports

  // Filled by evaluator
  "outcome":       null | "tp_hit" | "sl_hit" | "timeout",
  "exit_ts":       null | ISO,
  "exit_price":    null | float,
  "pnl_usd":       null | float,        // net of 2× 0.075% taker fees
}
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

JOURNAL_PATH = Path("state/paper_signals.jsonl")
MARKET_1M_CSV = Path("market_live/market_1m.csv")
TAKER_FEE_PCT = 0.075  # BitMEX taker per side

# 2026-06-21 (Win-аудит): источники, убитые по СОБСТВЕННОМУ правилу отчёта
# «WR<40% ИЛИ PnL<−$50/нед → kill source entirely». level_break: WR 17–22% на
# 900+ сделках, −$830/нед = доказанный анти-эдж, флудил 100+/день. Перестаём
# писать paper (старые строки выпадут из rolling-окна). Детект LEVEL_BREAK для
# /levels и ROUTINE-канала живёт — убран только бесполезный paper-трекинг.
KILLED_SOURCES = frozenset({"level_break"})


def read_btc_last_price() -> Optional[float]:
    """Best-effort: вернуть последний close из market_live/market_1m.csv.
    None если файл недоступен или формат сломан."""
    if not MARKET_1M_CSV.exists():
        return None
    try:
        with MARKET_1M_CSV.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 4096))
            tail = f.read().decode("utf-8", errors="ignore")
        lines = [l for l in tail.splitlines() if l.strip()]
        if len(lines) < 2:
            return None
        # market_1m.csv: ts_utc,open,high,low,close,volume,...
        last_row = lines[-1].split(",")
        return float(last_row[4])
    except (OSError, IndexError, ValueError):
        return None


def record_paper_signal(*, source: str, side: str, entry: float,
                         stop_pct: float, tp_pct: float, hold_h: int,
                         context: str = "",
                         size_usd: float = 1000.0,
                         symbol: str = "BTCUSDT",
                         now: Optional[datetime] = None,
                         path: Path = JOURNAL_PATH) -> str:
    """Append a paper-trade hypothetical. Returns signal_id.

    side: 'LONG' or 'SHORT'.
    stop_pct, tp_pct: signed percentages relative to entry
      e.g. LONG: stop_pct=-0.5 → stop = entry × 0.995, tp_pct=+0.75 → tp = entry × 1.0075
    symbol: instrument the entry/stop/tp refer to (default BTCUSDT). The evaluator
      resolves each signal against ITS OWN symbol's 1m bars (2026-05-29 — needed
      for alt TV signals & alt_decorr; legacy rows w/o symbol → BTCUSDT).
    """
    if source in KILLED_SOURCES:
        logger.info("paper_signal.killed_source_skip source=%s — анти-эдж, не пишем", source)
        return ""
    if now is None:
        now = datetime.now(timezone.utc)
    side_u = side.upper()
    sign = 1 if side_u == "LONG" else -1
    stop = entry * (1.0 + sign * stop_pct / 100.0)
    tp = entry * (1.0 + sign * tp_pct / 100.0)
    signal_id = f"{_source_prefix(source)}_{now.strftime('%Y%m%d_%H%M%S')}_{side_u}"
    record = {
        "signal_id": signal_id,
        "source": source,
        "symbol": symbol.upper(),
        "ts_signal": now.isoformat(timespec="seconds"),
        "side": side_u,
        "entry": round(entry, 2),
        "stop": round(stop, 2),
        "tp": round(tp, 2),
        "size_usd": size_usd,
        "hold_h": hold_h,
        "context": context,
        "outcome": None,
        "exit_ts": None,
        "exit_price": None,
        "pnl_usd": None,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        logger.exception("paper_signal.append_failed source=%s", source)
    return signal_id


def _source_prefix(source: str) -> str:
    return {
        "cascade_alert": "ca",
        "spike_alert": "sp",
        "grid_coord": "gc",
        "market_intel": "mi",
        "level_break": "lb",
    }.get(source, source[:3])


def read_all(*, path: Path = JOURNAL_PATH) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
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
        logger.exception("paper_signal.write_failed")


def update_outcome(signal_id: str, outcome: str, exit_ts: datetime,
                   exit_price: float, pnl_usd: float, *,
                   path: Path = JOURNAL_PATH) -> bool:
    rows = read_all(path=path)
    found = False
    for r in rows:
        if r.get("signal_id") == signal_id:
            r["outcome"] = outcome
            r["exit_ts"] = exit_ts.isoformat(timespec="seconds")
            r["exit_price"] = round(float(exit_price), 2)
            r["pnl_usd"] = round(float(pnl_usd), 2)
            found = True
            break
    if found:
        write_all(rows, path=path)
    return found


def pending_signals(*, path: Path = JOURNAL_PATH) -> list[dict]:
    return [r for r in read_all(path=path) if r.get("outcome") is None]
