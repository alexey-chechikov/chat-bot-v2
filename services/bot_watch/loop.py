"""Сторож поведения бота: РАБОТАЕТ или картина поменялась (плато позиции).

Оператор 17.09: «различай, где бот работает и приносит прибыль, а где
картина меняется — эти окна явно видны» (по бэктесту ETH: плато позиции
06.02-19.03, 06.06-14.07, с 19.08 — прибыль в эти окна сползает).

ПЕРВАЯ ВЕРСИЯ (утро 17.09) мерила позицию и мешок в разах от МЕДИАНЫ
бота. Оператор поймал: 0.214 ETH = «×3.6 от обычной» — потому что бот
большую часть времени стоит в нуле и медиана 0.06 ETH. Шкала бессмысленная,
выброшена.

ОКНО = время, пока бот «в позиции»: |позиция| > 10% её 95-го перцентиля
за историю бота. Бот работает — окна короткие, позиция возвращается к нулю.
Картина поменялась — позиция стоит, выход по средней не срабатывает.

ЗАМЕР 17.09, 38 реальных ботов, 262 окна (глубокое = мешок хуже −6% от
пиковой позиции окна, то есть цена ушла ~6% за среднюю):
  в позиции  окон  стали глубокими  просадки ещё впереди  доход окон длиннее
    1ч        257        6%               74%                  100%
    24ч        73       18%               65%                   64%
    48ч        49       24%               64%                   64%
    96ч        26       42%               55%                   44%
    7 сут      16       69%                7%                   37%
Модель сетки на 2 годах 1m (ETH/XRP/BTC, лонг и шорт, шаг 0.4 / цель 1.49)
даёт ту же форму: ETH-лонг 10% → 17% → 30% → 50% на 24ч/48ч/96ч/7сут.

Что из этого следует:
  - окна ВИДНЫ: риск глубокого провала растёт с длиной плато монотонно;
  - но окна длиннее суток дают ~2/3 дохода (большое закрытие по средней в
    конце плато), и 3 из 4 суточных плато кончаются нормально — закрывать
    на «плато видно» значит резать доход;
  - 4 суток — точка решения: 42% уходят глубоко, впереди ещё половина;
    к 7 суткам просадка в основном уже случилась.

СОСТОЯНИЯ
  РАБОТАЕТ         в нуле или в позиции < 24ч
  ПЛАТО            в позиции 24-96ч — без тревоги, видно в журнале
  ЗАТЯЖНОЕ ПЛАТО   в позиции ≥ 96ч — тревога, один раз на окно
  РЕЗКИЙ НАБОР     позиция за 4ч выросла сильнее max(p99 бота, ×3) —
                   тревога (на прежнем замере 7 из 9 настоящие, 88%
                   падения впереди; 19.08 сработал на BTC, ETH, XRP сразу)

Ботов не трогает, только сообщает.
"""
from __future__ import annotations

import asyncio
import bisect
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "state" / "bot_watch_config.json"
STATE_PATH = ROOT / "state" / "bot_watch_state.json"
JOURNAL_PATH = ROOT / "state" / "bot_watch_journal.jsonl"
HEARTBEAT_PATH = ROOT / "state" / "bot_watch_heartbeat.json"

HOUR = 3600.0

WORKING, PLATEAU, LONG_PLATEAU, SHARP, CALIB = (
    "РАБОТАЕТ", "ПЛАТО", "ЗАТЯЖНОЕ ПЛАТО", "РЕЗКИЙ НАБОР", "КАЛИБРОВКА")
ALERT_STATES = (LONG_PLATEAU, SHARP)


def _now_ts() -> float:
    return datetime.now(timezone.utc).timestamp()


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


def load_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def read_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_state(d: dict) -> None:
    try:
        STATE_PATH.write_text(json.dumps(d, ensure_ascii=False),
                              encoding="utf-8")
    except OSError:
        logger.exception("bot_watch.state_write_failed")


def _deposit() -> float:
    """Депозит из risk_guard_config — чтобы мешок был виден в масштабе."""
    try:
        d = json.loads((ROOT / "state" / "risk_guard_config.json")
                       .read_text(encoding="utf-8"))
        return float(d.get("deposit_usd", 0) or 0)
    except (OSError, ValueError, TypeError):
        return 0.0


def _journal(rec: dict) -> None:
    try:
        with JOURNAL_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps({**rec, "ts": _iso(_now_ts())},
                               ensure_ascii=False) + "\n")
    except OSError:
        logger.exception("bot_watch.journal_failed")


# ─── чистые функции ────────────────────────────────────────────────────
def value_at(samples: list, t: float):
    """Последний сэмпл с отметкой времени <= t. samples отсортированы."""
    ts = [s[0] for s in samples]
    k = bisect.bisect_right(ts, t) - 1
    return samples[k] if k >= 0 else None


