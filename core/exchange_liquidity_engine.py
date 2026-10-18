from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import requests

try:
    import websocket  # type: ignore
except Exception:  # pragma: no cover
    websocket = None

logger = logging.getLogger(__name__)

STATE_FILE = Path(os.getenv('EXCHANGE_LIQUIDITY_STATE_FILE', 'state/exchange_liquidity_state.json'))
SYMBOL = os.getenv('EXCHANGE_LIQUIDITY_SYMBOL', 'BTCUSDT').upper()
MAX_EVENTS = int(os.getenv('EXCHANGE_LIQUIDITY_MAX_EVENTS', '500'))
BINANCE_WS = os.getenv('BINANCE_FUTURES_WS', 'wss://fstream.binance.com/market/ws')
BYBIT_WS = os.getenv('BYBIT_PUBLIC_WS', 'wss://stream.bybit.com/v5/public/linear')
BINANCE_REST = os.getenv('BINANCE_FUTURES_REST', 'https://fapi.binance.com')
BYBIT_REST = os.getenv('BYBIT_REST', 'https://api.bybit.com')
POLL_SEC = int(os.getenv('EXCHANGE_LIQUIDITY_POLL_SEC', '45'))
WINDOW_MINUTES = int(os.getenv('EXCHANGE_LIQUIDITY_WINDOW_MINUTES', '180'))
PRICE_BUCKET_USD = float(os.getenv('EXCHANGE_LIQUIDITY_PRICE_BUCKET_USD', '50'))

_STARTED = False
_LOCK = threading.RLock()
_LAST_ERROR_LOG: dict[str, float] = {}


def _log_ws_issue_once(label: str, exc: Exception) -> None:
    now = time.time()
    last = _LAST_ERROR_LOG.get(label, 0.0)
    if now - last >= 60:
        logger.warning('%s: %s: %s', label, type(exc).__name__, exc)
        _LAST_ERROR_LOG[label] = now


def _now_ms() -> int:
    return int(time.time() * 1000)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _default_state() -> Dict[str, Any]:
    return {
        'symbol': SYMBOL,
        'events': [],
        'metrics': {},
        'status': {'started_at': _iso_now(), 'source': 'exchange_real_liquidity'},
    }


def _load_state() -> Dict[str, Any]:
    if not STATE_FILE.exists():
        return _default_state()
    raw = STATE_FILE.read_text(encoding='utf-8').strip()
    if not raw:
        return _default_state()
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else _default_state()
    except json.JSONDecodeError:
        try:
            decoder = json.JSONDecoder()
            obj, end = decoder.raw_decode(raw)
            if isinstance(obj, dict):
                logger.warning('exchange_liquidity.load_state_salvaged extra_data_at=%s', end)
                _save_state(obj)
                return obj
        except Exception:
            pass
        logger.exception('exchange_liquidity.load_state_failed')
        try:
            broken = STATE_FILE.with_suffix(STATE_FILE.suffix + '.broken')
            STATE_FILE.replace(broken)
        except Exception:
            logger.exception('exchange_liquidity.backup_broken_state_failed')
        return _default_state()
    except Exception:
        logger.exception('exchange_liquidity.load_state_failed')
        return _default_state()


def _save_state(state: Dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state, ensure_ascii=False, indent=2)
    with _LOCK:
        last_exc: Exception | None = None
        for attempt in range(5):
            tmp_file = STATE_FILE.with_name(f"{STATE_FILE.name}.{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex}.tmp")
            try:
                tmp_file.write_text(payload, encoding='utf-8')
                os.replace(str(tmp_file), str(STATE_FILE))
                return
            except FileNotFoundError as exc:
                last_exc = exc
                time.sleep(0.05 * (attempt + 1))
            except PermissionError as exc:
                last_exc = exc
                time.sleep(0.05 * (attempt + 1))
            finally:
                try:
                    if tmp_file.exists():
                        tmp_file.unlink()
                except Exception:
                    pass
        if last_exc is not None:
            raise last_exc


