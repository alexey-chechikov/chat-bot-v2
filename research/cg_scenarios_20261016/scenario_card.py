"""Pure offline CG-SR1 manual scenario cards; no forecasting or order execution."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

MINUTE = 60_000
M15 = 15 * MINUTE
HORIZON = 240 * MINUTE
VERSION = "CG-SR1-manual-card-0.1"
COST_RESERVE = Decimal("0.0008")
SOURCE_LAG_LIMIT_MS = 120_000
QUOTE_AGE_LIMIT_MS = 60_000
FIRST_QUOTE_DELAY_LIMIT_MS = 60_000


class InputError(ValueError):
    pass


def decimal(value: Any) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise InputError("expected finite decimal")
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise InputError("expected finite decimal") from exc
    if not result.is_finite():
        raise InputError("expected finite decimal")
    return result


def ms(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InputError("expected nonnegative integer UTC milliseconds")
    return value


def rounded(value: Decimal, step: Decimal, up: bool = False) -> Decimal:
    return (value / step).to_integral_value(rounding=ROUND_CEILING if up else ROUND_FLOOR) * step


@dataclass(frozen=True)
class Bar:
    ts: int
    o: Decimal
    h: Decimal
    l: Decimal
    c: Decimal


def parse_bars(rows: Any, interval: int, asof: int, tick: Decimal | None) -> dict[int, Bar]:
    if not isinstance(rows, list):
        raise InputError("OHLC input must be an array")
    result = {}
    previous = -1
    for row in rows:
        ts = ms(row["ts_ms"])
        if ts <= previous or ts % interval or ts + interval > asof:
            raise InputError("OHLC must be increasing unique aligned CLOSED UTC bars")
        o, h, l, c = [decimal(row[key]) for key in ("open", "high", "low", "close")]
        if min(o, h, l, c) <= 0 or l > min(o, c) or h < max(o, c) or l > h:
            raise InputError("inconsistent or nonpositive OHLC")
        if tick is not None and any(value % tick for value in (o, h, l, c)):
            raise InputError("OHLC is not on declared tick grid")
        result[ts] = Bar(ts, o, h, l, c)
        previous = ts
    return result


def aggregate_15m(bars: Mapping[int, Bar]) -> dict[int, Bar]:
    result = {}
    for start in sorted({ts // M15 * M15 for ts in bars}):
        group = [bars.get(ts) for ts in range(start, start + M15, MINUTE)]
        if all(bar is not None for bar in group):
            result[start] = Bar(start, group[0].o, max(bar.h for bar in group), min(bar.l for bar in group), group[-1].c)
    return result


def atr_before(bars: Mapping[int, Bar], seed: int, signal_start: int) -> Decimal | None:
    """Same causal 14-TR/real-prevclose seed and Wilder recurrence as CG-SR1 v0."""
    previous = None
    trs = []
    atr = None
    for ts in range(seed, signal_start, M15):
        bar = bars.get(ts)
        if bar is None:
            return None  # fixed path: no gap interpolation/reseed
        if previous is not None:
            tr = max(bar.h - bar.l, abs(bar.h - previous.c), abs(bar.l - previous.c))
            if atr is None:
                trs.append(tr)
                if len(trs) == 14:
                    atr = sum(trs) / Decimal(14)
            else:
                atr = (13 * atr + tr) / 14
        previous = bar
    return atr


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Mapping):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _flow_diagnostic(value: Any, asof: int) -> dict[str, Any]:
    output = {"used_as_filter": False, "status": "NOT_PROVIDED"}
    if value is None:
        return output
    try:
        spot, perp = value["spot"], value["perp"]
        starts = [ms(row["bar_start_ms"]) for row in (spot, perp)]
        if starts[0] != starts[1] or starts[0] % M15:
            raise InputError("F must refer to the same full UTC15m bar")
        for row, market in ((spot, "spot"), (perp, "perpetual")):
            if row.get("verified") is not True or row.get("exchange") != "Binance" or row.get("symbol") != "BTCUSDT" or row.get("market") != market:
                raise InputError("unverified F/source")
            received = ms(row["received_ms"])
            if not starts[0] + M15 <= received <= asof:
                raise InputError("F not yet closed/received")
            if not -1 <= decimal(row["F"]) <= 1:
                raise InputError("F out of range")
        output.update(status="AVAILABLE_DIAGNOSTIC_ONLY", bar_start_ms=starts[0],
                      spot_F=decimal(spot["F"]), perp_F=decimal(perp["F"]))
    except (InputError, KeyError, TypeError, AttributeError) as exc:
        output.update(status="UNAVAILABLE", reason=str(exc))
    return output


def build_card(data: Mapping[str, Any], *, synthetic: bool = False) -> dict[str, Any]:
    """Build a JSON-compatible manual card; no I/O, mutation, fills, PnL or probabilities."""
    if data.get("schema_version") != "cg-manual-scenario-v1" or data.get("synthetic") is not synthetic:
        raise InputError("explicit schema/synthetic marker mismatch")
    asof = ms(data.get("data_asof_ms"))
    snapshot = data.get("snapshot", {})
    card = {"version": VERSION, "synthetic": synthetic, "snapshot_id": snapshot.get("snapshot_id"),
            "status": "WAIT", "setup": None, "reasons": [], "trade_permission": False,
            "primary_admitted": False, "conditions_passed": False, "source_lag_status": "UNKNOWN",
            "data_asof_ms": asof, "entry": None, "stop": None, "target": None, "quantity": None,
            "signal": None, "attempt_consumed": False,
            "cost_reserve": COST_RESERVE, "research_risk_usdt": Decimal(25), "notional_cap_usdt": Decimal(10000),
            "flow": _flow_diagnostic(data.get("flows"), asof),
            "continuation": {"status": "UNCONFIRMED", "executable": False},
            "scope": "manual research card; declared provenance only; no orders/fills/profitability established"}
    unknown, failures = [], []
    if not isinstance(snapshot.get("snapshot_id"), str) or not snapshot["snapshot_id"].strip():
        failures.append("MISSING_SNAPSHOT_ID")

    def finish(status: str, reasons: list[str]) -> dict[str, Any]:
        card.update(status=status, reasons=list(dict.fromkeys(reasons)))
        return _jsonable(card)

    # Source settings: absent != false/verified. No fabricated metadata admission.
    settings = snapshot.get("settings", {})
    for key, expected in {"provider": "CoinGlass", "product": "liquidation_heatmap", "model": "model1",
                          "exchange": "Binance", "symbol": "BTCUSDT", "market": "perpetual", "lookback": "24h"}.items():
        actual = settings.get(key)
        if actual is None:
            unknown.append("UNKNOWN_SETTINGS")
        elif actual != expected:
            failures.append("WRONG_SETTINGS")
    if settings.get("threshold") is None:
        unknown.append("UNKNOWN_SETTINGS")
    elif decimal(settings["threshold"]) != Decimal("0.85"):
        failures.append("WRONG_SETTINGS")
    for key in ("source_record_complete", "source_record_fresh", "annotation_frozen"):
        if snapshot.get(key) is False:
            failures.append(key.upper() + "_FALSE")
        elif snapshot.get(key) is not True:
            unknown.append("UNKNOWN_" + key.upper())
    try:
        capture, lock = ms(snapshot["capture_ms"]), ms(snapshot["annotation_lock_ms"])
    except (InputError, KeyError):
        return finish("NO_TRADE" if failures else "WAIT", failures + unknown + ["UNKNOWN_FREEZE_TIME"])
    freeze = max(capture, lock)
    t0 = (freeze // MINUTE + 1) * MINUTE
    deadline = t0 + HORIZON
    card.update(freeze_ms=freeze, t0_ms=t0, deadline_ms=deadline,
                exit_rule="exit at the exact original deadline 1m-open; missing open is unknown, no late fill")
    if freeze > asof:
        failures.append("FREEZE_AFTER_DATA_ASOF")
    source_asof = snapshot.get("source_asof_ms")
    if snapshot.get("lag_status") == "unknown" or source_asof is None:
        unknown.append("UNKNOWN_SOURCE_LAG_OUTSIDE_PRIMARY")
    else:
        source_asof = ms(source_asof)
        lag = capture - source_asof
        card.update(source_lag_status="KNOWN", source_lag_ms=lag)
        if lag < 0 or lag > SOURCE_LAG_LIMIT_MS:
            failures.append("SOURCE_TIMESTAMP_FUTURE_OR_STALE")
        if snapshot.get("lag_status") != "known":
            unknown.append("UNKNOWN_LAG_DECLARATION")
    try:
        lower = tuple(decimal(snapshot["lower_zone"][key]) for key in ("low", "high"))
        upper = tuple(decimal(snapshot["upper_zone"][key]) for key in ("low", "high"))
        spot = decimal(snapshot["frozen_spot"])
        if not 0 < lower[0] < lower[1] < spot < upper[0] < upper[1]:
            raise InputError("zone geometry")
    except (InputError, KeyError, TypeError):
        return finish("NO_TRADE", failures + ["MISSING_OR_INVALID_FROZEN_ZONES"])
    card.update(lower_zone=lower, upper_zone=upper, frozen_spot=spot,
                scenarios={"LONG_RECLAIM": {"condition": f"полная UTC15m начинается >= t0; low < {lower[0]} и close > {lower[1]}",
                                             "target": upper[0], "stop_rule": "low сигнала − 0.1 предыдущего ATR14, округлить вниз по tick"},
                           "SHORT_RECLAIM": {"condition": f"полная UTC15m начинается >= t0; high > {upper[1]} и close < {upper[0]}",
                                              "target": lower[1], "stop_rule": "high сигнала + 0.1 предыдущего ATR14, округлить вверх по tick"}},
                refusal_rules=["обе зоны в одной свече", "нет закрытого reclaim", "источник/quote неизвестен или устарел", "попытка использована или позиция открыта",
                               "нет причинного ATR/нужной цены", "направленная геометрия стопа/цели неверна", "net RR с резервом 8bp < 2", "срок истёк"])
    attempt_state = data.get("attempt_state")
    if attempt_state in ("consumed", "position_open"):
        card["attempt_consumed"] = True
        failures.append("ATTEMPT_CONSUMED" if attempt_state == "consumed" else "PORTFOLIO_BUSY")
    elif attempt_state != "unused":
        unknown.append("UNKNOWN_ATTEMPT_STATE")
    if asof >= deadline:
        failures.append("DEADLINE_REACHED")
    contract = data.get("contract", {})
    tick, step = None, None
    minimum_quantity, minimum_notional = None, None
    for key, expected in {"exchange": "Binance", "symbol": "BTCUSDT", "market": "perpetual"}.items():
        if contract.get(key) is None:
            unknown.append("UNKNOWN_CONTRACT_BINDING")
        elif contract[key] != expected:
            failures.append("WRONG_CONTRACT_BINDING")
    if contract.get("verified") is False:
        failures.append("CONTRACT_UNVERIFIED")
    elif contract.get("verified") is not True:
        unknown.append("UNKNOWN_CONTRACT")
    try:
        tick, step = decimal(contract["tick_size"]), decimal(contract["quantity_step"])
        if min(tick, step) <= 0:
            failures.append("INVALID_TICK_STEP")
            tick, step = None, None
        verified_at = ms(contract["verified_at_ms"])
        if verified_at > asof:
            failures.append("CONTRACT_VERIFICATION_IN_FUTURE")
        if not isinstance(contract.get("verification_source"), str) or not contract["verification_source"].strip():
            unknown.append("UNKNOWN_CONTRACT_SOURCE")
    except (InputError, KeyError):
        unknown.append("UNKNOWN_CONTRACT")
        tick, step, verified_at = None, None, None
    try:
        minimum_quantity = decimal(contract["min_quantity"])
        minimum_notional = decimal(contract["min_notional"])
        if min(minimum_quantity, minimum_notional) < 0:
            failures.append("INVALID_CONTRACT_MINIMUMS")
    except (InputError, KeyError):
        unknown.append("UNKNOWN_CONTRACT_MINIMUMS")
    source = data.get("price_source", {})
    for key, expected in {"exchange": "Binance", "symbol": "BTCUSDT", "market": "perpetual", "timezone": "UTC"}.items():
        if source.get(key) is None:
            unknown.append("UNKNOWN_PRICE_SOURCE")
        elif source[key] != expected:
            failures.append("WRONG_PRICE_SOURCE")
    if failures:
        return finish("NO_TRADE", failures + unknown)
    try:
        one = parse_bars(data.get("ohlc_1m", []), MINUTE, asof, tick)
        fifteen = parse_bars(data.get("ohlc_15m", []), M15, asof, tick)
        derived = aggregate_15m(one)
        for ts, bar in fifteen.items():
            if ts in derived and bar != derived[ts]:
                raise InputError("1m/15m OHLC mismatch")
            if one and min(one) <= ts and ts + M15 <= max(one) + MINUTE and ts not in derived:
                raise InputError("1m coverage gap inside supplied 15m bar")
        bars = dict(fifteen)
        bars.update(derived)
        seed = ms(data["atr_seed_start_ms"])
        if seed % M15:
            raise InputError("ATR seed must align to UTC15m")
    except (InputError, KeyError, TypeError) as exc:
        return finish("NO_TRADE", ["INVALID_OR_MISSING_PRICE_DATA", str(exc)] + unknown)
    if bars:
        latest = bars[max(bars)]
        card["latest_closed_price"] = {"close": latest.c, "bar_close_ms": latest.ts + M15}
        if latest.c > upper[1]:
            card["continuation"] = {"status": "UP_DIAGNOSTIC_ONLY", "executable": False,
                                    "condition": f"15m close > {upper[1]}", "invalidation": f"15m close <= {upper[1]}"}
        elif latest.c < lower[0]:
            card["continuation"] = {"status": "DOWN_DIAGNOSTIC_ONLY", "executable": False,
                                    "condition": f"15m close < {lower[0]}", "invalidation": f"15m close >= {lower[0]}"}
    # Search only closed bars and stop at first candidate/ambiguity/gap.
    candidate = None
    for start in range((t0 + M15 - 1) // M15 * M15, min(asof, deadline - 1) - M15 + 1, M15):
        bar = bars.get(start)
        if bar is None:
            return finish("NO_TRADE", ["MISSING_SIGNAL_BAR"] + unknown)
        if bar.l <= lower[1] and bar.h >= upper[0]:
            card.update(attempt_consumed=True, signal={"start_ms": start, "close_ms": start + M15})
            return finish("NO_TRADE", ["BOTH_ZONES_IN_SIGNAL_BAR"] + unknown)
        side = 1 if bar.l < lower[0] and bar.c > lower[1] else (-1 if bar.h > upper[1] and bar.c < upper[0] else 0)
        if side:
            candidate = bar, side
            break
    if candidate is None:
        return finish("WAIT", unknown + ["WAIT_FOR_FIRST_CLOSED_RECLAIM"])
    bar, side = candidate
    close_ms = bar.ts + M15
    card.update(setup="LONG_RECLAIM" if side == 1 else "SHORT_RECLAIM", attempt_consumed=True,
                signal={"start_ms": bar.ts, "close_ms": close_ms, "low": bar.l, "high": bar.h, "close": bar.c})
    atr = atr_before(bars, seed, bar.ts)
    if atr is None:
        return finish("NO_TRADE", ["MISSING_PREVIOUS_ATR14"] + unknown)
    card["previous_atr14"] = atr
    if tick is None or step is None:
        return finish("CONDITIONAL", unknown + ["NO_VERIFIED_TICK_STEP"])
    stop = rounded(bar.l - atr / 10, tick) if side == 1 else rounded(bar.h + atr / 10, tick, True)
    target = upper[0] if side == 1 else lower[1]
    card.update(stop=stop, target=target)
    card["price_invalidation"] = {
        "before_entry": f"E строго {'выше S и ниже T' if side == 1 else 'ниже S и выше T'}; иначе NO_TRADE",
        "after_entry": f"{'LONG' if side == 1 else 'SHORT'} защитный стоп S={stop}: цена {'<=' if side == 1 else '>='} S; исходный срок не меняется",
    }
    if target % tick or stop <= 0:
        return finish("NO_TRADE", ["INVALID_TARGET_TICK_OR_STOP"] + unknown)
    quote = data.get("next_available_quote")
    if quote is None:
        return finish("CONDITIONAL", unknown + ["ENTRY_QUOTE_NOT_PROVIDED_NO_RR_ADMISSION"])
    if not isinstance(quote, Mapping):
        return finish("NO_TRADE", ["INVALID_QUOTE_RECORD"] + unknown)
    if any(quote.get(key) is None for key in ("price", "received_ms", "signal_close_ms")):
        return finish("CONDITIONAL", unknown + ["ENTRY_QUOTE_PRICE_OR_TIMING_UNKNOWN_NO_RR_ADMISSION"])
    try:
        received = ms(quote["received_ms"])
        entry = decimal(quote["price"])
        if not close_ms <= received <= asof or received >= deadline or ms(quote["signal_close_ms"]) != close_ms:
            raise InputError("QUOTE_TIMING_INVALID")
        if received - close_ms > FIRST_QUOTE_DELAY_LIMIT_MS:
            raise InputError("LATE_FIRST_ENTRY_QUOTE")
        if asof - received > QUOTE_AGE_LIMIT_MS:
            raise InputError("QUOTE_STALE")
        if entry <= 0 or entry % tick:
            raise InputError("QUOTE_PRICE_INVALID")
        if verified_at is None or verified_at > received:
            raise InputError("CONTRACT_RULES_UNAVAILABLE_AT_QUOTE")
        if quote.get("executable") is not True or quote.get("first_available_after_close") is not True:
            return finish("CONDITIONAL", unknown + ["QUOTE_EXECUTABILITY_OR_FIRST_RECEIPT_UNVERIFIED"])
        for key, expected in {"exchange": "Binance", "symbol": "BTCUSDT", "market": "perpetual", "side": "BUY" if side == 1 else "SELL"}.items():
            if quote.get(key) != expected:
                raise InputError("QUOTE_SOURCE_OR_SIDE_MISMATCH")
    except (InputError, KeyError, TypeError) as exc:
        return finish("NO_TRADE", [str(exc)] + unknown)
    card.update(entry=entry, entry_received_ms=received)
    if side * (entry - stop) <= 0 or side * (target - entry) <= 0:
        return finish("NO_TRADE", ["INVALID_SIGNED_GEOMETRY"] + unknown)
    distance, gain = abs(entry - stop), abs(target - entry)
    rr = (gain - COST_RESERVE * entry) / (distance + COST_RESERVE * entry)
    q = rounded(min(Decimal(25) / (distance + COST_RESERVE * entry), Decimal(10000) / entry), step)
    card.update(net_rr_reserve8bp=rr, quantity=q, entry_notional=q * entry,
                planned_loss_with_reserve=q * (distance + COST_RESERVE * entry))
    if rr < 2 or q <= 0:
        return finish("NO_TRADE", ["NET_RR_BELOW_2" if rr < 2 else "QUANTITY_ROUNDED_TO_ZERO"] + unknown)
    minimum_failures = []
    if minimum_quantity is not None and q < minimum_quantity:
        minimum_failures.append("BELOW_CONTRACT_MIN_QUANTITY")
    if minimum_notional is not None and q * entry < minimum_notional:
        minimum_failures.append("BELOW_CONTRACT_MIN_NOTIONAL")
    if minimum_failures:
        return finish("NO_TRADE", minimum_failures + unknown)
    if unknown:
        return finish("CONDITIONAL", unknown)
    card["conditions_passed"] = True
    # Manual utility is not a provenance auditor or an admission to the v0 series.
    return finish("READY_RESEARCH", [])


def utc(value: Any) -> str:
    return "неизвестно" if value is None else datetime.fromtimestamp(value / 1000, timezone.utc).isoformat().replace("+00:00", "Z")


def render_markdown(card: Mapping[str, Any]) -> str:
    """Readable card, no additional calculations or invented entry anchor."""
    lines = ["# CG-SR1 — ручная исследовательская карточка", "",
             f"**Состояние: {card['status']}**; setup: {card.get('setup') or 'ещё нет'}. Автоордеров и разрешения на торговлю нет.",
             f"Synthetic: {str(card['synthetic']).lower()}. Снимок: {json.dumps(card.get('snapshot_id'), ensure_ascii=False)}.", "",
             "Карта не прогнозирует цену. Условия ниже проверяются по цене и закрытым свечам.", "",
             f"t0: {utc(card.get('t0_ms'))}; срок: {utc(card.get('deadline_ms'))}.", ""]
    for name, scenario in card.get("scenarios", {}).items():
        lines.append(f"- {name}: {scenario['condition']}; стоп: {scenario['stop_rule']}; цель: {scenario['target']}.")
    invalidation = card.get("price_invalidation")
    price_cancel = (f"До входа: {invalidation['before_entry']}. После условного входа: {invalidation['after_entry']}."
                    if invalidation else "До подтверждённой свечи S неизвестен; после входа LONG отменяется по S=low сигнала−0.1 предыдущего ATR, SHORT по S=high+0.1 ATR, с округлением от цены. До этого входа нет.")
    gate_text = {
        "WAIT_FOR_FIRST_CLOSED_RECLAIM": "Нет первой полной закрытой reclaim-свечи; касание не даёт входа.",
        "UNKNOWN_SOURCE_LAG_OUTSIDE_PRIMARY": "Нет заверенного source_asof: задержка неизвестна, основной допуск отсутствует.",
        "UNKNOWN_SOURCE_RECORD_FRESH": "Свежесть снимка не подтверждена.",
        "UNKNOWN_SETTINGS": "Не все настройки карты известны.",
        "UNKNOWN_CONTRACT": "Не объявлены проверенные tick/step контракта.",
        "UNKNOWN_CONTRACT_MINIMUMS": "Не объявлены проверенные min quantity/min notional.",
        "UNKNOWN_CONTRACT_BINDING": "Спецификация не привязана к точному контракту.",
        "ENTRY_QUOTE_NOT_PROVIDED_NO_RR_ADMISSION": "Нет исполнимой E: RR и размер не рассчитаны, вход не допущен.",
        "ENTRY_QUOTE_PRICE_OR_TIMING_UNKNOWN_NO_RR_ADMISSION": "Цена или время E неизвестны: вход не допущен.",
        "QUOTE_EXECUTABILITY_OR_FIRST_RECEIPT_UNVERIFIED": "Исполнимость/первое получение котировки не подтверждены.",
        "LATE_FIRST_ENTRY_QUOTE": "Первая котировка позже 60 секунд после закрытия сигнала: пропустить поздний вход.",
        "QUOTE_STALE": "Котировка старше 60 секунд к текущему data_asof.",
        "NET_RR_BELOW_2": "Net R/R после единственного резерва 8bp меньше 2: отказ.",
        "INVALID_SIGNED_GEOMETRY": "E за стопом/целью или на их границе: отказ.",
        "MISSING_PREVIOUS_ATR14": "Не хватает полной причинной истории предыдущего ATR14.",
        "BOTH_ZONES_IN_SIGNAL_BAR": "Одна свеча затронула обе зоны: снимок расходуется без входа.",
        "DEADLINE_REACHED": "Исходный срок истёк; новый вход запрещён.",
        "PORTFOLIO_BUSY": "Уже есть позиция: вход пропустить без откладывания.",
        "ATTEMPT_CONSUMED": "Попытка снимка уже использована; повторного входа нет.",
    }
    missing_gates = [gate_text.get(reason, reason) for reason in card["reasons"]]
    lines += ["", f"E: {card.get('entry') if card.get('entry') is not None else 'неизвестна; цену close/зоны не подставлять'}; S: {card.get('stop') if card.get('stop') is not None else 'ещё неизвестен'}; T: {card.get('target') if card.get('target') is not None else 'см. сценарии'}; q (исслед.): {card.get('quantity') if card.get('quantity') is not None else 'не рассчитан'}.",
              f"Net RR с единственным резервом 8bp: {card.get('net_rr_reserve8bp', 'не рассчитан; вход не допущен')}.",
              "Ценовая инвалидация: " + price_cancel,
              "Выход по сроку: точный 1m-open исходного deadline; пропущенный open не заменять поздним.", "",
              "Причины/ожидание: " + (", ".join(card["reasons"]) or "условия карточки прошли; исполнение/прибыльность не установлены"), "",
              "Отсутствующие допуски/отказы: " + (" ".join(missing_gates) or "декларативные проверки карточки пройдены; независимый допуск в торговлю отсутствует"), "",
              "Отказ: " + "; ".join(card.get("refusal_rules", [])), "",
              "Диагностика continuation (не вход): " + json.dumps(card["continuation"], ensure_ascii=False),
              "Spot/perp F (без фильтра): " + json.dumps(card["flow"], ensure_ascii=False), "",
              "Даже READY_RESEARCH — только исследовательская готовность условий. Снимок не принят этой карточкой в primary-серию; ордер и результат не моделируются.", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--json-out", required=True, type=Path)
    parser.add_argument("--md-out", required=True, type=Path)
    parser.add_argument("--synthetic", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.json_out.resolve() == args.md_out.resolve() or args.json_out.exists() or args.md_out.exists():
            raise InputError("output files must be distinct and new")
        payload = args.input.read_bytes()
        data = json.loads(payload.decode("utf-8-sig"))
        card = build_card(data, synthetic=args.synthetic)
        card["input_sha256"] = hashlib.sha256(payload).hexdigest()
        markdown = render_markdown(card)
        with args.json_out.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(card, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        with args.md_out.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(markdown)
        print(json.dumps({key: card[key] for key in ("version", "synthetic", "status", "setup", "reasons")}, ensure_ascii=False))
        return 0
    except (InputError, OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
