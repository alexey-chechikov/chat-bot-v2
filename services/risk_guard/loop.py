"""Портфельный контроль убытка: считает ВЕСЬ счёт, а не каждого бота.

Почему именно так, по следам ликвидации 19-22.08:

  * Убил не отдельный бот, а СУММА. Мешки по $1-4 тысячи выглядели терпимо
    поодиночке; вместе — $16 032 при депозите $10 000. Поэтому порог
    считается по сумме всех ботов.
  * Пять ботов в одну сторону — это ОДНА ставка, а не пять независимых.
    Поэтому экспозиция складывается по модулю, без взаимозачёта.
  * Остановка бота НЕ закрывает позицию. 21.08 боты стояли, а минус рос.
    Замер по 4 независимым эпизодам за 4 месяца: после −20% депозита мешок
    ни разу не восстановился за 48ч (4 из 4 углубились). Поэтому на верхнем
    пороге позиция ЗАКРЫВАЕТСЯ.
  * 22.08 я принял 22-часовой кэш за текущее состояние и сказал оператору,
    что позиции живы, когда их уже ликвидировали. Поэтому устаревшие данные
    здесь — АВАРИЯ, а не тишина: старше max_stale_minutes → тормозим.

Две ступени:
  WARN  — стоп ботов (перестают набирать), позиция остаётся, алерт.
  KILL  — стоп ботов И закрытие всех позиций.

Оператор выбрал KILL на −20% депозита. WARN на −10% добавлен потому, что
на истории лимит −10% поймал бы августовскую катастрофу при мешке −$1 121,
за трое суток до −$16 032; но два раза из шести мешок оттуда возвращался
сам, поэтому −10% только тормозит набор, а не фиксирует убыток.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "state" / "risk_guard_config.json"
JOURNAL_PATH = ROOT / "state" / "risk_guard_journal.jsonl"
FROZEN_PATH = ROOT / "state" / "risk_guard_frozen.json"

POLL_INTERVAL_SEC = 60
ACTIVE_STATUSES = {1, 2, 3}          # STARTING, ACTIVE, PAUSED — ещё в игре


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _journal(rec: dict) -> None:
    rec = {**rec, "ts": _now()}
    try:
        with JOURNAL_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        logger.exception("risk_guard.journal_failed")


def load_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def is_frozen() -> bool:
    return FROZEN_PATH.exists()


def freeze(reason: str, detail: dict | None = None) -> None:
    try:
        FROZEN_PATH.write_text(json.dumps(
            {"reason": reason, "detail": detail or {}, "ts": _now()},
            ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        logger.exception("risk_guard.freeze_write_failed")


# ─────────────────────────────────────────────────────────────────────────
def _price_of(api, inst_id: str) -> float | None:
    from services.order_harvester.loop import okx_price
    try:
        return okx_price(inst_id)
    except Exception:
        logger.exception("risk_guard.price_failed inst=%s", inst_id)
        return None


def snapshot(api, cfg: dict) -> dict:
    """Живое состояние счёта. Никаких кэшей и файлов — только API."""
    bots_cfg = cfg.get("bots") or {}
    now = datetime.now(timezone.utc)
    max_stale = float(cfg.get("max_stale_minutes", 15))

    rows = []
    stale = []
    unpriced = []
    total_unreal = 0.0
    total_notional = 0.0

    try:
        live = api.list_bots()
    except Exception as e:
        logger.exception("risk_guard.list_bots_failed")
        return {"error": f"{type(e).__name__}: {e}", "rows": []}

    for b in live:
        bid = str(b.id)
        bcfg = bots_cfg.get(bid)
        if bcfg is None:
            continue                       # не наш — не считаем
        if int(b.status) not in ACTIVE_STATUSES:
            continue                       # остановлен и без позиции — вне игры
        st = b.stat
        if st is None:
            stale.append(bid)
            continue

        age_min = ((now - st.updatedAt).total_seconds() / 60
                   if st.updatedAt else 1e9)
        if age_min > max_stale:
            stale.append(f"{bcfg.get('alias', bid)}({age_min:.0f}мин)")

        inverse = bool(bcfg.get("inverse"))
        price = _price_of(api, bcfg.get("inst_id", ""))
        if price is None or price <= 0:
            unpriced.append(bcfg.get("alias", bid))
            continue

        pos = abs(float(st.position or 0.0))
        notional = pos if inverse else pos * price
        bag = float(st.currentProfit or 0.0) - float(st.profit or 0.0)
        bag_usd = bag * price if inverse else bag

        total_unreal += bag_usd
        total_notional += notional
        rows.append({"bot_id": bid, "alias": bcfg.get("alias", bid),
                     "notional_usd": round(notional, 2),
                     "unrealized_usd": round(bag_usd, 2),
                     "position": pos, "status": int(b.status),
                     "age_min": round(age_min, 1)})

    deposit = float(cfg.get("deposit_usd", 0) or 0)
    return {
        "rows": rows, "stale": stale, "unpriced": unpriced,
        "total_unrealized_usd": round(total_unreal, 2),
        "total_notional_usd": round(total_notional, 2),
        "deposit_usd": deposit,
        "leverage": round(total_notional / deposit, 2) if deposit else None,
        "unrealized_pct": (round(total_unreal / deposit * 100, 2)
                           if deposit else None),
    }


def evaluate(snap: dict, cfg: dict) -> dict:
    """Что делать. Порядок проверок — от самого опасного к мягкому."""
    if snap.get("error"):
        return {"action": "HALT", "reason": f"API недоступен: {snap['error']}"}

    deposit = float(cfg.get("deposit_usd", 0) or 0)
    if deposit <= 0:
        return {"action": "NONE", "reason": "депозит не задан"}

    unreal = float(snap.get("total_unrealized_usd") or 0.0)
    notional = float(snap.get("total_notional_usd") or 0.0)
    kill_at = -deposit * float(cfg.get("kill_pct", 20)) / 100.0
    warn_at = -deposit * float(cfg.get("warn_pct", 10)) / 100.0
    max_lev = float(cfg.get("max_leverage", 1.0))

    if unreal <= kill_at:
        return {"action": "KILL",
                "reason": f"убыток ${unreal:,.0f} достиг предела "
                          f"${kill_at:,.0f} ({cfg.get('kill_pct')}% депозита)"}

    if snap.get("stale"):
        return {"action": "HALT",
                "reason": "данные устарели: " + ", ".join(snap["stale"])}
    if snap.get("unpriced"):
        return {"action": "HALT",
                "reason": "нет цены: " + ", ".join(snap["unpriced"])}

    if deposit and notional > max_lev * deposit:
        return {"action": "HALT",
                "reason": f"экспозиция ${notional:,.0f} = "
                          f"{notional/deposit:.2f}x выше предела {max_lev}x"}

    if unreal <= warn_at:
        return {"action": "HALT",
                "reason": f"убыток ${unreal:,.0f} достиг предупреждения "
                          f"${warn_at:,.0f} ({cfg.get('warn_pct')}% депозита)"}

    return {"action": "NONE", "reason": "в пределах"}


ALERT_STATE = ROOT / "state" / "risk_guard_alert.json"


def _alert_due(cfg: dict) -> bool:
    """Не спамить одним и тем же алертом каждую минуту.

    Порог убытка держится часами, а тик раз в минуту — без этого оператор
    получил бы сотни одинаковых сообщений и перестал бы их читать.
    """
    gap_min = float(cfg.get("alert_gap_minutes", 30))
    now = datetime.now(timezone.utc)
    try:
        last = datetime.fromisoformat(
            json.loads(ALERT_STATE.read_text(encoding="utf-8"))["ts"])
        if (now - last) < timedelta(minutes=gap_min):
            return False
    except (OSError, ValueError, KeyError):
        pass
    try:
        ALERT_STATE.write_text(json.dumps({"ts": now.isoformat()}),
                               encoding="utf-8")
    except OSError:
        logger.exception("risk_guard.alert_state_write_failed")
    return True


def _pause_all(api, snap: dict) -> list[str]:
    from services.short_bots_guard import control
    done = []
    for r in snap.get("rows", []):
        if r["status"] == 3:              # уже на паузе
            continue
        try:
            control.pause_bot(r["bot_id"], reason="risk_guard",
                              trigger="risk_guard")
            done.append(r["alias"])
        except Exception:
            logger.exception("risk_guard.pause_failed bot=%s", r["bot_id"])
    return done


def _close_all(api, snap: dict) -> tuple[list[str], list[str]]:
    ok, failed = [], []
    for r in snap.get("rows", []):
        if not r["position"]:
            continue
        try:
            api.close_position(int(r["bot_id"]))
            ok.append(r["alias"])
        except Exception as e:
            failed.append(f"{r['alias']}: {type(e).__name__}")
            logger.exception("risk_guard.close_failed bot=%s", r["bot_id"])
    return ok, failed


def tick(api=None, send_fn=None) -> str:
    cfg = load_config()
    if not cfg.get("enabled"):
        return "disabled"
    if is_frozen():
        return "frozen"

    if api is None:
        from services.order_harvester.loop import _cached_api
        api = _cached_api()
        if api is None:
            return "no_api"

    snap = snapshot(api, cfg)
    decision = evaluate(snap, cfg)
    action = decision["action"]

    if action == "NONE":
        return "ok"

    base = {"action": action, "reason": decision["reason"],
            "unrealized_usd": snap.get("total_unrealized_usd"),
            "notional_usd": snap.get("total_notional_usd"),
            "leverage": snap.get("leverage"),
            "rows": snap.get("rows")}

    if action == "HALT":
        paused = _pause_all(api, snap)
        _journal({"event": "HALT", **base, "paused": paused})
        if send_fn and paused:
            send_fn(f"🛑 RISK GUARD: {decision['reason']}\n"
                    f"Остановлены: {', '.join(paused)}. "
                    f"Позиции НЕ закрыты.")
        return "halt"

    # ── достигнут предел убытка ──────────────────────────────────────
    paused = _pause_all(api, snap)

    # Оператор 2026-08-27: «без закрытий — только пауза ботов и
    # предупреждение». Флаг выключен по умолчанию: закрытие позиции
    # необратимо и фиксирует убыток, поэтому включать его вправе только
    # оператор явной единицей в конфиге.
    # На истории ожидание обходится дороже (4 из 4 эпизодов после −20%
    # углубились за 48ч), и это сказано в алерте — но решение его.
    if not cfg.get("allow_close"):
        _journal({"event": "LIMIT_NO_CLOSE", **base, "paused": paused})
        if send_fn and _alert_due(cfg):
            send_fn(f"🚨 ПРЕДЕЛ УБЫТКА: {decision['reason']}\n"
                    f"Боты остановлены: {', '.join(paused) or 'уже стояли'}.\n"
                    f"ПОЗИЦИИ НЕ ЗАКРЫТЫ — закрытие выключено тобой.\n"
                    f"Номинал ${snap['total_notional_usd']:,.0f}, "
                    f"плечо {snap['leverage']}x.\n"
                    f"Справка: на истории после этого порога мешок за 48ч "
                    f"углублялся 4 раза из 4.")
        return "limit_no_close"

    closed, failed = _close_all(api, snap)
    _journal({"event": "KILL", **base, "paused": paused,
              "closed": closed, "failed": failed})
    freeze("KILL сработал — разбор вручную", base)
    if send_fn:
        send_fn(f"🚨 RISK GUARD — ЗАКРЫТИЕ ВСЕГО\n{decision['reason']}\n"
                f"Закрыты: {', '.join(closed) or '—'}\n"
                + (f"НЕ УДАЛОСЬ: {', '.join(failed)}\n" if failed else "")
                + "Служба заморожена, снимай state/risk_guard_frozen.json "
                  "после разбора.")
    return "kill"


async def risk_guard_loop(stop_event=None, send_fn=None) -> None:
    logger.info("risk_guard.start interval=%ds", POLL_INTERVAL_SEC)
    while True:
        if stop_event is not None and stop_event.is_set():
            return
        try:
            tick(send_fn=send_fn)
        except Exception:
            logger.exception("risk_guard.tick_failed")
        try:
            if stop_event is not None:
                await asyncio.wait_for(stop_event.wait(), POLL_INTERVAL_SEC)
                return
            await asyncio.sleep(POLL_INTERVAL_SEC)
        except asyncio.TimeoutError:
            continue