def _mutate_state(mutator) -> Dict[str, Any]:
    with _LOCK:
        state = _load_state()
        updated = mutator(state)
        state = updated if isinstance(updated, dict) else state
        _save_state(state)
        return state


def _touch_status(**kwargs: Any) -> None:
    def _apply(state: Dict[str, Any]) -> Dict[str, Any]:
        status = state.setdefault('status', {})
        for key, value in kwargs.items():
            status[key] = value
        return state
    _mutate_state(_apply)


def _mark_ws_connected(exchange: str, connected: bool) -> None:
    def _apply(state: Dict[str, Any]) -> Dict[str, Any]:
        status = state.setdefault('status', {})
        ws = status.setdefault('ws', {})
        row = ws.setdefault(exchange, {})
        row['connected'] = bool(connected)
        row['updated_at'] = _iso_now()
        return state
    _mutate_state(_apply)


def _mark_ws_message(exchange: str) -> None:
    def _apply(state: Dict[str, Any]) -> Dict[str, Any]:
        status = state.setdefault('status', {})
        ws = status.setdefault('ws', {})
        row = ws.setdefault(exchange, {})
        row['last_message_at'] = _iso_now()
        row['last_message_ts'] = _now_ms()
        row['connected'] = True
        return state
    _mutate_state(_apply)


def _inc_restart(exchange: str) -> None:
    def _apply(state: Dict[str, Any]) -> Dict[str, Any]:
        status = state.setdefault('status', {})
        ws = status.setdefault('ws', {})
        row = ws.setdefault(exchange, {})
        row['restart_count'] = int(row.get('restart_count') or 0) + 1
        row['last_restart_at'] = _iso_now()
        return state
    _mutate_state(_apply)


