"""Портфельный контроль убытка: считает ВЕСЬ счёт, а не каждого бота.

Почему именно так, по следам ликвидации 19-22.08:

  * Убил не отдельный бот, а СУММА. Мешки по $1-4 тысячи выглядели терпимо
    поодиночке; вместе — $16 032 при депозите $10 000. Поэтому порог
    считается по сумме всех ботов.
  * Пять ботов в одну сторону — это ОДНА ставка, а не пять независимых.
    Поэтому экспозиция складывается по модулю, без взаимозачёта.
  * Остановка бота НЕ закрывает позицию. 21.08 боты стояли, а минус рос.
    Единственный ЧИСТЫЙ эпизод (19.08, только боты OKX): мешок держался
    ниже порога 140 часов и за 48ч ушёл с −$1 121 до −$13 842. Прежняя
    оценка «4 из 4 эпизодов» была НЕВЕРНА — в неё попали старые
    битмексовые боты, у которых мешок в BTC, а считался долларами.
    Выборка из одного эпизода, и это надо помнить.
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
HEARTBEAT_PATH = ROOT / "state" / "risk_guard_heartbeat.json"
API_FAIL_PATH = ROOT / "state" / "risk_guard_api_fails.json"
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


def close_fraction_for(pct_of_deposit: float, cfg: dict) -> float:
    """Какую долю позиции закрыть при такой глубине убытка по боту.

    Оператор 2026-08-27: «после 10 мы закрываем только частично до 20
    процентов». То есть на пороге режем часть, на верхней границе — всё,
    между ними пропорционально. Ниже порога не режем вовсе.
    """
    start = float(cfg.get("kill_pct", 10))
    full = float(cfg.get("full_close_pct", 20))
    depth = abs(pct_of_deposit)
    if depth < start:
        return 0.0
    if depth >= full or full <= start:
        return 1.0
    base = float(cfg.get("first_close_fraction", 0.25))
    span = (depth - start) / (full - start)
    return min(1.0, base + (1.0 - base) * span)


def _per_bot_breaches(snap: dict, cfg: dict, deposit: float) -> list[dict]:
    """Боты, каждый из которых САМ прошёл порог. Пустой список = никто."""
    if deposit <= 0:
        return []
    out = []
    for r in snap.get("rows", []):
        pct = float(r.get("unrealized_usd") or 0.0) / deposit * 100.0
        frac = close_fraction_for(pct, cfg)
        if frac > 0:
            out.append({**r, "pct": pct, "close_fraction": frac})
    return out


def evaluate(snap: dict, cfg: dict, api_fails: int = 0) -> dict:
    """Что делать. Порядок проверок — от самого опасного к мягкому.

    api_fails — сколько чтений подряд уже не удалось. Одна неудача не
    повод объявлять тревогу: GinArea отдаёт 5xx пачками по несколько
    минут, и за неделю такой одиночный отказ дал 197 записей HALT со
    списком остановленных `[]` — то есть тревога, на которую сама служба
    ничего не сделала, потому что API был недоступен и для остановки
    тоже. Ждём подтверждения подряд, иначе это шум, маскирующий реальный
    отказ.
    """
    if snap.get("error"):
        need = int(cfg.get("api_fail_streak", 3))
        if api_fails < need:
            return {"action": "NONE",
                    "reason": f"чтение не удалось {api_fails}/{need}: "
                              f"{snap['error']}"}
        return {"action": "HALT",
                "reason": f"API недоступен {api_fails} раз подряд: "
                          f"{snap['error']}"}

    deposit = float(cfg.get("deposit_usd", 0) or 0)
    if deposit <= 0:
        return {"action": "NONE", "reason": "депозит не задан"}

    unreal = float(snap.get("total_unrealized_usd") or 0.0)
    notional = float(snap.get("total_notional_usd") or 0.0)
    kill_at = -deposit * float(cfg.get("kill_pct", 20)) / 100.0
    warn_at = -deposit * float(cfg.get("warn_pct", 10)) / 100.0
    max_lev = float(cfg.get("max_leverage", 1.0))

    # Оператор 2026-08-27: «делаем такие закрытия от 10 процентов — до
    # мы только увеличиваем шаг сетки, до 10 боты должны работать на
    # максимум и закрывать только прибыльные ордера».
    #
    # Отсюда устройство: НИЖЕ предела риск-контур ботов НЕ ОСТАНАВЛИВАЕТ.
    # Сетке нужно набирать, чтобы работать, — пауза её обесценивает.
    # Растущая экспозиция лечится расширением шага (лестница в
    # grid_autotune по занятой ёмкости), а плюсовые ордера снимает
    # харвестер. Риск-контур до предела только предупреждает.
    #
    # Пауза остаётся ровно для одного случая: когда мы НЕ ВИДИМ состояние
    # (протухшие данные, нет цены, API молчит). Это не риск-порог, это
    # слепота, и работать вслепую нельзя — 22.08 я именно так принял
    # 22-часовой кэш за живое состояние.
    # Оператор 2026-08-27: «это 10 процентов должно быть на каждом боте, а
    # не суммарно — если на одном 6, а на другом 4/5, ничего не должно
    # закрываться». Подтверждено августом: суммарный лимит сработал бы в
    # 14:00, по-ботовый в 15:00 — разница час, но в 14:00 отдельные боты
    # были здоровы (SHORT −3.8%, остальные около нуля), и суммарное
    # правило закрыло бы пятерых нормальных из-за одного больного.
    #
    # Портфельный потолок оставлен ЗНАЧИТЕЛЬНО выше как страховка: к концу
    # эпизода XRP замер на −9.1% и по-ботовое правило не тронуло бы его
    # никогда. Шесть ботов по 9% — это 54% депозита без единого
    # срабатывания, а именно так счёт и умер.
    per_bot = _per_bot_breaches(snap, cfg, deposit)
    if per_bot:
        return {"action": "KILL", "bots": per_bot,
                "reason": "по боту: " + "; ".join(
                    f"{b['alias']} ${b['unrealized_usd']:,.0f} "
                    f"({b['pct']:.1f}% депозита) → закрыть "
                    f"{b['close_fraction']*100:.0f}%" for b in per_bot)}

    portfolio_cap = float(cfg.get("portfolio_kill_pct", 0) or 0)
    if portfolio_cap and unreal <= -deposit * portfolio_cap / 100.0:
        return {"action": "KILL", "bots": None,
                "reason": f"страховка портфеля: сумма ${unreal:,.0f} прошла "
                          f"{portfolio_cap}% депозита"}

    if snap.get("stale"):
        return {"action": "HALT",
                "reason": "данные устарели: " + ", ".join(snap["stale"])}
    if snap.get("unpriced"):
        return {"action": "HALT",
                "reason": "нет цены: " + ", ".join(snap["unpriced"])}

    if deposit and notional > max_lev * deposit:
        return {"action": "NOTIFY",
                "reason": f"экспозиция ${notional:,.0f} = "
                          f"{notional/deposit:.2f}x выше ориентира {max_lev}x "
                          f"— шаг сетки должен расширяться"}

    if unreal <= warn_at:
        return {"action": "NOTIFY",
                "reason": f"убыток ${unreal:,.0f} прошёл отметку "
                          f"${warn_at:,.0f} ({cfg.get('warn_pct')}% депозита)"}

    return {"action": "NONE", "reason": "в пределах"}


BREACH_STATE = ROOT / "state" / "risk_guard_breach.json"


def move_character(lookback_h: int = 24) -> dict | None:
    """Каким СЕЙЧАС идёт движение BTC — ровным или с откатами.

    Это НЕ прогноз. 19.08 замерено, что классификаторы режима не
    предсказывают характер следующих суток (разделяющая способность
    отрицательная). Здесь описывается уже идущее движение, а это другое.

    Эффективность = |итоговый ход| / сумма |почасовых ходов|.
    Близко к 1 — цена идёт ровно в одну сторону, откатов нет, сетке нечего
    отрабатывать. Близко к 0 — ходит туда-сюда, сетка зарабатывает.
    """
    path = ROOT / "market_live" / "market_1m.csv"
    try:
        closes: dict[str, float] = {}
        with path.open(encoding="utf-8") as f:
            next(f)
            for ln in f:
                p = ln.split(",")
                if len(p) >= 5:
                    try:
                        closes[p[0][:13]] = float(p[4])
                    except ValueError:
                        continue
    except OSError:
        return None
    hrs = sorted(closes)[-(lookback_h + 1):]
    if len(hrs) < lookback_h:
        return None
    seg = [closes[h] for h in hrs]
    walk = sum(abs(seg[j + 1] - seg[j]) for j in range(len(seg) - 1))
    if walk <= 0 or seg[0] <= 0:
        return None
    return {"efficiency": round(abs(seg[-1] - seg[0]) / walk, 3),
            "move_pct": round((seg[-1] / seg[0] - 1) * 100, 2)}


def _breach_age_minutes(active: bool, level: str) -> float:
    """Сколько минут подряд держится пробой. 0 = только начался.

    Оператор 2026-08-27: «принудительное закрытие не только при наступлении
    минус 400, а если этот минус держится какой-то промежуток времени».
    В единственном чистом эпизоде (19.08) минус держался 140 часов, так что
    выдержка в пару часов там ничего бы не задержала.
    """
    now = datetime.now(timezone.utc)
    try:
        st = json.loads(BREACH_STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        st = {}
    if not active:
        if st:
            try:
                BREACH_STATE.unlink()
            except OSError:
                pass
        return 0.0
    started = st.get(level)
    if not started:
        st[level] = now.isoformat()
        try:
            BREACH_STATE.write_text(json.dumps(st, ensure_ascii=False),
                                    encoding="utf-8")
        except OSError:
            logger.exception("risk_guard.breach_state_write_failed")
        return 0.0
    try:
        return (now - datetime.fromisoformat(started)).total_seconds() / 60
    except ValueError:
        return 0.0


def required_hold_minutes(cfg: dict, character: dict | None) -> tuple[float, str]:
    """Сколько минут пробой должен держаться, прежде чем действовать.

    Быстрое однонаправленное движение — ждать нечего, откатов нет.
    Рваное с откатами — сетке дают время отработать.
    ВНИМАНИЕ: модуляция по характеру НЕ ПРОВЕРЕНА на истории — чистый
    эпизод был всего один. Дефолты подобраны так, чтобы в худшем случае
    вести себя как простая выдержка без модуляции.
    """
    p = cfg.get("persistence") or {}
    base = float(p.get("min_hold_minutes", 60))
    fast = float(p.get("fast_move_min_hold_minutes", base))
    thr = float(p.get("fast_move_efficiency", 0.5))
    if character and character.get("efficiency", 0) >= thr:
        return fast, (f"движение ровное (эфф {character['efficiency']}, "
                      f"ход {character['move_pct']:+.1f}%)")
    if character:
        return base, (f"движение с откатами (эфф {character['efficiency']})")
    return base, "характер движения неизвестен"


NOTIFY_STATE = ROOT / "state" / "risk_guard_notify.json"


def _notify_changed(reason: str) -> bool:
    """Изменилось ли состояние уведомления с прошлого тика.

    Причина сравнивается без чисел: «экспозиция $3 169 = 1.47x» и
    «экспозиция $3 205 = 1.48x» — одно и то же состояние, писать дважды
    незачем. Сброс до NONE чистит память, чтобы возврат в условие
    записался заново.
    """
    key = "".join(c for c in str(reason) if not c.isdigit())
    try:
        prev = json.loads(NOTIFY_STATE.read_text(encoding="utf-8")).get("key")
    except (OSError, ValueError):
        prev = None
    if prev == key:
        return False
    try:
        NOTIFY_STATE.write_text(json.dumps({"key": key, "ts": _now()},
                                           ensure_ascii=False),
                                encoding="utf-8")
    except OSError:
        logger.exception("risk_guard.notify_state_write_failed")
    return True


def _notify_clear() -> None:
    try:
        NOTIFY_STATE.unlink()
    except OSError:
        pass


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


REDUCE_STATE = ROOT / "state" / "risk_guard_reduce.json"


def _last_reduce_age_minutes() -> float | None:
    """Сколько минут назад сокращали. None = не сокращали.

    Нужен, чтобы сокращение не каскадило: после первого раза позиция
    меньше, но мешок в долларах может остаться за ступенью, и без паузы
    служба резала бы книгу каждую минуту.
    """
    try:
        st = json.loads(REDUCE_STATE.read_text(encoding="utf-8"))
        return (datetime.now(timezone.utc)
                - datetime.fromisoformat(st["ts"])).total_seconds() / 60
    except (OSError, ValueError, KeyError):
        return None


def _mark_reduced() -> None:
    try:
        REDUCE_STATE.write_text(
            json.dumps({"ts": datetime.now(timezone.utc).isoformat()}),
            encoding="utf-8")
    except OSError:
        logger.exception("risk_guard.reduce_state_write_failed")


def _reduce_positions(api, snap: dict, fraction: float,
                      cfg: dict) -> tuple[list[str], list[str]]:
    """Сократить позицию на долю fraction, закрывая ОТДЕЛЬНЫЕ ордера.

    Закрываем самые глубокие — те, что ушли дальше всего от цены и сами
    уже не закроются. Именно они образуют заклинившую часть книги, из-за
    которой 19-22.08 позиция росла, а оборота не было.

    Полное закрытие позиции здесь не используется: сокращение должно
    оставлять сетке возможность работать дальше.
    """
    from services.order_harvester.loop import order_fields, order_profit_usd

    done, failed = [], []
    for r in snap.get("rows", []):
        bid = r["bot_id"]
        bcfg = (cfg.get("bots") or {}).get(bid) or {}
        price = _price_of(api, bcfg.get("inst_id", ""))
        if not price:
            failed.append(f"{r['alias']}: нет цены")
            continue
        try:
            orders = (api.get_orders(int(bid), page_size=100, page_number=0,
                                     only_opened=True).get("orders")) or []
        except Exception as e:
            failed.append(f"{r['alias']}: {type(e).__name__}")
            continue
        if not orders:
            continue

        scored = []
        for o in orders:
            f = order_fields(o)
            p = order_profit_usd(price, f)
            if p is None or not f.get("order_id"):
                continue
            qty = abs(float(f.get("qty") or 0))
            scored.append((p, qty, f["order_id"]))
        if not scored:
            continue
        scored.sort(key=lambda t: t[0])          # худшие первыми

        target_qty = sum(q for _, q, _ in scored) * fraction
        closed_qty = 0.0
        n = 0
        for _, qty, oid in scored:
            if closed_qty >= target_qty:
                break
            try:
                api.close_order(int(bid), oid)
                closed_qty += qty
                n += 1
            except Exception:
                logger.exception("risk_guard.reduce_close_failed bot=%s "
                                 "order=%s", bid, oid)
        if n:
            done.append(f"{r['alias']}: {n} орд.")
    return done, failed


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
    """Обёртка: что бы ни случилось внутри, оставить отметку живости.

    02.09: у риск-контура НЕ БЫЛО файла, обновляемого каждым тиком, —
    только журнал, а он пишется по событию. Значит убедиться, что самая
    ответственная служба вообще крутится, было нечем: молчащий журнал и
    остановленный цикл выглядели одинаково. Пишем отметку на КАЖДОМ пути
    выхода, включая no_api и frozen: именно в этих состояниях служба не
    защищает, и знать об этом важнее всего.
    """
    status = "error"
    try:
        status = _tick_inner(api=api, send_fn=send_fn)
        return status
    finally:
        try:
            HEARTBEAT_PATH.write_text(
                json.dumps({"ts": _now(), "status": status},
                           ensure_ascii=False), encoding="utf-8")
        except OSError:
            logger.exception("risk_guard.heartbeat_write_failed")


def _tick_inner(api=None, send_fn=None) -> str:
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
    # Счётчик подряд идущих неудачных чтений живёт в файле: тик может
    # смениться процессом, а серия отказов длится минутами.
    fails = 0
    if snap.get("error"):
        try:
            fails = int(json.loads(API_FAIL_PATH.read_text(
                encoding="utf-8")).get("streak", 0))
        except (OSError, ValueError):
            fails = 0
        fails += 1
    try:
        API_FAIL_PATH.write_text(json.dumps({"streak": fails, "ts": _now()}),
                                 encoding="utf-8")
    except OSError:
        logger.exception("risk_guard.api_fail_write_failed")

    decision = evaluate(snap, cfg, api_fails=fails)
    action = decision["action"]

    if action == "NONE":
        _breach_age_minutes(False, "kill")     # пробой снят — таймер сбросить
        _notify_clear()                        # вернулись в норму
        return "ok"

    base = {"action": action, "reason": decision["reason"],
            "unrealized_usd": snap.get("total_unrealized_usd"),
            "notional_usd": snap.get("total_notional_usd"),
            "leverage": snap.get("leverage"),
            "rows": snap.get("rows")}

    if action == "NOTIFY":
        # Ботов НЕ трогаем: до предела они работают на максимум.
        #
        # 2026-08-28: за двое суток журнал набрал 1088 записей NOTIFY —
        # плечо держалось на 1.16x, условие ПОСТОЯННОЕ, а писалось каждый
        # тик. Это состояние, а не событие. Пишем только смену: вход в
        # условие и смену причины.
        if _notify_changed(decision["reason"]):
            _journal({"event": "NOTIFY", **base})
        if send_fn and _alert_due(cfg):
            send_fn(f"⚠️ {decision['reason']}\n"
                    f"Боты работают, ничего не остановлено. "
                    f"Мешок ${snap['total_unrealized_usd']:,.0f}, "
                    f"номинал ${snap['total_notional_usd']:,.0f}, "
                    f"плечо {snap['leverage']}x.")
        return "notify"

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
    # Выдержка по времени проверяется ТОЛЬКО перед закрытием: если
    # закрывать нельзя, ждать нечего — пауза уже сделана выше.
    if not cfg.get("allow_close"):
        _journal({"event": "LIMIT_NO_CLOSE", **base, "paused": paused})
        if send_fn and _alert_due(cfg):
            send_fn(f"🚨 ПРЕДЕЛ УБЫТКА: {decision['reason']}\n"
                    f"Боты остановлены: {', '.join(paused) or 'уже стояли'}.\n"
                    f"ПОЗИЦИИ НЕ ЗАКРЫТЫ — закрытие выключено тобой.\n"
                    f"Номинал ${snap['total_notional_usd']:,.0f}, "
                    f"плечо {snap['leverage']}x.\n"
                    f"Справка: на истории после этого порога мешок за 48ч "
                    f"единственный чистый эпизод 19.08 углубился с −$1 121 "
                    f"до −$13 842 за 48ч.")
        return "limit_no_close"

    # Закрытие разрешено — но пробой должен ДЕРЖАТЬСЯ, а не мелькнуть на
    # фитиле. Оператор 27.08: «не только при наступлении минус 400, а если
    # этот минус держится какой-то промежуток времени».
    char = move_character(int((cfg.get("persistence") or {})
                              .get("efficiency_lookback_hours", 24)))
    need, why = required_hold_minutes(cfg, char)
    age = _breach_age_minutes(True, "kill")
    if age < need:
        _journal({"event": "LIMIT_WAITING", **base, "held_minutes": round(age),
                  "need_minutes": need, "character": char, "why": why})
        if send_fn and _alert_due(cfg):
            send_fn(f"⚠️ Предел убытка задет: {decision['reason']}\n"
                    f"Держится {age:.0f} из {need:.0f} мин — {why}.\n"
                    f"Боты остановлены, позиции пока не тронуты.")
        return "limit_waiting"

    targets = decision.get("bots")
    if targets is None:                      # страховка портфеля — все
        targets = [{**r, "close_fraction": 1.0} for r in snap.get("rows", [])]

    full = [t for t in targets if t["close_fraction"] >= 0.999]
    part = [t for t in targets if t["close_fraction"] < 0.999]

    closed, failed = [], []
    if full:
        c, f = _close_all(api, {"rows": full})
        closed += c
        failed += f
    for t in part:
        done, fl = _reduce_positions(api, {"rows": [t]},
                                     t["close_fraction"], cfg)
        closed += [f"{d} ({t['close_fraction']*100:.0f}%)" for d in done]
        failed += fl

    _journal({"event": "KILL", **base, "paused": paused,
              "closed": closed, "failed": failed,
              "targets": [{"alias": t["alias"],
                           "fraction": t["close_fraction"]} for t in targets]})
    # Замораживаем только при ПОЛНОМ закрытии всего: частичное сокращение —
    # штатная работа, служба должна следить дальше.
    if full and not part:
        freeze("полное закрытие — разбор вручную", base)
    if send_fn:
        send_fn(f"🚨 RISK GUARD\n{decision['reason']}\n"
                f"Закрыто: {', '.join(closed) or '—'}\n"
                + (f"НЕ УДАЛОСЬ: {', '.join(failed)}\n" if failed else ""))
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
