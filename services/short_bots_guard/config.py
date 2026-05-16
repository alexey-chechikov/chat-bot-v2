"""Конфиг managed SHORT ботов в state/short_bots_managed.json.

Schema:
{
  "enabled": true,
  "dry_run": false,
  "managed_bots": [
    {"bot_id": "4729923198", "tier": "T1", "alias": "SHORT-T1"},
    {"bot_id": "6287583200", "tier": "T2", "alias": "SHORT-T2"},
    {"bot_id": "5736281160", "tier": "T3", "alias": "SHORT-T3"}
  ],
  "pause_triggers": {
    "cascade_short_5.0": {"affect_tiers": ["T1", "T2", "T3"], "pause_hours": 4},
    "cascade_short_2.0": {"affect_tiers": ["T1", "T2"], "pause_hours": 2}
  }
}
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "state" / "short_bots_managed.json"


@dataclass
class ManagedBot:
    bot_id: str
    tier: str
    alias: str


@dataclass
class PauseTrigger:
    name: str
    affect_tiers: list[str]
    pause_hours: float


@dataclass
class GuardConfig:
    enabled: bool
    dry_run: bool
    managed_bots: list[ManagedBot]
    triggers: dict[str, PauseTrigger]


DEFAULT_CONFIG = GuardConfig(
    enabled=True,
    dry_run=False,
    managed_bots=[
        ManagedBot(bot_id="4729923198", tier="T1", alias="SHORT-T1"),
        ManagedBot(bot_id="6287583200", tier="T2", alias="SHORT-T2"),
        ManagedBot(bot_id="5736281160", tier="T3", alias="SHORT-T3"),
    ],
    triggers={
        "cascade_short_5.0": PauseTrigger(
            name="cascade_short_5.0",
            affect_tiers=["T1", "T2", "T3"],
            pause_hours=4.0,
        ),
        "cascade_short_2.0": PauseTrigger(
            name="cascade_short_2.0",
            affect_tiers=["T1", "T2"],
            pause_hours=2.0,
        ),
    },
)


def load_config(path: Path = CONFIG_PATH) -> GuardConfig:
    """Read config from disk, create default if missing."""
    if not path.exists():
        save_config(DEFAULT_CONFIG, path=path)
        return DEFAULT_CONFIG
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.exception("short_bots_guard.config_read_failed")
        return DEFAULT_CONFIG

    bots = [
        ManagedBot(
            bot_id=str(b["bot_id"]),
            tier=str(b.get("tier", "?")),
            alias=str(b.get("alias", b["bot_id"])),
        )
        for b in data.get("managed_bots", [])
    ]
    triggers = {}
    for name, t in (data.get("pause_triggers", {}) or {}).items():
        triggers[name] = PauseTrigger(
            name=name,
            affect_tiers=list(t.get("affect_tiers", [])),
            pause_hours=float(t.get("pause_hours", 4.0)),
        )

    return GuardConfig(
        enabled=bool(data.get("enabled", True)),
        dry_run=bool(data.get("dry_run", False)),
        managed_bots=bots,
        triggers=triggers,
    )


def save_config(cfg: GuardConfig, *, path: Path = CONFIG_PATH) -> None:
    data = {
        "enabled": cfg.enabled,
        "dry_run": cfg.dry_run,
        "managed_bots": [
            {"bot_id": b.bot_id, "tier": b.tier, "alias": b.alias}
            for b in cfg.managed_bots
        ],
        "pause_triggers": {
            name: {"affect_tiers": t.affect_tiers, "pause_hours": t.pause_hours}
            for name, t in cfg.triggers.items()
        },
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        logger.exception("short_bots_guard.config_write_failed")


def load_managed_bots() -> list[ManagedBot]:
    return load_config().managed_bots