def _trim_events(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    cutoff = _now_ms() - WINDOW_MINUTES * 60 * 1000
    filtered = [e for e in events if _safe_int(e.get('ts')) >= cutoff]
    return filtered[-MAX_EVENTS:]


def _append_event(exchange: str, symbol: str, side: str, price: float, qty: float, notional: float, ts: int | None = None) -> None:
    symbol = (symbol or SYMBOL).upper()
    if symbol != SYMBOL:
        return
    def _apply(state: Dict[str, Any]) -> Dict[str, Any]:
        events = list(state.get('events') or [])
        events.append({
            'exchange': exchange,
            'symbol': symbol,
            'side': (side or '').upper(),
            'price': round(_safe_float(price), 2),
            'qty': round(_safe_float(qty), 6),
            'notional': round(_safe_float(notional), 2),
            'ts': _safe_int(ts or _now_ms()),
        })
        state['events'] = _trim_events(events)
        event_at = _iso_now()
        state.setdefault('status', {})['last_event_at'] = event_at
        state['status']['last_event_exchange'] = exchange
        ws = state['status'].setdefault('ws', {})
        row = ws.setdefault(exchange, {})
        row['last_message_at'] = event_at
        row['last_message_ts'] = _safe_int(ts or _now_ms())
        row['connected'] = True
        return state
    _mutate_state(_apply)


def _update_metrics(exchange: str, **kwargs: Any) -> None:
    def _apply(state: Dict[str, Any]) -> Dict[str, Any]:
        metrics = state.setdefault('metrics', {})
        ex_metrics = metrics.setdefault(exchange, {})
        for key, value in kwargs.items():
            ex_metrics[key] = value
        updated_at = _iso_now()
        ex_metrics['updated_at'] = updated_at
        status = state.setdefault('status', {})
        status['last_metrics_exchange'] = exchange
        status['last_metrics_at'] = updated_at
        return state
    _mutate_state(_apply)


def _set_error(label: str, error: str) -> None:
    def _apply(state: Dict[str, Any]) -> Dict[str, Any]:
        status = state.setdefault('status', {})
        errors = list(status.get('errors') or [])
        errors.append({'at': _iso_now(), 'label': label, 'error': error[:240]})
        status['errors'] = errors[-20:]
        return state
    _mutate_state(_apply)


def _bucket_price(price: float) -> float:
    if PRICE_BUCKET_USD <= 0:
        return round(price, 2)
    return round(round(price / PRICE_BUCKET_USD) * PRICE_BUCKET_USD, 2)


def _aggregate_events(events: List[Dict[str, Any]], price: float) -> Dict[str, Any]:
    above: Dict[float, float] = defaultdict(float)
    below: Dict[float, float] = defaultdict(float)
    recent_notional = 0.0
    recent_count = 0
    recent_ts_cutoff = _now_ms() - 15 * 60 * 1000
    for event in events:
        p = _safe_float(event.get('price'))
        n = abs(_safe_float(event.get('notional')))
        if p <= 0 or n <= 0:
            continue
        bucket = _bucket_price(p)
        if p >= price:
            above[bucket] += n
        else:
            below[bucket] += n
        if _safe_int(event.get('ts')) >= recent_ts_cutoff:
            recent_notional += n
            recent_count += 1

    def best_zone(side_map: Dict[float, float], current: float, prefer_above: bool) -> tuple[float, float]:
        if not side_map:
            return 0.0, 0.0
        ranked = sorted(side_map.items(), key=lambda kv: (-kv[1], abs(kv[0] - current)))
        return ranked[0]

    upper_price, upper_strength = best_zone(above, price, True)
    lower_price, lower_strength = best_zone(below, price, False)
    return {
        'nearest_above_price': upper_price,
        'nearest_above_strength': upper_strength,
        'nearest_below_price': lower_price,
        'nearest_below_strength': lower_strength,
        'recent_liquidation_notional_usd': round(recent_notional, 2),
        'recent_liquidation_events': recent_count,
        'event_window_minutes': WINDOW_MINUTES,
    }


def _read_binance_json(path: str, params: Dict[str, Any]) -> Any:
    r = requests.get(f'{BINANCE_REST}{path}', params=params, timeout=6)
    r.raise_for_status()
    return r.json()


def _read_bybit_json(path: str, params: Dict[str, Any]) -> Any:
    r = requests.get(f'{BYBIT_REST}{path}', params=params, timeout=6)
    r.raise_for_status()
    return r.json()


def _poll_metrics_loop() -> None:
    while True:
        try:
            premium = _read_binance_json('/fapi/v1/premiumIndex', {'symbol': SYMBOL})
            funding = _safe_float(premium.get('lastFundingRate'))
            mark = _safe_float(premium.get('markPrice'))
            oi_now = _read_binance_json('/fapi/v1/openInterest', {'symbol': SYMBOL})
            oi_current = _safe_float(oi_now.get('openInterest'))
            oi_hist = _read_binance_json('/futures/data/openInterestHist', {'symbol': SYMBOL, 'period': '5m', 'limit': 2})
            oi_prev = oi_current
            if isinstance(oi_hist, list) and len(oi_hist) >= 2:
                oi_prev = _safe_float(oi_hist[-2].get('sumOpenInterest') or oi_hist[-2].get('sumOpenInterestValue') or oi_current)
            _update_metrics('binance', funding_rate=funding, mark_price=mark, oi_current=oi_current, oi_prev=oi_prev)
        except Exception as exc:
            logger.exception('exchange_liquidity.binance_metrics_failed')
            _set_error('binance_metrics', f'{type(exc).__name__}: {exc}')

        try:
            bybit_oi = _read_bybit_json('/v5/market/open-interest', {'category': 'linear', 'symbol': SYMBOL, 'intervalTime': '5min', 'limit': 2})
            result = bybit_oi.get('result', {}) if isinstance(bybit_oi, dict) else {}
            lst = result.get('list') or []
            oi_current = 0.0
            oi_prev = 0.0
            if lst:
                oi_current = _safe_float(lst[0].get('openInterest'))
                oi_prev = _safe_float((lst[1] if len(lst) > 1 else lst[0]).get('openInterest'))
            fr = _read_bybit_json('/v5/market/funding/history', {'category': 'linear', 'symbol': SYMBOL, 'limit': 1})
            fr_list = ((fr.get('result') or {}).get('list') or []) if isinstance(fr, dict) else []
            funding = _safe_float((fr_list[0] if fr_list else {}).get('fundingRate'))
            _update_metrics('bybit', funding_rate=funding, oi_current=oi_current, oi_prev=oi_prev)
        except Exception as exc:
            logger.exception('exchange_liquidity.bybit_metrics_failed')
            _set_error('bybit_metrics', f'{type(exc).__name__}: {exc}')

        time.sleep(POLL_SEC)


def _run_binance_ws() -> None:
    if websocket is None:
        return
    url = f'{BINANCE_WS}/{SYMBOL.lower()}@forceOrder'
    while True:
        try:
            ws = websocket.create_connection(url, timeout=20)
            while True:
                raw = ws.recv()
                data = json.loads(raw)
                order = data.get('o') if isinstance(data, dict) else {}
                if not isinstance(order, dict):
                    continue
                price = _safe_float(order.get('ap') or order.get('p'))
                qty = _safe_float(order.get('q') or order.get('l'))
                notional = price * qty
                side = str(order.get('S') or '').upper()
                ts = _safe_int(order.get('T') or data.get('E') or _now_ms())
                _append_event('binance', order.get('s') or SYMBOL, side, price, qty, notional, ts)
        except Exception as exc:
            _log_ws_issue_once('exchange_liquidity.binance_ws_failed', exc)
            _mark_ws_connected('binance', False)
            _set_error('binance_ws', f'{type(exc).__name__}: {exc}')
            time.sleep(5)


def _run_bybit_ws() -> None:
    if websocket is None:
        return
    while True:
        try:
            _inc_restart('bybit')
            ws = websocket.create_connection(BYBIT_WS, timeout=20)
            _mark_ws_connected('bybit', True)
            ws.send(json.dumps({'op': 'subscribe', 'args': [f'allLiquidation.{SYMBOL}']}))
            while True:
                raw = ws.recv()
                data = json.loads(raw)
                rows = data.get('data') if isinstance(data, dict) else None
                if not isinstance(rows, list):
                    continue
                for row in rows:
                    price = _safe_float(row.get('price') or row.get('p'))
                    qty = _safe_float(row.get('size') or row.get('qty') or row.get('v'))
                    notional = price * qty
                    side = str(row.get('side') or row.get('S') or '').upper()
                    ts = _safe_int(row.get('updatedTime') or row.get('T') or data.get('ts') or _now_ms())
                    _append_event('bybit', row.get('symbol') or SYMBOL, side, price, qty, notional, ts)
        except Exception as exc:
            _log_ws_issue_once('exchange_liquidity.bybit_ws_failed', exc)
            _mark_ws_connected('bybit', False)
            _set_error('bybit_ws', f'{type(exc).__name__}: {exc}')
            time.sleep(5)


def start_background_engine() -> None:
    global _STARTED
    with _LOCK:
        if _STARTED:
            return
        _STARTED = True
    state = _load_state()
    state.setdefault('status', {})['started_at'] = _iso_now()
    state['status']['source'] = 'exchange_real_liquidity'
    state['status']['ws_enabled'] = bool(websocket is not None)
    state['status'].setdefault('ws', {'binance': {'connected': False, 'restart_count': 0}, 'bybit': {'connected': False, 'restart_count': 0}})
    _save_state(state)

    threads = [
        threading.Thread(target=_poll_metrics_loop, name='liq_metrics', daemon=True),
    ]
    if websocket is not None:
        threads.extend([
            threading.Thread(target=_run_binance_ws, name='liq_binance_ws', daemon=True),
            threading.Thread(target=_run_bybit_ws, name='liq_bybit_ws', daemon=True),
        ])
    for t in threads:
        t.start()


def _calc_health(status: Dict[str, Any]) -> Dict[str, Any]:
    now_ms = _now_ms()
    last_event_at = status.get('last_event_at')
    ws = status.get('ws') if isinstance(status.get('ws'), dict) else {}
    stale_sec = 999999
    freshest_ts = 0
    for exchange in ('binance', 'bybit'):
        row = ws.get(exchange) if isinstance(ws.get(exchange), dict) else {}
        freshest_ts = max(freshest_ts, _safe_int(row.get('last_message_ts')) )
    if freshest_ts > 0:
        stale_sec = max(0, int((now_ms - freshest_ts) / 1000))
    health = 'DEGRADED'
    if freshest_ts > 0 and stale_sec <= max(POLL_SEC * 3, 180):
        health = 'LIVE'
    elif status.get('last_metrics_at'):
        health = 'METRICS_ONLY'
    elif not status.get('ws_enabled'):
        health = 'WS_DISABLED'

    summary = 'feed деградирован'
    if health == 'LIVE':
        summary = f'live feed OK, stale={stale_sec}s'
    elif health == 'METRICS_ONLY':
        summary = 'есть OI/funding, но нет свежих liquidation events'
    elif health == 'WS_DISABLED':
        summary = 'websocket-client не установлен, только REST-режим'

    return {
        'health': health,
        'stale_seconds': stale_sec,
        'summary': summary,
    }


def get_exchange_liquidity_context(symbol: str = SYMBOL, price: float = 0.0) -> Dict[str, Any]:
    state = _load_state()
    events = _trim_events(list(state.get('events') or []))
    metrics = state.get('metrics') if isinstance(state.get('metrics'), dict) else {}
    price = _safe_float(price)
    agg = _aggregate_events(events, price)

    binance = metrics.get('binance') if isinstance(metrics.get('binance'), dict) else {}
    bybit = metrics.get('bybit') if isinstance(metrics.get('bybit'), dict) else {}

    funding_values = [_safe_float(binance.get('funding_rate')), _safe_float(bybit.get('funding_rate'))]
    funding_values = [v for v in funding_values if v != 0.0]
    funding_rate = sum(funding_values) / len(funding_values) if funding_values else 0.0

    oi_candidates = [_safe_float(binance.get('oi_current')), _safe_float(bybit.get('oi_current'))]
    oi_prev_candidates = [_safe_float(binance.get('oi_prev')), _safe_float(bybit.get('oi_prev'))]
    oi_close = sum(v for v in oi_candidates if v > 0)
    oi_prev_close = sum(v for v in oi_prev_candidates if v > 0)
    if oi_close <= 0:
        oi_close = max(oi_candidates + [0.0])
    if oi_prev_close <= 0:
        oi_prev_close = max(oi_prev_candidates + [oi_close])

    oi_delta = oi_close - (oi_prev_close or oi_close)
    oi_delta_pct = (oi_delta / max(abs(oi_prev_close), 1e-9) * 100.0) if oi_prev_close else 0.0
    funding_state = 'NEUTRAL'
    if funding_rate >= 0.0008:
        funding_state = 'CROWDED_LONG'
    elif funding_rate > 0:
        funding_state = 'POSITIVE'
    elif funding_rate <= -0.0008:
        funding_state = 'CROWDED_SHORT'
    elif funding_rate < 0:
        funding_state = 'NEGATIVE'

    price_oi_regime = 'NEUTRAL'
    if price > 0 and agg.get('nearest_above_price') and agg.get('nearest_below_price'):
        if oi_delta_pct > 0.15:
            price_oi_regime = 'UP_OI_UP' if agg.get('nearest_above_strength', 0.0) >= agg.get('nearest_below_strength', 0.0) else 'DOWN_OI_UP'
        elif oi_delta_pct < -0.15:
            price_oi_regime = 'UP_OI_DOWN' if agg.get('nearest_above_strength', 0.0) >= agg.get('nearest_below_strength', 0.0) else 'DOWN_OI_DOWN'
    elif oi_delta_pct > 0.15:
        price_oi_regime = 'OI_BUILDUP'
    elif oi_delta_pct < -0.15:
        price_oi_regime = 'OI_UNWIND'

    recent_cutoff = _now_ms() - 5 * 60 * 1000
    burst_up_notional = 0.0
    burst_down_notional = 0.0
    burst_up_count = 0
    burst_down_count = 0
    for event in events:
        if _safe_int(event.get('ts')) < recent_cutoff:
            continue
        n = abs(_safe_float(event.get('notional')))
        p = _safe_float(event.get('price'))
        if p >= price:
            burst_up_notional += n
            burst_up_count += 1
        else:
            burst_down_notional += n
            burst_down_count += 1

    event_burst_up = burst_up_count >= 2 or burst_up_notional >= 150000
    event_burst_down = burst_down_count >= 2 or burst_down_notional >= 150000
    liq_side_pressure = 'NEUTRAL'
    if event_burst_up or agg.get('nearest_above_strength', 0.0) > agg.get('nearest_below_strength', 0.0) * 1.25:
        liq_side_pressure = 'UP'
    elif event_burst_down or agg.get('nearest_below_strength', 0.0) > agg.get('nearest_above_strength', 0.0) * 1.25:
        liq_side_pressure = 'DOWN'

    crowding = 'NONE'
    if funding_state in {'POSITIVE', 'CROWDED_LONG'}:
        crowding = 'LONG'
    elif funding_state in {'NEGATIVE', 'CROWDED_SHORT'}:
        crowding = 'SHORT'

    squeeze_risk = 'LOW'
    if (event_burst_up or event_burst_down) and abs(oi_delta_pct) >= 0.15:
        squeeze_risk = 'HIGH'
    elif event_burst_up or event_burst_down or abs(oi_delta_pct) >= 0.15:
        squeeze_risk = 'MEDIUM'

    ok = bool(events or oi_close > 0 or funding_rate != 0.0)
    status = state.get('status') or {}
    health = _calc_health(status if isinstance(status, dict) else {})
    fallback_active = bool(agg.get('nearest_above_price') or agg.get('nearest_below_price') or status.get('last_metrics_at')) and health.get('health') in {'DEGRADED', 'METRICS_ONLY', 'LIVE'}
    out = {
        'ok': ok,
        'symbol': symbol,
        'source': 'exchange_real_liquidity',
        'events_count': len(events),
        'funding_rate': funding_rate,
        'funding_state': funding_state,
        'oi_close': oi_close,
        'oi_prev_close': oi_prev_close or oi_close,
        'oi_delta': oi_delta,
        'oi_delta_pct': round(oi_delta_pct, 4),
        'price_oi_regime': price_oi_regime,
        'last_event_at': (state.get('status') or {}).get('last_event_at'),
        'status': status,
        'feed_health': health.get('health'),
        'feed_stale_seconds': health.get('stale_seconds'),
        'feed_summary': health.get('summary'),
        'fallback_active': fallback_active,
        'fallback_mode': 'SNAPSHOT' if fallback_active and health.get('health') != 'LIVE' else 'OFF',
        'event_burst_up': event_burst_up,
        'event_burst_down': event_burst_down,
        'event_burst_up_notional_usd': round(burst_up_notional, 2),
        'event_burst_down_notional_usd': round(burst_down_notional, 2),
        'event_burst_up_count': burst_up_count,
        'event_burst_down_count': burst_down_count,
        'liq_side_pressure': liq_side_pressure,
        'crowding': crowding,
        'squeeze_risk': squeeze_risk,
        'recent_cluster_above_price': agg.get('nearest_above_price'),
        'recent_cluster_above_strength': agg.get('nearest_above_strength'),
        'recent_cluster_below_price': agg.get('nearest_below_price'),
        'recent_cluster_below_strength': agg.get('nearest_below_strength'),
        **agg,
    }
    out['heatmap_ready'] = bool(out.get('nearest_above_price') or out.get('nearest_below_price'))
    if out.get('nearest_above_price'):
        out['upper_cluster_price'] = out.get('nearest_above_price')
    if out.get('nearest_below_price'):
        out['lower_cluster_price'] = out.get('nearest_below_price')
    if fallback_active and not out.get('ok'):
        out['ok'] = True
        out['source'] = 'exchange_real_liquidity_fallback'
        out['reason'] = 'using_last_valid_snapshot'
    elif not ok:
        out['reason'] = 'no_exchange_data_yet'
    return out
