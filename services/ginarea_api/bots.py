from __future__ import annotations

import json
import logging
from pathlib import Path

from .client import GinAreaClient
from .exceptions import GinAreaProductionBotGuardError
from .models import Bot, BotStat, DefaultGridParams

logger = logging.getLogger(__name__)

PRODUCTION_BOT_IDS: frozenset[int] = frozenset()
_PRODUCTION_LOADED = False
_PORTFOLIO_PATH = Path("state/portfolio.json")


def _load_production_bot_ids() -> frozenset[int]:
    """Read state/portfolio.json once and cache the production bot id set."""
    global PRODUCTION_BOT_IDS, _PRODUCTION_LOADED
    if _PRODUCTION_LOADED:
        return PRODUCTION_BOT_IDS

    if not _PORTFOLIO_PATH.exists():
        logger.warning("state/portfolio.json missing; production bot guard is empty")
        PRODUCTION_BOT_IDS = frozenset()
        _PRODUCTION_LOADED = True
        return PRODUCTION_BOT_IDS

    try:
        payload = json.loads(_PORTFOLIO_PATH.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("failed to read state/portfolio.json; production bot guard is empty")
        PRODUCTION_BOT_IDS = frozenset()
        _PRODUCTION_LOADED = True
        return PRODUCTION_BOT_IDS

    if isinstance(payload.get("bots"), list):
        ids = {
            int(item["id"])
            for item in payload["bots"]
            if isinstance(item, dict) and item.get("active") and item.get("id") is not None
        }
    else:
        ids = {
            int(item)
            for item in list(payload.get("active_bot_ids") or [])
        }

    PRODUCTION_BOT_IDS = frozenset(ids)
    _PRODUCTION_LOADED = True
    return PRODUCTION_BOT_IDS


def _assert_not_production(bot_id: int) -> None:
    if bot_id in _load_production_bot_ids():
        raise GinAreaProductionBotGuardError(
            f"Bot {bot_id} is in production set; mutation blocked."
        )


class BotsAPI:
    def __init__(self, client: GinAreaClient) -> None:
        self.client = client

    def list_bots(self) -> list[Bot]:
        data = self.client.request("GET", "/bots")
        return [Bot.from_dict(item) for item in data]  # type: ignore[arg-type]

    def get_bot(self, bot_id: int) -> Bot:
        data = self.client.request("GET", f"/bots/{bot_id}")
        return Bot.from_dict(data)  # type: ignore[arg-type]

    def get_params(self, bot_id: int) -> DefaultGridParams:
        data = self.client.request("GET", f"/bots/{bot_id}/params")
        return DefaultGridParams.from_dict(data)  # type: ignore[arg-type]

    def get_stat(self, bot_id: int) -> BotStat:
        data = self.client.request("GET", f"/bots/{bot_id}/stat")
        return BotStat.from_dict(data)  # type: ignore[arg-type]

    def get_stat_history(
        self,
        bot_id: int,
        *,
        interval: str = "60m",
        max_count: int = 100,
    ) -> list[BotStat]:
        data = self.client.request(
            "GET",
            f"/bots/{bot_id}/stat/history",
            params={"interval": interval, "maxCount": str(max_count)},
        )
        return [BotStat.from_dict(item) for item in data]  # type: ignore[arg-type]

    def set_params(self, bot_id: int, params: DefaultGridParams) -> DefaultGridParams:
        _assert_not_production(bot_id)
        data = self.client.request(
            "PUT",
            f"/bots/{bot_id}/params",
            json=params.to_dict(),
        )
        return DefaultGridParams.from_dict(data)  # type: ignore[arg-type]

    # ─── Pause/Resume stubs ─────────────────────────────────────────────────
    # 2026-05-17: ginarea_api currently has NO working pause/resume.
    # Confirmed by scripts/_diag_tb_pause_strategies.py — set_params(p=false)
    # transitions bot to status=FAILED(10), not PAUSED(3). It's edit-config,
    # not pause control.
    #
    # Proper endpoint TBD — needs DevTools capture from GinArea UI showing
    # what HTTP request fires when operator clicks pause/resume in browser.
    # When known, implement here following the established pattern:
    #   data = self.client.request("POST", f"/bots/{bot_id}/pause")
    #   return ...
    #
    # Callers must check NotImplementedError to fail gracefully rather than
    # falling back to broken set_params logic.

    def pause_bot(self, bot_id: int) -> dict:
        """Pause a running bot via GinArea's proper pause API.

        STATUS: ENDPOINT NOT YET CAPTURED — need DevTools snapshot of UI
        pause click. start_bot endpoint was captured 2026-05-17 as
        `PUT /api/bots/{id}/start`, so pause likely follows similar pattern
        — try `/pause` or `/stop`.

        DO NOT fall back to set_params(p=False) — that breaks the bot
        (status → FAILED, confirmed 2026-05-17 TB diagnostic).
        """
        raise NotImplementedError(
            f"pause_bot({bot_id}): pause endpoint not yet captured via "
            "DevTools. Operator must click ⏸ in GinArea UI directly. "
            "See docs/api/GINAREA_API_NOTES.md and "
            "project_ginarea_pause_broken.md."
        )

    def resume_bot(self, bot_id: int) -> dict:
        """Resume a paused bot via GinArea's proper start API.

        Captured 2026-05-17 from operator DevTools: PUT /api/bots/{id}/start
        with empty JSON body `{}`. Returns 200 on success.

        Note: this is the same endpoint UI calls when operator clicks ▶
        Restart on a Failed bot — recovers from FAILED state.
        """
        return self.client.request(
            "PUT",
            f"/bots/{bot_id}/start",
            json={},
        )
