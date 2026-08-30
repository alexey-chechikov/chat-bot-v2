"""Теневой хедж инвентаря — считает, но НЕ торгует.

Зачем именно так, а не сразу боевой хедж.

КАКИМ ИНСТРУМЕНТОМ КРОЕМ. Оператор 30.08 поправил мою конструкцию, и
его вариант чище. Я собирался крыть встречной позицией на ТОМ ЖЕ
инструменте и упёрся в режим позиций OKX: в net-режиме встречный ордер
не создаёт хедж, а УМЕНЬШАЕТ позицию — то есть закрывал бы ордера
GinArea, воюя с ботом. Переключение в long/short требует нулевых позиций
и может сломать сами боты.

Крыть надо ДРУГИМ КОНТРАКТОМ на тот же актив: шорт сетки на линейном
BTC-USDT-SWAP кроется лонгом на инверсном BTC-USD-SWAP. Это разные
инструменты, позиции по ним не неттятся, режим позиций между ними не
действует — проблема исчезает целиком.

Ошибка слежения — базис между контрактами. Замерен 30.08, шесть проб:
BTC +0.006% (разброс 0.012 п.п.), ETH +0.012% (разброс 0.013 п.п.). На
позиции $2 000 это $0.11-0.24, то есть пренебрежимо.

Остаётся одно препятствие: торговых ключей OKX в окружении нет ни одного
(проверено по именам переменных, значения не читались).

Поэтому первая фаза: служба считает, каким должен быть хедж и что именно
она бы сделала, и пишет это в журнал. Ноль ордеров, ноль ключей. За
неделю работы получаем живые числа — частоту перебалансировок, остаточную
экспозицию, стоимость — на реальных данных, а не на симуляции по снимкам.

Основание — docs/RESEARCH/HEDGE_STRATEGY_2026-08-30.md: направленная
часть сетки убыточна по построению (позиция при росте цены против
падения 1.17x у BTC_c и 1.70x у BTC SHORT; после роста +$5, после
падения −$3), симуляция дала снятие $11 360 экспозиции ценой $149.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "state" / "hedge_shadow_config.json"
JOURNAL_PATH = ROOT / "state" / "hedge_shadow_journal.jsonl"
STATE_PATH = ROOT / "state" / "hedge_shadow_state.json"

POLL_INTERVAL_SEC = 300           # 1.75 перебалансировки в сутки — чаще незачем


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _journal(rec: dict) -> None:
    try:
        with JOURNAL_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps({**rec, "ts": _now()}, ensure_ascii=False) + "\n")
    except OSError:
        logger.exception("hedge_shadow.journal_failed")


def load_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _read_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_state(d: dict) -> None:
    try:
        STATE_PATH.write_text(json.dumps(d, ensure_ascii=False, indent=1),
                              encoding="utf-8")
    except OSError:
        logger.exception("hedge_shadow.state_write_failed")


def compute_hedge(position_coin: float, price: float, current_hedge: float,
                  cfg: dict) -> dict:
    """Каким должен быть хедж и надо ли его двигать.

    Хедж встречный: позиция сетки −0.05 BTC → хедж +0.05 BTC.
    Двигаем, только если отклонение больше полосы И сделка крупнее
    минимальной — иначе комиссия съедает саму перебалансировку.
    Полоса 5% и минимум $50 взяты из замера: шире 10% начинает течь
    остаток, на 50% слежение разваливается (−$2 658 за 16 суток).
    """
    band = float(cfg.get("rebalance_band", 0.05))
    min_usd = float(cfg.get("min_trade_usd", 50.0))
    want = -float(position_coin)
    delta = want - float(current_hedge)
    delta_usd = abs(delta) * price
    need = (delta_usd >= min_usd
            and abs(delta) > max(abs(want), 1e-12) * band)
    return {"want_hedge": want, "current_hedge": float(current_hedge),
            "delta": delta, "delta_usd": round(delta_usd, 2),
            "should_rebalance": bool(need),
            "side": ("buy" if delta > 0 else "sell") if need else None,
            "net_exposure_coin": float(position_coin) + float(current_hedge)}


def _bot_positions(api, cfg: dict) -> list[dict]:
    """Позиции ботов В МОНЕТАХ и цена. Инверсный переводим из контрактов."""
    from services.order_harvester.loop import okx_price
    out = []
    for bid, b in (cfg.get("bots") or {}).items():
        try:
            st = api.get_stat(int(bid))
        except Exception:
            logger.exception("hedge_shadow.stat_failed bot=%s", bid)
            continue
        price = okx_price(b.get("inst_id", ""))
        if not price:
            continue
        pos = float(st.position or 0.0)
        if b.get("inverse"):
            pos = pos / price          # долларовые контракты -> монета
        # Хедж ставится на ДРУГОЙ контракт того же актива: линейную сетку
        # кроем инверсным контрактом и наоборот. Иначе в net-режиме OKX
        # встречный ордер уменьшил бы позицию самого бота.
        hedge_inst = b.get("hedge_inst_id")
        if not hedge_inst:
            inst = str(b.get("inst_id", ""))
            hedge_inst = (inst.replace("-USDT-", "-USD-") if "-USDT-" in inst
                          else inst.replace("-USD-", "-USDT-"))
        out.append({"bot_id": bid, "alias": b.get("alias", bid),
                    "inst_id": b.get("inst_id"), "hedge_inst": hedge_inst,
                    "position_coin": pos, "price": price,
                    "notional_usd": round(abs(pos) * price, 2)})
    return out


def tick(api=None) -> str:
    cfg = load_config()
    if not cfg.get("enabled"):
        return "disabled"
    if api is None:
        from services.order_harvester.loop import _cached_api
        api = _cached_api()
        if api is None:
            return "no_api"

    state = _read_state()
    hedges = state.setdefault("hedges", {})
    stats = state.setdefault("stats", {"rebalances": 0, "fees_usd": 0.0,
                                       "hedge_pnl_usd": 0.0})
    fee_side = float(cfg.get("fee_side_pct", 0.05)) / 100.0

    rows = _bot_positions(api, cfg)
    if not rows:
        return "no_positions"

    acted = 0
    for r in rows:
        bid = r["bot_id"]
        prev = hedges.get(bid, {"size": 0.0, "price": r["price"]})
        # PnL теневого хеджа с прошлого тика
        pnl = float(prev["size"]) * (r["price"] - float(prev["price"]))
        stats["hedge_pnl_usd"] = round(stats["hedge_pnl_usd"] + pnl, 2)

        d = compute_hedge(r["position_coin"], r["price"], prev["size"], cfg)
        if d["should_rebalance"]:
            fee = d["delta_usd"] * fee_side
            stats["fees_usd"] = round(stats["fees_usd"] + fee, 2)
            stats["rebalances"] += 1
            acted += 1
            _journal({"event": "WOULD_REBALANCE", "alias": r["alias"],
                      "grid_inst": r["inst_id"],
                      "hedge_inst": r["hedge_inst"], "side": d["side"],
                      "size_coin": round(abs(d["delta"]), 8),
                      "size_usd": d["delta_usd"], "fee_usd": round(fee, 2),
                      "bot_position_coin": round(r["position_coin"], 8),
                      "hedge_from": round(d["current_hedge"], 8),
                      "hedge_to": round(d["want_hedge"], 8)})
            hedges[bid] = {"size": d["want_hedge"], "price": r["price"]}
        else:
            hedges[bid] = {"size": prev["size"], "price": r["price"]}

    state["last_tick"] = _now()
    state["net_exposure_usd"] = round(
        sum((r["position_coin"] + hedges[r["bot_id"]]["size"]) * r["price"]
            for r in rows), 2)
    _write_state(state)
    return f"acted:{acted}" if acted else "ok"


async def hedge_shadow_loop(stop_event=None) -> None:
    logger.info("hedge_shadow.start interval=%ds (ТЕНЕВОЙ, не торгует)",
                POLL_INTERVAL_SEC)
    while True:
        if stop_event is not None and stop_event.is_set():
            return
        try:
            tick()
        except Exception:
            logger.exception("hedge_shadow.tick_failed")
        try:
            if stop_event is not None:
                await asyncio.wait_for(stop_event.wait(), POLL_INTERVAL_SEC)
                return
            await asyncio.sleep(POLL_INTERVAL_SEC)
        except asyncio.TimeoutError:
            continue
