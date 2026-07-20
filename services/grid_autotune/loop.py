"""Grid Autotune — авто-расширение сетки при резком движении против ноги.

Запрос оператора 2026-07-20: «я не у ПК или ночь — смысл мне от сообщений
"РАСШИРИТЬ step/target"? Делай сам: +30% шаг и таргет при резком движении».

Механика (всё доказано живьём ранее):
- триггер: drift Stage >= 2 из alt_guard (state/alt_guard_state.json
  drift_last — лестница Win, валидирована 10.06) + мешок из снапшотов
  трекера. Никаких направленных прогнозов — только реакция на факт.
- действие: gs и gap.tog ×(1+widen_pct/100) через set_params на ЖИВОМ
  боте (без рестарта — доказано 10.06; extra_raw passthrough закрывает
  урок 2026-05-17 с потерей `in`-блока).
- откат: когда drift снят (stage 0) И мешок восстановился — возвращаем
  ИСХОДНЫЕ параметры (сетка не остаётся широкой навсегда).
- TG-пинг сообщает о СДЕЛАННОМ (событийное действие с деньгами, не совет).

Безопасность (паттерн order_harvester):
- работает ТОЛЬКО по ботам из state/grid_autotune_config.json;
- otc-гард (урок 2026-05-17), verify-после-записи (re-read params +
  статус Active), rollback при неудачной верификации;
- freeze-файл state/grid_autotune_frozen.json = полная остановка + CRITICAL TG;
- лимиты: max эпизодов/день/бот, мин-гэп между эпизодами;
- 1 логин на процесс (урок WAF 2026-07-08).
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "state" / "grid_autotune_config.json"
ACTIVE_PATH = ROOT / "state" / "grid_autotune_active.json"
JOURNAL_PATH = ROOT / "state" / "grid_autotune_journal.jsonl"
FROZEN_PATH = ROOT / "state" / "grid_autotune_frozen.json"
ALT_GUARD_STATE = ROOT / "state" / "alt_guard_state.json"
SNAPSHOTS_CSV = ROOT / "ginarea_live" / "snapshots.csv"

POLL_INTERVAL_SEC = 60
STATUS_ACTIVE = 2
_SNAP_TAIL_BYTES = 2_000_000  # ~13 мин снапшотов всех ботов — хватает с запасом

DEFAULT_CONFIG = {
    # безопасный фолбэк: битый/пропавший конфиг = сервис молчит
    "enabled": False,
    "widen_pct": 30,
    "trigger_stage": 2,
    "restore_bag_usd": -20.0,
    "max_episodes_per_day_per_bot": 2,
    "min_gap_between_episodes_sec": 7200,
    "bots": {},
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _journal(rec: dict) -> None:
    rec.setdefault("ts", _now())
    try:
        with JOURNAL_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        logger.exception("grid_autotune.journal_failed")


def load_config() -> dict:
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return dict(DEFAULT_CONFIG)
    except Exception:
        logger.exception("grid_autotune.config_read_failed — молчу")
        return dict(DEFAULT_CONFIG)
    out = dict(DEFAULT_CONFIG)
    out.update(cfg)
    return out


def is_frozen() -> bool:
    return FROZEN_PATH.exists()


def freeze(reason: str, detail: dict | None = None) -> None:
    try:
        FROZEN_PATH.write_text(json.dumps(
            {"ts": _now(), "reason": reason, "detail": detail or {}},
            ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        logger.exception("grid_autotune.freeze_write_failed")
    _journal({"event": "FROZEN", "reason": reason, "detail": detail or {}})


def _read_active() -> dict:
    try:
        return json.loads(ACTIVE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_active(d: dict) -> None:
    try:
        ACTIVE_PATH.write_text(json.dumps(d, ensure_ascii=False, indent=2),
                               encoding="utf-8")
    except OSError:
        logger.exception("grid_autotune.active_write_failed")


def read_drift_stages(path: Path = ALT_GUARD_STATE) -> dict[str, int]:
    """{bot_id: текущая drift-стадия} из persist-стейта alt_guard."""
    try:
        st = json.loads(path.read_text(encoding="utf-8"))
        return {bid: int(rec.get("stage", 0))
                for bid, rec in (st.get("drift_last") or {}).items()}
    except Exception:
        return {}


def read_bags(path: Path = SNAPSHOTS_CSV) -> dict[str, dict]:
    """{bot_id: {bag, status}} из хвоста snapshots.csv (последняя строка бота).

    Колонки: ts,bot_id,name,alias,status,position,profit,current_profit,..."""
    out: dict[str, dict] = {}
    try:
        with path.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - _SNAP_TAIL_BYTES))
            chunk = f.read().decode("utf-8", errors="replace")
    except OSError:
        logger.exception("grid_autotune.snapshots_read_failed")
        return out
    for ln in chunk.splitlines()[1:]:
        parts = ln.split(",")
        if len(parts) < 8:
            continue
        try:
            bid = str(int(float(parts[1])))
            status = int(float(parts[4]))
            bag = float(parts[7]) - float(parts[6])
        except (ValueError, IndexError):
            continue
        out[bid] = {"bag": bag, "status": status}  # последняя строка бота победит
    return out


def _episodes_today(bot_id: str, today: str) -> int:
    try:
        n = 0
        for ln in JOURNAL_PATH.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(ln)
            except json.JSONDecodeError:
                continue
            if r.get("event") == "APPLIED" and r.get("bot_id") == bot_id \
                    and str(r.get("ts", "")).startswith(today):
                n += 1
        return n
    except OSError:
        return 0


def _otc_safe(params) -> bool:
    return not ((params.extra_raw or {}).get("in") or {}).get("otc")


def _set_and_verify(api, bot_id: str, params, want_gs: float,
                    want_tog: float) -> bool:
    """set_params → re-read → значения совпали, p=true, бот Active."""
    api.set_params(int(bot_id), params)
    back = api.get_params(int(bot_id))
    if back.gs is None or back.gap.tog is None:
        return False
    ok = (abs(back.gs - want_gs) < 1e-9 and abs(back.gap.tog - want_tog) < 1e-9
          and bool(back.p))
    try:
        ok = ok and int(api.get_bot(int(bot_id)).status) == STATUS_ACTIVE
    except Exception:
        return False
    return ok


def apply_widen(api, bot_id: str, alias: str, factor: float, stage: int,
                bag: float, send_fn=None) -> bool:
    params = api.get_params(int(bot_id))
    if not _otc_safe(params):
        freeze("otc_guard: in.otc у бота — set_params опасен", {"bot_id": bot_id})
        if send_fn:
            send_fn(f"⚙️⛔️ Autotune ЗАМОРОЖЕН: у {alias} появился in.otc. "
                    "Удали state/grid_autotune_frozen.json после разбора.")
        return False
    if params.gs is None or params.gap.tog is None:
        _journal({"event": "SKIP_NO_PARAMS", "bot_id": bot_id, "alias": alias})
        return False

    orig = {"gs": params.gs, "tog": params.gap.tog}
    new_gs = round(params.gs * factor, 4)
    new_tog = round(params.gap.tog * factor, 4)
    params.gs, params.gap.tog = new_gs, new_tog

    base = {"bot_id": bot_id, "alias": alias, "orig": orig,
            "gs": new_gs, "tog": new_tog, "stage": stage, "bag": round(bag, 1)}
    try:
        if not _set_and_verify(api, bot_id, params, new_gs, new_tog):
            raise RuntimeError("verify failed")
    except Exception as e:
        # откат на исходные и стоп-кран
        try:
            params.gs, params.gap.tog = orig["gs"], orig["tog"]
            api.set_params(int(bot_id), params)
        except Exception:
            logger.exception("grid_autotune.rollback_failed bot=%s", bot_id)
        freeze(f"apply_verify_failed: {e}", base)
        if send_fn:
            send_fn(f"⚙️🚨 КРИТИЧНО {alias}: расширение сетки НЕ прошло "
                    f"верификацию ({e}) — откатил на gs={orig['gs']} "
                    f"tog={orig['tog']}, ПРОВЕРЬ бота в GinArea. "
                    "Autotune заморожен.")
        _journal({"event": "APPLY_FAILED", **base, "error": str(e)[:200]})
        return False

    active = _read_active()
    active[bot_id] = {"orig": orig, "applied_ts": _now(),
                      "widen_pct": round((factor - 1) * 100)}
    _write_active(active)
    _journal({"event": "APPLIED", **base})
    if send_fn:
        send_fn(f"⚙️ АВТОШИРЕНИЕ {alias}: drift Stage {stage}, мешок {bag:+,.0f}$ "
                f"→ сделал gs {orig['gs']}→{new_gs}, target {orig['tog']}→{new_tog} "
                f"(+{round((factor - 1) * 100)}%). Бот работает, верну при "
                "восстановлении мешка.")
    return True


def restore_params(api, bot_id: str, alias: str, rec: dict, bag: float,
                   send_fn=None) -> bool:
    params = api.get_params(int(bot_id))
    orig = rec["orig"]
    cur = {"gs": params.gs, "tog": params.gap.tog}
    params.gs, params.gap.tog = orig["gs"], orig["tog"]
    base = {"bot_id": bot_id, "alias": alias, "from": cur, "to": orig,
            "bag": round(bag, 1)}
    try:
        if not _set_and_verify(api, bot_id, params, orig["gs"], orig["tog"]):
            raise RuntimeError("verify failed")
    except Exception as e:
        freeze(f"restore_verify_failed: {e}", base)
        if send_fn:
            send_fn(f"⚙️🚨 КРИТИЧНО {alias}: откат параметров не прошёл "
                    f"верификацию ({e}) — бот может остаться с широкой сеткой "
                    f"(gs={cur['gs']}). Проверь в GinArea. Autotune заморожен.")
        _journal({"event": "RESTORE_FAILED", **base, "error": str(e)[:200]})
        return False

    active = _read_active()
    active.pop(bot_id, None)
    _write_active(active)
    _journal({"event": "RESTORED", **base})
    if send_fn:
        send_fn(f"↩️ {alias}: мешок восстановился ({bag:+,.0f}$) → вернул "
                f"gs {cur['gs']}→{orig['gs']}, target {cur['tog']}→{orig['tog']}.")
    return True


def tick(send_fn=None, api=None, *, drift: dict | None = None,
         bags: dict | None = None) -> int:
    """Один проход. Возвращает число применённых действий (widen+restore)."""
    if is_frozen():
        return 0
    cfg = load_config()
    if not cfg.get("enabled"):
        return 0
    bots = cfg.get("bots") or {}
    if not bots:
        return 0

    if drift is None:
        drift = read_drift_stages()
    if bags is None:
        bags = read_bags()

    active = _read_active()
    factor = 1.0 + float(cfg.get("widen_pct", 30)) / 100.0
    trigger_stage = int(cfg.get("trigger_stage", 2))
    restore_bag = float(cfg.get("restore_bag_usd", -20.0))
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    actions = 0

    for bot_id, bcfg in bots.items():
        alias = bcfg.get("alias", bot_id)
        snap = bags.get(bot_id)
        if snap is None:
            continue
        stage = drift.get(bot_id, 0)

        if api is None:
            api = _cached_api()
            if api is None:
                return actions

        if bot_id in active:
            # эпизод открыт → ждём восстановления
            if stage == 0 and snap["bag"] >= restore_bag \
                    and snap["status"] == STATUS_ACTIVE:
                if restore_params(api, bot_id, alias, active[bot_id],
                                  snap["bag"], send_fn=send_fn):
                    actions += 1
            continue

        # эпизод не открыт → ждём триггера
        if stage < trigger_stage or snap["status"] != STATUS_ACTIVE:
            continue
        if _episodes_today(bot_id, today) >= int(
                cfg.get("max_episodes_per_day_per_bot", 2)):
            continue
        last = _last_episode_mono.get(bot_id)
        gap = float(cfg.get("min_gap_between_episodes_sec", 7200))
        if last is not None and (time.monotonic() - last) < gap:
            continue

        if apply_widen(api, bot_id, alias, factor, stage, snap["bag"],
                       send_fn=send_fn):
            actions += 1
        _last_episode_mono[bot_id] = time.monotonic()
    return actions


_last_episode_mono: dict[str, float] = {}
_api_cache: list = []


def _cached_api():
    """1 логин на процесс (урок WAF 2026-07-08); клиент сам ре-логинится на 401."""
    if _api_cache:
        return _api_cache[0]
    from services.short_bots_guard.control import _build_api
    api, err = _build_api()
    if api is None:
        logger.warning("grid_autotune.api_unavailable: %s", err)
        return None
    _api_cache.append(api)
    return api


async def grid_autotune_loop(stop_event, *, send_fn=None,
                             interval_sec=POLL_INTERVAL_SEC):
    import asyncio
    logger.info("grid_autotune.start interval=%ds config=%s",
                interval_sec, CONFIG_PATH)
    while not stop_event.is_set():
        try:
            await asyncio.to_thread(tick, send_fn)
        except Exception:
            logger.exception("grid_autotune.tick_failed")
        try:
            await asyncio.wait_for(asyncio.shield(stop_event.wait()),
                                   timeout=interval_sec)
        except asyncio.TimeoutError:
            continue
    logger.info("grid_autotune.stopped")