def _pct(vals: list, q: float) -> float:
    v = sorted(vals)
    return v[min(len(v) - 1, int(len(v) * q))] if v else 0.0


def flat_limit(samples: list, cfg: dict) -> float | None:
    """|позиция| не выше этого — бот «в нуле». None — истории мало."""
    need = int(cfg.get("min_history_hours", 72))
    pos = [abs(s[1]) for s in samples if s[1]]
    if len(samples) < need or not pos:
        return None
    return float(cfg.get("flat_share", 0.10)) * _pct(pos, 0.95)


def plateau_hours(samples: list, lim: float) -> tuple[float, bool]:
    """Сколько часов бот в позиции без возврата к нулю.

    → (часы, полная_ли_оценка). Если в истории нуля не было — часы от
    первого сэмпла и False: плато не меньше этого.
    """
    if not samples or abs(samples[-1][1]) <= lim:
        return 0.0, True
    now = samples[-1][0]
    for s in reversed(samples):
        if abs(s[1]) <= lim:
            return (now - s[0]) / HOUR, True
    return (now - samples[0][0]) / HOUR, False


def growth4(samples: list, k: int, lim: float) -> float:
    """Во сколько раз |позиция| выросла за 4 часа (пол — порог нуля)."""
    t, pos = samples[k][0], samples[k][1]
    s4 = value_at(samples[:k + 1], t - 4 * HOUR)
    base = abs(s4[1]) if s4 else abs(pos)
    floor = max(lim, 1e-12)
    return abs(pos) / max(base, floor)


def sharp_threshold(samples: list, lim: float, cfg: dict) -> float:
    g = [growth4(samples, k, lim) for k in range(len(samples))]
    return max(_pct(g, 0.99), float(cfg.get("fast_min_mult", 3.0)))


def classify(plateau_h: float, g4: float, sharp: float, in_pos: bool,
             cfg: dict) -> str:
    if in_pos and g4 > sharp:
        return SHARP
    if plateau_h >= float(cfg.get("long_plateau_hours", 96)):
        return LONG_PLATEAU
    if plateau_h >= float(cfg.get("plateau_hours", 24)):
        return PLATEAU
    return WORKING


def should_alert(prev: str, new: str, last_alert: float | None, now: float,
                 cooldown_h: float, window_alerted: bool = False) -> bool:
    """Тревога: ЗАТЯЖНОЕ ПЛАТО — один раз на окно, РЕЗКИЙ НАБОР — при входе.

    Окно кончается, когда бот вернулся в РАБОТАЕТ (флаг сбрасывает tick).
    Пауза между тревогами не теряет затяжное плато: оно уйдёт после паузы.
    """
    if new not in ALERT_STATES:
        return False
    if last_alert and now - last_alert < cooldown_h * HOUR:
        return False
    if new == LONG_PLATEAU:
        return not window_alerted
    return new != prev


def bag_usd(bag: float, balance: float, avg_price: float) -> float:
    """Мешок в долларах. Инверсный бот (|баланс| < 5) считает профит в
    своей монете — переводим по средней цене входа, это ±несколько %."""
    if abs(balance) < 5 and avg_price > 0:
        return bag * avg_price
    return bag


def notional_usd(pos: float, balance: float, avg_price: float) -> float:
    """У инверсного позиция уже в USD-контрактах, у линейного — в монетах."""
    if abs(balance) < 5:
        return abs(pos)
    return abs(pos) * avg_price


def card(name: str, state: str, plateau_h: float, exact: bool, g4: float,
         sharp: float, notional: float, usd: float, deposit: float) -> str:
    share = f" = {abs(usd) / deposit:.1%} депозита" if deposit else ""
    of_pos = f" = {usd / notional:+.1%} позиции" if notional else ""
    days = plateau_h / 24
    lower = "" if exact else "не меньше "
    if state == SHARP:
        return "\n".join([
            f"🚨 РЕЗКИЙ НАБОР · {name}",
            f"позиция за 4 часа выросла в {g4:.1f} раза (норма бота до ×{sharp:.1f})",
            f"позиция ${notional:,.0f}, мешок ≈ ${usd:,.0f}{share}",
            "по истории: 7 из 9 таких тревог — настоящий провал, 88% падения "
            "ещё впереди.",
            "проверенная защита от ликвидации — аварийный хедж; рез и "
            "заморозка набора не помогают.",
        ])
    if plateau_h >= 168:
        stat = ("по 262 окнам 38 реальных ботов: из плато длиннее 7 суток 69% "
                "ушли глубже −6% позиции, но к 7 суткам просадка в основном "
                "уже случилась (впереди медиана 7%).")
    else:
        stat = ("по 262 окнам 38 реальных ботов: из плато длиннее 4 суток 42% "
                "ушли глубже −6% позиции, в этот момент впереди была ещё "
                "~половина просадки.")
    return "\n".join([
        f"⏳ ЗАТЯЖНОЕ ПЛАТО · {name}",
        f"в позиции {lower}{days:.1f} сут без возврата к нулю",
        f"позиция ${notional:,.0f}, мешок ≈ ${usd:,.0f}{share}{of_pos}",
        stat,
        "58% закрылись нормально, а окна длиннее суток дали 64% дохода — "
        "закрытие здесь фиксирует убыток.",
        "проверенная защита от ликвидации — аварийный хедж.",
    ])


