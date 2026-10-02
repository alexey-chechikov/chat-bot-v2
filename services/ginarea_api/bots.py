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
# Абсолютный путь: относительный работал только из папки бота. Скрипт,
# запущенный из другой папки, видел пустой список — и гард молча пропускал всё.
_PORTFOLIO_PATH = Path(__file__).resolve().parents[2] / "state" / "portfolio.json"


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


# Штатные службы, которым оператор разрешил менять параметры живых ботов.
# grid_autotune — с 2026-07-20 («делай сам, я не у ПК»): расширяет gs и target
# при drift Stage>=2. Гард против него не направлен: он против случайной
# мутации боевого бота из разового скрипта или новой недоделанной логики.
# Разрешение выдаётся по вызывающему модулю, а не по id бота, — иначе
# приходится выбирать между «гард не защищает» и «штатная служба сломана».
# Список собран по ВСЕМ вызывающим защищённые методы (set_params, close_order,
# pause_bot, resume_bot), а не по одному. 17.08 я включил гард, перечислив
# только два модуля, и за час положил харвестер: 117 ошибок close_failed,
# ордера не закрывались. Правило: при добавлении нового вызывающего —
# сначала сюда, иначе служба молча падает.
_ALLOWED_MUTATORS = (
    "services.grid_autotune",      # шаг/таргет при drift (разрешено 20.07)
    "services.short_bots_guard",   # пауза/резюм через /stop и /start
    "services.order_harvester",    # фиксация плюсовых ордеров (close_order)
    "services.pump_freeze",        # заморозка на пампе
    "services.bot_brain",          # предложения движка
    "services.telegram_runtime",   # ручные команды оператора из TG
)


# Закрытие ВСЕЙ позиции — отдельный, более узкий список: это аварийный
# тормоз риск-контура, а не инструмент управления сеткой.
_CLOSE_ALLOWED = (
    "services.risk_guard",
    # 2026-08-31: хедж меняет размер только закрытием и переоткрытием —
    # set_params правит лишь СЛЕДУЮЩИЙ ордер, проверено на боте 5848117800.
    # Значит закрытие ему нужно штатно, а не как аварийный тормоз.
    "services.hedge_shadow",
)


def _caller_is_allowed(allowed: tuple[str, ...] = _ALLOWED_MUTATORS) -> bool:
    import inspect

    for frame in inspect.stack()[2:12]:
        mod = frame.frame.f_globals.get("__name__", "")
        if any(mod.startswith(p) for p in allowed):
            return True
    return False


def _assert_not_production(bot_id: int) -> None:
    if bot_id in _load_production_bot_ids() and not _caller_is_allowed():
        raise GinAreaProductionBotGuardError(
            f"Bot {bot_id} is in production set; mutation blocked. "
            f"Разрешённые службы: {', '.join(_ALLOWED_MUTATORS)}"
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
        """Pause a running bot via GinArea's proper stop API.

        Captured 2026-05-17 from operator DevTools:
          PUT https://ginarea.org/api/bots/{id}/stop
          Body: {} (empty JSON)
          → 200 OK; bot transitions ACTIVE → STOPPING → STOPPED/PAUSED.

        This is what GinArea UI calls when operator clicks ⏸ on Active bot.
        """
        return self.client.request(
            "PUT",
            f"/bots/{bot_id}/stop",
            json={},
        )

    def resume_bot(self, bot_id: int) -> dict:
        """Resume a paused/stopped/failed bot via GinArea's proper start API.

        Captured 2026-05-17 from operator DevTools:
          PUT https://ginarea.org/api/bots/{id}/start
          Body: {} (empty JSON)
          → 200 OK; bot transitions PAUSED/FAILED → STARTING → ACTIVE.

        Same endpoint UI calls when operator clicks ▶ play/restart.
        """
        return self.client.request(
            "PUT",
            f"/bots/{bot_id}/start",
            json={},
        )

    # ─── Orders (RE 2026-07-08 from ginarea.org JS bundle chunk-NVN532GA.js) ──
    # getOrders(e,i,n,a) → GET /bots/{id}/orders?pageSize=&pageNumber=&onlyOpened=
    # closeOrder(e,i)    → PUT /bots/{id}/close/{orderId}, body {}
    # close(e)           → PUT /bots/{id}/close, body {}  — ВСЯ позиция.
    #
    # 2026-08-27: обёрнут как close_position(). До этого дня метод намеренно
    # не оборачивали, «чтобы никто случайно не закрыл позицию целиком».
    # Именно этого и не хватило: 19-22.08 шесть шортовых сеток встретили рост
    # BTC +19.2% при плече 8.8x, автоматика умела только ОСТАНАВЛИВАТЬ ботов,
    # а остановленный бот держит позицию дальше — минус вырос с −$1 121 до
    # −$16 032, счёт ликвидирован. Замер по 4 независимым эпизодам за 4
    # Единственный чистый эпизод (19.08): мешок держался ниже порога 140
    # часов и ушёл с −$1 121 до −$13 842. Прежняя оценка «4 из 4» была
    # неверна — в неё попали старые битмексовые боты с мешком в BTC.
    #
    # Вызывать вправе ТОЛЬКО services.risk_guard — см. _CLOSE_ALLOWED.

    def get_orders(self, bot_id: int, *, page_size: int = 100,
                   page_number: int = 0, only_opened: bool = True) -> dict:
        """Список ордеров бота (вкладка «Ордера» в UI).

        Пагинация 0-BASED (проверено живьём 2026-07-18: pageNumber=1 — это
        ВТОРАЯ страница; с onlyOpened=true при <100 открытых она пуста и
        сервер отдаёт orders:null при ненулевом totalCount).

        У ОТКРЫТЫХ ордеров profit=null — UI считает профит на клиенте;
        серверного значения нет, считать самим по mark-цене.
        """
        return self.client.request(
            "GET",
            f"/bots/{bot_id}/orders",
            params={"pageSize": str(page_size), "pageNumber": str(page_number),
                    "onlyOpened": "true" if only_opened else "false"},
        )

    def close_position(self, bot_id: int) -> dict:
        """Закрыть ВСЮ позицию бота по рынку (кнопка «Закрыть» в UI).

        Необратимо. Фиксирует убыток или прибыль целиком.
        Разрешено только services.risk_guard: это аварийный тормоз, а не
        инструмент управления. Любой другой вызывающий получает отказ.
        """
        if not _caller_is_allowed(_CLOSE_ALLOWED):
            raise GinAreaProductionBotGuardError(
                f"close_position({bot_id}) запрещён: закрывать позицию вправе "
                f"только {', '.join(_CLOSE_ALLOWED)}"
            )
        logger.warning("ginarea.close_position bot=%s — ЗАКРЫТИЕ ПОЗИЦИИ",
                       bot_id)
        return self.client.request("PUT", f"/bots/{bot_id}/close", json={})

    def close_order(self, bot_id: int, order_id: str) -> dict:
        """Закрыть ОДИН ордер бота (кнопка ✕ в UI-таблице ордеров).

        То, что UI вызывает при закрытии отдельного плюсового ордера:
        рыночный выход именно этой части позиции, бот продолжает работать
        с остальной сеткой.
        """
        _assert_not_production(bot_id)
        return self.client.request(
            "PUT",
            f"/bots/{bot_id}/close/{order_id}",
            json={},
        )
