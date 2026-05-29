"""Persistent state for auto_executor.

Three on-disk artifacts:

  state/auto_executor_state.json
      one open position (or none), daily counters, kill-state.
      written atomically every state mutation.

  state/auto_executor_outcomes.jsonl
      append-only log of closed trades — used by 7d-WR kill-switch and
      external audits.

  state/auto_executor_offset.json
      last-processed byte offset of state/setups.jsonl so we don't
      re-react to setups on restart.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field, asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
STATE_PATH = ROOT / "state" / "auto_executor_state.json"
OUTCOMES_PATH = ROOT / "state" / "auto_executor_outcomes.jsonl"
OFFSET_PATH = ROOT / "state" / "auto_executor_offset.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Position:
    setup_id: str
    setup_type: str
    pair: str  # bot7 internal pair name e.g. "BTCUSDT"
    bitmex_symbol: str  # actual BitMEX API symbol e.g. "XBTUSDT"
    side: str  # "long"
    entry_price: float
    sl_price: float
    tp1_price: float
    tp2_price: float
    expires_at: str
    qty_lots: int
    qty_btc: float
    nominal_usd: float
    cl_ord_id: str
    entry_order_id: Optional[str] = None
    status: str = "placed"  # placed | filled | closed | cancelled
    placed_at: str = field(default_factory=_now_iso)
    filled_at: Optional[str] = None
    avg_entry_price: Optional[float] = None
    entry_mode: str = "limit"  # limit | market_fallback (2026-05-26)
    closed_at: Optional[str] = None
    exit_reason: Optional[str] = None  # tp1 | sl | expire | manual | error
    avg_exit_price: Optional[float] = None
    realized_pnl_usd: Optional[float] = None

    def is_open(self) -> bool:
        return self.status in ("placed", "filled")


@dataclass
class KillState:
    daily_pnl_usd: float = 0.0
    daily_pnl_date: str = ""  # YYYY-MM-DD UTC
    consecutive_losses: int = 0
    freeze_until: Optional[str] = None  # ISO; if set + future, do not trade
    setup_frozen: dict[str, str] = field(default_factory=dict)  # setup_type → frozen_at_iso
    # 2026-05-29: manual unfreeze marker. setup_type → iso. The per-setup 7d-WR
    # killswitch ignores outcomes closed at/before this ts, so a manually
    # unfrozen setup gets a FRESH evaluation window instead of being re-frozen
    # immediately by the same losing streak that froze it.
    unfrozen_at: dict[str, str] = field(default_factory=dict)
    last_known_balance_usd: float = 0.0
    last_balance_check: Optional[str] = None


@dataclass
class State:
    open_positions: list[Position] = field(default_factory=list)
    kill: KillState = field(default_factory=KillState)
    schema_version: int = 2  # 2026-05-27: bumped from 1 — open_position → open_positions[]

    # Convenience accessor for legacy single-position code paths.
    @property
    def open_position(self) -> Optional[Position]:
        """Legacy alias — returns first open position or None. Use
        `open_positions` directly for multi-position management."""
        return self.open_positions[0] if self.open_positions else None

    @open_position.setter
    def open_position(self, value: Optional[Position]) -> None:
        """Legacy alias — setting to None clears; setting a Position replaces all."""
        self.open_positions = [value] if value is not None else []

    # ─── (de)serialization ───────────────────────────────────────────
    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "open_positions": [asdict(p) for p in self.open_positions],
            "kill": asdict(self.kill),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "State":
        # Backward-compat: schema v1 had single open_position; v2 has list.
        positions: list[Position] = []
        if "open_positions" in d and isinstance(d["open_positions"], list):
            for p in d["open_positions"]:
                if p:
                    positions.append(Position(**p))
        elif d.get("open_position"):
            positions.append(Position(**d["open_position"]))
        kill_raw = d.get("kill") or {}
        kill = KillState(
            daily_pnl_usd=float(kill_raw.get("daily_pnl_usd", 0.0)),
            daily_pnl_date=str(kill_raw.get("daily_pnl_date", "")),
            consecutive_losses=int(kill_raw.get("consecutive_losses", 0)),
            freeze_until=kill_raw.get("freeze_until"),
            setup_frozen=dict(kill_raw.get("setup_frozen", {})),
            unfrozen_at=dict(kill_raw.get("unfrozen_at", {})),
            last_known_balance_usd=float(kill_raw.get("last_known_balance_usd", 0.0)),
            last_balance_check=kill_raw.get("last_balance_check"),
        )
        return cls(open_positions=positions, kill=kill,
                   schema_version=int(d.get("schema_version", 2)))


def load_state(path: Path = STATE_PATH) -> State:
    if not path.exists():
        return State()
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return State.from_dict(d)
    except (OSError, ValueError, json.JSONDecodeError, TypeError):
        logger.exception("auto_executor.state_load_failed — starting fresh")
        return State()


def save_state(state: State, path: Path = STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state.to_dict(), ensure_ascii=False, indent=2),
                    encoding="utf-8")
    tmp.replace(path)


def append_outcome(position: Position, path: Path = OUTCOMES_PATH) -> None:
    """Append a closed-position record to outcomes.jsonl (one per line)."""
    if position.status != "closed":
        logger.warning("auto_executor.append_outcome.skip_not_closed id=%s status=%s",
                        position.setup_id, position.status)
        return
    rec = asdict(position)
    rec["recorded_at"] = _now_iso()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def load_offset(path: Path = OFFSET_PATH) -> int:
    if not path.exists():
        return 0
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return int(d.get("byte_offset", 0))
    except (OSError, ValueError, json.JSONDecodeError):
        return 0


def save_offset(offset: int, path: Path = OFFSET_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"byte_offset": int(offset),
                                "updated_at": _now_iso()}),
                    encoding="utf-8")
    tmp.replace(path)


def reset_daily_pnl_if_new_day(kill: KillState, now: Optional[datetime] = None) -> bool:
    """Rolls daily_pnl_usd to 0 if UTC date has changed. Returns True if rolled."""
    if now is None:
        now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    if kill.daily_pnl_date != today:
        kill.daily_pnl_usd = 0.0
        kill.daily_pnl_date = today
        return True
    return False
