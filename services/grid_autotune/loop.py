"""Grid Autotune — авто-расширение сетки при резком движении против ноги.

Запрос оператора 2026-07-20: «я не у ПК или ночь — смысл мне от сообщений
"РАСШИРИТЬ step/target"? Делай сам: +30% шаг и таргет при резком движении».

Механика (всё доказано живьём ранее):
- триггеры (per-bot "trigger" в конфиге):
  * "drift" (DYN-боты): drift Stage >= 2 из alt_guard
    (state/alt_guard_state.json drift_last — лестница Win, 10.06);
  * "btc_move_1h" (BTC-LONG 5317457827, оператор 2026-07-20: «спокойно —
    ордер до $300; сильное движение — ордер $100, шаг/таргет шире»):
    |1ч-ход BTC| >= move_pct_1h из живых свечей market_1m.csv.
  Никаких направленных прогнозов — только реакция на факт движения.
- действие: gs и gap.tog ×(1+widen_pct/100); опционально q.maxQ →
  episode_maxQ. Через set_params на ЖИВОМ боте (без рестарта — доказано
  10.06; extra_raw passthrough закрывает урок 2026-05-17 с потерей `in`).
- откат: успокоилось (drift 0 / BTC тихий calm_hours) И мешок
  восстановился — возвращаем исходные gs/tog и quiet_maxQ.
- otc-боты (otc_expected=true): правки параметров НЕ сбрасывают otcPassed
  (история 16-20.07: 8 ручных правок maxQ пережиты), но после КАЖДОЙ
  записи это проверяется — расхождение = rollback + freeze.
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

import dataclasses
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
BTC_1M_CSV = ROOT / "market_live" / "market_1m.csv"

POLL_INTERVAL_SEC = 60
STATUS_ACTIVE = 2
_SNAP_TAIL_BYTES = 2_000_000  # ~13 мин снапшотов всех ботов — хватает с запасом
_BTC_STALE_MIN = 10.0         # свечи старше — триггер по цене не работаем

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
    """{bot_id: {bag, status, position}} из хвоста snapshots.csv (последняя
    строка бота). position — в валюте бота (DYN: coin; BTC-LONG inverse: USD-
    контракты, ~= нотионал). Колонки: ts,bot_id,name,alias,status,position,
    profit,current_profit,..."""
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
        if len(parts) < 19:      # полная схема; иначе поля съехали — не гадаем
            continue
        try:
            bid = str(int(float(parts[1])))
            status = int(float(parts[4]))
            position = float(parts[5])
            bag = float(parts[7]) - float(parts[6])
        except (ValueError, IndexError):
            continue
        try:
            avg_price = float(parts[14])
        except (ValueError, IndexError):
            avg_price = None
        notional = (abs(position) * avg_price
                    if avg_price and avg_price > 0 else None)
        # последняя строка бота победит
        out[bid] = {"bag": bag, "status": status, "position": position,
                    "avg_price": avg_price, "notional": notional}
    return out


def read_btc_move(path: Path = BTC_1M_CSV, *, calm_hours: float = 4.0,
                  now: datetime | None = None) -> dict | None:
    """|1ч-движение| BTC сейчас и максимум за calm_hours, из market_1m.csv.

    None = данные протухли (>10 мин) или их мало — по цене НЕ действуем."""
    now = now or datetime.now(timezone.utc)
    need_min = int(calm_hours * 60) + 61
    closes: list[tuple[int, float]] = []
    try:
        with path.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - (need_min + 10) * 64))
            chunk = f.read().decode("utf-8", errors="replace")
    except OSError:
        return None
    for ln in chunk.splitlines()[1:]:
        parts = ln.split(",")
        if len(parts) < 5:
            continue
        try:
            ts = datetime.fromisoformat(parts[0]).timestamp()
            closes.append((int(ts) // 60, float(parts[4])))
        except (ValueError, IndexError):
            continue
    if len(closes) < 62:
        return None
    last_min, _ = closes[-1]
    if (now.timestamp() / 60 - last_min) > _BTC_STALE_MIN:
        return None
    by_min = dict(closes)
    moves = []
    for m, px in closes:
        prev = by_min.get(m - 60)
        if prev:
            moves.append((m, abs(px / prev - 1) * 100))
    if not moves:
        return None
    calm_cut = last_min - int(calm_hours * 60)
    window = [mv for m, mv in moves if m >= calm_cut]
    return {"move_1h_pct": moves[-1][1],
            "max_move_calm_pct": max(window) if window else moves[-1][1]}


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


def _otc_passed(params) -> object:
    return ((params.extra_raw or {}).get("in") or {}).get("otcPassed")


def _set_and_verify(api, bot_id: str, params, want_gs: float, want_tog: float,
                    want_maxq: float | None = None,
                    want_otc_passed: object = None) -> bool:
    """set_params → re-read → значения совпали, p=true, бот Active.

    want_otc_passed: для otc-ботов (BTC-LONG) — otcPassed обязан остаться
    каким был до записи (история 16-20.07: 8 правок maxQ его не трогали;
    если наша запись поведёт себя иначе — стоп немедленно)."""
    api.set_params(int(bot_id), params)
    back = api.get_params(int(bot_id))
    if back.gs is None or back.gap.tog is None:
        return False
    ok = (abs(back.gs - want_gs) < 1e-9 and abs(back.gap.tog - want_tog) < 1e-9
          and bool(back.p))
    if want_maxq is not None:
        ok = ok and back.q.maxQ is not None and abs(back.q.maxQ - want_maxq) < 1e-9
    if want_otc_passed is not None:
        ok = ok and _otc_passed(back) == want_otc_passed
    try:
        ok = ok and int(api.get_bot(int(bot_id)).status) == STATUS_ACTIVE
    except Exception:
        return False
    return ok


def apply_widen(api, bot_id: str, alias: str, factor: float, stage,
                bag: float, send_fn=None, bcfg: dict | None = None) -> bool:
    bcfg = bcfg or {}
    otc_expected = bool(bcfg.get("otc_expected"))
    episode_maxq = bcfg.get("episode_maxQ")

    params = api.get_params(int(bot_id))
    if not otc_expected and not _otc_safe(params):
        freeze("otc_guard: in.otc у бота — set_params опасен", {"bot_id": bot_id})
        if send_fn:
            send_fn(f"⚙️⛔️ Autotune ЗАМОРОЖЕН: у {alias} появился in.otc. "
                    "Удали state/grid_autotune_frozen.json после разбора.")
        return False
    if params.gs is None or params.gap.tog is None:
        _journal({"event": "SKIP_NO_PARAMS", "bot_id": bot_id, "alias": alias})
        return False

    # DefaultGridParams — frozen dataclass: строим НОВЫЙ инстанс через replace,
    # присваивание полей падает FrozenInstanceError (баг 2026-07-21, fail-safe).
    orig = {"gs": params.gs, "tog": params.gap.tog}
    new_gs = round(params.gs * factor, 4)
    new_tog = round(params.gap.tog * factor, 4)
    otc_before = _otc_passed(params) if otc_expected else None
    new_maxq = None
    new_q = params.q
    if episode_maxq is not None and params.q.maxQ is not None:
        orig["maxQ"] = params.q.maxQ
        new_maxq = float(episode_maxq)
        new_q = dataclasses.replace(params.q, maxQ=new_maxq)
    new_params = dataclasses.replace(
        params, gs=new_gs, gap=dataclasses.replace(params.gap, tog=new_tog),
        q=new_q)

    base = {"bot_id": bot_id, "alias": alias, "orig": orig, "gs": new_gs,
            "tog": new_tog, "maxQ": new_maxq, "trigger": stage,
            "bag": round(bag, 4)}
    try:
        if not _set_and_verify(api, bot_id, new_params, new_gs, new_tog,
                               want_maxq=new_maxq,
                               want_otc_passed=otc_before):
            raise RuntimeError("verify failed")
    except Exception as e:
        # откат на исходные (из captured params) и стоп-кран
        try:
            rb_q = (dataclasses.replace(params.q, maxQ=orig["maxQ"])
                    if "maxQ" in orig else params.q)
            rb = dataclasses.replace(
                params, gs=orig["gs"],
                gap=dataclasses.replace(params.gap, tog=orig["tog"]), q=rb_q)
            api.set_params(int(bot_id), rb)
        except Exception:
            logger.exception("grid_autotune.rollback_failed bot=%s", bot_id)
        freeze(f"apply_verify_failed: {e}", base)
        if send_fn:
            send_fn(f"⚙️🚨 КРИТИЧНО {alias}: правка сетки НЕ прошла "
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
        qnote = (f", ордер {orig['maxQ']:g}→{new_maxq:g}$"
                 if new_maxq is not None else "")
        send_fn(f"⚙️ АВТОШИРЕНИЕ {alias}: {stage} → сделал "
                f"gs {orig['gs']}→{new_gs}, target {orig['tog']}→{new_tog}"
                f"{qnote}. Бот работает, верну при успокоении.")
    return True


def restore_params(api, bot_id: str, alias: str, rec: dict, bag: float,
                   send_fn=None, bcfg: dict | None = None) -> bool:
    bcfg = bcfg or {}
    otc_expected = bool(bcfg.get("otc_expected"))
    params = api.get_params(int(bot_id))
    orig = rec["orig"]
    cur = {"gs": params.gs, "tog": params.gap.tog}
    otc_before = _otc_passed(params) if otc_expected else None
    want_maxq = None
    new_q = params.q
    if "maxQ" in orig:
        # тихий размер: quiet_maxQ конфига (актуален) > исходный на момент эпизода
        want_maxq = float(bcfg.get("quiet_maxQ", orig["maxQ"]))
        new_q = dataclasses.replace(params.q, maxQ=want_maxq)
    new_params = dataclasses.replace(
        params, gs=orig["gs"],
        gap=dataclasses.replace(params.gap, tog=orig["tog"]), q=new_q)
    base = {"bot_id": bot_id, "alias": alias, "from": cur, "to": orig,
            "maxQ": want_maxq, "bag": round(bag, 4)}
    try:
        if not _set_and_verify(api, bot_id, new_params, orig["gs"], orig["tog"],
                               want_maxq=want_maxq,
                               want_otc_passed=otc_before):
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
        qnote = f", ордер обратно {want_maxq:g}$" if want_maxq is not None else ""
        send_fn(f"↩️ {alias}: успокоилось (мешок {bag:+,.4g}) → вернул "
                f"gs {cur['gs']}→{orig['gs']}, target {cur['tog']}→{orig['tog']}"
                f"{qnote}.")
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
    default_restore_bag = float(cfg.get("restore_bag_usd", -20.0))
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    actions = 0
    btc_move = None       # лениво, один раз на тик
    btc_move_read = False

    for bot_id, bcfg in bots.items():
        alias = bcfg.get("alias", bot_id)
        snap = bags.get(bot_id)
        if snap is None:
            continue
        trig_kind = bcfg.get("trigger", "drift")
        restore_bag = float(bcfg.get("restore_bag", default_restore_bag))

        # оценка триггера/успокоения
        if trig_kind == "btc_move_1h":
            if not btc_move_read:
                btc_move = read_btc_move(
                    calm_hours=float(bcfg.get("calm_hours", 4.0)))
                btc_move_read = True
            if btc_move is None:
                continue  # цены протухли — по этому триггеру не действуем
            thr = float(bcfg.get("move_pct_1h", 0.8))
            fired = btc_move["move_1h_pct"] >= thr
            calmed = btc_move["max_move_calm_pct"] < thr
            trig_label = (f"BTC {btc_move['move_1h_pct']:.2f}%/1ч ≥ {thr}%")
        else:
            stage = drift.get(bot_id, 0)
            fired = stage >= trigger_stage
            calmed = stage == 0
            trig_label = f"drift Stage {stage}, мешок {snap['bag']:+,.0f}$"

        if api is None:
            api = _cached_api()
            if api is None:
                return actions

        if bot_id in active:
            # эпизод открыт → ждём успокоения
            if calmed and snap["bag"] >= restore_bag \
                    and snap["status"] == STATUS_ACTIVE:
                if restore_params(api, bot_id, alias, active[bot_id],
                                  snap["bag"], send_fn=send_fn, bcfg=bcfg):
                    actions += 1
            continue

        # эпизод не открыт → ждём триггера
        if not fired or snap["status"] != STATUS_ACTIVE:
            continue
        # ворота по размеру позиции: пока бот «не набрал» — не трогаем.
        # Гейт только на ВХОД в эпизод; восстановление выше не гейтится.
        #  * min_abs_position — в единицах position (BTC-LONG inverse: контракты
        #    = USD; оператор 2026-07-20: до ~$5-6k не трогать);
        #  * min_notional_usd — |поза| × avg_price (DYN: позиция в МОНЕТАХ;
        #    оператор 2026-07-21: альты $2000, ETH $3000). Проверено на неделе:
        #    в минуты худшего мешка нотионал был выше порогов у всех 7 ботов —
        #    гейт режет холостые срабатывания, не реальные эпизоды.
        min_pos = float(bcfg.get("min_abs_position", 0) or 0)
        if min_pos > 0:
            pos = snap.get("position")
            if pos is None or abs(pos) < min_pos:
                _journal({"event": "SKIP_SMALL_POS", "bot_id": bot_id,
                          "alias": alias, "position": pos, "min": min_pos})
                continue
        min_notional = float(bcfg.get("min_notional_usd", 0) or 0)
        if min_notional > 0:
            notional = snap.get("notional")
            if notional is None or notional < min_notional:
                _journal({"event": "SKIP_SMALL_POS", "bot_id": bot_id,
                          "alias": alias, "notional": notional,
                          "min_usd": min_notional})
                continue
        if _episodes_today(bot_id, today) >= int(
                cfg.get("max_episodes_per_day_per_bot", 2)):
            continue
        last = _last_episode_mono.get(bot_id)
        gap = float(cfg.get("min_gap_between_episodes_sec", 7200))
        if last is not None and (time.monotonic() - last) < gap:
            continue

        if apply_widen(api, bot_id, alias, factor, trig_label, snap["bag"],
                       send_fn=send_fn, bcfg=bcfg):
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