# ─── цикл ───────────────────────────────────────────────────────────────
def tick(api=None, send_fn=None) -> str:
    cfg = load_config()
    status = "error"
    now = _now_ts()
    try:
        if not cfg.get("enabled"):
            status = "disabled"
            return status
        if api is None:
            from services.order_harvester.loop import _cached_api
            api = _cached_api()
            if api is None:
                status = "no_api"
                return status
        state = read_state()
        bots_state = state.setdefault("bots", {})
        keep_h = float(cfg.get("keep_days", 35)) * 24
        sample_every = float(cfg.get("sample_every_minutes", 55)) * 60
        cooldown = float(cfg.get("cooldown_hours", 6))
        only = set(str(x) for x in (cfg.get("bots") or []))
        deposit = _deposit()
        alerts = 0
        for b in api.list_bots():
            bid = str(b.id)
            if only and bid not in only:
                continue
            if int(b.status) != 2 or b.stat is None:
                continue
            s = b.stat
            pos = float(getattr(s, "position", 0) or 0)
            prof = float(getattr(s, "profit", 0) or 0)
            cur = float(getattr(s, "currentProfit", 0) or 0)
            bal = float(getattr(s, "balance", 0) or 0)
            avg = float(getattr(s, "averagePrice", 0) or 0)
            bag = cur - prof
            bs = bots_state.setdefault(bid, {"samples": [], "state": CALIB})
            samples = bs["samples"]
            if not samples or now - samples[-1][0] >= sample_every:
                samples.append([now, pos, bag])
            else:
                samples[-1] = [samples[-1][0], pos, bag]
            cutoff = now - keep_h * HOUR
            bs["samples"] = samples = [x for x in samples if x[0] >= cutoff]

            prev = bs.get("state", CALIB)
            lim = flat_limit(samples, cfg)
            if lim is None:
                bs["state"] = CALIB
                continue
            ph, exact = plateau_hours(samples, lim)
            in_pos = abs(pos) > lim
            g4 = growth4(samples, len(samples) - 1, lim)
            sharp = sharp_threshold(samples, lim, cfg)
            new = classify(ph, g4, sharp, in_pos, cfg)
            usd = bag_usd(bag, bal, avg)
            notional = notional_usd(pos, bal, avg)
            bs.update({"state": new, "plateau_h": round(ph, 1),
                       "plateau_exact": exact, "growth4": round(g4, 2),
                       "bag_usd": round(usd, 2), "notional_usd": round(notional, 2),
                       "flat_limit": lim})
            if new != prev:
                _journal({"event": "STATE", "bot": bid,
                          "name": (b.name or "")[:40], "from": prev, "to": new,
                          "plateau_h": round(ph, 1), "growth4": round(g4, 2),
                          "position": pos, "notional_usd": round(notional, 2),
                          "bag_usd": round(usd, 2)})
            if new == WORKING:
                bs.pop("window_alerted", None)
            if should_alert(prev, new, bs.get("last_alert"), now, cooldown,
                            bool(bs.get("window_alerted"))):
                text = card(b.name or bid, new, ph, exact, g4, sharp,
                            notional, usd, deposit)
                if send_fn:
                    try:
                        send_fn(text)
                    except Exception:
                        logger.exception("bot_watch.send_failed bot=%s", bid)
                _journal({"event": "ALERT", "bot": bid, "state": new,
                          "text": text})
                bs["last_alert"] = now
                bs["window_alerted"] = True
                alerts += 1
        state["last_tick"] = _iso(now)
        write_state(state)
        status = f"alerts:{alerts}" if alerts else "ok"
        return status
    finally:
        try:
            HEARTBEAT_PATH.write_text(json.dumps(
                {"ts": _iso(now), "status": status}, ensure_ascii=False),
                encoding="utf-8")
        except OSError:
            logger.exception("bot_watch.heartbeat_failed")


async def bot_watch_loop(stop_event=None, send_fn=None) -> None:
    cfg = load_config()
    interval = int(cfg.get("poll_seconds", 900))
    logger.info("bot_watch.start interval=%ds", interval)
    while True:
        if stop_event is not None and stop_event.is_set():
            return
        try:
            tick(send_fn=send_fn)
        except Exception:
            logger.exception("bot_watch.tick_failed")
        try:
            if stop_event is not None:
                await asyncio.wait_for(stop_event.wait(), interval)
                return
            await asyncio.sleep(interval)
        except asyncio.TimeoutError:
            continue
